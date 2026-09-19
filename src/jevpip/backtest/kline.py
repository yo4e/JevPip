from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from jevpip.gmo.public_rest import fetch_klines
from jevpip.instruments import get_instrument
from jevpip.market.buffer import TickBuffer
from jevpip.market.features import build_features
from jevpip.market.models import MarketTick
from jevpip.storage.jsonl import append_jsonl


def _pair(date: str) -> list[tuple[Any, Any]]:
    bid = {x.open_time_ms: x for x in fetch_klines(date, "BID")}
    ask = {x.open_time_ms: x for x in fetch_klines(date, "ASK")}
    return [(bid[key], ask[key]) for key in sorted(bid.keys() & ask.keys())]


def replay_kline(
    date: str,
    profile: dict[str, Any],
    output: Path | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Replay GMO 1-minute BID/ASK closes through the same feature pipeline.

    This is useful for coarse experiments only. It cannot validate 5-second paths.
    """
    pairs = _pair(date)
    if limit is not None:
        pairs = pairs[:limit]
    buffer = TickBuffer(max_age_seconds=86_400)
    rows: list[dict[str, Any]] = []
    ticks: list[MarketTick] = []

    for bid, ask in pairs:
        at = datetime.fromtimestamp(bid.open_time_ms / 1000, tz=timezone.utc) + timedelta(minutes=1)
        instrument = get_instrument("USD_JPY")
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
        rows.append({"timestamp": at.isoformat(), "features": build_features(tick, buffer, profile)})

    for idx, row in enumerate(rows[:-1]):
        current = ticks[idx]
        future = ticks[idx + 1]
        row["outcome_1m"] = {
            "delta_mid_pips": float((future.mid - current.mid) / Decimal("0.01")),
            "long_edge_pips": float((future.bid - current.ask) / Decimal("0.01")),
            "short_edge_pips": float((current.bid - future.ask) / Decimal("0.01")),
        }
    if rows:
        rows[-1]["outcome_1m"] = None

    if output is not None:
        for row in rows:
            append_jsonl(output, row)
    return rows
