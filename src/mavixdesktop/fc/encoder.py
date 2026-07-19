"""Joystick stick positions -> CRSF RC frame."""
from __future__ import annotations

from mavixdesktop.fc.crsf import CH_MAX, CH_MIN, CRSF


def build_rc_frame(
    throttle: float,
    roll: float,
    pitch: float,
    yaw: float,
    armed: bool,
) -> bytes:
    channels = [
        CRSF.throttle_to_crsf(throttle),
        CRSF.axis_to_crsf(roll),
        CRSF.axis_to_crsf(pitch),
        CRSF.axis_to_crsf(yaw),
        CH_MAX if armed else CH_MIN,
    ]
    return CRSF.rc_frame(channels)
