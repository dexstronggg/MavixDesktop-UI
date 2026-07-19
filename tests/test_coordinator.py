from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from mavixdesktop.coordinator import SessionCoordinator


def _signal() -> MagicMock:
    sc = MagicMock()
    sc.connect = AsyncMock(return_value=True)
    sc.disconnect = AsyncMock()
    sc.send = AsyncMock()
    sc.listen = AsyncMock()
    sc.update_access_token = MagicMock()
    return sc


def _api() -> MagicMock:
    a = MagicMock()
    a.ice_servers = AsyncMock(return_value=[])
    a.refresh = AsyncMock(return_value={'access_token': 'new-access-jwt'})
    return a


def _coord(signal: MagicMock, api: MagicMock) -> SessionCoordinator:
    c = SessionCoordinator(signal_client=signal, api_session=api, refresh_token='r-token')
    c._loop = asyncio.get_running_loop()
    return c


async def test_request_drone_list_sends_message():
    sc = _signal()
    c = _coord(sc, _api())
    await c.request_drone_list()
    sc.send.assert_awaited_with({'type': 'list_drones'})


async def test_request_connect_starts_session():
    sc = _signal()
    c = _coord(sc, _api())
    c._manager = MagicMock()
    await c.request_connect('drone-A')
    c._manager.start_session.assert_called_once_with('drone-A')
    sc.send.assert_awaited_with({'type': 'connect', 'drone_id': 'drone-A'})


async def test_request_disconnect_no_target_is_noop():
    sc = _signal()
    c = _coord(sc, _api())
    await c.request_disconnect()
    sc.send.assert_not_awaited()


async def test_request_disconnect_sends_and_tears_down():
    sc = _signal()
    c = _coord(sc, _api())
    mgr = MagicMock()
    mgr.close_async = AsyncMock()
    c._manager = mgr
    c._target_drone_id = 'drone-A'
    await c.request_disconnect()
    sc.send.assert_awaited_with({'type': 'disconnect', 'drone_id': 'drone-A'})
    mgr.close_async.assert_awaited_once()


async def test_handle_drones_updates_list_and_callback():
    sc = _signal()
    c = _coord(sc, _api())
    received: list = []
    c.on_drones_changed = received.append

    await c._on_message({'type': 'drones', 'drones': [{'drone_id': 'a', 'online': True}]})
    assert c.drones == [{'drone_id': 'a', 'online': True}]
    assert received == [[{'drone_id': 'a', 'online': True}]]


async def test_handle_drones_skips_non_list():
    sc = _signal()
    c = _coord(sc, _api())
    await c._on_message({'type': 'drones', 'drones': 'not-a-list'})
    assert c.drones == []


async def test_handle_sdp_offer_routes_to_manager():
    sc = _signal()
    c = _coord(sc, _api())
    c._manager = MagicMock()
    c._manager.handle_offer = AsyncMock()
    c._manager.channels = None
    await c._on_message({
        'type': 'sdp', 'drone_id': 'd-1',
        'sdp': {'type': 'offer', 'sdp': 'v=0'},
    })
    c._manager.handle_offer.assert_awaited_once_with('d-1', {'type': 'offer', 'sdp': 'v=0'})


async def test_handle_sdp_offer_does_NOT_eagerly_wire_fc():
    from mavixdesktop.webrtc.channels import DataChannelHub
    sc = _signal()
    c = _coord(sc, _api())
    c._manager = MagicMock()
    c._manager.handle_offer = AsyncMock()
    hub = DataChannelHub()
    c._manager.channels = hub
    await c._on_message({
        'type': 'sdp', 'drone_id': 'd-1',
        'sdp': {'type': 'offer', 'sdp': 'v=0'},
    })
    assert hub.packet is None
    assert hub.config is None


async def test_wire_channels_to_fc_assigns_handlers_when_channels_present():
    sc = _signal()
    c = _coord(sc, _api())
    hub = MagicMock()
    hub.config = MagicMock()
    hub.packet = MagicMock()
    c._manager = MagicMock(channels=hub)

    c._wire_channels_to_fc()

    assert hub.config.on_message == c._on_config_message
    assert hub.packet.on_packet == c._on_packet_from_drone


async def test_handle_ice_routes_to_manager():
    sc = _signal()
    c = _coord(sc, _api())
    c._manager = MagicMock()
    c._manager.handle_ice = AsyncMock()
    await c._on_message({
        'type': 'ice', 'drone_id': 'd-1',
        'candidate': {'candidate': 'foo', 'sdpMLineIndex': 0},
    })
    c._manager.handle_ice.assert_awaited_once()


