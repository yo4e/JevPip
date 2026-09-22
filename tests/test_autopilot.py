from __future__ import annotations

import json
import random
import asyncio
import threading
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

import jevpip.jev_replay as replay

from jevpip.broker.autopilot import AutopilotBroker, make_paper_broker
from jevpip.broker.paper import PaperBroker, PaperConfig
from jevpip.broker.strategies import coin_flip_signal, moon_phase_signal, tarot_signal, zodiac_polarity_signal
from jevpip.jev.autopilot import REASONS, attach_target, question_specs
from jevpip.jev_replay import run_jev_historical_replay
from jevpip.signals import SignalPolicy
from jevpip.trader_context import TIMEFRAME_SPECS
from jevpip.web.app import PaperDemoInput
from jevpip.web.schemas import ObserverStartRequest
from jevpip.async_work import joined_thread
from jevpip.observer import _should_request_jev

START = datetime(2026, 9, 20, tzinfo=timezone.utc)


def tick(second, bid=99, ask=101, **extra):
    at = (START + timedelta(seconds=second)).isoformat()
    return {"instrument_id": "USD_JPY", "market_timestamp": at, "received_at": at,
            "bid": str(bid), "ask": str(ask), "status": "OPEN", **extra}


def broker(**extra):
    cfg = PaperConfig(autopilot_enabled=True, size=10, price_unit=1,
                      paper_leverage=1, fee_rate=0.001, slippage_units=0.5,
                      autopilot_confirmations=1)
    return AutopilotBroker(replace(cfg, **extra))


def answer(state, choice="LONG_BASE"):
    def select(key, choices):
        return {"type": "choice", "choice": key, "confidence": 0.8,
                "probabilities": {k: 1.0 if k == key else 0.0 for k in choices}}
    return {"model": "test-only", "usage": {"input_tokens": 100, "output_tokens": 10},
            "answers": {"target_position": select(choice, state["autopilot"]["targets"]),
                        "decision_factor": select("TREND", REASONS)}}


def event_for(b, second, choice="LONG_BASE", **updates):
    requested = START + timedelta(seconds=second)
    state = b.decision_state(requested)
    event = {"jev": answer(state, choice), "state": state,
             "requested_at": requested.isoformat(),
             "available_at": (requested+timedelta(seconds=0.1)).isoformat()}
    attach_target(event, state)
    event["target_decision"].update(updates)
    return event


def act(b, second, choice, bid=99, ask=101):
    b.on_tick(tick(second, bid, ask))
    b.on_decision(event_for(b, second, choice))
    return b.on_tick(tick(second+0.2, bid, ask))


def test_factory_preserves_legacy():
    assert type(make_paper_broker(PaperConfig())) is PaperBroker
    assert isinstance(make_paper_broker(PaperConfig(autopilot_enabled=True)), AutopilotBroker)


def test_daytrade_and_scalp_share_full_trader_context():
    scalp = broker(autopilot_style="scalp", autopilot_horizon_seconds=30)
    daytrade = broker(autopilot_style="daytrade", autopilot_horizon_seconds=600)
    for second in range(45):
        row = tick(second, 100 + second / 100, 102 + second / 100)
        scalp.on_tick(row)
        daytrade.on_tick(row)

    scalp_state = scalp.decision_state(START + timedelta(seconds=44))["autopilot"]
    daytrade_state = daytrade.decision_state(START + timedelta(seconds=44))["autopilot"]
    for state, style in ((scalp_state, "scalp"), (daytrade_state, "daytrade")):
        assert state["style"] == style
        assert state["context_version"] == "trader_context_v1"
        assert len(state["recent_ticks"]) == 40
        assert state["recent_ticks"][-1]["delta_units"] == pytest.approx(0.01)
        assert set(state["timeframes"]) == {"1min", "5min", "15min", "1hour"}
        assert "clock" in state
        assert "account" in state
        assert "performance" in state
        assert "costs" in state
    assert len(scalp_state["closed_1m_bars"]) <= 5
    assert len(daytrade_state["closed_1m_bars"]) <= 30


@pytest.mark.parametrize("style,horizon", [("scalp", 30), ("daytrade", 600)])
def test_regular_jev_questions_tell_model_to_weigh_full_context(style, horizon):
    b = broker(autopilot_style=style, autopilot_horizon_seconds=horizon)
    b.on_tick(tick(0))
    instructions = question_specs(b.decision_state(START))["target_position"]["instructions"]
    assert "1m/5m/15m/1h" in instructions
    assert "account/PnL" in instructions
    assert "Decide for yourself" in instructions


def test_live_cadence_schema_defaults_to_fifteen_minutes_and_accepts_it():
    request = ObserverStartRequest(profile={}, signal_policy={})
    assert request.jev_every_seconds == pytest.approx(900)
    assert ObserverStartRequest(
        profile={},
        signal_policy={},
        jev_every_seconds=900,
    ).jev_every_seconds == pytest.approx(900)
    with pytest.raises(ValueError):
        ObserverStartRequest(
            profile={},
            signal_policy={},
            jev_every_seconds=3600.1,
        )


def test_paper_demo_accepts_styles_and_current_defaults():
    defaults = PaperDemoInput()
    assert defaults.paper_leverage == 25
    assert defaults.autopilot_max_drawdown_pct == pytest.approx(0.20)
    assert defaults.autopilot_fifty_reentry_seconds == pytest.approx(60)
    assert defaults.autopilot_fifty_oracle == "jev"
    assert PaperDemoInput(autopilot_style="daytrade").autopilot_style == "daytrade"
    assert PaperDemoInput(autopilot_style="scalp", autopilot_horizon_seconds=30).autopilot_style == "scalp"
    assert PaperDemoInput(autopilot_style="fifty", autopilot_fifty_oracle="tarot").autopilot_fifty_oracle == "tarot"
    assert PaperDemoInput(autopilot_style="fifty", autopilot_fifty_oracle="coin_flip").autopilot_fifty_oracle == "coin_flip"
    with pytest.raises(ValueError):
        PaperDemoInput(autopilot_style="swing")
    with pytest.raises(ValueError):
        PaperDemoInput(paper_leverage=25.1)
    with pytest.raises(ValueError):
        PaperDemoInput(autopilot_fifty_reentry_seconds=3600.1)
    with pytest.raises(ValueError):
        PaperDemoInput(autopilot_fifty_oracle="crystal_ball")


