"""UI-адаптер над mavixdesktop.coordinator.SessionCoordinator.

Coordinator крутит asyncio event loop в фоновом потоке. Этот адаптер:
  - поднимает loop при создании;
  - логинит пользователя (или восстанавливает из keyring) и запускает
    coordinator;
  - пробрасывает события coordinator в сигналы Qt Bridge;
  - предоставляет синхронные UI-методы, которые планируют корутины на
    фоновый loop.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable

from PySide6.QtCore import QTimer

from mavixdesktop.coordinator import SessionCoordinator
from mavixdesktop.core.config import settings
from mavixdesktop.core.logger import logger
from mavixdesktop.server import token_store
from mavixdesktop.server.api import ApiError, ApiSession
from mavixdesktop.server.signal_client import SignalClient


class ConnectionManager:
    def __init__(self, bridge) -> None:
        self._bridge = bridge
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._api: ApiSession | None = None
        self._signal: SignalClient | None = None
        self._coord: SessionCoordinator | None = None
        self._coord_task: asyncio.Task | None = None
        self._track_callback = None
        self._reset_callback = None

    # --- Публичный API для App ---

    @property
    def coordinator(self) -> SessionCoordinator | None:
        return self._coord

    def set_track_callback(self, on_track, on_reset=None) -> None:
        self._track_callback = on_track
        self._reset_callback = on_reset
        if self._coord is not None:
            self._coord.on_track = on_track

    def login(self, email: str, password: str) -> None:
        """Запускает вход в фоновом loop; UI не блокируется."""
        self._ensure_loop_started()
        assert self._loop is not None
        asyncio.run_coroutine_threadsafe(
            self._login_and_run(email, password), self._loop,
        )

    def resume(self) -> bool:
        """Пытается перезапуститься по сохранённому refresh-токену.
        Возвращает True, если токен найден."""
        email, refresh = token_store.load()
        if not refresh:
            return False
        self._ensure_loop_started()
        assert self._loop is not None
        asyncio.run_coroutine_threadsafe(
            self._refresh_and_run(email or '', refresh), self._loop,
        )
        return True

    def logout(self) -> None:
        token_store.clear()
        if self._coord is not None:
            self._coord.stop()

    def request_drone_list(self) -> None:
        self._submit(self._coord.request_drone_list() if self._coord else None)

    def delete_drone(
        self,
        drone_id: str,
        on_done: Callable[[str | None], None] | None = None,
    ) -> None:
        """Асинхронно удаляет дрон через REST API. `on_done` вызывается в
        главном Qt-потоке с None при успехе или строкой-сообщением об
        ошибке при сбое (колбэк ставится в очередь через
        QTimer.singleShot)."""
        self._ensure_loop_started()
        assert self._loop is not None
        asyncio.run_coroutine_threadsafe(
            self._async_delete_drone(drone_id, on_done),
            self._loop,
        )

    async def _async_delete_drone(
        self,
        drone_id: str,
        on_done: Callable[[str | None], None] | None,
    ) -> None:
        try:
            if self._api is None or self._signal is None:
                raise ApiError('Нет активной сессии. Войдите в аккаунт.')
            token = getattr(self._signal, '_access_token', '')
            if not token:
                raise ApiError('Нет access-токена в активной сессии.')
            await self._api.delete_drone(drone_id, token)
            error: str | None = None
        except ApiError as exc:
            error = str(exc)
        except Exception as exc:
            logger.warning('[connection] не удалось удалить дрон: %s', exc)
            error = 'Не удалось удалить дрон. Попробуйте позже.'
        # В любом случае обновляем список, чтобы UI подхватил изменения.
        if self._coord is not None and error is None:
            try:
                await self._coord.request_drone_list()
            except Exception as exc:
                logger.warning('[connection] не удалось обновить список после удаления: %s', exc)
        if on_done is not None:
            QTimer.singleShot(0, lambda e=error: on_done(e))

    def select_drone(self, drone_id: str) -> None:
        if not drone_id:
            return
        self._submit(self._coord.request_connect(drone_id) if self._coord else None)

    def disconnect_drone(self) -> None:
        self._submit(self._coord.request_disconnect() if self._coord else None)

    def send_joystick_frame(self, frame: bytes) -> None:
        if self._coord is not None:
            self._coord.send_joystick_packet(frame)

    def request_password_reset(self, email: str) -> None:
        """Запрашивает восстановление пароля — fire-and-forget POST в API.

        Используется со страницы логина по клику «Забыли пароль?». UI
        показывает сообщение-подтверждение сразу, не дожидаясь ответа
        (сервер всё равно отвечает одинаково в любом случае,
        anti-enumeration). Если API-сессия ещё не создана (пользователь ни
        разу не пытался войти) — создаём временную.
        """
        self._ensure_loop_started()
        assert self._loop is not None
        asyncio.run_coroutine_threadsafe(self._async_password_reset(email), self._loop)

    async def _async_password_reset(self, email: str) -> None:
        api = self._api
        own_session = False
        if api is None:
            api = await ApiSession.create()
            own_session = True
        try:
            await api.password_reset_request(email)
            logger.info('[connection] запрошено восстановление пароля для %s', email)
        except ApiError as exc:
            logger.warning('[connection] восстановление пароля не удалось: %s', exc)
        except Exception as exc:
            logger.warning('[connection] восстановление пароля упало: %s', exc)
        finally:
            if own_session:
                await api.close()

    # --- Внутреннее ---

    def _ensure_loop_started(self) -> None:
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        logger.info('[connection] поток event loop запущен')

    async def _login_and_run(self, email: str, password: str) -> None:
        self._api = await ApiSession.create()
        try:
            result = await self._api.login(email, password)
            token_store.save(email, result['refresh_token'])
            await self._start_coordinator(result['access_token'], result['refresh_token'])
        except ApiError as exc:
            logger.error('[connection] вход не удался: %s', exc)
            await self._api.close()
            self._api = None
            self._emit_login_failed(str(exc))
            return
        except Exception as exc:
            logger.exception('[connection] вход упал: %s', exc)
            if self._api is not None:
                await self._api.close()
                self._api = None
            self._emit_login_failed('Не удалось подключиться к серверу')
            return
        self._emit_login_succeeded()

    async def _refresh_and_run(self, email: str, refresh_token: str) -> None:
        self._api = await ApiSession.create()
        try:
            result = await self._api.refresh(refresh_token)
            access = result.get('access_token', '')
            if not access:
                raise ApiError('refresh не вернул access-токен')
            await self._start_coordinator(access, refresh_token)
        except ApiError as exc:
            logger.warning('[connection] refresh не удался (%s); чистим сохранённый токен', exc)
            token_store.clear()
            await self._api.close()
            self._api = None
            self._emit_login_failed('Сессия истекла, войдите заново')
            return
        self._emit_login_succeeded()

    def _emit_login_succeeded(self) -> None:
        try:
            self._bridge.login_succeeded.emit()
        except Exception as exc:
            logger.warning('[connection] ошибка emit в bridge: %s', exc)

    def _emit_login_failed(self, reason: str) -> None:
        try:
            self._bridge.login_failed.emit(reason)
        except Exception as exc:
            logger.warning('[connection] ошибка emit в bridge: %s', exc)

    async def _start_coordinator(self, access: str, refresh: str) -> None:
        assert self._api is not None
        self._signal = SignalClient(url=settings.ws_url, access_token=access)
        self._coord = SessionCoordinator(
            signal_client=self._signal,
            api_session=self._api,
            refresh_token=refresh,
        )
        if self._track_callback is not None:
            self._coord.on_track = self._track_callback
        self._coord.on_drones_changed = self._emit_drones
        self._coord.on_fc_changed = self._emit_fc
        self._coord.on_cameras_received = self._emit_cameras
        self._coord.on_session_ended = self._on_session_ended
        self._coord.on_drone_offline = self._emit_drone_offline
        self._coord.on_connect_failed = self._emit_connect_failed
        self._coord.on_battery_changed = self._emit_battery
        self._coord_task = asyncio.create_task(self._coord.run())

    def _emit_drones(self, drones: list[dict]) -> None:
        try:
            self._bridge.client_list_updated.emit(drones)
        except Exception as exc:
            logger.warning('[connection] ошибка emit в bridge: %s', exc)

    def _emit_fc(self, kind: str, name: str) -> None:
        try:
            self._bridge.fc_info_received.emit(kind, name)
        except Exception as exc:
            logger.warning('[connection] ошибка emit в bridge: %s', exc)

    def _emit_cameras(self, cameras: list[dict]) -> None:
        try:
            self._bridge.config_received.emit(cameras)
        except Exception as exc:
            logger.warning('[connection] ошибка emit в bridge: %s', exc)

    def _on_session_ended(self) -> None:
        if self._reset_callback is not None:
            try:
                self._reset_callback()
            except Exception as exc:
                logger.warning('[connection] ошибка reset-колбэка: %s', exc)

    def _emit_drone_offline(self, drone_id: str) -> None:
        try:
            self._bridge.drone_went_offline.emit(drone_id)
        except Exception as exc:
            logger.warning('[connection] ошибка emit в bridge: %s', exc)

    def _emit_connect_failed(self, drone_id: str) -> None:
        try:
            self._bridge.connect_failed.emit(drone_id)
        except Exception as exc:
            logger.warning('[connection] ошибка emit в bridge: %s', exc)

    def _emit_battery(self, percent: int, voltage: float) -> None:
        try:
            self._bridge.battery_updated.emit(percent, voltage)
        except Exception as exc:
            logger.warning('[connection] ошибка emit в bridge: %s', exc)

    def _submit(self, coro: Awaitable | None) -> None:
        if coro is None or self._loop is None:
            return
        asyncio.run_coroutine_threadsafe(coro, self._loop)
