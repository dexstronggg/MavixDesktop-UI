import asyncio
from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QComboBox, QLabel, QMessageBox, QPushButton, QWidget

from mavixdesktop.core.logger import logger
from mavixdesktop.fc.encoder import build_rc_frame
from mavixdesktop.fc.mavlink_encoder import PX4_MAIN_MODES, MavlinkEncoder
from mavixdesktop.ui.style import theme
from .utils import overlay_btn, overlay_icon_btn
from .widgets import StickWidget

_TAKEOFF_HELP = (
    'Перед взлётом:\n\n'
    '1. Опустите газ в ноль.\n'
    '2. Нажмите кнопку ARM на джойстике.\n'
    '3. Аккуратно добавьте газ.'
)

_PAD        = 16
_STICK_SIZE = 120
_STICK_GAP  = 20
_STICK_PAD  = 24

_ARM_STYLE   = f'font-weight: bold; font-size: 13px; color: {theme.STATUS_ARM};   background: transparent;'
_DISARM_STYLE = f'font-weight: bold; font-size: 13px; color: {theme.STATUS_DISARM}; background: transparent;'


class FlightWindow(QWidget):
    def __init__(self, joystick_input, signalling,
                 get_frame: Callable, cam_count: Callable,
                 loop: asyncio.AbstractEventLoop, on_close: Callable,
                 fc_kind: str = 'crsf',
                 passive: bool = False):
        super().__init__()
        self.setWindowTitle('Flight')
        self._js = joystick_input
        self._signalling = signalling
        self._get_frame = get_frame
        self._cam_count = cam_count
        self._loop = loop
        self._on_close = on_close
        self._cam_index = 0
        self._help_shown = False
        # passive=True — окно только ПОКАЗЫВАЕТ видео + стики + battery +
        # ping; никаких MAVLink-фреймов не шлёт. Используется когда
        # параллельно запущен QGroundControl, который сам обрабатывает
        # joystick → MANUAL_CONTROL. Arm-кнопку при этом слушает app
        # отдельным фоновым таймером и шлёт ARM/DISARM через packet-channel.
        self._passive = bool(passive)

        # Per-protocol stream state. MAVLink needs an encoder + heartbeat
        # timer + arm-edge tracking; CRSF re-encodes the whole frame each
        # tick from raw stick values so no state is needed beyond armed.
        self._fc_kind = (fc_kind or 'crsf').lower()
        self._mavlink_enc: MavlinkEncoder | None = None
        self._last_armed: bool | None = None
        # Текущий выбранный main_mode (для PX4). Меняется через выпадающий
        # список в углу окна. По умолчанию Stabilized — самый «дружелюбный»
        # для multicopter на проверке управления.
        self._current_main_mode = PX4_MAIN_MODES['STABILIZED']
        self._mode_combo: QComboBox | None = None
        self._mode_set_sent = False
        self._heartbeat_timer: QTimer | None = None
        # Set when the joystick is physically disconnected mid-flight.
        # Stops normal 50Hz stream and replaces it with a 5Hz «neutral
        # sticks + DISARM» burst so the FC reliably receives the kill
        # command even if the first packet is dropped.
        self._js_lost = False
        self._rtl_sent = False
        if self._fc_kind == 'mavlink' and not self._passive:
            self._mavlink_enc = MavlinkEncoder()
            # PX4 triggers an RC-loss failsafe if it doesn't see a GCS
            # heartbeat for ~1 s. Send one before the 50 Hz manual_control
            # pump even starts, and keep them flowing in the background.
            self._send_packet(self._mavlink_enc.heartbeat())
            self._heartbeat_timer = QTimer(self, interval=1000)
            self._heartbeat_timer.timeout.connect(self.__send_heartbeat)
            self._heartbeat_timer.start()

        self.__build_ui()
        self._timer = QTimer(interval=20)  # 50 Hz
        self._timer.timeout.connect(self.__tick)
        self._timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._help_shown and not self._passive:
            self._help_shown = True
            QTimer.singleShot(100, self.__show_takeoff_help)

    def __show_takeoff_help(self):
        QMessageBox.information(self, 'Перед взлётом', _TAKEOFF_HELP)

    def __build_ui(self):
        self._video_label = QLabel(self)
        self._video_label.setStyleSheet(f'background: {theme.BG_VIDEO};')
        self._video_label.setAlignment(Qt.AlignCenter)

        self._back_btn = overlay_icon_btn('arrow_back.svg', self)
        self._back_btn.clicked.connect(self.__finish)

        self._prev_btn = overlay_btn('◀', self)
        self._prev_btn.clicked.connect(self.__prev_cam)
        self._next_btn = overlay_btn('▶', self)
        self._next_btn.clicked.connect(self.__next_cam)

        self._arm_label = QLabel('DISARM', self)
        self._arm_label.setAlignment(Qt.AlignCenter)
        self._arm_label.setAttribute(Qt.WA_TranslucentBackground)
        self._arm_label.setStyleSheet(_DISARM_STYLE)

        self._stick_left  = StickWidget('Тяга/Рыскание',  self, bg_alpha=160, label_font_px=18)
        self._stick_right = StickWidget('Тангаж/Крен',    self, bg_alpha=160, label_font_px=18)

        self.hint_lbl = QLabel('Клавиши  ←  →  для переключения камер', self)
        self.hint_lbl.setAlignment(Qt.AlignCenter)
        self.hint_lbl.setStyleSheet(
            'color: rgba(255,255,255,0.40);'
            f'font-size: {theme.FONT_SIZE_SM - 2}px;'
            'background: transparent;'
        )

        # Big red banner that appears the moment we detect joystick loss.
        # Текст подменяется в __handle_joystick_lost: для MAVLink сообщаем
        # о AUTO_RTL, для CRSF — о DISARM (тут нет настоящего failsafe).
        self._lost_lbl = QLabel('⚠  ДЖОЙСТИК ОТКЛЮЧЁН', self)
        self._lost_lbl.setAlignment(Qt.AlignCenter)
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

        self._ping_lbl = QLabel('— мс', self)
        self._ping_lbl.setAlignment(Qt.AlignCenter)
        self._ping_lbl.setFixedSize(90, 26)
        self._ping_lbl.setStyleSheet(corner_qss)

        self._battery_lbl = QLabel('—', self)
        self._battery_lbl.setAlignment(Qt.AlignCenter)
        self._battery_lbl.setFixedSize(90, 26)
        self._battery_lbl.setStyleSheet(corner_qss)
        self._battery_lbl.hide()

        # Dropdown переключения PX4 main_mode. Виден только для MAVLink-FC.
        # При смене мгновенно шлём DO_SET_MODE; PX4 ACK логируется в
        # coordinator'е, так что оператор видит подтверждение.
        # В passive-режиме mode/reboot не показываем — этим управляет QGC.
        if self._fc_kind == 'mavlink' and not self._passive:
            self._mode_combo = QComboBox(self)
            for name, code in PX4_MAIN_MODES.items():
                self._mode_combo.addItem(name, code)
            # Установить default = Stabilized
            default_idx = list(PX4_MAIN_MODES.values()).index(self._current_main_mode)
            self._mode_combo.setCurrentIndex(default_idx)
            self._mode_combo.setFixedSize(140, 28)
            self._mode_combo.setStyleSheet(f"""
                QComboBox {{
                    background: rgba(0,0,0,0.55);
                    color: rgba(255,255,255,0.9);
                    border: 1px solid rgba(255,255,255,0.15);
                    border-radius: {theme.RADIUS_SM}px;
                    padding: 2px 8px;
                    font-size: {theme.FONT_SIZE_SM - 1}px;
                }}
                QComboBox::drop-down {{ border: none; width: 16px; }}
                QComboBox QAbstractItemView {{
                    background: #1f1f1f;
                    color: white;
                    selection-background-color: {theme.ACCENT};
                }}
            """)
            self._mode_combo.currentIndexChanged.connect(self.__on_mode_picked)

            self._reboot_btn = QPushButton('⟳ Reboot FC', self)
            self._reboot_btn.setFixedSize(140, 28)
            self._reboot_btn.setToolTip('Послать PX4 команду перезагрузки автопилота')
            self._reboot_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(180,30,30,0.65);
                    color: white;
                    border: 1px solid rgba(255,255,255,0.20);
                    border-radius: {theme.RADIUS_SM}px;
                    font-size: {theme.FONT_SIZE_SM - 1}px;
                    font-weight: 600;
                }}
                QPushButton:hover {{ background: rgba(220,40,40,0.85); }}
                QPushButton:pressed {{ background: rgba(140,20,20,0.95); }}
            """)
            self._reboot_btn.clicked.connect(self.__on_reboot_clicked)
        else:
            self._reboot_btn: QPushButton | None = None

    def resizeEvent(self, event):
        self.__reposition()
        super().resizeEvent(event)

    def __reposition(self):
        w, h = self.width(), self.height()
        if w == 0 or h == 0:
            return

        self._video_label.setGeometry(0, 0, w, h)
        self._back_btn.move(_PAD, _PAD)

        side_sz = theme.OVERLAY_BTN_SIDE
        self._prev_btn.move(_PAD, (h - side_sz) // 2)
        self._next_btn.move(w - side_sz - _PAD, (h - side_sz) // 2)

        total_w = 2 * _STICK_SIZE + _STICK_GAP
        x0 = (w - total_w) // 2
        stick_y = h - _STICK_SIZE - _STICK_PAD
        self._stick_left.move(x0, stick_y)
        self._stick_right.move(x0 + _STICK_SIZE + _STICK_GAP, stick_y)

        self.hint_lbl.setGeometry(_PAD, _PAD + theme.OVERLAY_BTN_CORNER + 8, w - 2 * _PAD, 20)

        arm_w = 100
        self._arm_label.setGeometry((w - arm_w) // 2, stick_y - 26, arm_w, 20)

        self._ping_lbl.move(w - self._ping_lbl.width() - _PAD, h - self._ping_lbl.height() - _PAD)
        self._battery_lbl.move(
            w - self._battery_lbl.width() - _PAD,
            h - self._ping_lbl.height() - self._battery_lbl.height() - _PAD - 6,
        )

        if self._mode_combo is not None:
            # Верхний правый угол, рядом с joystick-кнопкой.
            self._mode_combo.move(w - self._mode_combo.width() - _PAD,
                                   _PAD + theme.OVERLAY_BTN_CORNER + 8)
            self._mode_combo.raise_()
        if self._reboot_btn is not None:
            # Под dropdown'ом режимов.
            self._reboot_btn.move(w - self._reboot_btn.width() - _PAD,
                                  _PAD + theme.OVERLAY_BTN_CORNER + 8 + 32)
            self._reboot_btn.raise_()


        self._lost_lbl.adjustSize()
        self._lost_lbl.move((w - self._lost_lbl.width()) // 2, (h - self._lost_lbl.height()) // 2)

    def __prev_cam(self):
        n = self._cam_count()
        if n > 0:
            self._cam_index = (self._cam_index - 1) % n

    def __next_cam(self):
        n = self._cam_count()
        if n > 0:
            self._cam_index = (self._cam_index + 1) % n

    def __tick(self):
        self.__update_joystick()
        self.__update_video_frame()
        self.__update_ping()

    def __update_ping(self):
        rtt = -1.0
        if self._signalling is not None:
            try:
                rtt = float(self._signalling.peer_ping_ms)
            except Exception:
                rtt = -1.0
        self._ping_lbl.setText('— мс' if rtt < 0 else f'{rtt:.0f} мс')

    def update_battery(self, percent: int, voltage: float) -> None:
        """Pushed by App when battery telemetry comes in (CRSF or MAVLink).
        Shows just the voltage — `percent` is accepted for signature
        symmetry with the bridge signal but isn't rendered."""
        if voltage <= 0:
            return
        self._battery_lbl.setText(f'{voltage:.1f} V')
        if not self._battery_lbl.isVisible():
            self._battery_lbl.show()

    def __update_joystick(self):
        # Re-arm-while-lost is not allowed: once we've sent the emergency
        # disarm we keep spamming it (slower) until the operator closes
        # the window. Coming back from a yanked joystick mid-flight isn't
        # something we want to surprise the pilot with.
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
            # Treat a read failure as a disconnect: pygame's «device gone»
            # error often surfaces here before JOYDEVICEREMOVED arrives.
            logger.warning('[FlightWindow] joystick read failed, treating as disconnect: %s', exc)
            self.__handle_joystick_lost()
            return

        self._stick_left.set_position(yaw, thr)
        self._stick_right.set_position(roll, pitch)
        self._arm_label.setText('ARM' if armed else 'DISARM')
        self._arm_label.setStyleSheet(_ARM_STYLE if armed else _DISARM_STYLE)

        if self._passive:
            # Видео + UI визуально показываем, никаких MAVLink-фреймов
            # не шлём — это делает параллельно запущенный QGC.
            return

        if self._fc_kind == 'mavlink':
            self.__tick_mavlink(thr, yaw, pitch, roll, armed)
        else:
            self.__tick_crsf(thr, yaw, pitch, roll, armed)

    def __handle_joystick_lost(self):
        """One-time setup when we detect the gamepad is gone.

        Для MAVLink (PX4) шлём AUTO_RTL — дрон автономно вернётся домой
        и сядет. Heartbeat НЕ глушим: PX4 должен видеть GCS живым, иначе
        запустится встроенный RC-loss (у нас он отключён через NAV_RCL_ACT=0,
        но всё равно полезно поддерживать связь, чтобы RTL прошёл штатно).

        Для CRSF посылаем neutral+DISARM-спам — у Betaflight нет honest
        RTL, а полагаться на конфиг RX-failsafe пользователя нельзя.
        """
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
            logger.warning('[FlightWindow] joystick disconnected — sending AUTO_RTL')
            self._lost_lbl.setText('⚠  ДЖОЙСТИК ОТКЛЮЧЁН — ВКЛЮЧЕН RETURN-TO-LAUNCH')
            self._rtl_sent = False
            # Heartbeat оставляем работать — PX4 нужно видеть GCS пока он рулит RTL.
        else:
            logger.warning('[FlightWindow] joystick disconnected — emergency DISARM (CRSF)')
            self._lost_lbl.setText('⚠  ДЖОЙСТИК ОТКЛЮЧЁН — ДРОН РАЗАРМИРУЕТСЯ')
            if self._heartbeat_timer is not None:
                self._heartbeat_timer.stop()
        self.__tick_emergency_failsafe()

    def __tick_emergency_failsafe(self):
        """Раз в 5 тиков (~10 Hz) шлём failsafe-команду.
        MAVLink: AUTO_RTL один раз (PX4 переключается и держит режим
        сам). CRSF: neutral+DISARM на каждом тике пока окно открыто.
        """
        cnt = getattr(self, '_emerg_cnt', 0) + 1
        self._emerg_cnt = cnt
        if cnt % 5 != 0:
            return
        if self._fc_kind == 'mavlink' and self._mavlink_enc is not None:
            if self._rtl_sent:
                return
            try:
                # Дублируем тремя пакетами в течение 0 ms — SCTP-канал
                # надёжный, но при флакающем линке полезно повторить.
                for _ in range(3):
                    self._send_packet(self._mavlink_enc.failsafe_rtl())
                self._rtl_sent = True
                logger.info('[FlightWindow] AUTO_RTL sent to PX4')
            except Exception as exc:
                logger.debug('[FlightWindow] emergency mavlink RTL send: %s', exc)
            return
        try:
            self._send_packet(build_rc_frame(-1.0, 0.0, 0.0, 0.0, armed=False))
        except Exception as exc:
            logger.debug('[FlightWindow] emergency crsf send: %s', exc)

    def __tick_crsf(self, thr: float, yaw: float, pitch: float,
                    roll: float, armed: bool) -> None:
        try:
            packet = build_rc_frame(thr, roll, pitch, yaw, armed)
        except Exception as exc:
            logger.debug('[FlightWindow] CRSF encode error: %s', exc)
            return
        # Log ARM/DISARM transitions explicitly so we can confirm the
        # button press is actually being read and a frame with the new
        # CH5 value is going out. Sticks are noisy at 50 Hz; don't spam.
        if armed != self._last_armed:
            logger.info(
                '[FlightWindow] CRSF arm transition: %s -> %s '
                '(thr=%.2f yaw=%.2f pitch=%.2f roll=%.2f, frame len=%d, head=%s)',
                self._last_armed, armed, thr, yaw, pitch, roll,
                len(packet), packet[:6].hex(),
            )
            self._last_armed = armed
        self._send_packet(packet)

    def __tick_mavlink(self, thr: float, yaw: float, pitch: float,
                       roll: float, armed: bool) -> None:
        assert self._mavlink_enc is not None
        # One-shot SET_MODE before the operator starts arming: PX4 has no
        # «default mode» param and stays in Hold without an explicit
        # SET_MODE command. We do it on the first joystick tick so the
        # packet channel is definitely open by now. Используется
        # текущий выбранный mode из dropdown'a (по умолчанию Stabilized).
        if not self._mode_set_sent:
            self._send_packet(self._mavlink_enc.set_mode(self._current_main_mode))
            self._mode_set_sent = True

        try:
            mc = self._mavlink_enc.manual_control(thr, yaw, pitch, roll)
        except Exception as exc:
            logger.debug('[FlightWindow] MANUAL_CONTROL encode error: %s', exc)
            return
        self._send_packet(mc)

        # Edge-triggered arm/disarm. We force-arm (param2=21196 magic) on
        # the assumption that the operator already disabled pre-arm checks
        # in QGC per настройка_px4.md — otherwise PX4 ignores normal arms
        # when sensors aren't fully calibrated.
        if self._last_armed is None or armed != self._last_armed:
            try:
                self._send_packet(self._mavlink_enc.arm_disarm(armed, force=True))
                logger.info('[FlightWindow] sent %s command', 'ARM' if armed else 'DISARM')
            except Exception as exc:
                logger.warning('[FlightWindow] arm command error: %s', exc)
            self._last_armed = armed

    def __on_reboot_clicked(self) -> None:
        """С подтверждением шлёт PX4 MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN.
        PX4 ответит COMMAND_ACK и тут же ребутнётся — WebRTC-сессия
        переподключится, mode/arm нужно будет выставлять заново."""
        if self._mavlink_enc is None:
            return
        reply = QMessageBox.question(
            self, 'Reboot FC',
            'Перезагрузить полётник?\n\nКоманда отправится только если дрон разармирован — '
            'PX4 защищает себя от ребута в воздухе.',
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self._send_packet(self._mavlink_enc.reboot_autopilot())
            logger.info('[FlightWindow] sent PREFLIGHT_REBOOT_SHUTDOWN')
        except Exception as exc:
            logger.warning('[FlightWindow] reboot send error: %s', exc)

    def __on_mode_picked(self, idx: int) -> None:
        """Мгновенно шлём SET_MODE при выборе в dropdown. PX4 ответит
        COMMAND_ACK для DO_SET_MODE — увидите в логах ACCEPTED/DENIED."""
        if self._mode_combo is None or self._mavlink_enc is None:
            return
        main_mode = self._mode_combo.itemData(idx)
        if main_mode is None:
            return
        try:
            main_mode = int(main_mode)
        except (TypeError, ValueError):
            return
        self._current_main_mode = main_mode
        try:
            self._send_packet(self._mavlink_enc.set_mode(main_mode))
            logger.info('[FlightWindow] sent SET_MODE main=%d (%s)',
                        main_mode, self._mode_combo.currentText())
        except Exception as exc:
            logger.warning('[FlightWindow] SET_MODE send error: %s', exc)

    def __send_heartbeat(self) -> None:
        if self._mavlink_enc is None:
            return
        try:
            self._send_packet(self._mavlink_enc.heartbeat())
        except Exception as exc:
            logger.debug('[FlightWindow] heartbeat encode error: %s', exc)

    def _send_packet(self, packet: bytes) -> None:
        if not self._signalling:
            return
        try:
            self._signalling.send_crsf_packet(packet)
        except Exception as exc:
            logger.debug('[FlightWindow] send_packet error: %s', exc)

    def __update_video_frame(self):
        frame = self._get_frame(self._cam_index)
        if frame is not None:
            fh, fw, ch = frame.shape
            qimg = QImage(frame.data, fw, fh, ch * fw, QImage.Format.Format_BGR888)
            self._video_label.setPixmap(
                QPixmap.fromImage(qimg).scaled(
                    self._video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
            )

    def __finish(self):
        self._stop_streams()
        if self._on_close:
            self._on_close()
        self.close()

    def closeEvent(self, event):
        self._stop_streams()
        super().closeEvent(event)

    def _stop_streams(self) -> None:
        self._timer.stop()
        if self._heartbeat_timer is not None:
            self._heartbeat_timer.stop()
        # Send one final DISARM on close so we don't leave the FC armed
        # if the operator just hit the back button.
        if self._mavlink_enc is not None and self._last_armed:
            try:
                self._send_packet(self._mavlink_enc.arm_disarm(False, force=True))
            except Exception as exc:
                logger.debug('[FlightWindow] final disarm error: %s', exc)