def test_fx_fifty_plus_uses_margin_capacity_and_crypto_stays_one_x():
    leveraged = broker(
        initial_balance=100000,
        size=1000,
        paper_leverage=25,
        autopilot_style="fifty",
        autopilot_horizon_seconds=30,
        fee_rate=0,
        slippage_units=0,
    )
    leveraged.on_tick(tick(0, bid=157, ask=159))
    policy = leveraged.decision_state(START)["autopilot"]
    assert set(policy["targets"]) == {"UP", "DOWN"}
    assert policy["paper_leverage"] == 25

    unleveraged = broker(
        initial_balance=100000,
        size=1000,
        paper_leverage=1,
        autopilot_style="fifty",
        autopilot_horizon_seconds=30,
        fee_rate=0,
        slippage_units=0,
    )
    unleveraged.on_tick(tick(0, bid=157, ask=159))
    assert unleveraged.decision_state(START)["autopilot"]["targets"] == {}

    crypto = AutopilotBroker(PaperConfig(
        autopilot_enabled=True,
        instrument_id="BTC",
        size=0.001,
        paper_leverage=25,
    ))
    assert crypto.config.paper_leverage == 1
    assert crypto.paper_leverage == Decimal("1.0")


def test_fifty_plus_is_mandatory_up_down_and_event_driven():
    b = broker(
        autopilot_style="fifty",
        autopilot_horizon_seconds=30,
        autopilot_fifty_target_units=5,
        fee_rate=0,
        slippage_units=0,
    )
    b.on_tick(tick(0))
    state = b.decision_state(START)
    policy = state["autopilot"]
    assert set(policy["targets"]) == {"UP", "DOWN"}
    assert set(question_specs(state)) == {"target_position"}
    assert _should_request_jev(state) is True
    assert policy["context_version"] == "trader_context_v1"
    assert "costs" in policy
    assert "account" in policy
    assert "performance" in policy
    assert set(policy["timeframes"]) == {"1min", "5min", "15min", "1hour"}
    assert {"bid", "ask", "mid", "spread", "spread_units"} <= set(policy["quote"])
    assert "spread_units" in policy["recent_ticks"][-1]
    assert set(policy["clock"]) == {"utc", "tokyo", "london", "new_york"}

    event = event_for(b, 0, "UP")
    assert event["target_decision"]["target_side"] == "LONG"
    assert event["target_decision"]["reason"] == "FIFTY_PLUS"
    b.on_decision(event)
    opened = b.on_tick(tick(0.2))
    assert opened and opened[0]["action"] == "OPEN"
    assert b.position is not None
    assert _should_request_jev(b.decision_state(START + timedelta(seconds=1))) is False

    closed = b.on_tick(tick(2, bid=106, ask=108))
    assert closed and closed[0]["action"] == "CLOSE"
    assert closed[0]["reason"] == "fifty_take_profit"
    assert closed[0]["pnl"] == pytest.approx(50)
    assert b.position is None
    waiting = b.decision_state(START + timedelta(seconds=2))
    gate = waiting["autopilot"]["fifty_plus"]["entry_gate"]
    assert gate["ready"] is False
    assert gate["reason"] == "post_close_wait"
    assert gate["reentry_remaining_seconds"] == pytest.approx(60)
    assert _should_request_jev(waiting) is False

    almost = b.decision_state(START + timedelta(seconds=61))
    assert almost["autopilot"]["fifty_plus"]["entry_gate"]["reentry_remaining_seconds"] == pytest.approx(1)
    assert _should_request_jev(almost) is False

    ready = b.decision_state(START + timedelta(seconds=62))
    assert ready["autopilot"]["fifty_plus"]["entry_gate"]["ready"] is True
    assert set(ready["autopilot"]["targets"]) == {"UP", "DOWN"}
    assert _should_request_jev(ready) is True


def test_fifty_trader_context_keeps_past_performance_and_filters_future_bars():
    b = broker(
        autopilot_style="fifty",
        autopilot_horizon_seconds=30,
        autopilot_fifty_target_units=5,
        fee_rate=0,
        slippage_units=0,
    )
    as_of = START + timedelta(hours=4)
    histories = {}
    for interval, seconds in (
        ("1min", 60),
        ("5min", 300),
        ("15min", 900),
        ("1hour", 3600),
    ):
        rows = []
        for index in range(205):
            opened = as_of - timedelta(seconds=seconds * (206 - index))
            value = 100 + index / 10
            rows.append({
                "open_time": opened.isoformat(),
                "end_time": (opened + timedelta(seconds=seconds)).isoformat(),
                "open": value,
                "high": value + 1,
                "low": value - 1,
                "close": value + 0.25,
            })
        rows.append({
            "open_time": as_of.isoformat(),
            "end_time": (as_of + timedelta(seconds=seconds)).isoformat(),
            "open": 999,
            "high": 1000,
            "low": 998,
            "close": 999,
        })
        histories[interval] = rows

    b.seed_trader_history(
        {
            "source": "test_history",
            "as_of": as_of.isoformat(),
            "timeframes": histories,
            "used_dates": {},
            "errors": {},
        },
        as_of=as_of,
    )
    b.on_tick({
        **tick(4 * 3600, bid=120, ask=121),
        "market_timestamp": as_of.isoformat(),
        "received_at": as_of.isoformat(),
    })
    state = b.decision_state(as_of)["autopilot"]

    assert state["trader_history"]["source"] == "test_history"
    one_min = state["timeframes"]["1min"]
    assert one_min["closed_bars_available"] == 205
    assert one_min["indicators"]["sma200"] is not None
    assert one_min["indicators"]["rsi14"] is not None
    assert one_min["indicators"]["atr14"] is not None
    assert len(one_min["closed_bars"]) == 60
    assert all(
        datetime.fromisoformat(row["end_time"]) <= as_of
        for row in one_min["closed_bars"]
    )
    assert all(row["close"] != 999 for row in one_min["closed_bars"])
    assert state["account"]["closed_trades"] == 0
    assert "exit_reasons" in state["performance"]


def test_fifty_question_compares_independent_long_and_short_net_races():
    b = broker(
        autopilot_style="fifty",
        autopilot_horizon_seconds=30,
        autopilot_fifty_target_units=5,
        fee_rate=0,
        slippage_units=0,
    )
    b.on_tick(tick(0))
    state = b.decision_state(START)
    fifty = state["autopilot"]["fifty_plus"]
    instructions = question_specs(state)["target_position"]["instructions"]

    assert fifty["target_value"] == 5
    assert fifty["directional_win_probabilities_are_not_complements"] is True
    assert set(fifty["directional_races"]) == {"UP", "DOWN"}
    up = state["autopilot"]["targets"]["UP"]["directional_race"]
    down = state["autopilot"]["targets"]["DOWN"]["directional_race"]
    assert up["side"] == "LONG"
    assert down["side"] == "SHORT"
    assert up["target"]["net_take_profit_jpy"] == pytest.approx(50)
    assert up["target"]["net_stop_loss_jpy"] == pytest.approx(-50)
    assert down["target"]["net_take_profit_jpy"] == pytest.approx(50)
    assert down["target"]["net_stop_loss_jpy"] == pytest.approx(-50)
    assert up["reference_exit_conditions"]["quote_side"] == "bid"
    assert down["reference_exit_conditions"]["quote_side"] == "ask"
    assert "TWO INDEPENDENT" in instructions
    assert "LONG losing does NOT imply SHORT would have won" in instructions
    assert "not complements" in instructions
    assert "Choice probabilities are relative choice preferences" in instructions
    assert "1m/5m/15m/1h" in instructions
    assert "account/PnL" in instructions
    assert "Decide for yourself" in instructions



