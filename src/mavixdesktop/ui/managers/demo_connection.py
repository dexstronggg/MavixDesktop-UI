"""Demo connection manager — заглушка для тестирования UI без сервера.

Реализует тот же публичный интерфейс, что и ConnectionManager, но никуда
не ходит. Используется при запуске с флагом ``--demo`` или при автофолбэке,
когда health-check реального сервера не прошёл.

Поведение:
  * ``login`` — принимает любой email/пароль, через 150 мс эмитит
    ``login_succeeded``;
  * ``resume`` — всегда False (форсируем экран входа);
  * ``request_drone_list`` — эмитит фиксированный набор мок-дронов с
    разными статусами (online / offline / connecting);
  * ``select_drone`` — эмитит mock-конфиг камер и mock-FC info, чтобы UI
    drone-view был полностью заполнен данными (комбобоксы разрешения/FPS,
    кнопка взлёта активна) — это нужно для визуальной проверки дизайна;
    видеопотока всё равно нет, но overlay калибровки гасится сразу;
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


# Мок-конфиг одной камеры с разумным набором (resolution / FPS) комбинаций —
# достаточно чтобы заполнить дропдауны в SettingsBar и включить save-кнопку.
# Совпадает по форме с реальным config_received от board.
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

# Mock FC — CRSF чтобы кнопка «Взлёт» оказалась активной и видимой.
_MOCK_FC = ('crsf', 'Демо-FC (Betaflight)')


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
        # Видеопотока в демо нет, но всё что НЕ требует реального видео —
        # заполняем mock-данными: дропдауны камеры, кнопку взлёта, статус
        # FC. Это нужно для визуальной проверки дизайна drone-view экрана
        # (раньше тут эмитился connect_failed, и пользователя сразу
        # выкидывало обратно к списку с баннером «Камеры не найдены»).
        logger.info('[demo] select_drone(%s) — эмитирую mock cameras+FC', drone_id)
        QTimer.singleShot(120, lambda: self._bridge.config_received.emit(list(_MOCK_CAMERAS)))
        QTimer.singleShot(140, lambda: self._bridge.fc_info_received.emit(*_MOCK_FC))

    def disconnect_drone(self) -> None:
        return None

    def send_joystick_frame(self, frame: bytes) -> None:
        return None

    def request_password_reset(self, email: str) -> None:
        # В демо никуда не ходим — но логируем, чтобы UI-флоу был виден
        # в консоли при ручном тестировании.
        logger.info('[demo] password reset requested for %s (no-op)', email)
