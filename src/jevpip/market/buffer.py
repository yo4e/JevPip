from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from decimal import Decimal

from .models import MarketTick


class TickBuffer:
    def __init__(self, max_age_seconds: int = 3600, max_items: int = 200_000) -> None:
        self.max_age_seconds = max_age_seconds
        self._ticks: deque[MarketTick] = deque(maxlen=max_items)

    def append(self, tick: MarketTick) -> None:
        self._ticks.append(tick)
        cutoff = tick.market_timestamp - timedelta(seconds=self.max_age_seconds)
        while self._ticks and self._ticks[0].market_timestamp < cutoff:
            self._ticks.popleft()

    def __len__(self) -> int:
        return len(self._ticks)

    def mids(self) -> list[Decimal]:
        return [tick.mid for tick in self._ticks]

    def ticks_since(self, now: datetime, seconds: int) -> list[MarketTick]:
        cutoff = now - timedelta(seconds=seconds)
        return [tick for tick in self._ticks if cutoff <= tick.market_timestamp <= now]

    def at_or_before(self, target: datetime) -> MarketTick | None:
        for tick in reversed(self._ticks):
            if tick.market_timestamp <= target:
                return tick
        return None
