"""StatsCollector: cumulative counters -> rates, with aiortc's quirks accounted for."""

from __future__ import annotations

import pytest

from mavixdesktop.webrtc.stats import StatsCollector, read_totals, to_sample


class FakeEntry:
    def __init__(self, **kwargs) -> None:
        self.__dict__.update(kwargs)


class FakeReport(dict):
    pass


def _report(*entries) -> FakeReport:
    report = FakeReport()
    for i, entry in enumerate(entries):
        report[str(i)] = entry
    return report


def test_inbound_packets_and_transport_bytes_are_summed():
    report = _report(
        FakeEntry(type='inbound-rtp', packetsReceived=100, packetsLost=5),
        FakeEntry(type='inbound-rtp', packetsReceived=50, packetsLost=1),
        FakeEntry(type='transport', bytesReceived=1_000_000),
    )
    totals = read_totals(report, now=10.0)
    assert (totals.packets_received, totals.packets_lost) == (150, 6)
    assert totals.bytes_received == 1_000_000


def test_unknown_entries_are_ignored():
    report = _report(
        FakeEntry(type='outbound-rtp', packetsSent=999), FakeEntry(type='codec')
    )
    totals = read_totals(report, now=1.0)
    assert (totals.packets_received, totals.bytes_received) == (0, 0)


def test_bitrate_and_loss_from_deltas():
    first = read_totals(
        _report(
            FakeEntry(type='inbound-rtp', packetsReceived=0, packetsLost=0),
            FakeEntry(type='transport', bytesReceived=0),
        ),
        now=0.0,
    )
    second = read_totals(
        _report(
            FakeEntry(type='inbound-rtp', packetsReceived=990, packetsLost=10),
            FakeEntry(type='transport', bytesReceived=250_000),
        ),
        now=1.0,
    )
    bitrate, loss = to_sample(first, second)
    assert bitrate == pytest.approx(2000.0)
    assert loss == pytest.approx(1.0)


def test_elapsed_is_used_not_assumed_one_second():
    first = read_totals(_report(FakeEntry(type='transport', bytesReceived=0)), now=0.0)
    second = read_totals(
        _report(FakeEntry(type='transport', bytesReceived=250_000)), now=2.0
    )
    bitrate, _ = to_sample(first, second)
    assert bitrate == pytest.approx(1000.0)


def test_negative_lost_delta_is_clamped():
    """packetsLost decreases when duplicates arrive — must not produce negative loss."""
    first = read_totals(
        _report(FakeEntry(type='inbound-rtp', packetsReceived=100, packetsLost=10)),
        now=0.0,
    )
    second = read_totals(
        _report(FakeEntry(type='inbound-rtp', packetsReceived=200, packetsLost=8)),
        now=1.0,
    )
    _, loss = to_sample(first, second)
    assert loss == 0.0


def test_zero_elapsed_is_safe():
    totals = read_totals(
        _report(FakeEntry(type='transport', bytesReceived=10)), now=5.0
    )
    assert to_sample(totals, totals) == (0.0, 0.0)


@pytest.mark.asyncio
async def test_first_poll_only_primes_the_baseline():
    samples: list = []

    class FakePc:
        def __init__(self) -> None:
            self.calls = 0

        async def getStats(self):
            self.calls += 1
            return _report(
                FakeEntry(type='transport', bytesReceived=125_000 * self.calls),
                FakeEntry(
                    type='inbound-rtp', packetsReceived=100 * self.calls, packetsLost=0
                ),
            )

    ticks = iter([0.0, 1.0])
    collector = StatsCollector(
        FakePc(),
        lambda bitrate, loss: samples.append((bitrate, loss)),
        clock=lambda: next(ticks),
    )
    await collector.poll_once()
    assert samples == []
    await collector.poll_once()
    assert samples[0][0] == pytest.approx(1000.0)
