from datetime import datetime, timedelta, timezone
from decimal import Decimal

from jevpip.broker.strategies import (
    ma_trend_signal,
    momentum_signal,
    rsi_mean_reversion_signal,
)
from jevpip.broker.supervisor import deterministic_supervisor


def prices(values):
    start = datetime(2026, 9, 19, tzinfo=timezone.utc)
    return [(start + timedelta(seconds=i), Decimal(str(v))) for i, v in enumerate(values)]


def test_momentum_strategy():
    series = prices([100, 100.01, 100.03])
    decision = momentum_signal(
        series,
        at=series[-1][0],
        mid=series[-1][1],
        price_unit=Decimal("0.01"),
        window_seconds=2,
        trigger_units=2,
    )
    assert decision.signal == "LONG"
    assert decision.reason == "momentum"


def test_rsi_mean_reversion_strategy():
    falling = prices([100, 99, 98, 97, 96, 95])
    decision = rsi_mean_reversion_signal(
        falling,
        period=5,
        oversold=30,
        overbought=70,
    )
    assert decision.signal == "LONG"
    assert decision.metrics["rsi"] == 0.0
    assert decision.metrics["semantics"] == "tick_count"


def test_ma_trend_strategy():
    rising = prices(range(1, 25))
    decision = ma_trend_signal(
        rising,
        price_unit=Decimal("0.01"),
        fast_period=5,
        slow_period=20,
        min_gap_units=1,
    )
    assert decision.signal == "LONG"
    assert decision.metrics["semantics"] == "tick_count"


def test_supervisor_pauses_closed_market():
    decision = deterministic_supervisor(
        market_status="CLOSED",
        spread_units=0.2,
        max_spread_units=2,
    )
    assert decision.state == "PAUSE_ALL"
    assert decision.allow_entry is False


def test_supervisor_pauses_over_spread_and_warns_near_limit():
    paused = deterministic_supervisor(
        market_status="OPEN",
        spread_units=2.1,
        max_spread_units=2,
    )
    caution = deterministic_supervisor(
        market_status="OPEN",
        spread_units=1.7,
        max_spread_units=2,
    )
    assert paused.state == "PAUSE_ENTRY"
    assert paused.allow_entry is False
    assert caution.state == "CAUTION"
    assert caution.allow_entry is True
