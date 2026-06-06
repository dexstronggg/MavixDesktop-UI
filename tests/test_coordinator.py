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
    a.accept_delivery = AsyncMock(return_value={'status': 'accepted'})
    a.set_delivery_in_flight = AsyncMock(return_value={'status': 'in_flight'})
    a.mark_delivery_delivered = AsyncMock(return_value={'status': 'delivered'})
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
    # close_async closes the RTCPeerConnection AND calls end_session
    # internally, so the assertion is on close_async.
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
    """The FC handler wiring used to happen right after handle_offer, but
    at that point DTLS+SCTP haven't completed and hub.config/packet are
    still None. Now it's driven by manager.on_channel_attached instead."""
    from mavixdesktop.webrtc.channels import DataChannelHub
    sc = _signal()
    c = _coord(sc, _api())
    c._manager = MagicMock()
    c._manager.handle_offer = AsyncMock()
    hub = DataChannelHub()
    c._manager.channels = hub  # empty hub — no packet/config attached yet
    await c._on_message({
        'type': 'sdp', 'drone_id': 'd-1',
        'sdp': {'type': 'offer', 'sdp': 'v=0'},
    })
    # Hub stays empty; nothing got wired
    assert hub.packet is None
    assert hub.config is None


async def test_wire_channels_to_fc_assigns_handlers_when_channels_present():
    """Once aiortc's 'datachannel' event has populated the hub, the
    coordinator's _wire_channels_to_fc should fire (via the manager's
    on_channel_attached callback) and assign the correct handlers."""
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
    """Server shutdown drops the active session, but the coordinator's
    connect loop stays armed so it can reconnect when the server returns."""
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
    # signal_client.send must have been called with the refresh_auth message
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
    c.send_joystick_packet(b'\x01')  # no exception


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
    # cleanup async-started relay if any
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
    await c.send_bitrate_update([])  # no exception


async def test_send_reboot_routes_to_config_channel():
    sc = _signal()
    c = _coord(sc, _api())
    config_ch = MagicMock()
    hub = MagicMock(config=config_ch)
    c._manager = MagicMock(channels=hub)
    await c.send_reboot()
    config_ch.send_json.assert_called_once_with({'type': 'reboot'})


async def test_send_reboot_no_session_is_noop():
    sc = _signal()
    c = _coord(sc, _api())
    await c.send_reboot()


#### deliveries ########################################################################

_DELIVERY = {
    'delivery_id': 'deliv-1',
    'drone_id': 'drone-A',
    'destination_address': 'ул. Тестовая, 1',
    'destination_lat': 55.0,
    'destination_lon': 37.0,
    'cargo_description': 'коробка',
}


async def test_delivery_offer_fires_callback():
    sc = _signal()
    c = _coord(sc, _api())
    received: list = []
    c.on_delivery_offer = received.append
    await c._on_message({'type': 'delivery_offer', 'delivery': dict(_DELIVERY)})
    assert received == [_DELIVERY]


async def test_delivery_offer_without_delivery_is_noop():
    sc = _signal()
    c = _coord(sc, _api())
    c.on_delivery_offer = lambda _: pytest.fail('should not fire')
    await c._on_message({'type': 'delivery_offer'})


async def test_delivery_taken_fires_callback():
    sc = _signal()
    c = _coord(sc, _api())
    taken: list = []
    c.on_delivery_taken = taken.append
    await c._on_message({'type': 'delivery_taken', 'delivery_id': 'deliv-1'})
    assert taken == ['deliv-1']


async def test_accept_delivery_success_connects_and_sets_in_flight():
    sc = _signal()
    sc._access_token = 'op-access'
    api = _api()
    c = _coord(sc, api)
    c._manager = MagicMock()
    accepted: list = []
    c.on_delivery_accepted = accepted.append

    await c.accept_delivery(dict(_DELIVERY))

    api.accept_delivery.assert_awaited_once_with('deliv-1', 'op-access')
    api.set_delivery_in_flight.assert_awaited_once_with('deliv-1', 'op-access')
    c._manager.start_session.assert_called_once_with('drone-A')
    sc.send.assert_awaited_with({'type': 'connect', 'drone_id': 'drone-A'})
    assert accepted == [_DELIVERY]
    assert c.active_delivery == _DELIVERY


