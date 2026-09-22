from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import jevpip.jev_replay as replay
from jevpip.broker.paper import PaperConfig
from jevpip.jev_replay import (
    MAX_JEV_REPLAY_CALLS,
    plan_jev_replay,
    preview_jev_replay,
    run_jev_historical_replay,
)
from jevpip.signals import SignalPolicy


class FakeJevClient:
    def __init__(self) -> None:
        self.calls = 0

    def decide(
        self,
        state,
        horizon="5s",
        *,
        supervisor_strategies=(),
        instrument_label="the instrument",
    ):
        self.calls += 1
        return {
            "model": "jev-test",
            "usage": {"input_tokens": 100, "output_tokens": 10},
            "answers": {
                "direction": {
                    "choice": "UP",
                    "probabilities": {"UP": 0.9, "DOWN": 0.05, "FLAT": 0.05},
                },
                "market_is_noisy": {"noul": 0.1},
                "reversal_risk": {"noul": 0.1},
                "trend_strength": {"score": 3},
            },
        }


def _raw_tick(second: float, bid: float, ask: float) -> dict:
    whole = int(second)
    micros = int(round((second - whole) * 1_000_000))
    stamp = f"2026-09-20T00:00:{whole:02d}"
    if micros:
        stamp += f".{micros:06d}"
    stamp += "+00:00"
    return {
        "instrument_id": "USD_JPY",
        "symbol": "USD_JPY",
        "display_symbol": "USD/JPY",
        "bid": str(bid),
        "ask": str(ask),
        "market_timestamp": stamp,
        "received_at": stamp,
        "price_unit": "0.01",
        "move_unit_label": "pips",
        "status": "OPEN",
        "raw": None,
    }


def _write_ticks(data_dir: Path) -> Path:
    path = data_dir / "raw_ticks" / "USD_JPY" / "2026-09-20.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        _raw_tick(0.0, 150.000, 150.002),
        _raw_tick(0.5, 150.005, 150.007),
        _raw_tick(1.0, 150.010, 150.012),
        _raw_tick(1.5, 150.015, 150.017),
        _raw_tick(2.0, 150.020, 150.022),
        _raw_tick(2.5, 150.025, 150.027),
        _raw_tick(3.0, 150.030, 150.032),
        _raw_tick(3.5, 150.035, 150.037),
        _raw_tick(4.0, 150.040, 150.042),
    ]
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    return path


def _historical_ticks():
    rows = []
    for minute, (bid, ask) in enumerate(
        [
            (150.000, 150.002),
            (150.010, 150.012),
            (150.020, 150.022),
            (150.030, 150.032),
        ],
        start=1,
    ):
        stamp = f"2026-09-19T00:{minute:02d}:00+00:00"
        rows.append(
            replay._tick_from_row(
                {
                    "instrument_id": "USD_JPY",
                    "symbol": "USD_JPY",
                    "display_symbol": "USD/JPY",
                    "bid": str(bid),
                    "ask": str(ask),
                    "market_timestamp": stamp,
                    "received_at": stamp,
                    "price_unit": "0.01",
                    "move_unit_label": "pips",
                    "status": "HISTORICAL",
                }
            )
        )
    return rows


def _paper_config() -> PaperConfig:
    return PaperConfig(
        initial_balance=100000,
        size=1000,
        strategy="momentum",
        strategy_enabled=False,
        jev_direct_enabled=True,
        price_unit=0.01,
        move_unit_label="pips",
        max_spread_units=10,
        take_profit_units=100,
        stop_loss_units=100,
        max_hold_seconds=10,
        cooldown_seconds=0,
        jev_signal_max_age_seconds=10,
        fee_rate=0,
        slippage_units=0,
        deterministic_supervisor_enabled=False,
    )


