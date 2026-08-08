"""Link quality: the six core metrics, a traffic light for the pilot, a jsonl trail."""
from __future__ import annotations

import json
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import IO

from mavixdesktop.core.logger import logger
from mavixdesktop.ui.style import theme

LEVEL_IDLE = 'idle'
LEVEL_OK = 'ok'
LEVEL_WARN = 'warn'
LEVEL_BAD = 'bad'

_RTT_WINDOW_S = 10.0
_FREEZE_WINDOW_S = 10.0
_FRESH_DATA_S = 3.0
_FREEZE_MIN_GAP_S = 0.15
_INTERVAL_HISTORY = 60

LOSS_WARN_PCT = 1.0
LOSS_BAD_PCT = 3.0
RTT_WARN_MS = 150.0
RTT_BAD_MS = 400.0
RTT_GROWTH_WARN = 1.5
RTT_GROWTH_BAD = 3.0
RTT_GROWTH_MIN_MS = 50.0
FREEZE_WARN_RATIO = 0.01
FREEZE_BAD_RATIO = 0.05
STALE_FRAME_MS = 300.0


@dataclass(frozen=True)
class LinkSnapshot:
    level: str = LEVEL_IDLE
    bitrate_in_kbps: float = 0.0
    loss_pct: float = 0.0
    rtt_p95_ms: float = -1.0
    rtt_growth: float = 1.0
    freeze_count: int = 0
    freeze_ms: float = 0.0
    freeze_ratio: float = 0.0
    staleness_ms: float = -1.0
    bitrate_out_kbps: float = -1.0
    encoder_kbps: float = -1.0
    out_ratio: float = -1.0
    pli: int = 0


@dataclass
class _Freeze:
    at: float
    duration: float = 0.0


@dataclass
class _RttSample:
    at: float
    value: float


@dataclass
class _State:
    rtt: deque[_RttSample] = field(default_factory=lambda: deque(maxlen=200))
    intervals: deque[float] = field(default_factory=lambda: deque(maxlen=_INTERVAL_HISTORY))
    freezes: deque[_Freeze] = field(default_factory=lambda: deque(maxlen=200))


