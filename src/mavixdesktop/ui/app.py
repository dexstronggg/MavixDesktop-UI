"""Главное Qt-окно MavixDesktop (приложение ОПЕРАТОРА системы доставки).

Поток экранов: вход (оператор) → ожидание заявок (DeliveryPage) →
[принята заявка] → DroneViewPage (видео) → JoystickSetupPage → FlightWindow
(видео + джойстик + карта в углу + кнопка сброса груза).

Дрон не выбирается вручную — он берётся из принятой заявки
(delivery.drone_id). Долетев, оператор жмёт «Сброс груза» → дрон сбрасывает
груз (CH8=DROP), доставка помечается delivered.

Связывает PySide6-UI с mavixdesktop.coordinator.SessionCoordinator через
ConnectionManager (адаптирует async event loop к Qt-сигналам) и
VideoManager (гоняет QTimer на 33 ms по очереди треков aiortc и отдаёт
BGR-кадры в DroneViewPage.show_frame).
"""

from __future__ import annotations

import platform
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from mavixdesktop.core.logger import logger
from mavixdesktop.joystick.guard import JoystickGuard
from mavixdesktop.qgc.launcher import is_qgc_running, launch_qgc, save_qgc_path
from mavixdesktop.ui.login_page import LoginPage
from mavixdesktop.ui.managers.connection import ConnectionManager
from mavixdesktop.ui.managers.demo_connection import DemoConnectionManager
from mavixdesktop.ui.managers.video import VideoManager
from mavixdesktop.ui.screens.bridge import Bridge
from mavixdesktop.ui.screens.delivery_page import DeliveryPage
from mavixdesktop.ui.screens.drone_view import DroneViewPage
from mavixdesktop.ui.screens.flight_window import FlightWindow
from mavixdesktop.ui.screens.joystick_setup import (
    JoystickSetupPage,
    QGCLaunchingOverlay,
)
from mavixdesktop.ui.screens.map_widget import telemetry_to_args
from mavixdesktop.ui.screens.settings_page import SettingsPage
from mavixdesktop.ui.state import SessionState


