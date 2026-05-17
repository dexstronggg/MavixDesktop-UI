"""Top-level session coordinator for the desktop side.

Wires together:
  - SignalClient   — WebSocket transport to /ws/gcs
  - ApiSession     — REST for login / refresh / ice-servers
  - WebRTCManager  — one PeerSession + DataChannelHub at a time
  - MavlinkRelay   — UDP bridge to QGC (started when an FC of type=mavlink
                     becomes known on the config-channel)
  - encoder.build_rc_frame — joystick → CRSF, when FC is type=crsf
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import websockets

from mavixdesktop.core.backoff import ExponentialBackoff
from mavixdesktop.core.config import settings
from mavixdesktop.core.logger import logger
from mavixdesktop.fc.mavlink_relay import MavlinkRelay
from mavixdesktop.server.api import ApiError, ApiSession
from mavixdesktop.server.signal_client import SignalClient
from mavixdesktop.webrtc.manager import WebRTCManager

if TYPE_CHECKING:
    from aiortc import MediaStreamTrack


class SessionCoordinator:
    def __init__(
        self,
        signal_client: SignalClient,
        api_session: ApiSession,
        refresh_token: str,
        backoff: ExponentialBackoff | None = None,
        on_track: Callable[['MediaStreamTrack'], None] | None = None,
    ) -> None:
        self._signal_client = signal_client
        self._api = api_session
        self._refresh_token = refresh_token
        self._backoff = backoff if backoff is not None else ExponentialBackoff()
        self.on_track = on_track

        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._manager: WebRTCManager | None = None
        self._mavlink: MavlinkRelay | None = None
        self._target_drone_id: str | None = None
        self._fc_kind: str = 'none'
        self._latest_drones: list[dict] = []
        self._latest_cameras: list[dict] = []
        self._reconnect_drone_id: str | None = None
        self._connect_request_at: float | None = None
        self.on_drones_changed: Callable[[list[dict]], None] | None = None
        self.on_fc_changed: Callable[[str, str], None] | None = None
        self.on_cameras_received: Callable[[list[dict]], None] | None = None
        self.on_cameras_changed: Callable[[list[int]], None] | None = None
        self.on_drone_disconnected: Callable[[str], None] | None = None
        self.on_drone_offline: Callable[[str], None] | None = None
        self.on_connect_failed: Callable[[str], None] | None = None
        self.on_error: Callable[[str], None] | None = None
        self.on_session_ended: Callable[[], None] | None = None
        self.on_battery_changed: Callable[[int, float], None] | None = None

    @property
    def fc_kind(self) -> str:
        return self._fc_kind

    @property
    def drones(self) -> list[dict]:
        return list(self._latest_drones)

    @property
    def cameras(self) -> list[dict]:
        return list(self._latest_cameras)

    async def send_bitrate_update(self, updates: list[dict]) -> None:
        """Send {type:bitrate, updates:[{device_index, bitrate_kbs}, ...]} via config channel."""
        if self._manager is None or self._manager.channels is None:
            return
        config_ch = self._manager.channels.config
        if config_ch is None:
            return
        config_ch.send_json({'type': 'bitrate', 'updates': updates})

    async def send_params_update(self, updates: list[dict]) -> None:
        """Send {type:params, updates:[{device_index, param_index}, ...]} via config channel.

        Changing resolution/FPS requires rebuilding the GStreamer pipeline,
        so the board tears down the current session after persisting; the
        GCS will auto-reconnect and the new pipeline is built with the new
        param_index.
        """
        if self._manager is None or self._manager.channels is None:
            return
        config_ch = self._manager.channels.config
        if config_ch is None:
            return
        config_ch.send_json({'type': 'params', 'updates': updates})

    async def send_calibrate(self) -> None:
        """Send {type:calibrate} via config channel. Board drops saved
        calibrations and tears down the session; auto-reconnect rebuilds
        the pipeline with a fresh full calibration of every camera."""
        if self._manager is None or self._manager.channels is None:
            return
        config_ch = self._manager.channels.config
        if config_ch is None:
            return
        config_ch.send_json({'type': 'calibrate'})

    async def run(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        ice_servers = await self._api.ice_servers()
        self._manager = WebRTCManager(send=self._signal_client.send, ice_servers=ice_servers)
        self._manager.on_track = self.on_track
        # Fires per channel attached (packet/ping/config). Idempotent —
        # see _wire_channels_to_fc. Must NOT fire from _handle_sdp because
        # at that point DTLS+SCTP haven't completed and the hub is empty.
        self._manager.on_channel_attached = lambda _label: self._wire_channels_to_fc()

        while not self._stop_event.is_set():
            connected = await self._signal_client.connect()
            if not connected:
                delay = self._backoff.next_delay()
                logger.info('[coord] signal connect failed, retry in %.1fs', delay)
                await asyncio.sleep(delay)
                continue
            logger.info('[coord] connected to signal server')
            self._backoff.reset()
            try:
                await self._signal_client.listen(self._on_message)
            except websockets.exceptions.ConnectionClosed as exc:
                logger.warning('[coord] signal closed: %s', exc)
            except Exception as exc:
                logger.error('[coord] listen error: %s', exc)
            finally:
                await self._teardown_session()
                await self._signal_client.disconnect()
            await asyncio.sleep(self._backoff.next_delay())

    def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()

    async def request_connect(self, drone_id: str) -> None:
        """UI calls this when the user clicks a drone to start streaming."""
        self._target_drone_id = drone_id
        self._connect_request_at = time.monotonic()
        if self._manager is not None:
            self._manager.start_session(drone_id)
        await self._signal_client.send({'type': 'connect', 'drone_id': drone_id})

    async def request_disconnect(self) -> None:
        if self._target_drone_id is None:
            return
        await self._signal_client.send({
            'type': 'disconnect', 'drone_id': self._target_drone_id,
        })
        await self._teardown_session()

    async def request_drone_list(self) -> None:
        await self._signal_client.send({'type': 'list_drones'})

    def send_joystick_packet(self, frame: bytes) -> None:
        """Bridge: every tick of the UI joystick loop sends one CRSF frame."""
        if self._manager is None or self._manager.channels is None:
            return
        packet = self._manager.channels.packet
        if packet is None:
            return
        packet.send_bytes(frame)

    async def _on_message(self, msg: dict) -> None:
        kind = msg.get('type')
        match kind:
            case 'drones':
                await self._handle_drones(msg.get('drones', []))
            case 'sdp':
                await self._handle_sdp(msg)
            case 'ice':
                await self._handle_ice(msg)
            case 'drone_disconnected':
                drone_id = msg.get('drone_id')
                # Distinguish "session never came up" (board dropped the peer
                # before SDP — e.g. no cameras / pipeline broken) from a
                # mid-flight teardown (board renegotiating after params/
                # camera-hotplug). If the disconnect arrives within 10s of
                # our request_connect for this same drone, the GCS hasn't
                # ever seen video → treat as a hard connect-failure: surface
                # to the UI and DO NOT auto-reconnect (otherwise we'd loop
                # while the board keeps rejecting connect because cameras
                # are still missing).
                is_connect_failure = (
                    isinstance(drone_id, str)
                    and self._target_drone_id == drone_id
                    and self._connect_request_at is not None
                    and (time.monotonic() - self._connect_request_at) < 10.0
                )
                self._connect_request_at = None
                if is_connect_failure:
                    logger.info('[coord] drone %s disconnected during connect; not retrying', drone_id)
                    await self._teardown_session()
                    if self.on_connect_failed is not None:
                        try:
                            self.on_connect_failed(drone_id)
                        except Exception as exc:
                            logger.warning('[coord] on_connect_failed error: %s', exc)
                    return
                logger.info('[coord] drone disconnected: %s; will auto-reconnect when it returns', drone_id)
                if isinstance(drone_id, str) and self._target_drone_id == drone_id:
                    self._reconnect_drone_id = drone_id
                await self._teardown_session()
                if self.on_drone_disconnected is not None and isinstance(drone_id, str):
                    try:
                        self.on_drone_disconnected(drone_id)
                    except Exception as exc:
                        logger.warning('[coord] on_drone_disconnected error: %s', exc)
                if self._reconnect_drone_id is not None:
                    await self.request_drone_list()
            case 'auth_warning':
                await self._handle_auth_warning(msg)
            case 'auth_refreshed':
                await self._handle_auth_refreshed(msg)
            case 'shutdown':
                logger.info('[coord] server shutdown notice')
                await self._teardown_session()
            case 'ping':
                await self._signal_client.send({'type': 'pong'})
            case 'pong':
                pass
            case 'error':
                err = msg.get('message')
                logger.warning('[coord] server error: %s', err)
                if self.on_error is not None and isinstance(err, str):
                    try:
                        self.on_error(err)
                    except Exception as exc:
                        logger.warning('[coord] on_error callback error: %s', exc)
            case _:
                logger.debug('[coord] unknown message type: %s', kind)

    async def _handle_drones(self, drones) -> None:
        if not isinstance(drones, list):
            return
        self._latest_drones = drones
        if self.on_drones_changed is not None:
            try:
                self.on_drones_changed(self._latest_drones)
            except Exception as exc:
                logger.warning('[coord] on_drones_changed error: %s', exc)
        # Auto-reconnect: if we lost a drone and it has now come back online, re-connect.
        # Check active_drone_id rather than `_manager is None` — the manager
        # itself is kept alive across teardowns (it's reusable); a torn-down
        # session is signalled by `_peer is None`, i.e. active_drone_id is None.
        manager_idle = self._manager is None or self._manager.active_drone_id is None
        if self._reconnect_drone_id is not None and manager_idle:
            entry = next(
                (d for d in drones if d.get('drone_id') == self._reconnect_drone_id and d.get('online')),
                None,
            )
            if entry is not None:
                target = self._reconnect_drone_id
                self._reconnect_drone_id = None
                logger.info('[coord] auto-reconnecting to drone %s', target)
                await self.request_connect(target)
            else:
                # Drone isn't in the refreshed list as online: this isn't a
                # renegotiation blip — the board's WS is genuinely gone (crash,
                # network, power). Stop waiting for it to come back and let
                # the UI navigate the user out of drone-view.
                offline_id = self._reconnect_drone_id
                self._reconnect_drone_id = None
                logger.info('[coord] drone %s confirmed offline; giving up reconnect', offline_id)
                if self.on_drone_offline is not None:
                    try:
                        self.on_drone_offline(offline_id)
                    except Exception as exc:
                        logger.warning('[coord] on_drone_offline error: %s', exc)

    async def _handle_sdp(self, msg: dict) -> None:
        if self._manager is None:
            return
        drone_id = msg.get('drone_id')
        sdp = msg.get('sdp')
        if not isinstance(drone_id, str) or not isinstance(sdp, dict):
            return
        # First SDP from the drone in a session arrives as the offer; manager
        # handles only that direction (the answer was already sent by us).
        # FC wiring used to be done eagerly here, but at this point DTLS+SCTP
        # haven't completed yet — hub.packet / hub.config are still None.
        # The manager now invokes _wire_channels_to_fc via on_channel_attached
        # when each data channel actually shows up on the aiortc PC.
        if sdp.get('type') == 'offer':
            # SDP arrived — connect is in progress; clear the connect-failure
            # window so a later disconnect is treated as a normal teardown.
            self._connect_request_at = None
            await self._manager.handle_offer(drone_id, sdp)

    async def _handle_ice(self, msg: dict) -> None:
        if self._manager is None:
            return
        drone_id = msg.get('drone_id')
        cand = msg.get('candidate')
        if isinstance(drone_id, str) and isinstance(cand, dict):
            await self._manager.handle_ice(drone_id, cand)

    async def _handle_auth_refreshed(self, msg: dict) -> None:
        """Server confirms a refresh — its new access token replaces ours.
        Also accept the server-emitted access token directly (in case our REST
        refresh returned an older one).

        If the server also rotated the refresh token (msg['refresh_token']),
        update the in-memory copy AND the persisted token_store, otherwise
        the next REST /auth/refresh will fail with a 401 on the stale token.
        """
        new_access = msg.get('access_token')
        if isinstance(new_access, str) and new_access:
            self._signal_client.update_access_token(new_access)
            logger.info('[coord] access token updated from server-side refresh')
        new_refresh = msg.get('refresh_token')
        if isinstance(new_refresh, str) and new_refresh and new_refresh != self._refresh_token:
            self._refresh_token = new_refresh
            # Persist for next launch — failures are non-fatal (we still
            # have the in-memory copy for the rest of this session).
            try:
                from mavixdesktop.server import token_store
                email, _ = token_store.load()
                if email:
                    token_store.save(email, new_refresh)
            except Exception as exc:
                logger.warning('[coord] refresh-token persist failed: %s', exc)

    async def _handle_auth_warning(self, msg: dict) -> None:
        logger.info('[coord] auth expiring in %ss, refreshing', msg.get('seconds_left'))
        try:
            new_access = await self._refresh_now()
        except ApiError as exc:
            logger.error('[coord] refresh failed: %s', exc)
            return
        try:
            await self._signal_client.send({
                'type': 'refresh_auth',
                'refresh_token': self._refresh_token,
            })
        except Exception as exc:
            logger.warning('[coord] refresh_auth send error: %s', exc)
        if new_access:
            self._signal_client.update_access_token(new_access)

    async def _refresh_now(self) -> str:
        """Hit /api/v1/auth/refresh. Returns the new access token."""
        result = await self._api.refresh(self._refresh_token)
        new_access = result.get('access_token', '')
        if isinstance(new_access, str) and new_access:
            return new_access
        raise ApiError('refresh returned no access token')

    def _wire_channels_to_fc(self) -> None:
        """Once data channels exist, plumb the packet channel to the FC."""
        if self._manager is None or self._manager.channels is None:
            return
        hub = self._manager.channels
        if hub.config is not None:
            hub.config.on_message = self._on_config_message
        if hub.packet is not None:
            hub.packet.on_packet = self._on_packet_from_drone

    async def _on_config_message_async(self, payload: dict | list) -> None:
        if not isinstance(payload, dict):
            return
        kind = payload.get('type')
        if kind == 'fc':
            await self._handle_fc_message(payload)
        elif kind == 'cameras':
            self._handle_cameras_message(payload)
        elif kind == 'cameras_changed':
            self._handle_cameras_changed_message(payload)
        elif kind == 'battery':
            self._handle_battery_message(payload)
        elif kind == 'command_ack':
            self._handle_command_ack_message(payload)
        elif kind == 'fc_armed':
            armed = bool(payload.get('armed', False))
            cm = int(payload.get('custom_mode', 0))
            logger.info('[coord] FC armed=%s custom_mode=0x%08x', armed, cm)
        else:
            logger.debug('[coord] unknown config-channel type: %s', kind)

    def _handle_battery_message(self, payload: dict) -> None:
        try:
            percent = int(payload.get('percent', 0))
            voltage = float(payload.get('voltage', 0.0))
        except (TypeError, ValueError):
            return
        if self.on_battery_changed is not None:
            try:
                self.on_battery_changed(percent, voltage)
            except Exception as exc:
                logger.warning('[coord] on_battery_changed error: %s', exc)

    def _handle_command_ack_message(self, payload: dict) -> None:
        """Loud log line for every MAVLink COMMAND_ACK the FC sends back.
        Result `ACCEPTED` means our SET_MODE / ARM went through; anything
        else (DENIED / TEMPORARILY_REJECTED / FAILED / UNSUPPORTED) is
        the FC explaining why the command was refused."""
        cmd = payload.get('command', '?')
        result = payload.get('result', '?')
        if result == 'ACCEPTED':
            logger.info('[coord] FC ack %s: %s', cmd, result)
        else:
            logger.warning('[coord] FC REJECT %s: %s', cmd, result)

    async def _handle_fc_message(self, payload: dict) -> None:
        kind = payload.get('kind') or 'none'
        name = payload.get('name') or ''
        if not isinstance(kind, str):
            kind = 'none'
        self._fc_kind = kind
        await self._apply_fc_kind(kind)
        if self.on_fc_changed is not None:
            try:
                self.on_fc_changed(kind, name if isinstance(name, str) else '')
            except Exception as exc:
                logger.warning('[coord] on_fc_changed error: %s', exc)

    def _handle_cameras_message(self, payload: dict) -> None:
        cameras = payload.get('cameras')
        if not isinstance(cameras, list):
            return
        self._latest_cameras = cameras
        if self.on_cameras_received is not None:
            try:
                self.on_cameras_received(cameras)
            except Exception as exc:
                logger.warning('[coord] on_cameras_received error: %s', exc)

    def _handle_cameras_changed_message(self, payload: dict) -> None:
        indices = payload.get('device_indices')
        if not isinstance(indices, list):
            return
        if self.on_cameras_changed is not None:
            try:
                self.on_cameras_changed(indices)
            except Exception as exc:
                logger.warning('[coord] on_cameras_changed error: %s', exc)

    def _on_config_message(self, payload: dict | list) -> None:
        # ConfigChannel calls this synchronously; schedule async handler.
        if self._loop is None:
            return
        self._loop.create_task(self._on_config_message_async(payload))

    async def _apply_fc_kind(self, kind: str) -> None:
        if kind == 'mavlink':
            if self._mavlink is None:
                self._mavlink = MavlinkRelay(
                    qgc_host=settings.qgc_host,
                    qgc_port=settings.qgc_port,
                    bind_port=settings.qgc_bind_port,
                )
                self._mavlink.set_packet_callback(self._on_qgc_packet)
                await self._mavlink.start()
        else:
            if self._mavlink is not None:
                await self._mavlink.stop()
                self._mavlink = None

    def _on_packet_from_drone(self, data: bytes) -> None:
        """Drone → packet-channel → here. For MAVLink, forward to QGC."""
        if self._fc_kind == 'mavlink' and self._mavlink is not None:
            self._mavlink.send_to_qgc(data)
        # For CRSF, telemetry packets currently have no UI consumer; the UI
        # may subscribe via the bridge layer to parse them itself.

    def _on_qgc_packet(self, data: bytes) -> None:
        """QGC → UDP socket → here. Forward to drone via packet-channel."""
        if self._manager is None or self._manager.channels is None:
            return
        packet = self._manager.channels.packet
        if packet is None:
            return
        packet.send_bytes(data)

    async def _teardown_session(self) -> None:
        # All callers run on the coordinator's own event loop, so we can
        # just await — no need for run_coroutine_threadsafe (which would
        # deadlock when scheduled onto the loop currently executing us).
        # NOTE: keep self._manager alive across teardowns. WebRTCManager's
        # close_async/end_session leave it in a clean state, and request_connect
        # only calls start_session when manager is not None — nulling it
        # here breaks auto-reconnect (e.g. after a params-driven session drop)
        # and the in-and-out-of-drone-view re-entry path.
        if self._manager is not None:
            await self._manager.close_async()
        if self._mavlink is not None:
            try:
                await self._mavlink.stop()
            except Exception as exc:
                logger.debug('[coord] mavlink stop error: %s', exc)
            self._mavlink = None
        self._target_drone_id = None
        self._fc_kind = 'none'
        if self.on_session_ended is not None:
            try:
                self.on_session_ended()
            except Exception as exc:
                logger.warning('[coord] on_session_ended error: %s', exc)