async def test_handle_ping_replies_pong():
    sc = _signal()
    c = _coord(sc, _api())
    await c._on_message({'type': 'ping'})
    sc.send.assert_awaited_with({'type': 'pong'})


async def test_handle_drone_disconnected_tears_down():
    sc = _signal()
    c = _coord(sc, _api())
    mgr = MagicMock()
    mgr.close_async = AsyncMock()
    c._manager = mgr
    await c._on_message({'type': 'drone_disconnected', 'drone_id': 'd-1'})
    mgr.close_async.assert_awaited_once()


async def test_handle_shutdown_tears_down_without_stopping_loop():
    sc = _signal()
    c = _coord(sc, _api())
    mgr = MagicMock()
    mgr.close_async = AsyncMock()
    c._manager = mgr
    c._stop_event = asyncio.Event()
    await c._on_message({'type': 'shutdown'})
    mgr.close_async.assert_awaited_once()
    assert not c._stop_event.is_set()


async def test_auth_warning_triggers_refresh():
    sc = _signal()
    api = _api()
    c = _coord(sc, api)
    await c._on_message({'type': 'auth_warning', 'seconds_left': 30})
    api.refresh.assert_awaited_once_with('r-token')
    refresh_msg = next(
        (call.args[0] for call in sc.send.await_args_list if call.args[0].get('type') == 'refresh_auth'),
        None,
    )
    assert refresh_msg is not None
    assert refresh_msg['refresh_token'] == 'r-token'
    sc.update_access_token.assert_called_once_with('new-access-jwt')


async def test_send_joystick_packet_when_no_session_is_noop():
    sc = _signal()
    c = _coord(sc, _api())
    c.send_joystick_packet(b'\x01')


async def test_send_joystick_packet_when_session_routes_to_packet_channel():
    sc = _signal()
    c = _coord(sc, _api())
    packet_mock = MagicMock()
    hub = MagicMock(packet=packet_mock, ping=None, config=None)
    c._manager = MagicMock(channels=hub)
    c.send_joystick_packet(b'\xAA\xBB')
    packet_mock.send_bytes.assert_called_once_with(b'\xAA\xBB')


async def test_qgc_packet_routes_to_data_channel():
    sc = _signal()
    c = _coord(sc, _api())
    packet_mock = MagicMock()
    hub = MagicMock(packet=packet_mock)
    c._manager = MagicMock(channels=hub)
    c._on_qgc_packet(b'\x11')
    packet_mock.send_bytes.assert_called_once_with(b'\x11')


async def test_drone_packet_to_mavlink_relay():
    sc = _signal()
    c = _coord(sc, _api())
    relay_mock = MagicMock()
    c._mavlink = relay_mock
    c._fc_kind = 'mavlink'
    c._on_packet_from_drone(b'\x22')
    relay_mock.send_to_qgc.assert_called_once_with(b'\x22')


async def test_drone_packet_when_not_mavlink_is_noop():
    sc = _signal()
    c = _coord(sc, _api())
    relay_mock = MagicMock()
    c._mavlink = relay_mock
    c._fc_kind = 'crsf'
    c._on_packet_from_drone(b'\x33')
    relay_mock.send_to_qgc.assert_not_called()


async def test_config_message_fc_change_calls_callback():
    sc = _signal()
    c = _coord(sc, _api())
    fired = []
    c.on_fc_changed = lambda k, n: fired.append((k, n))
    await c._on_config_message_async({'type': 'fc', 'kind': 'mavlink', 'name': 'ardupilot'})
    assert ('mavlink', 'ardupilot') in fired
    assert c.fc_kind == 'mavlink'
    if c._mavlink is not None:
        await c._mavlink.stop()


async def test_config_message_non_dict_ignored():
    sc = _signal()
    c = _coord(sc, _api())
    c.on_fc_changed = lambda *a: pytest.fail('should not fire')
    await c._on_config_message_async([1, 2, 3])


async def test_cameras_message_stores_list_and_fires_callback():
    sc = _signal()
    c = _coord(sc, _api())
    received: list = []
    c.on_cameras_received = received.append

    payload = {'type': 'cameras', 'cameras': [
        {'device_index': 0, 'name': 'cam0', 'bitrate_kbs': 1000},
        {'device_index': 1, 'name': 'cam1', 'bitrate_kbs': 800},
    ]}
    await c._on_config_message_async(payload)

    assert c.cameras == payload['cameras']
    assert received == [payload['cameras']]


async def test_cameras_message_with_non_list_ignored():
    sc = _signal()
    c = _coord(sc, _api())
    c.on_cameras_received = lambda _: pytest.fail('should not fire')
    await c._on_config_message_async({'type': 'cameras', 'cameras': 'oops'})
    assert c.cameras == []


