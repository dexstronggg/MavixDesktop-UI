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
    page.update(
        [
            {'drone_id': 'd-1', 'online': True},
            {'drone_id': 'd-2', 'online': False},
        ]
    )
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


def test_app_close_without_session(qapp, monkeypatch):
    monkeypatch.setattr(
        'mavixdesktop.ui.managers.connection.token_store.load',
        lambda: (None, None),
    )

    from mavixdesktop.ui.app import App

    app = App()
    app.close()


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
        on_back=lambda: None,
        on_prev=lambda: None,
        on_next=lambda: None,
        on_save=lambda: None,
        on_joystick_cfg=lambda: None,
        on_takeoff=lambda: None,
        on_calibrate=lambda: None,
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
        LinkSnapshot(
            level=LEVEL_OK, bitrate_in_kbps=2400.0, loss_pct=0.3, rtt_p95_ms=78.0
        )
    )
    assert '2.4 Мбит/с' in ok_text and '0.3%' in ok_text and '78 мс' in ok_text

    _, bad_color = format_quality_line(LinkSnapshot(level=LEVEL_BAD))
    assert bad_color != ok_color

    table = format_stats_table(
        LinkSnapshot(level=LEVEL_OK, bitrate_in_kbps=2400.0, pli=3)
    )
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
        joystick_input=FakeJoystick(),
        signalling=None,
        get_frame=lambda idx: None,
        cam_count=lambda: 1,
        loop=None,
        on_close=lambda: None,
        fc_kind='crsf',
        passive=True,
    )
    window.resize(1280, 720)

    window.update_quality(
        *format_quality_line(
            LinkSnapshot(
                level=LEVEL_BAD, bitrate_in_kbps=900.0, loss_pct=4.2, rtt_p95_ms=530.0
            )
        )
    )
    assert '0.9 Мбит/с' in window._quality_lbl.text()

    assert window._stale_lbl.isHidden()
    window.update_stale(2.1)
    assert '2.1' in window._stale_lbl.text()
    window.update_stale(0.0)
    assert window._stale_lbl.isHidden()


def test_flight_window_joystick_lost_label_depends_on_fc_kind(qapp):
    from mavixdesktop.ui.screens.flight_window import FlightWindow

    class FakeJoystick:
        def is_connected(self):
            return False

        def is_armed(self):
            return False

    for kind, expect_disarm in (('crsf', True), ('mavlink', False)):
        window = FlightWindow(
            joystick_input=FakeJoystick(),
            signalling=None,
            get_frame=lambda idx: None,
            cam_count=lambda: 1,
            loop=None,
            on_close=lambda: None,
            fc_kind=kind,
            passive=True,
        )
        window._FlightWindow__handle_joystick_lost()
        text = window._lost_lbl.text()
        if expect_disarm:
            assert 'РАЗАРМИРУЕТСЯ' in text
        else:
            assert 'РАЗАРМИРУЕТСЯ' not in text
            assert 'СВЯЗЬ С ДЖОЙСТИКОМ ПОТЕРЯНА' in text


def test_flight_closed_stops_arm_listener(qapp, monkeypatch):
    monkeypatch.setattr(
        'mavixdesktop.ui.managers.connection.token_store.load',
        lambda: (None, None),
    )

    from mavixdesktop.ui.app import App

    app = App()
    calls: list[str] = []
    monkeypatch.setattr(app, '_stop_joystick_guard', lambda: calls.append('guard'))
    monkeypatch.setattr(app, '_stop_arm_listener', lambda: calls.append('arm'))

    app._handle_flight_closed()

    assert calls == ['guard', 'arm']


def test_settings_defaults_signal_url_matches_module_constant():
    from mavixdesktop.core.config import DEFAULT_SIGNAL_URL
    from mavixdesktop.ui.screens.settings_page import _DEFAULTS

    assert _DEFAULTS['signal_url'] == DEFAULT_SIGNAL_URL


def test_bitrate_input_is_bounded(qapp):
    from mavixdesktop.ui.screens.drone_view.settings_bar import (
        BITRATE_DEFAULT_KBS,
        BITRATE_MAX_KBS,
        BITRATE_MIN_KBS,
        SettingsBar,
    )

    bar = SettingsBar(on_save=lambda: None, on_calibrate=lambda: None)

    bar.bitrate_input.setText('2500')
    assert bar.selected_bitrate() == 2500

    bar.bitrate_input.setText('')
    assert bar.selected_bitrate() == BITRATE_DEFAULT_KBS

    bar.bitrate_input.setText('999999999')
    assert bar.selected_bitrate() == BITRATE_MAX_KBS

    bar.bitrate_input.setText('1')
    assert bar.selected_bitrate() == BITRATE_MIN_KBS

    validator = bar.bitrate_input.validator()
    assert validator is not None
    assert (validator.bottom(), validator.top()) == (BITRATE_MIN_KBS, BITRATE_MAX_KBS)


