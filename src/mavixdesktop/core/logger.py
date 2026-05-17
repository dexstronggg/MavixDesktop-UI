from __future__ import annotations

import logging

from mavixdesktop.core.config import settings


def _build_logger() -> logging.Logger:
    log = logging.getLogger('mavixdesktop')
    log.setLevel(logging.INFO)
    if log.handlers:
        return log
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    log.addHandler(stream)
    return log


logger = _build_logger()


def setup_file_logging() -> None:
    log_path = settings.log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    file_handler = logging.FileHandler(filename=log_path)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
