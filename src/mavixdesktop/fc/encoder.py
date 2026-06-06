"""Позиции стиков joystick → RC-кадр CRSF."""
from __future__ import annotations

from mavixdesktop.fc.crsf import CH_CENTER, CH_MAX, CH_MIN, CRSF

# Канал сброса груза (CH8): оператор жмёт кнопку — канал уходит в CH_MAX, и
# полётник по нему дёргает серво/gripper. Физический сброс кодируется здесь
# (на стороне оператора) и форвардится board'ом в FC как обычный RC —
# отдельного протокола на борту не нужно.
DROP_CHANNEL = 8  # 1-based


def build_rc_frame(
    throttle: float,
    roll: float,
    pitch: float,
    yaw: float,
    armed: bool,
    drop: bool = False,
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
      CH6, CH7      — центрированы (CH_CENTER)
      CH8 DROP      — CH_MAX при сбросе груза, иначе CH_MIN
      CH9..CH16     — центрированы (CH_CENTER)
    """
    channels = [
        CRSF.throttle_to_crsf(throttle),
        CRSF.axis_to_crsf(roll),
        CRSF.axis_to_crsf(pitch),
        CRSF.axis_to_crsf(yaw),
        CH_MAX if armed else CH_MIN,
        CH_CENTER,
        CH_CENTER,
        CH_MAX if drop else CH_MIN,
    ]
    return CRSF.rc_frame(channels)