def test_spiritual_oracles_are_binary_and_do_not_request_jev():
    moon = moon_phase_signal(at=START)
    zodiac = zodiac_polarity_signal(at=START)
    tarot = tarot_signal()
    coin = coin_flip_signal()
    assert moon.signal in {"LONG", "SHORT"}
    assert zodiac.signal == "SHORT"  # 2026-09-20 is Virgo in this deterministic calendar rule
    assert tarot.signal in {"LONG", "SHORT"}
    assert tarot.metrics["orientation"] in {"upright", "reversed"}
    assert isinstance(tarot.metrics["card"], str)
    assert coin.signal in {"LONG", "SHORT"}
    assert coin.metrics["side"] in {"heads", "tails"}

    b = broker(
        autopilot_style="fifty",
        autopilot_fifty_oracle="moon_phase",
        autopilot_horizon_seconds=30,
        autopilot_fifty_target_units=5,
        fee_rate=0,
        slippage_units=0,
    )
    opened = b.on_tick(tick(0))
    assert opened and opened[0]["action"] == "OPEN"
    assert b.position is not None
    snapshot = b.snapshot()
    assert snapshot["strategy"] == "spiritual_fifty"
    assert snapshot["fifty_oracle"] == "moon_phase"
    assert snapshot["spiritual_decision"]["signal"] == b.position.side
    assert _should_request_jev(b.decision_state(START)) is False


def test_tarot_fifty_opens_without_calling_jev():
    b = broker(
        autopilot_style="fifty",
        autopilot_fifty_oracle="tarot",
        autopilot_horizon_seconds=30,
        autopilot_fifty_target_units=5,
        fee_rate=0,
        slippage_units=0,
    )
    opened = b.on_tick(tick(0))
    assert opened and opened[0]["action"] == "OPEN"
    snapshot = b.snapshot()
    assert snapshot["fifty_oracle"] == "tarot"
    assert snapshot["spiritual_decision"]["metrics"]["card"]
    assert snapshot["spiritual_decision"]["metrics"]["orientation"] in {"upright", "reversed"}
    assert _should_request_jev(b.decision_state(START)) is False



def test_coin_flip_fifty_opens_without_calling_jev():
    b = broker(
        autopilot_style="fifty",
        autopilot_fifty_oracle="coin_flip",
        autopilot_horizon_seconds=30,
        autopilot_fifty_target_units=5,
        fee_rate=0,
        slippage_units=0,
    )
    opened = b.on_tick(tick(0))
    assert opened and opened[0]["action"] == "OPEN"
    snapshot = b.snapshot()
    assert snapshot["fifty_oracle"] == "coin_flip"
    assert snapshot["spiritual_decision"]["metrics"]["side"] in {"heads", "tails"}
    assert _should_request_jev(b.decision_state(START)) is False

def test_spiritual_fifty_reuses_close_wait_and_reenters_without_jev():
    b = broker(
        autopilot_style="fifty",
        autopilot_fifty_oracle="zodiac_polarity",
        autopilot_horizon_seconds=30,
        autopilot_fifty_target_units=5,
        autopilot_fifty_reentry_seconds=60,
        fee_rate=0,
        slippage_units=0,
    )
    opened = b.on_tick(tick(0))
    assert opened and b.position is not None
    assert b.position.side == "SHORT"

    closed = b.on_tick(tick(2, bid=92, ask=94))
    assert closed and closed[0]["action"] == "CLOSE"
    assert closed[0]["reason"] == "fifty_take_profit"
    assert b.position is None

    assert b.on_tick(tick(30, bid=92, ask=94)) == []
    waiting = b.snapshot()["fifty_entry_gate"]
    assert waiting["reason"] == "post_close_wait"

    reopened = b.on_tick(tick(62, bid=92, ask=94))
    assert reopened and reopened[0]["action"] == "OPEN"
    assert b.position is not None
    assert b.position.side == "SHORT"


def test_spiritual_fifty_respects_spread_gate_before_opening():
    b = broker(
        initial_balance=100000,
        size=1000,
        price_unit=0.01,
        paper_leverage=25,
        autopilot_style="fifty",
        autopilot_fifty_oracle="moon_phase",
        autopilot_fifty_target_units=20,
        autopilot_max_spread=1.5,
        fee_rate=0,
        slippage_units=0,
    )
    assert b.on_tick(tick(0, bid=157.000, ask=157.020)) == []
    assert b.position is None
    assert b.snapshot()["fifty_entry_gate"]["reason"] == "spread_above_limit"

    opened = b.on_tick(tick(1, bid=157.000, ask=157.010))
    assert opened and opened[0]["action"] == "OPEN"


def test_fifty_plus_waits_when_round_trip_cost_already_exceeds_target():
    b = broker(
        initial_balance=100000,
        size=1000,
        price_unit=0.01,
        paper_leverage=25,
        autopilot_style="fifty",
        autopilot_horizon_seconds=30,
        autopilot_fifty_target_units=10,
        fee_rate=0.00002,
        slippage_units=0,
    )
    b.on_tick(tick(0, bid=157.000, ask=157.099))
    state = b.decision_state(START)
    gate = state["autopilot"]["fifty_plus"]["entry_gate"]
    assert gate["ready"] is False
    assert gate["reason"] == "round_trip_cost_at_or_above_target"
    assert gate["estimated_round_trip_cost_units"] == pytest.approx(10.528198)
    assert gate["estimated_round_trip_cost_jpy"] == pytest.approx(105.28198)
    assert state["autopilot"]["targets"] == {}
    assert _should_request_jev(state) is False
    snapshot = b.snapshot()
    assert snapshot["fifty_entry_gate"]["ready"] is False

    b.on_tick(tick(1, bid=157.000, ask=157.002))
    ready_state = b.decision_state(START + timedelta(seconds=1))
    assert ready_state["autopilot"]["fifty_plus"]["entry_gate"]["ready"] is True
    assert set(ready_state["autopilot"]["targets"]) == {"UP", "DOWN"}
    assert _should_request_jev(ready_state) is True


