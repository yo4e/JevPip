from __future__ import annotations

from decimal import Decimal
from typing import Any


def _finite_positive(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except Exception:
        return None
    if not result.is_finite() or result <= 0:
        return None
    return result


def build_event_reference_levels(
    *,
    bid: Decimal,
    ask: Decimal,
    price_unit: Decimal,
    timeframes: dict[str, Any],
    round_trip_cost_per_unit: Decimal,
) -> dict[str, Decimal]:
    """Create bounded reference levels from information already visible to Jev.

    These are not predictions. They are code-generated menu anchors so Jev can
    choose a typed price-cross plan without emitting arbitrary numeric strings.
    """
    mid = (bid + ask) / 2
    one = timeframes.get("1min", {}) if isinstance(timeframes, dict) else {}
    five = timeframes.get("5min", {}) if isinstance(timeframes, dict) else {}
    one_ind = one.get("indicators", {}) if isinstance(one, dict) else {}
    five_ind = five.get("indicators", {}) if isinstance(five, dict) else {}

    atr = _finite_positive(five_ind.get("atr14"))
    if atr is None:
        atr = _finite_positive(one_ind.get("atr14"))
    min_move = max(price_unit, round_trip_cost_per_unit * Decimal("1.5"))
    anchor_move = max(min_move, (atr or min_move) * Decimal("0.5"))

    highs = [
        _finite_positive(one_ind.get("recent_20_high")),
        _finite_positive(five_ind.get("recent_20_high")),
    ]
    lows = [
        _finite_positive(one_ind.get("recent_20_low")),
        _finite_positive(five_ind.get("recent_20_low")),
    ]
    upper_candidates = [value for value in highs if value is not None and value > mid]
    lower_candidates = [value for value in lows if value is not None and value < mid]
    upper = min(upper_candidates) if upper_candidates else mid + anchor_move
    lower = max(lower_candidates) if lower_candidates else mid - anchor_move
    if upper <= ask:
        upper = ask + anchor_move
    if lower >= bid:
        lower = bid - anchor_move
    lower = max(price_unit, lower)

    return {
        "mid": mid,
        "upper": upper,
        "lower": lower,
        "atr": atr or anchor_move * 2,
        "anchor_move": anchor_move,
    }


def build_event_risk_profiles(
    *,
    price_unit: Decimal,
    round_trip_cost_per_unit: Decimal,
    reference_atr: Decimal,
) -> dict[str, dict[str, float]]:
    """Return a small typed menu of net-PnL stop widths and RR choices."""
    cost_units = round_trip_cost_per_unit / price_unit
    atr_units = reference_atr / price_unit
    base_stop = max(
        Decimal("1"),
        cost_units * Decimal("2"),
        atr_units * Decimal("0.5"),
    )
    specs = {
        "TIGHT": (Decimal("0.75"), Decimal("1.25")),
        "BASE": (Decimal("1.0"), Decimal("1.5")),
        "WIDE": (Decimal("1.5"), Decimal("2.0")),
    }
    result: dict[str, dict[str, float]] = {}
    for name, (stop_scale, rr) in specs.items():
        stop = max(cost_units * Decimal("1.25"), base_stop * stop_scale)
        take = stop * rr
        result[name] = {
            "stop_loss_units": round(float(stop), 6),
            "take_profit_units": round(float(take), 6),
            "risk_reward": float(rr),
        }
    return result


def build_event_wake_plans(levels: dict[str, Decimal]) -> dict[str, dict[str, Any]]:
    return {
        "PRICE_ABOVE": {
            "type": "price_cross_above",
            "price": str(levels["upper"]),
            "description": "Wake when MID crosses above the supplied upper reference.",
        },
        "PRICE_BELOW": {
            "type": "price_cross_below",
            "price": str(levels["lower"]),
            "description": "Wake when MID crosses below the supplied lower reference.",
        },
        "BAR_1M_1": {
            "type": "bar_close",
            "timeframe": "1min",
            "bars": 1,
            "description": "Wake after one additional 1-minute bar closes.",
        },
        "BAR_5M_1": {
            "type": "bar_close",
            "timeframe": "5min",
            "bars": 1,
            "description": "Wake after one additional 5-minute bar closes.",
        },
        "BAR_5M_3": {
            "type": "bar_close",
            "timeframe": "5min",
            "bars": 3,
            "description": "Wake after three additional 5-minute bars close.",
        },
        "BAR_15M_1": {
            "type": "bar_close",
            "timeframe": "15min",
            "bars": 1,
            "description": "Wake after one additional 15-minute bar closes.",
        },
        "TIMEOUT_5M": {
            "type": "timeout",
            "seconds": 300,
            "description": "Wake after five minutes even if no other event happens.",
        },
        "TIMEOUT_15M": {
            "type": "timeout",
            "seconds": 900,
            "description": "Wake after fifteen minutes even if no other event happens.",
        },
        "TIMEOUT_30M": {
            "type": "timeout",
            "seconds": 1800,
            "description": "Wake after thirty minutes even if no other event happens.",
        },
    }
