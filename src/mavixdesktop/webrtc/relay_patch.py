"""Нативный relay-only (iceTransportPolicy=relay) для aiortc.

aiortc 1.14 не выставляет `iceTransportPolicy` на RTCConfiguration, поэтому
раньше единственным способом форсировать relay было вырезание non-relay
строк из SDP. Это косметика: ICE-агент aiortc всё равно работает с
transport_policy=ALL, собирает host/srflx кандидатов и шлёт connectivity-
проверки *из* них. Когда удалённый пир — строго relay-only endpoint
(GStreamer/libnice на дроне), эти проверки приходят на TURN-relay с
публичного IP десктопа, для которого у allocation дрона нет permission,
поэтому coturn их отбрасывает и ICE падает — хотя сам relay работает.

Фикс лежит уровнем ниже: aioice.Connection *поддерживает*
`transport_policy=TransportPolicy.RELAY` нативно (тогда он пропускает
host/srflx кандидатов и использует только TURN-relay). aiortc создаёт этот
Connection в RTCIceGatherer через модульный символ `Connection`, поэтому мы
подменяем этот символ подклассом. Подкласс (а не голая функция) сохраняет
валидность `isinstance(x, aioice.Connection)`.

Подкласс решает per-connection, читая живой флаг `settings.force_relay`,
поэтому переключение force_relay в Settings UI вступает в силу на следующей
сессии и мы никогда не застреваем в RELAY. RELAY форсируется только когда
TURN-сервер реально настроен — aioice падает, если RELAY задан без него.
"""
from __future__ import annotations

from mavixdesktop.core.logger import logger

_applied = False


def enable_relay_only() -> None:
    """Устанавливает одноразовый хук, чтобы ICE Connection aiortc переключался
    на transport_policy=RELAY, когда settings.force_relay включён и присутствует
    TURN-сервер. Идемпотентно — безопасно вызывать на каждой сессии."""
    global _applied
    if _applied:
        return

    from aioice.ice import Connection as _AioiceConnection
    from aioice.ice import TransportPolicy
    from aiortc import rtcicetransport

    def _relay_wanted(kwargs: dict) -> bool:
        from mavixdesktop.core.config import settings
        return bool(getattr(settings, 'force_relay', False)) and kwargs.get('turn_server') is not None

    class _RelayConnection(_AioiceConnection):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            if 'transport_policy' not in kwargs and _relay_wanted(kwargs):
                kwargs['transport_policy'] = TransportPolicy.RELAY
                logger.info('[ice] ICE Connection форсирован в transport_policy=RELAY (нативный relay-only)')
            super().__init__(*args, **kwargs)

    rtcicetransport.Connection = _RelayConnection
    _applied = True
    logger.info('[ice] relay-хук aiortc установлен')
