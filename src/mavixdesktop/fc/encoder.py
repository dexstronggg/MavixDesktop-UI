"""Joystick stick positions -> CRSF RC frame."""

from __future__ import annotations

from mavixdesktop.fc.crsf import CH_MAX, CH_MIN, CRSF


def build_rc_frame(
    throttle: float,
    roll: float,
    pitch: float,
    yaw: float,
    armed: bool,
    aux: list[int] | None = None,
) -> bytes:
    """CH1-4 — стики, CH5 — ARM, CH6 и дальше — тумблеры и кнопки.

    `aux` короче остатка кадра дополняется центром в `CRSF.rc_frame`,
    длиннее — обрезается там же, так что кадр всегда 16-канальный.
    """
    channels = [
        CRSF.throttle_to_crsf(throttle),
        CRSF.axis_to_crsf(roll),
        CRSF.axis_to_crsf(pitch),
        CRSF.axis_to_crsf(yaw),
        CH_MAX if armed else CH_MIN,
    ]
    if aux:
        channels.extend(aux)
    return CRSF.rc_frame(channels)