def test_fifty_plus_waits_when_spread_exceeds_configured_limit():
    b = broker(
        initial_balance=100000,
        size=1000,
        price_unit=0.01,
        paper_leverage=25,
        autopilot_style="fifty",
        autopilot_horizon_seconds=30,
        autopilot_fifty_target_units=20,
        autopilot_max_spread=1.5,
        fee_rate=0,
        slippage_units=0,
    )
    b.on_tick(tick(0, bid=157.000, ask=157.020))
    state = b.decision_state(START)
    gate = state["autopilot"]["fifty_plus"]["entry_gate"]
    assert gate["ready"] is False
    assert gate["reason"] == "spread_above_limit"
    assert gate["spread_units"] == pytest.approx(2.0)
    assert gate["max_spread_units"] == pytest.approx(1.5)
    assert state["autopilot"]["targets"] == {}
    assert _should_request_jev(state) is False

    b.on_tick(tick(1, bid=157.000, ask=157.010))
    ready = b.decision_state(START + timedelta(seconds=1))
    assert ready["autopilot"]["fifty_plus"]["entry_gate"]["ready"] is True
    assert set(ready["autopilot"]["targets"]) == {"UP", "DOWN"}


def test_fifty_plus_rechecks_spread_before_execution():
    b = broker(
        size=10,
        price_unit=1,
        autopilot_style="fifty",
        autopilot_horizon_seconds=30,
        autopilot_fifty_target_units=10,
        autopilot_max_spread=1,
        fee_rate=0,
        slippage_units=0,
    )
    b.on_tick(tick(0, bid=100, ask=101))
    event = event_for(b, 0, "UP")
    b.on_decision(event)
    rows = b.on_tick(tick(0.2, bid=100, ask=102))
    assert rows == []
    assert b.position is None
    assert b.snapshot()["target_status"] == "max_spread"

def test_fifty_plus_can_open_on_latest_fresh_quote_without_waiting_for_next_tick():
    b = broker(
        autopilot_style="fifty",
        autopilot_horizon_seconds=30,
        autopilot_fifty_target_units=5,
        fee_rate=0,
        slippage_units=0,
        max_market_age_seconds=5,
    )
    b.on_tick(tick(0))
    event = event_for(b, 0, "UP")
    b.on_decision(event)

    opened = b.execute_fifty_pending(START + timedelta(seconds=0.1))
    assert opened and opened[0]["action"] == "OPEN"
    assert b.position is not None
    assert b.position.side == "LONG"
    assert b.snapshot()["target_status"] == "executed"


def test_fifty_plus_rejects_stale_quote_and_reasks_on_next_fresh_tick():
    b = broker(
        autopilot_style="fifty",
        autopilot_horizon_seconds=30,
        fee_rate=0,
        slippage_units=0,
        max_market_age_seconds=5,
    )
    b.on_tick(tick(0))
    b.on_decision(event_for(b, 0, "DOWN"))
    assert b.execute_fifty_pending(START + timedelta(seconds=6)) == []
    assert b.position is None
    assert b.snapshot()["target_status"] == "rejected:stale_quote"

    b.on_tick(tick(7))
    assert _should_request_jev(b.decision_state(START + timedelta(seconds=7))) is True


def test_fifty_plus_fx_stop_is_symmetric_net_units():
    b = broker(
        autopilot_style="fifty",
        autopilot_horizon_seconds=30,
        autopilot_fifty_target_units=5,
        fee_rate=0,
        slippage_units=0,
    )
    act(b, 0, "UP")
    closed = b.on_tick(tick(2, bid=96, ask=98))
    assert closed and closed[0]["reason"] == "fifty_stop_loss"
    assert closed[0]["pnl"] == pytest.approx(-50)


def test_fifty_plus_btc_uses_symmetric_net_yen_target():
    cfg = PaperConfig(
        autopilot_enabled=True,
        autopilot_style="fifty",
        autopilot_horizon_seconds=30,
        autopilot_fifty_target_jpy=500,
        autopilot_confirmations=1,
        instrument_id="BTC",
        size=0.001,
        price_unit=1,
        fee_rate=0,
        slippage_units=0,
    )
    b = AutopilotBroker(cfg)
    def btc_tick(second, bid, ask):
        at = (START + timedelta(seconds=second)).isoformat()
        return {"instrument_id": "BTC", "market_timestamp": at, "received_at": at,
                "bid": str(bid), "ask": str(ask), "status": "OPEN"}
    b.on_tick(btc_tick(0, 10_000_000, 10_001_000))
    state = b.decision_state(START)
    event = {"jev": answer(state, "UP"), "state": state, "requested_at": START.isoformat(),
             "available_at": (START + timedelta(seconds=.1)).isoformat()}
    attach_target(event, state)
    b.on_decision(event)
    assert b.on_tick(btc_tick(.2, 10_000_000, 10_001_000))[0]["action"] == "OPEN"
    closed = b.on_tick(btc_tick(2, 10_501_000, 10_502_000))
    assert closed and closed[0]["reason"] == "fifty_take_profit"
    assert closed[0]["pnl"] == pytest.approx(500)


def test_scale_reduce_reverse_conserve_cash_and_allocate_all_costs():
    b = broker()
    cash = Decimal("100000")
    fees = Decimal(0)
    actions = []
    for second, choice, bid, ask in [
        (0, "LONG_BASE", 99, 101), (2, "LONG_LARGE", 109, 111),
        (4, "LONG_SMALL", 119, 121), (6, "SHORT_BASE", 114, 116),
        (8, "SHORT_SMALL", 104, 106), (10, "FLAT", 94, 96),
    ]:
        rows = act(b, second, choice, bid, ask)
        for row in rows:
            actions.append(row["action"])
            buy = (row["side"] == "LONG") == (row["action"] in {"OPEN", "INCREASE"})
            cash += Decimal(row["price"])*Decimal(str(row["size"]))*(-1 if buy else 1)
            fees += Decimal(str(row["execution_fee"]))
        remaining = b.position
        liquidation = Decimal(0)
        if remaining:
            px = Decimal(str(bid-0.5 if remaining.side == "LONG" else ask+0.5))
            liquidation = px*remaining.size*(1 if remaining.side == "LONG" else -1)-px*remaining.size*Decimal("0.001")
        assert b.snapshot()["equity"] == pytest.approx(float(cash-fees+liquidation), abs=0.001)
    assert actions == ["OPEN", "INCREASE", "REDUCE", "CLOSE", "OPEN", "REDUCE", "CLOSE"]
    s = b.snapshot()
    assert s["equity"] == pytest.approx(float(cash-fees), abs=0.001)
    assert s["fees_paid"] == pytest.approx(float(fees), abs=0.001)
    p = s["pnl_breakdown"]
    assert p["market_pnl"]-p["spread_cost"]-p["slippage_cost"]-p["fees"] == pytest.approx(s["realized_pnl"], abs=0.001)
    assert p["fees"] == pytest.approx(s["fees_paid"], abs=0.001)
    assert b.position is None


