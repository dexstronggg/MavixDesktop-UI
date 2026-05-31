"""Позиции стиков joystick → RC-кадр CRSF."""
from __future__ import annotations

from mavixdesktop.fc.crsf import CH_MAX, CH_MIN, CRSF


def build_rc_frame(
    throttle: float,
    roll: float,
    pitch: float,
    yaw: float,
    armed: bool,
) -> bytes:
    """Собирает CRSF RC channels frame (тип 0x16) из нормированных значений стиков.

    Все входы стиков ожидаются в [-1.0, 1.0]; clamping/dead-zone делегированы
    CRSF.axis_to_crsf / CRSF.throttle_to_crsf. Маппинг следует стандартному
    порядку каналов TAER:

      CH1 Throttle  (T)
      CH2 Aileron   (A) — roll
      CH3 Elevator  (E) — pitch
      CH4 Rudder    (R) — yaw
      CH5 ARM       — CH_MAX когда armed, иначе CH_MIN
      CH6..CH16     — центрированы (CH_CENTER)
    """
    channels = [
        CRSF.throttle_to_crsf(throttle),
        CRSF.axis_to_crsf(roll),
        CRSF.axis_to_crsf(pitch),
        CRSF.axis_to_crsf(yaw),
        CH_MAX if armed else CH_MIN,
    ]
    return CRSF.rc_frame(channels)
