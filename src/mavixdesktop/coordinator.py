"""Top-level session coordinator for the desktop side."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import websockets

from mavixdesktop.core.backoff import ExponentialBackoff
from mavixdesktop.core.config import settings
from mavixdesktop.core.logger import logger
from mavixdesktop.fc.mavlink_relay import MavlinkRelay
from mavixdesktop.server.api import ApiError, ApiSession
from mavixdesktop.server.signal_client import SignalClient
from mavixdesktop.webrtc.manager import WebRTCManager

if TYPE_CHECKING:
    from aiortc import MediaStreamTrack


def _local_ice_servers() -> list[dict]:
    servers: list[dict] = []
    if settings.stun_server:
        servers.append({'urls': settings.stun_server})
    if settings.turn_server:
        entry: dict = {'urls': settings.turn_server}
        if settings.turn_username:
            entry['username'] = settings.turn_username
        if settings.turn_password:
            entry['credential'] = settings.turn_password
        servers.append(entry)
    return servers


class SessionCoordinator:
    def __init__(
        self,
        signal_client: SignalClient,
        api_session: ApiSession,
        refresh_token: str,
        backoff: ExponentialBackoff | None = None,
        on_track: Callable[[MediaStreamTrack], None] | None = None,
    ) -> None:
        self._signal_client = signal_client
        self._api = api_session
        self._refresh_token = refresh_token
        self._backoff = backoff if backoff is not None else ExponentialBackoff()
        self.on_track = on_track

        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._manager: WebRTCManager | None = None
        self._mavlink: MavlinkRelay | None = None
        self._target_drone_id: str | None = None
        self._fc_kind: str = 'none'
        self._latest_drones: list[dict] = []
        self._latest_cameras: list[dict] = []
        self._reconnect_drone_id: str | None = None
        self._connect_request_at: float | None = None
        self.on_drones_changed: Callable[[list[dict]], None] | None = None
        self.on_fc_changed: Callable[[str, str], None] | None = None
        self.on_cameras_received: Callable[[list[dict]], None] | None = None
        self.on_drone_offline: Callable[[str], None] | None = None
        self.on_connect_failed: Callable[[str], None] | None = None
        self.on_error: Callable[[str], None] | None = None
        self.on_session_ended: Callable[[], None] | None = None
        self.on_battery_changed: Callable[[int, float], None] | None = None

    @property
    def fc_kind(self) -> str:
        return self._fc_kind

    @property
    def drones(self) -> list[dict]:
        return list(self._latest_drones)

    @property
    def cameras(self) -> list[dict]:
        return list(self._latest_cameras)

    async def send_bitrate_update(self, updates: list[dict]) -> None:
        if self._manager is None or self._manager.channels is None:
            return
        config_ch = self._manager.channels.config
        if config_ch is None:
            return
        config_ch.send_json({'type': 'bitrate', 'updates': updates})

    async def send_params_update(self, updates: list[dict]) -> None:
        if self._manager is None or self._manager.channels is None:
            return
        config_ch = self._manager.channels.config
        if config_ch is None:
            return
        config_ch.send_json({'type': 'params', 'updates': updates})

    async def send_calibrate(self) -> None:
        if self._manager is None or self._manager.channels is None:
            return
        config_ch = self._manager.channels.config
        if config_ch is None:
            return
        config_ch.send_json({'type': 'calibrate'})

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        ice_servers = _local_ice_servers()
        if ice_servers:
            logger.info('[coord] используем %d ICE-сервер(ов) из локального конфига', len(ice_servers))
        else:
            ice_servers = await self._api.ice_servers()
            logger.info('[coord] локальный ICE-конфиг пуст — используем %d сервер(ов) из API', len(ice_servers))
        self._manager = WebRTCManager(send=self._signal_client.send, ice_servers=ice_servers)
        self._manager.on_track = self.on_track
        self._manager.on_channel_attached = lambda _label: self._wire_channels_to_fc()

        while not self._stop_event.is_set():
            connected = await self._signal_client.connect()
            if not connected:
                delay = self._backoff.next_delay()
                logger.info('[coord] не удалось подключиться к сигналингу, повтор через %.1fs', delay)
                await asyncio.sleep(delay)
                continue
            logger.info('[coord] подключились к сигнальному серверу')
            self._backoff.reset()
            try:
                await self._signal_client.listen(self._on_message)
            except websockets.exceptions.ConnectionClosed as exc:
                logger.warning('[coord] сигналинг закрыт: %s', exc)
            except Exception as exc:
                logger.error('[coord] ошибка listen: %s', exc)
            finally:
                await self._teardown_session()
                await self._signal_client.disconnect()
            await asyncio.sleep(self._backoff.next_delay())

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    async def request_connect(self, drone_id: str) -> None:
        self._target_drone_id = drone_id
        self._connect_request_at = time.monotonic()
        if self._manager is not None:
            self._manager.start_session(drone_id)
        await self._signal_client.send({'type': 'connect', 'drone_id': drone_id})

    async def request_disconnect(self) -> None:
        if self._target_drone_id is None:
            return
        await self._signal_client.send({
            'type': 'disconnect', 'drone_id': self._target_drone_id,
        })
        await self._teardown_session()

    async def request_drone_list(self) -> None:
        await self._signal_client.send({'type': 'list_drones'})

    def send_joystick_packet(self, frame: bytes) -> None:
        if self._manager is None or self._manager.channels is None:
            return
        packet = self._manager.channels.packet
        if packet is None:
            return
        packet.send_bytes(frame)

    async def _on_message(self, msg: dict) -> None:
        kind = msg.get('type')
        match kind:
            case 'drones':
                await self._handle_drones(msg.get('drones', []))
            case 'sdp':
                await self._handle_sdp(msg)
            case 'ice':
                await self._handle_ice(msg)
            case 'drone_disconnected':
                drone_id = msg.get('drone_id')
                is_connect_failure = (
                    isinstance(drone_id, str)
                    and self._target_drone_id == drone_id
                    and self._connect_request_at is not None
                    and (time.monotonic() - self._connect_request_at) < 10.0
                )
                self._connect_request_at = None
                if is_connect_failure:
                    logger.info('[coord] дрон %s отключился во время connect; без повтора', drone_id)
                    await self._teardown_session()
                    if self.on_connect_failed is not None:
                        try:
                            self.on_connect_failed(drone_id)
                        except Exception as exc:
                            logger.warning('[coord] ошибка on_connect_failed: %s', exc)
                    return
                logger.info('[coord] дрон отключился: %s; авто-переподключение при возврате', drone_id)
                if isinstance(drone_id, str) and self._target_drone_id == drone_id:
                    self._reconnect_drone_id = drone_id
                await self._teardown_session()
                if self._reconnect_drone_id is not None:
                    await self.request_drone_list()
            case 'auth_warning':
                await self._handle_auth_warning(msg)
            case 'auth_refreshed':
                await self._handle_auth_refreshed(msg)
            case 'shutdown':
                logger.info('[coord] уведомление о завершении работы сервера')
                await self._teardown_session()
            case 'ping':
                await self._signal_client.send({'type': 'pong'})
            case 'pong':
                pass
            case 'error':
                err = msg.get('message')
                logger.warning('[coord] ошибка сервера: %s', err)
                if self.on_error is not None and isinstance(err, str):
                    try:
                        self.on_error(err)
                    except Exception as exc:
                        logger.warning('[coord] ошибка колбэка on_error: %s', exc)
            case _:
                logger.debug('[coord] неизвестный тип сообщения: %s', kind)

    async def _handle_drones(self, drones: object) -> None:
        if not isinstance(drones, list):
            return
        self._latest_drones = drones
        if self.on_drones_changed is not None:
            try:
                self.on_drones_changed(self._latest_drones)
            except Exception as exc:
                logger.warning('[coord] ошибка on_drones_changed: %s', exc)
        manager_idle = self._manager is None or self._manager.active_drone_id is None
        if self._reconnect_drone_id is not None and manager_idle:
            entry = next(
                (d for d in drones if d.get('drone_id') == self._reconnect_drone_id and d.get('online')),
                None,
            )
            if entry is not None:
                target = self._reconnect_drone_id
                self._reconnect_drone_id = None
                logger.info('[coord] авто-переподключение к дрону %s', target)
                await self.request_connect(target)
            else:
                offline_id = self._reconnect_drone_id
                self._reconnect_drone_id = None
                logger.info('[coord] дрон %s подтверждённо offline; прекращаем переподключение', offline_id)
                if self.on_drone_offline is not None:
                    try:
                        self.on_drone_offline(offline_id)
                    except Exception as exc:
                        logger.warning('[coord] ошибка on_drone_offline: %s', exc)

    async def _handle_sdp(self, msg: dict) -> None:
        if self._manager is None:
            return
        drone_id = msg.get('drone_id')
        sdp = msg.get('sdp')
        if not isinstance(drone_id, str) or not isinstance(sdp, dict):
            return
        if sdp.get('type') == 'offer':
            self._connect_request_at = None
            await self._manager.handle_offer(drone_id, sdp)

    async def _handle_ice(self, msg: dict) -> None:
        if self._manager is None:
            return
        drone_id = msg.get('drone_id')
        cand = msg.get('candidate')
        if isinstance(drone_id, str) and isinstance(cand, dict):
            await self._manager.handle_ice(drone_id, cand)

    async def _handle_auth_refreshed(self, msg: dict) -> None:
        new_access = msg.get('access_token')
        if isinstance(new_access, str) and new_access:
            self._signal_client.update_access_token(new_access)
            logger.info('[coord] access-токен обновлён из server-side refresh')
        new_refresh = msg.get('refresh_token')
        if isinstance(new_refresh, str) and new_refresh and new_refresh != self._refresh_token:
            self._refresh_token = new_refresh
            try:
                from mavixdesktop.server import token_store
                email, _ = token_store.load()
                if email:
                    token_store.save(email, new_refresh)
            except Exception as exc:
                logger.warning('[coord] не удалось сохранить refresh-токен: %s', exc)

    async def _handle_auth_warning(self, msg: dict) -> None:
        logger.info('[coord] срок авторизации истекает через %ss, обновляем', msg.get('seconds_left'))
        try:
            new_access = await self._refresh_now()
        except ApiError as exc:
            logger.error('[coord] refresh не удался: %s', exc)
            return
        try:
            await self._signal_client.send({
                'type': 'refresh_auth',
                'refresh_token': self._refresh_token,
            })
        except Exception as exc:
            logger.warning('[coord] ошибка отправки refresh_auth: %s', exc)
        if new_access:
            self._signal_client.update_access_token(new_access)

    async def _refresh_now(self) -> str:
        result = await self._api.refresh(self._refresh_token)
        new_access = result.get('access_token', '')
        if isinstance(new_access, str) and new_access:
            return new_access
        raise ApiError('refresh не вернул access-токен')

    def _wire_channels_to_fc(self) -> None:
        if self._manager is None or self._manager.channels is None:
            return
        hub = self._manager.channels
        if hub.config is not None:
            hub.config.on_message = self._on_config_message
        if hub.packet is not None:
            hub.packet.on_packet = self._on_packet_from_drone

    async def _on_config_message_async(self, payload: dict | list) -> None:
        if not isinstance(payload, dict):
            return
        kind = payload.get('type')
        if kind == 'fc':
            await self._handle_fc_message(payload)
        elif kind == 'cameras':
            self._handle_cameras_message(payload)
        elif kind == 'battery':
            self._handle_battery_message(payload)
        elif kind == 'command_ack':
            self._handle_command_ack_message(payload)
        elif kind == 'fc_armed':
            armed = bool(payload.get('armed', False))
            cm = int(payload.get('custom_mode', 0))
            logger.info('[coord] FC armed=%s custom_mode=0x%08x', armed, cm)
        else:
            logger.debug('[coord] неизвестный тип config-канала: %s', kind)

    def _handle_battery_message(self, payload: dict) -> None:
        try:
            percent = int(payload.get('percent', 0))
            voltage = float(payload.get('voltage', 0.0))
        except (TypeError, ValueError):
            return
        if self.on_battery_changed is not None:
            try:
                self.on_battery_changed(percent, voltage)
            except Exception as exc:
                logger.warning('[coord] ошибка on_battery_changed: %s', exc)

    def _handle_command_ack_message(self, payload: dict) -> None:
        cmd = payload.get('command', '?')
        result = payload.get('result', '?')
        if result == 'ACCEPTED':
            logger.info('[coord] FC ack %s: %s', cmd, result)
        else:
            logger.warning('[coord] FC REJECT %s: %s', cmd, result)

    async def _handle_fc_message(self, payload: dict) -> None:
        kind = payload.get('kind') or 'none'
        name = payload.get('name') or ''
        if not isinstance(kind, str):
            kind = 'none'
        self._fc_kind = kind
        await self._apply_fc_kind(kind)
        if self.on_fc_changed is not None:
            try:
                self.on_fc_changed(kind, name if isinstance(name, str) else '')
            except Exception as exc:
                logger.warning('[coord] ошибка on_fc_changed: %s', exc)

    def _handle_cameras_message(self, payload: dict) -> None:
        cameras = payload.get('cameras')
        if not isinstance(cameras, list):
            return
        self._latest_cameras = cameras
        if self.on_cameras_received is not None:
            try:
                self.on_cameras_received(cameras)
            except Exception as exc:
                logger.warning('[coord] ошибка on_cameras_received: %s', exc)

    def _on_config_message(self, payload: dict | list) -> None:
        if self._loop is None:
            return
        self._loop.create_task(self._on_config_message_async(payload))

    async def _apply_fc_kind(self, kind: str) -> None:
        if kind == 'mavlink':
            if self._mavlink is None:
                self._mavlink = MavlinkRelay(
                    qgc_host=settings.qgc_host,
                    qgc_port=settings.qgc_port,
                    bind_port=settings.qgc_bind_port,
                )
                self._mavlink.set_packet_callback(self._on_qgc_packet)
                await self._mavlink.start()
        else:
            if self._mavlink is not None:
                await self._mavlink.stop()
                self._mavlink = None

    def _on_packet_from_drone(self, data: bytes) -> None:
        if self._fc_kind == 'mavlink' and self._mavlink is not None:
            self._mavlink.send_to_qgc(data)

    def _on_qgc_packet(self, data: bytes) -> None:
        if self._manager is None or self._manager.channels is None:
            return
        packet = self._manager.channels.packet
        if packet is None:
            return
        packet.send_bytes(data)

    async def _teardown_session(self) -> None:
        if self._manager is not None:
            await self._manager.close_async()
        if self._mavlink is not None:
            try:
                await self._mavlink.stop()
            except Exception as exc:
                logger.debug('[coord] ошибка остановки mavlink: %s', exc)
            self._mavlink = None
        self._target_drone_id = None
        self._fc_kind = 'none'
        if self.on_session_ended is not None:
            try:
                self.on_session_ended()
            except Exception as exc:
                logger.warning('[coord] ошибка on_session_ended: %s', exc)
