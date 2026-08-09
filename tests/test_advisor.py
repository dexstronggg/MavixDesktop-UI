"""Advisor: рекомендация режима камеры по формуле Kush Gauge и оценке канала TFRC."""

from __future__ import annotations

import pytest

from mavixdesktop.ui.managers import advisor
from mavixdesktop.ui.managers.advisor import (
    CONFIRM_TICKS,
    Advisor,
    ChannelEstimator,
    format_advice,
    pick_mode,
    required_kbps,
    tfrc_kbps,
)
from mavixdesktop.ui.managers.quality import LinkSnapshot


def _snap(
    bitrate_in_kbps: float = 2000.0,
    loss_pct: float = 0.0,
    rtt_p95_ms: float = 40.0,
    rtt_growth: float = 1.0,
) -> LinkSnapshot:
    return LinkSnapshot(
        bitrate_in_kbps=bitrate_in_kbps,
        loss_pct=loss_pct,
        rtt_p95_ms=rtt_p95_ms,
        rtt_growth=rtt_growth,
    )


def test_required_kbps_known_numbers():
    assert required_kbps(1280, 720, 30, 0.07, 1) == pytest.approx(1935.36)


def test_tfrc_zero_loss_means_no_limit():
    assert tfrc_kbps(50.0, 0.0) == float('inf')


def test_tfrc_zero_rtt_means_no_limit():
    assert tfrc_kbps(0.0, 0.1) == float('inf')


def test_tfrc_falls_with_more_loss():
    low = tfrc_kbps(50.0, 0.02)
    high = tfrc_kbps(50.0, 0.2)
    assert high < low


def test_tfrc_falls_with_more_rtt():
    fast = tfrc_kbps(30.0, 0.05)
    slow = tfrc_kbps(300.0, 0.05)
    assert slow < fast


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


def test_channel_estimator_grows_on_clean_channel_after_probe_delay():
    estimator = ChannelEstimator()
    clock = _Clock()
    capacity = 2000.0
    for _ in range(35):
        capacity = estimator.update(_snap(bitrate_in_kbps=2000.0), clock.advance(1.0))
    assert capacity > 2000.0


def test_channel_estimator_drops_under_heavy_loss():
    estimator = ChannelEstimator()
    capacity = estimator.update(
        _snap(bitrate_in_kbps=5000.0, loss_pct=10.0, rtt_p95_ms=80.0, rtt_growth=1.0),
        now=1.0,
    )
    assert capacity < 5000.0


def test_channel_estimator_resets_probe_timer_on_loss():
    estimator = ChannelEstimator()
    clock = _Clock()
    for _ in range(20):
        estimator.update(_snap(bitrate_in_kbps=2000.0), clock.advance(1.0))
    estimator.update(
        _snap(bitrate_in_kbps=2000.0, loss_pct=5.0, rtt_p95_ms=80.0),
        clock.advance(1.0),
    )
    capacity = 0.0
    for _ in range(20):
        capacity = estimator.update(_snap(bitrate_in_kbps=2000.0), clock.advance(1.0))
    # с момента потерь чистый канал держится всего 20 с — меньше PROBE_AFTER_S
    assert capacity <= 2000.0 * advisor.CLEAN_FACTOR + 1.0
    assert capacity < 2000.0 * advisor.PROBE_FACTOR


def test_moderate_loss_keeps_capacity_at_goodput():
    """При 1 % потерь TFRC даёт втрое меньше реально прошедшего — душить канал нельзя."""
    estimator = ChannelEstimator()
    capacity = 0.0
    for i in range(20):
        capacity = estimator.update(
            _snap(bitrate_in_kbps=4000.0, loss_pct=1.0, rtt_p95_ms=50.0),
            now=float(i),
        )
    assert capacity == pytest.approx(4000.0, rel=0.02)


