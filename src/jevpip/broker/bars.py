from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class TimeBar:
    start: datetime
    end: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    tick_count: int

    def as_dict(self) -> dict[str, object]:
        return {
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "tick_count": self.tick_count,
        }


class TimeBarBuilder:
    """Build fixed-duration OHLC bars from timestamped prices.

    Empty intervals are not synthesized. A gap simply closes the previous bar
    when the next tick arrives and starts a new bar in the new bucket.
    """

    def __init__(self, interval_seconds: int) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.interval_seconds = interval_seconds
        self._current: TimeBar | None = None

    @staticmethod
    def _utc(at: datetime) -> datetime:
        if at.tzinfo is None:
            return at.replace(tzinfo=timezone.utc)
        return at.astimezone(timezone.utc)

    def _bounds(self, at: datetime) -> tuple[datetime, datetime]:
        at = self._utc(at)
        epoch = int(at.timestamp())
        start_epoch = epoch - (epoch % self.interval_seconds)
        start = datetime.fromtimestamp(start_epoch, tz=timezone.utc)
        return start, start + timedelta(seconds=self.interval_seconds)

    @property
    def current(self) -> TimeBar | None:
        return self._current

    def update(self, at: datetime, price: Decimal) -> list[TimeBar]:
        start, end = self._bounds(at)
        completed: list[TimeBar] = []

        if self._current is None:
            self._current = TimeBar(
                start=start,
                end=end,
                open=price,
                high=price,
                low=price,
                close=price,
                tick_count=1,
            )
            return completed

        if start < self._current.start:
            raise ValueError("Ticks must be supplied in non-decreasing time order")

        if start != self._current.start:
            completed.append(self._current)
            self._current = TimeBar(
                start=start,
                end=end,
                open=price,
                high=price,
                low=price,
                close=price,
                tick_count=1,
            )
            return completed

        current = self._current
        self._current = TimeBar(
            start=current.start,
            end=current.end,
            open=current.open,
            high=max(current.high, price),
            low=min(current.low, price),
            close=price,
            tick_count=current.tick_count + 1,
        )
        return completed

    def flush(self) -> TimeBar | None:
        current = self._current
        self._current = None
        return current
