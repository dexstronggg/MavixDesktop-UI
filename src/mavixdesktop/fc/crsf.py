"""Encode joystick stick positions into CRSF RC channels frames (TBS Crossfire)."""
from __future__ import annotations

ADDR_FC = 0xC8

FRAME_RC_CHANNELS = 0x16

CHANNEL_COUNT = 16
CHANNEL_BITS = 11
CHANNEL_MAX_RAW = 0x7FF
RC_PAYLOAD_BYTES = 22

CH_MIN, CH_CENTER, CH_MAX = 172, 992, 1811

CRC8_POLY = 0xD5
CRC8_MSB = 0x80
BYTE_MASK = 0xFF


class CRSF:
    @staticmethod
    def crc8(data: bytes) -> int:
        crc = 0
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = ((crc << 1) ^ CRC8_POLY if crc & CRC8_MSB else crc << 1) & BYTE_MASK
        return crc

    @staticmethod
    def _frame(ftype: int, payload: bytes, addr: int = ADDR_FC) -> bytes:
        body = bytes([ftype]) + payload
        return bytes([addr, len(body) + 1]) + body + bytes([CRSF.crc8(body)])

    @staticmethod
    def rc_frame(channels: list[int]) -> bytes:
        ch = (list(channels) + [CH_CENTER] * CHANNEL_COUNT)[:CHANNEL_COUNT]
        bits = 0
        for i, value in enumerate(ch):
            bits |= max(0, min(CHANNEL_MAX_RAW, value)) << (i * CHANNEL_BITS)
        return CRSF._frame(FRAME_RC_CHANNELS, bits.to_bytes(RC_PAYLOAD_BYTES, 'little'))

    @staticmethod
    def axis_to_crsf(v: float, dz: float = 0.05) -> int:
        if abs(v) < dz:
            return CH_CENTER
        n = (v - dz) / (1 - dz) if v > 0 else (v + dz) / (1 - dz)
        return max(CH_MIN, min(CH_MAX, int(CH_CENTER + n * (CH_MAX - CH_CENTER))))

    @staticmethod
    def throttle_to_crsf(v: float) -> int:
        n = max(0.0, min(1.0, (v + 1) / 2))
        return int(CH_MIN + n * (CH_MAX - CH_MIN))