def test_random_target_paths_match_independent_cash_ledger():
    b = broker()
    rng = random.Random(17)
    cash, fees = Decimal("100000"), Decimal(0)
    for i in range(120):
        mid = rng.randint(80, 150)
        choice = rng.choice(["KEEP", "FLAT", "LONG_SMALL", "LONG_BASE", "LONG_LARGE", "SHORT_SMALL", "SHORT_BASE"])
        for row in act(b, i*2, choice, mid-1, mid+1):
            sign = -1 if (row["side"] == "LONG") == (row["action"] in {"OPEN", "INCREASE"}) else 1
            cash += sign*Decimal(row["price"])*Decimal(str(row["size"]))
            fees += Decimal(str(row["execution_fee"]))
        liquidation = Decimal(0)
        if b.position:
            sign = 1 if b.position.side == "LONG" else -1
            price = Decimal(str(mid-1.5 if sign == 1 else mid+1.5))
            liquidation = b.position.size*price*(sign-Decimal("0.001"))
        assert b.snapshot()["equity"] == pytest.approx(float(cash-fees+liquidation), abs=0.001)


def test_same_target_is_hold_and_duplicate_is_never_reapplied():
    b = broker()
    act(b, 0, "LONG_BASE")
    before = b.snapshot()["fees_paid"]
    assert act(b, 2, "LONG_BASE") == []
    assert b.snapshot()["target_status"] == "hold"
    event = event_for(b, 3, "LONG_LARGE")
    b.on_decision(event)
    assert b.on_tick(tick(3.2))
    version = b.account_version
    b.on_decision(event)
    assert b.on_tick(tick(3.3)) == []
    assert b.account_version == version
    assert before < b.snapshot()["fees_paid"]


@pytest.mark.parametrize("updates", [
    {"target_quantity": -1}, {"target_quantity": "NaN"}, {"target_quantity": "Infinity"},
    {"target_quantity": True}, {"target_quantity": 0.5}, {"target_quantity": 0},
    {"target_quantity": "1e999999"},
    {"target_side": "BUY"}, {"target_side": "FLAT", "target_quantity": 10},
    {"confidence": 1.1}, {"confidence": float("nan")}, {"account_version": True},
    {"account_version": 9}, {"session_id": "old"}, {"instrument_id": "BTC"},
    {"reason": "run shell command"}, {"schema_version": 2}, {"schema_version": True},
])
def test_invalid_target_cannot_trade(updates):
    b = broker()
    b.on_tick(tick(0))
    b.on_decision(event_for(b, 0, **updates))
    assert b.on_tick(tick(0.2)) == []
    assert b.position is None
    assert b.snapshot()["target_status"].startswith("rejected:")


def test_late_response_stale_market_and_account_changes():
    b = broker()
    b.on_tick(tick(0))
    pending = event_for(b, 0)
    b.on_decision(pending)
    assert b.on_tick(tick(0.05)) == []
    assert b.on_tick(tick(6)) == []  # expired before an executable quote
    assert b.snapshot()["target_status"] == "rejected:expired"
    b.on_decision(event_for(b, 6))
    assert b.on_tick(tick(6.2, status="CLOSE")) == []
    assert b.on_tick(tick(6.3, received_at=tick(20)["received_at"])) == []
    assert b.position is None
    b.on_decision(event_for(b, 21))
    b.account_version += 1  # e.g. a risk exit while the request is in flight
    assert b.on_tick(tick(21.2)) == []
    assert b.snapshot()["target_status"] == "rejected:account_changed"


def test_reset_does_not_accept_an_inflight_old_session():
    b = broker()
    b.on_tick(tick(0))
    event = event_for(b, 0)
    reset = broker()
    reset.on_decision(event)
    assert reset.on_tick(tick(0.2)) == []


def test_confirm_increases_but_reduce_immediately():
    b = broker(autopilot_confirmations=2)
    assert act(b, 0, "LONG_BASE") == []
    assert act(b, 2, "LONG_BASE")[0]["action"] == "OPEN"
    assert act(b, 4, "LONG_SMALL")[0]["action"] == "REDUCE"
    assert act(b, 6, "FLAT")[0]["action"] == "CLOSE"


@pytest.mark.parametrize("config,status", [
    ({"initial_balance": 900}, "capital_limit"),
    ({"autopilot_max_quantity": 5}, "max_quantity"),
    ({"autopilot_max_notional": 900}, "max_notional"),
    ({"autopilot_max_change": 5}, "max_position_change"),
    ({"autopilot_max_spread": 1}, "max_spread"),
    ({"autopilot_min_confidence": 0.9}, "minimum_confidence"),
])
def test_increase_constraints(config, status):
    b = broker(**config)
    b.on_tick(tick(0))
    b.on_decision(event_for(b, 0, "KEEP", target_side="LONG", target_quantity="10"))
    assert b.on_tick(tick(0.2)) == []
    assert b.snapshot()["target_status"] == status


def test_rejected_reverse_is_atomic():
    b = broker(autopilot_max_quantity=10)
    act(b, 0, "LONG_BASE")
    version = b.account_version
    b.on_tick(tick(2))
    b.on_decision(event_for(b, 2, "KEEP", target_side="SHORT", target_quantity="20"))
    assert b.on_tick(tick(2.2)) == []
    assert b.position.side == "LONG" and b.position.size == 10
    assert b.account_version == version


def test_legacy_tp_and_eight_second_exit_are_not_applied():
    b = broker(take_profit_units=1, max_hold_seconds=8)
    act(b, 0, "LONG_BASE")
    assert b.on_tick(tick(20, 110, 112)) == []
    assert b.position is not None


def test_net_tp_and_dd_exit_are_cost_aware_and_reject_old_target():
    b = broker(autopilot_take_profit_units=1)
    act(b, 0, "LONG_BASE")
    assert b.on_tick(tick(1, 102, 104)) == []  # price gain but not net TP
    rows = b.on_tick(tick(2, 105, 107))
    assert rows[0]["reason"] == "net_take_profit" and rows[0]["pnl"] > 0
    b = broker(autopilot_max_drawdown=50)
    act(b, 0, "LONG_BASE")
    b.on_tick(tick(2))
    b.on_decision(event_for(b, 2, "LONG_LARGE"))
    rows = b.on_tick(tick(2.2, 90, 92))
    assert rows[0]["reason"] == "drawdown_or_equity_stop"
    assert b.snapshot()["risk_halted"]
    halted_state = b.decision_state(START + timedelta(seconds=3))
    assert halted_state["autopilot"]["risk_halted"] is True
    assert _should_request_jev(halted_state) is False
    assert act(b, 4, "LONG_BASE") == []


