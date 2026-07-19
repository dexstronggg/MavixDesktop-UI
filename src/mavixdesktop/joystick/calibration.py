"""Persistent joystick calibration: save/load JSON files in settings.data_path."""
from __future__ import annotations

import json
from pathlib import Path

from mavixdesktop.core.config import settings

REQUIRED_KEYS = frozenset({
    'axis_thr', 'axis_yaw', 'axis_pitch', 'axis_roll',
    'thr_min', 'thr_max', 'thr_center',
    'yaw_min', 'yaw_max', 'yaw_center',
    'pitch_min', 'pitch_max', 'pitch_center',
    'roll_min', 'roll_max', 'roll_center',
    'arm_button_index',
})


def _safe_name(joystick_name: str) -> str:
    return ''.join(c for c in joystick_name if c.isalnum() or c in ' _-')


def _path(joystick_name: str, data_dir: Path | None = None) -> Path:
    base = data_dir if data_dir is not None else settings.data_path
    return base / f'{_safe_name(joystick_name)}.json'


def save(cal: dict, joystick_name: str, data_dir: Path | None = None) -> Path:
    target = _path(joystick_name, data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(cal, indent=2))
    return target


def load(joystick_name: str, data_dir: Path | None = None) -> dict | None:
    target = _path(joystick_name, data_dir)
    if not target.exists():
        return None
    try:
        return json.loads(target.read_text())
    except (OSError, ValueError):
        return None


def validate(data: dict) -> tuple[bool, str]:
    missing = REQUIRED_KEYS - set(data.keys())
    if missing:
        return False, f'Missing keys: {", ".join(sorted(missing))}'
    return True, ''
