"""Tests for mapping joystick controls onto free CRSF channels."""

from __future__ import annotations

from mavixdesktop.fc.crsf import CH_CENTER, CH_MAX, CH_MIN
from mavixdesktop.joystick.channels import (
    AUX_COUNT,
    Binding,
    auto_bindings,
    aux_from_state,
)


def _cal(**extra) -> dict:
    base = {
        'axis_thr': 1,
        'axis_yaw': 0,
        'axis_pitch': 3,
        'axis_roll': 2,
        'arm_type': 'button',
        'arm_button_index': 0,
    }
    base.update(extra)
    return base


class TestAutoBindings:
    def test_buttons_start_after_release_channel(self):
        b = auto_bindings(_cal(), num_buttons=3, num_axes=4, num_hats=0)
        assert [x.channel for x in b] == [7, 8]
        assert [x.index for x in b] == [1, 2]

    def test_arm_button_is_excluded(self):
        b = auto_bindings(_cal(arm_button_index=1), 3, 4, 0)
        assert 1 not in [x.index for x in b if x.kind == 'button']

    def test_release_button_is_excluded(self):
        b = auto_bindings(_cal(release_button_index=2), 4, 4, 0)
        buttons = [x.index for x in b if x.kind == 'button']
        assert 2 not in buttons
        assert buttons == [1, 3]

    def test_free_axes_follow_buttons(self):
        b = auto_bindings(_cal(), num_buttons=1, num_axes=6, num_hats=0)
        assert [(x.kind, x.index, x.channel) for x in b] == [
            ('axis', 4, 7),
            ('axis', 5, 8),
        ]

    def test_stick_axes_are_excluded(self):
        b = auto_bindings(_cal(), num_buttons=0, num_axes=4, num_hats=0)
        assert b == []

    def test_arm_axis_is_excluded(self):
        cal = _cal(arm_type='axis', arm_axis_index=4)
        cal.pop('arm_button_index')
        b = auto_bindings(cal, num_buttons=0, num_axes=6, num_hats=0)
        assert [(x.kind, x.index) for x in b] == [('axis', 5)]

    def test_hats_come_last_and_take_two_channels(self):
        b = auto_bindings(_cal(), num_buttons=1, num_axes=4, num_hats=1)
        assert [(x.kind, x.index) for x in b] == [('hat_x', 0), ('hat_y', 0)]

    def test_never_exceeds_channel_sixteen(self):
        b = auto_bindings(_cal(), num_buttons=40, num_axes=20, num_hats=4)
        assert len(b) == AUX_COUNT - 1  # CH6 занят сбросом
        assert max(x.channel for x in b) == 16

    def test_layout_is_stable_when_release_unset(self):
        """Каналы не должны съезжать от того, назначен сброс или нет."""
        with_release = auto_bindings(_cal(release_button_index=9), 3, 4, 0)
        without = auto_bindings(_cal(), 3, 4, 0)
        assert with_release[0].channel == without[0].channel == 7


class TestAuxValues:
    def test_length_covers_ch6_to_ch16(self):
        values = aux_from_state([], release_on=False, toggles={}, axes={}, hats={})
        assert len(values) == AUX_COUNT

    def test_release_sits_on_ch6(self):
        off = aux_from_state([], release_on=False, toggles={}, axes={}, hats={})
        on = aux_from_state([], release_on=True, toggles={}, axes={}, hats={})
        assert off[0] == CH_MIN
        assert on[0] == CH_MAX

    def test_unbound_channels_stay_centered(self):
        values = aux_from_state([], release_on=False, toggles={}, axes={}, hats={})
        assert values[1:] == [CH_CENTER] * (AUX_COUNT - 1)

    def test_button_toggle_drives_its_channel(self):
        binding = Binding(channel=7, kind='button', index=2, label='Кнопка 2')
        on = aux_from_state([binding], False, {2: True}, {}, {})
        off = aux_from_state([binding], False, {2: False}, {}, {})
        assert on[1] == CH_MAX
        assert off[1] == CH_MIN

    def test_axis_is_proportional(self):
        binding = Binding(channel=7, kind='axis', index=4, label='Ось 4')
        assert aux_from_state([binding], False, {}, {4: -1.0}, {})[1] == CH_MIN
        assert aux_from_state([binding], False, {}, {4: 1.0}, {})[1] == CH_MAX
        mid = aux_from_state([binding], False, {}, {4: 0.0}, {})[1]
        assert abs(mid - CH_CENTER) <= 2

    def test_axis_out_of_range_is_clamped(self):
        binding = Binding(channel=7, kind='axis', index=4, label='Ось 4')
        assert aux_from_state([binding], False, {}, {4: -9.0}, {})[1] == CH_MIN
        assert aux_from_state([binding], False, {}, {4: 9.0}, {})[1] == CH_MAX

    def test_hat_has_three_positions(self):
        bx = Binding(channel=7, kind='hat_x', index=0, label='Крестовина 0 ←→')
        by = Binding(channel=8, kind='hat_y', index=0, label='Крестовина 0 ↑↓')
        values = aux_from_state([bx, by], False, {}, {}, {0: (-1, 1)})
        assert values[1] == CH_MIN
        assert values[2] == CH_MAX
        centered = aux_from_state([bx, by], False, {}, {}, {0: (0, 0)})
        assert centered[1] == centered[2] == CH_CENTER

    def test_missing_source_falls_back_to_center(self):
        binding = Binding(channel=9, kind='axis', index=7, label='Ось 7')
        values = aux_from_state([binding], False, {}, {}, {})
        assert values[3] == CH_CENTER