def test_state_costs_history_and_typed_questions():
    b = broker()
    b.warm_history(tick(0, 99, 101))
    b.warm_history(tick(60, 104, 106))
    b.on_tick(tick(120, 109, 111))
    state = b.decision_state(START+timedelta(seconds=120))
    p = state["autopilot"]
    assert p["costs"]["estimated_round_trip_cost_per_unit"] == "3.220"
    assert all(bar["end_unix"] <= (START+timedelta(seconds=120)).timestamp() for bar in p["closed_1m_bars"])
    assert len(p["closed_1m_bars"]) == 2
    assert set(question_specs(state)) == {"target_position", "decision_factor"}
    assert "secret" not in json.dumps(state).lower()
    event = event_for(b, 120)
    event["jev"]["answers"]["target_position"]["confidence"] = float("nan")
    attach_target(event, state)
    assert "target_error" in event


def test_fifty_replay_falls_back_to_historical_1m(tmp_path, monkeypatch):
    ticks = []
    for minute, (bid, ask) in enumerate(
        [(99, 101), (100, 102), (101, 103), (102, 104)],
        start=1,
    ):
        at = START + timedelta(minutes=minute)
        ticks.append(
            replay._tick_from_row(
                {
                    "instrument_id": "USD_JPY",
                    "symbol": "USD_JPY",
                    "display_symbol": "USD/JPY",
                    "bid": str(bid),
                    "ask": str(ask),
                    "market_timestamp": at.isoformat(),
                    "received_at": at.isoformat(),
                    "price_unit": "1",
                    "move_unit_label": "pips",
                    "status": "HISTORICAL",
                }
            )
        )
    monkeypatch.setattr(
        replay,
        "load_historical_ticks",
        lambda date, *, instrument_id, limit=None: (ticks, "fx_bid_ask_close"),
    )
    times = iter(i / 100 for i in range(100))
    monkeypatch.setattr("jevpip.jev_replay.time.perf_counter", lambda: next(times))

    class Fake:
        calls = 0

        def decide(self, state, horizon, **kwargs):
            assert state["autopilot"]["style"] == "fifty"
            self.calls += 1
            return answer(state, "UP")

    fake = Fake()
    result = run_jev_historical_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-19",
        start_time=None,
        duration_seconds=180,
        cadence_seconds=60,
        profile={"quote": True},
        signal_policy=SignalPolicy(),
        paper_config=broker(
            autopilot_style="fifty",
            autopilot_fifty_oracle="jev",
            autopilot_fifty_target_units=100,
            autopilot_max_spread=10,
            fee_rate=0,
            slippage_units=0,
        ).config,
        jev_client=fake,
        acknowledged_token_use=True,
    )

    assert result["data_source"] == "gmo_historical_1m"
    assert "GMO historical 1分足" in result["data_source_note"]
    assert result["summary"]["calls"] == fake.calls
    assert fake.calls > 0


def test_fifty_replay_executes_at_response_time_before_sparse_next_tick(tmp_path, monkeypatch):
    path = tmp_path/"raw_ticks"/"USD_JPY"/"2026-09-20.jsonl"
    path.parent.mkdir(parents=True)
    rows = [
        tick(0, 99, 101),
        tick(10, 106, 108),
        tick(20, 106, 108),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows)+"\n")
    times = iter([0.0, 0.1])
    monkeypatch.setattr("jevpip.jev_replay.time.perf_counter", lambda: next(times))

    class Fake:
        calls = 0
        def decide(self, state, horizon, **kwargs):
            self.calls += 1
            return answer(state, "UP")

    fake = Fake()
    result = run_jev_historical_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-20",
        start_time="00:00:00",
        duration_seconds=20,
        cadence_seconds=60,
        profile={"quote": True},
        signal_policy=SignalPolicy(),
        paper_config=broker(
            autopilot_style="fifty",
            autopilot_fifty_oracle="jev",
            autopilot_fifty_target_units=5,
            autopilot_max_spread=10,
            autopilot_fifty_reentry_seconds=60,
            fee_rate=0,
            slippage_units=0,
        ).config,
        jev_client=fake,
        acknowledged_token_use=True,
    )

    saved = [json.loads(line) for line in open(result["output"])]
    trades = [row for row in saved if row.get("kind") == "paper_trade"]
    assert fake.calls == 1
    assert [row["action"] for row in trades[:2]] == ["OPEN", "CLOSE"]
    assert trades[0]["timestamp"] == (START + timedelta(seconds=0.1)).isoformat()
    assert trades[1]["reason"] == "fifty_take_profit"
    assert not any("rejected:expired" in json.dumps(row) for row in saved)
    labels = result["summary"]["fifty_directional_outcomes"]
    assert labels["samples"] == 1
    assert labels["chosen_resolved"] == 1
    assert labels["chosen_tp_first_rate"] == pytest.approx(1.0)
    assert labels["directions"]["LONG"]["take_profit_first"] == 1
    assert labels["directions"]["SHORT"]["stop_loss_first"] == 1
    outcome_rows = [row for row in saved if row.get("kind") == "fifty_directional_outcome"]
    assert len(outcome_rows) == 1
    assert outcome_rows[0]["outcomes"]["LONG"]["status"] == "take_profit_first"
    assert outcome_rows[0]["outcomes"]["SHORT"]["status"] == "stop_loss_first"


def test_fifty_replay_uses_live_style_trader_history_seed(tmp_path, monkeypatch):
    path = tmp_path/"raw_ticks"/"USD_JPY"/"2026-09-20.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            json.dumps(tick(i, 99, 101))
            for i in (0, 5, 10, 11)
        )+"\n"
    )
    replay_start = START + timedelta(seconds=10)
    times = iter([0.0, 0.1])
    monkeypatch.setattr("jevpip.jev_replay.time.perf_counter", lambda: next(times))

    timeframes = {}
    for interval, spec in TIMEFRAME_SPECS.items():
        seconds = spec["seconds"]
        bars = []
        for index in range(205):
            end = replay_start - timedelta(seconds=seconds*(204-index))
            opened = end - timedelta(seconds=seconds)
            value = 100 + index
            bars.append({
                "open_time": opened.isoformat(),
                "end_time": end.isoformat(),
                "open": value,
                "high": value + 1,
                "low": value - 1,
                "close": value,
            })
        timeframes[interval] = bars
    seed = {
        "source": "test_history",
        "as_of": replay_start.isoformat(),
        "timeframes": timeframes,
        "used_dates": {},
        "errors": {},
    }

    class Fake:
        calls = 0
        def decide(self, state, horizon, **kwargs):
            self.calls += 1
            context = state["autopilot"]
            assert context["trader_history"]["source"] == "test_history"
            assert context["timeframes"]["1hour"]["closed_bars_available"] == 205
            assert context["timeframes"]["1hour"]["indicators"]["sma_200"] is not None
            assert all(
                datetime.fromisoformat(row["end_time"]) <= replay_start
                for row in context["timeframes"]["1hour"]["closed_bars"]
            )
            # Pre-window raw ticks are not part of a live session's startup
            # context. Only the first in-window tick should be visible here.
            assert len(context["recent_ticks"]) == 1
            assert context["recent_ticks"][0]["at"] == replay_start.isoformat()
            return answer(state, "UP")

    result = run_jev_historical_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-20",
        start_time="00:00:10",
        duration_seconds=1,
        cadence_seconds=60,
        profile={"quote": True},
        signal_policy=SignalPolicy(),
        paper_config=broker(
            autopilot_style="fifty",
            autopilot_fifty_oracle="jev",
            autopilot_fifty_target_units=5,
            autopilot_max_spread=10,
            fee_rate=0,
            slippage_units=0,
        ).config,
        jev_client=Fake(),
        acknowledged_token_use=True,
        trader_history_seed=seed,
    )
    assert result["summary"]["calls"] == 1


