"""Smoke tests for the Qt UI: imports + widget construction under offscreen QPA. These tests deliberately avoid driving the asyncio thread in ConnectionManager (login / coordinator), so no real network or PyAV codec setup happens."""
from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


@pytest.fixture(scope='session')
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_login_page_constructs(qapp):
    from mavixdesktop.ui.login_page import LoginPage
    page = LoginPage(on_login=lambda email, pw: None)
    assert page is not None


def test_login_page_set_error(qapp):
    from mavixdesktop.ui.login_page import LoginPage
    page = LoginPage(on_login=lambda email, pw: None)
    page.set_error('bad credentials')
    assert page.error.text() == 'bad credentials'


def test_login_submit_requires_both_fields(qapp):
    from mavixdesktop.ui.login_page import LoginPage
    captured: list = []

    page = LoginPage(on_login=lambda email, pw: captured.append((email, pw)))
    page._submit()
    assert captured == []
    assert page.error.text() != ''

    page.email.setText('me@example.com')
    page.password.setText('hunter2')
    page.error.setText('')
    page._submit()
    assert captured == [('me@example.com', 'hunter2')]


def test_bridge_imports(qapp):
    from mavixdesktop.ui.screens.bridge import Bridge
    b = Bridge()
    assert hasattr(b, 'client_list_updated')
    assert hasattr(b, 'fc_info_received')


def test_drone_list_page_update_with_new_format(qapp):
    from mavixdesktop.ui.screens.drone_list_page import DroneListPage
    page = DroneListPage(
        on_select=lambda _id: None,
        on_refresh=lambda: None,
        on_logout=lambda: None,
        on_joystick_cfg=lambda: None,
    )
    page.update([
        {'drone_id': 'd-1', 'online': True},
        {'drone_id': 'd-2', 'online': False},
    ])
    page.update([])


def test_drone_list_page_update_with_legacy_format(qapp):
    from mavixdesktop.ui.screens.drone_list_page import DroneListPage
    page = DroneListPage(
        on_select=lambda _id: None,
        on_refresh=lambda: None,
        on_logout=lambda: None,
        on_joystick_cfg=lambda: None,
    )
    page.update([{'session_id': 'legacy', 'status': 'ready'}])


def test_app_constructs_without_login(qapp, monkeypatch):
    monkeypatch.setattr(
        'mavixdesktop.ui.managers.connection.token_store.load',
        lambda: (None, None),
    )

    from mavixdesktop.ui.app import App
    app = App()
    assert app.stack.currentWidget() is app.login_page


def test_app_resumes_when_refresh_token_stored(qapp, monkeypatch):
    monkeypatch.setattr(
        'mavixdesktop.ui.managers.connection.token_store.load',
        lambda: ('me@example.com', 'r-token-xyz'),
    )

    from mavixdesktop.ui.managers import connection as conn_mod

    async def _no_op(self, *a, **kw):
        return None
    monkeypatch.setattr(conn_mod.ConnectionManager, '_refresh_and_run', _no_op)

    from mavixdesktop.ui.app import App
    app = App()
    assert app.stack.currentWidget() is app.drone_list_page


def test_token_page_constructs(qapp):
    from mavixdesktop.ui.screens.token_page import TokenPage
    page = TokenPage(
        on_connect=lambda token: None,
        cur_token='', cur_signal_url='', cur_stun='', cur_turn='',
    )
    assert page is not None


def test_settings_page_ui_scale_slider(qapp, tmp_path, monkeypatch):
    from mavixdesktop.core import user_config
    monkeypatch.setattr(user_config, 'USER_CONFIG_PATH', tmp_path / 'config.json')

    from mavixdesktop.ui.screens.settings_page import SettingsPage
    page = SettingsPage(on_close=lambda: None)

    slider = page._ui_scale_slider
    assert slider is not None
    assert slider.minimum() == user_config.UI_SCALE_MIN
    assert slider.maximum() == user_config.UI_SCALE_MAX
    assert slider.value() == user_config.UI_SCALE_DEFAULT

    slider.setValue(130)
    assert page._ui_scale_value.text() == '130 %'
    assert page._collect()['ui_scale'] == 130


def test_drone_view_quality_overlays(qapp):
    from mavixdesktop.ui.screens.drone_view import DroneViewPage
    page = DroneViewPage(
        on_back=lambda: None, on_prev=lambda: None, on_next=lambda: None,
        on_save=lambda: None, on_joystick_cfg=lambda: None,
        on_takeoff=lambda: None, on_calibrate=lambda: None,
    )
    panel = page._video_panel

    page.update_quality('●  2.4 Мбит/с   потери 0.3%   78 мс', '#4ADE80')
    assert 'Мбит/с' in panel.quality_overlay.text()

    assert panel.stale_overlay.isHidden()
    page.update_stale(1.4)
    assert '1.4' in panel.stale_overlay.text()
    page.update_stale(0.0)
    assert panel.stale_overlay.isHidden()

    page.set_stats_text('КАЧЕСТВО КАНАЛА\n\nпотери   0.30 %')
    assert 'потери' in panel.stats_panel.text()
    assert panel.stats_panel.isHidden()
    assert panel.toggle_stats_panel() is True
    assert panel.toggle_stats_panel() is False


def test_quality_line_and_table_render(qapp):
    from mavixdesktop.ui.managers.quality import (
        LEVEL_BAD,
        LEVEL_IDLE,
        LEVEL_OK,
        LinkSnapshot,
        format_quality_line,
        format_stats_table,
    )

    idle_text, _ = format_quality_line(LinkSnapshot(level=LEVEL_IDLE))
    assert 'нет данных' in idle_text

    ok_text, ok_color = format_quality_line(
        LinkSnapshot(level=LEVEL_OK, bitrate_in_kbps=2400.0, loss_pct=0.3, rtt_p95_ms=78.0)
    )
    assert '2.4 Мбит/с' in ok_text and '0.3%' in ok_text and '78 мс' in ok_text

    _, bad_color = format_quality_line(LinkSnapshot(level=LEVEL_BAD))
    assert bad_color != ok_color

    table = format_stats_table(LinkSnapshot(level=LEVEL_OK, bitrate_in_kbps=2400.0, pli=3))
    assert 'входящий поток' in table
    assert 'запросов ключевого кадра' in table
    assert '—' in table, 'метрики борта без данных показываются прочерком'


def test_flight_window_quality_overlays(qapp):
    from mavixdesktop.ui.managers.quality import (
        LEVEL_BAD,
        LinkSnapshot,
        format_quality_line,
    )
    from mavixdesktop.ui.screens.flight_window import FlightWindow

    class FakeJoystick:
        def is_connected(self):
            return True

        def read(self):
            return {'thr': 0.0, 'yaw': 0.0, 'pitch': 0.0, 'roll': 0.0}

        def is_armed(self):
            return False

    window = FlightWindow(
        joystick_input=FakeJoystick(), signalling=None,
        get_frame=lambda idx: None, cam_count=lambda: 1,
        loop=None, on_close=lambda: None, fc_kind='crsf', passive=True,
    )
    window.resize(1280, 720)

    window.update_quality(*format_quality_line(
        LinkSnapshot(level=LEVEL_BAD, bitrate_in_kbps=900.0, loss_pct=4.2, rtt_p95_ms=530.0)
    ))
    assert '0.9 Мбит/с' in window._quality_lbl.text()

    assert window._stale_lbl.isHidden()
    window.update_stale(2.1)
    assert '2.1' in window._stale_lbl.text()
    window.update_stale(0.0)
    assert window._stale_lbl.isHidden()
