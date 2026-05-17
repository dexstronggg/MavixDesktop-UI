from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from mavixdesktop.server.api import ApiError, ApiSession


class _FakeResponse:
    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self._payload = payload

    async def json(self) -> dict:
        return self._payload

    async def __aenter__(self) -> '_FakeResponse':
        return self

    async def __aexit__(self, *exc) -> None:
        return None


def _session_with(method: str, response: _FakeResponse) -> MagicMock:
    session = MagicMock()
    fn = MagicMock(return_value=response)
    setattr(session, method, fn)
    return session


async def test_health_returns_true_on_ok():
    session = _session_with('get', _FakeResponse(200, {'status': 'ok'}))
    api = ApiSession(session)
    assert await api.health() is True


async def test_health_returns_false_on_non_ok_status():
    session = _session_with('get', _FakeResponse(500, {}))
    api = ApiSession(session)
    assert await api.health() is False


async def test_health_returns_false_on_unexpected_payload():
    session = _session_with('get', _FakeResponse(200, {'status': 'broken'}))
    api = ApiSession(session)
    assert await api.health() is False


async def test_health_swallows_client_error():
    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError('refused'))
    api = ApiSession(session)
    assert await api.health() is False


async def test_login_returns_tokens():
    payload = {'access_token': 'a', 'refresh_token': 'r', 'token_type': 'bearer'}
    session = _session_with('post', _FakeResponse(200, payload))
    api = ApiSession(session)
    result = await api.login('a@b.c', 'pw')
    assert result == payload


async def test_login_raises_on_error():
    session = _session_with('post', _FakeResponse(401, {'detail': 'bad credentials'}))
    api = ApiSession(session)
    with pytest.raises(ApiError, match='bad credentials'):
        await api.login('a@b.c', 'wrong')


async def test_refresh_returns_new_access():
    session = _session_with('post', _FakeResponse(200, {'access_token': 'new'}))
    api = ApiSession(session)
    result = await api.refresh('r-token')
    assert result == {'access_token': 'new'}


async def test_refresh_raises_on_error():
    session = _session_with('post', _FakeResponse(401, {'detail': 'expired'}))
    api = ApiSession(session)
    with pytest.raises(ApiError, match='expired'):
        await api.refresh('r-token')


async def test_ice_servers_returns_list():
    payload = {'ice_servers': [{'urls': 'stun:s.example:3478'}]}
    session = _session_with('get', _FakeResponse(200, payload))
    api = ApiSession(session)
    servers = await api.ice_servers()
    assert servers == [{'urls': 'stun:s.example:3478'}]


async def test_ice_servers_returns_empty_on_error():
    session = _session_with('get', _FakeResponse(500, {}))
    api = ApiSession(session)
    assert await api.ice_servers() == []


async def test_ice_servers_swallows_client_error():
    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError('refused'))
    api = ApiSession(session)
    assert await api.ice_servers() == []


async def test_ice_servers_handles_non_list_payload():
    session = _session_with('get', _FakeResponse(200, {'ice_servers': None}))
    api = ApiSession(session)
    assert await api.ice_servers() == []
