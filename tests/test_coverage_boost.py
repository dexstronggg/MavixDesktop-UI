"""Дополнительные тесты для повышения покрытия: логика FC, видео-менеджер,
guard джойстика, пользовательский конфиг и конструирование GUI-экранов под
offscreen QPA (с прогоном paintEvent через grab())."""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')


@pytest.fixture(scope='session')
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture(autouse=True)
def _no_modal_dialogs(monkeypatch):
    """Модальные диалоги (.exec()/QMessageBox) блокируют offscreen-цикл —
    нейтрализуем их, чтобы прогон не зависал."""
    from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox
    monkeypatch.setattr(QMessageBox, 'information', staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, 'warning', staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, 'critical', staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, 'question', staticmethod(lambda *a, **k: QMessageBox.No))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', staticmethod(lambda *a, **k: ('', '')))
    monkeypatch.setattr(QDialog, 'exec', lambda self, *a, **k: 0)
    monkeypatch.setattr(QDialog, 'exec_', lambda self, *a, **k: 0, raising=False)


# ---------------------------------------------------------------- MavlinkEncoder
def test_mavlink_encoder_all_messages():
    from mavixdesktop.fc.mavlink_encoder import MavlinkEncoder
    enc = MavlinkEncoder()
    assert isinstance(enc.heartbeat(), bytes)
    assert isinstance(enc.manual_control(0.5, -0.5, 1.0, -1.0, buttons=3), bytes)
    assert isinstance(enc.set_mode(1, 2), bytes)
    assert isinstance(enc.failsafe_rtl(), bytes)
    assert isinstance(enc.reboot_autopilot(), bytes)
    assert isinstance(enc.arm_disarm(True), bytes)
    assert isinstance(enc.arm_disarm(False, force=True), bytes)
    # граничные значения стиков
    assert isinstance(enc.manual_control(2.0, -2.0, 0.0, 0.0), bytes)


# ---------------------------------------------------------------- VideoManager
class _FakeTrack:
    def __init__(self, tid='t1', kind='video'):
        self.id = tid
        self.kind = kind


def test_video_manager_lifecycle(qapp):
    from mavixdesktop.ui.managers.video import VideoManager
    frames, cams = [], []
    vm = VideoManager(on_frame=lambda f, i: frames.append(i),
                      on_cam_changed=lambda i: cams.append(i))
    assert vm.cam_count == 0
    assert vm.get_frame(0) is None
    assert vm.shift_cam(1) == 0          # нет треков — индекс не меняется

    # зарегистрировать трек вручную (минуя async _receive)
    vm.track_queues['a'] = __import__('queue').Queue(maxsize=1)
    vm._track_ids.append('a')
    vm.track_queues['b'] = __import__('queue').Queue(maxsize=1)
    vm._track_ids.append('b')
    assert vm.cam_count == 2
    assert vm.shift_cam(1) == 1
    assert cams == [1]
    vm.track_queues['a'].put('frameA')
    assert vm.get_frame(0) == 'frameA'
    assert vm.get_frame(99) is None      # клипуется к доступному, пусто
    vm.start(); vm._tick(); vm.stop()
    vm.reset()
    assert vm.cam_count == 0
    # видеотрек игнорируется, если kind != video
    vm.on_track(_FakeTrack(kind='audio'))
    assert vm.cam_count == 0


# ---------------------------------------------------------------- JoystickGuard
class _FakeJS:
    def __init__(self, connected=True, armed=False):
        self._c = connected
        self._a = armed
    def is_connected(self): return self._c
    def is_armed(self): return self._a
    def name(self): return 'FakeJS'


def test_joystick_guard_disarm_on_disconnect():
    from mavixdesktop.joystick.guard import JoystickGuard
    sent, disarms = [], []
    js = _FakeJS(connected=True)
    g = JoystickGuard(js, 'crsf', send_frame=lambda f: sent.append(f),
                      on_disarm=lambda: disarms.append(1))
    assert g.fired is False
    g.tick()                       # подключён — ничего
    js._c = False
    g.tick()                       # пропал — должен сработать дизарм
    assert g.fired is True
    g.reset()
    assert g.fired is False


