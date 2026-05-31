"""DroneViewPage — страница просмотра видео с борта.

Собирает VideoPanel (видео + overlay) и SettingsBar (нижняя панель)
в единый экран. Сама не содержит логики отображения — только
пробрасывает вызовы в нужный компонент.
"""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QVBoxLayout, QWidget

from mavixdesktop.ui.screens.drone_view.settings_bar import SettingsBar
from mavixdesktop.ui.screens.drone_view.video_panel import VideoPanel


class DroneViewPage(QWidget):
    """Страница с видеопотоком, настройками камеры и статусом FC."""

    def __init__(self, on_back: Callable[[], None], on_prev: Callable[[], None],
                 on_next: Callable[[], None], on_save: Callable[[], None],
                 on_joystick_cfg: Callable[[], None], on_takeoff: Callable[[], None],
                 on_calibrate: Callable[[], None]) -> None:
        super().__init__()
        self._on_prev = on_prev
        self._on_next = on_next
        self.setFocusPolicy(Qt.StrongFocus)

        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        self._video_panel = VideoPanel(
            on_prev=on_prev, on_next=on_next,
            on_back=on_back, on_joy=on_joystick_cfg,
            on_takeoff=on_takeoff,
        )
        self._settings_bar = SettingsBar(on_save=on_save, on_calibrate=on_calibrate)

        root.addWidget(self._video_panel, 1)
        root.addWidget(self._settings_bar)

        # Алиасы для обратной совместимости с App
        self.video = self._video_panel.video
        self.save_btn = self._settings_bar.save_btn
        self.calibrate_btn = self._settings_bar.calibrate_btn

    #### Клавиши ###########################################################################
    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key_Left:
            self._on_prev()
        elif event.key() == Qt.Key_Right:
            self._on_next()
        else:
            super().keyPressEvent(event)

    #### Публичный API (делегируем компонентам) ############################################
    def show_frame(self, img) -> None:
        """Показывает кадр видеопотока."""
        self._video_panel.show_frame(img)

    def update_fc_status(self, fc_type: str, fc_name: str) -> None:
        """Обновляет статус FC в панели настроек и кнопку взлёта."""
        self._settings_bar.update_fc_status(fc_type, fc_name)
        self._video_panel.set_fc(fc_type or 'none')

    def update_ping(self, rtt_ms: float) -> None:
        """Обновляет показание peer-to-peer пинга."""
        self._video_panel.update_ping_overlay(rtt_ms)

    def update_battery(self, percent: int, voltage: float) -> None:
        """Обновляет overlay батареи (CRSF BATTERY_SENSOR от борта)."""
        self._video_panel.update_battery_overlay(percent, voltage)

    def update_camera_settings(self, camera: dict) -> None:
        """Обновляет дропдауны настроек камеры."""
        self._settings_bar.update_camera(camera)

    def get_selected_params(self):
        """Возвращает (param_index, bitrate_kbs) по текущему выбору."""
        return self._settings_bar.get_selected_params()

    def set_calibration_visible(self, visible: bool) -> None:
        """Показывает/скрывает overlay «Идёт калибровка камеры…»."""
        self._video_panel.set_calibration_visible(visible)

    def show_error_banner(self, text: str) -> None:
        """Показывает красный баннер по центру (для ошибок установки сессии)."""
        self._video_panel.show_error_banner(text)

    def hide_error_banner(self) -> None:
        self._video_panel.hide_error_banner()
