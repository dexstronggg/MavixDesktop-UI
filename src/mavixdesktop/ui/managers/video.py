"""Video stream manager: decoded frames go to the UI as they arrive, newest wins."""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any, cast

from aiortc import MediaStreamTrack, VideoStreamTrack
from aiortc.mediastreams import MediaStreamError
from av import VideoFrame
from PySide6.QtCore import QObject, Qt, QTimer, Signal

from mavixdesktop.core.logger import logger


class _FrameArrival(QObject):
    arrived = Signal(str)


class VideoManager:
    STATS_INTERVAL_MS = 5000

    def __init__(
        self,
        on_frame: Callable[[Any], None],
        on_cam_changed: Callable[[int], None] | None = None,
        on_frame_shown: Callable[[], None] | None = None,
    ) -> None:
        self._on_frame = on_frame
        self._on_cam_changed = on_cam_changed
        self._on_frame_shown = on_frame_shown

        self._track_ids: list[str] = []
        self._receive_tasks: list[asyncio.Task[None]] = []
        self._cam_index: int = 0

        self._lock = threading.Lock()
        self._pending: dict[str, Any] = {}
        self._scheduled: set[str] = set()
        self._delivering = False

        self._arrival = _FrameArrival()
        self._arrival.arrived.connect(self._deliver, Qt.ConnectionType.QueuedConnection)

        self._decoded = 0
        self._rendered = 0
        self._coalesced = 0
        # диагностика: по какому треку что происходит (см. _log_stats)
        self._decoded_by_track: dict[str, int] = {}
        self._shown_by_track: dict[str, int] = {}
        self._miss_by_track: dict[str, int] = {}
        self._stats_timer = QTimer(interval=self.STATS_INTERVAL_MS)
        self._stats_timer.timeout.connect(self._log_stats)

        self._rendered_fps_prev_count = 0
        self._rendered_fps_prev_at: float | None = None

    def on_track(self, track: MediaStreamTrack) -> None:
        if track.kind != 'video':
            return
        with self._lock:
            self._track_ids.append(track.id)
            index = len(self._track_ids) - 1
        logger.info(
            '[video] трек получен: порядковый=%d id=%s (индекс камеры в UI берётся '
            'из порядка прихода треков)',
            index,
            track.id,
        )
        self._receive_tasks.append(
            asyncio.create_task(self._receive(cast(VideoStreamTrack, track)))
        )

    async def _receive(self, track: VideoStreamTrack) -> None:
        loop = asyncio.get_event_loop()
        try:
            while True:
                frame = cast(VideoFrame, await track.recv())
                img = await loop.run_in_executor(
                    None,
                    cast(
                        Callable[[], Any], lambda f=frame: f.to_ndarray(format='bgr24')
                    ),
                )
                self._publish(track.id, img)
        except asyncio.CancelledError:
            return
        except (MediaStreamError, RuntimeError):
            pass

    def _publish(self, track_id: str, img: Any) -> None:
        with self._lock:
            self._decoded += 1
            self._decoded_by_track[track_id] = (
                self._decoded_by_track.get(track_id, 0) + 1
            )
            if track_id in self._pending:
                self._coalesced += 1
            self._pending[track_id] = img
            if not self._delivering or track_id in self._scheduled:
                return
            self._scheduled.add(track_id)
        self._arrival.arrived.emit(track_id)

    def _deliver(self, track_id: str) -> None:
        with self._lock:
            self._scheduled.discard(track_id)
            if not self._delivering or track_id != self._active_track_id():
                return
            img = self._pending.pop(track_id, None)
            if img is None:
                return
            self._rendered += 1
            self._shown_by_track[track_id] = self._shown_by_track.get(track_id, 0) + 1
        self._on_frame(img)
        self._notify_shown()

    def _active_track_id(self) -> str | None:
        if not self._track_ids:
            return None
        return self._track_ids[min(self._cam_index, len(self._track_ids) - 1)]

    def _schedule_active(self) -> None:
        with self._lock:
            track_id = self._active_track_id()
            if (
                track_id is None
                or not self._delivering
                or track_id in self._scheduled
                or track_id not in self._pending
            ):
                return
            self._scheduled.add(track_id)
        self._arrival.arrived.emit(track_id)

    def get_frame(self, cam_idx: int) -> Any:
        """Poll API for FlightWindow: returns a frame only if a new one arrived."""
        with self._lock:
            if not self._track_ids:
                return None
            track_id = self._track_ids[min(cam_idx, len(self._track_ids) - 1)]
            img = self._pending.pop(track_id, None)
            if img is not None:
                self._rendered += 1
                self._shown_by_track[track_id] = (
                    self._shown_by_track.get(track_id, 0) + 1
                )
            else:
                self._miss_by_track[track_id] = self._miss_by_track.get(track_id, 0) + 1
        if img is not None:
            self._notify_shown()
        return img

    def _notify_shown(self) -> None:
        if self._on_frame_shown is None:
            return
        try:
            self._on_frame_shown()
        except Exception as exc:
            logger.debug('[video] ошибка обработчика on_frame_shown: %s', exc)

    def shift_cam(self, delta: int) -> int:
        with self._lock:
            if not self._track_ids:
                return self._cam_index
            self._cam_index = (self._cam_index + delta) % len(self._track_ids)
        if self._on_cam_changed:
            self._on_cam_changed(self._cam_index)
        self._schedule_active()
        return self._cam_index

    @property
    def cam_index(self) -> int:
        return self._cam_index

    @property
    def cam_count(self) -> int:
        with self._lock:
            return len(self._track_ids)

    def start(self) -> None:
        with self._lock:
            self._delivering = True
        self._stats_timer.start()
        self._schedule_active()

    def stop(self) -> None:
        with self._lock:
            self._delivering = False
        self._stats_timer.stop()

    def reset(self) -> None:
        self.clear_tracks()
        self._cam_index = 0

    def clear_tracks(self) -> None:
        self._cancel_receive_tasks()
        self._log_stats()
        with self._lock:
            self._track_ids.clear()
            self._pending.clear()
            self._scheduled.clear()

    def _cancel_receive_tasks(self) -> None:
        for task in self._receive_tasks:
            if not task.done():
                task.cancel()
        self._receive_tasks.clear()

    def rendered_fps(self) -> float:
        """Средний fps отрисовки с прошлого вызова; первый вызов возвращает 0."""
        now = time.monotonic()
        with self._lock:
            rendered = self._rendered
        prev_at = self._rendered_fps_prev_at
        prev_count = self._rendered_fps_prev_count
        self._rendered_fps_prev_at = now
        self._rendered_fps_prev_count = rendered
        if prev_at is None:
            return 0.0
        elapsed = now - prev_at
        if elapsed <= 0:
            return 0.0
        return (rendered - prev_count) / elapsed

    def _log_stats(self) -> None:
        with self._lock:
            decoded, rendered, coalesced = (
                self._decoded,
                self._rendered,
                self._coalesced,
            )
            self._decoded = self._rendered = self._coalesced = 0
            per_track = [
                (
                    idx,
                    tid,
                    self._decoded_by_track.pop(tid, 0),
                    self._shown_by_track.pop(tid, 0),
                    self._miss_by_track.pop(tid, 0),
                )
                for idx, tid in enumerate(self._track_ids)
            ]
            self._decoded_by_track.clear()
            self._shown_by_track.clear()
            self._miss_by_track.clear()
            active_idx = self._cam_index
            active_id = self._active_track_id()
            delivering = self._delivering
        for idx, tid, dec, shown, miss in per_track:
            logger.info(
                '[video] трек %d%s id=%s: принято %d, показано %d, пусто %d',
                idx,
                ' (активный)' if tid == active_id else '',
                tid[:8],
                dec,
                shown,
                miss,
            )
        logger.info(
            '[video] активная камера в UI: индекс=%d, доставка на экран просмотра=%s',
            active_idx,
            'вкл' if delivering else 'выкл',
        )
        if not decoded and not rendered:
            return
        secs = self.STATS_INTERVAL_MS / 1000
        logger.info(
            '[video] декодировано %.1f к/с, отрисовано %.1f к/с, вытеснено %d',
            decoded / secs,
            rendered / secs,
            coalesced,
        )
