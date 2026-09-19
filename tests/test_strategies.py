from datetime import datetime, timedelta, timezone
from decimal import Decimal

from jevpip.broker.strategies import (
    ma_trend_signal,
    momentum_signal,
    rsi_mean_reversion_signal,
)
from jevpip.broker.supervisor import (
    SupervisorDecision,
    combine_supervisors,
    deterministic_supervisor,
    validate_jev_supervisor_payload,
)


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


def test_supervisor_pauses_stale_data():
    decision = deterministic_supervisor(
        market_status="OPEN",
        spread_units=0.2,
        max_spread_units=2,
        market_age_seconds=8,
        max_market_age_seconds=5,
    )
    assert decision.state == "PAUSE_ALL"
    assert decision.reason == "stale_market_data"
    assert decision.allow_entry is False


def test_jev_supervisor_payload_rejects_unknown_strategy():
    import pytest

    with pytest.raises(ValueError, match="allowlisted"):
        validate_jev_supervisor_payload(
            {
                "state": "CAUTION",
                "strategy": "invented_magic",
                "confidence": 0.8,
                "ttl_seconds": 30,
                "reason": "test",
            },
            allowed_strategies={"momentum", "ma_trend"},
        )


def test_jev_supervisor_payload_accepts_bounded_advice():
    advice = validate_jev_supervisor_payload(
        {
            "state": "PAUSE_ENTRY",
            "strategy": "ma_trend",
            "confidence": 0.72,
            "ttl_seconds": 45,
            "reason": "event risk",
        },
        allowed_strategies={"momentum", "ma_trend"},
    )
    assert advice.state == "PAUSE_ENTRY"
    assert advice.strategy == "ma_trend"
    assert advice.confidence == 0.72
    assert advice.ttl_seconds == 45


def test_code_supervisor_cannot_be_relaxed_by_jev():
    advice = validate_jev_supervisor_payload(
        {
            "state": "NORMAL",
            "strategy": "momentum",
            "confidence": 0.9,
            "ttl_seconds": 30,
            "reason": "looks calm",
        },
        allowed_strategies={"momentum"},
    )
    plan = combine_supervisors(
        SupervisorDecision("PAUSE_ALL", "stale_market_data", False),
        advice,
    )
    assert plan.state == "PAUSE_ALL"
    assert plan.allow_entry is False
    assert plan.strategy is None


def test_jev_can_tighten_and_select_allowlisted_strategy():
    advice = validate_jev_supervisor_payload(
        {
            "state": "CAUTION",
            "strategy": "ma_trend",
            "confidence": 0.8,
            "ttl_seconds": 60,
            "reason": "trend regime",
        },
        allowed_strategies={"momentum", "ma_trend"},
    )
    plan = combine_supervisors(
        SupervisorDecision("NORMAL", "ok", True),
        advice,
    )
    assert plan.state == "CAUTION"
    assert plan.allow_entry is True
    assert plan.strategy == "ma_trend"
