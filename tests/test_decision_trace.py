import asyncio
import json

from jevpip.broker.paper import PaperBroker, PaperConfig
from jevpip.config import Settings
from jevpip.decision_trace import (
    COST_MODEL_VERSION,
    TRACE_SCHEMA_VERSION,
    append_decision_trace,
    build_decision_trace,
)
from jevpip.web.controller import UIController


def tick(at: str, bid: str, ask: str) -> dict:
    return {
        "kind": "tick",
        "instrument_id": "USD_JPY",
        "display_symbol": "USD/JPY",
        "market_timestamp": at,
        "received_at": at,
        "bid": bid,
        "ask": ask,
        "status": "OPEN",
        "features": {},
    }


def test_blocked_entry_trace_preserves_code_candidate():
    broker = PaperBroker(
        PaperConfig(
            price_unit=0.01,
            momentum_window_seconds=5,
            momentum_trigger_units=0.5,
            cooldown_seconds=0,
        )
    )
    broker.on_tick(tick("2026-09-20T00:00:00+00:00", "150.000", "150.002"))
    events = broker.on_tick(
        tick("2026-09-20T00:00:05+00:00", "150.010", "150.012"),
        allow_entry=False,
        entry_gate_reason="code:event_window",
    )

    assert events == []
    trace = broker.last_decision_trace
    assert trace is not None
    assert trace["code_candidate"]["signal"] == "LONG"
    assert trace["entry_candidate"]["signal"] == "LONG"
    assert trace["blocked_entry_reason"] == "code:event_window"
    assert trace["final_action"] == "NOOP"
    assert trace["trade_link"]["trade"] is None


def test_direction_gate_trace_keeps_pre_gate_candidate():
    broker = PaperBroker(
        PaperConfig(
            price_unit=0.01,
            momentum_window_seconds=5,
            momentum_trigger_units=0.5,
            cooldown_seconds=0,
            jev_direction_gate_enabled=True,
        )
    )
    broker.on_tick(tick("2026-09-20T00:00:00+00:00", "150.000", "150.002"))
    broker.on_decision(
        {
            "direction_signal": "WAIT",
            "basis_market_timestamp": "2026-09-20T00:00:04+00:00",
            "requested_at": "2026-09-20T00:00:04+00:00",
            "available_at": "2026-09-20T00:00:04+00:00",
        }
    )
    broker.on_tick(tick("2026-09-20T00:00:05+00:00", "150.010", "150.012"))

    trace = broker.last_decision_trace
    assert trace is not None
    assert trace["code_candidate"]["signal"] == "LONG"
    assert trace["entry_candidate"]["signal"] == "WAIT"
    assert trace["entry_candidate"]["reason"] == "jev_gate_wait"
    assert trace["blocked_entry_reason"] == "jev_gate_wait"


def test_build_and_append_decision_trace(tmp_path):
    broker_trace = {
        "market": {
            "market_timestamp": "2026-09-20T00:00:05+00:00",
            "received_at": "2026-09-20T00:00:05+00:00",
            "bid": "150.010",
            "ask": "150.012",
            "spread_units": 0.2,
            "status": "OPEN",
        },
        "code_candidate": {"signal": "LONG", "reason": "momentum", "metrics": {}},
        "entry_candidate": {"signal": "WAIT", "reason": "event_block", "metrics": {}},
        "jev_direction": {"signal": "WAIT", "age_seconds": 1.0},
        "deterministic_supervisor": {
            "state": "NORMAL",
            "reason": "ok",
            "allow_entry": True,
        },
        "blocked_entry_reason": "event_block",
        "position_management": {"action": None},
        "final_action": "NOOP",
        "holding_seconds": None,
        "turnover_size": 0.0,
        "trade_link": {"trade": None},
    }
    record = build_decision_trace(
        run_id="run-1",
        instrument_id="USD_JPY",
        recorded_at="2026-09-20T00:00:05+00:00",
        run_config={"paper": {"strategy": "momentum"}},
        cost_model={"spread": "real_bid_ask"},
        broker_trace=broker_trace,
        event_supervisor={
            "state": "PAUSE_ENTRY",
            "reason": "event_window",
            "allow_entry": False,
        },
        jev_supervisor=None,
        combined_supervisor={
            "state": "PAUSE_ENTRY",
            "reason": "code:event_window",
            "allow_entry": False,
            "strategy": None,
            "confidence": None,
            "ttl_seconds": None,
        },
    )

    path = append_decision_trace(tmp_path, record)
    saved = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert saved["schema_version"] == TRACE_SCHEMA_VERSION
    assert saved["cost_model"]["version"] == COST_MODEL_VERSION
    assert saved["run_id"] == "run-1"
    assert saved["gates"]["event"]["state"] == "PAUSE_ENTRY"
    assert path.name == "2026-09-20.jsonl"


def test_controller_persists_trace_for_each_paper_tick(tmp_path):
    config = PaperConfig(
        price_unit=0.01,
        momentum_window_seconds=5,
        momentum_trigger_units=0.5,
        cooldown_seconds=0,
    )
    controller = UIController(Settings(data_dir=tmp_path))
    controller._instrument_id = "USD_JPY"
    controller._paper_config = config
    controller._paper = PaperBroker(config)
    controller._trace_run_id = "controller-test"
    controller._trace_run_config = {
        "started_at": "2026-09-20T00:00:00+00:00",
        "profile_name": "minimal",
        "with_jev": False,
        "signal_policy_name": None,
        "paper": {},
    }

    asyncio.run(
        controller._on_update(
            tick("2026-09-20T00:00:00+00:00", "150.000", "150.002")
        )
    )

    path = tmp_path / "decision_traces" / "USD_JPY" / "2026-09-20.jsonl"
    saved = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert saved["kind"] == "paper_decision_trace"
    assert saved["run_id"] == "controller-test"
    assert saved["instrument_id"] == "USD_JPY"
    assert saved["gates"]["combined_supervisor"]["allow_entry"] is True
    assert controller.snapshot()["latest_decision_trace"]["run_id"] == "controller-test"
