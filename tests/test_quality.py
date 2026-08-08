"""LinkQuality: freeze detection, RTT percentiles, traffic light, jsonl trail."""
from __future__ import annotations

import json

import pytest

from mavixdesktop.ui.managers.quality import (
    LEVEL_BAD,
    LEVEL_IDLE,
    LEVEL_OK,
    LEVEL_WARN,
    LinkQuality,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def quality(clock):
    q = LinkQuality(clock=clock)
    q.start_session()
    return q


def _steady_frames(quality, clock, count=60, interval=1 / 30):
    for _ in range(count):
        clock.advance(interval)
        quality.on_frame_shown()


def test_idle_without_any_data(quality):
    assert quality.snapshot().level == LEVEL_IDLE


def test_clean_link_is_ok(quality, clock):
    quality.update_inbound(2500.0, 0.0)
    quality.add_rtt(40.0)
    assert quality.snapshot().level == LEVEL_OK


def test_high_loss_is_bad(quality):
    quality.update_inbound(2500.0, 5.0)
    assert quality.snapshot().level == LEVEL_BAD


def test_moderate_loss_is_warn(quality):
    quality.update_inbound(2500.0, 2.0)
    assert quality.snapshot().level == LEVEL_WARN


def test_rtt_growth_flags_bufferbloat_without_loss(quality, clock):
    for _ in range(20):
        clock.advance(0.2)
        quality.add_rtt(50.0)
    quality.update_inbound(2500.0, 0.0)
    assert quality.snapshot().level == LEVEL_OK
    for _ in range(20):
        clock.advance(0.2)
        quality.add_rtt(900.0)
    snap = quality.snapshot()
    assert snap.level == LEVEL_BAD
    assert snap.rtt_growth >= 3.0


def test_rtt_p95_ignores_single_spike(quality, clock):
    for _ in range(40):
        clock.advance(0.2)
        quality.add_rtt(50.0)
    clock.advance(0.2)
    quality.add_rtt(5000.0)
    assert quality.snapshot().rtt_p95_ms < 1000.0


def test_steady_frames_produce_no_freezes(quality, clock):
    _steady_frames(quality, clock)
    snap = quality.snapshot()
    assert snap.freeze_count == 0
    assert snap.freeze_ratio == 0.0


def test_long_gap_counts_as_freeze(quality, clock):
    _steady_frames(quality, clock)
    clock.advance(2.0)
    quality.on_frame_shown()
    snap = quality.snapshot()
    assert snap.freeze_count == 1
    assert snap.freeze_ms == pytest.approx(2000.0, rel=0.01)
    assert snap.level == LEVEL_BAD


def test_freeze_ratio_falls_out_of_the_window(quality, clock):
    _steady_frames(quality, clock)
    clock.advance(2.0)
    quality.on_frame_shown()
    assert quality.snapshot().freeze_ratio > 0
    clock.advance(15.0)
    snap = quality.snapshot()
    assert snap.freeze_ratio == 0.0
    assert snap.freeze_count == 1, 'счётчик за сессию не сбрасывается'


def test_staleness_grows_between_frames(quality, clock):
    quality.on_frame_shown()
    clock.advance(0.75)
    assert quality.snapshot().staleness_ms == pytest.approx(750.0, rel=0.01)


def test_board_underdelivery_is_recorded_but_does_not_colour_the_light(quality, clock):
    """Показатель ушёл из таблицы на экране, но пишется в файл — значит светофор им не красим."""
    quality.update_inbound(1200.0, 0.0)
    quality.add_rtt(40.0)
    quality.update_board(bitrate_out_kbps=1200.0, encoder_kbps=2500.0, pli=0)
    snap = quality.snapshot()
    assert snap.out_ratio == pytest.approx(0.48, rel=0.05)
    assert snap.level == LEVEL_OK


def test_growth_on_tiny_rtt_does_not_raise_alarm(quality, clock):
    """Пинг 1 -> 4 мс это «рост втрое», но по сути ничего не произошло."""
    quality.update_inbound(1000.0, 0.0)
    for _ in range(20):
        clock.advance(0.2)
        quality.add_rtt(1.0)
    for _ in range(20):
        clock.advance(0.2)
        quality.add_rtt(4.0)
    snap = quality.snapshot()
    assert snap.rtt_growth >= 3.0, 'сам множитель считается как раньше'
    assert snap.level == LEVEL_OK, 'но на единицах миллисекунд он не должен красить плашку'


def test_growth_on_real_latency_still_alarms(quality, clock):
    quality.update_inbound(1000.0, 0.0)
    for _ in range(20):
        clock.advance(0.2)
        quality.add_rtt(60.0)
    for _ in range(20):
        clock.advance(0.2)
        quality.add_rtt(240.0)
    assert quality.snapshot().level == LEVEL_BAD


def test_pli_accumulates(quality):
    quality.update_board(1000.0, 1000.0, pli=2)
    quality.update_board(1000.0, 1000.0, pli=3)
    assert quality.snapshot().pli == 5


def test_stale_inbound_returns_to_idle(quality, clock):
    quality.update_inbound(2500.0, 0.0)
    assert quality.snapshot().level == LEVEL_OK
    clock.advance(30.0)
    assert quality.snapshot().level == LEVEL_IDLE


def test_jsonl_trail(tmp_path, clock):
    q = LinkQuality(clock=clock)
    path = tmp_path / 'stats.jsonl'
    q.start_session(log_path=path)
    q.update_inbound(2500.0, 0.5)
    q.add_rtt(80.0)
    q.log_snapshot(q.snapshot())
    q.log_snapshot(q.snapshot())
    q.end_session()

    lines = path.read_text(encoding='utf-8').strip().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first['seq'] == 1
    assert first['bitrate_in_kbps'] == 2500.0
    assert first['loss_pct'] == 0.5
    assert json.loads(lines[1])['seq'] == 2


def test_start_session_resets_counters(quality, clock):
    _steady_frames(quality, clock)
    clock.advance(2.0)
    quality.on_frame_shown()
    assert quality.snapshot().freeze_count == 1
    quality.start_session()
    assert quality.snapshot().freeze_count == 0