def test_heavy_loss_never_falls_below_half_of_goodput():
    estimator = ChannelEstimator()
    capacity = 0.0
    for i in range(30):
        capacity = estimator.update(
            _snap(
                bitrate_in_kbps=4000.0,
                loss_pct=20.0,
                rtt_p95_ms=400.0,
                rtt_growth=3.0,
            ),
            now=float(i),
        )
    assert capacity < 4000.0 * advisor.CONGESTED_FACTOR
    assert capacity >= 4000.0 * advisor.TFRC_FLOOR_FACTOR - 1.0


def test_pick_mode_prefers_largest_that_fits():
    params = [
        {'width': 640, 'height': 480, 'fps': 30},
        {'width': 1280, 'height': 720, 'fps': 30},
        {'width': 1920, 'height': 1080, 'fps': 60},
    ]
    mode = pick_mode(
        params, capacity_kbps=3000.0, fps_ceiling=60.0, bpp=0.07, motion=1.0
    )
    assert mode == {'width': 1280, 'height': 720, 'fps': 30}


def test_pick_mode_respects_fps_ceiling():
    params = [
        {'width': 1280, 'height': 720, 'fps': 15},
        {'width': 1280, 'height': 720, 'fps': 30},
    ]
    mode = pick_mode(
        params, capacity_kbps=3000.0, fps_ceiling=20.0, bpp=0.07, motion=1.0
    )
    assert mode == {'width': 1280, 'height': 720, 'fps': 15}


def test_pick_mode_falls_back_to_minimal_when_channel_too_narrow():
    params = [
        {'width': 640, 'height': 480, 'fps': 30},
        {'width': 1280, 'height': 720, 'fps': 30},
        {'width': 1920, 'height': 1080, 'fps': 60},
    ]
    mode = pick_mode(params, capacity_kbps=10.0, fps_ceiling=60.0, bpp=0.07, motion=1.0)
    assert mode == {'width': 640, 'height': 480, 'fps': 30}


def test_pick_mode_ignores_malformed_entries():
    params = [
        {'width': 'x', 'height': 480, 'fps': 30},
        {'height': 480, 'fps': 30},
        {'width': 1280, 'height': 720, 'fps': 30},
    ]
    mode = pick_mode(
        params, capacity_kbps=3000.0, fps_ceiling=60.0, bpp=0.07, motion=1.0
    )
    assert mode == {'width': 1280, 'height': 720, 'fps': 30}


_PARAMS = [
    {'width': 640, 'height': 480, 'fps': 30},
    {'width': 1280, 'height': 720, 'fps': 30},
]


def test_advisor_silent_before_min_history():
    advisor = Advisor(bpp=0.07, motion=1.0)
    advisor.start_session(now=0.0)
    rec = advisor.update(_snap(), _PARAMS, None, fps_rendered=30.0, now=5.0)
    assert rec is None


def test_advisor_silent_without_bitrate_data():
    advisor = Advisor(bpp=0.07, motion=1.0)
    advisor.start_session(now=0.0)
    rec = advisor.update(
        _snap(bitrate_in_kbps=0.0), _PARAMS, None, fps_rendered=30.0, now=20.0
    )
    assert rec is None


def test_advisor_silent_without_params():
    advisor = Advisor(bpp=0.07, motion=1.0)
    advisor.start_session(now=0.0)
    rec = advisor.update(_snap(), [], None, fps_rendered=30.0, now=20.0)
    assert rec is None


