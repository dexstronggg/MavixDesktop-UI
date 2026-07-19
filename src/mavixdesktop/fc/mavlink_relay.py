"""Async UDP-relay between WebRTC data-channel and local QGroundControl."""
from __future__ import annotations

import asyncio
from collections.abc import Callable

from mavixdesktop.core.logger import logger

PacketCallback = Callable[[bytes], None]


class _RelayProtocol(asyncio.DatagramProtocol):
    def __init__(self, on_packet: PacketCallback) -> None:
        self._on_packet = on_packet
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, _addr: object) -> None:
        try:
            self._on_packet(data)
        except Exception as exc:
            logger.warning('[mavlink-relay] ошибка колбэка: %s', exc)

    def error_received(self, exc: Exception) -> None:
        logger.debug('[mavlink-relay] error_received: %s', exc)


class MavlinkRelay:
    def __init__(self, qgc_host: str, qgc_port: int, bind_port: int = 0) -> None:
        self._qgc_host = qgc_host
        self._qgc_port = qgc_port
        self._bind_port = bind_port
        self._on_packet_to_drone: PacketCallback | None = None
        self._transport: asyncio.DatagramTransport | None = None
        self._protocol: _RelayProtocol | None = None
        self._bound_port: int = 0

    @property
    def is_running(self) -> bool:
        return self._transport is not None

    @property
    def bound_port(self) -> int:
        return self._bound_port

    def set_packet_callback(self, cb: PacketCallback | None) -> None:
        self._on_packet_to_drone = cb

    async def start(self) -> None:
        if self._transport is not None:
            return
        loop = asyncio.get_running_loop()
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _RelayProtocol(self._dispatch),
            local_addr=('0.0.0.0', self._bind_port),
            allow_broadcast=False,
        )
        self._transport = transport
        self._protocol = protocol
        sock = transport.get_extra_info('socket')
        if sock is not None:
            self._bound_port = sock.getsockname()[1]
        logger.info(
            '[mavlink-relay] слушаем на :%d, пересылаем на %s:%d',
            self._bound_port, self._qgc_host, self._qgc_port,
        )

    async def stop(self) -> None:
        if self._transport is None:
            return
        self._transport.close()
        self._transport = None
        self._protocol = None
        self._on_packet_to_drone = None

    def send_to_qgc(self, data: bytes) -> None:
        if self._transport is None or not data:
            return
        if isinstance(data, memoryview):
            data = data.tobytes()
        elif not isinstance(data, (bytes, bytearray)):
            data = bytes(data)
        try:
            self._transport.sendto(data, (self._qgc_host, self._qgc_port))
        except OSError as exc:
            logger.warning('[mavlink-relay] ошибка sendto: %s', exc)

    def _dispatch(self, data: bytes) -> None:
        if self._on_packet_to_drone is not None:
            self._on_packet_to_drone(data)