async def test_send_bitrate_update_routes_to_config_channel():
    sc = _signal()
    c = _coord(sc, _api())
    config_ch = MagicMock()
    hub = MagicMock(config=config_ch)
    c._manager = MagicMock(channels=hub)
    await c.send_bitrate_update([{'device_index': 0, 'bitrate_kbs': 500}])
    config_ch.send_json.assert_called_once_with({
        'type': 'bitrate',
        'updates': [{'device_index': 0, 'bitrate_kbs': 500}],
    })


async def test_send_bitrate_update_no_session_is_noop():
    sc = _signal()
    c = _coord(sc, _api())
    await c.send_bitrate_update([])


async def test_drone_disconnected_remembers_target_for_reconnect():
    sc = _signal()
    c = _coord(sc, _api())
    mgr = MagicMock()
    mgr.close_async = AsyncMock()
    c._manager = mgr
    c._target_drone_id = 'drone-A'

    await c._on_message({'type': 'drone_disconnected', 'drone_id': 'drone-A'})

    assert c._reconnect_drone_id == 'drone-A'


async def test_drone_disconnected_for_other_drone_no_reconnect():
    sc = _signal()
    c = _coord(sc, _api())
    mgr = MagicMock()
    mgr.close_async = AsyncMock()
    c._manager = mgr
    c._target_drone_id = 'drone-A'

    await c._on_message({'type': 'drone_disconnected', 'drone_id': 'drone-B'})

    assert c._reconnect_drone_id is None


async def test_drones_event_auto_reconnects_after_disconnect():
    sc = _signal()
    c = _coord(sc, _api())
    c._reconnect_drone_id = 'drone-A'
    c._manager = None

    c._manager_factory = None
    original_request_connect = c.request_connect

    called = []

    async def fake_request_connect(drone_id):
        called.append(drone_id)
    c.request_connect = fake_request_connect

    await c._on_message({
        'type': 'drones',
        'drones': [{'drone_id': 'drone-A', 'online': True}],
    })

    assert called == ['drone-A']
    assert c._reconnect_drone_id is None


async def test_drones_event_does_not_reconnect_if_offline():
    sc = _signal()
    c = _coord(sc, _api())
    c._reconnect_drone_id = 'drone-A'
    c._manager = None
    called = []

    async def fake_request_connect(drone_id):
        called.append(drone_id)
    c.request_connect = fake_request_connect

    await c._on_message({
        'type': 'drones',
        'drones': [{'drone_id': 'drone-A', 'online': False}],
    })
    assert called == []
    assert c._reconnect_drone_id is None


async def test_auth_refreshed_updates_signal_client_token():
    sc = _signal()
    c = _coord(sc, _api())

    await c._on_message({
        'type': 'auth_refreshed',
        'access_token': 'fresh-jwt',
        'expires_at': '2030-01-01T00:00:00Z',
    })

    sc.update_access_token.assert_called_with('fresh-jwt')


async def test_auth_refreshed_without_token_is_noop():
    sc = _signal()
    c = _coord(sc, _api())
    await c._on_message({'type': 'auth_refreshed'})
    sc.update_access_token.assert_not_called()


async def test_auth_refreshed_rotates_in_memory_refresh_token(monkeypatch):
    sc = _signal()
    c = _coord(sc, _api())
    assert c._refresh_token == 'r-token'

    monkeypatch.setattr(
        'mavixdesktop.server.token_store.load',
        lambda: (None, None),
    )

    await c._on_message({
        'type': 'auth_refreshed',
        'access_token': 'fresh-access',
        'refresh_token': 'fresh-refresh',
    })

    assert c._refresh_token == 'fresh-refresh'


async def test_auth_refreshed_skips_persist_when_unchanged():
    sc = _signal()
    c = _coord(sc, _api())
    await c._on_message({
        'type': 'auth_refreshed',
        'access_token': 'a',
        'refresh_token': 'r-token',
    })
    assert c._refresh_token == 'r-token'


async def test_error_message_fires_callback():
    sc = _signal()
    c = _coord(sc, _api())
    errors = []
    c.on_error = errors.append
    await c._on_message({'type': 'error', 'message': 'pipeline_error'})
    assert errors == ['pipeline_error']


async def test_shutdown_tears_down_but_does_not_stop():
    sc = _signal()
    c = _coord(sc, _api())
    mgr = MagicMock()
    mgr.close_async = AsyncMock()
    c._manager = mgr
    c._stop_event = asyncio.Event()

    await c._on_message({'type': 'shutdown'})

    mgr.close_async.assert_awaited_once()
    assert not c._stop_event.is_set()
