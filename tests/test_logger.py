"""Logging: rotation, no duplicate handlers, crashes end up in the log."""

from __future__ import annotations

import logging
import logging.handlers
import sys
import threading

import pytest

from mavixdesktop.core import logger as logger_module


@pytest.fixture
def clean_logger(tmp_path, monkeypatch):
    log = logger_module.logger
    saved = list(log.handlers)
    log.handlers = [
        h for h in saved if not isinstance(h, logging.handlers.RotatingFileHandler)
    ]

    from mavixdesktop.core.config import settings

    monkeypatch.setattr(settings, 'log_path', tmp_path / 'logs' / 'mavixdesktop.log')

    saved_excepthook = sys.excepthook
    saved_threadhook = threading.excepthook
    yield log
    log.handlers = saved
    sys.excepthook = saved_excepthook
    threading.excepthook = saved_threadhook


def _file_handlers(log):
    return [
        h for h in log.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]


def test_file_logging_uses_rotation(clean_logger, tmp_path):
    logger_module.setup_file_logging()
    handlers = _file_handlers(clean_logger)
    assert len(handlers) == 1
    assert handlers[0].maxBytes > 0
    assert handlers[0].backupCount > 0


def test_file_logging_is_idempotent(clean_logger):
    logger_module.setup_file_logging()
    logger_module.setup_file_logging()
    assert len(_file_handlers(clean_logger)) == 1


def test_rotation_actually_rolls_over(clean_logger, tmp_path):
    logger_module.setup_file_logging()
    handler = _file_handlers(clean_logger)[0]
    handler.maxBytes = 512
    for i in range(200):
        clean_logger.info('строка лога номер %d, набиваем объём для ротации', i)
    log_dir = tmp_path / 'logs'
    assert (log_dir / 'mavixdesktop.log').exists()
    assert (log_dir / 'mavixdesktop.log.1').exists()


def test_uncaught_exception_is_logged(clean_logger, caplog):
    logger_module.install_exception_hooks()
    with caplog.at_level(logging.CRITICAL, logger='mavixdesktop'):
        try:
            raise ValueError('тестовый сбой')
        except ValueError:
            sys.excepthook(*sys.exc_info())
    assert 'необработанное исключение' in caplog.text
    assert 'тестовый сбой' in caplog.text


def test_keyboard_interrupt_is_not_swallowed(clean_logger, caplog, monkeypatch):
    logger_module.install_exception_hooks()
    seen: list = []
    monkeypatch.setattr(sys, '__excepthook__', lambda *a: seen.append(a))
    with caplog.at_level(logging.CRITICAL, logger='mavixdesktop'):
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    assert seen, 'KeyboardInterrupt должен уходить в штатный обработчик'
    assert caplog.text == ''


def test_thread_exception_is_logged(clean_logger, caplog):
    logger_module.install_exception_hooks()

    def boom() -> None:
        raise RuntimeError('сбой в потоке')

    with caplog.at_level(logging.CRITICAL, logger='mavixdesktop'):
        thread = threading.Thread(target=boom, name='рабочий')
        thread.start()
        thread.join()
    assert 'необработанное исключение в потоке рабочий' in caplog.text
    assert 'сбой в потоке' in caplog.text
