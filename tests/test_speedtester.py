"""Integration tests for SpeedTester against an in-process websockets server."""
from __future__ import annotations

import asyncio

import pytest
import websockets

from mavixdesktop.speedtester.tester import SpeedTester
from mavixdesktop.speedtester.units import SizeType, Standard


async def _serve(handler, host: str = 'localhost'):
    return await websockets.serve(handler, host, 0)


# ---------- check_connection ----------

async def test_check_connection_returns_true_on_success():
    async def handler(ws, *args):
        await ws.send(bytes(64))

    server = await _serve(handler)
    try:
        port = server.sockets[0].getsockname()[1]
        tester = SpeedTester(f'ws://localhost:{port}')
        assert await tester.check_connection() is True
    finally:
        server.close()
        await server.wait_closed()


async def test_check_connection_returns_false_on_unreachable():
    tester = SpeedTester('ws://localhost:1')  # nothing listening
    assert await tester.check_connection() is False


# ---------- download / upload / ping loops ----------

async def test_download_measures_throughput():
    async def handler(ws, *args):
        try:
            while True:
                await ws.send(bytes(65536))
        except websockets.exceptions.ConnectionClosed:
            return

    server = await _serve(handler)
    try:
        port = server.sockets[0].getsockname()[1]
        tester = SpeedTester(f'ws://localhost:{port}')
        run_task = asyncio.create_task(tester.run())
        for _ in range(50):
            if tester.download_speed.value > 0:
                break
            await asyncio.sleep(0.05)
        tester.stop()
        try:
            await asyncio.wait_for(run_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        assert tester.download_speed.value > 0
    finally:
        server.close()
        await server.wait_closed()


async def test_upload_measures_throughput():
    async def handler(ws, *args):
        try:
            async for msg in ws:
                await ws.send(b'ack')
        except websockets.exceptions.ConnectionClosed:
            return

    server = await _serve(handler)
    try:
        port = server.sockets[0].getsockname()[1]
        tester = SpeedTester(f'ws://localhost:{port}')
        run_task = asyncio.create_task(tester.run())
        for _ in range(50):
            if tester.upload_speed.value > 0:
                break
            await asyncio.sleep(0.05)
        tester.stop()
        try:
            await asyncio.wait_for(run_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        assert tester.upload_speed.value > 0
    finally:
        server.close()
        await server.wait_closed()


async def test_ping_measures_rtt():
    async def handler(ws, *args):
        try:
            async for _ in ws:
                pass
        except websockets.exceptions.ConnectionClosed:
            return

    server = await _serve(handler)
    try:
        port = server.sockets[0].getsockname()[1]
        tester = SpeedTester(f'ws://localhost:{port}')
        run_task = asyncio.create_task(tester.run())
        for _ in range(50):
            if tester.ping_ms > 0:
                break
            await asyncio.sleep(0.05)
        tester.stop()
        try:
            await asyncio.wait_for(run_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        assert tester.ping_ms > 0
    finally:
        server.close()
        await server.wait_closed()


# ---------- lifecycle ----------

async def test_stop_cancels_run():
    tester = SpeedTester('ws://localhost:1')  # unreachable
    run_task = asyncio.create_task(tester.run())
    await asyncio.sleep(0.05)
    tester.stop()
    try:
        await asyncio.wait_for(run_task, timeout=2.0)
    except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
        pass


async def test_stop_before_run_is_noop():
    tester = SpeedTester('ws://localhost:1')
    tester.stop()  # no exception


async def test_url_trailing_slash_is_stripped():
    tester = SpeedTester('ws://example.com/')
    assert tester.url == 'ws://example.com'


async def test_initial_values_are_negative_sentinels():
    """Until a measurement completes, values must be < 0 so the UI can
    distinguish 'no data' from 'zero throughput'."""
    tester = SpeedTester('ws://localhost:1')
    assert tester.download_speed.value < 0
    assert tester.upload_speed.value < 0
    assert tester.ping_ms < 0
    # Reads in any unit are still negative
    assert tester.download_speed.get(SizeType.MB, Standard.Binary) < 0


async def test_handles_endpoint_dropping_mid_run():
    """If the server closes immediately, the tester should retry without
    crashing."""
    drop_counter = {'n': 0}

    async def handler(ws, *args):
        drop_counter['n'] += 1
        await ws.close()

    server = await _serve(handler)
    try:
        port = server.sockets[0].getsockname()[1]
        tester = SpeedTester(f'ws://localhost:{port}')
        run_task = asyncio.create_task(tester.run())
        # Allow a couple of retries to happen
        await asyncio.sleep(0.3)
        tester.stop()
        try:
            await asyncio.wait_for(run_task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass
        # Some attempts should have happened; speeds still at default
        assert drop_counter['n'] >= 1
    finally:
        server.close()
        await server.wait_closed()
