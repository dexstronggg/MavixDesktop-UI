from __future__ import annotations

import asyncio
from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QImage, QPixmap, QResizeEvent, QShowEvent
from PySide6.QtWidgets import QComboBox, QLabel, QMessageBox, QPushButton, QWidget

from mavixdesktop.core.logger import logger
from mavixdesktop.fc.encoder import build_rc_frame
from mavixdesktop.fc.mavlink_encoder import PX4_MAIN_MODES, MavlinkEncoder
from mavixdesktop.ui.screens.utils import overlay_btn, overlay_icon_btn
from mavixdesktop.ui.screens.widgets import StickWidget
from mavixdesktop.ui.style import theme

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
                 get_frame: Callable[[int], object], cam_count: Callable[[], int],
                 loop: asyncio.AbstractEventLoop, on_close: Callable[[], None],
                 fc_kind: str = 'crsf',
                 passive: bool = False,
                 on_drop: Callable[[], None] | None = None,
                 on_open_settings: Callable[[], None] | None = None) -> None:
        super().__init__()
        self.setWindowTitle('Flight')
        self._js = joystick_input
        self._signalling = signalling
        self._get_frame = get_frame
        self._cam_count = cam_count
        self._loop = loop
        self._on_close = on_close
        self._on_drop = on_drop
        self._on_open_settings = on_open_settings
        self._cam_index = 0
        self._help_shown = False
        # Залипает на N тиков после нажатия кнопки сброса груза, чтобы CH8
        # успел гарантированно уйти на борт несколькими RC-кадрами (50..100 Hz
        # поток, один потерянный пакет недопустим для физического сброса).
        self._drop_hold_ticks = 0
        self._delivered_marked = False
        # passive=True — окно только ПОКАЗЫВАЕТ видео + стики + battery +
        # ping; никаких MAVLink-фреймов не шлёт. Используется когда
        # параллельно запущен QGroundControl, который сам обрабатывает
        # joystick → MANUAL_CONTROL. Arm-кнопку при этом слушает app
        # отдельным фоновым таймером и шлёт ARM/DISARM через packet-channel.
        self._passive = bool(passive)

        # Состояние потока на протокол. MAVLink требует encoder + heartbeat-
        # таймер + отслеживание фронта arm; CRSF перекодирует весь кадр на
        # каждом тике из сырых значений стиков, так что состояния, кроме
        # armed, не нужно.
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
        # Ставится, когда джойстик физически отключён в полёте. Останавливает
        # обычный 50 Hz поток и заменяет его 5 Hz пачкой «нейтральные стики +
        # DISARM», чтобы FC надёжно получил kill-команду, даже если первый
        # пакет потеряется.
        self._js_lost = False
        self._rtl_sent = False
        if self._fc_kind == 'mavlink' and not self._passive:
            self._mavlink_enc = MavlinkEncoder()
            # PX4 запускает RC-loss failsafe, если не видит heartbeat от GCS
            # ~1 с. Шлём один до старта 50 Hz manual_control-насоса и держим
            # их идущими в фоне.
            self._send_packet(self._mavlink_enc.heartbeat())
            self._heartbeat_timer = QTimer(self, interval=1000)
            self._heartbeat_timer.timeout.connect(self.__send_heartbeat)
            self._heartbeat_timer.start()

        self.__build_ui()
        self._timer = QTimer(interval=10)  # 100 Hz — ниже Betaflight срывается в RXLOSS
        self._timer.timeout.connect(self.__tick)
        self._timer.start()

    #### Построение UI #####################################################################
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
        self._video_label.setAlignment(Qt.AlignCenter)

        self._back_btn = overlay_icon_btn('arrow_back.svg', self)
        self._back_btn.clicked.connect(self.__finish)

        # Кнопка настроек в углу полётного экрана (доступ к Settings перенесён
        # сюда — отдельной навигации-списка больше нет).
        self._settings_btn = overlay_icon_btn('tune.svg', self)
        self._settings_btn.setToolTip('Настройки')
        if self._on_open_settings is not None:
            self._settings_btn.clicked.connect(self._on_open_settings)
        else:
            self._settings_btn.hide()

        # Кнопка ручного сброса груза — дублирует кнопку джойстика на случай,
        # если она не привязана в калибровке. Шлёт CH8=DROP и помечает
        # доставку delivered (через тот же __trigger_drop).
        self._drop_btn = QPushButton('⬇  Сброс груза', self)
        self._drop_btn.setFixedSize(150, 40)
        self._drop_btn.setCursor(Qt.PointingHandCursor)
        self._drop_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(34,197,94,0.80);
                color: white;
                border: 1px solid rgba(255,255,255,0.25);
                border-radius: {theme.RADIUS_MD}px;
                font-size: {theme.FONT_SIZE_SM}px;
                font-weight: 700;
            }}
            QPushButton:hover {{ background: rgba(34,197,94,0.95); }}
            QPushButton:pressed {{ background: rgba(22,163,74,0.95); }}
        """)
        self._drop_btn.clicked.connect(self.__trigger_drop)
        if self._passive:
            # В passive-режиме (QGC рулит) CRSF-кадры мы не шлём — кнопка
            # сброса бессмысленна, скрываем её.
            self._drop_btn.hide()

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

        # Большой красный баннер, появляется в момент обнаружения потери
        # джойстика. Текст подменяется в __handle_joystick_lost: для MAVLink
        # сообщаем об AUTO_RTL, для CRSF — о DISARM (тут нет настоящего
        # failsafe).
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

        # Статус груза — виден всегда (и в passive/QGC, и в CRSF): пока не
        # сброшено — нейтральный, после сброса — зелёный «сброшено».
        self._drop_status_lbl = QLabel('Груз: не сброшено', self)
        self._drop_status_lbl.setAlignment(Qt.AlignCenter)
        self._drop_status_lbl.setFixedSize(160, 26)
        self._drop_status_lbl.setStyleSheet(corner_qss)

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

        # Карта в углу экрана управления (нативный QPainter-виджет, без
        # QtWebEngine): позиция дрона, поворот по курсу, точка назначения.
        from mavixdesktop.ui.screens.map_widget import MapWidget
        self._map = MapWidget(self)
        self._map.setFixedSize(280, 200)

    #### Карта и телеметрия ################################################################
    def update_telemetry(self, lat: float, lon: float, heading: float) -> None:
        """Обновляет позицию дрона на карте и поворот карты по курсу."""
        try:
            self._map.update_telemetry(lat, lon, heading)
        except Exception as exc:
            logger.debug('[FlightWindow] ошибка обновления карты: %s', exc)

    def set_destination(self, lat: float, lon: float) -> None:
        """Ставит маркер точки назначения на карте (из принятой заявки)."""
        try:
            self._map.set_destination(lat, lon)
        except Exception as exc:
            logger.debug('[FlightWindow] ошибка маркера назначения: %s', exc)

    #### Геометрия и позиционирование ######################################################
    def resizeEvent(self, event: QResizeEvent) -> None:
        self.__reposition()
        super().resizeEvent(event)

    def __reposition(self) -> None:
        w, h = self.width(), self.height()
        if w == 0 or h == 0:
            return

        self._video_label.setGeometry(0, 0, w, h)
        self._back_btn.move(_PAD, _PAD)
        # Кнопка настроек — рядом с «назад», правее.
        self._settings_btn.move(_PAD + theme.OVERLAY_BTN_CORNER + 8, _PAD)
        self._settings_btn.raise_()

        side_sz = theme.OVERLAY_BTN_SIDE
        self._prev_btn.move(_PAD, (h - side_sz) // 2)
        self._next_btn.move(w - side_sz - _PAD, (h - side_sz) // 2)

        # Карта — нижний левый угол.
        self._map.move(_PAD, h - self._map.height() - _PAD)
        self._map.raise_()

        # Кнопка сброса груза — по центру внизу, над стиками-зоной справа.
        self._drop_btn.move(
            (w - self._drop_btn.width()) // 2,
            _PAD + theme.OVERLAY_BTN_CORNER + 36,
        )
        self._drop_btn.raise_()

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

        # Статус груза — верхний центр, над hint'ом.
        self._drop_status_lbl.move((w - self._drop_status_lbl.width()) // 2, _PAD)
        self._drop_status_lbl.raise_()

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

    #### Игровой цикл и ввод ###############################################################
    def __prev_cam(self) -> None:
        n = self._cam_count()
        if n > 0:
            self._cam_index = (self._cam_index - 1) % n

    def __next_cam(self) -> None:
        n = self._cam_count()
        if n > 0:
            self._cam_index = (self._cam_index + 1) % n

    def __tick(self) -> None:
        self.__update_joystick()
        self.__update_video_frame()
        self.__update_ping()

    def __update_ping(self) -> None:
        rtt = -1.0
        if self._signalling is not None:
            try:
                rtt = float(self._signalling.peer_ping_ms)
            except Exception:
                rtt = -1.0
        self._ping_lbl.setText('— мс' if rtt < 0 else f'{rtt:.0f} мс')

    def update_battery(self, percent: int, voltage: float) -> None:
        """Вызывается App при поступлении телеметрии батареи (CRSF или MAVLink).

        Показывает только вольтаж — percent принимается для симметрии
        сигнатуры с bridge-сигналом, но не рендерится.
        """
        if voltage <= 0:
            return
        self._battery_lbl.setText(f'{voltage:.1f} V')
        if not self._battery_lbl.isVisible():
            self._battery_lbl.show()

    def __update_joystick(self) -> None:
        # В MAVLink/passive режиме джойстик передан как None: QGC владеет
        # устройством через EVIOCGRAB, pygame.event.pump() на том же SDL-
        # объекте вызвал бы SIGSEGV. Пропускаем — QGC сам управляет полётом.
        if self._js is None:
            return

        # Повторный arm при потере джойстика запрещён: отправив аварийный
        # disarm, продолжаем спамить им (реже), пока оператор не закроет
        # окно. Возврат после выдернутого в полёте джойстика — не то, чем
        # стоит удивлять пилота.
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
            # Сбой чтения трактуем как отключение: ошибка pygame «device
            # gone» часто всплывает здесь до прихода JOYDEVICEREMOVED.
            logger.warning('[FlightWindow] сбой чтения джойстика, трактуем как отключение: %s', exc)
            self.__handle_joystick_lost()
            return

        self._stick_left.set_position(yaw, thr)
        self._stick_right.set_position(roll, pitch)
        self._arm_label.setText('ARM' if armed else 'DISARM')
        self._arm_label.setStyleSheet(_ARM_STYLE if armed else _DISARM_STYLE)

        # Кнопка сброса груза: на фронте нажатия удерживаем CH8=DROP на
        # несколько тиков и однократно помечаем доставку delivered.
        try:
            if self._js.is_drop_pressed():
                self.__trigger_drop()
        except Exception as exc:
            logger.debug('[FlightWindow] ошибка чтения кнопки сброса: %s', exc)

        if self._passive:
            # Видео + UI визуально показываем, никаких MAVLink-фреймов
            # не шлём — это делает параллельно запущенный QGC.
            return

        if self._fc_kind == 'mavlink':
            self.__tick_mavlink(thr, yaw, pitch, roll, armed)
        else:
            self.__tick_crsf(thr, yaw, pitch, roll, armed)

    #### Аварийный failsafe ################################################################
    def __handle_joystick_lost(self) -> None:
        """Однократная настройка при обнаружении пропажи геймпада.

        Для MAVLink (PX4) шлём AUTO_RTL — дрон автономно вернётся домой
        и сядет. Heartbeat НЕ глушим: PX4 должен видеть GCS живым, иначе
        запустится встроенный RC-loss (у нас он отключён через NAV_RCL_ACT=0,
        но всё равно полезно поддерживать связь, чтобы RTL прошёл штатно).

        Для CRSF посылаем neutral+DISARM-спам — у Betaflight нет честного
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
            logger.warning('[FlightWindow] джойстик отключён — шлём AUTO_RTL')
            self._lost_lbl.setText('⚠  ДЖОЙСТИК ОТКЛЮЧЁН — ВКЛЮЧЕН RETURN-TO-LAUNCH')
            self._rtl_sent = False
            # Heartbeat оставляем работать — PX4 нужно видеть GCS пока он рулит RTL.
        else:
            logger.warning('[FlightWindow] джойстик отключён — аварийный DISARM (CRSF)')
            self._lost_lbl.setText('⚠  ДЖОЙСТИК ОТКЛЮЧЁН — ДРОН РАЗАРМИРУЕТСЯ')
            if self._heartbeat_timer is not None:
                self._heartbeat_timer.stop()
        self.__tick_emergency_failsafe()

    def __tick_emergency_failsafe(self) -> None:
        """Раз в 5 тиков (~10 Hz) шлём failsafe-команду.

        MAVLink: AUTO_RTL один раз (PX4 переключается и держит режим сам).
        CRSF: neutral+DISARM на каждом тике, пока окно открыто.
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
                logger.info('[FlightWindow] AUTO_RTL отправлен на PX4')
            except Exception as exc:
                logger.debug('[FlightWindow] ошибка аварийной отправки mavlink RTL: %s', exc)
            return
        try:
            self._send_packet(build_rc_frame(-1.0, 0.0, 0.0, 0.0, armed=False))
        except Exception as exc:
            logger.debug('[FlightWindow] ошибка аварийной отправки crsf: %s', exc)

    #### Сброс груза #######################################################################
    def __trigger_drop(self) -> None:
        """Запускает сброс груза: удержание CH8=DROP на ~15 тиков (RC-кадр
        уходит дрону) и однократная отметка доставки delivered (сервер
        уведомит админа). Повторное нажатие посылает DROP ещё раз, но
        delivered помечаем только один раз."""
        self._drop_hold_ticks = 15
        logger.info('[FlightWindow] сброс груза: CH8=DROP, отметка delivered')
        # Статус груза → «сброшено» (зелёный).
        self._drop_status_lbl.setText('Груз: сброшено')
        self._drop_status_lbl.setStyleSheet(
            f'background: rgba(34,197,94,0.85); color: white;'
            f'border: 1px solid rgba(255,255,255,0.25);'
            f'border-radius: {theme.RADIUS_SM}px; font-size: {theme.FONT_SIZE_SM - 2}px;'
            f'font-family: monospace; padding: 0 8px; font-weight: 700;'
        )
        if not self._delivered_marked:
            self._delivered_marked = True
            if self._on_drop is not None:
                try:
                    self._on_drop()
                except Exception as exc:
                    logger.warning('[FlightWindow] ошибка on_drop: %s', exc)

    #### Кодирование команд FC #############################################################
    def __tick_crsf(self, thr: float, yaw: float, pitch: float,
                    roll: float, armed: bool) -> None:
        drop = self._drop_hold_ticks > 0
        if self._drop_hold_ticks > 0:
            self._drop_hold_ticks -= 1
        try:
            packet = build_rc_frame(thr, roll, pitch, yaw, armed, drop=drop)
        except Exception as exc:
            logger.debug('[FlightWindow] ошибка кодирования CRSF: %s', exc)
            return
        # Логируем переходы ARM/DISARM явно, чтобы подтвердить, что нажатие
        # кнопки реально считывается и кадр с новым значением CH5 уходит.
        # Стики шумят на 50 Hz; не спамим.
        if armed != self._last_armed:
            logger.info(
                '[FlightWindow] переход arm CRSF: %s -> %s '
                '(thr=%.2f yaw=%.2f pitch=%.2f roll=%.2f, frame len=%d, head=%s)',
                self._last_armed, armed, thr, yaw, pitch, roll,
                len(packet), packet[:6].hex(),
            )
            self._last_armed = armed
        self._send_packet(packet)

    def __tick_mavlink(self, thr: float, yaw: float, pitch: float,
                       roll: float, armed: bool) -> None:
        assert self._mavlink_enc is not None
        # Однократный SET_MODE до того, как оператор начнёт армить: у PX4
        # нет параметра «режим по умолчанию», он остаётся в Hold без явной
        # SET_MODE-команды. Делаем это на первом тике джойстика, так что
        # packet-канал к этому моменту точно открыт. Используется текущий
        # выбранный mode из dropdown-а (по умолчанию Stabilized).
        if not self._mode_set_sent:
            self._send_packet(self._mavlink_enc.set_mode(self._current_main_mode))
            self._mode_set_sent = True

        try:
            mc = self._mavlink_enc.manual_control(thr, yaw, pitch, roll)
        except Exception as exc:
            logger.debug('[FlightWindow] ошибка кодирования MANUAL_CONTROL: %s', exc)
            return
        self._send_packet(mc)

        # Arm/disarm по фронту. Делаем force-arm (param2=21196 magic) в
        # расчёте, что оператор уже отключил pre-arm проверки в QGC по
        # настройка_px4.md — иначе PX4 игнорирует обычный arm, пока сенсоры
        # не откалиброваны полностью.
        if self._last_armed is None or armed != self._last_armed:
            try:
                self._send_packet(self._mavlink_enc.arm_disarm(armed, force=True))
                logger.info('[FlightWindow] отправлена команда %s', 'ARM' if armed else 'DISARM')
            except Exception as exc:
                logger.warning('[FlightWindow] ошибка команды arm: %s', exc)
            self._last_armed = armed

    #### Обработчики панели управления #####################################################
    def __on_reboot_clicked(self) -> None:
        """С подтверждением шлёт PX4 MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN.

        PX4 ответит COMMAND_ACK и тут же ребутнётся — WebRTC-сессия
        переподключится, mode/arm нужно будет выставлять заново.
        """
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
            logger.info('[FlightWindow] отправлен PREFLIGHT_REBOOT_SHUTDOWN')
        except Exception as exc:
            logger.warning('[FlightWindow] ошибка отправки reboot: %s', exc)

    def __on_mode_picked(self, idx: int) -> None:
        """Мгновенно шлёт SET_MODE при выборе в dropdown.

        PX4 ответит COMMAND_ACK для DO_SET_MODE — увидите в логах
        ACCEPTED/DENIED.
        """
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
            logger.info('[FlightWindow] отправлен SET_MODE main=%d (%s)',
                        main_mode, self._mode_combo.currentText())
        except Exception as exc:
            logger.warning('[FlightWindow] ошибка отправки SET_MODE: %s', exc)

    #### Отправка и рендер #################################################################
    def __send_heartbeat(self) -> None:
        if self._mavlink_enc is None:
            return
        try:
            self._send_packet(self._mavlink_enc.heartbeat())
        except Exception as exc:
            logger.debug('[FlightWindow] ошибка кодирования heartbeat: %s', exc)

    def _send_packet(self, packet: bytes) -> None:
        if not self._signalling:
            return
        try:
            self._signalling.send_crsf_packet(packet)
        except Exception as exc:
            logger.debug('[FlightWindow] ошибка send_packet: %s', exc)

    def __update_video_frame(self) -> None:
        frame = self._get_frame(self._cam_index)
        if frame is not None:
            fh, fw, ch = frame.shape
            qimg = QImage(frame.data, fw, fh, ch * fw, QImage.Format.Format_BGR888)
            self._video_label.setPixmap(
                QPixmap.fromImage(qimg).scaled(
                    self._video_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation,
                )
            )

    #### Закрытие окна #####################################################################
    def __finish(self) -> None:
        self._stop_streams()
        if self._on_close:
            self._on_close()
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop_streams()
        super().closeEvent(event)

    def _stop_streams(self) -> None:
        self._timer.stop()
        if self._heartbeat_timer is not None:
            self._heartbeat_timer.stop()
        # Шлём один финальный DISARM при закрытии, чтобы не оставить FC
        # армированным, если оператор просто нажал кнопку «назад».
        if self._mavlink_enc is not None and self._last_armed:
            try:
                self._send_packet(self._mavlink_enc.arm_disarm(False, force=True))
            except Exception as exc:
                logger.debug('[FlightWindow] ошибка финального disarm: %s', exc)
