"""Common application logger: single named singleton `logger`."""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from types import TracebackType
from typing import cast

_FORMAT = '%(asctime)s - %(levelname)s - %(name)s - %(message)s'
_MAX_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5
_THIRD_PARTY = ('aiortc', 'aioice', 'av', 'websockets', 'asyncio')


def _build_logger() -> logging.Logger:
    log = logging.getLogger('mavixdesktop')
    log.setLevel(logging.INFO)
    if log.handlers:
        return log
    formatter = logging.Formatter(_FORMAT)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    log.addHandler(stream)

    for name in _THIRD_PARTY:
        lib = logging.getLogger(name)
        if lib.level == logging.NOTSET:
            lib.setLevel(logging.WARNING)
        lib.addHandler(stream)

    if os.getenv('ICE_DEBUG', '').strip().lower() in ('1', 'true', 'yes', 'on'):
        for name in ('aioice', 'aiortc'):
            logging.getLogger(name).setLevel(logging.DEBUG)
        log.info('[ice] ICE_DEBUG включён — aioice/aiortc на DEBUG')
    return log


logger = _build_logger()


def enable_debug_logging() -> None:
    logger.setLevel(logging.DEBUG)
    logger.debug('[log] debug-режим включён — уровень логирования DEBUG')


def setup_file_logging() -> None:
    from mavixdesktop.core.config import settings

    if any(isinstance(h, logging.handlers.RotatingFileHandler) for h in logger.handlers):
        return

    log_path = settings.log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        filename=log_path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    for name in _THIRD_PARTY:
        logging.getLogger(name).addHandler(handler)


def install_exception_hooks() -> None:
    """Routes crashes into the log — otherwise they die on stderr, invisible in a bundle."""

    def _main_hook(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        logger.critical('необработанное исключение', exc_info=(exc_type, exc, tb))

    def _thread_hook(args: threading.ExceptHookArgs) -> None:
        if issubclass(args.exc_type, SystemExit):
            return
        name = args.thread.name if args.thread is not None else '?'
        logger.critical(
            'необработанное исключение в потоке %s', name,
            exc_info=cast(
                tuple[type[BaseException], BaseException, TracebackType | None],
                (args.exc_type, args.exc_value, args.exc_traceback),
            ),
        )

    sys.excepthook = _main_hook
    threading.excepthook = _thread_hook


def install_qt_message_handler() -> None:
    """Qt writes its warnings to stderr — in a bundled binary nobody ever sees them."""
    from PySide6.QtCore import QtMsgType, qInstallMessageHandler

    levels = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }

    def handler(mode: QtMsgType, context: object, message: str) -> None:
        logger.log(levels.get(mode, logging.INFO), '[qt] %s', message)

    qInstallMessageHandler(handler)
