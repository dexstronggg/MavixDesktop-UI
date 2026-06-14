"""Tests for joystick.input.JoystickInput — pygame is fully mocked."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock


def _install_pygame_mock(monkeypatch, axes_by_idx: dict[int, float], buttons_by_idx: dict[int, int] | None = None):
    pg = MagicMock()
    js = MagicMock()
    js.get_axis.side_effect = lambda idx: axes_by_idx.get(idx, 0.0)
    js.get_button.side_effect = lambda idx: (buttons_by_idx or {}).get(idx, 0)
    js.get_name.return_value = 'Fake Pad'
    pg.joystick.Joystick.return_value = js
    monkeypatch.setitem(sys.modules, 'pygame', pg)
    return js


def _full_cal() -> dict:
    return {
        'axis_thr': 1, 'axis_yaw': 0, 'axis_pitch': 3, 'axis_roll': 2,
        'thr_min': -1.0, 'thr_max': 1.0, 'thr_center': 0.0,
        'yaw_min': -1.0, 'yaw_max': 1.0, 'yaw_center': 0.0,
        'pitch_min': -1.0, 'pitch_max': 1.0, 'pitch_center': 0.0,
        'roll_min': -1.0, 'roll_max': 1.0, 'roll_center': 0.0,
        'arm_type': 'button', 'arm_button_index': 4,
    }


def test_reads_centered_axes_as_zero(monkeypatch):
    _install_pygame_mock(monkeypatch, axes_by_idx={0: 0.0, 1: 0.0, 2: 0.0, 3: 0.0})
    from mavixdesktop.joystick.input import JoystickInput

    js = JoystickInput(0, _full_cal())
    thr, yaw, pitch, roll = js.get_stick_positions()
    assert (thr, yaw, pitch, roll) == (0.0, 0.0, 0.0, 0.0)


def test_reads_full_positive_axes_as_one(monkeypatch):
    _install_pygame_mock(monkeypatch, axes_by_idx={0: 1.0, 1: 1.0, 2: 1.0, 3: 1.0})
    from mavixdesktop.joystick.input import JoystickInput

    js = JoystickInput(0, _full_cal())
    thr, yaw, pitch, roll = js.get_stick_positions()
    assert thr == 1.0
    assert yaw == 1.0
    assert pitch == 1.0
    assert roll == 1.0


def test_reads_full_negative_axes_as_minus_one(monkeypatch):
    _install_pygame_mock(monkeypatch, axes_by_idx={0: -1.0, 1: -1.0, 2: -1.0, 3: -1.0})
    from mavixdesktop.joystick.input import JoystickInput

    js = JoystickInput(0, _full_cal())
    thr, yaw, pitch, roll = js.get_stick_positions()
    assert thr == -1.0
    assert yaw == -1.0
    assert pitch == -1.0
    assert roll == -1.0


def test_handles_axis_read_error_gracefully(monkeypatch):
    pg = MagicMock()
    js = MagicMock()
    js.get_axis.side_effect = RuntimeError('hw fail')
    pg.joystick.Joystick.return_value = js
    monkeypatch.setitem(sys.modules, 'pygame', pg)
    from mavixdesktop.joystick.input import JoystickInput

    j = JoystickInput(0, _full_cal())
    assert j.get_stick_positions() == (0.0, 0.0, 0.0, 0.0)


def test_arm_button_toggles_on_press_release(monkeypatch):
    pg = MagicMock()
    js = MagicMock()
    button_state = {'val': 0}
    js.get_axis.side_effect = lambda idx: 0.0
    js.get_button.side_effect = lambda idx: button_state['val']
    pg.joystick.Joystick.return_value = js
    monkeypatch.setitem(sys.modules, 'pygame', pg)
    from mavixdesktop.joystick.input import JoystickInput

    j = JoystickInput(0, _full_cal())
    assert j.is_armed() is False
    # press
    button_state['val'] = 1
    assert j.is_armed() is True
    # release
    button_state['val'] = 0
    assert j.is_armed() is True  # stays armed
    # press again → toggle off
    button_state['val'] = 1
    assert j.is_armed() is False


def test_arm_axis_mode(monkeypatch):
    cal = _full_cal()
    cal['arm_type'] = 'axis'
    cal['arm_axis_index'] = 5
    pg = MagicMock()
    js = MagicMock()
    axis_state = {5: -1.0}
    js.get_axis.side_effect = lambda idx: axis_state.get(idx, 0.0)
    pg.joystick.Joystick.return_value = js
    monkeypatch.setitem(sys.modules, 'pygame', pg)
    from mavixdesktop.joystick.input import JoystickInput

    j = JoystickInput(0, cal)
    assert j.is_armed() is False
    axis_state[5] = 1.0
    assert j.is_armed() is True


def test_arm_axis_in_arm_on_entry_requires_disarm_first(monkeypatch):
    """Вход в полёт с тумблером, оставленным в ARM, НЕ должен армировать сразу:
    is_armed() держит DISARM, пока тумблер не пройдёт через DISARM."""
    cal = _full_cal()
    cal['arm_type'] = 'axis'
    cal['arm_axis_index'] = 5
    pg = MagicMock()
    js = MagicMock()
    axis_state = {5: 1.0}  # тумблер УЖЕ в ARM в момент входа
    js.get_axis.side_effect = lambda idx: axis_state.get(idx, 0.0)
    pg.joystick.Joystick.return_value = js
    monkeypatch.setitem(sys.modules, 'pygame', pg)
    from mavixdesktop.joystick.input import JoystickInput

    j = JoystickInput(0, cal)
    # защёлка держит DISARM, сколько бы ни опрашивали
    assert j.is_armed() is False
    assert j.is_armed() is False
    # оператор перевёл тумблер в DISARM
    axis_state[5] = -1.0
    assert j.is_armed() is False
    # после этого ARM снова работает как обычно
    axis_state[5] = 1.0
    assert j.is_armed() is True


def test_arm_axis_read_error_returns_false(monkeypatch):
    cal = _full_cal()
    cal['arm_type'] = 'axis'
    cal['arm_axis_index'] = 5
    pg = MagicMock()
    js = MagicMock()
    js.get_axis.side_effect = RuntimeError('boom')
    pg.joystick.Joystick.return_value = js
    monkeypatch.setitem(sys.modules, 'pygame', pg)
    from mavixdesktop.joystick.input import JoystickInput

    j = JoystickInput(0, cal)
    assert j.is_armed() is False


def test_partial_calibration_uses_defaults(monkeypatch):
    """Even when calibration dict is sparse, reads should not crash."""
    _install_pygame_mock(monkeypatch, axes_by_idx={0: 0.5})
    cal = {'axis_thr': 0}  # everything else missing
    from mavixdesktop.joystick.input import JoystickInput

    j = JoystickInput(0, cal)
    thr, *_ = j.get_stick_positions()
    assert -1.0 <= thr <= 1.0


def test_name_property(monkeypatch):
    _install_pygame_mock(monkeypatch, axes_by_idx={})
    from mavixdesktop.joystick.input import JoystickInput

    j = JoystickInput(0, _full_cal())
    assert j.name == 'Fake Pad'
