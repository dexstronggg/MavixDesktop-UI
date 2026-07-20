"""End-to-end PeerSession test: real aiortc loopback drone<->gcs in-process. The 'drone' side here is a plain aiortc RTCPeerConnection that creates data channels and produces an offer; the GCS side is our PeerSession applying the offer and producing an answer."""
from __future__ import annotations

import asyncio

from aiortc import RTCPeerConnection, RTCSessionDescription

from mavixdesktop.webrtc.peer import (
    PeerSession,
    _build_configuration,
    _patch_dtls_setup_passive,
)


def test_build_configuration_no_servers():
    cfg = _build_configuration([])
    assert cfg.iceServers == []


def test_build_configuration_keeps_stun_when_relay_off(monkeypatch):
    from mavixdesktop.core.config import settings as s
    monkeypatch.setattr(s, 'force_relay', False, raising=False)
    cfg = _build_configuration([
        {'urls': 'stun:stun.example:3478'},
        {'urls': 'turn:turn.example:3478', 'username': 'a', 'credential': 'b'},
    ])
    assert len(cfg.iceServers) == 1
    assert cfg.iceServers[0].urls == 'stun:stun.example:3478'


def test_build_configuration_keeps_turn_when_relay_on(monkeypatch):
    from mavixdesktop.core.config import settings as s
    monkeypatch.setattr(s, 'force_relay', True, raising=False)
    cfg = _build_configuration([
        {'urls': 'stun:stun.example:3478'},
        {'urls': 'turn:turn.example:3478', 'username': 'alice', 'credential': 'secret'},
    ])
    assert len(cfg.iceServers) == 1
    assert cfg.iceServers[0].username == 'alice'
    assert cfg.iceServers[0].credential == 'secret'


def test_build_configuration_keeps_turns_when_relay_on(monkeypatch):
    from mavixdesktop.core.config import settings as s
    monkeypatch.setattr(s, 'force_relay', True, raising=False)
    cfg = _build_configuration([
        {'urls': 'stun:stun.example:3478'},
        {'urls': 'turns:turn.example:443', 'username': 'a', 'credential': 'b'},
    ])
    assert len(cfg.iceServers) == 1
    assert 'turns:' in (cfg.iceServers[0].urls if isinstance(cfg.iceServers[0].urls, str) else cfg.iceServers[0].urls[0])


def test_build_configuration_ignores_entries_without_urls(monkeypatch):
    from mavixdesktop.core.config import settings as s
    monkeypatch.setattr(s, 'force_relay', False, raising=False)
    cfg = _build_configuration([{'username': 'x'}, {'urls': 'stun:y:3478'}])
    assert len(cfg.iceServers) == 1


def test_patch_dtls_replaces_setup_active_line():
    sdp = (
        'v=0\r\n'
        'a=group:BUNDLE 0\r\n'
        'a=setup:active\r\n'
        'a=ice-ufrag:abc\r\n'
    )
    out = _patch_dtls_setup_passive(sdp)
    assert 'a=setup:passive\r\n' in out
    assert 'a=setup:active' not in out


def test_patch_dtls_replaces_every_occurrence():
    sdp = (
        'a=setup:active\r\n'
        'm=video 9 UDP/TLS/RTP/SAVPF 96\r\n'
        'a=setup:active\r\n'
        'm=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n'
        'a=setup:active\r\n'
    )
    out = _patch_dtls_setup_passive(sdp)
    assert out.count('a=setup:passive') == 3
    assert 'a=setup:active' not in out


def test_patch_dtls_handles_lf_only_newlines():
    sdp = 'a=setup:active\na=ice-ufrag:x\n'
    out = _patch_dtls_setup_passive(sdp)
    assert out == 'a=setup:passive\na=ice-ufrag:x\n'


def test_patch_dtls_does_not_touch_other_lines():
    sdp = (
        'v=0\r\n'
        'a=ice-options:trickle\r\n'
        'a=fingerprint:sha-256 AA:BB\r\n'
        'a=setup:active\r\n'
    )
    out = _patch_dtls_setup_passive(sdp)
    assert 'v=0\r\n' in out
    assert 'a=ice-options:trickle\r\n' in out
    assert 'a=fingerprint:sha-256 AA:BB\r\n' in out
    assert 'a=setup:passive\r\n' in out


def test_patch_dtls_does_not_touch_setup_passive_or_actpass():
    sdp = 'a=setup:passive\r\na=setup:actpass\r\n'
    out = _patch_dtls_setup_passive(sdp)
    assert out == sdp


def test_patch_dtls_does_not_match_attribute_substring():
    sdp = 'a=setup:active-but-not-really\r\na=setup:active\r\n'
    out = _patch_dtls_setup_passive(sdp)
    assert 'a=setup:active-but-not-really\r\n' in out
    assert 'a=setup:passive\r\n' in out


def test_patch_dtls_noop_on_empty_string():
    assert _patch_dtls_setup_passive('') == ''


async def test_apply_offer_produces_valid_answer():
    drone_pc = RTCPeerConnection()
    drone_pc.createDataChannel('packet-channel')
    drone_pc.createDataChannel('config-channel')

    offer = await drone_pc.createOffer()
    await drone_pc.setLocalDescription(offer)
    offer_sdp = drone_pc.localDescription.sdp

    peer = PeerSession('drone-loopback', ice_servers=[])
    try:
        answer_sdp = await peer.apply_offer(offer_sdp)
        assert isinstance(answer_sdp, str)
        assert answer_sdp.startswith('v=0')
        assert 'a=setup:passive' in answer_sdp
        assert 'a=setup:active' not in answer_sdp
    finally:
        await peer.close()
        await drone_pc.close()


async def test_datachannel_callback_fires_on_drone_open(monkeypatch):
    monkeypatch.setattr(
        'mavixdesktop.webrtc.peer._patch_dtls_setup_passive', lambda s: s
    )
    drone_pc = RTCPeerConnection()
    drone_pc.createDataChannel('packet-channel')

    received_labels: list[str] = []
    peer = PeerSession('drone-loopback', ice_servers=[])
    peer.on_datachannel = lambda ch: received_labels.append(ch.label)

    try:
        offer = await drone_pc.createOffer()
        await drone_pc.setLocalDescription(offer)
        answer_sdp = await peer.apply_offer(drone_pc.localDescription.sdp)
        await drone_pc.setRemoteDescription(RTCSessionDescription(sdp=answer_sdp, type='answer'))

        for _ in range(50):
            if received_labels:
                break
            await asyncio.sleep(0.05)
        assert 'packet-channel' in received_labels
    finally:
        await peer.close()
        await drone_pc.close()


async def test_add_remote_ice_invalid_payload_returns_false():
    peer = PeerSession('drone', ice_servers=[])
    try:
        ok = await peer.add_remote_ice({'sdpMLineIndex': 0})
        assert ok is False
    finally:
        await peer.close()


async def test_close_is_idempotent_ish():
    peer = PeerSession('drone', ice_servers=[])
    await peer.close()
    await peer.close()
