"""Обёртки над aiortc RTCDataChannel — по одной на label.

В отличие от дрона (который создаёт каналы), GCS получает их уже открытыми
через pc.on('datachannel'). Hub идентифицирует их по .label и предоставляет
единообразный API, симметричный channels.py из MavixBoard:

  packet    — бинарные FC-пакеты (двунаправленный мост к MavlinkRelay / CRSF)
  ping      — round-trip echo для измерения RTT
  config    — JSON: FC info, camera config, calibrate
  telemetry — JSON: GPS/heading-телеметрия для карты (только приём)
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


#### Обёртки data-каналов ##############################################################
class _BaseChannel:
    LABEL: str = ''

    def __init__(self, channel: RTCDataChannel) -> None:
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

    def _on_message(self, message: object) -> None:
        return


class PacketChannel(_BaseChannel):
    LABEL = 'packet-channel'

    def __init__(self, channel: RTCDataChannel) -> None:
        super().__init__(channel)
        self.on_packet: PacketHandler | None = None

    def send_bytes(self, data: bytes) -> None:
        if not self.is_open:
            return
        try:
            self._ch.send(data)
        except Exception as exc:
            logger.warning('[dc:packet] ошибка отправки: %s', exc)

    def _on_message(self, message: object) -> None:
        if not isinstance(message, (bytes, bytearray, memoryview)):
            return
        if self.on_packet is None:
            return
        raw = bytes(message)
        try:
            self.on_packet(raw)
        except Exception as exc:
            logger.warning('[dc:packet] ошибка обработчика: %s', exc)


class PingChannel(_BaseChannel):
    LABEL = 'ping-channel'

    # 8 байт: big-endian double (monotonic-секунды).
    _PAYLOAD_FMT = '!d'
    _PAYLOAD_SIZE = struct.calcsize(_PAYLOAD_FMT)

    def __init__(self, channel: RTCDataChannel) -> None:
        super().__init__(channel)
        self._last_rtt_ms: float | None = None

    @property
    def last_rtt_ms(self) -> float | None:
        return self._last_rtt_ms

    def send_ping(self) -> None:
        """Отправляет текущий monotonic-таймстамп как 8 сырых байт; плата
        эхом возвращает тот же payload. Без состояния — нет inflight-словаря,
        нет nonce — таймстамп путешествует прямо в пакете."""
        if not self.is_open:
            return
        payload = struct.pack(self._PAYLOAD_FMT, time.monotonic())
        try:
            self._ch.send(payload)
        except Exception as exc:
            logger.warning('[dc:ping] ошибка отправки: %s', exc)

    def _on_message(self, message: object) -> None:
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

    def __init__(self, channel: RTCDataChannel) -> None:
        super().__init__(channel)
        self.on_message: JsonHandler | None = None
        self.on_opened: Callable[[], None] | None = None

    def send_json(self, payload: dict | list) -> None:
        if not self.is_open:
            return
        try:
            data = json.dumps(payload).encode('utf-8')
        except (TypeError, ValueError) as exc:
            logger.warning('[dc:config] ошибка кодирования: %s', exc)
            return
        try:
            self._ch.send(data)
        except Exception as exc:
            logger.warning('[dc:config] ошибка отправки: %s', exc)

    def _on_open(self) -> None:
        super()._on_open()
        if self.on_opened is not None:
            try:
                self.on_opened()
            except Exception as exc:
                logger.warning('[dc:config] ошибка on_opened: %s', exc)

    def _on_message(self, message: object) -> None:
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
            logger.warning('[dc:config] ошибка декодирования json: %s', exc)
            return
        if self.on_message is None:
            return
        try:
            self.on_message(payload)
        except Exception as exc:
            logger.warning('[dc:config] ошибка обработчика: %s', exc)


class TelemetryChannel(_BaseChannel):
    """Приёмный канал GPS/heading-телеметрии.

    Дрон шлёт по нему JSON-сообщения вида
    ``{type:'telemetry', lat, lon, alt, heading, sats}`` (heading — градусы
    0..360). Канал односторонний (только приём): desktop парсит payload и
    отдаёт его в on_telemetry, откуда обновляется маркер/поворот карты.
    """

    LABEL = 'telemetry-channel'

    def __init__(self, channel: RTCDataChannel) -> None:
        super().__init__(channel)
        self.on_telemetry: JsonHandler | None = None

    def _on_message(self, message: object) -> None:
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
            logger.warning('[dc:telemetry] ошибка декодирования json: %s', exc)
            return
        if self.on_telemetry is None:
            return
        try:
            self.on_telemetry(payload)
        except Exception as exc:
            logger.warning('[dc:telemetry] ошибка обработчика: %s', exc)


_LABEL_TO_CLASS = {
    PacketChannel.LABEL: PacketChannel,
    PingChannel.LABEL: PingChannel,
    ConfigChannel.LABEL: ConfigChannel,
    TelemetryChannel.LABEL: TelemetryChannel,
}


#### Реестр data-каналов ###############################################################
class DataChannelHub:
    """Владеет максимум одним каналом каждого известного label. По мере того
    как дрон открывает каналы в WebRTC-сессии, менеджер вызывает .attach(),
    чтобы зарегистрировать их по label."""

    def __init__(self) -> None:
        self.packet: PacketChannel | None = None
        self.ping: PingChannel | None = None
        self.config: ConfigChannel | None = None
        self.telemetry: TelemetryChannel | None = None

    def attach(self, channel: RTCDataChannel) -> bool:
        """Оборачивает только что открытый канал по его label. Возвращает True,
        если label распознан."""
        cls = _LABEL_TO_CLASS.get(channel.label)
        if cls is None:
            logger.warning('[hub] неизвестный label data-канала: %s', channel.label)
            return False
        wrapped = cls(channel)
        if cls is PacketChannel:
            self.packet = wrapped  # type: ignore[assignment]
        elif cls is PingChannel:
            self.ping = wrapped  # type: ignore[assignment]
        elif cls is ConfigChannel:
            self.config = wrapped  # type: ignore[assignment]
        elif cls is TelemetryChannel:
            self.telemetry = wrapped  # type: ignore[assignment]
        return True

    def close(self) -> None:
        self.packet = None
        self.ping = None
        self.config = None
        self.telemetry = None
