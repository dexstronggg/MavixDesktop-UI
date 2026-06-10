"""Точка входа: python -m mavixdesktop.

По умолчанию открывает PySide6 UI (страница логина → список дронов → видео).
Флаг --headless оставляет legacy-режим без GUI (авторизация + цикл
координатора), удобный для длительного прогона против живого сервера.
"""
from __future__ import annotations

import argparse
import asyncio
import faulthandler
import os
import sys

# В windowed-сборке PyInstaller (console=False) консоли нет, поэтому
# sys.stdout / sys.stderr == None — и faulthandler.enable(), logging
# StreamHandler или print падают с «RuntimeError: sys.stderr is None».
# Подменяем пустые потоки на devnull ДО импорта логгера и faulthandler.
# Реальные логи всё равно пишутся в файл (см. setup_file_logging).
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')

from mavixdesktop.coordinator import SessionCoordinator
from mavixdesktop.core.config import settings
from mavixdesktop.core.logger import logger, setup_file_logging
from mavixdesktop.server import token_store
from mavixdesktop.server.api import ApiError, ApiSession
from mavixdesktop.server.signal_client import SignalClient


def _init_dirs() -> None:
    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.log_path.parent.mkdir(parents=True, exist_ok=True)
    settings.config_dir.mkdir(parents=True, exist_ok=True)
    setup_file_logging()


#### Headless-режим ####################################################################
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


#### GUI-режим #########################################################################
def _server_reachable(timeout_sec: float = 2.0) -> bool:
    """Быстрый sync-пинг сервера на /api/v1/health. True = жив, иначе False.

    Используется только как сигнал «включать ли авто-демо-режим» при
    старте GUI — на интерактивный логин не влияет.
    """
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
    """Event-filter, ставит PointingHandCursor на каждый QPushButton при
    его первом polish-событии. Так не нужно вручную дёргать setCursor
    на каждом сайте создания кнопки — в том числе на сторонних виджетах
    из библиотек.
    """

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
    """Event-filter, удерживающий QToolTip внутри application window.

    Qt позиционирует тултип относительно курсора — если виджет с длинной
    подсказкой стоит у нижнего края окна (как кнопка калибровки в
    SettingsBar), тултип уходит ПОД нижнюю границу и обрезается. Здесь
    перехватываем QEvent.ToolTip и при необходимости сами вызываем
    QToolTip.showText с поднятой позицией.
    """

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
                # globalPos() / globalPosition() — координаты курсора при
                # ToolTip-событии. Для PySide6 берём globalPos (deprecated
                # в Qt6 но всё ещё работает) — globalPosition() возвращает
                # QPointF, дальше требует .toPoint().
                try:
                    cursor_global = event.globalPos()
                except AttributeError:
                    cursor_global = event.globalPosition().toPoint()

                win_top_left = win.mapToGlobal(QPoint(0, 0))
                win_bottom_y = win_top_left.y() + win.height()
                # Эмпирическая высота однострочного тултипа в Qt ≈ 28-30 px.
                # Для двухстрочных будет ~50 — берём с запасом 56 чтобы
                # не упереться в нижнюю границу при многострочном тексте.
                tooltip_h = 56
                # Тултип отрисовывается чуть ниже курсора (~24 px смещение).
                tooltip_bottom_if_default = cursor_global.y() + 24 + tooltip_h
                if tooltip_bottom_if_default <= win_bottom_y:
                    return False  # Помещается стандартно — не мешаем Qt
                # Не помещается: ставим тултип НАД курсором так, чтобы его
                # нижний край пришёлся на ~16 px выше курсора.
                adjusted_y = cursor_global.y() - tooltip_h - 8
                adjusted_y = max(adjusted_y, win_top_left.y() + 8)
                adjusted = QPoint(cursor_global.x(), adjusted_y)
                QToolTip.showText(adjusted, tip, obj)
                return True  # Подавляем дефолтное позиционирование Qt

        self._filter = _Filter()

    def attach_to(self, app) -> None:
        app.installEventFilter(self._filter)