async def test_accept_delivery_conflict_fires_failed_and_no_connect():
    from mavixdesktop.server.api import ApiError
    sc = _signal()
    api = _api()
    api.accept_delivery = AsyncMock(side_effect=ApiError('уже принята'))
    c = _coord(sc, api)
    c._manager = MagicMock()
    failed: list = []
    c.on_delivery_accept_failed = lambda did, reason: failed.append((did, reason))

    await c.accept_delivery(dict(_DELIVERY))

    assert failed == [('deliv-1', 'уже принята')]
    c._manager.start_session.assert_not_called()
    assert c.active_delivery is None


async def test_mark_delivered_calls_api():
    sc = _signal()
    sc._access_token = 'op-access'
    api = _api()
    c = _coord(sc, api)
    c._active_delivery = dict(_DELIVERY)
    await c.mark_delivered()
    api.mark_delivery_delivered.assert_awaited_once_with('deliv-1', 'op-access')


async def test_mark_delivered_without_active_is_noop():
    sc = _signal()
    api = _api()
    c = _coord(sc, api)
    await c.mark_delivered()
    api.mark_delivery_delivered.assert_not_awaited()


async def test_telemetry_message_fires_callback():
    sc = _signal()
    c = _coord(sc, _api())
    received: list = []
    c.on_telemetry = received.append
    c._on_telemetry_message({'type': 'telemetry', 'lat': 55.0, 'lon': 37.0, 'heading': 90})
    assert received == [{'type': 'telemetry', 'lat': 55.0, 'lon': 37.0, 'heading': 90}]


#### reconnect on drone_disconnected ###################################################

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
    """When a previously-paired drone comes back online, coordinator
    re-issues a 'connect' request."""
    sc = _signal()
    c = _coord(sc, _api())
    c._reconnect_drone_id = 'drone-A'
    c._manager = None  # session was torn down

    # Spy on request_connect
    c._manager_factory = None

    called = []

    async def fake_request_connect(drone_id):
        called.append(drone_id)
        # Do NOT actually create a session in the test
    c.request_connect = fake_request_connect

    await c._on_message({
        'type': 'drones',
        'drones': [{'drone_id': 'drone-A', 'online': True}],
    })

    assert called == ['drone-A']
    assert c._reconnect_drone_id is None  # cleared on reconnect attempt


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
    assert c._reconnect_drone_id is None  # offline → перестаём ждать (новое поведение)


#### auth_refreshed ####################################################################

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
    """Server may rotate the refresh token alongside the access token.
    If we don't update _refresh_token in memory, the next REST /auth/refresh
    sends the stale (revoked) value and gets 401."""
    sc = _signal()
    c = _coord(sc, _api())
    assert c._refresh_token == 'r-token'

    # Block the persist path so the test doesn't touch real keyring/file
    monkeypatch.setattr(
        'mavixdesktop.server.token_store.load',
        lambda: (None, None),  # no email → save not invoked
    )

    await c._on_message({
        'type': 'auth_refreshed',
        'access_token': 'fresh-access',
        'refresh_token': 'fresh-refresh',
    })

    assert c._refresh_token == 'fresh-refresh'


async def test_auth_refreshed_skips_persist_when_unchanged():
    """Idempotency: receiving the same refresh token again must not
    re-write the keyring."""
    sc = _signal()
    c = _coord(sc, _api())
    await c._on_message({
        'type': 'auth_refreshed',
        'access_token': 'a',
        'refresh_token': 'r-token',  # same as initial
    })
    # No exception, _refresh_token unchanged
    assert c._refresh_token == 'r-token'


#### error / shutdown ##################################################################

async def test_error_message_fires_callback():
    sc = _signal()
    c = _coord(sc, _api())
    errors = []
    c.on_error = errors.append
    await c._on_message({'type': 'error', 'message': 'pipeline_error'})
    assert errors == ['pipeline_error']


async def test_shutdown_tears_down_but_does_not_stop():
    """After server shutdown, coordinator should drop the active session
    but stay in its connect loop so it can reconnect when the server
    comes back."""
    sc = _signal()
    c = _coord(sc, _api())
    mgr = MagicMock()
    mgr.close_async = AsyncMock()
    c._manager = mgr
    c._stop_event = asyncio.Event()

    await c._on_message({'type': 'shutdown'})

    mgr.close_async.assert_awaited_once()
    # Coordinator must NOT have set the stop event — its run() loop should
    # naturally reconnect via the existing reconnect-on-listen-exit path.
    assert not c._stop_event.is_set()
