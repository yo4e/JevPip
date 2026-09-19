from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import httpx

PUBLIC_REST_URL = "https://forex-api.coin.z.com/public"
PriceType = Literal["BID", "ASK"]


@dataclass(frozen=True, slots=True)
class KLine:
    open_time_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


def fetch_klines(date: str, price_type: PriceType, symbol: str = "USD_JPY", interval: str = "1min") -> list[KLine]:
    response = httpx.get(
        f"{PUBLIC_REST_URL}/v1/klines",
        params={"symbol": symbol, "priceType": price_type, "interval": interval, "date": date},
        timeout=20.0,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("status") != 0:
        raise RuntimeError(f"GMO KLine API error: {body}")
    return [
        KLine(
            open_time_ms=int(row["openTime"]),
            open=Decimal(str(row["open"])),
            high=Decimal(str(row["high"])),
            low=Decimal(str(row["low"])),
            close=Decimal(str(row["close"])),
        )
        for row in body.get("data", [])
    ]
