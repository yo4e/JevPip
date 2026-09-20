from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest

from jevpip.broker.paper import PaperConfig
from jevpip.decision_trace import COST_MODEL_VERSION, TRACE_SCHEMA_VERSION
from jevpip.experiment import (
    read_decision_traces,
    run_abcd_experiment,
    run_abcd_experiment_file,
)


def _source_config() -> PaperConfig:
    return PaperConfig(
        initial_balance=100000,
        size=1000,
        strategy="momentum",
        strategy_enabled=True,
        jev_direct_enabled=False,
        price_unit=0.01,
        move_unit_label="pips",
        momentum_window_seconds=1,
        momentum_trigger_units=0.5,
        max_spread_units=2,
        take_profit_units=0.5,
        stop_loss_units=5,
        max_hold_seconds=10,
        cooldown_seconds=0,
        jev_signal_max_age_seconds=3,
        jev_direction_gate_enabled=True,
        fee_rate=0,
        fee_label="test",
        slippage_units=0,
        deterministic_supervisor_enabled=True,
        max_market_age_seconds=5,
    )


def _row(
    second: int,
    bid: float,
    ask: float,
    *,
    jev_signal: str = "LONG",
    event_allow: bool = True,
    combined_allow: bool = True,
    combined_reason: str = "code:event_ok; jev:normal",
    run_id: str = "run-c",
) -> dict:
    at = f"2026-09-20T00:00:{second:02d}+00:00"
    config = _source_config()
    return {
        "kind": "paper_decision_trace",
        "schema_version": TRACE_SCHEMA_VERSION,
        "run_id": run_id,
        "recorded_at": at,
        "instrument_id": "USD_JPY",
        "run_config": {
            "started_at": "2026-09-20T00:00:00+00:00",
            "profile_name": "minimal",
            "with_jev": True,
            "signal_policy_name": "research_default",
            "paper": asdict(config),
        },
        "cost_model": {
            "version": COST_MODEL_VERSION,
            "spread": "real_bid_ask",
            "fee_rate_per_execution": 0,
            "fee_label": "test",
            "slippage_units": 0,
            "short_is_synthetic": False,
        },
        "market": {
            "market_timestamp": at,
            "received_at": at,
            "bid": str(bid),
            "ask": str(ask),
            "spread_units": round((ask - bid) / 0.01, 3),
            "status": "OPEN",
        },
        "code_candidate": {
            "signal": "WAIT",
            "reason": "source-placeholder",
            "metrics": {},
        },
        "entry_candidate": {
            "signal": "WAIT",
            "reason": "source-placeholder",
            "metrics": {},
        },
        "jev_direction": {
            "signal": jev_signal,
            "basis_at": at,
            "requested_at": at,
            "available_at": at,
            "age_seconds": 0,
        },
        "gates": {
            "deterministic": {
                "state": "NORMAL",
                "reason": "ok",
                "allow_entry": True,
            },
            "event": {
                "state": "NORMAL" if event_allow else "PAUSE_ENTRY",
                "reason": "event_ok" if event_allow else "scheduled_event_high:test",
                "allow_entry": event_allow,
            },
            "jev_supervisor": {
                "state": "NORMAL",
                "strategy": None,
                "confidence": 0.8,
                "ttl_seconds": 20,
                "reason": "normal",
            },
            "combined_supervisor": {
                "state": "NORMAL" if combined_allow else "PAUSE_ENTRY",
                "reason": combined_reason,
                "allow_entry": combined_allow,
                "strategy": None,
                "confidence": 0.8,
                "ttl_seconds": 20,
            },
        },
        "blocked_entry_reason": None,
        "position_management": {
            "action": None,
            "detail": {},
            "target_opened_at": None,
            "close_confirmations": 0,
            "required_close_confirmations": 2,
            "action_age_seconds": None,
        },
        "final_action": "NOOP",
        "holding_seconds": None,
        "turnover_size": 0,
        "trade_link": {
            "position_before_opened_at": None,
            "position_after_opened_at": None,
            "trade": None,
        },
    }


