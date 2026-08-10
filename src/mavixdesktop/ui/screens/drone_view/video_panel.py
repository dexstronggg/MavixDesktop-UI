"""Video panel with overlay control buttons."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from mavixdesktop.ui.screens.help_dialog import HelpDialog
from mavixdesktop.ui.screens.utils import (
    build_stats_scroll,
    fit_stats_scroll,
    overlay_btn,
    overlay_icon_btn,
    stats_label_qss,
    stats_panel_width,
)
from mavixdesktop.ui.style import theme


class VideoPanel(QWidget):
    def __init__(
        self,
        on_prev: Callable[[], object],
        on_next: Callable[[], object],
        on_back: Callable[[], None],
        on_joy: Callable[[], None],
        on_takeoff: Callable[[], None],
    ) -> None:
        super().__init__()

        self.video = QLabel(self)
        self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video.setStyleSheet(f'background: {theme.BG_VIDEO};')

        self.__build_controls(on_prev, on_next, on_back, on_joy, on_takeoff)
        self.__build_battery_overlay()
        self.__build_quality_overlays()
        self.__build_labels()
        self.__build_calibration_overlay()
        self.__build_error_overlay()
        self.__reposition(800, 600)

    def __build_controls(
        self,
        on_prev: Callable[[], object],
        on_next: Callable[[], object],
        on_back: Callable[[], None],
        on_joy: Callable[[], None],
        on_takeoff: Callable[[], None],
    ) -> None:
        self.back_btn = overlay_icon_btn('arrow_back.svg', self)
        self.back_btn.setToolTip('Назад к списку дронов')
        self.back_btn.clicked.connect(on_back)

        self.joy_btn = overlay_icon_btn('joystick.svg', self)
        self.joy_btn.setToolTip('Настройка джойстика')
        self.joy_btn.clicked.connect(on_joy)

        self.help_btn = overlay_btn('i', self, size=theme.OVERLAY_BTN_CORNER_ICON)
        self.help_btn.setToolTip('Горячие клавиши и что означают показатели')
        self.help_btn.clicked.connect(self.toggle_help)

        s = theme.OVERLAY_BTN_SIDE
        self.prev_btn = overlay_btn('◀', self, size=s)
        self.prev_btn.setToolTip('Предыдущая камера')
        self.prev_btn.clicked.connect(on_prev)

        self.next_btn = overlay_btn('▶', self, size=s)
        self.next_btn.setToolTip('Следующая камера')
        self.next_btn.clicked.connect(on_next)

        self.takeoff_btn = QPushButton('✈  Взлёт', self)
        self.takeoff_btn.setFixedSize(100, 36)
        self.takeoff_btn.setEnabled(False)
        self.takeoff_btn.clicked.connect(on_takeoff)
        self.__style_takeoff(False)

    def __build_battery_overlay(self) -> None:
        self.battery_overlay = QLabel('—', self)
        self.battery_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.battery_overlay.setFixedSize(90, 26)
        self.battery_overlay.setStyleSheet(f"""
            QLabel {{
                background: rgba(0,0,0,0.45);
                color: rgba(255,255,255,0.85);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: {theme.RADIUS_SM}px;
                font-size: {theme.FONT_SIZE_SM - 2}px;
                font-family: monospace;
                padding: 0 8px;
            }}
        """)
        self.battery_overlay.hide()

    def __build_quality_overlays(self) -> None:
        self.quality_overlay = QLabel('—', self)
        self.quality_overlay.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        self.quality_overlay.setStyleSheet(self.__quality_qss(theme.TEXT_MUTED))
        self.quality_overlay.adjustSize()

        self.stale_overlay = QLabel('', self)
        self.stale_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stale_overlay.setStyleSheet(f"""
            QLabel {{
                background: rgba(0,0,0,0.60);
                color: {theme.STATUS_ERROR};
                border: 1px solid {theme.STATUS_ERROR};
                border-radius: {theme.RADIUS_MD}px;
                font-size: {theme.FONT_SIZE_SM}px;
                font-weight: 600;
                padding: 6px 14px;
            }}
        """)
        self.stale_overlay.hide()

        self.stats_panel = QLabel('')
        self.stats_panel.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self.stats_panel.setWordWrap(True)
        self.stats_panel.setStyleSheet(stats_label_qss())
        self.stats_scroll = build_stats_scroll(self.stats_panel, self)
        self.stats_scroll.hide()

    def toggle_help(self) -> None:
        HelpDialog(self.window()).exec()

    @staticmethod
    def __quality_qss(color: str) -> str:
        return f"""
            QLabel {{
                background: rgba(0,0,0,0.45);
                color: {color};
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: {theme.RADIUS_SM}px;
                font-size: {theme.FONT_SIZE_SM - 2}px;
                font-family: monospace;
                padding: 3px 10px;
            }}
        """

    def update_quality(self, text: str, color: str) -> None:
        self.quality_overlay.setStyleSheet(self.__quality_qss(color))
        self.quality_overlay.setText(text)
        self.quality_overlay.adjustSize()
        self.__reposition(self.width(), self.height())

    def update_stale(self, seconds: float) -> None:
        if seconds <= 0:
            self.stale_overlay.hide()
            return
        self.stale_overlay.setText(f'⚠  нет свежего кадра {seconds:.1f} с')
        self.stale_overlay.adjustSize()
        self.stale_overlay.show()
        self.stale_overlay.raise_()
        self.__reposition(self.width(), self.height())

    def set_stats_text(self, text: str) -> None:
        self.stats_panel.setText(text)
        self.__reposition(self.width(), self.height())

    def toggle_stats_panel(self) -> bool:
        visible = self.stats_scroll.isHidden()
        self.stats_scroll.setVisible(visible)
        if visible:
            self.stats_scroll.raise_()
        return visible

    def __build_calibration_overlay(self) -> None:
        self.calib_overlay = QFrame(self)
        self.calib_overlay.setStyleSheet(f"""
            QFrame {{
                background: rgba(0,0,0,0.78);
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: {theme.RADIUS_MD}px;
            }}
        """)
        layout = QVBoxLayout(self.calib_overlay)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)

        label = QLabel(
            'Идёт калибровка камеры…\nЭто может занять продолжительное время',
            self.calib_overlay,
        )
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(
            f'color: {theme.TEXT_PRIMARY};'
            f' font-size: {theme.FONT_SIZE_BASE}px;'
            ' background: transparent; border: none;'
        )
        layout.addWidget(label)

        spinner = QProgressBar(self.calib_overlay)
        spinner.setRange(0, 0)
        spinner.setTextVisible(False)
        spinner.setFixedHeight(6)
        spinner.setStyleSheet(f"""
            QProgressBar {{
                background: rgba(255,255,255,0.10);
                border: none;
                border-radius: 3px;
            }}
            QProgressBar::chunk {{
                background: {theme.ACCENT};
                border-radius: 3px;
            }}
        """)
        layout.addWidget(spinner)

        self.calib_overlay.setFixedSize(520, 140)
        self.calib_overlay.hide()

    def __build_error_overlay(self) -> None:
        self.error_overlay = QLabel('', self)
        self.error_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.error_overlay.setWordWrap(True)
        self.error_overlay.setStyleSheet(f"""
            QLabel {{
                background: rgba(0,0,0,0.82);
                color: {theme.STATUS_ERROR};
                border: 1px solid {theme.STATUS_ERROR};
                border-radius: {theme.RADIUS_MD}px;
                font-size: {theme.FONT_SIZE_BASE}px;
                font-weight: 600;
                padding: 22px 28px;
            }}
        """)
        self.error_overlay.setFixedSize(520, 100)
        self.error_overlay.hide()

    def show_error_banner(self, text: str) -> None:
        self.error_overlay.setText(text)
        self.error_overlay.show()
        self.error_overlay.raise_()
        self.__reposition(self.width(), self.height())

    def hide_error_banner(self) -> None:
        self.error_overlay.hide()

    def __build_labels(self) -> None:
        self.warn_lbl = QLabel('⚠  Смена настроек во время полёта недоступна', self)
        self.warn_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.warn_lbl.setStyleSheet(f"""
            QLabel {{
                background: rgba(0,0,0,0.50);
                color: {theme.WARNING};
                font-size: {theme.FONT_SIZE_SM - 1}px;
                border: none;
                padding: 4px 12px;
                border-radius: {theme.RADIUS_MD}px;
            }}
        """)
        self.warn_lbl.adjustSize()

        self.hint_lbl = QLabel('Клавиши  ←  →  для переключения камер', self)
        self.hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_lbl.setStyleSheet(
            'color: rgba(255,255,255,0.40);'
            f'font-size: {theme.FONT_SIZE_SM - 2}px;'
            'background: transparent;'
        )

    def __style_takeoff(self, enabled: bool) -> None:
        if enabled:
            self.takeoff_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(42,130,218,0.75);
                    color: {theme.TEXT_PRIMARY};
                    border: none;
                    border-radius: {theme.RADIUS_MD}px;
                    font-size: {theme.FONT_SIZE_SM}px;
                    font-weight: 600;
                }}
                QPushButton:hover {{ background: rgba(61,154,232,0.90); }}
                QPushButton:pressed {{ background: rgba(31,106,176,0.90); }}
            """)
        else:
            self.takeoff_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(0,0,0,0.50);
                    color: rgba(255,255,255,0.25);
                    border: none;
                    border-radius: {theme.RADIUS_MD}px;
                    font-size: {theme.FONT_SIZE_SM}px;
                    font-weight: 600;
                }}
            """)

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.__reposition(event.size().width(), event.size().height())
        super().resizeEvent(event)

    def __reposition(self, w: int, h: int) -> None:
        self.video.setGeometry(0, 0, w, h)

        c = theme.OVERLAY_BTN_CORNER
        s = theme.OVERLAY_BTN_SIDE

        self.back_btn.move(16, 16)
        self.joy_btn.move(w - c - 16, 16)
        self.help_btn.move(
            w - c - 16 - self.help_btn.width() - 12,
            16 + (c - self.help_btn.height()) // 2,
        )
        self.warn_lbl.adjustSize()
        self.warn_lbl.move((w - self.warn_lbl.width()) // 2, 16)

        self.prev_btn.move(16, (h - s) // 2)
        self.next_btn.move(w - s - 16, (h - s) // 2)

        self.takeoff_btn.move(
            (w - self.takeoff_btn.width()) // 2, h - self.takeoff_btn.height() - 56
        )

        self.battery_overlay.move(
            w - self.battery_overlay.width() - 16,
            h - self.battery_overlay.height() - 16,
        )

        self.calib_overlay.move(
            (w - self.calib_overlay.width()) // 2,
            (h - self.calib_overlay.height()) // 2,
        )

        self.error_overlay.move(
            (w - self.error_overlay.width()) // 2,
            (h - self.error_overlay.height()) // 2,
        )

        self.quality_overlay.move(16, h - self.quality_overlay.height() - 16)
        self.stale_overlay.move((w - self.stale_overlay.width()) // 2, 64)
        top = 16 + theme.OVERLAY_BTN_CORNER + 12
        panel_w = stats_panel_width(self)
        free_h = max(0, h - top - self.quality_overlay.height() - 32)
        fit_stats_scroll(self.stats_scroll, self.stats_panel, 16, top, panel_w, free_h)

        hw = min(400, w)
        self.hint_lbl.setFixedWidth(hw)
        self.hint_lbl.move((w - hw) // 2, h - 24)

    def show_frame(self, img: np.ndarray[Any, Any]) -> None:
        h, w, ch = img.shape
        qimg = QImage(img.data, w, h, ch * w, QImage.Format.Format_BGR888)
        self.video.setPixmap(
            QPixmap.fromImage(qimg).scaled(
                self.video.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        if self.calib_overlay.isVisible():
            self.calib_overlay.hide()

    def set_calibration_visible(self, visible: bool) -> None:
        self.calib_overlay.setVisible(visible)
        if visible:
            self.calib_overlay.raise_()

    def update_battery_overlay(self, percent: int, voltage: float) -> None:
        if voltage <= 0:
            return
        self.battery_overlay.setText(f'{voltage:.1f} V')
        if not self.battery_overlay.isVisible():
            self.battery_overlay.show()

    def set_fc(self, fc_type: str) -> None:
        if fc_type in ('crsf', 'mavlink'):
            self.takeoff_btn.show()
            self.takeoff_btn.setEnabled(True)
            self.__style_takeoff(True)
        else:
            self.takeoff_btn.show()
            self.takeoff_btn.setEnabled(False)
            self.__style_takeoff(False)
        self.__reposition(self.width(), self.height())
