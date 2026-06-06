"""Tests for joystick → CRSF frame conversion."""
from mavixdesktop.fc.crsf import CH_CENTER, CH_MAX, CH_MIN, CRSF
from mavixdesktop.fc.encoder import build_rc_frame


def _decode_channels(frame: bytes) -> list[int]:
    """Reverse rc_frame.bits.to_bytes(22, 'little') to inspect each 11-bit channel."""
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
    # Throttle is at midpoint (zero input mapped to half), others at center
    assert abs(channels[0] - (CH_MIN + CH_MAX) // 2) <= 2
    assert channels[1] == CH_CENTER  # roll
    assert channels[2] == CH_CENTER  # pitch
    assert channels[3] == CH_CENTER  # yaw


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
    # CH6, CH7 (индексы 5,6) и CH9..CH16 (индексы 8..) центрированы;
    # CH8 (индекс 7) — канал сброса груза, по умолчанию CH_MIN.
    for ch in channels[5:7] + channels[8:]:
        assert ch == CH_CENTER
    assert channels[7] == CH_MIN


def test_taer_order_roll_is_channel_2():
    """Stick fully right should bump CH2 (aileron) high."""
    frame = build_rc_frame(0, roll=1.0, pitch=0, yaw=0, armed=False)
    channels = _decode_channels(frame)
    # CH_MAX up to off-by-one due to int() in axis_to_crsf
    assert CH_MAX - 1 <= channels[1] <= CH_MAX
    assert channels[2] == CH_CENTER  # pitch unchanged
    assert channels[3] == CH_CENTER  # yaw unchanged


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
    assert channels[0] == CH_MAX  # throttle
    assert CH_MAX - 1 <= channels[1] <= CH_MAX
    assert channels[2] == CH_MIN or channels[2] == CH_MIN + 1


def test_drop_channel_high_when_drop_true():
    frame = build_rc_frame(0, 0, 0, 0, armed=True, drop=True)
    channels = _decode_channels(frame)
    assert channels[7] == CH_MAX  # CH8 = drop


def test_drop_channel_low_when_drop_false():
    frame = build_rc_frame(0, 0, 0, 0, armed=True, drop=False)
    channels = _decode_channels(frame)
    assert channels[7] == CH_MIN


def test_drop_defaults_to_false():
    frame = build_rc_frame(0, 0, 0, 0, armed=False)
    channels = _decode_channels(frame)
    assert channels[7] == CH_MIN
