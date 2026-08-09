"""Polls RTCPeerConnection.getStats() once a second and turns counters into rates."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass

from mavixdesktop.core.logger import logger


@dataclass
class _Totals:
    at: float = 0.0
    bytes_received: int = 0
    packets_received: int = 0
    packets_lost: int = 0


def read_totals(report: object, now: float) -> _Totals:
    """aiortc inbound-rtp carries only packets; bytes live on the transport."""
    totals = _Totals(at=now)
    values = report.values() if hasattr(report, 'values') else []
    for entry in values:
        kind = getattr(entry, 'type', '')
        if kind == 'inbound-rtp':
            totals.packets_received += int(getattr(entry, 'packetsReceived', 0) or 0)
            totals.packets_lost += int(getattr(entry, 'packetsLost', 0) or 0)
        elif kind == 'transport':
            totals.bytes_received += int(getattr(entry, 'bytesReceived', 0) or 0)
    return totals


def to_sample(previous: _Totals, current: _Totals) -> tuple[float, float]:
    """Returns (kbit/s, loss %). Lost packets can go negative on duplicates — clamped."""
    elapsed = current.at - previous.at
    if elapsed <= 0:
        return 0.0, 0.0
    bitrate = (
        max(0, current.bytes_received - previous.bytes_received) * 8 / 1000.0 / elapsed
    )
    received = max(0, current.packets_received - previous.packets_received)
    lost = max(0, current.packets_lost - previous.packets_lost)
    expected = received + lost
    loss = (lost / expected * 100.0) if expected else 0.0
    return bitrate, loss


class StatsCollector:
    """Runs as an asyncio task for as long as the session lives."""

    def __init__(
        self,
        pc: object,
        on_sample: Callable[[float, float], None],
        interval: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._pc = pc
        self._on_sample = on_sample
        self._interval = interval
        self._clock = clock
        self._previous: _Totals | None = None

    async def poll_once(self) -> None:
        report = await self._pc.getStats()  # type: ignore[attr-defined]
        current = read_totals(report, self._clock())
        previous, self._previous = self._previous, current
        if previous is None:
            return
        bitrate, loss = to_sample(previous, current)
        self._on_sample(bitrate, loss)

    async def run(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval)
                await self.poll_once()
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug('[stats] опрос getStats не удался: %s', exc)
