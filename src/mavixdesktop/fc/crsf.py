"""Кодирование позиций стиков в RC-кадры протокола CRSF (TBS Crossfire).

Сторона оператора: собирает кадр RC_CHANNELS из нормированных значений
стиков и отдаёт его дрону по сети. Разбор телеметрии и служебные кадры
живут на стороне дрона (MavixBoard) — поэтому здесь их нет.
"""

from __future__ import annotations

#### Константы протокола ###############################################################
# CRSF device-address получателя по умолчанию — полётный контроллер
ADDR_FC = 0xC8

# Тип кадра RC-каналов (3-й байт)
FRAME_RC_CHANNELS = 0x16

# Кодирование RC-каналов
CHANNEL_COUNT = 16               # кадр всегда содержит ровно 16 каналов
CHANNEL_BITS = 11                # каждый канал — 11 бит
CHANNEL_MAX_RAW = 0x7FF          # максимум, влезающий в 11 бит (2047)
RC_PAYLOAD_BYTES = 22            # 16 × 11 = 176 бит = 22 байта

# Рабочий диапазон значения канала (конвенция CRSF): минимум / центр / максимум
CH_MIN, CH_CENTER, CH_MAX = 172, 992, 1811

# CRC-8 (полином 0xD5, как в DVB-S2)
CRC8_POLY = 0xD5
CRC8_MSB = 0x80                  # старший бит байта — флаг переноса в цикле
BYTE_MASK = 0xFF


class CRSF:
    #### CRC и сборка кадра ################################################################
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

    #### Кодирование RC-каналов ############################################################
    @staticmethod
    def rc_frame(channels: list[int]) -> bytes:
        # дополняем центром / обрезаем до ровно CHANNEL_COUNT каналов
        ch = (list(channels) + [CH_CENTER] * CHANNEL_COUNT)[:CHANNEL_COUNT]
        bits = 0
        for i, value in enumerate(ch):
            bits |= max(0, min(CHANNEL_MAX_RAW, value)) << (i * CHANNEL_BITS)
        return CRSF._frame(FRAME_RC_CHANNELS, bits.to_bytes(RC_PAYLOAD_BYTES, 'little'))

    #### Преобразование осей в каналы ######################################################
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
