"""Tests for the async MAVLink UDP relay."""
from __future__ import annotations

import asyncio
import socket

import pytest

from mavixdesktop.fc.mavlink_relay import MavlinkRelay


def _spawn_udp_listener(host: str = '127.0.0.1') -> tuple[socket.socket, int]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, 0))
    sock.settimeout(2.0)
    return sock, sock.getsockname()[1]


async def test_starts_and_stops():
    relay = MavlinkRelay('127.0.0.1', 14550, bind_port=0)
    await relay.start()
    assert relay.is_running is True
    assert relay.bound_port > 0
    await relay.stop()
    assert relay.is_running is False


async def test_double_start_idempotent():
    relay = MavlinkRelay('127.0.0.1', 14550, bind_port=0)
    await relay.start()
    transport = relay._transport
    await relay.start()
    assert relay._transport is transport
    await relay.stop()


async def test_stop_idempotent():
    relay = MavlinkRelay('127.0.0.1', 14550, bind_port=0)
    await relay.start()
    await relay.stop()
    await relay.stop()


async def test_send_to_qgc_delivers_packet():
    qgc_sock, qgc_port = _spawn_udp_listener()
    try:
        relay = MavlinkRelay('127.0.0.1', qgc_port, bind_port=0)
        await relay.start()
        relay.send_to_qgc(b'\xFE\x09hello')
        data, _ = await asyncio.get_running_loop().run_in_executor(None, qgc_sock.recvfrom, 2048)
        assert data == b'\xFE\x09hello'
        await relay.stop()
    finally:
        qgc_sock.close()


async def test_send_to_qgc_accepts_memoryview_and_bytearray():
    qgc_sock, qgc_port = _spawn_udp_listener()
    try:
        relay = MavlinkRelay('127.0.0.1', qgc_port, bind_port=0)
        await relay.start()
        relay.send_to_qgc(memoryview(b'\x01\x02'))
        d1, _ = await asyncio.get_running_loop().run_in_executor(None, qgc_sock.recvfrom, 2048)
        assert d1 == b'\x01\x02'
        relay.send_to_qgc(bytearray(b'\x03\x04'))
        d2, _ = await asyncio.get_running_loop().run_in_executor(None, qgc_sock.recvfrom, 2048)
        assert d2 == b'\x03\x04'
        await relay.stop()
    finally:
        qgc_sock.close()


async def test_send_to_qgc_before_start_is_noop():
    relay = MavlinkRelay('127.0.0.1', 14550, bind_port=0)
    relay.send_to_qgc(b'data')


async def test_send_to_qgc_empty_payload_is_noop():
    qgc_sock, qgc_port = _spawn_udp_listener()
    try:
        relay = MavlinkRelay('127.0.0.1', qgc_port, bind_port=0)
        await relay.start()
        relay.send_to_qgc(b'')
        qgc_sock.settimeout(0.1)
        with pytest.raises(socket.timeout):
            qgc_sock.recvfrom(2048)
        await relay.stop()
    finally:
        qgc_sock.close()


async def test_packet_from_qgc_routes_to_callback():
    relay = MavlinkRelay('127.0.0.1', 14550, bind_port=0)
    received: list[bytes] = []
    relay.set_packet_callback(received.append)
    await relay.start()
    try:
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.sendto(b'\xAA\xBB\xCC', ('127.0.0.1', relay.bound_port))
        sender.close()
        for _ in range(20):
            if received:
                break
            await asyncio.sleep(0.02)
        assert received == [b'\xAA\xBB\xCC']
    finally:
        await relay.stop()


async def test_callback_errors_are_swallowed():
    relay = MavlinkRelay('127.0.0.1', 14550, bind_port=0)
    relay.set_packet_callback(lambda _: (_ for _ in ()).throw(RuntimeError('boom')))
    await relay.start()
    try:
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.sendto(b'\x00', ('127.0.0.1', relay.bound_port))
        sender.close()
        await asyncio.sleep(0.05)
        assert relay.is_running is True
    finally:
        await relay.stop()


async def test_set_packet_callback_to_none():
    relay = MavlinkRelay('127.0.0.1', 14550, bind_port=0)
    relay.set_packet_callback(lambda _: None)
    relay.set_packet_callback(None)
    await relay.start()
    try:
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.sendto(b'\x01', ('127.0.0.1', relay.bound_port))
        sender.close()
        await asyncio.sleep(0.05)
    finally:
        await relay.stop()
