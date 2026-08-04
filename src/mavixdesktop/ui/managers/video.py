"""Video stream manager: decoded frames go to the UI as they arrive, newest wins."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any

from aiortc import VideoStreamTrack
from aiortc.mediastreams import MediaStreamError
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
    ) -> None:
        self._on_frame = on_frame
        self._on_cam_changed = on_cam_changed

        self._track_ids: list[str] = []
        self._receive_tasks: list[asyncio.Task] = []
        self._cam_index: int = 0

        self._lock = threading.Lock()
        self._pending: dict[str, Any] = {}
        self._scheduled: set[str] = set()
        self._delivering = False

        self._arrival = _FrameArrival()
        self._arrival.arrived.connect(self._deliver, Qt.QueuedConnection)

        self._decoded = 0
        self._rendered = 0
        self._coalesced = 0
        self._stats_timer = QTimer(interval=self.STATS_INTERVAL_MS)
        self._stats_timer.timeout.connect(self._log_stats)

    def on_track(self, track: VideoStreamTrack) -> None:
        if track.kind != 'video':
            return
        self._track_ids.append(track.id)
        logger.info('[video] трек получен: id=%s', track.id)
        self._receive_tasks.append(asyncio.create_task(self._receive(track)))

    async def _receive(self, track: VideoStreamTrack) -> None:
        loop = asyncio.get_event_loop()
        try:
            while True:
                frame = await track.recv()
                img = await loop.run_in_executor(None, lambda f=frame: f.to_ndarray(format='bgr24'))
                self._publish(track.id, img)
        except asyncio.CancelledError:
            return
        except (MediaStreamError, RuntimeError):
            pass

    def _publish(self, track_id: str, img: Any) -> None:
        with self._lock:
            self._decoded += 1
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
        self._on_frame(img)

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
        if not self._track_ids:
            return None
        track_id = self._track_ids[min(cam_idx, len(self._track_ids) - 1)]
        with self._lock:
            img = self._pending.pop(track_id, None)
            if img is not None:
                self._rendered += 1
        return img

    def shift_cam(self, delta: int) -> int:
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

    def _log_stats(self) -> None:
        with self._lock:
            decoded, rendered, coalesced = self._decoded, self._rendered, self._coalesced
            self._decoded = self._rendered = self._coalesced = 0
        if not decoded and not rendered:
            return
        secs = self.STATS_INTERVAL_MS / 1000
        logger.info(
            '[video] декодировано %.1f к/с, отрисовано %.1f к/с, вытеснено %d',
            decoded / secs, rendered / secs, coalesced,
        )
