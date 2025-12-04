import asyncio

import pytest

from github_top.github.rate_limit import RateLimiter


class FakeTime:
    def __init__(self) -> None:
        self.now = 100.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, delay: float) -> None:
        self.sleeps.append(round(delay, 6))


async def test_spreads_concurrent_calls_evenly():
    time = FakeTime()
    limiter = RateLimiter(rps=4, clock=time.clock, sleep=time.sleep)

    await asyncio.gather(*(limiter.acquire() for _ in range(5)))

    assert sorted(time.sleeps) == [0.25, 0.5, 0.75, 1.0]


async def test_does_not_wait_when_calls_are_rare():
    time = FakeTime()
    limiter = RateLimiter(rps=10, clock=time.clock, sleep=time.sleep)

    await limiter.acquire()
    time.now += 1
    await limiter.acquire()

    assert time.sleeps == []


def test_rejects_non_positive_rps():
    with pytest.raises(ValueError):
        RateLimiter(rps=0)
