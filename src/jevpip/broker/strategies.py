from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Sequence

from jevpip.market.features import rsi

Signal = Literal["LONG", "SHORT", "WAIT"]
StrategyName = Literal["momentum", "rsi_mean_reversion", "ma_trend", "jev"]


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    signal: Signal
    reason: str
    metrics: dict[str, float | int | str | None]


PricePoint = tuple[datetime, Decimal]


def momentum_signal(
    prices: Sequence[PricePoint],
    *,
    at: datetime,
    mid: Decimal,
    price_unit: Decimal,
    window_seconds: float,
    trigger_units: float,
) -> StrategyDecision:
    previous: Decimal | None = None
    for seen_at, seen_mid in reversed(prices):
        if (at - seen_at).total_seconds() >= window_seconds:
            previous = seen_mid
            break
    if previous is None:
        return StrategyDecision("WAIT", "momentum_warmup", {"window_seconds": window_seconds})

    move_units = (mid - previous) / price_unit
    trigger = Decimal(str(trigger_units))
    signal: Signal = "WAIT"
    if move_units >= trigger:
        signal = "LONG"
    elif move_units <= -trigger:
        signal = "SHORT"
    return StrategyDecision(
        signal,
        "momentum",
        {
            "window_seconds": window_seconds,
            "move_units": round(float(move_units), 6),
            "trigger_units": float(trigger),
        },
    )


def rsi_mean_reversion_signal(
    prices: Sequence[PricePoint],
    *,
    period: int,
    oversold: float,
    overbought: float,
) -> StrategyDecision:
    values = [mid for _, mid in prices]
    value = rsi(values, period)
    if value is None:
        return StrategyDecision("WAIT", "rsi_warmup", {"period": period, "rsi": None})

    signal: Signal = "WAIT"
    if value <= oversold:
        signal = "LONG"
    elif value >= overbought:
        signal = "SHORT"
    return StrategyDecision(
        signal,
        "rsi_mean_reversion",
        {
            "period": period,
            "rsi": value,
            "oversold": oversold,
            "overbought": overbought,
            "semantics": "tick_count",
        },
    )


def ma_trend_signal(
    prices: Sequence[PricePoint],
    *,
    price_unit: Decimal,
    fast_period: int,
    slow_period: int,
    min_gap_units: float,
) -> StrategyDecision:
    if fast_period <= 0 or slow_period <= 0 or fast_period >= slow_period:
        return StrategyDecision("WAIT", "ma_invalid_config", {})
    if len(prices) < slow_period:
        return StrategyDecision(
            "WAIT",
            "ma_warmup",
            {"fast_period": fast_period, "slow_period": slow_period},
        )

    values = [mid for _, mid in prices]
    fast = sum(values[-fast_period:]) / Decimal(fast_period)
    slow = sum(values[-slow_period:]) / Decimal(slow_period)
    gap_units = (fast - slow) / price_unit
    threshold = Decimal(str(min_gap_units))

    signal: Signal = "WAIT"
    if gap_units >= threshold:
        signal = "LONG"
    elif gap_units <= -threshold:
        signal = "SHORT"

    return StrategyDecision(
        signal,
        "ma_trend",
        {
            "fast_period": fast_period,
            "slow_period": slow_period,
            "fast": round(float(fast), 8),
            "slow": round(float(slow), 8),
            "gap_units": round(float(gap_units), 6),
            "min_gap_units": float(threshold),
            "semantics": "tick_count",
        },
    )