def test_plan_uses_raw_ticks_and_configurable_cadence(tmp_path: Path):
    _write_ticks(tmp_path)

    one_second = plan_jev_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-20",
        start_time="00:00:00",
        duration_seconds=4,
        cadence_seconds=1,
    )
    two_seconds = plan_jev_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-20",
        start_time="00:00:00",
        duration_seconds=4,
        cadence_seconds=2,
    )

    five_minutes = plan_jev_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-20",
        start_time="00:00:00",
        duration_seconds=4,
        cadence_seconds=300,
    )
    fifteen_minutes = plan_jev_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-20",
        start_time="00:00:00",
        duration_seconds=4,
        cadence_seconds=900,
    )

    assert one_second.selected_ticks == 9
    assert one_second.planned_max_calls == 5
    assert two_seconds.planned_max_calls == 3
    assert five_minutes.planned_max_calls == 1
    assert fifteen_minutes.planned_max_calls == 1


def test_event_replay_call_budget_is_independent_of_hidden_cadence(tmp_path: Path):
    _write_ticks(tmp_path)

    fast = plan_jev_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-20",
        start_time="00:00:00",
        duration_seconds=4,
        cadence_seconds=1,
        event_driven=True,
    )
    slow = plan_jev_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-20",
        start_time="00:00:00",
        duration_seconds=4,
        cadence_seconds=60,
        event_driven=True,
    )

    assert fast.planned_max_calls == slow.planned_max_calls == 9
    assert fast.call_budget_basis == slow.call_budget_basis == "event_tick_upper_bound_capped"
    assert fast.event_driven is True
    assert slow.event_driven is True


def test_plan_prefers_raw_ticks_over_historical_fallback(tmp_path: Path, monkeypatch):
    _write_ticks(tmp_path)

    def must_not_fetch(*args, **kwargs):
        pytest.fail("historical fallback must not run when raw ticks exist")

    monkeypatch.setattr(replay, "load_historical_ticks", must_not_fetch)
    plan = plan_jev_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-20",
        start_time=None,
        duration_seconds=4,
        cadence_seconds=1,
    )
    assert plan.source_kind == "raw_ticks"
    assert plan.source_path is not None
    assert plan.replay_mode == "raw_tick"


class FakeEventJevClient:
    def __init__(self) -> None:
        self.calls = 0

    @staticmethod
    def _select(key, choices):
        return {
            "type": "choice",
            "choice": key,
            "confidence": 0.8,
            "probabilities": {
                candidate: 1.0 if candidate == key else 0.0
                for candidate in choices
            },
        }

    def decide(self, state, horizon="5s", *, supervisor_strategies=(), instrument_label="the instrument"):
        self.calls += 1
        plan = state["autopilot"]["event_plan"]
        trade_plans = plan["trade_plans"]
        trade_choice = next(
            (
                key
                for key, value in trade_plans.items()
                if value.get("action") == "MARKET"
            ),
            next(iter(trade_plans)),
        )
        return {
            "model": "event-test",
            "usage": {"input_tokens": 100, "output_tokens": 10},
            "answers": {
                "event_trade_plan": self._select(trade_choice, trade_plans),
                "event_wake_plan": self._select("TIMEOUT_30M", plan["wake_plans"]),
                "event_expiry_plan": self._select("EXPIRY_30M", plan["expiry_plans"]),
            },
        }


def test_event_replay_marks_result_truncated_when_call_budget_is_exhausted(tmp_path: Path, monkeypatch):
    _write_ticks(tmp_path)
    monkeypatch.setattr(replay, "MAX_JEV_REPLAY_CALLS", 1)
    config = replace(
        _paper_config(),
        autopilot_enabled=True,
        autopilot_style="event",
        autopilot_max_risk_pct=0.05,
        paper_leverage=25,
    )
    client = FakeEventJevClient()

    result = run_jev_historical_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-20",
        start_time="00:00:00",
        duration_seconds=4,
        cadence_seconds=60,
        profile={"quote": True},
        signal_policy=SignalPolicy(),
        paper_config=config,
        jev_client=client,
        acknowledged_token_use=True,
    )

    assert result["call_budget_exhausted"] is True
    assert result["completed_full_window"] is False
    assert result["summary"]["call_budget_exhausted"] is True
    assert result["summary"]["completed_full_window"] is False
    assert result["effective_end"] < result["selected_end"]
    assert any("truncated replay" in item for item in result["limitations"])


