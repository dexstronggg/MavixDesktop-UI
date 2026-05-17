"""Joystick stick positions → CRSF RC frame."""
from __future__ import annotations

from mavixdesktop.fc.crsf import CH_CENTER, CH_MAX, CH_MIN, CRSF


def build_rc_frame(
    throttle: float,
    roll: float,
    pitch: float,
    yaw: float,
    armed: bool,
) -> bytes:
    """Build a CRSF RC channels frame (type 0x16) from normalised stick values.

    All stick inputs are expected in [-1.0, 1.0]; clamping/dead-zone is
    delegated to CRSF.axis_to_crsf / CRSF.throttle_to_crsf. The mapping
    follows the standard TAER channel order:

      CH1 Throttle  (T)
      CH2 Aileron   (A) — roll
      CH3 Elevator  (E) — pitch
      CH4 Rudder    (R) — yaw
      CH5 ARM       — CH_MAX when armed, CH_MIN otherwise
      CH6..CH16     — centered (CH_CENTER)
    """
    channels = [
        CRSF.throttle_to_crsf(throttle),
        CRSF.axis_to_crsf(roll),
        CRSF.axis_to_crsf(pitch),
        CRSF.axis_to_crsf(yaw),
        CH_MAX if armed else CH_MIN,
    ]
    return CRSF.rc_frame(channels)
