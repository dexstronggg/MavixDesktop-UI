"""GCS-side WebRTC peer session.

The desktop is the answerer in this signalling exchange: the drone sends
an SDP offer (containing the media tracks and pre-negotiated data-channel
descriptors), we set it as remote, create an answer, set it as local,
and send the answer back to the signal server.

The drone *creates* the data-channels (packet / ping / config); we receive
them via the pc.on('datachannel') event, so unlike MavixBoard's peer we
don't emit anything ourselves.
"""
from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription

from mavixdesktop.core.config import settings
from mavixdesktop.core.logger import logger

if TYPE_CHECKING:
    from aiortc import MediaStreamTrack, RTCDataChannel

TrackHandler = Callable[['MediaStreamTrack'], None]
DataChannelHandler = Callable[['RTCDataChannel'], None]


def _patch_dtls_setup_passive(sdp: str) -> str:
    """Rewrite every `a=setup:active` line in an SDP to `a=setup:passive`.

    Required for compatibility with the GStreamer `webrtcbin` drone side
    (see PeerSession.apply_offer for the full rationale).
    """
    out_lines: list[str] = []
    for line in sdp.splitlines(keepends=True):
        stripped = line.rstrip('\r\n')
        if stripped == 'a=setup:active':
            ending = line[len(stripped):]
            out_lines.append('a=setup:passive' + ending)
        else:
            out_lines.append(line)
    return ''.join(out_lines)


_CAND_RE = re.compile(r'^a=candidate:.* typ (\w+) ', re.MULTILINE)


def _log_candidates(label: str, sdp: str) -> None:
    """Log every ICE candidate line by type. Used to see what aiortc
    actually gathered / what the drone offered."""
    by_type: dict[str, list[str]] = {}
    for line in sdp.splitlines():
        if not line.startswith('a=candidate:'):
            continue
        m = _CAND_RE.match(line)
        if not m:
            continue
        by_type.setdefault(m.group(1), []).append(line)
    if not by_type:
        logger.info('[ice/%s] no candidates in SDP', label)
        return
    for typ, lines in by_type.items():
        logger.info('[ice/%s] %s x%d', label, typ, len(lines))
        for cand in lines:
            logger.info('[ice/%s]   %s', label, cand.strip())


def _filter_to_relay_only(sdp: str, label: str) -> str:
    """Drop every non-relay candidate from SDP. Used when settings.force_relay
    is True to simulate a network where host/srflx paths are blocked
    (e.g. corporate/university firewalls). Useful for reproducing failed
    connections locally without travelling to that network.

    Keep `a=end-of-candidates` and everything else verbatim."""
    kept = 0
    dropped = 0
    out_lines: list[str] = []
    for line in sdp.splitlines(keepends=True):
        if line.startswith('a=candidate:'):
            m = _CAND_RE.match(line)
            if m and m.group(1) != 'relay':
                dropped += 1
                continue
            kept += 1
        out_lines.append(line)
    if kept or dropped:
        logger.info('[ice/%s] force_relay filter: kept %d relay, dropped %d non-relay',
                    label, kept, dropped)
    return ''.join(out_lines)


def _entry_scheme(entry: dict) -> str:
    """Возвращает scheme первого URL в записи RTCIceServer (stun/stuns/turn/turns/'')."""
    urls = entry.get('urls') if isinstance(entry, dict) else None
    if not urls:
        return ''
    url = urls if isinstance(urls, str) else (urls[0] if urls else '')
    if not isinstance(url, str) or ':' not in url:
        return ''
    return url.split(':', 1)[0].strip().lower()


