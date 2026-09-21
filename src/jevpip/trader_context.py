from __future__ import annotations

from datetime import datetime
from statistics import fmean
from typing import Any
from zoneinfo import ZoneInfo


TIMEFRAME_SPECS: dict[str, dict[str, int]] = {
    "1min": {"seconds": 60, "display_bars": 60},
    "5min": {"seconds": 300, "display_bars": 48},
    "15min": {"seconds": 900, "display_bars": 32},
    "1hour": {"seconds": 3600, "display_bars": 24},
}
INDICATOR_HISTORY_BARS = 240


def market_clock(as_of: datetime) -> dict[str, Any]:
    if as_of.tzinfo is None:
        raise ValueError("market clock requires timezone-aware datetime")
    zones = {
        "utc": ZoneInfo("UTC"),
        "tokyo": ZoneInfo("Asia/Tokyo"),
        "london": ZoneInfo("Europe/London"),
        "new_york": ZoneInfo("America/New_York"),
    }
    return {
        key: {
            "timestamp": as_of.astimezone(zone).isoformat(),
            "weekday": as_of.astimezone(zone).strftime("%A"),
        }
        for key, zone in zones.items()
    }


def _sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return round(fmean(closes[-period:]), 8)


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    changes = [
        closes[index] - closes[index - 1]
        for index in range(len(closes) - period, len(closes))
    ]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = fmean(gains)
    average_loss = fmean(losses)
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    relative_strength = average_gain / average_loss
    return round(100 - 100 / (1 + relative_strength), 4)


def _atr(bars: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(bars) < period + 1:
        return None
    selected = bars[-(period + 1):]
    true_ranges: list[float] = []
    for previous, current in zip(selected, selected[1:]):
        high = float(current["high"])
        low = float(current["low"])
        previous_close = float(previous["close"])
        true_ranges.append(
            max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        )
    return round(fmean(true_ranges), 8)


def build_timeframe_view(
    interval: str,
    closed_bars: list[dict[str, Any]],
    *,
    current_bar: dict[str, Any] | None,
) -> dict[str, Any]:
    if interval not in TIMEFRAME_SPECS:
        raise ValueError(f"unsupported timeframe: {interval}")
    closed = sorted(closed_bars, key=lambda row: row["open_time"])
    closes = [float(row["close"]) for row in closed]
    display_limit = TIMEFRAME_SPECS[interval]["display_bars"]
    recent = closed[-display_limit:]

    window = closed[-20:]
    recent_high = max((float(row["high"]) for row in window), default=None)
    recent_low = min((float(row["low"]) for row in window), default=None)
    reference = (
        float(current_bar["close"])
        if current_bar is not None
        else (closes[-1] if closes else None)
    )
    range_position = None
    if (
        reference is not None
        and recent_high is not None
        and recent_low is not None
        and recent_high > recent_low
    ):
        range_position = round(
            (reference - recent_low) / (recent_high - recent_low),
            6,
        )

    return {
        "interval": interval,
        "closed_bars_available": len(closed),
        "closed_bars": recent,
        "current_bar": current_bar,
        "indicators": {
            "sma20": _sma(closes, 20),
            "sma50": _sma(closes, 50),
            "sma200": _sma(closes, 200),
            "rsi14": _rsi(closes, 14),
            "atr14": _atr(closed, 14),
            "recent_20_high": (
                None if recent_high is None else round(recent_high, 8)
            ),
            "recent_20_low": (
                None if recent_low is None else round(recent_low, 8)
            ),
            "range_position_20": range_position,
        },
    }
