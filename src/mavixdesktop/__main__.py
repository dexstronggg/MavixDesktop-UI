"""Entry point: python -m mavixdesktop."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys

from mavixdesktop.coordinator import SessionCoordinator
from mavixdesktop.core.config import settings
from mavixdesktop.core.logger import enable_debug_logging, logger, setup_file_logging
from mavixdesktop.server import token_store
from mavixdesktop.server.api import ApiError, ApiSession
from mavixdesktop.server.signal_client import SignalClient


def _init_dirs() -> None:
    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    setup_file_logging()


async def _authenticate_headless(api: ApiSession, email: str | None, password: str | None) -> tuple[str, str]:
    stored_email, stored_refresh = token_store.load()
    if stored_refresh:
        try:
            result = await api.refresh(stored_refresh)
            access = result.get('access_token', '')
            if access:
                logger.info('[auth] обновлён access-токен для %s', stored_email)
                return access, stored_refresh
        except ApiError as exc:
            logger.info('[auth] сохранённый refresh недействителен: %s', exc)

    if not email or not password:
        raise SystemExit(
            'нет валидных сохранённых учётных данных и не переданы --email/--password. '
            'запустите с --email me@example.com --password ... для первого входа.'
        )

    result = await api.login(email, password)
    access = result['access_token']
    refresh = result['refresh_token']
    token_store.save(email, refresh)
    logger.info('[auth] выполнен вход как %s; refresh-токен сохранён', email)
    return access, refresh


async def _run_headless(email: str | None, password: str | None) -> None:
    api = await ApiSession.create()
    try:
        if not await api.health():
            logger.error('[bootstrap] сигнальный сервер недоступен по адресу %s', settings.http_url)
            return
        access, refresh = await _authenticate_headless(api, email, password)
        signal_client = SignalClient(url=settings.ws_url, access_token=access)
        coordinator = SessionCoordinator(
            signal_client=signal_client,
            api_session=api,
            refresh_token=refresh,
        )
        await coordinator.run()
    finally:
        await api.close()


def _server_reachable(timeout_sec: float = 2.0) -> bool:
    import urllib.error
    import urllib.request
    url = settings.http_url.rstrip('/') + '/api/v1/health'
    try:
        with urllib.request.urlopen(url, timeout=timeout_sec) as resp:
            return 200 <= resp.status < 400
    except Exception as exc:
        logger.info('[bootstrap] проверка health не удалась: %s', exc)
        return False


class _PointingCursorFilter:
    def __init__(self) -> None:
        from PySide6.QtCore import QObject
        from PySide6.QtWidgets import QPushButton

        class _Filter(QObject):
            def eventFilter(self, obj, event):
                from PySide6.QtCore import QEvent, Qt
                if event.type() == QEvent.Polish and isinstance(obj, QPushButton):
                    obj.setCursor(Qt.PointingHandCursor)
                return False

        self._filter = _Filter()

    def attach_to(self, app) -> None:
        app.installEventFilter(self._filter)


class _BoundedToolTipFilter:
    def __init__(self) -> None:
        from PySide6.QtCore import QEvent, QObject, QPoint
        from PySide6.QtWidgets import QToolTip, QWidget

        class _Filter(QObject):
            def eventFilter(self, obj, event):
                if event.type() != QEvent.ToolTip:
                    return False
                if not isinstance(obj, QWidget):
                    return False
                tip = obj.toolTip()
                if not tip:
                    return False
                win = obj.window()
                if win is None:
                    return False
                try:
                    cursor_global = event.globalPos()
                except AttributeError:
                    cursor_global = event.globalPosition().toPoint()

                win_top_left = win.mapToGlobal(QPoint(0, 0))
                win_bottom_y = win_top_left.y() + win.height()
                tooltip_h = 56
                tooltip_bottom_if_default = cursor_global.y() + 24 + tooltip_h
                if tooltip_bottom_if_default <= win_bottom_y:
                    return False
                adjusted_y = cursor_global.y() - tooltip_h - 8
                adjusted_y = max(adjusted_y, win_top_left.y() + 8)
                adjusted = QPoint(cursor_global.x(), adjusted_y)
                QToolTip.showText(adjusted, tip, obj)
                return True

        self._filter = _Filter()

    def attach_to(self, app) -> None:
        app.installEventFilter(self._filter)


def _run_gui(demo: bool = False) -> int:
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication

    from mavixdesktop.ui.app import App
    from mavixdesktop.ui.screens.utils import mavix_logo_pixmap
    from mavixdesktop.ui.style import theme

    if settings.debug:
        enable_debug_logging()
        logger.info('[bootstrap] DEBUG-режим включён — старт на debug-странице')

    if not demo and not settings.debug and not _server_reachable():
        logger.warning(
            '[bootstrap] сигнальный сервер недоступен, переключаемся в демо-режим'
        )
        demo = True

    app = QApplication(sys.argv)
    app_icon = QIcon()
    for size in (16, 24, 32, 48, 64, 96, 128, 256):
        app_icon.addPixmap(mavix_logo_pixmap(size))
    app.setWindowIcon(app_icon)
    app.setStyle('Fusion')
    font = QFont('Inter')
    font.setStyleStrategy(QFont.PreferAntialias)
    font.setPixelSize(theme.FONT_SIZE_BASE)
    app.setFont(font)
    app.setStyleSheet(theme.QSS_GLOBAL)
    cursor_filter = _PointingCursorFilter()
    cursor_filter.attach_to(app)
    app._mavix_cursor_filter = cursor_filter
    tooltip_filter = _BoundedToolTipFilter()
    tooltip_filter.attach_to(app)
    app._mavix_tooltip_filter = tooltip_filter

    window = App(demo=demo, debug=settings.debug)
    window.show()
    return app.exec()


def main() -> None:
    parser = argparse.ArgumentParser(prog='mavixdesktop', description='Mavix GCS')
    parser.add_argument('--headless', action='store_true',
                        help='Run coordinator without Qt UI')
    parser.add_argument('--demo', action='store_true',
                        help='Run UI with mock data (no server). '
                             'Accepts any email/password, shows '
                             'test drones and a mock joystick.')
    parser.add_argument('--email', help='email for login (first run, headless or GUI)')
    parser.add_argument('--password', help='password for login (first run, headless only)')
    args = parser.parse_args()

    _init_dirs()
    if args.headless:
        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(_run_headless(args.email, args.password))
        return

    sys.exit(_run_gui(demo=args.demo))


if __name__ == '__main__':
    main()
