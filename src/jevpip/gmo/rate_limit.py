from __future__ import annotations

from collections import deque
import threading
import time
from collections.abc import Callable


class SlidingWindowRateLimiter:
    """Small synchronous sliding-window limiter for REST clients."""

    def __init__(
        self,
        max_calls: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_calls <= 0:
            raise ValueError("max_calls must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self._clock = clock
        self._sleep = sleep
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            wait = 0.0
            with self._lock:
                now = self._clock()
                cutoff = now - self.window_seconds
                while self._calls and self._calls[0] <= cutoff:
                    self._calls.popleft()

                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return

                wait = max(0.0, self._calls[0] + self.window_seconds - now)

            if wait > 0:
                self._sleep(wait)
            else:
                # Avoid a tight loop with coarse or injected clocks.
                self._sleep(0.001)