def _run_gui(demo: bool = False) -> int:
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication

    from mavixdesktop.ui.app import App
    from mavixdesktop.ui.screens.utils import mavix_logo_pixmap
    from mavixdesktop.ui.style import theme

    # Авто-фолбэк: если пользователь не указал --demo, но сервер не
    # отвечает на /health за 2 с — поднимаем демо-режим автоматически,
    # чтобы можно было хотя бы посмотреть/потрогать UI.
    if not demo and not _server_reachable():
        logger.warning(
            '[bootstrap] сигнальный сервер недоступен, переключаемся в демо-режим'
        )
        demo = True

    app = QApplication(sys.argv)
    # Иконка приложения для title-bar, Alt-Tab, taskbar. Генерируем M-логотип
    # в нескольких размерах через mavix_logo_pixmap — Qt сам выбирает лучший
    # для каждого контекста. Без этого Windows показывает дефолтный «pythonw»
    # иконку (excel-подобную), что сразу выдаёт «это скрипт, а не продукт».
    app_icon = QIcon()
    for size in (16, 24, 32, 48, 64, 96, 128, 256):
        app_icon.addPixmap(mavix_logo_pixmap(size))
    app.setWindowIcon(app_icon)
    # Fusion — кроссплатформенный стиль Qt, который корректно отрисовывает
    # border-radius/padding из QSS на всех ОС (нативные стили Windows /
    # macOS их часто игнорируют, и кнопки оставались бы прямоугольными).
    app.setStyle('Fusion')
    # Inter — основной интерфейсный шрифт, как на сайте Mavix. Если он
    # не установлен в системе, Qt автоматически подставит следующий
    # из цепочки fallback (через FONT_FAMILY в QSS-правилах).
    font = QFont('Inter')
    font.setStyleStrategy(QFont.PreferAntialias)
    font.setPixelSize(theme.FONT_SIZE_BASE)
    app.setFont(font)
    # Глобальные QSS-правила: тёмная палитра + cyan-акцент,
    # выровнено со стилем сайта.
    app.setStyleSheet(theme.QSS_GLOBAL)
    # Глобальный pointing-hand cursor для всех QPushButton.
    # QSS-свойство cursor Qt не поддерживает, ставим через
    # event-filter на Polish (срабатывает один раз для каждой
    # кнопки до первого show).
    cursor_filter = _PointingCursorFilter()
    cursor_filter.attach_to(app)
    app._mavix_cursor_filter = cursor_filter  # type: ignore[attr-defined]
    # Удержание тултипов внутри окна — у виджетов в нижней части
    # SettingsBar/flight-окна Qt по умолчанию ставил тултип под
    # курсором, и длинные подписи уходили за нижнюю границу.
    tooltip_filter = _BoundedToolTipFilter()
    tooltip_filter.attach_to(app)
    app._mavix_tooltip_filter = tooltip_filter  # type: ignore[attr-defined]

    window = App(demo=demo)
    window.show()
    return app.exec()


#### Точка входа #######################################################################
def main() -> None:
    # Включаем дамп Python-стека при SIGSEGV/SIGFPE/SIGABRT.
    # Пишем в stderr И в mavix_crash.log во временном каталоге — второй
    # вариант гарантированно переживёт крэш и не теряется при перезапуске.
    # (stderr к этому моменту уже не None — подменён на devnull выше, если
    # консоли нет; путь через tempfile, чтобы работало и на Windows.)
    faulthandler.enable()
    try:
        import tempfile
        _crash_log = open(os.path.join(tempfile.gettempdir(), 'mavix_crash.log'), 'w')
        faulthandler.enable(file=_crash_log, all_threads=True)
    except OSError:
        pass

    parser = argparse.ArgumentParser(prog='mavixdesktop', description='Mavix GCS')
    parser.add_argument('--headless', action='store_true',
                        help='Запустить координатор без Qt UI')
    parser.add_argument('--demo', action='store_true',
                        help='Запустить UI с мок-данными (без сервера). '
                             'Принимает любые email/пароль, показывает '
                             'тестовых дронов и один мок-джойстик.')
    parser.add_argument('--email', help='email для входа (первый запуск, headless или GUI)')
    parser.add_argument('--password', help='пароль для входа (первый запуск, только headless)')
    args = parser.parse_args()

    _init_dirs()
    if args.headless:
        try:
            asyncio.run(_run_headless(args.email, args.password))
        except KeyboardInterrupt:
            pass
        return

    sys.exit(_run_gui(demo=args.demo))


if __name__ == '__main__':
    main()
