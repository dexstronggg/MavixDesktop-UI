"""Native relay-only (iceTransportPolicy=relay) for aiortc."""
from __future__ import annotations

from mavixdesktop.core.logger import logger

_applied = False


def enable_relay_only() -> None:
    global _applied
    if _applied:
        return

    from aioice.ice import Connection as _AioiceConnection
    from aioice.ice import TransportPolicy
    from aiortc import rtcicetransport

    def _relay_wanted(kwargs: dict) -> bool:
        from mavixdesktop.core.config import settings
        return bool(getattr(settings, 'force_relay', False)) and kwargs.get('turn_server') is not None

    class _RelayConnection(_AioiceConnection):
        def __init__(self, *args, **kwargs):
            if 'transport_policy' not in kwargs and _relay_wanted(kwargs):
                kwargs['transport_policy'] = TransportPolicy.RELAY
                logger.info('[ice] ICE Connection форсирован в transport_policy=RELAY (нативный relay-only)')
            super().__init__(*args, **kwargs)

    rtcicetransport.Connection = _RelayConnection
    _applied = True
    logger.info('[ice] relay-хук aiortc установлен')