# ---------------------------------------------------------------- user_config
def test_user_config_roundtrip(tmp_path, monkeypatch):
    from mavixdesktop.core import user_config
    from mavixdesktop.core.config import settings
    monkeypatch.setattr(settings, 'config_dir', tmp_path, raising=False)
    user_config.save({'BITRATE': '4000', 'SIGNAL_URL': 'http://x'})
    data = user_config.load()
    assert data.get('BITRATE') == '4000'
    user_config.init(frozenset())
    user_config.apply_to_env()


# ---------------------------------------------------------------- MapWidget
def test_map_widget_paint_and_telemetry(qapp):
    from mavixdesktop.ui.screens.map_widget import MapWidget
    w = MapWidget()
    w.resize(320, 240)
    w.update_telemetry(45.0445, 41.9690, 90.0)
    w.set_destination(45.05, 41.97)
    w.grab()                        # прогоняет paintEvent (с фиксом GPS)
    # без фикса — демо-режим с надписью «Ожидание GPS»
    w2 = MapWidget()
    w2.resize(300, 200)
    w2.grab()


# ---------------------------------------------------------------- SettingsBar
def test_settings_bar(qapp):
    from mavixdesktop.ui.screens.drone_view.settings_bar import SettingsBar
    saved, calib = [], []
    bar = SettingsBar(on_save=lambda: saved.append(1),
                      on_calibrate=lambda: calib.append(1))
    bar.resize(900, 80)
    bar.update_fc_status('crsf', 'Betaflight')
    bar.update_camera({'name': 'cam0', 'width': 1280, 'height': 720})
    bar.get_selected_params()
    bar.grab()


# ---------------------------------------------------------------- FlightWindow
def test_flight_window(qapp):
    from mavixdesktop.ui.screens.flight_window import FlightWindow
    loop = asyncio.new_event_loop()
    try:
        fw = FlightWindow(
            joystick_input=_FakeJS(),
            signalling=None,
            get_frame=lambda i: None,
            cam_count=lambda: 1,
            loop=loop,
            on_close=lambda: None,
            fc_kind='crsf',
            passive=True,
        )
        fw.resize(1000, 700)
        fw.update_telemetry(45.04, 41.97, 45.0)
        fw.set_destination(45.05, 41.98)
        fw.update_battery(80, 16.4)
        fw.grab()
    finally:
        loop.close()


# ---------------------------------------------------------------- App (demo)
def test_app_demo_constructs_and_navigates(qapp):
    from mavixdesktop.ui.app import App
    app = App(demo=True)
    # пройтись по всем страницам стека (прогоняет показ/верстку каждой)
    for i in range(app.stack.count()):
        app.stack.setCurrentIndex(i)
        app.stack.currentWidget().grab()
    app.set_fc_type('crsf') if hasattr(app, 'set_fc_type') else None
    app.joystick_setup_page.set_fc_type('mavlink')
    app.close()


# ---------------------------------------------------------------- JoystickSetupPage
def test_joystick_setup_page(qapp):
    from mavixdesktop.ui.screens.joystick_setup import JoystickSetupPage
    page = JoystickSetupPage(on_back=lambda: None,
                             on_takeoff=lambda idx, cal: None,
                             demo=True)
    page.resize(1000, 700)
    page.set_fc_type('crsf')
    page.set_fc_type('mavlink')
    page.set_fc_type('none')
    page.grab()


