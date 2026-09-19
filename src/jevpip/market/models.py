from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class MarketTick:
    symbol: str
    bid: Decimal
    ask: Decimal
    market_timestamp: datetime
    received_at: datetime
    status: str = "UNKNOWN"
    raw: dict[str, Any] | None = None

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def spread_pips(self) -> Decimal:
        # JPY pairs: 1 pip = 0.01 yen.
        return self.spread / Decimal("0.01")

    def as_json_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "bid": str(self.bid),
            "ask": str(self.ask),
            "market_timestamp": self.market_timestamp.astimezone(timezone.utc).isoformat(),
            "received_at": self.received_at.astimezone(timezone.utc).isoformat(),
            "status": self.status,
            "raw": self.raw,
        }
