# MavixDesktop

PC ground station (GCS / receiver) for the Mavix UAV project. Connects to
a MavixServer signalling instance, opens a WebRTC session with a paired
MavixBoard drone, streams its camera(s), and relays joystick / MAVLink
traffic back to the flight controller.

Built on PySide6, aiortc, and asyncio. See `../MavixServer` and
`../MavixBoard` for the other halves of the system.

## Layout

```
src/mavixdesktop/
├── core/
│   ├── config.py        # Pydantic-Settings, env aliases, ws_url property
│   ├── logger.py        # module logger + optional file handler
│   └── backoff.py       # exponential reconnect delay
├── server/
│   ├── api.py           # REST: /health, /auth/login, /auth/refresh, /ice-servers
│   ├── signal_client.py # WebSocket client for /ws/gcs (auth-in-first-message)
│   └── token_store.py   # OS keyring + JSON file fallback for refresh tokens
├── webrtc/
│   ├── peer.py          # PeerSession: answerer, applies SDP offer
│   ├── manager.py       # WebRTCManager: one active session + DataChannelHub
│   └── channels.py      # PacketChannel / PingChannel / ConfigChannel wrappers
├── fc/
│   ├── crsf.py          # CRSF protocol (copy of MavixBoard's)
│   ├── encoder.py       # joystick → CRSF RC frame (pure function)
│   └── mavlink_relay.py # async UDP relay between data-channel and QGC
├── joystick/
│   ├── manager.py       # discovery, SDL config string builder
│   ├── calibration.py   # save/load/validate calibration JSON
│   └── input.py         # JoystickInput: calibrated stick reads, ARM logic
├── qgc/
│   └── launcher.py      # find_qgc + launch with SDL_GAMECONTROLLERCONFIG
├── coordinator.py       # SessionCoordinator: wires signal+webrtc+fc+QGC
└── __main__.py          # headless entry point: python -m mavixdesktop
```

The legacy `src/*.py` files (signalling.py, webrtc.py, joystick.py, ui/)
still build against the old protocol and are left in place during the
migration. They are NOT used by `python -m mavixdesktop`.

## Run (headless)

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade hatchling pip
.venv/bin/pip install -e ".[dev]"

# First launch — provide credentials, refresh token is cached in the
# OS keyring (or ~/.config/mavixdesktop/tokens.json as fallback).
.venv/bin/python -m mavixdesktop --email you@example.com --password '...'

# Subsequent launches — no flags needed, refresh token is reused.
.venv/bin/python -m mavixdesktop
```

Headless mode authenticates, opens the signal WebSocket, and listens
for `drones` / `sdp` / `ice` events. To start a session right now it
needs a programmatic caller (`coordinator.request_connect("drone-id")`).
A PySide6 UI on top of this coordinator is the next planned step — see
TODO below.

## Сборка дистрибутивов

Готовые `.exe` (Windows) и `.AppImage` (Linux) собираются скриптами в `scripts/`:

```bash
./scripts/build_appimage.sh     # → dist/Mavix-Desktop-x86_64.AppImage
.\scripts\build_windows.ps1     # → dist\mavixdesktop.exe
```

Дистрибутивы раздаёт **MavixServer** по `/api/v1/builds/desktop?build_type=exe|deb`
из каталога `BUILDS_PREBUILT_DIR` (дефолт `/srv/mavix/prebuilt`). Бинарники
кладутся туда под строго фиксированными именами: `mavixdesktop.exe` и
`mavixdesktop-linux` (**AppImage без расширения**). `MavixWeb` бинарники не
раздаёт.

Подробности (требования, troubleshooting) — см.
[`scripts/README.md`](scripts/README.md).

## Tests

```bash
.venv/bin/pytest             # full suite (~190 tests)
.venv/bin/pytest tests/test_webrtc_peer.py -v   # real aiortc loopback
```

Tests use `pytest-asyncio` with `asyncio_mode=auto`. `pygame`, `keyring`
and `aiortc.RTCPeerConnection` are exercised either with full mocks or
in-process loopback — no GUI is required to run them.

## What's mocked vs real in tests

| Layer | Tests | Real components |
|---|---|---|
| `core/` | unit | — |
| `server/api.py` | mocked aiohttp | — |
| `server/signal_client.py` | unit + real `websockets.serve` loopback | optional |
| `server/token_store.py` | tmp_path + mocked keyring | — |
| `fc/crsf.py` | pure-Python | — |
| `fc/encoder.py` | pure-Python | — |
| `fc/mavlink_relay.py` | real UDP sockets via `socket.bind` | always |
| `webrtc/peer.py` | real aiortc RTCPeerConnection loopback | always |
| `webrtc/manager.py` | mocked peer | — |
| `webrtc/channels.py` | mocked RTCDataChannel | — |
| `joystick/*` | mocked pygame | — |
| `qgc/launcher.py` | mocked subprocess.Popen | — |
| `coordinator.py` | mocked client + api | — |

## TODO

- **UI rewire to the new coordinator.** The legacy App/Bridge/screens
  currently wrap the old Signalling/WebRTC classes; they need to be
  rewritten as thin adapters over `SessionCoordinator`. Once that lands,
  `python -m mavixdesktop` becomes the single launch path and the
  `src/main.py` + `src/{signalling,webrtc,joystick}.py` legacy can be
  deleted.

- **Speed test** (`src/speedtester/`) is a separate utility and not
  yet ported — it talks to a different server endpoint than signalling
  and can be migrated independently.
