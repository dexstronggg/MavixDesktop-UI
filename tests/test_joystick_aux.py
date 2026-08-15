"""Tests for reading spare joystick controls as AUX channels."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

from mavixdesktop.fc.crsf import CH_CENTER, CH_MAX, CH_MIN
from mavixdesktop.joystick.channels import AUX_COUNT


def _pad(
    monkeypatch,
    buttons: dict[int, int] | None = None,
    axes: dict[int, float] | None = None,
    hats: dict[int, tuple[int, int]] | None = None,
    num_buttons: int = 4,
    num_axes: int = 4,
    num_hats: int = 0,
):
    pg = MagicMock()
    js = MagicMock()
    js.get_button.side_effect = lambda i: (buttons or {}).get(i, 0)
    js.get_axis.side_effect = lambda i: (axes or {}).get(i, 0.0)
    js.get_hat.side_effect = lambda i: (hats or {}).get(i, (0, 0))
    js.get_numbuttons.return_value = num_buttons
    js.get_numaxes.return_value = num_axes
    js.get_numhats.return_value = num_hats
    js.get_name.return_value = 'Fake Pad'
    pg.joystick.Joystick.return_value = js
    monkeypatch.setitem(sys.modules, 'pygame', pg)
    return js


def _cal(**extra) -> dict:
    base = {
        'axis_thr': 1,
        'axis_yaw': 0,
        'axis_pitch': 3,
        'axis_roll': 2,
        'thr_min': -1.0,
        'thr_max': 1.0,
        'thr_center': 0.0,
        'yaw_min': -1.0,
        'yaw_max': 1.0,
        'yaw_center': 0.0,
        'pitch_min': -1.0,
        'pitch_max': 1.0,
        'pitch_center': 0.0,
        'roll_min': -1.0,
        'roll_max': 1.0,
        'roll_center': 0.0,
        'arm_type': 'button',
        'arm_button_index': 0,
    }
    base.update(extra)
    return base


def _make(monkeypatch, cal, **pad_kwargs):
    js = _pad(monkeypatch, **pad_kwargs)
    from mavixdesktop.joystick.input import JoystickInput

    return JoystickInput(0, cal, pump_events=False), js


class TestAuxChannels:
    def test_returns_one_value_per_spare_channel(self, monkeypatch):
        joy, _ = _make(monkeypatch, _cal())
        assert len(joy.get_aux_channels()) == AUX_COUNT

    def test_idle_pad_is_centered_except_release(self, monkeypatch):
        joy, _ = _make(monkeypatch, _cal())
        values = joy.get_aux_channels()
        assert values[0] == CH_MIN  # сброс не нажат
        assert values[1:] == [CH_CENTER] * (AUX_COUNT - 1) or CH_MIN in values

    def test_button_press_toggles_and_holds(self, monkeypatch):
        buttons = {1: 0}
        joy, _ = _make(monkeypatch, _cal(), buttons=buttons)
        assert joy.get_aux_channels()[1] == CH_MIN
        buttons[1] = 1
        assert joy.get_aux_channels()[1] == CH_MAX
        # удержание не должно переключать обратно
        assert joy.get_aux_channels()[1] == CH_MAX
        buttons[1] = 0
        assert joy.get_aux_channels()[1] == CH_MAX
        buttons[1] = 1
        assert joy.get_aux_channels()[1] == CH_MIN

    def test_arm_button_does_not_leak_into_aux(self, monkeypatch):
        buttons = {0: 1}
        joy, _ = _make(monkeypatch, _cal(arm_button_index=0), buttons=buttons)
        values = joy.get_aux_channels()
        assert all(v in (CH_CENTER, CH_MIN) for v in values)

    def test_release_button_drives_channel_six(self, monkeypatch):
        buttons = {3: 0}
        joy, _ = _make(monkeypatch, _cal(release_button_index=3), buttons=buttons)
        assert joy.get_aux_channels()[0] == CH_MIN
        buttons[3] = 1
        assert joy.get_aux_channels()[0] == CH_MAX

    def test_spare_axis_is_proportional(self, monkeypatch):
        axes = {4: 1.0}
        joy, _ = _make(monkeypatch, _cal(), axes=axes, num_axes=5, num_buttons=1)
        assert joy.get_aux_channels()[1] == CH_MAX
        axes[4] = -1.0
        assert joy.get_aux_channels()[1] == CH_MIN

    def test_hat_is_reported(self, monkeypatch):
        hats = {0: (1, -1)}
        joy, _ = _make(
            monkeypatch, _cal(), hats=hats, num_hats=1, num_buttons=1, num_axes=4
        )
        values = joy.get_aux_channels()
        assert values[1] == CH_MAX
        assert values[2] == CH_MIN

    def test_read_failure_keeps_last_values(self, monkeypatch):
        buttons = {1: 0}
        joy, js = _make(monkeypatch, _cal(), buttons=buttons)
        buttons[1] = 1
        good = joy.get_aux_channels()
        assert good[1] == CH_MAX
        js.get_button.side_effect = OSError('unplugged')
        assert joy.get_aux_channels() == good

    def test_bindings_are_exposed_for_the_ui(self, monkeypatch):
        joy, _ = _make(monkeypatch, _cal(), num_buttons=3, num_axes=4)
        labels = [(b.channel, b.label) for b in joy.aux_bindings()]
        assert labels == [(7, 'Кнопка 1'), (8, 'Кнопка 2')]


class TestReleaseOnAxis:
    """Тумблеры Radiomaster приходят осями, а не кнопками — сброс должен ловиться и так."""

    def test_release_axis_drives_channel_six(self, monkeypatch):
        axes = {5: -1.0}
        joy, _ = _make(
            monkeypatch,
            _cal(release_type='axis', release_axis_index=5),
            axes=axes,
            num_axes=6,
            num_buttons=1,
        )
        assert joy.get_aux_channels()[0] == CH_MIN
        axes[5] = 1.0
        assert joy.get_aux_channels()[0] == CH_MAX
        axes[5] = -1.0
        assert joy.get_aux_channels()[0] == CH_MIN

    def test_release_axis_is_not_reused_as_spare_channel(self, monkeypatch):
        joy, _ = _make(
            monkeypatch,
            _cal(release_type='axis', release_axis_index=5),
            num_axes=6,
            num_buttons=1,
        )
        assert 5 not in [b.index for b in joy.aux_bindings() if b.kind == 'axis']

    def test_axis_release_holds_position_without_toggle(self, monkeypatch):
        """Ось — физический тумблер с фиксацией, повторные опросы не переключают."""
        axes = {5: -1.0}
        joy, _ = _make(
            monkeypatch,
            _cal(release_type='axis', release_axis_index=5),
            axes=axes,
            num_axes=6,
            num_buttons=1,
        )
        joy.get_aux_channels()  # снимаем защёлку «не сброшено»
        axes[5] = 1.0
        assert joy.get_aux_channels()[0] == CH_MAX
        assert joy.get_aux_channels()[0] == CH_MAX
        assert joy.get_aux_channels()[0] == CH_MAX


class TestReleaseLatch:
    """Как у ARM: с тумблером, забытым во включённом положении, взлетаем без сброса."""

    def test_release_stays_false_until_safe_position_seen(self, monkeypatch):
        axes = {5: 1.0}  # тумблер уже включён на момент входа в полёт
        joy, _ = _make(
            monkeypatch,
            _cal(release_type='axis', release_axis_index=5),
            axes=axes,
            num_axes=6,
            num_buttons=1,
        )
        assert joy.is_released() is False
        assert joy.get_aux_channels()[0] == CH_MIN
        axes[5] = -1.0  # вернули в исходное — защёлка снялась
        assert joy.is_released() is False
        axes[5] = 1.0
        assert joy.is_released() is True
        assert joy.get_aux_channels()[0] == CH_MAX

    def test_button_toggle_survives_the_latch(self, monkeypatch):
        buttons = {3: 0}
        joy, _ = _make(monkeypatch, _cal(release_button_index=3), buttons=buttons)
        assert joy.is_released() is False
        buttons[3] = 1
        assert joy.is_released() is True
        buttons[3] = 0
        assert joy.is_released() is True
        buttons[3] = 1
        assert joy.is_released() is False

    def test_has_release_reports_assignment(self, monkeypatch):
        none_joy, _ = _make(monkeypatch, _cal())
        assert none_joy.has_release() is False
        btn_joy, _ = _make(monkeypatch, _cal(release_button_index=3))
        assert btn_joy.has_release() is True
        axis_joy, _ = _make(
            monkeypatch, _cal(release_axis_index=5), num_axes=6, num_buttons=1
        )
        assert axis_joy.has_release() is True