def _build_configuration(ice_servers: list[dict]) -> RTCConfiguration:
    """Фильтрует ICE-серверы под текущий режим force_relay и собирает RTCConfiguration.

    Почему фильтр в принципе нужен: aiortc держит ровно один STUN и ровно
    один TURN сервер (rtcicetransport.py: второй URL c тем же scheme молча
    отбрасывается). При force_relay нам нужен ТОЛЬКО TURN — STUN-запись
    может «занять слот» и заодно сбивает iceTransportPolicy='relay',
    добавляя на сторону переговоров лишние srflx-кандидаты. При выключенном
    force_relay, наоборот, TURN-запись не нужна: всё равно политика 'all'
    предпочтёт прямую пару, а лишний TURN-сервер только удлиняет gathering."""
    use_relay = bool(getattr(settings, 'force_relay', False))
    mode = 'RELAY (TURN only)' if use_relay else 'DIRECT (STUN only)'
    logger.info('[ice/config] mode=%s, force_relay=%s, received %d ICE server(s)',
                mode, use_relay, len(ice_servers))
    servers: list[RTCIceServer] = []
    for entry in ice_servers:
        urls = entry.get('urls') if isinstance(entry, dict) else None
        if not urls:
            continue
        scheme = _entry_scheme(entry)
        is_turn = scheme in ('turn', 'turns')
        is_stun = scheme in ('stun', 'stuns')
        if use_relay and not is_turn:
            logger.info('[ice/config] skip non-TURN (%s) — force_relay is on', urls)
            continue
        if not use_relay and not is_stun:
            logger.info('[ice/config] skip non-STUN (%s) — force_relay is off', urls)
            continue
        username = entry.get('username')
        credential = entry.get('credential')
        kwargs: dict = {'urls': urls}
        if username:
            kwargs['username'] = username
        if credential:
            kwargs['credential'] = credential
        servers.append(RTCIceServer(**kwargs))
        logger.info('[ice/config] USING %s: urls=%s username=%s',
                    scheme.upper(), urls, bool(username))
    if not servers:
        logger.warning('[ice/config] no ICE servers left after filtering — '
                       'connection will likely fail. Check local STUN/TURN config '
                       '(or /api/v1/ice-servers) and force_relay setting (current: %s).', use_relay)
    # aiortc has no iceTransportPolicy on RTCConfiguration, so force relay
    # natively at the aioice layer (see relay_patch). The hook self-gates on
    # settings.force_relay + TURN presence per connection; installing it is
    # cheap and idempotent.
    from mavixdesktop.webrtc.relay_patch import enable_relay_only
    enable_relay_only()
    if use_relay and not servers:
        logger.warning('[ice/config] force_relay requested but no TURN server — '
                       'relay path cannot be used')
    logger.info('[ice/config] transport policy=%s (native via aioice)',
                'relay' if (use_relay and servers) else 'all')
    return RTCConfiguration(iceServers=servers)


