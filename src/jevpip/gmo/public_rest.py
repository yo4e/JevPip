from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import httpx

from jevpip.instruments import get_instrument

PUBLIC_REST_URL = "https://forex-api.coin.z.com/public"
CRYPTO_PUBLIC_REST_URL = "https://api.coin.z.com/public"
PriceType = Literal["BID", "ASK"]


@dataclass(frozen=True, slots=True)
class KLine:
    open_time_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True, slots=True)
class PublicTicker:
    instrument_id: str
    symbol: str
    bid: Decimal
    ask: Decimal
    timestamp: str
    status: str


def fetch_public_ticker(instrument_id: str) -> PublicTicker:
    """Fetch a read-only latest quote for pre-start UI preview."""
    instrument = get_instrument(instrument_id)
    if instrument.market_kind == "crypto_spot":
        endpoint = CRYPTO_PUBLIC_REST_URL
        params: dict[str, str] | None = {"symbol": instrument.api_symbol}
    else:
        endpoint = PUBLIC_REST_URL
        # GMO FX ticker returns all symbols in one response.
        params = None

    response = httpx.get(
        f"{endpoint}/v1/ticker",
        params=params,
        timeout=10.0,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("status") != 0:
        raise RuntimeError(f"GMO ticker API error: {body}")

    row = next(
        (
            item
            for item in body.get("data", [])
            if item.get("symbol") == instrument.api_symbol
        ),
        None,
    )
    if row is None:
        raise RuntimeError(f"GMO ticker has no {instrument.api_symbol} quote")

    bid = Decimal(str(row["bid"]))
    ask = Decimal(str(row["ask"]))
    if ask < bid:
        raise RuntimeError(f"GMO ticker returned crossed quote for {instrument.api_symbol}")

    return PublicTicker(
        instrument_id=instrument.id,
        symbol=instrument.api_symbol,
        bid=bid,
        ask=ask,
        timestamp=str(row["timestamp"]),
        status=str(row.get("status") or "OPEN"),
    )


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
