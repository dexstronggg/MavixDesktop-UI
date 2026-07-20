from __future__ import annotations

import asyncio
import contextlib
import json
from unittest.mock import AsyncMock, patch

import pytest
import websockets

from mavixdesktop.server.signal_client import SignalClient


async def test_connect_sends_auth_first_message():
    fake_conn = AsyncMock()
    with patch(
        'mavixdesktop.server.signal_client.ws_connect',
        AsyncMock(return_value=fake_conn),
    ):
        sc = SignalClient('ws://test', 'access-jwt')
        assert await sc.connect() is True
    fake_conn.send.assert_awaited_once()
    sent = fake_conn.send.await_args.args[0]
    assert json.loads(sent) == {'type': 'auth', 'token': 'access-jwt'}


async def test_connect_returns_false_on_oserror():
    with patch(
        'mavixdesktop.server.signal_client.ws_connect',
        AsyncMock(side_effect=OSError('refused')),
    ):
        sc = SignalClient('ws://test', 't')
        assert await sc.connect() is False


async def test_connect_returns_false_when_auth_send_fails():
    fake_conn = AsyncMock()
    fake_conn.send.side_effect = websockets.exceptions.ConnectionClosed(None, None)
    with patch(
        'mavixdesktop.server.signal_client.ws_connect',
        AsyncMock(return_value=fake_conn),
    ):
        sc = SignalClient('ws://test', 't')
        assert await sc.connect() is False


async def test_update_access_token():
    sc = SignalClient('ws://test', 'old')
    sc.update_access_token('new')
    assert sc._access_token == 'new'


async def test_send_raises_when_not_connected():
    sc = SignalClient('ws://test', 't')
    with pytest.raises(RuntimeError):
        await sc.send({'type': 'list_drones'})


async def test_listen_raises_when_not_connected():
    sc = SignalClient('ws://test', 't')
    with pytest.raises(RuntimeError):
        await sc.listen(AsyncMock())


async def test_disconnect_noop_when_not_connected():
    sc = SignalClient('ws://test', 't')
    await sc.disconnect()
    assert not sc.is_connected


class _Server:
    def __init__(self) -> None:
        self.auth_msg: dict | None = None
        self.received: list[dict] = []
        self.send_after_auth: list[dict] = []

    async def handler(self, ws) -> None:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            self.auth_msg = json.loads(raw)
            for outgoing in self.send_after_auth:
                await ws.send(json.dumps(outgoing))
            async for msg in ws:
                self.received.append(json.loads(msg))
        except (TimeoutError, websockets.exceptions.ConnectionClosed):
            return


async def test_full_lifecycle_against_real_server():
    srv = _Server()
    srv.send_after_auth = [{'type': 'drones', 'drones': []}]
    async with websockets.serve(srv.handler, 'localhost', 0) as server:
        port = server.sockets[0].getsockname()[1]
        sc = SignalClient(f'ws://localhost:{port}', 'jwt-abc')

        assert await sc.connect() is True
        await asyncio.sleep(0.05)
        assert srv.auth_msg == {'type': 'auth', 'token': 'jwt-abc'}

        await sc.send({'type': 'list_drones'})

        received: list[dict] = []

        async def collect(msg: dict) -> None:
            received.append(msg)
            await sc.disconnect()

        with contextlib.suppress(websockets.exceptions.ConnectionClosed):
            await asyncio.wait_for(sc.listen(collect), timeout=2.0)

        assert received == [{'type': 'drones', 'drones': []}]
        await asyncio.sleep(0.05)
        assert srv.received == [{'type': 'list_drones'}]


async def test_listen_skips_invalid_json():
    async def handler(ws) -> None:
        await ws.recv()
        await ws.send('not-json')
        await ws.send(json.dumps({'type': 'pong'}))
        await asyncio.sleep(0.05)

    async with websockets.serve(handler, 'localhost', 0) as server:
        port = server.sockets[0].getsockname()[1]
        sc = SignalClient(f'ws://localhost:{port}', 't')
        await sc.connect()

        received: list[dict] = []

        async def cb(msg: dict) -> None:
            received.append(msg)

        try:
            await asyncio.wait_for(sc.listen(cb), timeout=1.5)
        except (TimeoutError, websockets.exceptions.ConnectionClosed):
            pass
        finally:
            await sc.disconnect()

        assert received == [{'type': 'pong'}]
