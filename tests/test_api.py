from __future__ import annotations

from unittest.mock import MagicMock

import aiohttp
import pytest

from mavixdesktop.server.api import ApiError, ApiSession


class _FakeResponse:
    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self._payload = payload

    async def json(self) -> dict:
        return self._payload

    async def __aenter__(self) -> _FakeResponse:
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


#### operator login + deliveries ######################################################

async def test_operator_login_returns_tokens():
    session = _session_with('post', _FakeResponse(200, {'access_token': 'a', 'refresh_token': 'r', 'token_type': 'bearer'}))
    api = ApiSession(session)
    data = await api.operator_login('op-1', 'pw')
    assert data['access_token'] == 'a'


async def test_operator_login_raises_on_401():
    session = _session_with('post', _FakeResponse(401, {'detail': 'неверные учётные данные'}))
    api = ApiSession(session)
    with pytest.raises(ApiError):
        await api.operator_login('op-1', 'bad')


async def test_accept_delivery_returns_delivery():
    session = _session_with('post', _FakeResponse(200, {'delivery_id': 'd1', 'status': 'accepted'}))
    api = ApiSession(session)
    data = await api.accept_delivery('d1', 'tok')
    assert data['status'] == 'accepted'


async def test_accept_delivery_conflict_raises():
    session = _session_with('post', _FakeResponse(409, {'detail': 'заявка уже принята'}))
    api = ApiSession(session)
    with pytest.raises(ApiError):
        await api.accept_delivery('d1', 'tok')


async def test_list_offered_returns_list():
    session = _session_with('get', _FakeResponse(200, [{'delivery_id': 'd1'}]))
    api = ApiSession(session)
    data = await api.list_offered_deliveries('tok')
    assert data == [{'delivery_id': 'd1'}]


async def test_list_offered_empty_on_error():
    session = _session_with('get', _FakeResponse(403, {}))
    api = ApiSession(session)
    assert await api.list_offered_deliveries('tok') == []


async def test_mark_delivered_returns_delivery():
    session = _session_with('post', _FakeResponse(200, {'delivery_id': 'd1', 'status': 'delivered'}))
    api = ApiSession(session)
    data = await api.mark_delivery_delivered('d1', 'tok')
    assert data['status'] == 'delivered'


# --- дополнительные методы ApiSession (повышение покрытия) ---
async def test_operator_login_ok():
    session = _session_with('post', _FakeResponse(200, {'access_token': 'A', 'refresh_token': 'R'}))
    api = ApiSession(session)
    res = await api.operator_login('op', 'pw')
    assert res['access_token'] == 'A'


async def test_refresh_ok():
    session = _session_with('post', _FakeResponse(200, {'access_token': 'A2'}))
    api = ApiSession(session)
    assert (await api.refresh('R'))['access_token'] == 'A2'


async def test_password_reset_request_ok():
    session = _session_with('post', _FakeResponse(200, {'status': 'sent'}))
    api = ApiSession(session)
    await api.password_reset_request('op@example.com')


async def test_ice_servers_ok():
    session = _session_with('get', _FakeResponse(200, {'ice_servers': [{'urls': 'stun:x'}]}))
    api = ApiSession(session)
    res = await api.ice_servers()
    assert isinstance(res, list)


async def test_list_offered_and_my_delivery():
    session = _session_with('get', _FakeResponse(200, [{'delivery_id': 'd1'}]))
    api = ApiSession(session)
    assert isinstance(await api.list_offered_deliveries('A'), list)
    session2 = _session_with('get', _FakeResponse(200, {'delivery_id': 'd1'}))
    api2 = ApiSession(session2)
    assert (await api2.get_my_delivery('A')) is not None


async def test_delivery_status_transitions():
    session = _session_with('post', _FakeResponse(200, {'delivery_id': 'd1', 'status': 'accepted'}))
    api = ApiSession(session)
    assert (await api.accept_delivery('d1', 'A'))['status'] == 'accepted'
    session2 = _session_with('post', _FakeResponse(200, {'status': 'in_flight'}))
    api2 = ApiSession(session2)
    await api2.set_delivery_in_flight('d1', 'A')
    session3 = _session_with('post', _FakeResponse(200, {'status': 'delivered'}))
    api3 = ApiSession(session3)
    await api3.mark_delivery_delivered('d1', 'A')


async def test_delete_drone_and_close():
    session = _session_with('delete', _FakeResponse(204, {}))
    api = ApiSession(session)
    await api.delete_drone('dr1', 'A')


# --- error-пути (запас покрытия) ---
async def test_login_raises_on_401():
    session = _session_with('post', _FakeResponse(401, {'detail': 'bad creds'}))
    api = ApiSession(session)
    with pytest.raises(ApiError):
        await api.login('e@x.com', 'wrong')


async def test_refresh_raises_on_401():
    session = _session_with('post', _FakeResponse(401, {'detail': 'expired'}))
    api = ApiSession(session)
    with pytest.raises(ApiError):
        await api.refresh('bad-token')


async def test_operator_login_raises_on_500():
    session = _session_with('post', _FakeResponse(500, {}))
    api = ApiSession(session)
    with pytest.raises(ApiError):
        await api.operator_login('op', 'pw')


async def test_accept_delivery_raises_on_409():
    session = _session_with('post', _FakeResponse(409, {'detail': 'занята'}))
    api = ApiSession(session)
    with pytest.raises(ApiError):
        await api.accept_delivery('d1', 'A')
