"""Video stream manager."""
from __future__ import annotations

import asyncio
import contextlib
import queue

from aiortc import VideoStreamTrack
from aiortc.mediastreams import MediaStreamError
from PySide6.QtCore import QTimer

from mavixdesktop.core.logger import logger


class VideoManager:
    def __init__(self, on_frame, on_cam_changed=None) -> None:
        self._on_frame = on_frame
        self._on_cam_changed = on_cam_changed

        self.track_queues: dict[str, queue.Queue] = {}
        self._track_ids: list[str] = []
        self._receive_tasks: list[asyncio.Task] = []
        self._cam_index: int = 0

        self._timer = QTimer(interval=33)
        self._timer.timeout.connect(self._tick)

    def on_track(self, track: VideoStreamTrack) -> None:
        if track.kind != 'video':
            return
        self.track_queues[track.id] = queue.Queue(maxsize=1)
        self._track_ids.append(track.id)
        logger.info('[video] трек получен: id=%s', track.id)
        self._receive_tasks.append(asyncio.create_task(self._receive(track)))

    async def _receive(self, track: VideoStreamTrack) -> None:
        q = self.track_queues[track.id]
        loop = asyncio.get_event_loop()
        try:
            while True:
                frame = await track.recv()
                img = await loop.run_in_executor(None, lambda f=frame: f.to_ndarray(format='bgr24'))
                try:
                    q.put_nowait(img)
                except queue.Full:
                    q.get_nowait()
                    q.put_nowait(img)
        except asyncio.CancelledError:
            return
        except (MediaStreamError, RuntimeError):
            pass

    def _cancel_receive_tasks(self) -> None:
        for task in self._receive_tasks:
            if not task.done():
                task.cancel()
        self._receive_tasks.clear()

    def reset(self) -> None:
        self._cancel_receive_tasks()
        self.track_queues.clear()
        self._track_ids.clear()
        self._cam_index = 0

    def clear_tracks(self) -> None:
        self._cancel_receive_tasks()
        self.track_queues.clear()
        self._track_ids.clear()

    def shift_cam(self, delta: int) -> int:
        if not self._track_ids:
            return self._cam_index
        self._cam_index = (self._cam_index + delta) % len(self._track_ids)
        if self._on_cam_changed:
            self._on_cam_changed(self._cam_index)
        return self._cam_index

    def get_frame(self, cam_idx: int):
        if not self._track_ids:
            return None
        idx = min(cam_idx, len(self._track_ids) - 1)
        q = self.track_queues.get(self._track_ids[idx])
        if q is None:
            return None
        frame = None
        try:
            while True:
                frame = q.get_nowait()
        except queue.Empty:
            pass
        return frame

    @property
    def cam_index(self) -> int:
        return self._cam_index

    @property
    def cam_count(self) -> int:
        return len(self._track_ids)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _tick(self) -> None:
        if not self._track_ids:
            return
        self._cam_index = min(self._cam_index, len(self._track_ids) - 1)
        q = self.track_queues.get(self._track_ids[self._cam_index])
        if q is None:
            return
        with contextlib.suppress(queue.Empty):
            self._on_frame(q.get_nowait())