class App(QMainWindow):
    def __init__(self, demo: bool = False) -> None:
        super().__init__()
        self._demo = demo
        title = 'Mavix · ДЕМО-РЕЖИМ' if demo else 'Mavix'
        self.setWindowTitle(title)
        self.setMinimumSize(1300, 600)
        self.resize(1300, 600)

        try:
            import pygame
            pygame.init()
        except Exception as exc:
            logger.warning('[app] не удалось выполнить pygame.init: %s', exc)

        self._state = SessionState()
        self._nav_history: list[int] = []
        self._bridge = Bridge()

        # Демо-режим подменяет настоящий ConnectionManager заглушкой
        # с мок-данными (см. ui/managers/demo_connection.py).
        self._conn = (
            DemoConnectionManager(bridge=self._bridge)
            if demo else
            ConnectionManager(bridge=self._bridge)
        )
        self._video = VideoManager(
            on_frame=lambda img: self.drone_view_page.show_frame(img),
            on_cam_changed=self._on_cam_changed,
        )
        self._conn.set_track_callback(self._video.on_track, on_reset=self._on_session_reset)

        # Подписка на колбэки уровня coordinator (приходят через ConnectionManager.bridge).
        self._bridge.fc_info_received.connect(self._on_fc_info)
        self._bridge.config_received.connect(self._on_cameras_received)
        self._bridge.speed_updated.connect(
            lambda rtt_ms: self.drone_view_page.update_ping(rtt_ms)
        )
        self._bridge.drone_went_offline.connect(self._on_drone_went_offline)
        self._bridge.connect_failed.connect(self._on_connect_failed)
        self._bridge.battery_updated.connect(self._on_battery_updated)
        self._bridge.telemetry_received.connect(self._on_telemetry)
        self._bridge.login_succeeded.connect(self._on_login_succeeded)
        self._bridge.login_failed.connect(self._on_login_failed)
        # Доставки.
        self._bridge.delivery_offered.connect(self._on_delivery_offered)
        self._bridge.delivery_taken.connect(self._on_delivery_taken)
        self._bridge.delivery_accepted.connect(self._on_delivery_accepted)
        self._bridge.delivery_accept_failed.connect(self._on_delivery_accept_failed)

        # Сборка экранов.
        self.login_page = LoginPage(
            on_login=self._handle_login,
            on_forgot_password=self._handle_forgot_password,
            on_open_settings=self._open_settings,
        )
        self.delivery_page = DeliveryPage(
            on_accept=self._handle_accept_delivery,
            on_logout=self._handle_logout,
            on_open_settings=self._open_settings,
            on_open_joystick=self._open_joystick_setup,
        )
        self.drone_view_page = DroneViewPage(
            on_back=self._handle_back_to_deliveries,
            on_prev=lambda: self._video.shift_cam(-1),
            on_next=lambda: self._video.shift_cam(1),
            on_save=self._handle_save_config,
            on_joystick_cfg=self._open_joystick_setup,
            on_takeoff=self._open_joystick_setup,
            on_calibrate=self._handle_calibrate_cameras,
        )
        self.joystick_setup_page = JoystickSetupPage(
            on_back=self._handle_back_from_joystick,
            on_takeoff=self._handle_joystick_selected,
            demo=demo,
        )
        self.settings_page = SettingsPage(on_close=self._close_settings)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.login_page)
        self.stack.addWidget(self.delivery_page)
        self.stack.addWidget(self.drone_view_page)
        self.stack.addWidget(self.joystick_setup_page)
        self.stack.addWidget(self.settings_page)
        self.setCentralWidget(self.stack)
        # Куда возвращаться при закрытии Settings (открыта из login/deliveries).
        self._settings_return_to = self.login_page

        self._flight_window: FlightWindow | None = None
        self._settings_from_flight = False
        self._qgc_overlay: QGCLaunchingOverlay | None = None
        # Следит за активным джойстиком, пока идёт полётная сессия; если
        # стик пропадает в полёте — шлёт дрону один disarm-фрейм.
        self._joystick_guard: JoystickGuard | None = None
        self._joystick_guard_qgc_proc = None  # type: ignore[assignment]
        self._joystick_guard_timer = QTimer(interval=200)
        self._joystick_guard_timer.timeout.connect(self._tick_joystick_guard)
        # Один таймер на 1 Hz гоняет и peer-to-peer ping (send_ping по
        # ping-каналу), и обновление UI (читает обратно last_rtt_ms).
        self._ping_timer = QTimer(interval=1000)
        self._ping_timer.timeout.connect(self._tick_ping)
        # Фоновый слушатель джойстика: для MAVLink-FC при открытом QGC
        # мы продолжаем слушать ARM-кнопку джойстика поверх QGC и шлём
        # MAV_CMD_COMPONENT_ARM_DISARM через packet-channel. Pygame
        # читает /dev/input/eventN — фокус окна не нужен.
        self._arm_joystick = None  # JoystickInput | None
        self._arm_state = False
        # Счётчик подряд-идущих ошибок чтения джойстика: 3 подряд = считаем
        # пропавшим и шлём failsafe AUTO_RTL на PX4 (флаг ниже не даёт
        # повторно отправить RTL после того, как уже отослали).
        self._arm_err_count = 0
        self._failsafe_sent = False
        self._arm_poll_timer = QTimer(interval=100)
        self._arm_poll_timer.timeout.connect(self._poll_arm_button)

        # Активная заявка (для проброса точки назначения на карту полёта).
        self._active_delivery: dict | None = None

        # Старт: тихое восстановление при наличии refresh-токена, иначе вход.
        if self._conn.resume():
            self.stack.setCurrentWidget(self.delivery_page)
        else:
            self.stack.setCurrentWidget(self.login_page)

    #### Навигация #########################################################################
    def _navigate_to(self, widget: QWidget) -> None:
        current = self.stack.currentWidget()
        if current is not widget:
            self._nav_history.append(self.stack.indexOf(current))
        self.stack.setCurrentWidget(widget)

    def _navigate_back(self) -> None:
        if self._nav_history:
            self.stack.setCurrentIndex(self._nav_history.pop())

    #### Аутентификация ####################################################################
    def _handle_login(self, username: str, password: str) -> None:
        self.login_page.set_busy(True)
        self.login_page.set_error('')
        self._conn.login(username, password)

    def _on_login_succeeded(self) -> None:
        self.login_page.set_busy(False)
        self.login_page.set_error('')
        if self.stack.currentWidget() is self.login_page:
            self.stack.setCurrentWidget(self.delivery_page)

    def _on_login_failed(self, reason: str) -> None:
        self.login_page.set_busy(False)
        self.login_page.set_error(reason or 'Не удалось войти')
        if self.stack.currentWidget() is not self.login_page:
            self.stack.setCurrentWidget(self.login_page)

    def _handle_forgot_password(self, email: str) -> None:
        """Запрос восстановления пароля со страницы логина.

        UI уже показал оператору сообщение-подтверждение, здесь просто
        шлём fire-and-forget запрос на сервер (или no-op в демо).
        """
        self._conn.request_password_reset(email)

    def _handle_logout(self) -> None:
        self._ping_timer.stop()
        self._stop_arm_listener()
        self._conn.logout()
        self._video.stop()
        self._video.reset()
        self._active_delivery = None
        self.delivery_page.clear()
        # Сбрасываем форму логина — иначе после logout оператор видит
        # старый forgot-message, заполненный логин и пр.
        self.login_page.reset()
        self.stack.setCurrentWidget(self.login_page)

    #### Заявки на доставку ###############################################################
    def _on_delivery_offered(self, delivery: dict) -> None:
        """Пришла новая заявка — показываем карточку на экране ожидания."""
        try:
            self.delivery_page.add_offer(delivery)
        except Exception as exc:
            logger.warning('[app] ошибка показа заявки: %s', exc)

    def _on_delivery_taken(self, delivery_id: str) -> None:
        """Заявку забрал другой оператор — убираем карточку."""
        self.delivery_page.remove_offer(delivery_id)

    def _handle_accept_delivery(self, delivery: dict) -> None:
        """Кнопка «Принять» на карточке заявки → accept_delivery в coordinator."""
        self._conn.accept_delivery(delivery)

    def _on_delivery_accepted(self, delivery: dict) -> None:
        """Заявка успешно принята (200) — coordinator уже инициировал connect.
        Запоминаем заявку (точка назначения нужна для карты), открываем
        drone-view с видео."""
        self._active_delivery = dict(delivery)
        delivery_id = delivery.get('delivery_id', '')
        self.delivery_page.remove_offer(delivery_id)
        self._state.selected_drone_id = delivery.get('drone_id')
        self._state.cam_index = 0
        self._video.start()
        self._ping_timer.start()
        if not self._demo:
            self.drone_view_page.set_calibration_visible(True)
        self.stack.setCurrentWidget(self.drone_view_page)

    def _on_delivery_accept_failed(self, delivery_id: str, reason: str) -> None:
        """409 / ошибка accept — убираем карточку и поясняем оператору."""
        self.delivery_page.remove_offer(delivery_id)
        QMessageBox.information(
            self, 'Заявку уже забрали',
            reason or 'Эту заявку уже принял другой оператор.',
        )

    def _open_settings(self) -> None:
        """Открыть страницу настроек. Запоминаем, откуда пришли, чтобы
        закрытие вернуло на исходный экран.

        Settings могут открываться и из полётного окна (кнопка-шестерёнка):
        в этом случае временно прячем fullscreen-FlightWindow, показываем
        главное окно с настройками, а на закрытии возвращаем полёт."""
        current = self.stack.currentWidget()
        if current is not self.settings_page:
            self._settings_return_to = current
        self._settings_from_flight = self._flight_window is not None
        if self._settings_from_flight:
            self._flight_window.hide()
            self.showNormal()
            self.raise_()
            self.activateWindow()
        self.stack.setCurrentWidget(self.settings_page)

    def _close_settings(self) -> None:
        if getattr(self, '_settings_from_flight', False) and self._flight_window is not None:
            self._settings_from_flight = False
            self.stack.setCurrentWidget(self.drone_view_page)
            self._flight_window.showFullScreen()
            self._flight_window.raise_()
            self._flight_window.activateWindow()
            # Снова прячем главное окно — на полёт вернулись, одно окно.
            self.hide()
            return
        target = self._settings_return_to or self.login_page
        self.stack.setCurrentWidget(target)

    def _handle_back_to_deliveries(self) -> None:
        """Возврат с drone-view на экран ожидания заявок (оператор прервал
        доставку, не сбросив груз). Сессия с дроном разрывается."""
        # Если полётное окно открыто (например, дрон ушёл в офлайн прямо в
        # полёте) — закрываем его и возвращаем главное окно из hide().
        if self._flight_window is not None:
            self._flight_window.close()  # closeEvent → таймеры/финальный DISARM
            self._flight_window = None
        self.showNormal()
        self._video.stop()
        self._ping_timer.stop()
        self._stop_arm_listener()
        self.drone_view_page.update_ping(-1.0)
        self._conn.disconnect_drone()
        self._video.reset()
        self._state.reset()
        self._active_delivery = None
        self.drone_view_page.set_calibration_visible(False)
        self.drone_view_page.update_fc_status('none', '')
        self.stack.setCurrentWidget(self.delivery_page)

    def _on_battery_updated(self, percent: int, voltage: float) -> None:
        """Раздача CRSF BATTERY_SENSOR: показать на drone-view и, если
        полётное окно открыто — там тоже."""
        self.drone_view_page.update_battery(percent, voltage)
        if self._flight_window is not None:
            try:
                self._flight_window.update_battery(percent, voltage)
            except Exception as exc:
                logger.debug('[app] обновление заряда в полётном окне: %s', exc)

    def _on_telemetry(self, payload: dict) -> None:
        """GPS/heading-телеметрия с борта → карта в полётном окне."""
        if self._flight_window is None:
            return
        args = telemetry_to_args(payload)
        if args is None:
            return
        lat, lon, heading = args
        try:
            self._flight_window.update_telemetry(lat, lon, heading)
        except Exception as exc:
            logger.debug('[app] ошибка обновления карты телеметрией: %s', exc)

    def _on_drone_went_offline(self, drone_id: str) -> None:
        """Coordinator подтвердил, что дрон действительно офлайн (а не
        кратковременный сбой при renegotiation). Если пользователь всё ещё
        смотрит на drone-view, возвращаем его к списку, чтобы он не сидел
        на замороженном кадре."""
        if self.stack.currentWidget() is not self.drone_view_page:
            return
        logger.info('[app] дрон %s офлайн, возврат к заявкам', drone_id)
        self._handle_back_to_deliveries()

    def _on_connect_failed(self, drone_id: str) -> None:
        """Board сбросил peer во время подключения (нет камер / ошибка
        pipeline). Показываем по центру баннер на 3 s, затем возвращаемся к
        списку дронов. Авто-переподключение намеренно не запускаем — причина
        локальна для дрона и повтор просто зациклится."""
        if self.stack.currentWidget() is not self.drone_view_page:
            return
        logger.info('[app] подключение к дрону %s не удалось; показываю баннер', drone_id)
        self.drone_view_page.set_calibration_visible(False)
        self.drone_view_page.show_error_banner('Камеры не найдены')
        QTimer.singleShot(3000, self._dismiss_error_banner_and_back)

    def _dismiss_error_banner_and_back(self) -> None:
        self.drone_view_page.hide_error_banner()
        if self.stack.currentWidget() is self.drone_view_page:
            self._handle_back_to_deliveries()

    def _on_session_reset(self) -> None:
        """Вызывается из connection.ConnectionManager на session_ended.
        Сбрасывает устаревшие треки, но сохраняет выбранный индекс камеры,
        затем — если пользователь всё ещё на drone-view (т.е. идёт авто-
        переподключение после смены параметров или hot-plug камеры) — снова
        показывает overlay калибровки, пока не придёт первый кадр следующей
        сессии. При полном отключении (возврат к заявкам)
        _handle_back_to_deliveries вместо этого зовёт video.reset(), который
        сбрасывает и индекс камеры."""
        self._video.clear_tracks()
        if self.stack.currentWidget() is self.drone_view_page:
            self.drone_view_page.set_calibration_visible(True)

    #### Drone-view: камеры, FC, битрейт, калибровка #######################################
    def _on_cameras_received(self, cameras: list) -> None:
        self._state.cameras = cameras
        self.drone_view_page.save_btn.setEnabled(True)
        self._update_camera_settings_ui()

    def _on_fc_info(self, fc_type: str, fc_name: str) -> None:
        self._state.fc_type = fc_type
        self._state.fc_name = fc_name
        self.drone_view_page.update_fc_status(fc_type, fc_name)
        self.joystick_setup_page.set_fc_type(fc_type or 'none')

    def _on_cam_changed(self, cam_index: int) -> None:
        # Переключение камеры — чисто UI-операция: видеотреки уже идут с борта,
        # таймер просто показывает кадры другого. Никаких пакетов на board
        # не шлём — раньше тут был троттлинг неактивных камер до 200 kbps,
        # но это перезаписывало сохранённый пользователем bitrate в JSON
        # на борту, и при возврате к камере её настройки оказывались
        # потеряны. Теперь каждая камера всегда стримит на своём bitrate'е.
        self._state.cam_index = cam_index
        self._update_camera_settings_ui()

    def _update_camera_settings_ui(self) -> None:
        cameras = self._state.cameras
        idx = self._state.cam_index
        if not cameras or idx >= len(cameras):
            return
        self.drone_view_page.update_camera_settings(cameras[idx])

    def _handle_save_config(self) -> None:
        cameras = self._state.cameras
        idx = self._state.cam_index
        if not cameras or idx >= len(cameras):
            return
        param_index, bitrate = self.drone_view_page.get_selected_params()
        if param_index is None:
            return
        old_cam = cameras[idx]
        cam = dict(old_cam)
        cam['param_index'] = param_index
        cam['bitrate_kbs'] = bitrate
        self._state.cameras[idx] = cam
        self.drone_view_page.save_btn.setEnabled(False)
        coord = self._conn.coordinator
        device_index = cam.get('device_index', idx)
        old_param_index = old_cam.get('param_index')
        logger.info('[app] сохранение: device_index=%s old_param_index=%s new_param_index=%s bitrate=%s',
                    device_index, old_param_index, param_index, bitrate)
        if coord is not None:
            self._conn._submit(coord.send_bitrate_update([
                {'device_index': device_index, 'bitrate_kbs': bitrate},
            ]))
            # Раньше Desktop сам решал нужно ли слать params_update сравнивая
            # старый и новый param_index, но при смене только FPS на той же
            # резолюции эта проверка иногда не триггерилась (state.cameras
            # могло быть рассинхронизировано с board'ом). Теперь шлём
            # всегда — board сам проверит cam.param_index == new и пропустит
            # renegotiation если действительно ничего не изменилось.
            self._conn._submit(coord.send_params_update([
                {'device_index': device_index, 'param_index': param_index},
            ]))
        self.drone_view_page.save_btn.setEnabled(True)

    def _start_arm_listener(self, joystick_index: int, calibration: dict) -> None:
        """Запускает фоновый опрос джойстика для arm-кнопки. Работает,
        пока открыт QGC (или просто пока пользователь залогинен) — pygame
        читает /dev/input/eventN, фокус окна не нужен."""
        from mavixdesktop.joystick.input import JoystickInput
        try:
            self._arm_joystick = JoystickInput(joystick_index, calibration)
        except Exception as exc:
            logger.warning('[app] не удалось инициализировать arm listener: %s', exc)
            self._arm_joystick = None
            return
        self._arm_state = False
        self._arm_poll_timer.start()
        logger.info('[app] arm listener запущен (joystick=%d)', joystick_index)

    def _stop_arm_listener(self) -> None:
        if self._arm_poll_timer.isActive():
            self._arm_poll_timer.stop()
        self._arm_joystick = None
        self._arm_state = False
        self._arm_err_count = 0
        self._failsafe_sent = False

    def _poll_arm_button(self) -> None:
        """Опрос на 10 Hz. pygame.event.pump() обновляет состояние кнопок
        даже когда окно нашего приложения не в фокусе. Если 3 чтения
        подряд упали (или джойстик отвалился) — шлём PX4 AUTO_RTL и
        останавливаем таймер."""
        if self._arm_joystick is None:
            return
        try:
            import pygame
            pygame.event.pump()
            if not self._arm_joystick.is_connected():
                self._arm_err_count += 1
            else:
                new_state = self._arm_joystick.is_armed()
                self._arm_err_count = 0
        except Exception as exc:
            self._arm_err_count += 1
            logger.debug('[app] ошибка опроса джойстика: %s', exc)
        else:
            if self._arm_err_count == 0:
                if new_state != self._arm_state:
                    self._arm_state = new_state
                    self._send_arm_disarm(new_state)
                return
        if self._arm_err_count >= 3 and not self._failsafe_sent:
            logger.warning('[app] джойстик потерян во время полёта MAVLink/QGC — шлём AUTO_RTL')
            self._failsafe_sent = True
            self._send_failsafe_rtl()
            self._stop_arm_listener()

    def _send_arm_disarm(self, armed: bool) -> None:
        """Шлёт MAV_CMD_COMPONENT_ARM_DISARM через packet channel.
        Команда долетит до PX4 параллельно с трафиком QGC."""
        from mavixdesktop.fc.mavlink_encoder import MavlinkEncoder
        coord = self._conn.coordinator
        if coord is None or coord._manager is None or coord._manager.channels is None:
            return
        ch = coord._manager.channels.packet
        if ch is None:
            return
        try:
            enc = MavlinkEncoder()
            packet = enc.arm_disarm(armed, force=True)
            if self._conn._loop is not None:
                self._conn._loop.call_soon_threadsafe(ch.send_bytes, packet)
            logger.info('[app] джойстик → команда %s на PX4', 'ARM' if armed else 'DISARM')
        except Exception as exc:
            logger.warning('[app] ошибка отправки arm: %s', exc)

    def _send_failsafe_rtl(self) -> None:
        """Шлёт PX4 AUTO_RTL через packet channel — дрон автономно
        вернётся на точку взлёта. Используется при потере джойстика
        в режиме MAVLink+QGC (наш FlightWindow в passive сам RTL тоже
        отправит, но если он закрыт, fallback срабатывает здесь)."""
        from mavixdesktop.fc.mavlink_encoder import MavlinkEncoder
        coord = self._conn.coordinator
        if coord is None or coord._manager is None or coord._manager.channels is None:
            return
        ch = coord._manager.channels.packet
        if ch is None:
            return
        try:
            enc = MavlinkEncoder()
            packet = enc.failsafe_rtl()
            if self._conn._loop is not None:
                for _ in range(3):
                    self._conn._loop.call_soon_threadsafe(ch.send_bytes, packet)
            logger.info('[app] команда AUTO_RTL отправлена на PX4')
        except Exception as exc:
            logger.warning('[app] ошибка отправки failsafe: %s', exc)

    def _handle_calibrate_cameras(self) -> None:
        coord = self._conn.coordinator
        if coord is None:
            return
        self._conn._submit(coord.send_calibrate())
        logger.info('[app] команда принудительной калибровки отправлена')

    #### Джойстик и полёт ##################################################################
    def _open_joystick_setup(self) -> None:
        self._navigate_to(self.joystick_setup_page)

    def _handle_back_from_joystick(self) -> None:
        self._navigate_back()

    def _handle_joystick_selected(self, joystick_index: int, calibration: dict) -> None:
        """CRSF — наш FlightWindow (joystick → CRSF-фрейм → board → UART).
        MAVLink — параллельно запускаем QGroundControl (он сам шлёт
        MANUAL_CONTROL) и открываем наш passive FlightWindow, чтобы
        смотреть видео. Arm-кнопку джойстика слушает фоновый таймер."""
        coord = self._conn.coordinator
        fc_kind = coord.fc_kind if coord is not None else 'crsf'
        if fc_kind == 'mavlink':
            # SDL_GAMECONTROLLERCONFIG передаётся в QGC через env-var при
            # старте процесса — в уже запущенный инстанс инжектировать
            # его нельзя. Проверка идёт через QSharedMemory с ключом QGC
            # «QGroundControlRunGuardKey» (тем же, что сам QGC использует
            # для single-instance lock); pgrep/proc/Popen.poll ловили
            # wrapper-родителя AppImage/.deb и врали.
            if is_qgc_running():
                logger.info('[app] QGC уже запущен — просим пользователя закрыть его')
                QMessageBox.warning(
                    self, 'Закройте QGroundControl',
                    'QGroundControl уже запущен. Закройте его и нажмите '
                    '«Взлёт» ещё раз — приложение запустит QGC с нужной '
                    'конфигурацией джойстика.',
                )
                return
            sdl_config = calibration.get('sdl_gamecontrollerconfig', '')
            logger.info('[app] MAVLink: запускаем QGC, joystick=%d', joystick_index)
            proc = launch_qgc(sdl_config)
            if proc is None:
                proc = self._launch_qgc_with_user_pick(sdl_config)
            if proc is None:
                logger.warning('[app] QGC не найден; полётное окно работает без него')
            else:
                logger.info('[app] MAVLink: создаём overlay')
                self._qgc_overlay = QGCLaunchingOverlay(qgc_proc=proc)
                logger.info('[app] MAVLink: показываем overlay')
                self._qgc_overlay.show_centered()
                logger.info('[app] MAVLink: overlay показан')
            logger.info('[app] MAVLink: открываем passive FlightWindow')
            # Фоновый слушатель ARM-кнопки джойстика: pygame читает
            # /dev/input/eventN на 10 Hz (фокус окна не нужен) и шлёт ARM/DISARM
            # в PX4 через packet-канал параллельно трафику QGC, а при потере
            # джойстика — AUTO_RTL. QGC не захватывает устройство эксклюзивно,
            # поэтому читать его одновременно безопасно (проверено на реальном
            # дроне в remote_control).
            self._start_arm_listener(joystick_index, calibration)
            self._open_flight_window(joystick_index, calibration, passive=True)
            return
        self._open_flight_window(joystick_index, calibration)

    def _launch_qgc_with_user_pick(self, sdl_config: str):
        """Открыть диалог выбора файла, сохранить путь и повторить запуск."""
        if platform.system() == 'Windows':
            filt = 'QGroundControl (QGroundControl*.exe);;Executable (*.exe);;All files (*)'
        else:
            filt = 'QGroundControl (QGroundControl* qgroundcontrol* *.AppImage);;All files (*)'
        ans = QMessageBox.question(
            self, 'QGroundControl не найден',
            'QGroundControl не удалось найти автоматически.\n'
            'Указать путь к исполняемому файлу вручную?',
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if ans != QMessageBox.Yes:
            return None
        start_dir = str(Path.home())
        picked, _ = QFileDialog.getOpenFileName(
            self, 'Выберите исполняемый файл QGroundControl', start_dir, filt,
        )
        if not picked:
            return None
        path = Path(picked)
        if not path.is_file():
            QMessageBox.warning(self, 'QGroundControl', 'Указанный файл не существует.')
            return None
        save_qgc_path(path)
        proc = launch_qgc(sdl_config)
        if proc is None:
            QMessageBox.warning(
                self, 'QGroundControl',
                'Не удалось запустить выбранный файл. Проверьте, что это исполняемый файл QGroundControl.',
            )
        return proc

    def _open_flight_window(self, joystick_index: int, calibration: dict,
                            passive: bool = False, js=None) -> None:
        from mavixdesktop.joystick.input import JoystickInput
        # JoystickInput создаём и в passive: окно показывает реальный
        # ARM/DISARM с джойстика и читает кнопку сброса груза. В passive окно
        # НЕ шлёт RC-кадры сам (см. guard в FlightWindow.__update_joystick) —
        # полётом рулит QGC, ARM/DISARM шлёт фоновый _arm_listener.
        try:
            js_input = js if js is not None else JoystickInput(joystick_index, calibration)
        except Exception as exc:
            logger.warning('[app] не удалось открыть джойстик для окна: %s', exc)
            js_input = None

        logger.info('[app] flight_window: video.stop()')
        # Останавливаем ТОЛЬКО таймер отрисовки видео (как в remote_control).
        # Раньше здесь была остановка decoder-приёмников через приватные методы
        # aiortc (recv._handle_disconnect) + cross-thread cancel задач —
        # «защита» от мнимого сброса H.264 при открытии QGC. Премиса ошибочна:
        # QGC общается с полётником по MAVLink/UDP и НЕ трогает наш WebRTC-
        # видеопоток с борта. Эта возня с внутренностями aiortc повреждала
        # состояние loop/декодера и приводила к зависанию окна. Убрано —
        # поведение приведено к рабочему remote_control: декодер живёт дальше,
        # просто не рисуем.
        self._video.stop()
        coord = self._conn.coordinator
        fc_kind = coord.fc_kind if coord is not None else 'crsf'
        logger.info('[app] flight_window: создаём FlightWindow (passive=%s, js=%s)', passive, js_input)
        self._flight_window = FlightWindow(
            joystick_input=js_input,
            signalling=_CoordinatorAdapter(self._conn),
            get_frame=lambda cam_idx: self._video.get_frame(cam_idx),
            cam_count=lambda: self._video.cam_count,
            loop=self._conn._loop,
            on_close=self._handle_flight_closed,
            fc_kind=fc_kind,
            passive=passive,
            on_drop=self._conn.mark_delivered,
            on_open_settings=self._open_settings,
        )
        logger.info('[app] flight_window: FlightWindow создан')
        # Точка назначения из принятой заявки → маркер на карте.
        if self._active_delivery is not None:
            try:
                lat = float(self._active_delivery.get('destination_lat'))
                lon = float(self._active_delivery.get('destination_lon'))
                self._flight_window.set_destination(lat, lon)
            except (TypeError, ValueError):
                logger.debug('[app] заявка без координат назначения — маркер не ставим')
        # Переходим на drone_view чтобы скрыть JoystickSetupPage и остановить
        # её _auto_refresh_timer: тот каждые 3 с вызывает pygame.event.pump()
        # через list_joysticks() → SIGSEGV когда QGC уже EVIOCGRAB'ил джойстик.
        logger.info('[app] flight_window: navigating to drone_view_page')
        self.stack.setCurrentWidget(self.drone_view_page)
        logger.info('[app] flight_window: showFullScreen()')
        self._flight_window.showFullScreen()
        # Прячем главное окно, пока открыт полётный экран — чтобы у приложения
        # было ровно ОДНО видимое окно (раньше предпросмотр/настройки и
        # полётное окно висели в alt-tab одновременно). Возврат показывает его
        # снова (_handle_flight_closed / _handle_back_to_deliveries).
        self.hide()
        logger.info('[app] flight_window: готово')
        if not passive:
            self._start_joystick_guard(joystick_index, calibration, js=js_input)

    def _handle_flight_closed(self) -> None:
        self._stop_joystick_guard()
        self._stop_arm_listener()
        self._flight_window = None
        self.showNormal()
        self.stack.setCurrentWidget(self.drone_view_page)
        self._video.start()

    #### Joystick guard ####################################################################
    def _start_joystick_guard(
        self,
        joystick_index: int,
        calibration: dict,
        js=None,
        qgc_proc=None,
    ) -> None:
        fc_type = self._state.fc_type
        if fc_type not in ('crsf', 'mavlink'):
            return
        if js is None:
            from mavixdesktop.joystick.input import JoystickInput
            try:
                js = JoystickInput(joystick_index, calibration)
            except Exception as exc:
                logger.warning('[app] joystick guard пропущен: не удалось открыть джойстик: %s', exc)
                return
        self._joystick_guard = JoystickGuard(
            js=js,
            fc_type=fc_type,
            send_frame=self._conn.send_joystick_frame,
            on_disarm=self._on_guard_disarm,
        )
        self._joystick_guard_qgc_proc = qgc_proc
        self._joystick_guard_timer.start()
        logger.info('[app] joystick guard активирован (%s)', fc_type)

    def _stop_joystick_guard(self) -> None:
        if self._joystick_guard is None and not self._joystick_guard_timer.isActive():
            return
        self._joystick_guard_timer.stop()
        self._joystick_guard = None
        self._joystick_guard_qgc_proc = None

    def _tick_joystick_guard(self) -> None:
        guard = self._joystick_guard
        if guard is None:
            self._joystick_guard_timer.stop()
            return
        guard.tick()
        # В MAVLink-ветке нет FlightWindow, чтобы вести жизненный цикл, —
        # выходим, как только сам QGC исчез (пользователь его закрыл).
        # CRSF-ветка останавливается из _handle_flight_closed.
        proc = self._joystick_guard_qgc_proc
        if proc is not None and proc.poll() is not None:
            logger.info('[app] joystick guard остановлен (QGC завершился)')
            self._stop_joystick_guard()

    def _on_guard_disarm(self) -> None:
        QMessageBox.warning(
            self, 'Джойстик отключён',
            'Связь с джойстиком потеряна. Дрону отправлена команда DISARM.',
        )

    #### Peer-to-peer ping #################################################################
    def _tick_ping(self) -> None:
        """Отправляет один ping по peer-каналу ping и обновляет UI
        последним измеренным RTT. send_ping диспатчится в asyncio event
        loop через call_soon_threadsafe — RTCDataChannel.send нельзя
        безопасно звать из Qt-потока напрямую (он планирует на своём loop
        через call_soon, и вызов тихо теряется, если это не текущий
        поток)."""
        coord = self._conn.coordinator
        if coord is None or coord._manager is None or coord._manager.channels is None:
            return
        ping_ch = coord._manager.channels.ping
        if ping_ch is None:
            return
        loop = self._conn._loop
        if loop is not None:
            loop.call_soon_threadsafe(ping_ch.send_ping)
        rtt = ping_ch.last_rtt_ms if ping_ch.last_rtt_ms is not None else -1.0
        self._bridge.speed_updated.emit(rtt)


#### Адаптер для FlightWindow ##########################################################
class _CoordinatorAdapter:
    """Тонкая прослойка, чтобы FlightWindow (ожидающий устаревший
    Signalling-API) мог общаться с новым Coordinator. Пробрасываются только
    методы, которые FlightWindow реально использует; остальное возвращает
    безобидные значения по умолчанию."""

    def __init__(self, conn: ConnectionManager) -> None:
        self._conn = conn

    @property
    def webrtc(self):
        return self

    @property
    def peer_ping_ms(self) -> float:
        coord = self._conn.coordinator
        if coord is None or coord._manager is None or coord._manager.channels is None:
            return -1.0
        ping_ch = coord._manager.channels.ping
        return ping_ch.last_rtt_ms if (ping_ch and ping_ch.last_rtt_ms is not None) else -1.0

    @property
    def crsf_receiver(self):
        return None

    @property
    def drone_id(self) -> str | None:
        coord = self._conn.coordinator
        return coord._target_drone_id if coord is not None else None

    def send_crsf_packet(self, frame: bytes) -> None:
        self._conn.send_joystick_frame(frame)
