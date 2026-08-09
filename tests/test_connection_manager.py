"""ConnectionManager: завершение сессии при выходе из учётной записи."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from mavixdesktop.ui.managers.connection import ConnectionManager


async def test_shutdown_cancels_coordinator_that_ignores_stop():
    """Зависший координатор должен быть отменён, иначе после logout живут две сессии."""
    manager = ConnectionManager(bridge=MagicMock())
    started = asyncio.Event()

    async def never_finishes() -> None:
        started.set()
        await asyncio.sleep(3600)

    task = asyncio.create_task(never_finishes())
    await started.wait()
    manager._coord_task = task

    await manager._shutdown_coordinator()

    assert task.cancelled() or task.done()
    assert manager._coord_task is None


async def test_shutdown_awaits_coordinator_that_stops_on_its_own():
    manager = ConnectionManager(bridge=MagicMock())
    coord = MagicMock()
    finished = asyncio.Event()

    async def stops_quickly() -> None:
        await finished.wait()

    task = asyncio.create_task(stops_quickly())
    manager._coord = coord
    manager._coord_task = task
    coord.stop.side_effect = finished.set

    await manager._shutdown_coordinator()

    coord.stop.assert_called_once()
    assert task.done() and not task.cancelled()
    assert manager._coord_task is None
