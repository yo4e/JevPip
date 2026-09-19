from __future__ import annotations

from datetime import datetime, timezone, timedelta
from decimal import Decimal
from hashlib import sha256
from math import cos, pi
from statistics import pstdev
from typing import Any

from .buffer import TickBuffer
from .models import MarketTick

SYNODIC_MONTH_DAYS = 29.530588853
REFERENCE_NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)


def _round(value: Decimal | float, digits: int = 8) -> float:
    return round(float(value), digits)


def moon_features(at: datetime) -> dict[str, Any]:
    at = at.astimezone(timezone.utc)
    age_days = ((at - REFERENCE_NEW_MOON).total_seconds() / 86400.0) % SYNODIC_MONTH_DAYS
    fraction = age_days / SYNODIC_MONTH_DAYS
    illumination = (1.0 - cos(2 * pi * fraction)) / 2.0
    idx = int((fraction * 8) + 0.5) % 8
    phases = [
        "new_moon",
        "waxing_crescent",
        "first_quarter",
        "waxing_gibbous",
        "full_moon",
        "waning_gibbous",
        "last_quarter",
        "waning_crescent",
    ]
    return {
        "phase": phases[idx],
        "age_days": round(age_days, 3),
        "illumination": round(illumination, 4),
    }


def rsi(values: list[Decimal], period: int) -> float | None:
    if period <= 0 or len(values) < period + 1:
        return None
    recent = values[-(period + 1) :]
    gains: list[float] = []
    losses: list[float] = []
    for left, right in zip(recent, recent[1:]):
        delta = float(right - left)
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 4)


def build_features(tick: MarketTick, buffer: TickBuffer, profile: dict[str, Any]) -> dict[str, Any]:
    state: dict[str, Any] = {
        "symbol": tick.symbol,
        "timestamp": tick.market_timestamp.astimezone(timezone.utc).isoformat(),
    }

    if profile.get("quote", False):
        state["quote"] = {
            "bid": _round(tick.bid, 5),
            "ask": _round(tick.ask, 5),
            "mid": _round(tick.mid, 5),
            "spread_units": _round(tick.spread_units, 4),
            "spread_unit": tick.move_unit_label,
            "market_status": tick.status,
        }

    returns: dict[str, float | None] = {}
    for seconds in profile.get("returns_seconds", []):
        previous = buffer.at_or_before(tick.market_timestamp - timedelta(seconds=int(seconds)))
        returns[f"{seconds}s"] = None if previous is None else _round((tick.mid - previous.mid) / tick.price_unit, 4)
    if returns:
        state["move_units"] = {"unit": tick.move_unit_label, "values": returns}

    ranges: dict[str, float | None] = {}
    for seconds in profile.get("range_seconds", []):
        window = buffer.ticks_since(tick.market_timestamp, int(seconds))
        if len(window) < 2:
            ranges[f"{seconds}s"] = None
        else:
            mids = [x.mid for x in window]
            ranges[f"{seconds}s"] = _round((max(mids) - min(mids)) / tick.price_unit, 4)
    if ranges:
        state["range_units"] = {"unit": tick.move_unit_label, "values": ranges}

    counts: dict[str, int] = {}
    for seconds in profile.get("tick_count_seconds", []):
        counts[f"{seconds}s"] = len(buffer.ticks_since(tick.market_timestamp, int(seconds)))
    if counts:
        state["tick_count"] = counts

    vols: dict[str, float | None] = {}
    for seconds in profile.get("realized_vol_seconds", []):
        window = buffer.ticks_since(tick.market_timestamp, int(seconds))
        changes = [float((b.mid - a.mid) / tick.price_unit) for a, b in zip(window, window[1:])]
        vols[f"{seconds}s"] = round(pstdev(changes), 6) if len(changes) >= 2 else None
    if vols:
        state["realized_tick_vol_units"] = {"unit": tick.move_unit_label, "values": vols}

    period = int(profile.get("rsi_period", 0) or 0)
    if period:
        state["rsi"] = {"period": period, "value": rsi(buffer.mids(), period)}

    sma_periods = [int(x) for x in profile.get("sma_periods", [])]
    if sma_periods:
        mids = buffer.mids()
        state["sma"] = {
            str(period): None if len(mids) < period else _round(sum(mids[-period:]) / Decimal(period), 5)
            for period in sma_periods
        }

    if profile.get("moon_phase", False):
        state["moon"] = moon_features(tick.market_timestamp)

    if profile.get("random_control", False):
        bucket = int(tick.market_timestamp.timestamp()) // 60
        digest = sha256(f"jevpip-control:{bucket}".encode()).digest()
        state["random_control"] = {
            "bucket": int.from_bytes(digest[:2], "big") % 8,
            "value": round(int.from_bytes(digest[2:6], "big") / 2**32, 6),
        }

    return state