def test_plan_falls_back_to_gmo_historical_1m_without_raw_ticks(
    tmp_path: Path,
    monkeypatch,
):
    ticks = _historical_ticks()

    def fake_history(date, *, instrument_id, limit=None):
        assert date == "20260919"
        assert instrument_id == "USD_JPY"
        return ticks, "fx_bid_ask_close"

    monkeypatch.setattr(replay, "load_historical_ticks", fake_history)
    plan = plan_jev_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-19",
        start_time=None,
        duration_seconds=180,
        cadence_seconds=1,
    )
    assert plan.source_kind == "gmo_historical_1m"
    assert plan.source_path is None
    assert plan.replay_mode == "fx_bid_ask_close"
    assert plan.selected_ticks == 4
    assert plan.planned_max_calls == 4

    preview = preview_jev_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-19",
        start_time=None,
        duration_seconds=180,
        cadence_seconds=1,
    )
    assert preview["source_kind"] == "gmo_historical_1m"
    assert "GMO historical 1分足" in preview["source_note"]
    assert "概算/smoke test" in preview["source_note"]
    assert "TP/SL到達順序" in preview["source_note"]


def test_replay_runs_on_historical_1m_fallback_and_marks_result(
    tmp_path: Path,
    monkeypatch,
):
    ticks = _historical_ticks()
    monkeypatch.setattr(
        replay,
        "load_historical_ticks",
        lambda date, *, instrument_id, limit=None: (ticks, "fx_bid_ask_close"),
    )
    client = FakeJevClient()
    result = run_jev_historical_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-19",
        start_time=None,
        duration_seconds=180,
        cadence_seconds=60,
        profile={"quote": True},
        signal_policy=SignalPolicy(),
        paper_config=_paper_config(),
        jev_client=client,
        acknowledged_token_use=True,
    )
    assert result["data_source"] == "gmo_historical_1m"
    assert result["replay_mode"] == "fx_bid_ask_close"
    assert "概算/smoke test" in result["data_source_note"]
    assert "live相当のFifty+成績として扱わない" in result["data_source_note"]
    assert result["summary"]["calls"] == client.calls
    assert client.calls > 0


