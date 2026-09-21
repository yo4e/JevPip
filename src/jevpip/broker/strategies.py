from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Sequence

from jevpip.market.features import moon_features, rsi

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


def moon_phase_signal(*, at: datetime) -> StrategyDecision:
    """Deterministic lunar-cycle baseline; no predictive power is assumed."""
    moon = moon_features(at)
    phase = str(moon["phase"])
    # Fifty+-style experiment: always choose a direction. The first half of the
    # synodic cycle is UP/LONG, the second half is DOWN/SHORT.
    signal: Signal = "LONG" if float(moon["age_days"]) < 14.7652944265 else "SHORT"
    return StrategyDecision(
        signal,
        "moon_phase",
        {
            "phase": phase,
            "age_days": float(moon["age_days"]),
            "illumination": float(moon["illumination"]),
            "semantics": "experimental_spiritual_baseline",
        },
    )


_ZODIAC_STARTS = (
    ((1, 20), "aquarius"),
    ((2, 19), "pisces"),
    ((3, 21), "aries"),
    ((4, 20), "taurus"),
    ((5, 21), "gemini"),
    ((6, 22), "cancer"),
    ((7, 23), "leo"),
    ((8, 23), "virgo"),
    ((9, 23), "libra"),
    ((10, 24), "scorpio"),
    ((11, 23), "sagittarius"),
    ((12, 22), "capricorn"),
)
_POSITIVE_SIGNS = {"aries", "gemini", "leo", "libra", "sagittarius", "aquarius"}

def zodiac_polarity_signal(*, at: datetime) -> StrategyDecision:
    """Calendar sun-sign polarity baseline for reproducible astrology experiments."""
    month, day = at.month, at.day
    sign = "capricorn"
    for (start_month, start_day), candidate in _ZODIAC_STARTS:
        if (month, day) >= (start_month, start_day):
            sign = candidate
        else:
            break
    signal: Signal = "LONG" if sign in _POSITIVE_SIGNS else "SHORT"
    return StrategyDecision(
        signal,
        "zodiac_polarity",
        {
            "sun_sign": sign,
            "polarity": "positive" if signal == "LONG" else "negative",
            "semantics": "experimental_spiritual_baseline",
        },
    )