def test_advisor_hysteresis_needs_two_confirming_ticks(monkeypatch):
    """Гистерезис проверяем отдельно от сглаживания ёмкости: pick_mode подменён."""
    assert CONFIRM_TICKS == 2
    import mavixdesktop.ui.managers.advisor as advisor_module

    outputs = iter(
        [
            {'width': 640, 'height': 480, 'fps': 30},
            {'width': 640, 'height': 480, 'fps': 30},
            {'width': 1280, 'height': 720, 'fps': 30},
            {'width': 1280, 'height': 720, 'fps': 30},
        ]
    )
    monkeypatch.setattr(advisor_module, 'pick_mode', lambda *a, **k: next(outputs))

    advisor = Advisor(bpp=0.07, motion=1.0)
    advisor.start_session(now=0.0)

    snap = _snap(bitrate_in_kbps=2000.0)

    # первый тик после разогрева ещё не даёт рекомендации — только копит streak
    assert advisor.update(snap, _PARAMS, None, 30.0, now=10.0) is None
    first = advisor.update(snap, _PARAMS, None, 30.0, now=11.0)
    assert first is not None
    assert (first.width, first.height) == (640, 480)

    # смена условий на один тик рекомендацию ещё не меняет
    second = advisor.update(snap, _PARAMS, None, 30.0, now=12.0)
    assert (second.width, second.height) == (640, 480)

    # два одинаковых тика подряд — рекомендация меняется
    third = advisor.update(snap, _PARAMS, None, 30.0, now=13.0)
    assert (third.width, third.height) == (1280, 720)


def test_format_advice_empty_for_none():
    assert format_advice(None, None) == ''


def test_format_advice_has_both_lines_and_fits_note():
    from mavixdesktop.ui.managers.advisor import Recommendation

    rec = Recommendation(
        width=1280,
        height=720,
        fps=30,
        required_kbps=3870.72,
        capacity_kbps=4200.0,
        current_required_kbps=8709.12,
        fits=True,
    )
    text = format_advice(rec, {'width': 1920, 'height': 1080, 'fps': 30})
    assert 'рекомендуется' in text
    assert 'сейчас' in text
    assert '1280x720@30' in text
    assert '1920x1080@30' in text
    assert 'не тянет' not in text


def test_format_advice_marks_when_even_minimum_does_not_fit():
    from mavixdesktop.ui.managers.advisor import Recommendation

    rec = Recommendation(
        width=640,
        height=480,
        fps=15,
        required_kbps=201.6,
        capacity_kbps=50.0,
        current_required_kbps=0.0,
        fits=False,
    )
    text = format_advice(rec, None)
    assert 'не тянет даже минимум' in text


_MODES = [
    {'width': 640, 'height': 480, 'fps': 30},
    {'width': 1280, 'height': 720, 'fps': 30},
    {'width': 1920, 'height': 1080, 'fps': 30},
]


def _advise(snap: LinkSnapshot, current: dict[str, int], ticks: int = 24):
    adv = Advisor(bpp=0.07, motion=2.0)
    adv.start_session(0.0)
    rec = None
    for i in range(1, ticks + 1):
        rec = adv.update(snap, _MODES, current, 30.0, i * 5.0)
    return rec


def test_working_mode_is_not_downgraded_just_for_lack_of_headroom():
    """720p на 4 Мбит/с работает; запас в 25 % не набирается, но понижать нечего."""
    rec = _advise(
        _snap(bitrate_in_kbps=4000.0, loss_pct=1.0, rtt_p95_ms=50.0), _MODES[1]
    )
    assert rec is not None
    assert (rec.width, rec.height) == (1280, 720)
    assert rec.fits


def test_mode_is_downgraded_when_it_stops_fitting():
    rec = _advise(
        _snap(bitrate_in_kbps=1200.0, loss_pct=8.0, rtt_p95_ms=180.0, rtt_growth=2.0),
        _MODES[1],
    )
    assert rec is not None
    assert (rec.width, rec.height) == (640, 480)


def test_upgrade_is_offered_only_after_the_channel_stays_clean():
    rec = _advise(
        _snap(bitrate_in_kbps=6000.0, loss_pct=0.0, rtt_p95_ms=30.0), _MODES[0]
    )
    assert rec is not None
    assert (rec.width, rec.height) == (1280, 720)


def test_alarm_only_when_even_the_smallest_mode_does_not_fit():
    rec = _advise(
        _snap(bitrate_in_kbps=300.0, loss_pct=12.0, rtt_p95_ms=300.0, rtt_growth=3.0),
        _MODES[1],
    )
    assert rec is not None
    assert not rec.fits
    assert 'не тянет' in format_advice(rec, _MODES[1])
