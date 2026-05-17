"""Tests for joystick.manager — only pure-Python helpers; list_joysticks
is exercised by an integration smoke test that doesn't assume a pad."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

from mavixdesktop.joystick.manager import build_sdl_config, list_joysticks


def _cal_neutral() -> dict:
    return {
        'axis_thr': 1, 'axis_yaw': 0, 'axis_pitch': 3, 'axis_roll': 2,
        'thr_min': -1.0, 'thr_max': 1.0,
        'yaw_min': -1.0, 'yaw_max': 1.0,
        'pitch_min': -1.0, 'pitch_max': 1.0,
        'roll_min': -1.0, 'roll_max': 1.0,
        'arm_button_index': 3,
    }


def test_build_sdl_config_basic_shape():
    s = build_sdl_config(_cal_neutral(), 'Test Pad', 'guid-abc')
    parts = s.split(',')
    assert parts[0] == 'guid-abc'
    assert parts[1] == 'Test Pad'
    # one entry per stick + arm + platform
    assert any(p.startswith('leftx:') for p in parts)
    assert any(p.startswith('lefty:') for p in parts)
    assert any(p.startswith('rightx:') for p in parts)
    assert any(p.startswith('righty:') for p in parts)
    assert any(p.startswith('a:b') for p in parts)
    assert any(p.startswith('platform:') for p in parts)


def test_build_sdl_arm_button_index_used():
    cal = _cal_neutral()
    cal['arm_button_index'] = 7
    s = build_sdl_config(cal, 'p', 'g')
    assert 'a:b7' in s


def test_build_sdl_inverts_axis_when_max_lt_min():
    # raw axis: pushing up gives 1.0 (max=1, min=-1) → not inverted
    cal = _cal_neutral()
    s = build_sdl_config(cal, 'p', 'g')
    # lefty gets a '~' because thr is NOT inverted (thr_max > thr_min)
    assert 'lefty:a1~' in s

    # Flip the bounds → inverted
    cal['thr_max'] = -1.0
    cal['thr_min'] = 1.0
    s2 = build_sdl_config(cal, 'p', 'g')
    assert 'lefty:a1,' in s2 or s2.endswith('lefty:a1') or 'lefty:a1,' in s2 + ','


def test_build_sdl_axis_indices_match_calibration():
    cal = _cal_neutral()
    cal['axis_yaw'] = 5
    cal['axis_thr'] = 6
    cal['axis_roll'] = 7
    cal['axis_pitch'] = 8
    s = build_sdl_config(cal, 'p', 'g')
    assert 'leftx:a5' in s
    assert 'lefty:a6' in s
    assert 'rightx:a7' in s
    assert 'righty:a8' in s


def test_list_joysticks_returns_list_when_pygame_mocked(monkeypatch):
    pg = MagicMock()
    pg.joystick.get_count.return_value = 2
    pg.joystick.Joystick.return_value.get_name.side_effect = ['Pad A', 'Pad B']
    monkeypatch.setitem(sys.modules, 'pygame', pg)

    names = list_joysticks()
    assert len(names) == 2
