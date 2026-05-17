"""Demo connection manager — заглушка для тестирования UI без сервера.

Реализует тот же публичный интерфейс, что и ConnectionManager, но никуда
не ходит. Используется при запуске с флагом ``--demo`` или при автофолбэке,
когда health-check реального сервера не прошёл.

Поведение:
  * ``login`` — принимает любой email/пароль, через 150 мс эмитит
    ``login_succeeded``;
  * ``resume`` — всегда False (форсируем экран входа);
  * ``request_drone_list`` — эмитит фиксированный набор из 3 мок-дронов с
    разными статусами (online / offline / connecting);
  * ``select_drone`` — заглушка, видеопотока в демо-режиме нет;
  * остальные методы — no-op.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer

from mavixdesktop.core.logger import logger


_MOCK_DRONES = [
    {'drone_id': 'demo-online-0001', 'online': True},
    {'drone_id': 'demo-offline-0002', 'online': False},
    # Legacy-формат — статус 'connecting' будет показан как есть в карточке
    # (DroneCard рендерит этот status, если поля 'online' нет).
    {'session_id': 'demo-connecting-0003', 'status': 'connecting'},
]


class DemoConnectionManager:
    """Drop-in для ConnectionManager в демо-режиме."""

    def __init__(self, bridge) -> None:
        self._bridge = bridge
        logger.info('[demo] connection manager activated; no real server calls')

    @property
    def coordinator(self):
        return None

    def set_track_callback(self, on_track, on_reset=None) -> None:
        # В демо-режиме видеопотока нет — track-колбэки не нужны.
        return None

    def login(self, email: str, password: str) -> None:
        logger.info('[demo] accepting login email=%s (any password ok)', email)
        # Небольшая задержка, чтобы login_page успел показать spinner и
        # переход выглядел как настоящий.
        QTimer.singleShot(150, self._bridge.login_succeeded.emit)

    def resume(self) -> bool:
        # В демо-режиме всегда начинаем с экрана входа — так нагляднее.
        return False

    def logout(self) -> None:
        return None

    def request_drone_list(self) -> None:
        # Имитируем сетевую задержку (~80 мс), чтобы UI не моргал.
        QTimer.singleShot(
            80, lambda: self._bridge.client_list_updated.emit(list(_MOCK_DRONES))
        )

    def select_drone(self, drone_id: str) -> None:
        # Видеопотока нет; считаем что connect провалился — это переключит
        # пользователя обратно на список с понятным баннером.
        logger.info('[demo] select_drone(%s) — нет реального WebRTC', drone_id)
        QTimer.singleShot(100, lambda: self._bridge.connect_failed.emit(drone_id))

    def disconnect_drone(self) -> None:
        return None

    def send_joystick_frame(self, frame: bytes) -> None:
        return None
