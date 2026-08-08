"""JitterBuffer-патч aiortc: deadline для кадров с потерянными пакетами."""

from __future__ import annotations

import time

from aiortc.jitterbuffer import JitterBuffer, JitterFrame
from aiortc.rtp import RtpPacket

from mavixdesktop.core.logger import logger

STUCK_DEADLINE_S = 0.2

_applied = False


class DeadlineJitterBuffer(JitterBuffer):
    def __init__(
        self, capacity: int, prefetch: int = 0, is_video: bool = False
    ) -> None:
        super().__init__(capacity, prefetch, is_video)
        self._stuck_since: float | None = None
        self._deadline_s = STUCK_DEADLINE_S

    def add(self, packet: RtpPacket) -> tuple[bool, JitterFrame | None]:
        pli_flag, frame = super().add(packet)
        if not self._is_video:
            return pli_flag, frame
        if self._origin is None or frame is not None:
            self._stuck_since = None
            return pli_flag, frame
        if not self._is_blocked():
            self._stuck_since = None
            return pli_flag, frame
        now = time.monotonic()
        if self._stuck_since is None:
            self._stuck_since = now
        elif now - self._stuck_since >= self._deadline_s:
            self._stuck_since = None
            saved = self._skip_blocked_frame()
            logger.info(
                '[jitter] дыра в кадре не закрылась за %.0f мс — '
                'сброс неполного кадра, запрос ключевого кадра',
                self._deadline_s * 1000,
            )
            if saved is not None:
                return True, saved
            return True, None
        return pli_flag, frame

    def _is_blocked(self) -> bool:
        if self._origin is None:
            return False
        seen_gap = False
        for count in range(self._capacity):
            packet = self._packets[(self._origin + count) % self._capacity]
            if packet is None:
                seen_gap = True
            elif seen_gap:
                return True
        return False

    def _skip_blocked_frame(self) -> JitterFrame | None:
        """Пропускает застрявшую дыру; полный кадр на origin выдаёт, неполный — отбрасывает."""
        if self._origin is None:
            return None

        frame_ts: int | None = None
        frame_packets: list[RtpPacket] = []
        gap_at: int | None = None
        for count in range(self._capacity):
            slot = (self._origin + count) % self._capacity
            p = self._packets[slot]
            if p is None:
                if gap_at is None:
                    gap_at = count
                continue
            if frame_ts is None:
                frame_ts = p.timestamp
            if p.timestamp != frame_ts:
                break
            if gap_at is None:
                frame_packets.append(p)

        if frame_ts is None:
            return None

        gap_inside = False
        if gap_at is not None:
            for count in range(gap_at + 1, self._capacity):
                p = self._packets[(self._origin + count) % self._capacity]
                if p is not None:
                    gap_inside = p.timestamp == frame_ts
                    break

        if gap_inside:
            remove_count = 0
            for count in range(self._capacity):
                p = self._packets[(self._origin + count) % self._capacity]
                if p is None or p.timestamp == frame_ts:
                    remove_count += 1
                else:
                    break
            self.remove(remove_count)
            return None

        self.remove(len(frame_packets) + 1)
        first_after = self._packets[self._origin % self._capacity]
        if first_after is not None:
            after_ts = first_after.timestamp
            remove_count = 0
            for count in range(self._capacity):
                p = self._packets[(self._origin + count) % self._capacity]
                if p is not None and p.timestamp == after_ts:
                    remove_count += 1
                else:
                    break
            self.remove(remove_count)
        return JitterFrame(
            data=b''.join(p._data for p in frame_packets),  # type: ignore
            timestamp=frame_ts,
        )


def install_jitter_patch() -> None:
    global _applied
    if _applied:
        return
    try:
        from aiortc import rtcrtpreceiver

        rtcrtpreceiver.JitterBuffer = DeadlineJitterBuffer  # type: ignore[attr-defined]
        _applied = True
        logger.info(
            '[webrtc] jitter-патч aiortc установлен (video deadline %.0f мс)',
            STUCK_DEADLINE_S * 1000,
        )
    except Exception as exc:
        logger.error('[webrtc] jitter-патч aiortc не применился: %s', exc)
