from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jevpip.gmo.history import fetch_history
from jevpip.gmo.public_rest import fetch_klines
from jevpip.instruments import get_instrument
from jevpip.market.buffer import TickBuffer
from jevpip.market.features import build_features
from jevpip.market.models import MarketTick
from jevpip.storage.jsonl import append_jsonl


def _pair(date: str, symbol: str) -> list[tuple[Any, Any]]:
    bid = {x.open_time_ms: x for x in fetch_klines(date, "BID", symbol)}
    ask = {x.open_time_ms: x for x in fetch_klines(date, "ASK", symbol)}
    return [(bid[key], ask[key]) for key in sorted(bid.keys() & ask.keys())]


def replay_kline(
    date: str,
    profile: dict[str, Any],
    output: Path | None = None,
    limit: int | None = None,
    instrument_id: str = "USD_JPY",
) -> list[dict[str, Any]]:
    """Replay 1-minute historical closes through the feature pipeline.

    FX uses paired BID/ASK closes, so spread-aware 1-minute edge can be measured.
    Crypto historical KLine is OHLC-only, so it is replayed as close-to-close
    midpoint research data and does not pretend to contain historical spread.
    """
    instrument = get_instrument(instrument_id)

    rows: list[dict[str, Any]] = []
    ticks: list[MarketTick] = []
    buffer = TickBuffer(max_age_seconds=86_400)

    if instrument.market_kind == "fx":
        pairs = _pair(date, instrument.api_symbol)
        if limit is not None:
            pairs = pairs[:limit]

        for bid, ask in pairs:
            at = datetime.fromtimestamp(
                bid.open_time_ms / 1000,
                tz=timezone.utc,
            ) + timedelta(minutes=1)
            tick = MarketTick(
                instrument_id=instrument.id,
                symbol=instrument.api_symbol,
                display_symbol=instrument.display_symbol,
                bid=bid.close,
                ask=ask.close,
                market_timestamp=at,
                received_at=at,
                price_unit=instrument.price_unit,
                move_unit_label=instrument.move_unit_label,
                status="HISTORICAL",
                raw=None,
            )
            buffer.append(tick)
            ticks.append(tick)
            rows.append(
                {
                    "timestamp": at.isoformat(),
                    "features": build_features(tick, buffer, profile),
                    "replay_mode": "fx_bid_ask_close",
                }
            )

        for idx, row in enumerate(rows[:-1]):
            current = ticks[idx]
            future = ticks[idx + 1]
            delta = (future.mid - current.mid) / instrument.price_unit
            long_edge = (future.bid - current.ask) / instrument.price_unit
            short_edge = (current.bid - future.ask) / instrument.price_unit
            row["outcome_1m"] = {
                "delta_units": float(delta),
                "long_edge_units": float(long_edge),
                "short_edge_units": float(short_edge),
            }
    else:
        candles = fetch_history(instrument_id, date, "1min")
        if limit is not None:
            candles = candles[:limit]

        for candle in candles:
            at = datetime.fromtimestamp(
                candle.open_time_ms / 1000,
                tz=timezone.utc,
            ) + timedelta(minutes=1)
            # Crypto public historical KLine has OHLC but no historical BID/ASK.
            # Use close as a synthetic midpoint only for feature / direction replay.
            tick = MarketTick(
                instrument_id=instrument.id,
                symbol=instrument.api_symbol,
                display_symbol=instrument.display_symbol,
                bid=candle.close,
                ask=candle.close,
                market_timestamp=at,
                received_at=at,
                price_unit=instrument.price_unit,
                move_unit_label=instrument.move_unit_label,
                status="HISTORICAL",
                raw=None,
            )
            buffer.append(tick)
            ticks.append(tick)
            rows.append(
                {
                    "timestamp": at.isoformat(),
                    "features": build_features(tick, buffer, profile),
                    "replay_mode": "crypto_close_only",
                }
            )

        for idx, row in enumerate(rows[:-1]):
            current = ticks[idx]
            future = ticks[idx + 1]
            delta = (future.mid - current.mid) / instrument.price_unit
            row["outcome_1m"] = {
                "delta_units": float(delta),
                "long_edge_units": None,
                "short_edge_units": None,
            }

    if rows:
        rows[-1]["outcome_1m"] = None

    if output is not None:
        for row in rows:
            append_jsonl(output, row)
    return rows

