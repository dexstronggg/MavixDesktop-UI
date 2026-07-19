"""Demo connection manager — stub for UI testing without a server."""
from __future__ import annotations

from PySide6.QtCore import QTimer

from mavixdesktop.core.logger import logger

_MOCK_DRONES = [
    {'drone_id': 'demo-online-0001', 'online': True},
    {'drone_id': 'demo-offline-0002', 'online': False},
    {'session_id': 'demo-connecting-0003', 'status': 'connecting'},
]

_MOCK_CAMERAS = [
    {
        'device_index': 0,
        'param_index': 0,
        'bitrate_kbs': 2500,
        'params': [
            {'width': 1920, 'height': 1080, 'fps': 30},
            {'width': 1920, 'height': 1080, 'fps': 60},
            {'width': 1280, 'height': 720,  'fps': 30},
            {'width': 1280, 'height': 720,  'fps': 60},
            {'width': 640,  'height': 480,  'fps': 30},
        ],
    },
]

_MOCK_FC = ('crsf', 'Демо-FC (Betaflight)')


class DemoConnectionManager:
    def __init__(self, bridge) -> None:
        self._bridge = bridge
        self._loop = None
        logger.info('[demo] connection manager активирован; реальных вызовов сервера нет')

    @property
    def coordinator(self):
        return None

    def delete_drone(self, drone_id: str, on_done=None) -> None:
        logger.info('[demo] delete_drone(%s) — no-op', drone_id)
        if on_done is not None:
            on_done(None)

    def set_track_callback(self, on_track, on_reset=None) -> None:
        return None

    def login(self, email: str, password: str) -> None:
        logger.info('[demo] принимаю вход email=%s (любой пароль подходит)', email)
        QTimer.singleShot(150, self._bridge.login_succeeded.emit)

    def resume(self) -> bool:
        return False

    def logout(self) -> None:
        return None

    def request_drone_list(self) -> None:
        QTimer.singleShot(
            80, lambda: self._bridge.client_list_updated.emit(list(_MOCK_DRONES))
        )

    def select_drone(self, drone_id: str) -> None:
        logger.info('[demo] select_drone(%s) — эмитирую mock-камеры и FC', drone_id)
        QTimer.singleShot(120, lambda: self._bridge.config_received.emit(list(_MOCK_CAMERAS)))
        QTimer.singleShot(140, lambda: self._bridge.fc_info_received.emit(*_MOCK_FC))

    def disconnect_drone(self) -> None:
        return None

    def send_joystick_frame(self, frame: bytes) -> None:
        return None

    def request_password_reset(self, email: str) -> None:
        logger.info('[demo] запрошено восстановление пароля для %s (no-op)', email)