def test_replay_uses_same_policy_and_preserves_full_diagnostics(tmp_path, monkeypatch):
    path = tmp_path/"raw_ticks"/"USD_JPY"/"2026-09-20.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(json.dumps(tick(i, 99+i, 101+i)) for i in range(12))+"\n")
    times = iter(i/10 for i in range(100))
    monkeypatch.setattr("jevpip.jev_replay.time.perf_counter", lambda: next(times))
    class Fake:
        calls = 0
        def decide(self, state, horizon, **kwargs):
            assert horizon == "5s"
            assert "horizon_seconds" not in state["autopilot"]
            assert "external_context" not in state
            assert all(x["end_unix"] <= datetime.fromisoformat(state["autopilot"]["as_of"]).timestamp() for x in state["autopilot"]["closed_1m_bars"])
            self.calls += 1
            return answer(state, "LONG_BASE" if self.calls < 5 else "FLAT")
    fake = Fake()
    result = run_jev_historical_replay(tmp_path, instrument_id="USD_JPY", date="2026-09-20",
        start_time=None, duration_seconds=11, cadence_seconds=1, profile={"quote": True},
        signal_policy=SignalPolicy(), paper_config=broker().config, jev_client=fake, acknowledged_token_use=True)
    rows = [json.loads(x) for x in open(result["output"])]
    assert any(x["kind"] == "paper_trade" and x["action"] == "OPEN" for x in rows)
    assert any(x["kind"] == "target_decision_trace" for x in rows)
    assert any(x["kind"] == "jev_replay_config" for x in rows)
    s = result["summary"]
    assert s["calls"] == fake.calls
    assert s["pnl_breakdown"]["net_realized_pnl"] == pytest.approx(s["net_pnl"], abs=0.001)
    assert s["closed_trades"] == 1


def test_historical_fundamentals_rejected_before_paid_call(tmp_path):
    class MustNotCall:
        def decide(self, *args, **kwargs):
            pytest.fail("must not call Jev")
    with pytest.raises(ValueError, match="historical fundamentals unavailable"):
        run_jev_historical_replay(tmp_path, instrument_id="USD_JPY", date="2026-09-20",
            start_time=None, duration_seconds=60, cadence_seconds=1, profile={},
            signal_policy=SignalPolicy(), paper_config=broker(autopilot_fundamentals=True).config,
            jev_client=MustNotCall(), acknowledged_token_use=True)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_api_rejects_nonfinite_constraints(value):
    with pytest.raises(ValueError):
        PaperDemoInput(autopilot_max_notional=value)


def test_cancelled_api_worker_is_drained_before_stop_completes():
    started, release = threading.Event(), threading.Event()
    def call():
        started.set()
        assert release.wait(timeout=3)
        return "late result must be discarded"
    async def run():
        task = asyncio.create_task(joined_thread(call))
        await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())


def test_client_uses_only_target_questions_without_network(monkeypatch):
    from jevpip.jev.client import JevClient
    b = broker()
    b.on_tick(tick(0))
    state = b.decision_state(START)
    captured = {}
    class FakeSDK:
        def __init__(self, **kwargs):
            captured["options"] = kwargs
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def system_one(self, **kwargs):
            captured.update(kwargs)
            class Response:
                def model_dump(self, **kwargs):
                    return answer(state)
            return Response()
    monkeypatch.setattr("typesafe_sdk.TypeSafeClient", FakeSDK)
    result = JevClient("test-key-not-a-credential").decide(state)
    assert set(captured["questions"]) == {"target_position", "decision_factor"}
    assert captured["options"]["timeout"] == 10
    assert captured["options"]["retry"].max_retries == 0
    assert result["model"] == "test-only"


def test_live_provider_shares_replay_state_and_fundamentals_toggle(tmp_path):
    from jevpip.config import Settings
    from jevpip.web.controller import UIController
    b = broker()
    b.on_tick(tick(0))
    ui = UIController(Settings(data_dir=tmp_path))
    ui._paper, ui._paper_config = b, b.config
    ui._jev_context_state = lambda *args: {"external_context": {"source": "observed official calendar"}}
    assert ui._jev_state_context(START, "USD_JPY") == b.decision_state(START)
    b.config = replace(b.config, autopilot_fundamentals=True)
    assert "external_context" in ui._jev_state_context(START, "USD_JPY")


def test_replay_lock_blocks_parallel_runs_without_calling_model(tmp_path):
    from jevpip.config import Settings
    from jevpip.web.controller import UIController
    ui = UIController(Settings(data_dir=tmp_path))
    ui._jev_replay_running = True
    async def run():
        with pytest.raises(RuntimeError):
            await ui.run_jev_replay(instrument_id="USD_JPY", date="2026-09-20", start_time=None,
                duration_seconds=10, cadence_seconds=1, profile={}, signal_policy=SignalPolicy(),
                paper_config={}, acknowledged_token_use=True)
    asyncio.run(run())


def test_candidates_fit_capital_but_keep_and_reductions_remain_available():
    b = broker(initial_balance=900)
    b.on_tick(tick(0))
    targets = b.decision_state(START)["autopilot"]["targets"]
    assert set(targets) == {"KEEP", "FLAT", "LONG_SMALL", "SHORT_SMALL"}
    act(b, 0, "LONG_SMALL")
    b.on_tick(tick(2, 1000, 1002))
    assert "KEEP" in b.decision_state(START+timedelta(seconds=2))["autopilot"]["targets"]


