"""Советчик режима камеры: только подсказка, переключение — решение пилота."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from mavixdesktop.ui.managers.quality import LinkSnapshot

REQUIRED_HEADROOM = 1.25
CLEAN_LOSS_PCT = 0.5
CLEAN_GROWTH = 1.2
BUSY_LOSS_PCT = 5.0
BUSY_GROWTH = 1.5
CLEAN_FACTOR = 1.15
PROBE_AFTER_S = 30.0
PROBE_FACTOR = 1.5
CONGESTED_FACTOR = 0.85
TFRC_FLOOR_FACTOR = 0.5
EWMA_ALPHA = 0.3
MIN_HISTORY_S = 10.0
CONFIRM_TICKS = 2
MTU_BYTES = 1200


def required_kbps(
    width: int, height: int, fps: int, bpp: float, motion: float
) -> float:
    """Формула Kush Gauge: битрейт, нужный для картинки такого разрешения и динамики."""
    return width * height * fps * bpp * motion / 1000


def tfrc_kbps(
    rtt_ms: float, loss_fraction: float, packet_bytes: int = MTU_BYTES
) -> float:
    """Уравнение пропускной способности TFRC (RFC 5348) при доле потерь p и RTT."""
    if loss_fraction <= 0 or rtt_ms <= 0:
        return float('inf')
    r = rtt_ms / 1000.0
    p = loss_fraction
    t_rto = max(4 * r, 1.0)
    denom = r * math.sqrt(2 * p / 3) + t_rto * (
        3 * math.sqrt(3 * p / 8) * p * (1 + 32 * p**2)
    )
    if denom <= 0:
        return float('inf')
    bytes_per_s = packet_bytes / denom
    return bytes_per_s * 8 / 1000


class ChannelEstimator:
    """Оценка доступной ёмкости канала: goodput, TFRC при потерях, осторожный рост."""

    def __init__(self) -> None:
        self._smoothed: float | None = None
        self._clean_since: float | None = None

    def reset(self) -> None:
        self._smoothed = None
        self._clean_since = None

    def update(self, snap: LinkSnapshot, now: float) -> float:
        goodput = snap.bitrate_in_kbps
        clean = snap.loss_pct < CLEAN_LOSS_PCT and snap.rtt_growth < CLEAN_GROWTH
        busy = snap.loss_pct > BUSY_LOSS_PCT or snap.rtt_growth >= BUSY_GROWTH
        if clean:
            if self._clean_since is None:
                self._clean_since = now
            probing = now - self._clean_since >= PROBE_AFTER_S
            candidate = goodput * (PROBE_FACTOR if probing else CLEAN_FACTOR)
        elif busy:
            self._clean_since = None
            # TFRC даёт «честную рядом с TCP» скорость, а не потолок канала:
            # ниже половины реально прошедшего трафика ему опускать нас нельзя
            tfrc = tfrc_kbps(snap.rtt_p95_ms, snap.loss_pct / 100)
            candidate = max(
                goodput * TFRC_FLOOR_FACTOR, min(goodput * CONGESTED_FACTOR, tfrc)
            )
        else:
            self._clean_since = None
            candidate = goodput
        if candidate == float('inf'):
            candidate = goodput
        if self._smoothed is None:
            self._smoothed = candidate
        else:
            self._smoothed = EWMA_ALPHA * candidate + (1 - EWMA_ALPHA) * self._smoothed
        return self._smoothed


@dataclass(frozen=True)
class Recommendation:
    width: int
    height: int
    fps: int
    required_kbps: float
    capacity_kbps: float
    current_required_kbps: float
    fits: bool


def _valid_mode(param: object) -> tuple[int, int, int] | None:
    if not isinstance(param, dict):
        return None
    try:
        width = int(param['width'])
        height = int(param['height'])
        fps = int(param['fps'])
    except (KeyError, TypeError, ValueError):
        return None
    if width <= 0 or height <= 0 or fps <= 0:
        return None
    return width, height, fps


def pick_mode(
    params: list[dict[str, Any]],
    capacity_kbps: float,
    fps_ceiling: float,
    bpp: float,
    motion: float,
) -> dict[str, Any] | None:
    modes: list[tuple[int, int, int]] = []
    for param in params:
        mode = _valid_mode(param)
        if mode is not None:
            modes.append(mode)
    if not modes:
        return None

    fits: list[tuple[int, int, int]] = []
    for width, height, fps in modes:
        required = required_kbps(width, height, fps, bpp, motion)
        within_headroom = required * REQUIRED_HEADROOM <= capacity_kbps
        within_fps = fps <= fps_ceiling + 5
        if within_headroom and within_fps:
            fits.append((width, height, fps))

    if fits:
        best = max(fits, key=lambda m: (m[0] * m[1], m[2]))
    else:
        best = min(modes, key=lambda m: m[0] * m[1] * m[2])
    return {'width': best[0], 'height': best[1], 'fps': best[2]}


class Advisor:
    """Фасад с гистерезисом: новая рекомендация приживается после двух тиков подряд."""

    def __init__(self, bpp: float, motion: float) -> None:
        self._bpp = bpp
        self._motion = motion
        self._estimator = ChannelEstimator()
        self._session_start: float | None = None
        self._pending: dict[str, Any] | None = None
        self._pending_streak = 0
        self._confirmed: dict[str, Any] | None = None

    def start_session(self, now: float) -> None:
        self._session_start = now
        self._estimator.reset()
        self._pending = None
        self._pending_streak = 0
        self._confirmed = None

    def reset(self) -> None:
        self._session_start = None
        self._estimator.reset()
        self._pending = None
        self._pending_streak = 0
        self._confirmed = None

    def _keep_current_if_still_fits(
        self,
        best: dict[str, Any],
        current_param: dict[str, Any] | None,
        capacity: float,
    ) -> dict[str, Any]:
        """Понижение советуем, когда текущий режим перестал влезать, а не по запасу в 25 %."""
        current = _valid_mode(current_param)
        if current is None:
            return best
        width, height, fps = current
        if required_kbps(width, height, fps, self._bpp, self._motion) > capacity:
            return best
        if best['width'] * best['height'] * best['fps'] >= width * height * fps:
            return best
        return {'width': width, 'height': height, 'fps': fps}

    def update(
        self,
        snap: LinkSnapshot,
        params: list[dict[str, Any]],
        current_param: dict[str, Any] | None,
        fps_rendered: float,
        now: float,
    ) -> Recommendation | None:
        if self._session_start is None or now - self._session_start < MIN_HISTORY_S:
            return None
        if snap.bitrate_in_kbps <= 0 or not params:
            return None

        fps_ceiling = fps_rendered if fps_rendered > 0 else float('inf')
        capacity = self._estimator.update(snap, now)
        best = pick_mode(params, capacity, fps_ceiling, self._bpp, self._motion)
        if best is None:
            return None
        best = self._keep_current_if_still_fits(best, current_param, capacity)

        if self._pending is not None and self._pending == best:
            self._pending_streak += 1
        else:
            self._pending = best
            self._pending_streak = 1

        if self._pending_streak >= CONFIRM_TICKS:
            self._confirmed = best
        chosen = self._confirmed
        if chosen is None:
            return None

        required = required_kbps(
            chosen['width'], chosen['height'], chosen['fps'], self._bpp, self._motion
        )
        fits = required <= capacity

        current_required = 0.0
        current_mode = _valid_mode(current_param)
        if current_mode is not None:
            current_required = required_kbps(
                current_mode[0],
                current_mode[1],
                current_mode[2],
                self._bpp,
                self._motion,
            )

        return Recommendation(
            width=chosen['width'],
            height=chosen['height'],
            fps=chosen['fps'],
            required_kbps=required,
            capacity_kbps=capacity,
            current_required_kbps=current_required,
            fits=fits,
        )


def format_advice(rec: Recommendation | None, current: dict[str, Any] | None) -> str:
    if rec is None:
        return ''

    rows = [
        (
            'рекомендуется',
            f'{rec.width}x{rec.height}@{rec.fps} — нужно '
            f'{rec.required_kbps / 1000.0:.1f} Мбит/с',
        )
    ]

    current_mode = _valid_mode(current)
    if current_mode is not None:
        width, height, fps = current_mode
        second = (
            f'{width}x{height}@{fps} — нужно {rec.current_required_kbps / 1000.0:.1f}, '
            f'канал даёт ~{rec.capacity_kbps / 1000.0:.1f} Мбит/с'
        )
    else:
        second = f'канал даёт ~{rec.capacity_kbps / 1000.0:.1f} Мбит/с'
    if not rec.fits:
        second += ' (канал не тянет даже минимум)'
    rows.append(('сейчас', second))

    width_col = max(len(name) for name, _ in rows)
    body = '\n'.join(f'{name.ljust(width_col)}   {value}' for name, value in rows)
    return body
