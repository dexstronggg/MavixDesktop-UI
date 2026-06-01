import pytest

from mavixdesktop.fc.crsf import CH_CENTER, CH_MAX, CH_MIN, CRSF

#### crc8 ##############################################################################

def test_crc8_empty():
    assert CRSF.crc8(b'') == 0


def test_crc8_known_vector():
    # CRC8/DVB-S2 (polynomial 0xD5, init 0x00)
    assert CRSF.crc8(b'\x00') == 0
    assert CRSF.crc8(b'\x01') == 0xD5


def test_crc8_consistency_for_same_input():
    assert CRSF.crc8(b'foo') == CRSF.crc8(b'foo')


#### frame builder #####################################################################

def test_frame_structure_starts_with_addr_and_length():
    payload = b'\x01\x02\x03'
    frame = CRSF._frame(0x14, payload, addr=0xC8)
    assert frame[0] == 0xC8
    # length byte = len(ftype + payload + crc) = 1 + 3 + 1 = 5
    assert frame[1] == 5
    assert frame[2] == 0x14
    assert frame[3:6] == payload


def test_frame_includes_valid_crc():
    payload = b'\xAA\xBB'
    frame = CRSF._frame(0x16, payload)
    body = frame[2:-1]
    assert frame[-1] == CRSF.crc8(body)


#### rc_frame ##########################################################################

def test_rc_frame_has_22_byte_payload_plus_header_and_crc():
    frame = CRSF.rc_frame([CH_CENTER] * 16)
    # addr + len + ftype + 22 channel bytes + crc = 26
    assert len(frame) == 26
    assert frame[2] == 0x16


def test_rc_frame_pads_short_channel_lists():
    frame = CRSF.rc_frame([CH_MAX])
    assert frame[2] == 0x16
    # First 11 bits should be CH_MAX, the rest CH_CENTER
    bits = int.from_bytes(frame[3:25], 'little')
    assert (bits & 0x7FF) == CH_MAX
    assert ((bits >> 11) & 0x7FF) == CH_CENTER


def test_rc_frame_clamps_out_of_range():
    frame = CRSF.rc_frame([99999, -1])
    bits = int.from_bytes(frame[3:25], 'little')
    assert (bits & 0x7FF) == 0x7FF
    assert ((bits >> 11) & 0x7FF) == 0


#### axis/throttle helpers #############################################################

def test_axis_to_crsf_deadzone_returns_center():
    assert CRSF.axis_to_crsf(0.0) == CH_CENTER
    assert CRSF.axis_to_crsf(0.04) == CH_CENTER
    assert CRSF.axis_to_crsf(-0.04) == CH_CENTER


def test_axis_to_crsf_full_positive():
    # Boundary: floating math may give CH_MAX-1, accept off-by-one
    assert CH_MAX - 1 <= CRSF.axis_to_crsf(1.0) <= CH_MAX


def test_axis_to_crsf_full_negative():
    # Boundary: floating math + int() may give CH_MIN+1, accept off-by-one
    assert CH_MIN <= CRSF.axis_to_crsf(-1.0) <= CH_MIN + 1


def test_axis_to_crsf_clamps_oob():
    assert CRSF.axis_to_crsf(5.0) == CH_MAX
    assert CRSF.axis_to_crsf(-5.0) == CH_MIN


def test_throttle_to_crsf_at_zero_is_midpoint():
    val = CRSF.throttle_to_crsf(0.0)
    assert val == pytest.approx((CH_MIN + CH_MAX) // 2, abs=2)


def test_throttle_to_crsf_min_max():
    assert CRSF.throttle_to_crsf(-1.0) == CH_MIN
    assert CRSF.throttle_to_crsf(1.0) == CH_MAX
