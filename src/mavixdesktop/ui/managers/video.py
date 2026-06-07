"""Менеджер видеопотока.

Отвечает за:
  - приём треков от WebRTC (on_track)
  - буферизацию кадров (queue.Queue на каждый трек)
  - таймер 33 мс → вызывает on_frame с очередным кадром
  - переключение активной камеры (shift_cam)

Ничего не знает о UI-страницах — только вызывает колбэки.
"""

from __future__ import annotations

import asyncio
import queue

from aiortc import VideoStreamTrack
from aiortc.mediastreams import MediaStreamError
from PySide6.QtCore import QTimer

from mavixdesktop.core.logger import logger


class VideoManager:
    """Управляет видеотреками и доставкой кадров в UI.

    on_frame вызывается каждые ~33 мс с очередным кадром, on_cam_changed —
    при смене активной камеры.
    """

    def __init__(self, on_frame, on_cam_changed=None) -> None:
        self._on_frame = on_frame
        self._on_cam_changed = on_cam_changed

        self.track_queues: dict[str, queue.Queue] = {}
        self._track_ids: list[str] = []
        self._receive_tasks: list[asyncio.Task] = []
        self._cam_index: int = 0

        self._timer = QTimer(interval=33)
        self._timer.timeout.connect(self._tick)

    #### Управление треками ################################################################
    def on_track(self, track: VideoStreamTrack) -> None:
        """Регистрирует новый видеотрек от WebRTC."""
        if track.kind != 'video':
            return
        self.track_queues[track.id] = queue.Queue(maxsize=1)
        self._track_ids.append(track.id)
        logger.info('[video] трек получен: id=%s', track.id)
        self._receive_tasks.append(asyncio.create_task(self._receive(track)))

    async def _receive(self, track: VideoStreamTrack) -> None:
        """Асинхронно читает кадры из трека и кладёт в очередь."""
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
        """Отменяет все активные корутины _receive и сбрасывает ссылки на них.

        Без этого каждая новая сессия создаёт свежие задачи _receive,
        которые не отменяются при сбросе старого набора треков — они
        продолжают ждать track.recv(), пока aiortc сам не закроет трек, что
        на завершении проявляется предупреждениями «Task was destroyed but
        it is pending» (и медленной утечкой файловых дескрипторов / памяти).

        Task.cancel() НЕ потокобезопасен, а нас зовут и из Qt-потока
        (reset/clear_tracks при навигации), и с asyncio-loop. Поэтому всегда
        планируем отмену на собственном loop задачи через call_soon_threadsafe
        — прямой cross-thread cancel повреждал состояние loop (SIGSEGV).
        """
        for task in self._receive_tasks:
            if task.done():
                continue
            try:
                task.get_loop().call_soon_threadsafe(task.cancel)
            except RuntimeError:
                # loop уже закрыт (выключение приложения) — отменяем как есть.
                task.cancel()
        self._receive_tasks.clear()

    def reset(self) -> None:
        """Сбрасывает всё при выходе из drone-view (треки и выбор камеры)."""
        self._cancel_receive_tasks()
        self.track_queues.clear()
        self._track_ids.clear()
        self._cam_index = 0

    def clear_tracks(self) -> None:
        """Сбрасывает только треки, сохраняя _cam_index.

        Используется при renegotiation сессии (смена разрешения, hot-plug):
        треки старой сессии становятся невалидными и надо очистить очереди,
        но пользователь всё ещё «смотрит» на ту же камеру с тем же индексом —
        после прихода новых треков _tick покажет тот же индекс."""
        self._cancel_receive_tasks()
        self.track_queues.clear()
        self._track_ids.clear()

    #### Управление камерой ################################################################
    def shift_cam(self, delta: int) -> int:
        """Переключает активную камеру на delta позиций. Возвращает новый индекс."""
        if not self._track_ids:
            return self._cam_index
        self._cam_index = (self._cam_index + delta) % len(self._track_ids)
        if self._on_cam_changed:
            self._on_cam_changed(self._cam_index)
        return self._cam_index

    def get_frame(self, cam_idx: int):
        """Возвращает последний кадр для заданного индекса камеры (или None)."""
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

    #### Таймер ############################################################################
    def start(self) -> None:
        """Запускает таймер отрисовки видео."""
        self._timer.start()

    def stop(self) -> None:
        """Останавливает таймер."""
        self._timer.stop()

    def _tick(self) -> None:
        """Колбэк таймера: берёт кадр из очереди и передаёт в on_frame."""
        if not self._track_ids:
            return
        self._cam_index = min(self._cam_index, len(self._track_ids) - 1)
        q = self.track_queues.get(self._track_ids[self._cam_index])
        if q is None:
            return
        try:
            self._on_frame(q.get_nowait())
        except queue.Empty:
            pass
