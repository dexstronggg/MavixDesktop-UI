from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QCloseEvent,
    QImage,
    QKeyEvent,
    QPixmap,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import QLabel, QMessageBox, QWidget

from mavixdesktop.core.logger import logger
from mavixdesktop.fc.encoder import build_rc_frame
from mavixdesktop.joystick.input import JoystickInput
from mavixdesktop.ui.screens.help_dialog import HelpDialog
from mavixdesktop.ui.screens.utils import (
    build_stats_scroll,
    fit_stats_scroll,
    overlay_btn,
    overlay_icon_btn,
    stats_label_qss,
    stats_panel_width,
)
from mavixdesktop.ui.screens.widgets import StickWidget
from mavixdesktop.ui.style import theme

if TYPE_CHECKING:
    import numpy as np

_TAKEOFF_HELP = (
    'Перед взлётом:\n\n'
    '1. Опустите газ в ноль.\n'
    '2. Нажмите кнопку ARM на джойстике.\n'
    '3. Аккуратно добавьте газ.'
)

_PAD = 16
_STICK_SIZE = 120
_STICK_GAP = 20
_STICK_PAD = 24

_ARM_STYLE = f'font-weight: bold; font-size: 13px; color: {theme.STATUS_ARM};   background: transparent;'
_DISARM_STYLE = f'font-weight: bold; font-size: 13px; color: {theme.STATUS_DISARM}; background: transparent;'


class Signalling(Protocol):
    @property
    def peer_ping_ms(self) -> float: ...

    def send_crsf_packet(self, frame: bytes) -> None: ...


