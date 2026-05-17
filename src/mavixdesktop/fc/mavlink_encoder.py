"""MAVLink v2 packet builders for the Mavix → PX4 joystick path.

Mavix replaces QGroundControl as the manual-control GCS: stick positions
from the gamepad get encoded as `MANUAL_CONTROL` and shipped to the FC at
~50 Hz via the WebRTC packet data-channel. Board-side `MavlinkController`
forwards raw bytes to the FC's UART without inspecting them.

For PX4 to accept these:
  * `COM_RC_IN_MODE=1` (joystick only) — already in the operator's setup
    notes (настройка_px4.md).
  * A heartbeat from this GCS (sysid=255, compid=190) at ≥1 Hz, otherwise
    PX4 triggers RC-loss failsafe.
  * The flight mode must be set explicitly: PX4 has no «default mode at
    boot» param, so without an explicit `SET_MODE` it stays in Hold.

This module is stateful only as far as MAVLink2 sequence numbers go —
pymavlink's `MAVLink` instance increments them on `pack()`. One instance
per peer (target FC) is fine; we reuse it for every packet of this run.
"""
from __future__ import annotations

from pymavlink.dialects.v20 import common as mavlink


# Source identity of this GCS. 255/190 is the convention QGC also uses.
SRC_SYSTEM = 255
SRC_COMPONENT = 190

# Default FC peer. PX4 starts at sysid=1, compid=1 (autopilot).
TARGET_SYSTEM_DEFAULT = 1
TARGET_COMPONENT_DEFAULT = 1

# PX4 custom_mode layout: byte2=main_mode, byte3=sub_mode (little-endian
# uint32). UI отдаёт numeric main_mode прямо в set_mode().
PX4_MAIN_MODES = {
    'STABILIZED': 7,
    'ACRO': 5,
}

# AUTO имеет несколько sub-mode'ов; нам нужен RTL для failsafe-сценария.
PX4_MAIN_MODE_AUTO = 4
PX4_AUTO_SUB_RTL = 5

ARM_FORCE_MAGIC = 21196  # MAV_CMD_COMPONENT_ARM_DISARM param2 for force-arm


class MavlinkEncoder:
    """Builds raw MAVLink2 byte frames for outbound packets."""

    def __init__(
        self,
        target_system: int = TARGET_SYSTEM_DEFAULT,
        target_component: int = TARGET_COMPONENT_DEFAULT,
    ) -> None:
        # pymavlink wants a file argument; we never call send() so it can
        # be a stub. msg.pack(mav) returns the wire bytes directly.
        self._mav = mavlink.MAVLink(
            file=None, srcSystem=SRC_SYSTEM, srcComponent=SRC_COMPONENT,
        )
        self.target_system = target_system
        self.target_component = target_component

    def heartbeat(self) -> bytes:
        """GCS heartbeat — PX4 uses this to detect that the operator is
        still alive. Required at ≥1 Hz."""
        msg = self._mav.heartbeat_encode(
            mavlink.MAV_TYPE_GCS,
            mavlink.MAV_AUTOPILOT_INVALID,
            base_mode=0,
            custom_mode=0,
            system_status=mavlink.MAV_STATE_ACTIVE,
        )
        return self._pack(msg)

    def manual_control(
        self,
        throttle: float,
        yaw: float,
        pitch: float,
        roll: float,
        buttons: int = 0,
    ) -> bytes:
        """All sticks in -1.0 … 1.0 (throttle: -1=down, +1=up).

        MANUAL_CONTROL semantics for PX4:
          x = pitch  (-1000…1000, +1000 nose-up)
          y = roll   (-1000…1000, +1000 right roll)
          z = throttle (in PX4 manual mode: 0…1000, where 0 = idle/no thrust,
                        1000 = full thrust; we map -1..1 → 0..1000)
          r = yaw    (-1000…1000, +1000 yaw right)
        """
        msg = self._mav.manual_control_encode(
            target=self.target_system,
            x=_to_axis(pitch),
            y=_to_axis(roll),
            z=_to_throttle(throttle),
            r=_to_axis(yaw),
            buttons=buttons,
        )
        return self._pack(msg)

    def set_mode(self, main_mode: int, sub_mode: int = 0) -> bytes:
        """Tell PX4 to switch to the given main flight mode (см.
        PX4_MAIN_MODES). Sent как MAV_CMD_DO_SET_MODE в COMMAND_LONG —
        param1=MAV_MODE_FLAG_CUSTOM_MODE_ENABLED → PX4 читает main из
        param2 и sub из param3 (нужен для AUTO_*, иначе 0)."""
        msg = self._mav.command_long_encode(
            target_system=self.target_system,
            target_component=self.target_component,
            command=mavlink.MAV_CMD_DO_SET_MODE,
            confirmation=0,
            param1=mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            param2=float(main_mode),
            param3=float(sub_mode),
            param4=0.0,
            param5=0.0,
            param6=0.0,
            param7=0.0,
        )
        return self._pack(msg)

    def failsafe_rtl(self) -> bytes:
        """PX4 AUTO_RTL — дрон автономно возвращается на точку взлёта
        и садится. Используется как failsafe при потере джойстика
        (NAV_RCL_ACT=0 у нас отключает встроенный PX4 RC-loss, так что
        переключение режима делаем сами явно)."""
        return self.set_mode(PX4_MAIN_MODE_AUTO, PX4_AUTO_SUB_RTL)

    def reboot_autopilot(self) -> bytes:
        """`MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN` (cmd 246) с param1=1 — мгновенный
        перезапуск автопилота. PX4 принимает в любом disarmed-состоянии;
        в air команду проигнорирует (защита)."""
        msg = self._mav.command_long_encode(
            target_system=self.target_system,
            target_component=self.target_component,
            command=mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,
            confirmation=0,
            param1=1.0,  # autopilot reboot
            param2=0.0,
            param3=0.0,
            param4=0.0,
            param5=0.0,
            param6=0.0,
            param7=0.0,
        )
        return self._pack(msg)

    def arm_disarm(self, arm: bool, force: bool = False) -> bytes:
        """COMMAND_LONG MAV_CMD_COMPONENT_ARM_DISARM. `force=True` sets
        the 21196 magic in param2 which bypasses the commander's remaining
        pre-arm checks — useful for bench tests but unsafe in flight."""
        msg = self._mav.command_long_encode(
            target_system=self.target_system,
            target_component=self.target_component,
            command=mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
            confirmation=0,
            param1=1.0 if arm else 0.0,
            param2=float(ARM_FORCE_MAGIC) if force else 0.0,
            param3=0.0,
            param4=0.0,
            param5=0.0,
            param6=0.0,
            param7=0.0,
        )
        return self._pack(msg)

    def _pack(self, msg) -> bytes:
        return msg.pack(self._mav)


def _to_axis(value: float) -> int:
    """Clamp and scale a -1..1 stick value to MAVLink's -1000..1000."""
    if value < -1.0:
        value = -1.0
    elif value > 1.0:
        value = 1.0
    return int(value * 1000.0)


def _to_throttle(value: float) -> int:
    """Map a -1..1 throttle stick to PX4's 0..1000 thrust range.

    -1 (stick fully down) → 0 (no thrust), +1 (fully up) → 1000.
    """
    if value < -1.0:
        value = -1.0
    elif value > 1.0:
        value = 1.0
    return int((value + 1.0) * 500.0)