class PeerSession:
    """One active WebRTC session with one drone. Created on 'connect'
    coming back from the server, destroyed when the GCS or the drone
    drops the pair."""

    def __init__(
        self,
        drone_id: str,
        ice_servers: list[dict] | None = None,
        pc: RTCPeerConnection | None = None,
    ) -> None:
        self.drone_id = drone_id
        self._pc = pc if pc is not None else RTCPeerConnection(
            _build_configuration(ice_servers or [])
        )
        self.on_track: TrackHandler | None = None
        self.on_datachannel: DataChannelHandler | None = None

        self._pc.add_listener('track', self._handle_track)
        self._pc.add_listener('datachannel', self._handle_datachannel)
        self._pc.add_listener('iceconnectionstatechange', self._handle_ice_state)
        self._pc.add_listener('icegatheringstatechange', self._handle_gather_state)
        self._pc.add_listener('connectionstatechange', self._handle_conn_state)

    @property
    def pc(self) -> RTCPeerConnection:
        return self._pc

    @property
    def connection_state(self) -> str:
        return self._pc.connectionState

    async def apply_offer(self, sdp_text: str) -> str:
        """Set the drone's offer as remote, build answer, return its sdp.

        NOTE: the returned SDP has every `a=setup:active` rewritten to
        `a=setup:passive`. This is load-bearing: the drone uses
        GStreamer `webrtcbin`, which always wants to be the DTLS client
        (`a=setup:active`). aiortc, by default, also returns
        `a=setup:active` here. With both sides claiming active, the DTLS
        handshake never completes — symptom on the drone side is
        "Fatal SSL error" / stuck DTLS. Forcing the GCS answer to
        passive makes aiortc the DTLS server and unblocks negotiation.
        Removing this rewrite breaks every session.
        """
        logger.info('[peer] offer m-lines: %s',
                    [l for l in sdp_text.splitlines() if l.startswith('m=')])

        # 1. Log incoming candidates from the drone.
        _log_candidates('offer/drone', sdp_text)

        # 2. Optional: simulate corporate NAT — drop host/srflx from the
        # drone's offer so only its relay candidates remain. Effectively
        # forces relay-relay path.
        if getattr(settings, 'force_relay', False):
            sdp_text = _filter_to_relay_only(sdp_text, 'offer/drone')

        await self._pc.setRemoteDescription(
            RTCSessionDescription(sdp=sdp_text, type='offer')
        )
        answer = await self._pc.createAnswer()
        patched_answer = RTCSessionDescription(
            sdp=_patch_dtls_setup_passive(answer.sdp),
            type=answer.type,
        )
        await self._pc.setLocalDescription(patched_answer)
        assert self._pc.localDescription is not None
        final_sdp = _patch_dtls_setup_passive(self._pc.localDescription.sdp)

        # 3. Log our own gathered candidates.
        _log_candidates('answer/gcs', final_sdp)

        # 4. Same filter on our side if force_relay enabled.
        if getattr(settings, 'force_relay', False):
            final_sdp = _filter_to_relay_only(final_sdp, 'answer/gcs')

        logger.info('[peer] answer m-lines: %s',
                    [l for l in final_sdp.splitlines() if l.startswith('m=')])
        return final_sdp

    async def add_remote_ice(self, candidate: dict) -> bool:
        """Apply a single ICE candidate received from the signal server.

        aiortc embeds candidates in the SDP, so most real drones won't trickle.
        This is provided for compatibility when the other side does trickle.
        """
        try:
            from aiortc import RTCIceCandidate
            cand_str = candidate.get('candidate')
            sdp_mid = candidate.get('sdpMid')
            sdp_mline_index = candidate.get('sdpMLineIndex')
            if not isinstance(cand_str, str):
                logger.warning('[peer] invalid ICE payload: %s', candidate)
                return False
            # При force-relay режиме отбрасываем не-relay кандидаты,
            # пришедшие через trickle.
            if getattr(settings, 'force_relay', False) and ' typ ' in cand_str:
                typ = cand_str.split(' typ ', 1)[1].split(' ', 1)[0]
                if typ != 'relay':
                    logger.info('[ice/trickle] dropped non-relay candidate: %s', cand_str)
                    return False
            # Парсим тип кандидата из строки — без этого все trickle-кандидаты
            # помечались как 'host', что ломало приоритеты ICE и могло
            # привести к выбору нерабочей пары за симметричным NAT.
            cand_type = 'host'
            cand_protocol = 'udp'
            if ' typ ' in cand_str:
                cand_type = cand_str.split(' typ ', 1)[1].split(' ', 1)[0]
            parts = cand_str.split()
            if len(parts) >= 7:
                cand_protocol = parts[2].lower()
            logger.info('[ice/trickle] add candidate type=%s proto=%s', cand_type, cand_protocol)
            ice = RTCIceCandidate(
                component=1,
                foundation='',
                ip='',
                port=0,
                priority=0,
                protocol=cand_protocol,
                type=cand_type,
                sdpMid=sdp_mid,
                sdpMLineIndex=sdp_mline_index,
            )
            ice.candidate = cand_str
            await self._pc.addIceCandidate(ice)
            return True
        except Exception as exc:
            logger.warning('[peer] add_remote_ice error: %s', exc)
            return False

    async def close(self) -> None:
        try:
            await self._pc.close()
        except Exception as exc:
            logger.debug('[peer] close error: %s', exc)

    def _handle_track(self, track: 'MediaStreamTrack') -> None:
        logger.info('[peer] track event fired: kind=%s id=%s', track.kind, track.id)
        if self.on_track is None:
            logger.warning('[peer] on_track handler is None, dropping track')
            return
        try:
            self.on_track(track)
        except Exception as exc:
            logger.warning('[peer] on_track handler error: %s', exc)

    def _handle_datachannel(self, channel: 'RTCDataChannel') -> None:
        if self.on_datachannel is None:
            return
        try:
            self.on_datachannel(channel)
        except Exception as exc:
            logger.warning('[peer] on_datachannel handler error: %s', exc)

    def _handle_ice_state(self) -> None:
        state = self._pc.iceConnectionState
        logger.info('[ice/state] iceConnectionState=%s', state)
        if state == 'failed':
            logger.warning('[ice/state] ICE failed — нет работающей кандидат-пары. '
                           'Проверьте логи [ice/offer/drone] и [ice/answer/gcs] выше: '
                           'обе стороны должны иметь хотя бы по одному relay-кандидату.')

    def _handle_gather_state(self) -> None:
        logger.info('[ice/state] iceGatheringState=%s', self._pc.iceGatheringState)

    def _handle_conn_state(self) -> None:
        logger.info('[ice/state] connectionState=%s', self._pc.connectionState)
