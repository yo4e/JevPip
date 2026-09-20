from __future__ import annotations

import json
import random
import asyncio
import threading
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from jevpip.broker.autopilot import AutopilotBroker, make_paper_broker
from jevpip.broker.paper import PaperBroker, PaperConfig
from jevpip.jev.autopilot import REASONS, attach_target, question_specs
from jevpip.jev_replay import run_jev_historical_replay
from jevpip.signals import SignalPolicy
from jevpip.web.app import PaperDemoInput
from jevpip.async_work import joined_thread

START = datetime(2026, 9, 20, tzinfo=timezone.utc)


def tick(second, bid=99, ask=101, **extra):
    at = (START + timedelta(seconds=second)).isoformat()
    return {"instrument_id": "USD_JPY", "market_timestamp": at, "received_at": at,
            "bid": str(bid), "ask": str(ask), "status": "OPEN", **extra}


def broker(**extra):
    cfg = PaperConfig(autopilot_enabled=True, size=10, price_unit=1,
                      fee_rate=0.001, slippage_units=0.5, autopilot_confirmations=1)
    return AutopilotBroker(replace(cfg, **extra))


def answer(state, choice="LONG_BASE"):
    def select(key, choices):
        return {"type": "choice", "choice": key, "confidence": 0.8,
                "probabilities": {k: 1.0 if k == key else 0.0 for k in choices}}
    return {"model": "test-only", "usage": {"input_tokens": 100, "output_tokens": 10},
            "answers": {"target_position": select(choice, state["autopilot"]["targets"]),
                        "target_reason": select("TREND", REASONS)}}


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
    assert set(question_specs(state)) == {"target_position", "target_reason"}
    assert "secret" not in json.dumps(state).lower()
    event = event_for(b, 120)
    event["jev"]["answers"]["target_position"]["confidence"] = float("nan")
    attach_target(event, state)
    assert "target_error" in event


def test_replay_uses_same_policy_and_preserves_full_diagnostics(tmp_path, monkeypatch):
    path = tmp_path/"raw_ticks"/"USD_JPY"/"2026-09-20.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text("\n".join(json.dumps(tick(i, 99+i, 101+i)) for i in range(12))+"\n")
    times = iter(i/10 for i in range(100))
    monkeypatch.setattr("jevpip.jev_replay.time.perf_counter", lambda: next(times))
    class Fake:
        calls = 0
        def decide(self, state, horizon, **kwargs):
            assert horizon == "600s"
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
    assert set(captured["questions"]) == {"target_position", "target_reason"}
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
    with pytest.raises(ValueError, match="causal, ordered"):
        run_jev_historical_replay(tmp_path, instrument_id="USD_JPY", date="2026-09-20",
            start_time=None, duration_seconds=10, cadence_seconds=1, profile={}, signal_policy=SignalPolicy(),
            paper_config=broker().config, jev_client=None, acknowledged_token_use=True)


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