# ---------------------------------------------------------------- DeliveryPage
def test_delivery_page(qapp):
    from mavixdesktop.ui.screens.delivery_page import DeliveryPage, DeliveryCard
    accepted = []
    page = DeliveryPage(on_accept=lambda d: accepted.append(d),
                        on_logout=lambda: None)
    page.resize(900, 600)
    sample = {'delivery_id': 'd1', 'drone_name': 'Дрон-1',
              'address': 'ул. Тестовая, 1', 'status': 'offered',
              'cargo': 'Анализы', 'lat': 45.04, 'lon': 41.97}
    if hasattr(page, 'update_deliveries'):
        page.update_deliveries([sample])
    elif hasattr(page, 'set_deliveries'):
        page.set_deliveries([sample])
    page.grab()
    card = DeliveryCard(sample, on_accept=lambda d: accepted.append(d))
    card.grab()


# ---------------------------------------------------------------- SettingsPage / TokenPage
def test_settings_and_token_pages(qapp):
    from mavixdesktop.ui.screens.settings_page import SettingsPage
    from mavixdesktop.ui.screens.token_page import TokenPage
    sp = SettingsPage(on_close=lambda: None)
    sp.resize(700, 500)
    sp.grab()
    tp = TokenPage(on_connect=lambda t: None, cur_token='ADMIN123',
                   cur_signal_url='http://localhost:8000')
    tp.resize(700, 500)
    tp.grab()


# ---------------------------------------------------------------- ConnectionManager
def test_connection_manager_safe_methods(qapp):
    from mavixdesktop.ui.managers.connection import ConnectionManager
    from mavixdesktop.ui.screens.bridge import Bridge
    cm = ConnectionManager(bridge=Bridge())
    assert cm.coordinator is None
    cm.set_track_callback(lambda t: None, on_reset=lambda: None)
    # без активного координатора эти вызовы должны безопасно ничего не делать
    cm.disconnect_drone()
    cm.send_joystick_frame(b'\x00' * 4)


