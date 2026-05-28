"""Native relay-only (iceTransportPolicy=relay) for aiortc.

aiortc 1.14 does not expose `iceTransportPolicy` on RTCConfiguration, so the
only previous way to force relay was stripping non-relay lines from the SDP.
That is cosmetic: aiortc's ICE agent still runs with transport_policy=ALL,
gathers host/srflx candidates and sends connectivity checks *from* them. When
the remote peer is a strict relay-only endpoint (GStreamer/libnice on the
drone), those checks arrive at the TURN relay from the desktop's public IP,
for which the drone's allocation has no permission, so coturn drops them and
ICE fails — even though the relay itself works fine.

The fix lives one layer down: aioice.Connection *does* support
`transport_policy=TransportPolicy.RELAY` natively (it then skips host/srflx
candidates and only ever uses the TURN relay). aiortc builds that Connection
in RTCIceGatherer via the module-level `Connection` symbol, so we swap that
symbol for a subclass. Subclassing (not a bare function) keeps
`isinstance(x, aioice.Connection)` valid.

The subclass decides per-connection, reading the live `settings.force_relay`
flag, so toggling force_relay in the Settings UI takes effect on the next
session and we never get stuck in RELAY. It only forces RELAY when a TURN
server is actually configured — aioice raises if RELAY is set without one.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_applied = False


def enable_relay_only() -> None:
    """Install a one-time hook so aiortc's ICE Connection switches to
    transport_policy=RELAY whenever settings.force_relay is on and a TURN
    server is present. Idempotent — safe to call on every session."""
    global _applied
    if _applied:
        return

    from aiortc import rtcicetransport
    from aioice.ice import Connection as _AioiceConnection, TransportPolicy

    def _relay_wanted(kwargs: dict) -> bool:
        from mavixdesktop.core.config import settings
        return bool(getattr(settings, 'force_relay', False)) and kwargs.get('turn_server') is not None

    class _RelayConnection(_AioiceConnection):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            if 'transport_policy' not in kwargs and _relay_wanted(kwargs):
                kwargs['transport_policy'] = TransportPolicy.RELAY
                logger.info('[ice] ICE Connection forced to transport_policy=RELAY (native relay-only)')
            super().__init__(*args, **kwargs)

    rtcicetransport.Connection = _RelayConnection
    _applied = True
    logger.info('[ice] aiortc relay hook installed')
