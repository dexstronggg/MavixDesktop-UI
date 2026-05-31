"""Владеет одним PeerSession + его DataChannelHub за раз.

Зеркалит WebRTCManager из MavixBoard, но инвертированно: мы принимаем offer /
отправляем answer и *получаем* data-каналы, а не создаём их.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from mavixdesktop.core.logger import logger
from mavixdesktop.webrtc.channels import DataChannelHub
from mavixdesktop.webrtc.peer import PeerSession

if TYPE_CHECKING:
    from aiortc import MediaStreamTrack, RTCDataChannel


SignalSender = Callable[[dict], Awaitable[None]]
TrackHandler = Callable[['MediaStreamTrack'], None]


class WebRTCManager:
    def __init__(self, send: SignalSender, ice_servers: list[dict] | None = None) -> None:
        self._send = send
        self._ice_servers = ice_servers or []
        self._peer: PeerSession | None = None
        self._channels: DataChannelHub | None = None
        self.on_session_ended: Callable[[], None] | None = None
        self.on_track: TrackHandler | None = None
        # Срабатывает каждый раз, когда data-канал от дрона прикреплён к hub
        # (аргумент label). Дрон создаёт packet/ping/config каналы, поэтому
        # может сработать до 3 раз за сессию; вызывающие должны быть
        # идемпотентны. Координатор использует это, чтобы подключать FC-
        # обработчики только ПОСЛЕ того, как каналы реально появились на hub —
        # а это происходит только когда DTLS+SCTP поднят, не сразу после offer/answer.
        self.on_channel_attached: Callable[[str], None] | None = None

    @property
    def active_drone_id(self) -> str | None:
        return self._peer.drone_id if self._peer else None

    @property
    def channels(self) -> DataChannelHub | None:
        return self._channels

    def update_ice_servers(self, ice_servers: list[dict]) -> None:
        self._ice_servers = list(ice_servers)

    def start_session(self, drone_id: str) -> None:
        if self._peer is not None:
            logger.warning('[manager] сессия уже активна (drone=%s), завершаем', self._peer.drone_id)
            self.end_session()
        logger.info('[manager] запускаем сессию с drone=%s', drone_id)
        self._peer = PeerSession(drone_id, ice_servers=self._ice_servers)
        self._channels = DataChannelHub()
        self._peer.on_track = self._handle_track
        self._peer.on_datachannel = self._handle_datachannel

    def end_session(self) -> None:
        if self._peer is None:
            return
        logger.info('[manager] завершаем сессию с drone=%s', self._peer.drone_id)
        if self._channels is not None:
            self._channels.close()
            self._channels = None
        self._peer = None
        if self.on_session_ended is not None:
            self.on_session_ended()

    async def handle_offer(self, drone_id: str, sdp: dict) -> None:
        if not self._guard(drone_id):
            return
        sdp_text = sdp.get('sdp') if isinstance(sdp, dict) else None
        if not isinstance(sdp_text, str):
            logger.warning('[manager] offer без текста sdp')
            return
        assert self._peer is not None
        answer_sdp = await self._peer.apply_offer(sdp_text)
        await self._send({
            'type': 'sdp',
            'drone_id': drone_id,
            'sdp': {'type': 'answer', 'sdp': answer_sdp},
        })

    async def handle_ice(self, drone_id: str, candidate: dict) -> None:
        if not self._guard(drone_id):
            return
        assert self._peer is not None
        await self._peer.add_remote_ice(candidate)

    async def close_async(self) -> None:
        if self._peer is not None:
            await self._peer.close()
        self.end_session()

    def _guard(self, drone_id: str) -> bool:
        if self._peer is None:
            logger.warning('[manager] сообщение для drone=%s, но активной сессии нет', drone_id)
            return False
        if self._peer.drone_id != drone_id:
            logger.warning('[manager] сообщение для drone=%s, но активен drone=%s',
                           drone_id, self._peer.drone_id)
            return False
        return True

    def _handle_track(self, track: MediaStreamTrack) -> None:
        if self.on_track is not None:
            self.on_track(track)

    def _handle_datachannel(self, channel: RTCDataChannel) -> None:
        if self._channels is None:
            return
        attached = self._channels.attach(channel)
        if attached and self.on_channel_attached is not None:
            try:
                self.on_channel_attached(channel.label)
            except Exception as exc:
                logger.warning('[manager] ошибка on_channel_attached: %s', exc)
