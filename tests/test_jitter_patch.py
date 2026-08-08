from __future__ import annotations

import time

from aiortc.jitterbuffer import JitterBuffer
from aiortc.rtp import RtpPacket

from mavixdesktop.webrtc.jitter_patch import (
    STUCK_DEADLINE_S,
    DeadlineJitterBuffer,
    install_jitter_patch,
)


def _packet(seq: int, timestamp: int) -> RtpPacket:
    p = RtpPacket()
    p.payload_type = 96
    p.sequence_number = seq
    p.timestamp = timestamp
    p.payload = b'x' * 100
    p._data = p.payload
    return p


def _partial_frame(buf: JitterBuffer, first_seq: int, ts: int, have: int) -> None:
    for i in range(have):
        buf.add(_packet(first_seq + i, ts))


def test_patch_installs_video_only_and_is_idempotent():
    install_jitter_patch()
    install_jitter_patch()
    from aiortc import rtcrtpreceiver

    assert rtcrtpreceiver.JitterBuffer is DeadlineJitterBuffer


def test_no_loss_same_behaviour_as_base():
    a = JitterBuffer(capacity=16, is_video=True)
    b = DeadlineJitterBuffer(capacity=16, is_video=True)
    for buf in (a, b):
        _partial_frame(buf, 100, 1000, 4)
    assert a.add(_packet(104, 2000))[1] is not None
    assert b.add(_packet(104, 2000))[1] is not None


def test_recovered_gap_emits_frame_without_pli():
    b = DeadlineJitterBuffer(capacity=16, is_video=True)
    _partial_frame(b, 100, 1000, 3)
    b.add(_packet(104, 2000))
    pli, frame = b.add(_packet(103, 1000))
    assert pli is False
    assert frame is not None
    assert b._stuck_since is None


def test_stuck_gap_triggers_pli_after_deadline(monkeypatch):
    b = DeadlineJitterBuffer(capacity=16, is_video=True)
    _partial_frame(b, 100, 1000, 3)
    b.add(_packet(104, 2000))

    now = [time.monotonic()]
    monkeypatch.setattr(time, 'monotonic', lambda: now[0])
    b.add(_packet(102, 1000))
    assert b._stuck_since is not None

    now[0] += STUCK_DEADLINE_S + 0.01
    pli, frame = b.add(_packet(105, 3000))
    assert pli is True
    assert frame is not None
    assert frame.timestamp == 1000
    assert frame.data == b'x' * 300
    assert b._stuck_since is None


def test_audio_never_triggers_deadline(monkeypatch):
    a = DeadlineJitterBuffer(capacity=16, prefetch=4)
    a.add(_packet(1, 100))
    a.add(_packet(3, 100))

    now = [time.monotonic()]
    monkeypatch.setattr(time, 'monotonic', lambda: now[0])
    now[0] += STUCK_DEADLINE_S + 0.5
    pli, _ = a.add(_packet(4, 100))
    assert pli is False
    assert a._stuck_since is None


def test_gap_recovered_before_deadline_keeps_frame(monkeypatch):
    b = DeadlineJitterBuffer(capacity=16, is_video=True)
    _partial_frame(b, 100, 1000, 3)
    b.add(_packet(104, 2000))

    now = [time.monotonic()]
    monkeypatch.setattr(time, 'monotonic', lambda: now[0])
    b.add(_packet(102, 1000))
    now[0] += STUCK_DEADLINE_S / 2
    pli, frame = b.add(_packet(103, 1000))
    assert pli is False
    assert frame is not None


def test_install_patch_tolerates_missing_module(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == 'aiortc.rtcrtpreceiver':
            raise ImportError('simulated')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    install_jitter_patch()


def test_full_frame_on_origin_gap_in_next_emits_full_frame(monkeypatch):
    b = DeadlineJitterBuffer(capacity=32, is_video=True)
    _partial_frame(b, 100, 1000, 5)
    b.add(_packet(106, 2000))
    b.add(_packet(107, 2000))
    b.add(_packet(108, 2000))
    now = [time.monotonic()]
    monkeypatch.setattr(time, 'monotonic', lambda: now[0])
    now[0] += STUCK_DEADLINE_S + 0.01
    pli, frame = b.add(_packet(109, 3000))
    assert pli is True
    assert frame is not None
    assert frame.timestamp == 1000
    assert frame.data == b'x' * 500
    assert b.add(_packet(110, 3000))[1] is None


def test_full_frame_on_origin_gap_inside_skips_partial(monkeypatch):
    b = DeadlineJitterBuffer(capacity=32, is_video=True)
    _partial_frame(b, 100, 1000, 2)
    b.add(_packet(103, 1000))
    b.add(_packet(104, 2000))
    now = [time.monotonic()]
    monkeypatch.setattr(time, 'monotonic', lambda: now[0])
    now[0] += STUCK_DEADLINE_S + 0.01
    pli, frame = b.add(_packet(105, 2000))
    assert pli is True
    assert frame is None