class LinkQuality:
    """Fed from three threads: asyncio (inbound/board), GUI (rtt, frames, snapshot)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._state = _State()

        self._bitrate_in = 0.0
        self._loss_pct = 0.0
        self._inbound_at = 0.0

        self._bitrate_out = -1.0
        self._encoder_kbps = -1.0
        self._pli_total = 0

        self._last_frame_at = 0.0
        self._freeze_total = 0
        self._freeze_ms_total = 0.0

        self._log: IO[str] | None = None
        self._log_seq = 0

    def start_session(self, log_path: Path | None = None) -> None:
        with self._lock:
            self._state = _State()
            self._bitrate_in = self._loss_pct = self._inbound_at = 0.0
            self._bitrate_out = self._encoder_kbps = -1.0
            self._pli_total = 0
            self._last_frame_at = 0.0
            self._freeze_total = 0
            self._freeze_ms_total = 0.0
            self._log_seq = 0
        self._close_log()
        if log_path is not None:
            self._open_log(log_path)

    def end_session(self) -> None:
        self._close_log()

    def add_rtt(self, rtt_ms: float) -> None:
        if rtt_ms < 0:
            return
        now = self._clock()
        with self._lock:
            self._state.rtt.append(_RttSample(now, rtt_ms))
            self._prune(now)

    def update_inbound(self, bitrate_in_kbps: float, loss_pct: float) -> None:
        now = self._clock()
        with self._lock:
            self._bitrate_in = bitrate_in_kbps
            self._loss_pct = loss_pct
            self._inbound_at = now

    def update_board(self, bitrate_out_kbps: float, encoder_kbps: float, pli: int) -> None:
        with self._lock:
            self._bitrate_out = bitrate_out_kbps
            self._encoder_kbps = encoder_kbps
            self._pli_total += max(0, pli)

    def on_frame_shown(self) -> None:
        now = self._clock()
        with self._lock:
            previous, self._last_frame_at = self._last_frame_at, now
            if previous <= 0:
                return
            gap = now - previous
            threshold = self._freeze_threshold()
            if gap > threshold:
                self._state.freezes.append(_Freeze(now, gap))
                self._freeze_total += 1
                self._freeze_ms_total += gap * 1000.0
            else:
                self._state.intervals.append(gap)
            self._prune(now)

    def snapshot(self) -> LinkSnapshot:
        now = self._clock()
        with self._lock:
            self._prune(now)
            rtt_p95 = self._percentile([s.value for s in self._state.rtt], 0.95)
            rtt_floor = self._percentile([s.value for s in self._state.rtt], 0.20)
            growth = (rtt_p95 / rtt_floor) if rtt_floor > 0 else 1.0
            freeze_ms = sum(f.duration for f in self._state.freezes) * 1000.0
            freeze_ratio = freeze_ms / 1000.0 / _FREEZE_WINDOW_S
            staleness = (now - self._last_frame_at) * 1000.0 if self._last_frame_at > 0 else -1.0
            fresh = (now - self._inbound_at) <= _FRESH_DATA_S if self._inbound_at > 0 else False
            out_ratio = (
                self._bitrate_out / self._encoder_kbps
                if self._bitrate_out >= 0 and self._encoder_kbps > 0
                else -1.0
            )
            snap = LinkSnapshot(
                level=LEVEL_IDLE,
                bitrate_in_kbps=self._bitrate_in,
                loss_pct=self._loss_pct,
                rtt_p95_ms=rtt_p95 if self._state.rtt else -1.0,
                rtt_growth=growth,
                freeze_count=self._freeze_total,
                freeze_ms=self._freeze_ms_total,
                freeze_ratio=freeze_ratio,
                staleness_ms=staleness,
                bitrate_out_kbps=self._bitrate_out,
                encoder_kbps=self._encoder_kbps,
                out_ratio=out_ratio,
                pli=self._pli_total,
            )
            frames_active = self._last_frame_at > 0 and (now - self._last_frame_at) <= _FREEZE_WINDOW_S
            has_data = fresh or bool(self._state.rtt) or frames_active
        level = self._level(snap) if has_data else LEVEL_IDLE
        return LinkSnapshot(**{**asdict(snap), 'level': level})

    @staticmethod
    def _level(snap: LinkSnapshot) -> str:
        # множитель роста учитываем только на заметных задержках: втрое от 1 мс ничего не значит
        growth = snap.rtt_growth if snap.rtt_p95_ms >= RTT_GROWTH_MIN_MS else 1.0
        if (
            snap.loss_pct > LOSS_BAD_PCT
            or (snap.rtt_p95_ms >= 0 and snap.rtt_p95_ms > RTT_BAD_MS)
            or growth >= RTT_GROWTH_BAD
            or snap.freeze_ratio > FREEZE_BAD_RATIO
        ):
            return LEVEL_BAD
        if (
            snap.loss_pct > LOSS_WARN_PCT
            or (snap.rtt_p95_ms >= 0 and snap.rtt_p95_ms > RTT_WARN_MS)
            or growth >= RTT_GROWTH_WARN
            or snap.freeze_ratio > FREEZE_WARN_RATIO
        ):
            return LEVEL_WARN
        return LEVEL_OK

    def _freeze_threshold(self) -> float:
        if not self._state.intervals:
            return 1.0
        avg = sum(self._state.intervals) / len(self._state.intervals)
        return max(3.0 * avg, avg + _FREEZE_MIN_GAP_S)

    def _prune(self, now: float) -> None:
        while self._state.rtt and now - self._state.rtt[0].at > _RTT_WINDOW_S:
            self._state.rtt.popleft()
        while self._state.freezes and now - self._state.freezes[0].at > _FREEZE_WINDOW_S:
            self._state.freezes.popleft()

    @staticmethod
    def _percentile(values: list[float], q: float) -> float:
        if not values:
            return -1.0
        ordered = sorted(values)
        idx = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
        return ordered[idx]

    def _open_log(self, path: Path) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._log = path.open('a', encoding='utf-8', buffering=1)
        except OSError as exc:
            logger.warning('[quality] не удалось открыть %s: %s', path, exc)
            self._log = None

    def _close_log(self) -> None:
        if self._log is None:
            return
        try:
            self._log.close()
        except OSError as exc:
            logger.debug('[quality] ошибка закрытия лога метрик: %s', exc)
        self._log = None

    def log_snapshot(self, snap: LinkSnapshot) -> None:
        if self._log is None:
            return
        self._log_seq += 1
        record = {'seq': self._log_seq, 'ts': round(time.time(), 3)}
        record.update({k: round(v, 3) if isinstance(v, float) else v for k, v in asdict(snap).items()})
        try:
            self._log.write(json.dumps(record, ensure_ascii=False) + '\n')
        except (OSError, ValueError) as exc:
            logger.warning('[quality] ошибка записи метрик: %s', exc)
            self._close_log()


_LEVEL_COLORS = {
    LEVEL_OK: theme.STATUS_READY,
    LEVEL_WARN: theme.WARNING,
    LEVEL_BAD: theme.STATUS_ERROR,
    LEVEL_IDLE: theme.TEXT_MUTED,
}


def level_color(level: str) -> str:
    return _LEVEL_COLORS.get(level, theme.TEXT_MUTED)


def format_quality_line(snap: LinkSnapshot) -> tuple[str, str]:
    color = level_color(snap.level)
    if snap.level == LEVEL_IDLE:
        return '\u25cf  нет данных', color
    rtt = f'{snap.rtt_p95_ms:.0f} мс' if snap.rtt_p95_ms >= 0 else '— мс'
    mbit = snap.bitrate_in_kbps / 1000.0
    return f'\u25cf  {mbit:.1f} Мбит/с   потери {snap.loss_pct:.1f}%   {rtt}', color


def format_stats_table(snap: LinkSnapshot) -> str:
    def num(value: float, unit: str, digits: int = 1) -> str:
        return '—' if value < 0 else f'{value:.{digits}f} {unit}'

    rows = [
        ('входящий поток', num(snap.bitrate_in_kbps / 1000.0, 'Мбит/с')),
        ('потери', f'{snap.loss_pct:.2f} %'),
        ('задержка p95', num(snap.rtt_p95_ms, 'мс', 0)),
        ('рост задержки', f'x{snap.rtt_growth:.1f}'),
        ('замирания', f'{snap.freeze_count} шт / {snap.freeze_ms / 1000.0:.1f} с'),
        ('доля замираний (10 с)', f'{snap.freeze_ratio * 100:.1f} %'),
        ('запросов ключевого кадра', str(snap.pli)),
    ]
    width = max(len(name) for name, _ in rows)
    body = '\n'.join(f'{name.ljust(width)}   {value}' for name, value in rows)
    return f'КАЧЕСТВО КАНАЛА  (S — скрыть)\n\n{body}'