def test_bitrate_out_of_range_is_flagged(qapp):
    from mavixdesktop.ui.screens.drone_view.settings_bar import (
        BITRATE_MAX_KBS,
        BITRATE_MIN_KBS,
        SettingsBar,
    )

    bar = SettingsBar(on_save=lambda: None, on_calibrate=lambda: None)

    bar.bitrate_input.setText('2500')
    assert bar.bitrate_hint.isHidden()
    assert 'border' not in bar.bitrate_input.styleSheet()

    bar.bitrate_input.setText('50')
    assert not bar.bitrate_hint.isHidden(), (
        'значение вне диапазона должно подсвечиваться'
    )
    assert 'border' in bar.bitrate_input.styleSheet()
    assert str(BITRATE_MIN_KBS) in bar.bitrate_hint.text()

    bar.bitrate_input.setText('')
    assert bar.bitrate_hint.isHidden(), 'пустое поле — ещё не ошибка, человек печатает'

    bar.bitrate_input.setText('50')
    assert bar.selected_bitrate() == BITRATE_MIN_KBS
    assert bar.bitrate_input.text() == str(BITRATE_MIN_KBS), (
        'поле показывает реально применённое'
    )

    bar.bitrate_input.setText('99999')
    assert bar.selected_bitrate() == BITRATE_MAX_KBS
    assert bar.bitrate_input.text() == str(BITRATE_MAX_KBS)


def test_help_dialog_fits_into_small_window(qapp):
    from PySide6.QtWidgets import QWidget

    from mavixdesktop.ui.screens.help_dialog import HelpDialog
    from mavixdesktop.ui.screens.widgets import CloseButton

    for w, h in ((1920, 1080), (1280, 720), (800, 480), (640, 400)):
        parent = QWidget()
        parent.resize(w, h)
        dlg = HelpDialog(parent)
        assert dlg.width() <= w, f'справка шире окна {w}x{h}'
        assert dlg.height() <= h, f'справка выше окна {w}x{h}'
        assert isinstance(dlg.close_btn, CloseButton)
        assert dlg.close_btn.toolTip() == 'Закрыть (Esc)'


def test_help_text_covers_every_metric_and_the_log_path(qapp):
    from mavixdesktop.ui.screens import help_text

    html = help_text.as_html()
    for name, unit, _ in help_text.METRICS:
        assert name in html, f'в справке нет показателя «{name}»'
        assert unit in html, f'у показателя «{name}» не указана единица измерения'
    assert 'stats_' in html and '.jsonl' in html, (
        'в справке нет пути к файлу статистики'
    )
    assert 'stats_report.py' in html
    for key in ('S  /  Ы', 'I  /  Ш', 'Esc'):
        assert key in html


def test_hotkeys_work_in_both_layouts(qapp, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    from mavixdesktop.ui.screens.drone_view import DroneViewPage

    page = DroneViewPage(
        on_back=lambda: None,
        on_prev=lambda: None,
        on_next=lambda: None,
        on_save=lambda: None,
        on_joystick_cfg=lambda: None,
        on_takeoff=lambda: None,
        on_calibrate=lambda: None,
    )
    opened: list[str] = []
    monkeypatch.setattr(page._video_panel, 'toggle_help', lambda: opened.append('help'))

    def press(key: int, text: str) -> None:
        page.keyPressEvent(
            QKeyEvent(
                QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier, text
            )
        )

    press(Qt.Key.Key_S, 's')
    assert not page._video_panel.stats_panel.isHidden(), (
        'латинская S не открыла таблицу'
    )
    press(0, 'ы')
    assert page._video_panel.stats_panel.isHidden(), 'русская ы не закрыла таблицу'

    press(Qt.Key.Key_I, 'i')
    press(0, 'ш')
    assert opened == ['help', 'help'], 'справка должна открываться и по i, и по ш'


def test_qgc_overlay_is_a_child_widget_not_a_window(qapp):
    """Wayland игнорирует move() для окон — плашка обязана быть дочерним виджетом."""
    from PySide6.QtWidgets import QWidget

    from mavixdesktop.ui.screens.joystick_setup import QGCSearchOverlay

    parent = QWidget()
    parent.resize(1200, 800)
    overlay = QGCSearchOverlay(parent=parent)
    assert not overlay.isWindow()
    assert overlay.parentWidget() is parent


def test_qgc_overlay_centers_itself_in_the_parent(qapp):
    from PySide6.QtWidgets import QWidget

    from mavixdesktop.ui.screens.joystick_setup import QGCSearchOverlay

    parent = QWidget()
    parent.resize(1200, 800)
    overlay = QGCSearchOverlay(parent=parent)
    overlay.show_centered()

    assert overlay.geometry().center().x() == pytest.approx(600, abs=1)
    assert overlay.geometry().center().y() == pytest.approx(400, abs=1)


def test_qgc_overlay_follows_window_resize(qapp):
    from PySide6.QtWidgets import QWidget

    from mavixdesktop.ui.screens.joystick_setup import QGCSearchOverlay

    parent = QWidget()
    parent.resize(1200, 800)
    parent.show()
    overlay = QGCSearchOverlay(parent=parent)
    overlay.show_centered()
    parent.resize(600, 400)
    qapp.processEvents()

    assert overlay.geometry().center().x() == pytest.approx(300, abs=1)
    assert overlay.geometry().center().y() == pytest.approx(200, abs=1)
