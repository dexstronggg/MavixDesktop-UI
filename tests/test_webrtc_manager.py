from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from mavixdesktop.webrtc.manager import WebRTCManager


def _build_peer_mock() -> MagicMock:
    peer = MagicMock()
    peer.drone_id = 'drone-1'
    peer.apply_offer = AsyncMock(return_value='v=0\\r\\n...answer...')
    peer.add_remote_ice = AsyncMock(return_value=True)
    peer.close = AsyncMock()
    return peer


async def test_start_session_sets_active_drone(monkeypatch):
    monkeypatch.setattr(
        'mavixdesktop.webrtc.manager.PeerSession',
        lambda drone_id, ice_servers=None: _build_peer_mock(),
    )
    mgr = WebRTCManager(send=AsyncMock())
    mgr.start_session('drone-1')
    assert mgr.active_drone_id == 'drone-1'
    assert mgr.channels is not None


async def test_start_session_replaces_existing(monkeypatch):
    monkeypatch.setattr(
        'mavixdesktop.webrtc.manager.PeerSession',
        lambda drone_id, ice_servers=None: _build_peer_mock(),
    )
    mgr = WebRTCManager(send=AsyncMock())
    mgr.start_session('drone-1')
    mgr.start_session('drone-2')
    assert mgr.active_drone_id is not None


async def test_end_session_clears():
    mgr = WebRTCManager(send=AsyncMock())
    mgr.end_session()
    assert mgr.active_drone_id is None


async def test_end_session_fires_callback(monkeypatch):
    monkeypatch.setattr(
        'mavixdesktop.webrtc.manager.PeerSession',
        lambda drone_id, ice_servers=None: _build_peer_mock(),
    )
    mgr = WebRTCManager(send=AsyncMock())
    fired = []
    mgr.on_session_ended = lambda: fired.append(True)
    mgr.start_session('drone-1')
    mgr.end_session()
    assert fired == [True]


async def test_handle_offer_routes_to_peer_and_sends_answer(monkeypatch):
    peer = _build_peer_mock()
    monkeypatch.setattr(
        'mavixdesktop.webrtc.manager.PeerSession',
        lambda drone_id, ice_servers=None: peer,
    )
    send = AsyncMock()
    mgr = WebRTCManager(send=send)
    mgr.start_session('drone-1')

    await mgr.handle_offer('drone-1', {'type': 'offer', 'sdp': 'v=0\\r\\n...'})

    peer.apply_offer.assert_awaited_once_with('v=0\\r\\n...')
    send.assert_awaited_once()
    sent = send.await_args.args[0]
    assert sent['type'] == 'sdp'
    assert sent['drone_id'] == 'drone-1'
    assert sent['sdp']['type'] == 'answer'


async def test_handle_offer_wrong_drone_id_ignored(monkeypatch):
    peer = _build_peer_mock()
    monkeypatch.setattr(
        'mavixdesktop.webrtc.manager.PeerSession',
        lambda drone_id, ice_servers=None: peer,
    )
    send = AsyncMock()
    mgr = WebRTCManager(send=send)
    mgr.start_session('drone-1')

    await mgr.handle_offer('drone-other', {'type': 'offer', 'sdp': 'v=0'})
    peer.apply_offer.assert_not_awaited()
    send.assert_not_awaited()


async def test_handle_offer_without_session_ignored(monkeypatch):
    send = AsyncMock()
    mgr = WebRTCManager(send=send)
    await mgr.handle_offer('drone-1', {'type': 'offer', 'sdp': 'v=0'})
    send.assert_not_awaited()


async def test_handle_offer_missing_sdp_text_ignored(monkeypatch):
    peer = _build_peer_mock()
    monkeypatch.setattr(
        'mavixdesktop.webrtc.manager.PeerSession',
        lambda drone_id, ice_servers=None: peer,
    )
    send = AsyncMock()
    mgr = WebRTCManager(send=send)
    mgr.start_session('drone-1')
    await mgr.handle_offer('drone-1', {'type': 'offer'})
    peer.apply_offer.assert_not_awaited()
    send.assert_not_awaited()


async def test_handle_ice_routes_to_peer(monkeypatch):
    peer = _build_peer_mock()
    monkeypatch.setattr(
        'mavixdesktop.webrtc.manager.PeerSession',
        lambda drone_id, ice_servers=None: peer,
    )
    mgr = WebRTCManager(send=AsyncMock())
    mgr.start_session('drone-1')

    await mgr.handle_ice('drone-1', {'candidate': 'foo', 'sdpMLineIndex': 0})
    peer.add_remote_ice.assert_awaited_once()


async def test_update_ice_servers_replaces_list():
    mgr = WebRTCManager(send=AsyncMock())
    mgr.update_ice_servers([{'urls': 'stun:a.b:3478'}])
    assert mgr._ice_servers == [{'urls': 'stun:a.b:3478'}]


async def test_close_async_closes_peer_and_session(monkeypatch):
    peer = _build_peer_mock()
    monkeypatch.setattr(
        'mavixdesktop.webrtc.manager.PeerSession',
        lambda drone_id, ice_servers=None: peer,
    )
    mgr = WebRTCManager(send=AsyncMock())
    mgr.start_session('drone-1')
    await mgr.close_async()
    peer.close.assert_awaited_once()
    assert mgr.active_drone_id is None


async def test_handle_datachannel_attaches_and_fires_callback(monkeypatch):
    peer = _build_peer_mock()
    monkeypatch.setattr(
        'mavixdesktop.webrtc.manager.PeerSession',
        lambda drone_id, ice_servers=None: peer,
    )
    mgr = WebRTCManager(send=AsyncMock())
    mgr.start_session('drone-1')

    seen_labels: list[str] = []
    mgr.on_channel_attached = lambda label: seen_labels.append(label)

    ch = MagicMock()
    ch.label = 'packet-channel'
    ch.on = MagicMock()
    mgr._handle_datachannel(ch)

    assert mgr.channels.packet is not None
    assert seen_labels == ['packet-channel']


async def test_handle_datachannel_skips_callback_when_attach_rejects(monkeypatch):
    peer = _build_peer_mock()
    monkeypatch.setattr(
        'mavixdesktop.webrtc.manager.PeerSession',
        lambda drone_id, ice_servers=None: peer,
    )
    mgr = WebRTCManager(send=AsyncMock())
    mgr.start_session('drone-1')

    seen: list[str] = []
    mgr.on_channel_attached = lambda label: seen.append(label)

    ch = MagicMock()
    ch.label = 'unknown-channel-label'
    ch.on = MagicMock()
    mgr._handle_datachannel(ch)

    assert seen == []


async def test_handle_datachannel_swallows_callback_exception(monkeypatch):
    peer = _build_peer_mock()
    monkeypatch.setattr(
        'mavixdesktop.webrtc.manager.PeerSession',
        lambda drone_id, ice_servers=None: peer,
    )
    mgr = WebRTCManager(send=AsyncMock())
    mgr.start_session('drone-1')

    def boom(_label):
        raise RuntimeError('coordinator bug')

    mgr.on_channel_attached = boom

    ch = MagicMock()
    ch.label = 'packet-channel'
    ch.on = MagicMock()
    mgr._handle_datachannel(ch)
    assert mgr.channels.packet is not None
