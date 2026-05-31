"""Общий логгер приложения: единый именованный синглтон `logger`."""
from __future__ import annotations

import logging
import os


def _build_logger() -> logging.Logger:
    log = logging.getLogger('mavixdesktop')
    log.setLevel(logging.INFO)
    if log.handlers:
        return log
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    log.addHandler(stream)

    # ICE_DEBUG=1 включает DEBUG-логирование aioice/aiortc — каждую кандидат-пару,
    # connectivity-проверку и TURN-запрос. Используется для диагностики, почему
    # relay-пара не проходит валидацию (нет permission, нет ответа и т.п.).
    if os.getenv('ICE_DEBUG', '').strip().lower() in ('1', 'true', 'yes', 'on'):
        for name in ('aioice', 'aiortc'):
            dbg = logging.getLogger(name)
            dbg.setLevel(logging.DEBUG)
            dbg.addHandler(stream)
        log.info('[ice] ICE_DEBUG включён — aioice/aiortc на DEBUG')
    return log


logger = _build_logger()


def setup_file_logging() -> None:
    # Импорт settings отложен внутрь функции, чтобы не создавать цикл
    # импорта: core.config импортирует user_config, который пользуется
    # этим логгером ещё до того, как config закончит инициализацию.
    from mavixdesktop.core.config import settings

    log_path = settings.log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    file_handler = logging.FileHandler(filename=log_path)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