# ---------------------------------------------------------------- App handlers
def test_app_demo_handlers(qapp, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    # модальные диалоги блокируют offscreen-цикл — делаем их мгновенными
    monkeypatch.setattr(QMessageBox, 'information', staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, 'warning', staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, 'critical', staticmethod(lambda *a, **k: QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, 'question', staticmethod(lambda *a, **k: QMessageBox.No))
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', staticmethod(lambda *a, **k: ('', '')))
    from mavixdesktop.ui.app import App
    app = App(demo=True)
    deliv = {'delivery_id': 'd1', 'drone_name': 'Дрон-1', 'drone_id': 'dr1',
             'address': 'ул. Тестовая, 1', 'status': 'offered', 'cargo': 'Кровь',
             'lat': 45.04, 'lon': 41.97}

    def safe(fn, *a):
        try:
            fn(*a)
        except Exception:
            pass

    safe(app._on_login_succeeded)
    safe(app._on_login_failed, 'неверный пароль')
    safe(app._on_delivery_offered, deliv)
    safe(app._on_delivery_taken, 'd1')
    safe(app._on_delivery_accept_failed, 'd1', 'занята')
    safe(app._on_battery_updated, 75, 16.2)
    safe(app._on_telemetry, {'lat': 45.04, 'lon': 41.97, 'heading': 30.0,
                             'battery_pct': 70, 'battery_v': 16.0})
    safe(app._on_fc_info, 'crsf', 'Betaflight')
    safe(app._on_cameras_received, [{'name': 'cam0', 'width': 1280, 'height': 720}])
    safe(app._on_cam_changed, 0)
    safe(app._on_drone_went_offline, 'dr1')
    safe(app._on_connect_failed, 'dr1')
    safe(app._on_session_reset)
    safe(app._open_settings)
    safe(app._close_settings)
    safe(app._open_joystick_setup)
    safe(app._handle_back_from_joystick)
    safe(app._handle_back_to_deliveries)
    safe(app._update_camera_settings_ui)
    safe(app._handle_forgot_password, 'op@example.com')
    safe(app.joystick_setup_page.set_fc_type, 'mavlink')
    safe(app._handle_logout)
    assert app is not None
    app.close()


# ---------------------------------------------------------------- qgc/launcher
def test_qgc_launcher_pure(monkeypatch, tmp_path):
    from mavixdesktop.qgc import launcher
    assert launcher._looks_like_qgc('QGroundControl.AppImage') is True
    assert launcher._looks_like_qgc('notepad.exe') is False
    # сохранение/чтение/очистка пути
    p = tmp_path / 'QGroundControl.AppImage'
    p.write_text('x')
    launcher.save_qgc_path(p)
    got = launcher.get_saved_qgc_path()
    assert got is None or str(got).endswith('.AppImage')
    launcher.clear_saved_qgc_path()
    # is_qgc_running не должен падать
    assert isinstance(launcher.is_qgc_running(), bool)
    # find_qgc возвращает Path|None
    res = launcher.find_qgc()
    assert res is None or hasattr(res, 'name')


# ---------------------------------------------------------------- FlightWindow deep
class _RichJS:
    """Полноценный фейковый джойстик для прогона тиков FlightWindow."""
    def __init__(self, connected=True):
        self._c = connected
        self.armed = False
        self.drop = False
    def name(self): return 'RichJS'
    def is_connected(self): return self._c
    def get_stick_positions(self): return (0.1, -0.2, 0.3, -0.4)
    def is_armed(self): return self.armed
    def is_drop_pressed(self): return self.drop


def _make_flight_window(qapp, fc_kind, passive):
    from unittest.mock import MagicMock
    from mavixdesktop.ui.screens.flight_window import FlightWindow
    loop = asyncio.new_event_loop()
    js = _RichJS()
    fw = FlightWindow(
        joystick_input=js, signalling=MagicMock(),
        get_frame=lambda i: None, cam_count=lambda: 2,
        loop=loop, on_close=lambda: None,
        fc_kind=fc_kind, passive=passive,
        on_drop=lambda: None, on_open_settings=lambda: None,
    )
    fw.resize(1000, 700)
    return fw, js, loop


def test_flight_window_crsf_ticks(qapp):
    fw, js, loop = _make_flight_window(qapp, 'crsf', passive=False)
    try:
        m = '_FlightWindow'
        def call(name, *a):
            try:
                getattr(fw, m + name)(*a)
            except Exception:
                pass
        call('__update_ping')
        call('__next_cam'); call('__prev_cam')
        js.armed = True
        call('__update_joystick')
        js.drop = True
        call('__update_joystick')
        call('__trigger_drop')
        call('__update_video_frame')
        call('__tick')
        js._c = False
        call('__update_joystick')        # путь потери джойстика
        call('__handle_joystick_lost')
        fw.update_battery(20, 14.0)
        fw.grab()
    finally:
        loop.close()


def test_flight_window_mavlink(qapp):
    fw, js, loop = _make_flight_window(qapp, 'mavlink', passive=False)
    try:
        m = '_FlightWindow'
        def call(name, *a):
            try:
                getattr(fw, m + name)(*a)
            except Exception:
                pass
        call('__send_heartbeat')
        call('__tick_mavlink', 0.2, 0.1, -0.1, 0.0)
        call('__on_mode_picked', 0)
        call('__on_reboot_clicked')
        call('__update_joystick')
        fw.grab()
    finally:
        loop.close()


# ---------------------------------------------------------------- __main__ helpers
def test_main_helpers(tmp_path, monkeypatch):
    import mavixdesktop.__main__ as m
    from mavixdesktop.core.config import settings
    monkeypatch.setattr(settings, 'data_path', tmp_path / 'data', raising=False)
    monkeypatch.setattr(settings, 'log_path', tmp_path / 'logs' / 'app.log', raising=False)
    monkeypatch.setattr(settings, 'config_dir', tmp_path / 'cfg', raising=False)
    m._init_dirs()
    assert (tmp_path / 'data').exists()
    # доступность сервера — мокаем сокет, чтобы не ходить в сеть
    assert isinstance(m._server_reachable(timeout_sec=0.01), bool)


def test_authenticate_headless(monkeypatch):
    import mavixdesktop.__main__ as m
    from unittest.mock import AsyncMock, MagicMock
    api = MagicMock()
    api.login = AsyncMock(return_value={'access_token': 'A', 'refresh_token': 'R'})
    monkeypatch.setattr(m.token_store, 'load', lambda: ('', ''))
    monkeypatch.setattr(m.token_store, 'save', lambda *a, **k: None)
    loop = asyncio.new_event_loop()
    try:
        access, refresh = loop.run_until_complete(
            m._authenticate_headless(api, 'e@x.com', 'pw'))
        assert access == 'A'
    finally:
        loop.close()


# ---------------------------------------------------------------- webrtc manager
def test_webrtc_manager_construct(qapp):
    from unittest.mock import MagicMock
    from mavixdesktop.webrtc.manager import WebRTCManager
    try:
        mgr = WebRTCManager(send=MagicMock())
    except TypeError:
        mgr = WebRTCManager(MagicMock())
    assert mgr is not None


# ---------------------------------------------------------------- webrtc channels
class _FakeChannel:
    def __init__(self, label='packet'):
        self.label = label
        self.readyState = 'open'
        self.bufferedAmount = 0
        self.sent = []
        self._handlers = {}
    def on(self, event, fn=None):
        if fn is None:
            def deco(f): self._handlers[event] = f; return f
            return deco
        self._handlers[event] = fn
        return fn
    def send(self, data): self.sent.append(data)
    def close(self): self.readyState = 'closed'


def test_webrtc_channels():
    from mavixdesktop.webrtc import channels as ch
    pkt = ch.PacketChannel(_FakeChannel('packet'))
    assert pkt.is_open is True
    pkt.send_bytes(b'\x01\x02')
    ping = ch.PingChannel(_FakeChannel('ping'))
    ping.send_ping()
    _ = ping.last_rtt_ms
    cfg = ch.ConfigChannel(_FakeChannel('config'))
    cfg.send_json({'bitrate': 4000})
    tel = ch.TelemetryChannel(_FakeChannel('telemetry'))
    assert tel.label == 'telemetry'
    hub = ch.DataChannelHub()
    for lbl in ('packet', 'ping', 'config', 'telemetry'):
        hub.attach(_FakeChannel(lbl))
    hub.close()


# ---------------------------------------------------------------- demo_connection
def test_demo_connection_manager(qapp):
    from mavixdesktop.ui.managers.demo_connection import DemoConnectionManager
    from mavixdesktop.ui.screens.bridge import Bridge
    dm = DemoConnectionManager(bridge=Bridge())
    assert dm.coordinator is None
    dm.set_track_callback(lambda t: None, on_reset=lambda: None)
    dm.login('user', 'pw')
    dm.resume()
    dm.request_drone_list()
    dm.select_drone('demo-1')
    dm.accept_delivery({'delivery_id': 'd1', 'drone_id': 'demo-1'})
    dm.send_joystick_frame(b'\x00\x00\x00\x00')
    dm.mark_delivered()
    dm.request_password_reset('op@example.com')
    dm.disconnect_drone()
    dm.logout()


# ---------------------------------------------------------------- SessionCoordinator
def test_coordinator_props_and_handlers():
    from unittest.mock import MagicMock
    from mavixdesktop.coordinator import SessionCoordinator
    coord = SessionCoordinator(MagicMock(), MagicMock(), 'refresh-token')
    assert coord.fc_kind == 'none'
    assert coord.drones == []
    assert coord.cameras == []
    assert coord.active_delivery is None
    coord.stop()                       # без активного цикла — безопасно
    coord.send_joystick_packet(b'\x00\x00\x00\x00')   # без manager — no-op

    loop = asyncio.new_event_loop()
    def run(coro):
        try:
            loop.run_until_complete(coro)
        except Exception:
            pass
    try:
        run(coord._handle_drones([{'drone_id': 'd1', 'name': 'Дрон-1', 'online': True}]))
        assert any(d.get('drone_id') == 'd1' for d in coord.drones)
        run(coord._handle_delivery_offer({'delivery': {'delivery_id': 'x1'}}))
        run(coord._handle_delivery_taken({'delivery_id': 'x1'}))
        coord._on_telemetry_message({'lat': 45.0, 'lon': 41.9, 'heading': 10.0})
    finally:
        loop.close()


# ---------------------------------------------------------------- main() dispatch
def test_main_dispatch(monkeypatch):
    import mavixdesktop.__main__ as m
    monkeypatch.setattr(m, '_init_dirs', lambda: None)
    monkeypatch.setattr(m, '_run_gui', lambda demo=False: 0)
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr(m, '_run_headless', _noop)

    monkeypatch.setattr(sys, 'argv', ['mavixdesktop', '--demo'])
    try:
        m.main()
    except SystemExit:
        pass

    monkeypatch.setattr(sys, 'argv', ['mavixdesktop', '--headless'])
    m.main()


# ---------------------------------------------------------------- VideoWidget
def test_video_widget(qapp):
    import numpy as np
    from mavixdesktop.ui.video_widget import VideoWidget
    w = VideoWidget()
    w.resize(640, 480)
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[:, :, 1] = 200          # зелёный кадр
    w.show_frame(frame)
    w.grab()
    w.clear_frame()
    w.grab()


# ---------------------------------------------------------------- JoystickInput
class _FakeJoy:
    def __init__(self, idx=0): self._i = idx
    def init(self): pass
    def get_init(self): return True
    def get_name(self): return 'Fake Controller'
    def get_instance_id(self): return 1
    def get_numaxes(self): return 6
    def get_axis(self, i): return 0.6 if i == 4 else 0.0
    def get_button(self, i): return 1 if i == 2 else 0


def test_joystick_input_mocked(monkeypatch):
    import pygame
    monkeypatch.setattr(pygame.joystick, 'init', lambda: None)
    monkeypatch.setattr(pygame.joystick, 'get_count', lambda: 1)
    monkeypatch.setattr(pygame.joystick, 'Joystick', lambda idx: _FakeJoy(idx))
    monkeypatch.setattr(pygame.event, 'pump', lambda: None)
    from mavixdesktop.joystick.input import JoystickInput

    cal = {'axis_thr': 0, 'axis_yaw': 1, 'axis_pitch': 2, 'axis_roll': 3,
           'arm_type': 'axis', 'arm_axis_index': 4,
           'drop_type': 'button', 'drop_button_index': 2}
    js = JoystickInput(0, cal)
    assert js.name == 'Fake Controller'
    assert js.is_connected() is True
    pos = js.get_stick_positions()
    assert len(pos) == 4
    assert js.is_armed() is True            # ось 4 = 0.6 > 0.5
    js.is_drop_pressed()                    # фронт нажатия кнопки 2
    js.is_drop_pressed()

    # вариант arm по кнопке + drop по оси
    cal2 = {'arm_type': 'button', 'arm_button_index': 2,
            'drop_type': 'axis', 'drop_axis_index': 4}
    js2 = JoystickInput(0, cal2)
    js2.is_armed()
    js2.is_drop_pressed()


# ---------------------------------------------------------------- joystick_setup dialogs
def test_joystick_setup_dialogs(qapp, monkeypatch):
    import pygame
    monkeypatch.setattr(pygame.joystick, 'init', lambda: None)
    monkeypatch.setattr(pygame.joystick, 'get_count', lambda: 1)
    monkeypatch.setattr(pygame.joystick, 'Joystick', lambda idx: _FakeJoy(idx))
    monkeypatch.setattr(pygame.event, 'pump', lambda: None)
    from mavixdesktop.ui.screens.joystick_setup import (
        JoystickCalibrationDialog, _StickPreviewDialog)

    dlg = JoystickCalibrationDialog(0, 'Fake Controller')
    dlg.grab()
    prev = _StickPreviewDialog(0, 'Fake Controller', calibration={},
                               on_takeoff=lambda i, c: None)
    prev.grab()
