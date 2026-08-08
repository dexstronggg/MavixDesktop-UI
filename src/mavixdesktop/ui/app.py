"""Main Qt window of MavixDesktop."""
from __future__ import annotations

import asyncio
import platform
import subprocess
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QThread, QTimer, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QWidget,
)

from mavixdesktop.core.config import settings
from mavixdesktop.core.logger import logger
from mavixdesktop.joystick.guard import JoystickGuard
from mavixdesktop.qgc.launcher import (
    find_qgc,
    is_qgc_running,
    launch_qgc,
    save_qgc_path,
)
from mavixdesktop.ui.login_page import LoginPage
from mavixdesktop.ui.managers.connection import ConnectionManager
from mavixdesktop.ui.managers.demo_connection import DemoConnectionManager
from mavixdesktop.ui.managers.quality import (
    STALE_FRAME_MS,
    LinkQuality,
    LinkSnapshot,
    format_quality_line,
    format_stats_table,
)
from mavixdesktop.ui.managers.video import VideoManager
from mavixdesktop.ui.screens.bridge import Bridge
from mavixdesktop.ui.screens.debug_page import DebugPage
from mavixdesktop.ui.screens.drone_list_page import DroneListPage
from mavixdesktop.ui.screens.drone_view import DroneViewPage
from mavixdesktop.ui.screens.flight_window import FlightWindow
from mavixdesktop.ui.screens.joystick_setup import (
    JoystickSetupPage,
    QGCLaunchingOverlay,
    QGCSearchOverlay,
)
from mavixdesktop.ui.screens.settings_page import SettingsPage
from mavixdesktop.ui.state import SessionState

if TYPE_CHECKING:
    from mavixdesktop.joystick.input import JoystickInput


class _QgcFindWorker(QThread):
    found = Signal(object)

    def run(self) -> None:
        try:
            result = find_qgc()
        except Exception as exc:
            logger.warning('[app] фоновый поиск QGC упал: %s', exc)
            result = None
        self.found.emit(result)


