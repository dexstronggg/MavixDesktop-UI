"""User config persisted at ~/.config/mavixdesktop/config.json.

This is what the Settings UI reads from and writes to. The file is
loaded at startup (in core.config) and overrides the defaults baked
into the binary. OS env vars still win over the file - that's by
design so a developer can override anything from the shell.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

USER_CONFIG_PATH = Path.home() / '.config' / 'mavixdesktop' / 'config.json'

# Which keys the Settings UI exposes. The Settings page renders fields
# in this order and saves only these keys to disk - unknown keys in
# the file are preserved on save but ignored by the UI.
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
    """Read the JSON config. Returns an empty dict if the file doesn't
    exist or is unreadable - callers fall back to their defaults."""
    if not USER_CONFIG_PATH.is_file():
        return {}
    try:
        with USER_CONFIG_PATH.open('r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning('user config %s is not a JSON object, ignoring', USER_CONFIG_PATH)
            return {}
        return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning('failed to read user config %s: %s', USER_CONFIG_PATH, exc)
        return {}


def save(values: dict[str, Any]) -> None:
    """Write the JSON config atomically. Creates the directory if needed."""
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

# Env-keys that the JSON layer is currently responsible for, so on
# reload we can safely clear them before re-applying the fresh JSON.
# A key that came from a real OS env var (set before this module was
# ever imported) is NOT in this set and will be left alone.
_MANAGED_KEYS: set[str] = set()


def apply_to_env() -> None:
    """Project the JSON config into os.environ so pydantic-settings picks
    it up. Real OS env vars set before the first call always take
    precedence. Subsequent calls reset previously-managed keys so that
    clearing a field in Settings UI actually unsets it."""
    # Remove anything we set on a previous pass so an empty JSON value
    # really empties the env, not just keeps the stale one.
    for env_key in list(_MANAGED_KEYS):
        os.environ.pop(env_key, None)
    _MANAGED_KEYS.clear()

    data = load()
    if not data:
        return
    for json_key, env_key in _MAPPING.items():
        if env_key in os.environ:
            # Real OS env var set externally - leave it alone.
            continue
        value = data.get(json_key)
        if value is None or value == '':
            continue
        os.environ[env_key] = str(value)
        _MANAGED_KEYS.add(env_key)
