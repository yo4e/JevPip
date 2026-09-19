from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any


@dataclass(frozen=True, slots=True)
class MarketTick:
    instrument_id: str
    symbol: str
    display_symbol: str
    bid: Decimal
    ask: Decimal
    market_timestamp: datetime
    received_at: datetime
    price_unit: Decimal = Decimal("0.01")
    move_unit_label: str = "pips"
    status: str = "UNKNOWN"
    raw: dict[str, Any] | None = None

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid

    @property
    def spread_units(self) -> Decimal:
        return self.spread / self.price_unit

    @property
    def spread_pips(self) -> Decimal:
        """Backward-compatible alias. For non-FX instruments this is a generic move unit."""
        return self.spread_units

    def as_json_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "display_symbol": self.display_symbol,
            "bid": str(self.bid),
            "ask": str(self.ask),
            "market_timestamp": self.market_timestamp.astimezone(timezone.utc).isoformat(),
            "received_at": self.received_at.astimezone(timezone.utc).isoformat(),
            "price_unit": str(self.price_unit),
            "move_unit_label": self.move_unit_label,
            "status": self.status,
            "raw": self.raw,
        }
