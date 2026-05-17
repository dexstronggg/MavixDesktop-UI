import pytest

from mavixdesktop.core.backoff import ExponentialBackoff


def test_default_sequence():
    b = ExponentialBackoff()
    delays = [b.next_delay() for _ in range(7)]
    assert delays == [1.0, 2.0, 4.0, 8.0, 16.0, 30.0, 30.0]


def test_custom_params():
    b = ExponentialBackoff(initial=0.5, multiplier=3.0, cap=10.0)
    assert [b.next_delay() for _ in range(4)] == [0.5, 1.5, 4.5, 10.0]


def test_reset():
    b = ExponentialBackoff()
    for _ in range(5):
        b.next_delay()
    b.reset()
    assert b.next_delay() == 1.0


def test_validates_args():
    with pytest.raises(ValueError):
        ExponentialBackoff(initial=0)
    with pytest.raises(ValueError):
        ExponentialBackoff(multiplier=0.5)
    with pytest.raises(ValueError):
        ExponentialBackoff(initial=10, cap=5)
