import asyncio
import time
from collections.abc import Awaitable, Callable


class RateLimiter:
    """Ограничение частоты запросов (RPS) по равномерному расписанию слотов.

    Каждый вызов `acquire` резервирует под блокировкой ближайший свободный слот и спит до него,
    поэтому конкурентные корутины не стартуют пачкой, а распределяются с шагом `1 / rps`.
    """

    def __init__(
        self,
        rps: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if rps <= 0:
            raise ValueError("rps должен быть больше нуля")
        self._interval = 1.0 / rps
        self._clock = clock
        self._sleep = sleep
        self._next_slot = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = self._clock()
            slot = max(now, self._next_slot)
            self._next_slot = slot + self._interval
        if (delay := slot - now) > 0:
            await self._sleep(delay)
