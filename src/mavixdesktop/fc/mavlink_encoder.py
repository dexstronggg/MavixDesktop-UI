"""Построители MAVLink v2 пакетов для пути joystick Mavix → PX4.

Mavix заменяет QGroundControl в роли GCS ручного управления: позиции стиков
с геймпада кодируются как `MANUAL_CONTROL` и отправляются на FC с частотой
~50 Hz по WebRTC packet data-channel. На стороне платы `MavlinkController`
пересылает сырые байты в UART FC, не разбирая их.

Чтобы PX4 их принимал:
  * `COM_RC_IN_MODE=1` (только joystick) — уже в заметках по настройке
    оператора (настройка_px4.md).
  * Heartbeat от этого GCS (sysid=255, compid=190) с частотой ≥1 Hz, иначе
    PX4 срабатывает RC-loss failsafe.
  * Режим полёта надо задавать явно: у PX4 нет параметра «режим по
    умолчанию при загрузке», поэтому без явного `SET_MODE` он остаётся в Hold.

Модуль хранит состояние только в части sequence-номеров MAVLink2 — экземпляр
`MAVLink` из pymavlink инкрементирует их на `pack()`. Один экземпляр на пир
(целевой FC) — нормально; переиспользуем его для каждого пакета этого запуска.
"""
from __future__ import annotations

from pymavlink.dialects.v20 import common as mavlink

# Идентичность источника этого GCS. 255/190 — конвенция, которую использует и QGC.
SRC_SYSTEM = 255
SRC_COMPONENT = 190

# FC-пир по умолчанию. PX4 стартует с sysid=1, compid=1 (autopilot).
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

ARM_FORCE_MAGIC = 21196  # MAV_CMD_COMPONENT_ARM_DISARM param2 для force-arm


class MavlinkEncoder:
    """Строит сырые MAVLink2 байтовые кадры для исходящих пакетов."""

    def __init__(
        self,
        target_system: int = TARGET_SYSTEM_DEFAULT,
        target_component: int = TARGET_COMPONENT_DEFAULT,
    ) -> None:
        # pymavlink требует аргумент file; мы никогда не вызываем send(),
        # поэтому он может быть заглушкой. msg.pack(mav) сразу возвращает
        # байты для провода.
        self._mav = mavlink.MAVLink(
            file=None, srcSystem=SRC_SYSTEM, srcComponent=SRC_COMPONENT,
        )
        self.target_system = target_system
        self.target_component = target_component

    def heartbeat(self) -> bytes:
        """Heartbeat GCS — PX4 по нему понимает, что оператор ещё жив.
        Требуется с частотой ≥1 Hz."""
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
        """Все стики в -1.0 … 1.0 (throttle: -1=вниз, +1=вверх).

        Семантика MANUAL_CONTROL для PX4:
          x = pitch  (-1000…1000, +1000 нос вверх)
          y = roll   (-1000…1000, +1000 крен вправо)
          z = throttle (в manual-режиме PX4: 0…1000, где 0 = idle/нет тяги,
                        1000 = полная тяга; мы маппим -1..1 → 0..1000)
          r = yaw    (-1000…1000, +1000 рыскание вправо)
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
        """COMMAND_LONG MAV_CMD_COMPONENT_ARM_DISARM. `force=True` ставит
        magic 21196 в param2, что обходит оставшиеся pre-arm проверки
        commander'а — удобно для стендовых тестов, но небезопасно в полёте."""
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
    """Зажимает и масштабирует значение стика -1..1 в MAVLink-диапазон -1000..1000."""
    if value < -1.0:
        value = -1.0
    elif value > 1.0:
        value = 1.0
    return int(value * 1000.0)


def _to_throttle(value: float) -> int:
    """Маппит throttle-стик -1..1 в PX4-диапазон тяги 0..1000.

    -1 (стик в самый низ) → 0 (нет тяги), +1 (в самый верх) → 1000.
    """
    if value < -1.0:
        value = -1.0
    elif value > 1.0:
        value = 1.0
    return int((value + 1.0) * 500.0)
