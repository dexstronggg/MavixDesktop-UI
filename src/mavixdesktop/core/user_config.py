"""User config saved to ~/.config/mavixdesktop/config.json."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mavixdesktop.core.logger import logger

USER_CONFIG_PATH = Path.home() / '.config' / 'mavixdesktop' / 'config.json'

EDITABLE_KEYS = (
    'signal_url',
    'stun_server',
    'turn_server',
    'turn_username',
    'turn_password',
    'qgc_host',
    'qgc_port',
    'force_relay',
)


def load() -> dict[str, Any]:
    if not USER_CONFIG_PATH.is_file():
        return {}
    try:
        with USER_CONFIG_PATH.open('r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning('[user-config] %s не является JSON-объектом, игнорируем', USER_CONFIG_PATH)
            return {}
        return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning('[user-config] не удалось прочитать %s: %s', USER_CONFIG_PATH, exc)
        return {}


def save(values: dict[str, Any]) -> None:
    USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = USER_CONFIG_PATH.with_suffix('.json.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        json.dump(values, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, USER_CONFIG_PATH)


_MAPPING = {
    'signal_url':    'SIGNAL_URL',
    'stun_server':   'STUN_SERVER',
    'turn_server':   'TURN_SERVER',
    'turn_username': 'TURN_USERNAME',
    'turn_password': 'TURN_PASSWORD',
    'qgc_host':      'QGC_HOST',
    'qgc_port':      'QGC_PORT',
    'force_relay':   'FORCE_RELAY',
}

_MANAGED_KEYS: set[str] = set()


def apply_to_env() -> None:
    for env_key in list(_MANAGED_KEYS):
        os.environ.pop(env_key, None)
    _MANAGED_KEYS.clear()

    data = load()
    if not data:
        return
    for json_key, env_key in _MAPPING.items():
        if env_key in os.environ:
            continue
        value = data.get(json_key)
        if value is None or value == '':
            continue
        os.environ[env_key] = str(value)
        _MANAGED_KEYS.add(env_key)
