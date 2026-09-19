from __future__ import annotations

from jevpip.gmo.rate_limit import SlidingWindowRateLimiter


def test_rate_limiter_allows_calls_within_limit_without_sleep():
    now = [0.0]
    sleeps: list[float] = []

    limiter = SlidingWindowRateLimiter(
        2,
        1.0,
        clock=lambda: now[0],
        sleep=lambda seconds: sleeps.append(seconds),
    )
    limiter.acquire()
    limiter.acquire()

    assert sleeps == []


def test_rate_limiter_waits_until_oldest_call_expires():
    now = [0.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = SlidingWindowRateLimiter(
        2,
        1.0,
        clock=lambda: now[0],
        sleep=sleep,
    )
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()

    assert sleeps == [1.0]
    assert now[0] == 1.0


def test_rate_limiter_rejects_invalid_config():
    import pytest

    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(0, 1)
    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(1, 0)
