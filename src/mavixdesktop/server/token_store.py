"""Token storage over OS keyring with file fallback."""
from __future__ import annotations

import json
import os
from pathlib import Path

from mavixdesktop.core.config import settings
from mavixdesktop.core.logger import logger

_REFRESH_KEY = 'refresh_token'
_EMAIL_KEY = 'email'


def _file_path() -> Path:
    return settings.config_dir / 'tokens.json'


def _read_file() -> dict:
    p = _file_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _write_file(data: dict) -> None:
    p = _file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(json.dumps(data))
    os.chmod(p, 0o600)


def _keyring() -> object | None:
    try:
        import keyring
        return keyring
    except ImportError:
        return None


def save(email: str, refresh_token: str) -> None:
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(settings.keyring_service, _REFRESH_KEY, refresh_token)
            kr.set_password(settings.keyring_service, _EMAIL_KEY, email)
            return
        except Exception as exc:
            logger.warning('[token] запись в keyring не удалась (%s), откат на файл', exc)
    _write_file({_REFRESH_KEY: refresh_token, _EMAIL_KEY: email})


def load() -> tuple[str | None, str | None]:
    kr = _keyring()
    if kr is not None:
        try:
            email = kr.get_password(settings.keyring_service, _EMAIL_KEY)
            token = kr.get_password(settings.keyring_service, _REFRESH_KEY)
            if token is not None:
                return email, token
        except Exception as exc:
            logger.debug('[token] чтение keyring не удалось (%s), пробуем файл', exc)
    data = _read_file()
    return data.get(_EMAIL_KEY), data.get(_REFRESH_KEY)


def clear() -> None:
    kr = _keyring()
    if kr is not None:
        for key in (_REFRESH_KEY, _EMAIL_KEY):
            try:
                kr.delete_password(settings.keyring_service, key)
            except Exception:
                pass
    p = _file_path()
    if p.exists():
        try:
            p.unlink()
        except OSError as exc:
            logger.debug('[token] ошибка удаления файла: %s', exc)
