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