class FlightWindow(QWidget):
    def __init__(
        self,
        joystick_input: JoystickInput,
        signalling: Signalling | None,
        get_frame: Callable[
            [int], np.ndarray[tuple[int, int, int], np.dtype[np.uint8]] | None
        ],
        cam_count: Callable[[], int],
        loop: asyncio.AbstractEventLoop | None,
        on_close: Callable[[], None],
        fc_kind: str = 'crsf',
        passive: bool = False,
        shift_cam: Callable[[int], int] | None = None,
        cam_index: int = 0,
    ) -> None:
        super().__init__()
        self.setWindowTitle('Flight')
        self._js = joystick_input
        self._signalling = signalling
        self._get_frame = get_frame
        self._cam_count = cam_count
        self._shift_cam = shift_cam
        self._loop = loop
        self._on_close = on_close
        # не 0, а та камера, что была на экране просмотра: борт держит остальные
        # на IDLE_FPS, и опрос чужого трека даёт вечное «нет свежего кадра»
        self._cam_index = cam_index
        self._help_shown = False
        self._passive = bool(passive)

        self._fc_kind = (fc_kind or 'crsf').lower()
        self._last_armed: bool | None = None
        self._js_lost = False
        self._last_aux: list[int] | None = None
        self._release_done = False

        self.__build_ui()
        self._timer = QTimer(interval=10)
        self._timer.timeout.connect(self.__tick)
        self._timer.start()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._help_shown and not self._passive:
            self._help_shown = True
            QTimer.singleShot(100, self.__show_takeoff_help)

    def __show_takeoff_help(self) -> None:
        QMessageBox.information(self, 'Перед взлётом', _TAKEOFF_HELP)

    def __build_ui(self) -> None:
        self._video_label = QLabel(self)
        self._video_label.setStyleSheet(f'background: {theme.BG_VIDEO};')
        self._video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._back_btn = overlay_icon_btn('arrow_back.svg', self)
        self._back_btn.clicked.connect(self.__finish)

        self._help_btn = overlay_btn('i', self, size=theme.OVERLAY_BTN_CORNER_ICON)
        self._help_btn.setToolTip('Горячие клавиши и что означают показатели')
        self._help_btn.clicked.connect(self.toggle_help)

        self._prev_btn = overlay_btn('◀', self)
        self._prev_btn.clicked.connect(self.__prev_cam)
        self._next_btn = overlay_btn('▶', self)
        self._next_btn.clicked.connect(self.__next_cam)

        self._quality_lbl = QLabel('\u25cf  нет данных', self)
        self._quality_lbl.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        self._quality_lbl.setStyleSheet(self.__quality_qss(theme.TEXT_MUTED))
        self._quality_lbl.adjustSize()

        self._stale_lbl = QLabel('', self)
        self._stale_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._stale_lbl.setStyleSheet(f"""
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
        self._stale_lbl.hide()

        self._arm_label = QLabel('DISARM', self)
        self._arm_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._arm_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._arm_label.setStyleSheet(_DISARM_STYLE)

        self._release_label = QLabel('ГРУЗ НА БОРТУ', self)
        self._release_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._release_label.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._release_label.setStyleSheet(_DISARM_STYLE)
        self._release_label.setVisible(self._has_release())

        self._stick_left = StickWidget(
            'Тяга/Рыск', self, bg_alpha=160, label_font_px=18
        )
        self._stick_right = StickWidget(
            'Тангаж/Крен', self, bg_alpha=160, label_font_px=18
        )

        self.hint_lbl = QLabel('Клавиши  ←  →  для переключения камер', self)
        self.hint_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_lbl.setStyleSheet(
            'color: rgba(255,255,255,0.40);'
            f'font-size: {theme.FONT_SIZE_SM - 2}px;'
            'background: transparent;'
        )

        self._lost_lbl = QLabel('⚠  ДЖОЙСТИК ОТКЛЮЧЁН', self)
        self._lost_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lost_lbl.setStyleSheet(f"""
            QLabel {{
                background: rgba(180,30,30,0.92);
                color: white;
                font-weight: bold;
                font-size: {theme.FONT_SIZE_BASE}px;
                border: 1px solid rgba(255,255,255,0.30);
                border-radius: {theme.RADIUS_MD}px;
                padding: 10px 20px;
            }}
        """)
        self._lost_lbl.hide()

        self._stats_lbl = QLabel('')
        self._stats_lbl.setAlignment(
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft
        )
        self._stats_lbl.setWordWrap(True)
        self._stats_lbl.setStyleSheet(stats_label_qss())
        self._stats_scroll = build_stats_scroll(self._stats_lbl, self)
        self._stats_scroll.hide()

        corner_qss = f"""
            QLabel {{
                background: rgba(0,0,0,0.45);
                color: rgba(255,255,255,0.85);
                border: 1px solid rgba(255,255,255,0.10);
                border-radius: {theme.RADIUS_SM}px;
                font-size: {theme.FONT_SIZE_SM - 2}px;
                font-family: monospace;
                padding: 0 8px;
            }}
        """

        self._battery_lbl = QLabel('—', self)
        self._battery_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._battery_lbl.setFixedSize(90, 26)
        self._battery_lbl.setStyleSheet(corner_qss)
        self._battery_lbl.hide()

    def resizeEvent(self, event: QResizeEvent) -> None:
        self.__reposition()
        super().resizeEvent(event)

    def __reposition(self) -> None:
        w, h = self.width(), self.height()
        if w == 0 or h == 0:
            return

        self._video_label.setGeometry(0, 0, w, h)
        self._back_btn.move(_PAD, _PAD)
        self._help_btn.move(
            _PAD + theme.OVERLAY_BTN_CORNER + 12,
            _PAD + (theme.OVERLAY_BTN_CORNER - self._help_btn.height()) // 2,
        )

        side_sz = theme.OVERLAY_BTN_SIDE
        self._prev_btn.move(_PAD, (h - side_sz) // 2)
        self._next_btn.move(w - side_sz - _PAD, (h - side_sz) // 2)

        total_w = 2 * _STICK_SIZE + _STICK_GAP
        x0 = (w - total_w) // 2
        stick_y = h - _STICK_SIZE - _STICK_PAD
        self._stick_left.move(x0, stick_y)
        self._stick_right.move(x0 + _STICK_SIZE + _STICK_GAP, stick_y)

        self.hint_lbl.setGeometry(
            _PAD, _PAD + theme.OVERLAY_BTN_CORNER + 8, w - 2 * _PAD, 20
        )

        arm_w = 100
        self._arm_label.setGeometry((w - arm_w) // 2, stick_y - 26, arm_w, 20)
        rel_w = 180
        self._release_label.setGeometry((w - rel_w) // 2, stick_y - 46, rel_w, 20)

        self._quality_lbl.move(_PAD, h - self._quality_lbl.height() - _PAD)
        self._stale_lbl.move(
            (w - self._stale_lbl.width()) // 2, _PAD + theme.OVERLAY_BTN_CORNER + 34
        )
        self._battery_lbl.move(
            w - self._battery_lbl.width() - _PAD,
            h - self._battery_lbl.height() - _PAD,
        )

        self._lost_lbl.adjustSize()
        self._lost_lbl.move(
            (w - self._lost_lbl.width()) // 2, (h - self._lost_lbl.height()) // 2
        )

        top = _PAD + theme.OVERLAY_BTN_CORNER + 34
        panel_w = stats_panel_width(self, margin=_PAD)
        free_h = max(0, h - top - self._quality_lbl.height() - 2 * _PAD)
        fit_stats_scroll(
            self._stats_scroll, self._stats_lbl, _PAD, top, panel_w, free_h
        )

    def __prev_cam(self) -> None:
        if self._shift_cam is not None:
            self._cam_index = self._shift_cam(-1)
            return
        n = self._cam_count()
        if n > 0:
            self._cam_index = (self._cam_index - 1) % n

    def __next_cam(self) -> None:
        if self._shift_cam is not None:
            self._cam_index = self._shift_cam(1)
            return
        n = self._cam_count()
        if n > 0:
            self._cam_index = (self._cam_index + 1) % n

    def __tick(self) -> None:
        self.__update_joystick()
        self.__update_video_frame()

    def update_battery(self, percent: int, voltage: float) -> None:
        if voltage <= 0:
            return
        self._battery_lbl.setText(f'{voltage:.1f} V')
        if not self._battery_lbl.isVisible():
            self._battery_lbl.show()

    def __update_joystick(self) -> None:
        if self._js_lost:
            self.__tick_emergency_failsafe()
            return

        if not self._js.is_connected():
            self.__handle_joystick_lost()
            return

        try:
            thr, yaw, pitch, roll = self._js.get_stick_positions()
            armed = self._js.is_armed()
        except Exception as exc:
            logger.warning(
                '[FlightWindow] сбой чтения джойстика, трактуем как отключение: %s', exc
            )
            self.__handle_joystick_lost()
            return

        self._stick_left.set_position(yaw, thr)
        self._stick_right.set_position(roll, pitch)
        self._arm_label.setText('ARM' if armed else 'DISARM')
        self._arm_label.setStyleSheet(_ARM_STYLE if armed else _DISARM_STYLE)
        self.__update_release_label()

        if self._passive:
            return

        self.__tick_crsf(thr, yaw, pitch, roll, armed)

    def _has_release(self) -> bool:
        try:
            return bool(self._js.has_release())
        except Exception:
            return False

    def __update_release_label(self) -> None:
        """Надпись показываем только когда кнопка сброса назначена.

        Сброшенный груз назад не возвращается, поэтому надпись залипает:
        вернуть тумблер можно (чтобы закрыть замок), но «ГРУЗ НА БОРТУ»
        после сброса уже не покажем — груза там нет.
        """
        if not self._has_release():
            self._release_label.setVisible(False)
            return
        if not self._release_done:
            try:
                self._release_done = bool(self._js.is_released())
            except Exception:
                return
        self._release_label.setVisible(True)
        done = self._release_done
        self._release_label.setText('ГРУЗ СБРОШЕН' if done else 'ГРУЗ НА БОРТУ')
        self._release_label.setStyleSheet(_ARM_STYLE if done else _DISARM_STYLE)

    def __handle_joystick_lost(self) -> None:
        if self._js_lost:
            return
        self._js_lost = True
        self._arm_label.setText('DISARM')
        self._arm_label.setStyleSheet(_DISARM_STYLE)
        self._stick_left.set_position(0.0, -1.0)
        self._stick_right.set_position(0.0, 0.0)
        self._lost_lbl.show()
        self._lost_lbl.raise_()

        if self._fc_kind == 'mavlink':
            logger.warning(
                '[FlightWindow] джойстик отключён — аварийный DISARM (MAVLink)'
            )
            self._lost_lbl.setText('⚠  СВЯЗЬ С ДЖОЙСТИКОМ ПОТЕРЯНА')
        else:
            logger.warning('[FlightWindow] джойстик отключён — аварийный DISARM (CRSF)')
            self._lost_lbl.setText('⚠  ДЖОЙСТИК ОТКЛЮЧЁН — ДРОН РАЗАРМИРУЕТСЯ')
        self.__tick_emergency_failsafe()

    def __tick_emergency_failsafe(self) -> None:
        cnt = getattr(self, '_emerg_cnt', 0) + 1
        self._emerg_cnt = cnt
        if cnt % 5 != 0:
            return
        if self._fc_kind == 'mavlink':
            return
        try:
            # тумблеры замораживаем: обнуление в момент потери джойстика
            # дёрнуло бы сброс груза
            self._send_packet(
                build_rc_frame(-1.0, 0.0, 0.0, 0.0, armed=False, aux=self._last_aux)
            )
        except Exception as exc:
            logger.debug('[FlightWindow] ошибка аварийной отправки crsf: %s', exc)

    def __tick_crsf(
        self, thr: float, yaw: float, pitch: float, roll: float, armed: bool
    ) -> None:
        try:
            self._last_aux = self._js.get_aux_channels()
        except Exception as exc:
            logger.debug('[FlightWindow] ошибка чтения тумблеров: %s', exc)
        try:
            packet = build_rc_frame(thr, roll, pitch, yaw, armed, aux=self._last_aux)
        except Exception as exc:
            logger.debug('[FlightWindow] ошибка кодирования CRSF: %s', exc)
            return
        if armed != self._last_armed:
            logger.info(
                '[FlightWindow] переход arm CRSF: %s -> %s '
                '(thr=%.2f yaw=%.2f pitch=%.2f roll=%.2f, frame len=%d, head=%s)',
                self._last_armed,
                armed,
                thr,
                yaw,
                pitch,
                roll,
                len(packet),
                packet[:6].hex(),
            )
            self._last_armed = armed
        self._send_packet(packet)

    def _send_packet(self, packet: bytes) -> None:
        if not self._signalling:
            return
        try:
            self._signalling.send_crsf_packet(packet)
        except Exception as exc:
            logger.debug('[FlightWindow] ошибка send_packet: %s', exc)

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

    def toggle_help(self) -> None:
        HelpDialog(self).exec()

    def set_stats_text(self, text: str) -> None:
        self._stats_lbl.setText(text)
        self.__reposition()

    def toggle_stats_panel(self) -> bool:
        visible = self._stats_scroll.isHidden()
        self._stats_scroll.setVisible(visible)
        if visible:
            self._stats_scroll.raise_()
        self.__reposition()
        return visible

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.__finish()
        elif key == Qt.Key.Key_Left:
            self.__prev_cam()
        elif key == Qt.Key.Key_Right:
            self.__next_cam()
        elif key == Qt.Key.Key_S or event.text().lower() in ('s', 'ы'):
            self.toggle_stats_panel()
        elif key == Qt.Key.Key_I or event.text().lower() in ('i', 'ш'):
            self.toggle_help()
        else:
            super().keyPressEvent(event)

    def update_quality(self, text: str, color: str) -> None:
        self._quality_lbl.setStyleSheet(self.__quality_qss(color))
        self._quality_lbl.setText(text)
        self._quality_lbl.adjustSize()
        self.__reposition()

    def update_stale(self, seconds: float) -> None:
        if seconds <= 0:
            self._stale_lbl.hide()
            return
        self._stale_lbl.setText(f'\u26a0  нет свежего кадра {seconds:.1f} с')
        self._stale_lbl.adjustSize()
        self._stale_lbl.show()
        self._stale_lbl.raise_()
        self.__reposition()

    def __update_video_frame(self) -> None:
        frame = self._get_frame(self._cam_index)
        if frame is not None:
            fh, fw, ch = frame.shape
            qimg = QImage(frame.data, fw, fh, ch * fw, QImage.Format.Format_BGR888)
            self._video_label.setPixmap(
                QPixmap.fromImage(qimg).scaled(
                    self._video_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )

    def __finish(self) -> None:
        self._stop_streams()
        if self._on_close:  # type: ignore[truthy-function]
            self._on_close()
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop_streams()
        super().closeEvent(event)

    def _stop_streams(self) -> None:
        self._timer.stop()
