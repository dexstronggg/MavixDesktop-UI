"""Read calibrated stick positions and ARM state from pygame Joystick."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from mavixdesktop.joystick.channels import (
    AUX_COUNT,
    Binding,
    auto_bindings,
    aux_from_state,
)


class JoystickInput:
    AXES: Iterable[str] = ('thr', 'yaw', 'pitch', 'roll')

    def __init__(
        self, joystick_index: int, calibration: dict[str, Any], pump_events: bool = True
    ) -> None:
        import pygame

        pygame.joystick.init()
        self._joystick_index = joystick_index
        self._js = pygame.joystick.Joystick(joystick_index)
        self._js.init()
        self._cal = calibration
        self._pump_events = pump_events
        self._arm = False
        self._arm_btn_prev = 0
        self._disarm_seen = False
        try:
            self._instance_id: int | None = self._js.get_instance_id()
        except Exception:
            self._instance_id = None
        self._connected = True
        self._bindings: list[Binding] | None = None
        self._toggles: dict[int, bool] = {}
        self._btn_prev: dict[int, int] = {}
        self._release = False
        self._release_prev = 0
        self._release_safe_seen = False
        self._aux_last: list[int] | None = None

    @property
    def name(self) -> str:
        return self._js.get_name()

    def is_connected(self) -> bool:
        import pygame

        if self._pump_events:
            pygame.event.pump()
        try:
            if pygame.joystick.get_count() <= self._joystick_index:
                return False
            if not self._js.get_init():
                return False
            self._js.get_axis(0)
            return True
        except Exception:
            return False

    def get_stick_positions(self) -> tuple[float, float, float, float]:
        if self._pump_events:
            import pygame

            pygame.event.pump()
        return (
            self._read_axis('thr'),
            self._read_axis('yaw'),
            self._read_axis('pitch'),
            self._read_axis('roll'),
        )

    def is_armed(self) -> bool:
        raw = self._read_arm_raw()
        if not self._disarm_seen:
            if not raw:
                self._disarm_seen = True
            return False
        return raw

    def _read_arm_raw(self) -> bool:
        arm_type = self._cal.get('arm_type', 'button')
        if arm_type == 'axis':
            idx = self._cal.get('arm_axis_index', 0)
            try:
                return self._js.get_axis(idx) > 0.5
            except Exception:
                return False
        return self._poll_arm_button()

    def _read_axis(self, name: str) -> float:
        idx = self._cal.get(f'axis_{name}', 0)
        try:
            raw = self._js.get_axis(idx)
        except Exception:
            return 0.0
        mn = self._cal.get(f'{name}_min', -1.0)
        mx = self._cal.get(f'{name}_max', 1.0)
        center = self._cal.get(f'{name}_center', 0.0)
        if raw >= center:
            span = mx - center
            return (raw - center) / span if span > 0 else 0.0
        span = center - mn
        return -(center - raw) / span if span > 0 else 0.0

    def aux_bindings(self) -> list[Binding]:
        """Раскладка свободных органов управления по каналам — её же видит UI."""
        if self._bindings is None:
            try:
                counts = (
                    self._js.get_numbuttons(),
                    self._js.get_numaxes(),
                    self._js.get_numhats(),
                )
            except Exception:
                counts = (0, 0, 0)
            self._bindings = auto_bindings(self._cal, *counts)
        return self._bindings

    def get_aux_channels(self) -> list[int]:
        """CH6..CH16. При сбое чтения отдаём прошлые значения, а не центр:
        обнуление дёрнуло бы сброс груза в момент потери джойстика."""
        try:
            bindings = self.aux_bindings()
            released = self.is_released()
            for binding in bindings:
                if binding.kind != 'button':
                    continue
                self._toggles[binding.index] = self._toggle_button(binding.index)
            axes = {
                b.index: float(self._js.get_axis(b.index))
                for b in bindings
                if b.kind == 'axis'
            }
            hats: dict[int, tuple[int, int]] = {}
            for b in bindings:
                if b.kind in ('hat_x', 'hat_y') and b.index not in hats:
                    raw = self._js.get_hat(b.index)
                    hats[b.index] = (int(raw[0]), int(raw[1]))
            values = aux_from_state(bindings, released, self._toggles, axes, hats)
        except Exception:
            return list(self._aux_last) if self._aux_last else [992] * AUX_COUNT
        self._aux_last = values
        return values

    def has_release(self) -> bool:
        """Назначен ли орган управления под сброс груза."""
        for key in ('release_axis_index', 'release_button_index'):
            value = self._cal.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                return True
        return False

    def is_released(self) -> bool:
        """Защёлка как у `is_armed()`: пока не зафиксировано положение «не
        сброшено», отдаём False. Иначе вход в полёт с тумблером, забытым во
        включённом положении, сразу дёрнул бы замок."""
        raw = self._read_release()
        if not self._release_safe_seen:
            if not raw:
                self._release_safe_seen = True
            return False
        return raw

    def _read_release(self) -> bool:
        """Сброс — как ARM: тумблер приходит осью, кнопка кнопкой.

        Ось читаем напрямую (это физический тумблер с фиксацией), кнопку —
        фиксатором по фронту нажатия. Состояние фиксатора живёт в
        `self._release` и защёлкой из `is_released()` не затирается.
        """
        axis = self._cal.get('release_axis_index')
        if isinstance(axis, int) and not isinstance(axis, bool):
            return bool(self._js.get_axis(axis) > 0.5)
        self._release = self._toggle(
            self._cal.get('release_button_index'), self._release, '_release_prev'
        )
        return self._release

    def _toggle_button(self, index: int) -> bool:
        cur = int(self._js.get_button(index))
        prev = self._btn_prev.get(index, 0)
        self._btn_prev[index] = cur
        state = self._toggles.get(index, False)
        return not state if (cur != prev and cur == 1) else state

    def _toggle(self, index: Any, state: bool, prev_attr: str) -> bool:
        if isinstance(index, bool) or not isinstance(index, int):
            return state
        cur = int(self._js.get_button(index))
        prev = getattr(self, prev_attr)
        setattr(self, prev_attr, cur)
        return not state if (cur != prev and cur == 1) else state

    def _poll_arm_button(self) -> bool:
        idx = self._cal.get('arm_button_index', 0)
        try:
            cur = self._js.get_button(idx)
        except Exception:
            return self._arm
        if cur != self._arm_btn_prev:
            self._arm_btn_prev = cur
            if cur == 1:
                self._arm = not self._arm
        return self._arm
