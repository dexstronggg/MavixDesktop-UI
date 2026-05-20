"""Main Qt window for MavixDesktop.

Flow: login → drone list → DroneViewPage (video + settings) → optional
JoystickSetupPage → FlightWindow.

Wires the PySide6 UI to mavixdesktop.coordinator.SessionCoordinator
through ConnectionManager (which adapts the async loop to Qt signals)
and VideoManager (which drives a 33 ms QTimer over the aiortc track
queue and pushes BGR frames to DroneViewPage.show_frame).
"""
from __future__ import annotations

import platform
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QMainWindow, QStackedWidget, QMessageBox, QFileDialog

from mavixdesktop.core.logger import logger
from mavixdesktop.joystick.guard import JoystickGuard
from mavixdesktop.qgc.launcher import is_qgc_running, launch_qgc, save_qgc_path
from mavixdesktop.ui.login_page import LoginPage
from mavixdesktop.ui.managers.connection import ConnectionManager
from mavixdesktop.ui.managers.demo_connection import DemoConnectionManager
from mavixdesktop.ui.managers.video import VideoManager
from mavixdesktop.ui.screens.bridge import Bridge
from mavixdesktop.ui.screens.drone_list_page import DroneListPage
from mavixdesktop.ui.screens.drone_view import DroneViewPage
from mavixdesktop.ui.screens.flight_window import FlightWindow
from mavixdesktop.ui.screens.joystick_setup import JoystickSetupPage, QGCLaunchingOverlay
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
            logger.warning('[app] pygame.init failed: %s', exc)

        self._state = SessionState()
        self._nav_history: list[int] = []
        self._bridge = Bridge()

        # Demo-режим подменяет настоящий ConnectionManager заглушкой
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

        # Bind coordinator-level callbacks (forwarded via ConnectionManager.bridge)
        self._bridge.client_list_updated.connect(self._on_drones)
        self._bridge.fc_info_received.connect(self._on_fc_info)
        self._bridge.config_received.connect(self._on_cameras_received)
        self._bridge.speed_updated.connect(
            lambda rtt_ms: self.drone_view_page.update_ping(rtt_ms)
        )
        self._bridge.drone_went_offline.connect(self._on_drone_went_offline)
        self._bridge.connect_failed.connect(self._on_connect_failed)
        self._bridge.battery_updated.connect(self._on_battery_updated)
        self._bridge.login_succeeded.connect(self._on_login_succeeded)
        self._bridge.login_failed.connect(self._on_login_failed)

        # Build pages
        self.login_page = LoginPage(on_login=self._handle_login)
        self.drone_list_page = DroneListPage(
            on_select=self._handle_select_drone,
            on_refresh=self._handle_refresh,
            on_logout=self._handle_logout,
            on_joystick_cfg=self._open_joystick_setup,
        )
        self.drone_view_page = DroneViewPage(
            on_back=self._handle_back_to_list,
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

        self.stack = QStackedWidget()
        self.stack.addWidget(self.login_page)
        self.stack.addWidget(self.drone_list_page)
        self.stack.addWidget(self.drone_view_page)
        self.stack.addWidget(self.joystick_setup_page)
        self.setCentralWidget(self.stack)

        self._flight_window: FlightWindow | None = None
        self._qgc_overlay: QGCLaunchingOverlay | None = None
        # Watches the active joystick while a flight session is live; if the
        # stick disappears mid-flight, fires one disarm frame to the drone.
        self._joystick_guard: JoystickGuard | None = None
        self._joystick_guard_qgc_proc = None  # type: ignore[assignment]
        self._joystick_guard_timer = QTimer(interval=200)
        self._joystick_guard_timer.timeout.connect(self._tick_joystick_guard)
        # Single 1Hz timer drives both the peer-to-peer ping (send_ping on the
        # ping data-channel) and the UI refresh (reads back last_rtt_ms).
        self._ping_timer = QTimer(interval=1000)
        self._ping_timer.timeout.connect(self._tick_ping)
        # Background joystick listener: для MAVLink-FC при открытом QGC
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

        # Periodically refresh the drone list while the list page is visible
        self._drone_list_refresh_timer = QTimer(interval=5000)
        self._drone_list_refresh_timer.timeout.connect(self._tick_drone_list_refresh)

        # Bootstrap: silent resume if we have a refresh token, otherwise login
        if self._conn.resume():
            self.stack.setCurrentWidget(self.drone_list_page)
            QTimer.singleShot(500, self._conn.request_drone_list)
            self._drone_list_refresh_timer.start()
        else:
            self.stack.setCurrentWidget(self.login_page)

    def _tick_drone_list_refresh(self) -> None:
        if self.stack.currentWidget() is self.drone_list_page:
            self._conn.request_drone_list()
        else:
            # Stop polling when the user navigates away; resume in _handle_*
            self._drone_list_refresh_timer.stop()

    # ── Navigation helpers ────────────────────────────────────────────────────

    def _navigate_to(self, widget) -> None:
        current = self.stack.currentWidget()
        if current is not widget:
            self._nav_history.append(self.stack.indexOf(current))
        self.stack.setCurrentWidget(widget)

    def _navigate_back(self) -> None:
        if self._nav_history:
            self.stack.setCurrentIndex(self._nav_history.pop())

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _handle_login(self, email: str, password: str) -> None:
        self.login_page.set_busy(True)
        self.login_page.set_error('')
        self._conn.login(email, password)

    def _on_login_succeeded(self) -> None:
        self.login_page.set_busy(False)
        self.login_page.set_error('')
        if self.stack.currentWidget() is self.login_page:
            self.stack.setCurrentWidget(self.drone_list_page)
        QTimer.singleShot(500, self._conn.request_drone_list)
        self._drone_list_refresh_timer.start()

    def _on_login_failed(self, reason: str) -> None:
        self.login_page.set_busy(False)
        self.login_page.set_error(reason or 'Не удалось войти')
        if self.stack.currentWidget() is not self.login_page:
            self.stack.setCurrentWidget(self.login_page)

    def _handle_logout(self) -> None:
        self._ping_timer.stop()
        self._stop_arm_listener()
        self._drone_list_refresh_timer.stop()
        self._conn.logout()
        self._video.stop()
        self._video.reset()
        self.stack.setCurrentWidget(self.login_page)

    # ── Drone list / selection ────────────────────────────────────────────────

    def _on_drones(self, drones: list[dict]) -> None:
        try:
            self.drone_list_page.update(drones)
        except Exception as exc:
            logger.warning('[app] drone list update error: %s', exc)

    def _handle_refresh(self) -> None:
        self._conn.request_drone_list()

    def _handle_select_drone(self, drone_id: str) -> None:
        if not drone_id:
            return
        self._state.selected_drone_id = drone_id
        self._state.cam_index = 0
        self._conn.select_drone(drone_id)
        self._video.start()
        # Ping is shown all the time the WebRTC session is up; no toggle
        # button anymore. It's cheap (8 bytes/s) and the operator always
        # wants a glanceable latency indicator while flying.
        self._ping_timer.start()
        self._drone_list_refresh_timer.stop()
        # В демо overlay калибровки не нужен и его нечем погасить — кадров
        # с камеры нет, а именно первый frame сбрасывает overlay в реальной
        # сессии. Без этого условия overlay висел бы поверх всего drone-view.
        if not self._demo:
            self.drone_view_page.set_calibration_visible(True)
        self.stack.setCurrentWidget(self.drone_view_page)

    def _handle_back_to_list(self) -> None:
        self._video.stop()
        self._ping_timer.stop()
        self._stop_arm_listener()
        self.drone_view_page.update_ping(-1.0)
        self._conn.disconnect_drone()
        self._video.reset()
        self._state.reset()
        self.drone_view_page.set_calibration_visible(False)
        self.drone_view_page.update_fc_status('none', '')
        self.stack.setCurrentWidget(self.drone_list_page)
        self._drone_list_refresh_timer.start()
        self._conn.request_drone_list()

    def _on_battery_updated(self, percent: int, voltage: float) -> None:
        """CRSF BATTERY_SENSOR fan-out: показать на drone-view и, если
        полётное окно открыто — там тоже."""
        self.drone_view_page.update_battery(percent, voltage)
        if self._flight_window is not None:
            try:
                self._flight_window.update_battery(percent, voltage)
            except Exception as exc:
                logger.debug('[app] flight window battery update: %s', exc)

    def _on_drone_went_offline(self, drone_id: str) -> None:
        """Coordinator confirmed the drone is genuinely offline (not just a
        renegotiation blip). If the user is still staring at drone-view,
        bounce them back to the list so they don't sit on a frozen frame."""
        if self.stack.currentWidget() is not self.drone_view_page:
            return
        logger.info('[app] drone %s offline, returning to list', drone_id)
        self._handle_back_to_list()

    def _on_connect_failed(self, drone_id: str) -> None:
        """Board dropped the peer during connect (no cameras / pipeline error).
        Show a centered banner for 3s, then bounce back to the drone list.
        Auto-reconnect is intentionally not engaged — the cause is local to
        the drone and retrying would just loop."""
        if self.stack.currentWidget() is not self.drone_view_page:
            return
        logger.info('[app] connect to drone %s failed; showing banner', drone_id)
        self.drone_view_page.set_calibration_visible(False)
        self.drone_view_page.show_error_banner('Камеры не найдены')
        QTimer.singleShot(3000, self._dismiss_error_banner_and_back)

    def _dismiss_error_banner_and_back(self) -> None:
        self.drone_view_page.hide_error_banner()
        if self.stack.currentWidget() is self.drone_view_page:
            self._handle_back_to_list()

    def _on_session_reset(self) -> None:
        """Called from connection.ConnectionManager on session_ended. Drops
        stale tracks but preserves the user's selected camera index, then —
        if the user is still on the drone view (i.e. an auto-reconnect is in
        flight after a params change or camera hot-plug) — re-shows the
        calibration overlay until the first frame of the next session arrives.
        For a full disconnect (back to list), _handle_back_to_list calls
        video.reset() instead, which also resets the camera index."""
        self._video.clear_tracks()
        if self.stack.currentWidget() is self.drone_view_page:
            self.drone_view_page.set_calibration_visible(True)

    # ── Drone view: cameras, FC, bitrate, calibrate ───────────────────────────

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
        logger.info('[app] save: device_index=%s old_param_index=%s new_param_index=%s bitrate=%s',
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
        """Запустить фоновый poll джойстика для arm-кнопки. Работает
        пока открыт QGC (или просто пока юзер залогинен) — пайгейм
        читает /dev/input/eventN, фокус окна не нужен."""
        from mavixdesktop.joystick.input import JoystickInput
        try:
            self._arm_joystick = JoystickInput(joystick_index, calibration)
        except Exception as exc:
            logger.warning('[app] arm listener init failed: %s', exc)
            self._arm_joystick = None
            return
        self._arm_state = False
        self._arm_poll_timer.start()
        logger.info('[app] arm listener started (joystick=%d)', joystick_index)

    def _stop_arm_listener(self) -> None:
        if self._arm_poll_timer.isActive():
            self._arm_poll_timer.stop()
        self._arm_joystick = None
        self._arm_state = False
        self._arm_err_count = 0
        self._failsafe_sent = False

    def _poll_arm_button(self) -> None:
        """10Hz polling. pygame.event.pump() обновляет состояние кнопок
        даже когда окно нашего приложения не в фокусе. Если 3 чтения
        подряд упали (или джойстик отвалился) — шлём PX4 AUTO_RTL и
        стопаем таймер."""
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
            logger.debug('[app] arm poll error: %s', exc)
        else:
            if self._arm_err_count == 0:
                if new_state != self._arm_state:
                    self._arm_state = new_state
                    self._send_arm_disarm(new_state)
                return
        if self._arm_err_count >= 3 and not self._failsafe_sent:
            logger.warning('[app] joystick lost during MAVLink/QGC flight — sending AUTO_RTL')
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
            logger.info('[app] joystick → %s command to PX4', 'ARM' if armed else 'DISARM')
        except Exception as exc:
            logger.warning('[app] arm send error: %s', exc)

    def _send_failsafe_rtl(self) -> None:
        """Шлёт PX4 AUTO_RTL через packet channel — дрон автономно
        вернётся на точку взлёта. Используется при потере джойстика
        в режиме MAVLink+QGC (наш FlightWindow в passive — сам RTL
        тоже отправит, но если он закрыт, fallback срабатывает здесь)."""
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
            logger.info('[app] AUTO_RTL command sent to PX4')
        except Exception as exc:
            logger.warning('[app] failsafe send error: %s', exc)

    def _handle_calibrate_cameras(self) -> None:
        coord = self._conn.coordinator
        if coord is None:
            return
        self._conn._submit(coord.send_calibrate())
        logger.info('[app] force-calibration command sent')

    # ── Joystick / flight ─────────────────────────────────────────────────────

    def _open_joystick_setup(self) -> None:
        self._navigate_to(self.joystick_setup_page)

    def _handle_back_from_joystick(self) -> None:
        self._navigate_back()

    def _handle_joystick_selected(self, joystick_index: int, calibration: dict) -> None:
        """CRSF — наш FlightWindow (joystick → CRSF фрейм → board → UART).
        MAVLink — параллельно запускаем QGroundControl (он сам шлёт
        MANUAL_CONTROL) И открываем наш passive FlightWindow чтобы
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
            proc = launch_qgc(sdl_config)
            if proc is None:
                proc = self._launch_qgc_with_user_pick(sdl_config)
            if proc is None:
                logger.warning('[app] QGC не найден; flight-окно работает без него')
            else:
                self._qgc_overlay = QGCLaunchingOverlay(qgc_proc=proc)
                self._qgc_overlay.show_centered()
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
                             passive: bool = False) -> None:
        from mavixdesktop.joystick.input import JoystickInput
        js_input = JoystickInput(joystick_index, calibration)

        self._video.stop()
        coord = self._conn.coordinator
        fc_kind = coord.fc_kind if coord is not None else 'crsf'
        self._flight_window = FlightWindow(
            joystick_input=js_input,
            signalling=_CoordinatorAdapter(self._conn),
            get_frame=lambda cam_idx: self._video.get_frame(cam_idx),
            cam_count=lambda: self._video.cam_count,
            loop=self._conn._loop,
            on_close=self._handle_flight_closed,
            fc_kind=fc_kind,
            passive=passive,
        )
        self._flight_window.showFullScreen()
        self._start_joystick_guard(joystick_index, calibration, js=js_input)

    def _handle_flight_closed(self) -> None:
        self._stop_joystick_guard()
        self._flight_window = None
        self.showNormal()
        self.stack.setCurrentWidget(self.drone_view_page)
        self._video.start()

    # ── Joystick guard ────────────────────────────────────────────────────────

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
                logger.warning('[app] joystick guard skipped: cannot open joystick: %s', exc)
                return
        self._joystick_guard = JoystickGuard(
            js=js,
            fc_type=fc_type,
            send_frame=self._conn.send_joystick_frame,
            on_disarm=self._on_guard_disarm,
        )
        self._joystick_guard_qgc_proc = qgc_proc
        self._joystick_guard_timer.start()
        logger.info('[app] joystick guard armed (%s)', fc_type)

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
        # MAVLink path has no FlightWindow to drive lifecycle from — bail out
        # once QGC itself is gone (user closed it). CRSF path is stopped from
        # _handle_flight_closed.
        proc = self._joystick_guard_qgc_proc
        if proc is not None and proc.poll() is not None:
            logger.info('[app] joystick guard stopped (QGC exited)')
            self._stop_joystick_guard()

    def _on_guard_disarm(self) -> None:
        QMessageBox.warning(
            self, 'Джойстик отключён',
            'Связь с джойстиком потеряна. Дрону отправлена команда DISARM.',
        )

    # ── Peer-to-peer ping ─────────────────────────────────────────────────────

    def _tick_ping(self) -> None:
        """Fire one ping over the peer ping data-channel and refresh the
        UI with the last measured RTT. send_ping is dispatched to the
        asyncio loop via call_soon_threadsafe — RTCDataChannel.send is
        not safe to call from the Qt thread directly (it schedules on
        its own loop with call_soon, which silently drops if it isn't
        the current thread)."""
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


class _CoordinatorAdapter:
    """Thin shim so FlightWindow (which expects the legacy Signalling API)
    can talk to the new Coordinator. Only the methods FlightWindow actually
    uses are forwarded; everything else returns harmless defaults."""

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
