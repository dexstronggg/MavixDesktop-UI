"""Wrappers around aiortc RTCDataChannel — one per label.

Unlike the drone (which creates the channels), the GCS receives them
already opened via pc.on('datachannel'). The hub identifies them by their
.label and offers a uniform API symmetrical to MavixBoard's channels.py:

  packet  — binary FC packets (bidirectional bridge to MavlinkRelay / CRSF)
  ping    — round-trip echo for RTT measurement
  config  — JSON: FC info, camera config, calibrate, cameras_changed
"""
from __future__ import annotations

import json
import struct
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from mavixdesktop.core.logger import logger

if TYPE_CHECKING:
    from aiortc import RTCDataChannel

PacketHandler = Callable[[bytes], None]
JsonHandler = Callable[[dict | list], None]


class _BaseChannel:
    LABEL: str = ''

    def __init__(self, channel: 'RTCDataChannel') -> None:
        self._ch = channel
        channel.on('open', self._on_open)
        channel.on('close', self._on_close)
        channel.on('message', self._on_message)

    @property
    def label(self) -> str:
        return self._ch.label

    @property
    def is_open(self) -> bool:
        return self._ch.readyState == 'open'

    def _on_open(self) -> None:
        logger.info('[dc:%s] open', self.label)

    def _on_close(self) -> None:
        logger.info('[dc:%s] close', self.label)

    def _on_message(self, message) -> None:
        return


class PacketChannel(_BaseChannel):
    LABEL = 'packet-channel'

    def __init__(self, channel: 'RTCDataChannel') -> None:
        super().__init__(channel)
        self.on_packet: PacketHandler | None = None

    def send_bytes(self, data: bytes) -> None:
        if not self.is_open:
            return
        try:
            self._ch.send(data)
        except Exception as exc:
            logger.warning('[dc:packet] send error: %s', exc)

    def _on_message(self, message) -> None:
        if not isinstance(message, (bytes, bytearray, memoryview)):
            return
        if self.on_packet is None:
            return
        raw = bytes(message)
        try:
            self.on_packet(raw)
        except Exception as exc:
            logger.warning('[dc:packet] handler error: %s', exc)


class PingChannel(_BaseChannel):
    LABEL = 'ping-channel'

    # 8 bytes: big-endian double (monotonic seconds).
    _PAYLOAD_FMT = '!d'
    _PAYLOAD_SIZE = struct.calcsize(_PAYLOAD_FMT)

    def __init__(self, channel: 'RTCDataChannel') -> None:
        super().__init__(channel)
        self._last_rtt_ms: float | None = None

    @property
    def last_rtt_ms(self) -> float | None:
        return self._last_rtt_ms

    def send_ping(self) -> None:
        """Send the current monotonic timestamp as 8 raw bytes; the board
        echoes the same payload back. Stateless — no inflight dict, no
        nonces — the timestamp travels with the packet itself."""
        if not self.is_open:
            return
        payload = struct.pack(self._PAYLOAD_FMT, time.monotonic())
        try:
            self._ch.send(payload)
        except Exception as exc:
            logger.warning('[dc:ping] send error: %s', exc)

    def _on_message(self, message) -> None:
        if isinstance(message, (bytes, bytearray, memoryview)):
            raw = bytes(message)
        else:
            return
        if len(raw) != self._PAYLOAD_SIZE:
            return
        try:
            sent_at, = struct.unpack(self._PAYLOAD_FMT, raw)
        except struct.error:
            return
        self._last_rtt_ms = (time.monotonic() - sent_at) * 1000.0


class ConfigChannel(_BaseChannel):
    LABEL = 'config-channel'

    def __init__(self, channel: 'RTCDataChannel') -> None:
        super().__init__(channel)
        self.on_message: JsonHandler | None = None
        self.on_opened: Callable[[], None] | None = None

    def send_json(self, payload: dict | list) -> None:
        if not self.is_open:
            return
        try:
            data = json.dumps(payload).encode('utf-8')
        except (TypeError, ValueError) as exc:
            logger.warning('[dc:config] encode error: %s', exc)
            return
        try:
            self._ch.send(data)
        except Exception as exc:
            logger.warning('[dc:config] send error: %s', exc)

    def _on_open(self) -> None:
        super()._on_open()
        if self.on_opened is not None:
            try:
                self.on_opened()
            except Exception as exc:
                logger.warning('[dc:config] on_opened error: %s', exc)

    def _on_message(self, message) -> None:
        if isinstance(message, (bytes, bytearray, memoryview)):
            try:
                text = bytes(message).decode('utf-8')
            except UnicodeDecodeError:
                return
        elif isinstance(message, str):
            text = message
        else:
            return
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            logger.warning('[dc:config] json decode error: %s', exc)
            return
        if self.on_message is None:
            return
        try:
            self.on_message(payload)
        except Exception as exc:
            logger.warning('[dc:config] handler error: %s', exc)


_LABEL_TO_CLASS = {
    PacketChannel.LABEL: PacketChannel,
    PingChannel.LABEL: PingChannel,
    ConfigChannel.LABEL: ConfigChannel,
}


class DataChannelHub:
    """Owns at most one channel of each known label. As the drone opens
    channels via the WebRTC session, the manager calls .attach() to
    register them by label."""

    def __init__(self) -> None:
        self.packet: PacketChannel | None = None
        self.ping: PingChannel | None = None
        self.config: ConfigChannel | None = None

    def attach(self, channel: 'RTCDataChannel') -> bool:
        """Wrap a freshly-opened channel by its label. Returns True if
        the label was recognised."""
        cls = _LABEL_TO_CLASS.get(channel.label)
        if cls is None:
            logger.warning('[hub] unknown data-channel label: %s', channel.label)
            return False
        wrapped = cls(channel)
        if cls is PacketChannel:
            self.packet = wrapped  # type: ignore[assignment]
        elif cls is PingChannel:
            self.ping = wrapped  # type: ignore[assignment]
        elif cls is ConfigChannel:
            self.config = wrapped  # type: ignore[assignment]
        return True

    def close(self) -> None:
        self.packet = None
        self.ping = None
        self.config = None
