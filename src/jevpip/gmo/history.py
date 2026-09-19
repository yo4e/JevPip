from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import httpx

from jevpip.gmo.public_rest import fetch_klines
from jevpip.instruments import get_instrument

CRYPTO_PUBLIC_REST_URL = "https://api.coin.z.com/public"


@dataclass(frozen=True, slots=True)
class HistoryCandle:
    open_time_ms: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


def _crypto_klines(date: str, interval: str, symbol: str) -> list[HistoryCandle]:
    response = httpx.get(
        f"{CRYPTO_PUBLIC_REST_URL}/v1/klines",
        params={"symbol": symbol, "interval": interval, "date": date},
        timeout=20.0,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("status") != 0:
        raise RuntimeError(f"GMO crypto KLine API error: {body}")
    return [
        HistoryCandle(
            open_time_ms=int(row["openTime"]),
            open=Decimal(str(row["open"])),
            high=Decimal(str(row["high"])),
            low=Decimal(str(row["low"])),
            close=Decimal(str(row["close"])),
        )
        for row in body.get("data", [])
    ]


def fetch_history(
    instrument_id: str,
    date: str,
    interval: str = "1min",
) -> list[HistoryCandle]:
    instrument = get_instrument(instrument_id)
    if instrument.market_kind == "crypto_spot":
        return _crypto_klines(date, interval, instrument.api_symbol)

    bids = {item.open_time_ms: item for item in fetch_klines(date, "BID", instrument.api_symbol, interval)}
    asks = {item.open_time_ms: item for item in fetch_klines(date, "ASK", instrument.api_symbol, interval)}
    candles: list[HistoryCandle] = []
    two = Decimal("2")
    for key in sorted(bids.keys() & asks.keys()):
        bid = bids[key]
        ask = asks[key]
        candles.append(
            HistoryCandle(
                open_time_ms=key,
                open=(bid.open + ask.open) / two,
                high=(bid.high + ask.high) / two,
                low=(bid.low + ask.low) / two,
                close=(bid.close + ask.close) / two,
            )
        )
    return candles
