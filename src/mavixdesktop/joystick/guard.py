"""Watch a JoystickInput for disconnect mid-flight and send one disarm
frame to the drone if it goes away.

The guard is fc-aware: in CRSF mode it produces a zero-stick RC frame
with the ARM channel pulled low; in MAVLink mode it produces a
COMMAND_LONG / MAV_CMD_COMPONENT_ARM_DISARM packet. Both flow through
the same packet data-channel that already carries joystick traffic to
the drone, so no extra plumbing is required.
"""
from __future__ import annotations

from collections.abc import Callable

from mavixdesktop.core.logger import logger
from mavixdesktop.joystick.input import JoystickInput


def _build_mavlink_disarm() -> bytes | None:
    try:
        from pymavlink.dialects.v20 import common as mavlink
    except ImportError:
        logger.warning('[joystick-guard] pymavlink not installed; mavlink disarm skipped')
        return None
    mav = mavlink.MAVLink(file=None, srcSystem=255, srcComponent=190)
    msg = mavlink.MAVLink_command_long_message(
        target_system=1,
        target_component=1,
        command=mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        confirmation=0,
        param1=0.0,  # 0 = disarm
        param2=21196.0,  # force-disarm magic (PX4/ArduPilot)
        param3=0.0, param4=0.0, param5=0.0, param6=0.0, param7=0.0,
    )
    return msg.pack(mav)


def _build_crsf_disarm() -> bytes:
    from mavixdesktop.fc.encoder import build_rc_frame
    return build_rc_frame(throttle=-1.0, roll=0.0, pitch=0.0, yaw=0.0, armed=False)


class JoystickGuard:
    """Poll a JoystickInput; on a connected→disconnected transition fire
    exactly one disarm frame via `send_frame`. After firing the guard
    latches and won't repeat until reset()."""

    def __init__(
        self,
        js: JoystickInput,
        fc_type: str,
        send_frame: Callable[[bytes], None],
        on_disarm: Callable[[], None] | None = None,
    ) -> None:
        self._js = js
        self._fc_type = fc_type
        self._send = send_frame
        self._on_disarm = on_disarm
        self._was_connected = True
        self._fired = False

    @property
    def fired(self) -> bool:
        return self._fired

    def reset(self) -> None:
        self._fired = False
        self._was_connected = True

    def tick(self) -> bool:
        if self._js.is_connected():
            self._was_connected = True
            return False
        if self._fired or not self._was_connected:
            return False
        self._fire_disarm()
        self._fired = True
        return True

    def _fire_disarm(self) -> None:
        try:
            frame = self._build_frame()
        except Exception as exc:
            logger.error('[joystick-guard] failed to build disarm frame: %s', exc)
            return
        if frame:
            try:
                self._send(frame)
                logger.warning(
                    '[joystick-guard] joystick lost, sent %s disarm (%d bytes)',
                    self._fc_type, len(frame),
                )
            except Exception as exc:
                logger.error('[joystick-guard] send failed: %s', exc)
        if self._on_disarm is not None:
            try:
                self._on_disarm()
            except Exception as exc:
                logger.debug('[joystick-guard] on_disarm callback error: %s', exc)

    def _build_frame(self) -> bytes | None:
        if self._fc_type == 'crsf':
            return _build_crsf_disarm()
        if self._fc_type == 'mavlink':
            return _build_mavlink_disarm()
        return None