def test_startup_reservation_blocks_another_start_and_replay(tmp_path):
    from jevpip.config import Settings
    from jevpip.web.controller import UIController
    ui = UIController(Settings(data_dir=tmp_path, typesafe_api_key=""))
    async def run():
        refreshing, release = asyncio.Event(), asyncio.Event()
        async def refresh(*args):
            refreshing.set()
            await release.wait()
        ui.refresh_external_context = refresh
        params = dict(instrument_id="USD_JPY", profile_name="minimal", profile={},
            with_jev=True, jev_every_seconds=1, signal_policy_name="test", signal_policy=SignalPolicy())
        startup = asyncio.create_task(ui.start_observer(**params))
        await refreshing.wait()
        with pytest.raises(RuntimeError):
            await ui.start_observer(**params)
        with pytest.raises(RuntimeError):
            await ui.run_jev_replay(instrument_id="USD_JPY", date="2026-09-20", start_time=None,
                duration_seconds=10, cadence_seconds=1, profile={}, signal_policy=SignalPolicy(),
                paper_config={}, acknowledged_token_use=True)
        release.set()
        with pytest.raises(ValueError, match="TYPESAFE_API_KEY"):
            await startup
        assert not ui.running
    asyncio.run(run())


def test_cancelled_replay_stops_after_inflight_call(tmp_path, monkeypatch):
    from jevpip.config import Settings
    from jevpip.web.controller import UIController
    path = tmp_path/"raw_ticks"/"USD_JPY"/"2026-09-20.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(json.dumps(tick(i)) for i in range(20))+"\n")
    started, release = threading.Event(), threading.Event()
    class Fake:
        calls = 0
        def __init__(self, *args):
            pass
        def decide(self, state, *args, **kwargs):
            Fake.calls += 1
            started.set()
            assert release.wait(timeout=3)
            return answer(state, "KEEP")
    monkeypatch.setattr("jevpip.jev.client.JevClient", Fake)
    ui = UIController(Settings(data_dir=tmp_path, typesafe_api_key="test-only"))

    async def fake_trader_history(*, instrument_id, as_of):
        return {
            "source": "test_history",
            "as_of": as_of.isoformat(),
            "timeframes": {interval: [] for interval in TIMEFRAME_SPECS},
            "used_dates": {},
            "errors": {},
        }

    monkeypatch.setattr(ui._read, "fetch_trader_history", fake_trader_history)

    async def run():
        task = asyncio.create_task(ui.run_jev_replay(instrument_id="USD_JPY", date="2026-09-20",
            start_time=None, duration_seconds=19, cadence_seconds=1, profile={}, signal_policy=SignalPolicy(),
            paper_config={"autopilot_enabled": True, "size": 10}, acknowledged_token_use=True))
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert ui._jev_replay_running
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not ui._jev_replay_running
        assert Fake.calls == 1
    asyncio.run(run())
    assert any('jev_replay_cancelled' in p.read_text() for p in (tmp_path/'jev_replays'/'USD_JPY').glob('*.jsonl'))


def test_replay_rejects_noncausal_raw_history_before_call(tmp_path):
    path = tmp_path/"raw_ticks"/"USD_JPY"/"2026-09-20.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(json.dumps(t) for t in [
        tick(0, received_at=tick(2)["received_at"]), tick(1)])+"\n")
    with pytest.raises(ValueError, match="causal arrival order"):
        run_jev_historical_replay(tmp_path, instrument_id="USD_JPY", date="2026-09-20",
            start_time=None, duration_seconds=10, cadence_seconds=1, profile={}, signal_policy=SignalPolicy(),
            paper_config=broker().config, jev_client=None, acknowledged_token_use=True)


def test_replay_allows_small_exchange_clock_lead(tmp_path, monkeypatch):
    path = tmp_path/"raw_ticks"/"USD_JPY"/"2026-09-20.jsonl"
    path.parent.mkdir(parents=True)
    rows = []
    for i in range(4):
        rows.append(tick(
            i,
            received_at=(START + timedelta(seconds=i-0.5)).isoformat(),
        ))
    path.write_text("\n".join(json.dumps(row) for row in rows)+"\n")
    times = iter(i/100 for i in range(100))
    monkeypatch.setattr("jevpip.jev_replay.time.perf_counter", lambda: next(times))

    class Fake:
        calls = 0
        def decide(self, state, *args, **kwargs):
            self.calls += 1
            return answer(state, "KEEP")

    fake = Fake()
    result = run_jev_historical_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-20",
        start_time=None,
        duration_seconds=3,
        cadence_seconds=1,
        profile={},
        signal_policy=SignalPolicy(),
        paper_config=broker().config,
        jev_client=fake,
        acknowledged_token_use=True,
    )
    assert result["summary"]["calls"] == fake.calls
    assert fake.calls > 0


def test_replay_rejects_excessive_exchange_clock_lead_before_call(tmp_path):
    path = tmp_path/"raw_ticks"/"USD_JPY"/"2026-09-20.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(tick(
        10,
        received_at=START.isoformat(),
    ))+"\n")

    class MustNotCall:
        def decide(self, *args, **kwargs):
            pytest.fail("must not call Jev")

    with pytest.raises(ValueError, match="clock skew exceeds"):
        run_jev_historical_replay(
            tmp_path,
            instrument_id="USD_JPY",
            date="2026-09-20",
            start_time=None,
            duration_seconds=1,
            cadence_seconds=1,
            profile={},
            signal_policy=SignalPolicy(),
            paper_config=broker().config,
            jev_client=MustNotCall(),
            acknowledged_token_use=True,
        )


def test_live_controller_persists_both_reversal_legs(tmp_path):
    from jevpip.config import Settings
    from jevpip.web.controller import UIController
    ui = UIController(Settings(data_dir=tmp_path))
    b = broker()
    ui._paper, ui._paper_config = b, b.config
    ui._trace_run_id = "synthetic-test"
    ui._trace_run_config = {"paper": asdict(b.config)}
    async def run():
        for second, choice in [(0, "LONG_BASE"), (2, "SHORT_BASE")]:
            await ui._on_update({"kind": "tick", **tick(second)})
            await ui._on_update({"kind": "decision", **event_for(b, second, choice)})
            await ui._on_update({"kind": "tick", **tick(second+0.2)})
    asyncio.run(run())
    rows = [json.loads(line) for line in (tmp_path/"decision_traces"/"USD_JPY"/"2026-09-20.jsonl").read_text().splitlines()]
    reversal = rows[-1]
    assert reversal["cost_model"]["version"] == "target-paper-v1"
    legs = reversal["trade_link"]["executions"]
    assert [leg["action"] for leg in legs] == ["CLOSE", "OPEN"]
    assert legs[0]["decision_id"] == legs[1]["decision_id"]
    assert reversal["position_management"]["account_version_after"] == 3
