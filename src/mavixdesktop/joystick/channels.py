"""Map joystick controls onto the CRSF channels the sticks do not use."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mavixdesktop.fc.crsf import CH_CENTER, CH_MAX, CH_MIN

CH_ARM = 5
CH_RELEASE = 6
CH_AUTO_FIRST = 7
CH_LAST = 16

#: Каналы CH6..CH16 — всё, что не занято стиками.
AUX_COUNT = CH_LAST - CH_ARM

_STICK_KEYS = ('axis_thr', 'axis_yaw', 'axis_pitch', 'axis_roll')


@dataclass(frozen=True)
class Binding:
    channel: int
    kind: str
    index: int
    label: str


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _reserved_buttons(cal: dict[str, Any]) -> set[int]:
    reserved: set[int] = set()
    if cal.get('arm_type', 'button') == 'button':
        idx = _int_or_none(cal.get('arm_button_index'))
        if idx is not None:
            reserved.add(idx)
    idx = _int_or_none(cal.get('release_button_index'))
    if idx is not None:
        reserved.add(idx)
    return reserved


def _reserved_axes(cal: dict[str, Any]) -> set[int]:
    reserved = {_int_or_none(cal.get(key)) for key in _STICK_KEYS}
    if cal.get('arm_type') == 'axis':
        reserved.add(_int_or_none(cal.get('arm_axis_index')))
    reserved.add(_int_or_none(cal.get('release_axis_index')))
    return {idx for idx in reserved if idx is not None}


def auto_bindings(
    cal: dict[str, Any], num_buttons: int, num_axes: int, num_hats: int
) -> list[Binding]:
    """Свободные органы управления по каналам CH7..CH16, порядок детерминирован.

    CH6 всегда закреплён за сбросом, даже когда сброс не назначен: иначе
    раскладка съезжала бы при его настройке и правила aux в полётнике
    указывали бы не на те каналы.
    """
    skip_buttons = _reserved_buttons(cal)
    skip_axes = _reserved_axes(cal)

    sources: list[tuple[str, int, str]] = []
    sources += [
        ('button', i, f'Кнопка {i}')
        for i in range(max(0, num_buttons))
        if i not in skip_buttons
    ]
    sources += [
        ('axis', i, f'Ось {i}') for i in range(max(0, num_axes)) if i not in skip_axes
    ]
    for i in range(max(0, num_hats)):
        sources.append(('hat_x', i, f'Крестовина {i} ←→'))
        sources.append(('hat_y', i, f'Крестовина {i} ↑↓'))

    free = CH_LAST - CH_AUTO_FIRST + 1
    return [
        Binding(channel=CH_AUTO_FIRST + n, kind=kind, index=index, label=label)
        for n, (kind, index, label) in enumerate(sources[:free])
    ]


def _switch(on: bool) -> int:
    return CH_MAX if on else CH_MIN


def _axis(raw: float) -> int:
    clamped = max(-1.0, min(1.0, raw))
    return round(CH_MIN + (clamped + 1.0) / 2.0 * (CH_MAX - CH_MIN))


def _hat(raw: int) -> int:
    if raw > 0:
        return CH_MAX
    if raw < 0:
        return CH_MIN
    return CH_CENTER


def aux_from_state(
    bindings: list[Binding],
    release_on: bool,
    toggles: dict[int, bool],
    axes: dict[int, float],
    hats: dict[int, tuple[int, int]],
) -> list[int]:
    """Значения CH6..CH16. Источник без данных даёт центр, а не мусор."""
    values = [CH_CENTER] * AUX_COUNT
    values[CH_RELEASE - CH_ARM - 1] = _switch(release_on)
    for binding in bindings:
        slot = binding.channel - CH_ARM - 1
        if not 0 <= slot < AUX_COUNT:
            continue
        if binding.kind == 'button':
            values[slot] = _switch(bool(toggles.get(binding.index, False)))
        elif binding.kind == 'axis':
            raw = axes.get(binding.index)
            values[slot] = CH_CENTER if raw is None else _axis(raw)
        elif binding.kind in ('hat_x', 'hat_y'):
            pair = hats.get(binding.index)
            if pair is None:
                continue
            values[slot] = _hat(pair[0] if binding.kind == 'hat_x' else pair[1])
    return values