def test_preview_estimates_tokens_from_recent_reported_usage(tmp_path: Path):
    _write_ticks(tmp_path)
    decisions = tmp_path / "decisions" / "USD_JPY" / "2026-09-20.jsonl"
    decisions.parent.mkdir(parents=True, exist_ok=True)
    decisions.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "kind": "decision",
                        "jev": {
                            "usage": {
                                "input_tokens": 100,
                                "output_tokens": 10,
                            }
                        },
                    }
                ),
                json.dumps(
                    {
                        "kind": "decision",
                        "jev": {
                            "usage": {
                                "input_tokens": 120,
                                "output_tokens": 20,
                            }
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    preview = preview_jev_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-20",
        start_time="00:00:00",
        duration_seconds=4,
        cadence_seconds=1,
    )

    estimate = preview["token_estimate"]
    assert estimate["reported_calls"] == 2
    assert estimate["average_input_tokens"] == 110.0
    assert estimate["average_output_tokens"] == 15.0
    assert estimate["estimated_total_tokens"] == 625
    assert estimate["estimated_billable_input_tokens"] == 550
    assert estimate["estimated_output_tokens"] == 75
    assert estimate["estimated_cost_usd"] == pytest.approx(0.0000231)
    assert estimate["input_price_usd_per_million_tokens"] == 0.042
    assert estimate["output_price_usd_per_million_tokens"] == 0.0
    assert preview["within_call_limit"] is True
    assert "input tokenが課金対象" in preview["warning"]
    assert "output tokenは無料" in preview["warning"]


def test_preview_leaves_token_estimate_unknown_without_usage(tmp_path: Path):
    _write_ticks(tmp_path)
    preview = preview_jev_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-20",
        start_time=None,
        duration_seconds=4,
        cadence_seconds=1,
    )
    assert preview["token_estimate"]["basis"] == "unavailable"
    assert preview["token_estimate"]["estimated_total_tokens"] is None


def test_replay_requires_explicit_token_acknowledgement(tmp_path: Path):
    _write_ticks(tmp_path)
    with pytest.raises(ValueError, match="acknowledgement"):
        run_jev_historical_replay(
            tmp_path,
            instrument_id="USD_JPY",
            date="2026-09-20",
            start_time="00:00:00",
            duration_seconds=4,
            cadence_seconds=1,
            profile={"quote": True},
            signal_policy=SignalPolicy(),
            paper_config=_paper_config(),
            jev_client=FakeJevClient(),
            acknowledged_token_use=False,
        )


def test_replay_calls_current_jev_on_raw_tick_history_and_reports_usage(tmp_path: Path):
    _write_ticks(tmp_path)
    client = FakeJevClient()

    result = run_jev_historical_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-20",
        start_time="00:00:00",
        duration_seconds=4,
        cadence_seconds=1,
        profile={"quote": True, "returns_seconds": [1]},
        signal_policy=SignalPolicy(
            min_direction_probability=0.65,
            min_direction_margin=0.20,
        ),
        paper_config=_paper_config(),
        jev_client=client,
        acknowledged_token_use=True,
    )

    summary = result["summary"]
    assert 1 <= summary["calls"] <= summary["planned_max_calls"]
    assert summary["calls"] == client.calls
    assert summary["reported_usage_calls"] == summary["calls"]
    assert summary["input_tokens"] == summary["calls"] * 100
    assert summary["output_tokens"] == summary["calls"] * 10
    assert summary["total_tokens"] == summary["calls"] * 110
    assert summary["billable_input_tokens"] == summary["calls"] * 100
    assert summary["estimated_cost_usd"] == pytest.approx(
        summary["billable_input_tokens"] * 0.042 / 1_000_000
    )
    assert summary["output_price_usd_per_million_tokens"] == 0.0
    assert result["cadence_seconds"] == 1
    assert result["selected_ticks"] == 9
    assert "current Jev model" in result["limitations"][0]
    output = Path(result["output"])
    assert output.exists()
    saved = output.read_text(encoding="utf-8")
    assert "jev_historical_decision" in saved
    assert "jev_historical_replay_summary" in saved


def test_call_limit_blocks_run_but_preview_still_reports_it(
    tmp_path: Path,
    monkeypatch,
):
    _write_ticks(tmp_path)
    import jevpip.jev_replay as replay

    monkeypatch.setattr(replay, "MAX_JEV_REPLAY_CALLS", 2)
    preview = replay.preview_jev_replay(
        tmp_path,
        instrument_id="USD_JPY",
        date="2026-09-20",
        start_time="00:00:00",
        duration_seconds=4,
        cadence_seconds=1,
    )
    assert preview["planned_max_calls"] == 5
    assert preview["within_call_limit"] is False

    with pytest.raises(ValueError, match="exceed"):
        replay.run_jev_historical_replay(
            tmp_path,
            instrument_id="USD_JPY",
            date="2026-09-20",
            start_time="00:00:00",
            duration_seconds=4,
            cadence_seconds=1,
            profile={"quote": True},
            signal_policy=SignalPolicy(),
            paper_config=_paper_config(),
            jev_client=FakeJevClient(),
            acknowledged_token_use=True,
        )
