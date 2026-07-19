"""Tests for joystick -> CRSF frame conversion."""
from mavixdesktop.fc.crsf import CH_CENTER, CH_MAX, CH_MIN, CRSF
from mavixdesktop.fc.encoder import build_rc_frame


def _decode_channels(frame: bytes) -> list[int]:
    payload = frame[3:3 + 22]
    bits = int.from_bytes(payload, 'little')
    return [(bits >> (i * 11)) & 0x7FF for i in range(16)]


def test_frame_type_is_rc_channels():
    frame = build_rc_frame(0, 0, 0, 0, armed=False)
    assert frame[2] == 0x16


def test_frame_has_valid_crc():
    frame = build_rc_frame(0.5, -0.3, 0.2, -0.5, armed=True)
    body = frame[2:-1]
    assert frame[-1] == CRSF.crc8(body)


def test_throttle_min_when_minus_one():
    frame = build_rc_frame(-1.0, 0, 0, 0, armed=False)
    channels = _decode_channels(frame)
    assert channels[0] == CH_MIN


def test_throttle_max_when_plus_one():
    frame = build_rc_frame(1.0, 0, 0, 0, armed=False)
    channels = _decode_channels(frame)
    assert channels[0] == CH_MAX


def test_centered_inputs_produce_center():
    frame = build_rc_frame(0.0, 0.0, 0.0, 0.0, armed=False)
    channels = _decode_channels(frame)
    assert abs(channels[0] - (CH_MIN + CH_MAX) // 2) <= 2
    assert channels[1] == CH_CENTER
    assert channels[2] == CH_CENTER
    assert channels[3] == CH_CENTER


def test_arm_channel_high_when_armed():
    frame = build_rc_frame(0, 0, 0, 0, armed=True)
    channels = _decode_channels(frame)
    assert channels[4] == CH_MAX


def test_arm_channel_low_when_disarmed():
    frame = build_rc_frame(0, 0, 0, 0, armed=False)
    channels = _decode_channels(frame)
    assert channels[4] == CH_MIN


def test_unused_channels_centered():
    frame = build_rc_frame(0.7, -0.2, 0.4, 0.0, armed=True)
    channels = _decode_channels(frame)
    for ch in channels[5:]:
        assert ch == CH_CENTER


def test_taer_order_roll_is_channel_2():
    frame = build_rc_frame(0, roll=1.0, pitch=0, yaw=0, armed=False)
    channels = _decode_channels(frame)
    assert CH_MAX - 1 <= channels[1] <= CH_MAX
    assert channels[2] == CH_CENTER
    assert channels[3] == CH_CENTER


def test_taer_order_pitch_is_channel_3():
    frame = build_rc_frame(0, roll=0, pitch=1.0, yaw=0, armed=False)
    channels = _decode_channels(frame)
    assert CH_MAX - 1 <= channels[2] <= CH_MAX
    assert channels[1] == CH_CENTER
    assert channels[3] == CH_CENTER


def test_taer_order_yaw_is_channel_4():
    frame = build_rc_frame(0, roll=0, pitch=0, yaw=1.0, armed=False)
    channels = _decode_channels(frame)
    assert CH_MAX - 1 <= channels[3] <= CH_MAX
    assert channels[1] == CH_CENTER
    assert channels[2] == CH_CENTER


def test_clamps_out_of_range_inputs():
    frame = build_rc_frame(5.0, 5.0, -5.0, 5.0, armed=False)
    channels = _decode_channels(frame)
    assert channels[0] == CH_MAX
    assert CH_MAX - 1 <= channels[1] <= CH_MAX
    assert channels[2] == CH_MIN or channels[2] == CH_MIN + 1
