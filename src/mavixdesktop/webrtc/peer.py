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
from collections.abc import Callable
from typing import TYPE_CHECKING

from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription

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


def _build_configuration(ice_servers: list[dict]) -> RTCConfiguration:
    servers: list[RTCIceServer] = []
    for entry in ice_servers:
        urls = entry.get('urls') if isinstance(entry, dict) else None
        if not urls:
            continue
        username = entry.get('username')
        credential = entry.get('credential')
        kwargs: dict = {'urls': urls}
        if username:
            kwargs['username'] = username
        if credential:
            kwargs['credential'] = credential
        servers.append(RTCIceServer(**kwargs))
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
            ice = RTCIceCandidate(
                component=1,
                foundation='',
                ip='',
                port=0,
                priority=0,
                protocol='udp',
                type='host',
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
