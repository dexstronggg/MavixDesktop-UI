from __future__ import annotations

import json

from mavixdesktop.joystick import calibration


def _valid_cal() -> dict:
    return {
        'axis_thr': 1, 'axis_yaw': 0, 'axis_pitch': 3, 'axis_roll': 2,
        'thr_min': -1.0, 'thr_max': 1.0, 'thr_center': 0.0,
        'yaw_min': -1.0, 'yaw_max': 1.0, 'yaw_center': 0.0,
        'pitch_min': -1.0, 'pitch_max': 1.0, 'pitch_center': 0.0,
        'roll_min': -1.0, 'roll_max': 1.0, 'roll_center': 0.0,
        'arm_button_index': 0,
    }


def test_save_writes_file(tmp_path):
    cal = _valid_cal()
    p = calibration.save(cal, 'My Pad', data_dir=tmp_path)
    assert p.exists()
    assert json.loads(p.read_text()) == cal


def test_load_returns_dict(tmp_path):
    cal = _valid_cal()
    calibration.save(cal, 'My Pad', data_dir=tmp_path)
    assert calibration.load('My Pad', data_dir=tmp_path) == cal


def test_load_returns_none_if_missing(tmp_path):
    assert calibration.load('No Pad', data_dir=tmp_path) is None


def test_load_returns_none_on_garbage(tmp_path):
    f = tmp_path / 'Garbage.json'
    f.write_text('not-json{{')
    assert calibration.load('Garbage', data_dir=tmp_path) is None


def test_validate_accepts_complete():
    ok, err = calibration.validate(_valid_cal())
    assert ok is True
    assert err == ''


def test_validate_rejects_incomplete():
    cal = _valid_cal()
    del cal['arm_button_index']
    ok, err = calibration.validate(cal)
    assert ok is False
    assert 'arm_button_index' in err


def test_safe_name_strips_specials(tmp_path):
    cal = _valid_cal()
    p = calibration.save(cal, 'XBox/360 (R) #2!', data_dir=tmp_path)
    assert '/' not in p.name
    assert '(' not in p.name
    assert '#' not in p.name


def test_create_parent_dirs(tmp_path):
    nested = tmp_path / 'nested' / 'deeper'
    p = calibration.save(_valid_cal(), 'X', data_dir=nested)
    assert p.parent == nested