def _rows() -> list[dict]:
    return [
        _row(0, 150.000, 150.002),
        _row(
            1,
            150.010,
            150.012,
            event_allow=False,
            combined_allow=False,
            combined_reason="code:scheduled_event_high:test; jev:normal",
        ),
        _row(2, 150.020, 150.022, jev_signal="WAIT"),
        _row(3, 150.030, 150.032, jev_signal="LONG"),
        _row(4, 150.040, 150.042, jev_signal="LONG"),
    ]


def test_abcd_experiment_replays_same_trace_and_cost_model():
    result = run_abcd_experiment(_rows())

    assert result["source"]["source_variant"] == "C"
    assert result["source"]["cost_model_version"] == COST_MODEL_VERSION
    assert set(result["variants"]) == {"A", "B", "C", "D"}

    for name in ("A", "B", "C", "D"):
        row = result["variants"][name]
        assert row["ticks"] == 5
        assert row["cost_model"]["spread"] == "real_bid_ask"
        assert "net_pnl" in row
        assert "max_drawdown" in row

    assert result["variants"]["B"]["pause_duration_seconds"] == 1.0
    assert result["variants"]["C"]["pause_duration_seconds"] == 1.0


def test_blocked_entry_counterfactual_reports_missed_profit():
    result = run_abcd_experiment(_rows())

    b = result["variants"]["B"]["counterfactual"]
    assert b["blocked_candidate_episodes"] >= 1
    assert b["evaluated_non_overlapping"] >= 1
    assert b["missed_profit"] > 0
    assert b["missed_profit_count"] >= 1
    assert b["false_pause_count"] == b["missed_profit_count"]

    c = result["variants"]["C"]["counterfactual"]
    assert c["blocked_candidate_episodes"] >= b["blocked_candidate_episodes"]
    assert any(
        trade["blocked_reason"].startswith("jev_gate_")
        or trade["blocked_reason"].startswith("code:")
        for trade in c["trades"]
    )


def test_experiment_requires_full_c_source_run():
    rows = _rows()
    rows[0]["run_config"]["with_jev"] = False
    with pytest.raises(ValueError, match="Jev enabled"):
        run_abcd_experiment(rows)


def test_read_trace_requires_run_id_when_file_contains_multiple_runs(
    tmp_path: Path,
):
    path = tmp_path / "trace.jsonl"
    rows = [_row(0, 150.0, 150.002, run_id="one")]
    rows += [_row(1, 150.01, 150.012, run_id="two")]
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="multiple run_id"):
        read_decision_traces(path)

    selected = read_decision_traces(path, run_id="one")
    assert len(selected) == 1
    assert selected[0]["run_id"] == "one"


def test_run_experiment_file(tmp_path: Path):
    path = tmp_path / "trace.jsonl"
    rows = _rows()
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    result = run_abcd_experiment_file(path)
    assert result["source"]["run_id"] == "run-c"
    assert result["variants"]["A"]["ticks"] == len(rows)
    assert result["limitations"]


def test_variable_fee_breakeven_diagnostic_does_not_change_cost_model_identity():
    rows = _rows()
    rows[0]["cost_model"]["estimated_fee_break_even_units"] = 0.5
    rows[1]["cost_model"]["estimated_fee_break_even_units"] = 0.7

    result = run_abcd_experiment(rows)
    assert result["source"]["cost_model_version"] == COST_MODEL_VERSION


def test_missing_jev_timing_preserves_warmup_block():
    rows = _rows()
    for index in (0, 1):
        rows[index]["jev_direction"] = {
            "signal": "WAIT",
            "basis_at": None,
            "requested_at": None,
            "available_at": None,
            "age_seconds": None,
        }
    rows[1]["gates"]["event"] = {
        "state": "NORMAL",
        "reason": "event_ok",
        "allow_entry": True,
    }
    rows[1]["gates"]["combined_supervisor"] = {
        "state": "NORMAL",
        "reason": "code:event_ok",
        "allow_entry": True,
        "strategy": None,
        "confidence": None,
        "ttl_seconds": None,
    }
    result = run_abcd_experiment(rows)
    trades = result["variants"]["C"]["counterfactual"]["trades"]
    assert any(item["blocked_reason"] == "jev_gate_warmup" for item in trades)

