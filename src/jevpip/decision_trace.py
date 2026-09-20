from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from jevpip.storage.jsonl import append_jsonl

TRACE_SCHEMA_VERSION = 1
COST_MODEL_VERSION = "paper-v1"


def build_decision_trace(
    *,
    run_id: str,
    instrument_id: str,
    recorded_at: str,
    run_config: dict[str, Any],
    cost_model: dict[str, Any],
    broker_trace: dict[str, Any],
    event_supervisor: dict[str, Any],
    jev_supervisor: dict[str, Any] | None,
    combined_supervisor: dict[str, Any],
) -> dict[str, Any]:
    """Build the stable paper decision-trace envelope used by experiments.

    The broker owns strategy/execution facts. The controller adds run metadata
    and the external/Jev supervisor layers that sit outside PaperBroker.
    """

    required = {
        "market",
        "code_candidate",
        "entry_candidate",
        "jev_direction",
        "deterministic_supervisor",
        "blocked_entry_reason",
        "position_management",
        "final_action",
        "holding_seconds",
        "turnover_size",
        "trade_link",
    }
    missing = sorted(required.difference(broker_trace))
    if missing:
        raise ValueError(f"broker trace is missing required fields: {', '.join(missing)}")

    return {
        "kind": "paper_decision_trace",
        "schema_version": TRACE_SCHEMA_VERSION,
        "run_id": run_id,
        "recorded_at": recorded_at,
        "instrument_id": instrument_id,
        "run_config": dict(run_config),
        "cost_model": {
            "version": COST_MODEL_VERSION,
            **dict(cost_model),
        },
        "market": broker_trace["market"],
        "code_candidate": broker_trace["code_candidate"],
        "entry_candidate": broker_trace["entry_candidate"],
        "jev_direction": broker_trace["jev_direction"],
        "gates": {
            "deterministic": broker_trace["deterministic_supervisor"],
            "event": dict(event_supervisor),
            "jev_supervisor": (
                None if jev_supervisor is None else dict(jev_supervisor)
            ),
            "combined_supervisor": dict(combined_supervisor),
        },
        "blocked_entry_reason": broker_trace["blocked_entry_reason"],
        "position_management": broker_trace["position_management"],
        "final_action": broker_trace["final_action"],
        "holding_seconds": broker_trace["holding_seconds"],
        "turnover_size": broker_trace["turnover_size"],
        "trade_link": broker_trace["trade_link"],
    }


def append_decision_trace(data_dir: Path, record: dict[str, Any]) -> Path:
    """Persist one trace row under a UTC-market-date partition."""

    instrument_id = str(record.get("instrument_id") or "").strip()
    if not instrument_id or "/" in instrument_id or "\\" in instrument_id:
        raise ValueError("instrument_id is required and must be path-safe")

    market = record.get("market")
    if not isinstance(market, dict) or not market.get("market_timestamp"):
        raise ValueError("market.market_timestamp is required")
    timestamp = datetime.fromisoformat(
        str(market["market_timestamp"]).replace("Z", "+00:00")
    )
    day = timestamp.date().isoformat()
    path = data_dir / "decision_traces" / instrument_id / f"{day}.jsonl"
    append_jsonl(path, record)
    return path