class App(QMainWindow):
    def __init__(self, demo: bool = False, debug: bool = False) -> None:
        super().__init__()
        self._demo = demo
        self._debug = debug
        title = 'Mavix · ДЕМО-РЕЖИМ' if demo else 'Mavix'
        self.setWindowTitle(title)
        self.setMinimumSize(1, 1)
        self.resize(1300, 600)

        try:
            import pygame
            pygame.init()
        except Exception as exc:
            logger.warning('[app] не удалось выполнить pygame.init: %s', exc)

        self._state = SessionState()
        self._nav_history: list[int] = []
        self._bridge = Bridge()

        self._conn: ConnectionManager = (
            cast(ConnectionManager, DemoConnectionManager(bridge=self._bridge))
            if demo else
            ConnectionManager(bridge=self._bridge)
        )
        self._quality = LinkQuality()
        self._last_freeze_count = 0
        self._video = VideoManager(
            on_frame=lambda img: self.drone_view_page.show_frame(img),
            on_cam_changed=self._on_cam_changed,
            on_frame_shown=self._quality.on_frame_shown,
        )
        self._conn.set_quality_sink(self._quality.update_inbound, self._on_board_stats)
        self._conn.set_track_callback(self._video.on_track)

        self._bridge.client_list_updated.connect(self._on_drones)
        self._bridge.fc_info_received.connect(self._on_fc_info)
        self._bridge.config_received.connect(self._on_cameras_received)
        self._bridge.drone_went_offline.connect(self._on_drone_went_offline)
        self._bridge.connect_failed.connect(self._on_connect_failed)
        self._bridge.error_occurred.connect(self._on_server_error)
        self._bridge.battery_updated.connect(self._on_battery_updated)
        self._bridge.login_succeeded.connect(self._on_login_succeeded)
        self._bridge.login_failed.connect(self._on_login_failed)
        self._bridge.session_reset.connect(self._on_session_reset)

        self.login_page = LoginPage(
            on_login=self._handle_login,
            on_forgot_password=self._handle_forgot_password,
            on_open_settings=self._open_settings,
        )
        self.drone_list_page = DroneListPage(
            on_select=self._handle_select_drone,
            on_refresh=self._handle_refresh,
            on_logout=self._handle_logout,
            on_joystick_cfg=self._open_joystick_setup,
            on_open_settings=self._open_settings,
            on_delete_drone=self._handle_delete_drone,
        )
        self.drone_view_page: DroneViewPage = DroneViewPage(
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
        self.settings_page = SettingsPage(on_close=self._close_settings)
        self.debug_page = (
            DebugPage(on_launch_qgc=self._debug_launch_qgc) if debug else None
        )

        self.stack = QStackedWidget()
        self.stack.addWidget(self.login_page)
        self.stack.addWidget(self.drone_list_page)
        self.stack.addWidget(self.drone_view_page)
        self.stack.addWidget(self.joystick_setup_page)
        self.stack.addWidget(self.settings_page)
        if self.debug_page is not None:
            self.stack.addWidget(self.debug_page)
        self.setCentralWidget(self.stack)
        self._settings_return_to: QWidget = self.login_page

        self._flight_window: FlightWindow | None = None
        self._qgc_overlay: QGCLaunchingOverlay | None = None
        self._qgc_search_overlay: QGCSearchOverlay | None = None
        self._qgc_search_thread: _QgcFindWorker | None = None
        self._joystick_guard: JoystickGuard | None = None
        self._joystick_guard_qgc_proc: subprocess.Popen[bytes] | None = None
        self._joystick_guard_timer = QTimer(interval=200)
        self._joystick_guard_timer.timeout.connect(self._tick_joystick_guard)
        self._ping_timer = QTimer(interval=200)
        self._ping_timer.timeout.connect(self._tick_ping)
        self._quality_timer = QTimer(interval=1000)
        self._quality_timer.timeout.connect(self._tick_quality)
        self._arm_joystick: JoystickInput | None = None
        self._arm_state = False
        self._arm_err_count = 0
        self._failsafe_sent = False
        self._arm_poll_timer = QTimer(interval=100)
        self._arm_poll_timer.timeout.connect(self._poll_arm_button)

        self._drone_list_refresh_timer = QTimer(interval=5000)
        self._drone_list_refresh_timer.timeout.connect(self._tick_drone_list_refresh)

        if self.debug_page is not None:
            self.stack.setCurrentWidget(self.debug_page)
            return

        if self._conn.resume():
            self.stack.setCurrentWidget(self.drone_list_page)
            QTimer.singleShot(500, self._conn.request_drone_list)
            self._drone_list_refresh_timer.start()
        else:
            self.stack.setCurrentWidget(self.login_page)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._send_disconnect_on_close()
        super().closeEvent(event)

    def _send_disconnect_on_close(self) -> None:
        conn = self._conn
        if not isinstance(conn, ConnectionManager):
            return
        coord = conn.coordinator
        if coord is None or coord._target_drone_id is None:
            return
        loop = conn._loop
        if loop is None:
            return
        try:
            fut = asyncio.run_coroutine_threadsafe(coord.request_disconnect(), loop)
            fut.result(timeout=0.5)
        except Exception as exc:
            logger.debug('[app] не удалось отправить disconnect при закрытии: %s', exc)

    def _tick_drone_list_refresh(self) -> None:
        if self.stack.currentWidget() is self.drone_list_page:
            self._conn.request_drone_list()
        else:
            self._drone_list_refresh_timer.stop()

    def _navigate_to(self, widget: QWidget) -> None:
        current = self.stack.currentWidget()
        if current is not widget:
            self._nav_history.append(self.stack.indexOf(current))
        self.stack.setCurrentWidget(widget)

    def _navigate_back(self) -> None:
        if self._nav_history:
            self.stack.setCurrentIndex(self._nav_history.pop())

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

    def _handle_forgot_password(self, email: str) -> None:
        self._conn.request_password_reset(email)

    def _handle_logout(self) -> None:
        self._ping_timer.stop()
        self._quality_timer.stop()
        self._quality.end_session()
        self._stop_arm_listener()
        self._drone_list_refresh_timer.stop()
        self._conn.logout()
        self._video.stop()
        self._video.reset()
        self.login_page.reset()
        self.stack.setCurrentWidget(self.login_page)

    def _on_drones(self, drones: list[dict[str, object]]) -> None:
        try:
            self.drone_list_page.update(drones)
        except Exception as exc:
            logger.warning('[app] ошибка обновления списка дронов: %s', exc)

    def _handle_refresh(self) -> None:
        self._conn.request_drone_list()

    def _open_settings(self) -> None:
        current = self.stack.currentWidget()
        if current is not self.settings_page:
            self._settings_return_to = current
        self.stack.setCurrentWidget(self.settings_page)

    def _close_settings(self) -> None:
        target = self._settings_return_to or self.login_page
        self.stack.setCurrentWidget(target)

    def _handle_delete_drone(self, drone_id: str) -> None:
        def on_done(error: str | None) -> None:
            if error:
                QMessageBox.warning(self, 'Ошибка', error)
        self._conn.delete_drone(drone_id, on_done=on_done)

    def _handle_select_drone(self, drone_id: str) -> None:
        if not drone_id:
            return
        self._state.selected_drone_id = drone_id
        self._state.cam_index = 0
        self._conn.select_drone(drone_id)
        self._video.start()
        self._quality.start_session(log_path=self._stats_log_path())
        self._last_freeze_count = 0
        self._ping_timer.start()
        self._quality_timer.start()
        self._drone_list_refresh_timer.stop()
        if not self._demo:
            self.drone_view_page.set_calibration_visible(True)
        self.stack.setCurrentWidget(self.drone_view_page)

    def _handle_back_to_list(self) -> None:
        self._video.stop()
        self._ping_timer.stop()
        self._quality_timer.stop()
        self._quality.end_session()
        self.drone_view_page.update_stale(0.0)
        self._stop_arm_listener()
        self._conn.disconnect_drone()
        self._video.reset()
        self._state.reset()
        self.drone_view_page.set_calibration_visible(False)
        self.drone_view_page.update_fc_status('none', '')
        self.stack.setCurrentWidget(self.drone_list_page)
        self._drone_list_refresh_timer.start()
        self._conn.request_drone_list()

    def _on_battery_updated(self, percent: int, voltage: float) -> None:
        self.drone_view_page.update_battery(percent, voltage)
        if self._flight_window is not None:
            try:
                self._flight_window.update_battery(percent, voltage)
            except Exception as exc:
                logger.debug('[app] обновление заряда в полётном окне: %s', exc)

    def _on_drone_went_offline(self, drone_id: str) -> None:
        if self.stack.currentWidget() is not self.drone_view_page:
            return
        logger.info('[app] дрон %s офлайн, возврат к списку', drone_id)
        self._handle_back_to_list()

    def _on_connect_failed(self, drone_id: str) -> None:
        if self.stack.currentWidget() is not self.drone_view_page:
            return
        logger.info('[app] подключение к дрону %s не удалось; показываю баннер', drone_id)
        self.drone_view_page.set_calibration_visible(False)
        self.drone_view_page.show_error_banner('Камеры не найдены')
        QTimer.singleShot(3000, self._dismiss_error_banner_and_back)

    def _dismiss_error_banner_and_back(self) -> None:
        self.drone_view_page.hide_error_banner()
        if self.stack.currentWidget() is self.drone_view_page:
            self._handle_back_to_list()

    def _on_server_error(self, message: str) -> None:
        logger.warning('[app] ошибка сервера: %s', message)
        QMessageBox.warning(self, 'Ошибка сервера', message or 'Неизвестная ошибка сервера')

    def _on_session_reset(self) -> None:
        self._video.clear_tracks()
        if self.stack.currentWidget() is self.drone_view_page:
            self.drone_view_page.set_calibration_visible(True)

    def _on_cameras_received(self, cameras: list[dict[str, object]]) -> None:
        self._state.cameras = cameras
        self.drone_view_page.save_btn.setEnabled(True)
        self._update_camera_settings_ui()
        self._send_focus(self._video.cam_index)

    def _on_fc_info(self, fc_type: str, fc_name: str) -> None:
        self._state.fc_type = fc_type
        self._state.fc_name = fc_name
        self.drone_view_page.update_fc_status(fc_type, fc_name)
        self.joystick_setup_page.set_fc_type(fc_type or 'none')

    def _on_cam_changed(self, cam_index: int) -> None:
        self._state.cam_index = cam_index
        self._update_camera_settings_ui()
        self._send_focus(cam_index)

    def _send_focus(self, cam_index: int) -> None:
        cameras = self._state.cameras
        if not cameras or cam_index >= len(cameras):
            return
        cam = cameras[cam_index]
        if not isinstance(cam, dict):
            return
        device_index = cam.get('device_index', cam_index)
        if isinstance(device_index, bool) or not isinstance(device_index, int):
            return
        coord = self._conn.coordinator
        if coord is None:
            return
        self._conn._submit(coord.send_focus(device_index))

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
            self._conn._submit(coord.send_params_update([
                {'device_index': device_index, 'param_index': param_index},
            ]))
        self.drone_view_page.save_btn.setEnabled(True)

    def _start_arm_listener(self, joystick_index: int, calibration: dict[str, Any]) -> None:
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

    def _open_joystick_setup(self) -> None:
        self._navigate_to(self.joystick_setup_page)

    def _handle_back_from_joystick(self) -> None:
        self._navigate_back()

    def _handle_joystick_selected(self, joystick_index: int, calibration: dict[str, Any]) -> None:
        coord = self._conn.coordinator
        fc_kind = coord.fc_kind if coord is not None else 'crsf'
        if fc_kind == 'mavlink':
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
            self._start_arm_listener(joystick_index, calibration)
            self._open_flight_window(joystick_index, calibration, passive=True)
            self._begin_qgc_search(sdl_config)
            return
        self._open_flight_window(joystick_index, calibration)

    def _begin_qgc_search(self, sdl_config: str) -> None:
        self._qgc_search_overlay = QGCSearchOverlay()
        self._qgc_search_overlay.show_centered()
        worker = _QgcFindWorker()
        worker.found.connect(lambda path: self._on_qgc_found(path, sdl_config))
        self._qgc_search_thread = worker
        worker.start()

    def _on_qgc_found(self, qgc_path: Path | None, sdl_config: str) -> None:
        if self._qgc_search_overlay is not None:
            self._qgc_search_overlay.close()
            self._qgc_search_overlay = None
        proc = None
        if qgc_path is not None:
            proc = launch_qgc(sdl_config, qgc_path=qgc_path)
        if proc is None:
            proc = self._launch_qgc_with_user_pick(sdl_config)
        if proc is None:
            logger.warning('[app] QGC не найден; полётное окно работает без него')
            self._set_debug_status('QGroundControl не найден и не запущен')
        else:
            self._qgc_overlay = QGCLaunchingOverlay(qgc_proc=proc)
            self._qgc_overlay.show_centered()
            self._set_debug_status(f'QGroundControl запущен (pid={proc.pid})')

    def _debug_launch_qgc(self) -> None:
        if is_qgc_running():
            QMessageBox.warning(
                self, 'Закройте QGroundControl',
                'QGroundControl уже запущен. Закройте его и попробуйте снова.',
            )
            return
        self._set_debug_status('Ищу QGroundControl…')
        self._begin_qgc_search('')

    def _set_debug_status(self, text: str) -> None:
        if self.debug_page is not None:
            self.debug_page.set_status(text)

    def _launch_qgc_with_user_pick(self, sdl_config: str) -> subprocess.Popen[bytes] | None:
        if platform.system() == 'Windows':
            filt = 'QGroundControl (QGroundControl*.exe);;Executable (*.exe);;All files (*)'
        else:
            filt = 'QGroundControl (QGroundControl* qgroundcontrol* *.AppImage);;All files (*)'
        ans = QMessageBox.question(
            self, 'QGroundControl не найден',
            'QGroundControl не удалось найти автоматически.\n'
            'Указать путь к исполняемому файлу вручную?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
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
        proc = launch_qgc(sdl_config, qgc_path=path)
        if proc is None:
            QMessageBox.warning(
                self, 'QGroundControl',
                'Не удалось запустить выбранный файл. Проверьте, что это исполняемый файл QGroundControl.',
            )
        return proc

    def _open_flight_window(self, joystick_index: int, calibration: dict[str, Any],
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
        self._flight_window.raise_()
        self._flight_window.activateWindow()
        self.hide()
        self._start_joystick_guard(joystick_index, calibration, js=js_input)

    def _handle_flight_closed(self) -> None:
        self._stop_joystick_guard()
        self._stop_arm_listener()
        self._flight_window = None
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.stack.setCurrentWidget(self.drone_view_page)
        self._video.start()

    def _start_joystick_guard(
        self,
        joystick_index: int,
        calibration: dict[str, Any],
        js: JoystickInput | None = None,
        qgc_proc: subprocess.Popen[bytes] | None = None,
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
        proc = self._joystick_guard_qgc_proc
        if proc is not None and proc.poll() is not None:
            logger.info('[app] joystick guard остановлен (QGC завершился)')
            self._stop_joystick_guard()

    def _on_guard_disarm(self) -> None:
        QMessageBox.warning(
            self, 'Джойстик отключён',
            'Связь с джойстиком потеряна. Дрону отправлена команда DISARM.',
        )

    def _tick_ping(self) -> None:
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
        self._quality.add_rtt(rtt)
        self._tick_stale()

    def _tick_stale(self) -> None:
        staleness = self._quality.snapshot().staleness_ms
        seconds = staleness / 1000.0 if staleness > STALE_FRAME_MS else 0.0
        self.drone_view_page.update_stale(seconds)
        if self._flight_window is not None:
            self._flight_window.update_stale(seconds)

    def _on_board_stats(self, payload: dict[str, Any]) -> None:
        try:
            self._quality.update_board(
                bitrate_out_kbps=float(payload.get('bitrate_out_kbps', -1.0)),
                encoder_kbps=float(payload.get('encoder_kbps', -1.0)),
                pli=int(payload.get('pli', 0)),
            )
        except (TypeError, ValueError) as exc:
            logger.debug('[app] некорректный stats от борта: %s', exc)

    @staticmethod
    def _stats_log_path() -> Path:
        return settings.log_path.parent / f'stats_{date.today()}.jsonl'

    def _tick_quality(self) -> None:
        snap = self._quality.snapshot()
        self._quality.log_snapshot(snap)
        self.drone_view_page.update_quality(*format_quality_line(snap))
        self.drone_view_page.set_stats_text(format_stats_table(snap))
        if self._flight_window is not None:
            self._flight_window.update_quality(*format_quality_line(snap))
        self._maybe_request_keyframe(snap)

    def _maybe_request_keyframe(self, snap: LinkSnapshot) -> None:
        freeze_grew = snap.freeze_count > self._last_freeze_count
        self._last_freeze_count = snap.freeze_count
        if snap.loss_pct <= 2.0 and not freeze_grew:
            return
        coord = self._conn.coordinator
        if coord is None:
            return
        self._conn._submit(coord.request_keyframe())



class _CoordinatorAdapter:
    def __init__(self, conn: ConnectionManager) -> None:
        self._conn = conn

    @property
    def webrtc(self) -> _CoordinatorAdapter:
        return self

    @property
    def peer_ping_ms(self) -> float:
        coord = self._conn.coordinator
        if coord is None or coord._manager is None or coord._manager.channels is None:
            return -1.0
        ping_ch = coord._manager.channels.ping
        return ping_ch.last_rtt_ms if (ping_ch and ping_ch.last_rtt_ms is not None) else -1.0

    @property
    def crsf_receiver(self) -> None:
        return None

    @property
    def drone_id(self) -> str | None:
        coord = self._conn.coordinator
        return coord._target_drone_id if coord is not None else None

    def send_crsf_packet(self, frame: bytes) -> None:
        self._conn.send_joystick_frame(frame)
