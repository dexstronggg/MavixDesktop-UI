"""MAVLink v2 packet builders for Mavix joystick -> PX4 path."""
from __future__ import annotations

from pymavlink.dialects.v20 import common as mavlink

SRC_SYSTEM = 255
SRC_COMPONENT = 190

TARGET_SYSTEM_DEFAULT = 1
TARGET_COMPONENT_DEFAULT = 1

PX4_MAIN_MODES = {
    'STABILIZED': 7,
    'ACRO': 5,
}

PX4_MAIN_MODE_AUTO = 4
PX4_AUTO_SUB_RTL = 5

ARM_FORCE_MAGIC = 21196


class MavlinkEncoder:
    def __init__(
        self,
        target_system: int = TARGET_SYSTEM_DEFAULT,
        target_component: int = TARGET_COMPONENT_DEFAULT,
    ) -> None:
        self._mav = mavlink.MAVLink(
            file=None, srcSystem=SRC_SYSTEM, srcComponent=SRC_COMPONENT,
        )
        self.target_system = target_system
        self.target_component = target_component

    def heartbeat(self) -> bytes:
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
        return self.set_mode(PX4_MAIN_MODE_AUTO, PX4_AUTO_SUB_RTL)

    def reboot_autopilot(self) -> bytes:
        msg = self._mav.command_long_encode(
            target_system=self.target_system,
            target_component=self.target_component,
            command=mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,
            confirmation=0,
            param1=1.0,
            param2=0.0,
            param3=0.0,
            param4=0.0,
            param5=0.0,
            param6=0.0,
            param7=0.0,
        )
        return self._pack(msg)

    def arm_disarm(self, arm: bool, force: bool = False) -> bytes:
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

    def _pack(self, msg: object) -> bytes:
        return msg.pack(self._mav)


def _to_axis(value: float) -> int:
    if value < -1.0:
        value = -1.0
    elif value > 1.0:
        value = 1.0
    return int(value * 1000.0)


def _to_throttle(value: float) -> int:
    if value < -1.0:
        value = -1.0
    elif value > 1.0:
        value = 1.0
    return int((value + 1.0) * 500.0)
