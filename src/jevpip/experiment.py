from __future__ import annotations

import json
from dataclasses import asdict, fields, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from jevpip.broker.paper import PaperBroker, PaperConfig
from jevpip.decision_trace import COST_MODEL_VERSION, TRACE_SCHEMA_VERSION

VARIANT_DESCRIPTIONS = {
    "A": "technical only",
    "B": "technical + deterministic supervisor",
    "C": "technical + deterministic + Jev supervisor",
    "D": "Jev direct direction control",
}


def read_decision_traces(
    path: Path,
    *,
    run_id: str | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for number, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{number}: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"Expected object at {path}:{number}")
            if row.get("kind") != "paper_decision_trace":
                continue
            if row.get("schema_version") != TRACE_SCHEMA_VERSION:
                raise ValueError(
                    f"Unsupported decision trace schema at {path}:{number}: "
                    f"{row.get('schema_version')!r}"
                )
            rows.append(row)

    if not rows:
        raise ValueError("No paper_decision_trace rows found.")

    run_ids = {str(row.get("run_id") or "") for row in rows}
    if "" in run_ids:
        raise ValueError("Decision trace row is missing run_id.")

    selected_run = run_id
    if selected_run is None:
        if len(run_ids) != 1:
            available = ", ".join(sorted(run_ids))
            raise ValueError(
                "Trace file contains multiple run_id values; pass run_id explicitly. "
                f"Available: {available}"
            )
        selected_run = next(iter(run_ids))

    selected = [row for row in rows if row.get("run_id") == selected_run]
    if not selected:
        raise ValueError(f"run_id not found in trace file: {selected_run}")

    selected.sort(key=lambda row: _market_at(row))
    _validate_source_run(selected)
    return selected


def _market_at(row: dict[str, Any]) -> datetime:
    market = row.get("market")
    if not isinstance(market, dict) or not market.get("market_timestamp"):
        raise ValueError("Trace row is missing market.market_timestamp.")
    return datetime.fromisoformat(
        str(market["market_timestamp"]).replace("Z", "+00:00")
    )


def _validate_source_run(rows: list[dict[str, Any]]) -> None:
    first = rows[0]
    run_config = first.get("run_config")
    if not isinstance(run_config, dict):
        raise ValueError("Trace run_config is required.")
    paper = run_config.get("paper")
    if not isinstance(paper, dict):
        raise ValueError("Trace run_config.paper is required.")

    if not bool(run_config.get("with_jev")):
        raise ValueError("A/B/C/D experiment requires a source run with Jev enabled.")
    if not bool(paper.get("strategy_enabled", True)):
        raise ValueError(
            "A/B/C/D experiment requires a source run with code strategy enabled."
        )
    if not bool(paper.get("deterministic_supervisor_enabled")):
        raise ValueError(
            "A/B/C/D experiment requires a source run with safety supervisor enabled."
        )
    if str(paper.get("strategy") or "") not in {
        "momentum",
        "rsi_mean_reversion",
        "ma_trend",
    }:
        raise ValueError("Source run must use a supported code strategy.")

    expected_run = first["run_id"]
    expected_instrument = first.get("instrument_id")
    expected_run_config = json.dumps(run_config, sort_keys=True, default=str)
    expected_cost_model = json.dumps(
        first.get("cost_model"), sort_keys=True, default=str
    )
    if first.get("cost_model", {}).get("version") != COST_MODEL_VERSION:
        raise ValueError(
            f"Unsupported cost model version: "
            f"{first.get('cost_model', {}).get('version')!r}"
        )

    for row in rows:
        if row.get("run_id") != expected_run:
            raise ValueError("Selected rows contain multiple run_id values.")
        if row.get("instrument_id") != expected_instrument:
            raise ValueError("Selected run contains multiple instruments.")
        if json.dumps(row.get("run_config"), sort_keys=True, default=str) != expected_run_config:
            raise ValueError("run_config changed inside one trace run.")
        if json.dumps(row.get("cost_model"), sort_keys=True, default=str) != expected_cost_model:
            raise ValueError("cost_model changed inside one trace run.")


def _paper_config(rows: list[dict[str, Any]]) -> PaperConfig:
    raw = rows[0]["run_config"]["paper"]
    allowed = {field.name for field in fields(PaperConfig)}
    values = {key: value for key, value in raw.items() if key in allowed}
    return PaperConfig(**values)


def _variant_configs(base: PaperConfig) -> dict[str, PaperConfig]:
    return {
        "A": replace(
            base,
            strategy_enabled=True,
            jev_direct_enabled=False,
            jev_direction_gate_enabled=False,
            deterministic_supervisor_enabled=False,
        ),
        "B": replace(
            base,
            strategy_enabled=True,
            jev_direct_enabled=False,
            jev_direction_gate_enabled=False,
            deterministic_supervisor_enabled=True,
        ),
        "C": replace(
            base,
            strategy_enabled=True,
            jev_direct_enabled=False,
            jev_direction_gate_enabled=True,
            deterministic_supervisor_enabled=True,
        ),
        "D": replace(
            base,
            strategy_enabled=False,
            jev_direct_enabled=True,
            jev_direction_gate_enabled=False,
            deterministic_supervisor_enabled=False,
        ),
    }


def _tick_from_trace(row: dict[str, Any]) -> dict[str, Any]:
    market = row["market"]
    return {
        "instrument_id": row["instrument_id"],
        "market_timestamp": market["market_timestamp"],
        "received_at": market.get("received_at") or market["market_timestamp"],
        "bid": market["bid"],
        "ask": market["ask"],
        "status": market.get("status") or "",
    }


def _feed_jev_direction(broker: PaperBroker, row: dict[str, Any]) -> None:
    jev = row.get("jev_direction")
    if not isinstance(jev, dict):
        return
    signal = str(jev.get("signal") or "WAIT")
    if signal not in {"LONG", "SHORT", "WAIT"}:
        signal = "WAIT"
    requested = (
        jev.get("requested_at")
        or jev.get("basis_at")
        or row["market"]["market_timestamp"]
    )
    available = jev.get("available_at") or requested
    broker.on_decision(
        {
            "direction_signal": signal,
            "basis_market_timestamp": (
                jev.get("basis_at") or row["market"]["market_timestamp"]
            ),
            "requested_at": requested,
            "available_at": available,
        }
    )


def _gate(row: dict[str, Any], name: str) -> dict[str, Any]:
    gates = row.get("gates")
    if not isinstance(gates, dict):
        return {}
    value = gates.get(name)
    return value if isinstance(value, dict) else {}


def _allow(value: dict[str, Any], *, default: bool = True) -> bool:
    raw = value.get("allow_entry")
    return default if raw is None else bool(raw)


def _blocked_supervisor_reason(reason: str | None) -> bool:
    if not reason:
        return False
    if reason in {"cooldown", "end_of_sample"}:
        return False
    return reason.startswith("deterministic:") or reason.startswith("code:") or reason.startswith(
        "jev_gate_"
    )


def _collect_blocked_episode(
    *,
    variant: str,
    row_index: int,
    broker: PaperBroker,
    active_key: tuple[str, str] | None,
) -> tuple[dict[str, Any] | None, tuple[str, str] | None]:
    trace = broker.last_decision_trace
    if trace is None:
        return None, None
    candidate = trace.get("code_candidate")
    if not isinstance(candidate, dict):
        return None, None
    side = str(candidate.get("signal") or "")
    reason = trace.get("blocked_entry_reason")
    reason_text = str(reason) if reason is not None else None
    if side not in {"LONG", "SHORT"} or not _blocked_supervisor_reason(reason_text):
        return None, None

    key = (side, reason_text or "")
    if key == active_key:
        return None, key

    market = trace["market"]
    return (
        {
            "variant": variant,
            "entry_index": row_index,
            "side": side,
            "blocked_reason": reason_text,
            "market_timestamp": market["market_timestamp"],
        },
        key,
    )


def _simulate_candidate_trade(
    rows: list[dict[str, Any]],
    *,
    entry_index: int,
    side: str,
    base_config: PaperConfig,
) -> dict[str, Any]:
    config = replace(
        base_config,
        strategy_enabled=False,
        jev_direct_enabled=True,
        jev_direction_gate_enabled=False,
        deterministic_supervisor_enabled=False,
        cooldown_seconds=0.0,
    )
    broker = PaperBroker(config)
    entry_row = rows[entry_index]
    timestamp = entry_row["market"]["market_timestamp"]
    broker.on_decision(
        {
            "direction_signal": side,
            "basis_market_timestamp": timestamp,
            "requested_at": timestamp,
            "available_at": timestamp,
        }
    )
    opened = broker.on_tick(_tick_from_trace(entry_row))
    open_event = next(
        (event for event in opened if event.get("action") == "OPEN"), None
    )
    if open_event is None:
        raise ValueError(
            f"Counterfactual candidate could not open at row {entry_index}."
        )

    close_event: dict[str, Any] | None = None
    exit_index = entry_index
    for index in range(entry_index + 1, len(rows)):
        events = broker.on_tick(
            _tick_from_trace(rows[index]),
            allow_entry=False,
            entry_gate_reason="counterfactual_single_trade",
        )
        found = next(
            (event for event in events if event.get("action") == "CLOSE"), None
        )
        if found is not None:
            close_event = found
            exit_index = index
            break

    if close_event is None:
        close_event = broker.finalize(
            _tick_from_trace(rows[-1]),
            reason="end_of_sample",
        )
        exit_index = len(rows) - 1

    if close_event is None:
        raise ValueError("Counterfactual trade remained unresolved.")

    pnl = float(close_event.get("pnl") or 0.0)
    return {
        "entry_index": entry_index,
        "exit_index": exit_index,
        "side": side,
        "entry_timestamp": open_event["timestamp"],
        "exit_timestamp": close_event["timestamp"],
        "entry_price": open_event["price"],
        "exit_price": close_event["price"],
        "exit_reason": close_event["reason"],
        "net_pnl": round(pnl, 3),
        "fees": close_event.get("fees"),
        "slippage_cost": close_event.get("slippage_cost"),
    }


def _counterfactual_summary(
    rows: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    base_config: PaperConfig,
) -> dict[str, Any]:
    evaluated: list[dict[str, Any]] = []
    overlap_skipped = 0
    occupied_until = -1

    for candidate in candidates:
        entry_index = int(candidate["entry_index"])
        if entry_index <= occupied_until:
            overlap_skipped += 1
            continue
        result = _simulate_candidate_trade(
            rows,
            entry_index=entry_index,
            side=str(candidate["side"]),
            base_config=base_config,
        )
        result["blocked_reason"] = candidate["blocked_reason"]
        evaluated.append(result)
        occupied_until = int(result["exit_index"])

    avoided_loss = round(
        sum(-float(item["net_pnl"]) for item in evaluated if item["net_pnl"] < 0),
        3,
    )
    missed_profit = round(
        sum(float(item["net_pnl"]) for item in evaluated if item["net_pnl"] > 0),
        3,
    )
    reasons: dict[str, dict[str, Any]] = {}
    for item in evaluated:
        key = str(item["blocked_reason"])
        bucket = reasons.setdefault(
            key,
            {
                "count": 0,
                "counterfactual_net_pnl": 0.0,
                "avoided_loss": 0.0,
                "missed_profit": 0.0,
            },
        )
        pnl = float(item["net_pnl"])
        bucket["count"] += 1
        bucket["counterfactual_net_pnl"] = round(
            float(bucket["counterfactual_net_pnl"]) + pnl, 3
        )
        if pnl < 0:
            bucket["avoided_loss"] = round(
                float(bucket["avoided_loss"]) - pnl, 3
            )
        elif pnl > 0:
            bucket["missed_profit"] = round(
                float(bucket["missed_profit"]) + pnl, 3
            )

    return {
        "blocked_candidate_episodes": len(candidates),
        "evaluated_non_overlapping": len(evaluated),
        "overlap_skipped": overlap_skipped,
        "avoided_loss": avoided_loss,
        "avoided_loss_count": sum(1 for item in evaluated if item["net_pnl"] < 0),
        "missed_profit": missed_profit,
        "missed_profit_count": sum(1 for item in evaluated if item["net_pnl"] > 0),
        "neutral_count": sum(1 for item in evaluated if item["net_pnl"] == 0),
        "counterfactual_net_pnl": round(
            sum(float(item["net_pnl"]) for item in evaluated),
            3,
        ),
        "false_pause_count": sum(1 for item in evaluated if item["net_pnl"] > 0),
        "by_reason": reasons,
        "trades": evaluated,
    }


def _pause_seconds(rows: list[dict[str, Any]], variant: str) -> float:
    total = 0.0
    for index in range(len(rows) - 1):
        row = rows[index]
        if variant == "B":
            paused = (
                not _allow(_gate(row, "deterministic"))
                or not _allow(_gate(row, "event"))
            )
        elif variant == "C":
            paused = not _allow(_gate(row, "combined_supervisor"))
        else:
            paused = False
        if not paused:
            continue
        seconds = max(
            0.0,
            (_market_at(rows[index + 1]) - _market_at(row)).total_seconds(),
        )
        total += seconds
    return round(total, 3)


def _strategy_switches(rows: list[dict[str, Any]], base_strategy: str) -> int:
    previous: str | None = None
    switches = 0
    for row in rows:
        gate = _gate(row, "combined_supervisor")
        if not _allow(gate):
            continue
        current = str(gate.get("strategy") or base_strategy)
        if previous is not None and current != previous:
            switches += 1
        previous = current
    return switches


def _result_row(
    broker: PaperBroker,
    *,
    ticks: int,
    turnover_size: float,
    pause_duration_seconds: float,
    strategy_switches: int,
) -> dict[str, Any]:
    snapshot = broker.snapshot()
    return {
        "ticks": ticks,
        "strategy": snapshot["strategy"],
        "equity": snapshot["equity"],
        "net_pnl": round(
            float(snapshot["equity"]) - float(snapshot["initial_balance"]), 3
        ),
        "realized_pnl": snapshot["realized_pnl"],
        "profit_factor": snapshot["profit_factor"],
        "max_drawdown": snapshot["max_drawdown"],
        "max_drawdown_pct": snapshot["max_drawdown_pct"],
        "closed_trades": snapshot["closed_trades"],
        "win_rate": snapshot["win_rate"],
        "fees_paid": snapshot["fees_paid"],
        "slippage_cost": snapshot["slippage_cost"],
        "average_trade_pnl": snapshot["average_trade_pnl"],
        "average_win_pnl": snapshot["average_win_pnl"],
        "average_loss_pnl": snapshot["average_loss_pnl"],
        "exit_reasons": snapshot["exit_reasons"],
        "turnover_size": round(turnover_size, 8),
        "pause_duration_seconds": pause_duration_seconds,
        "strategy_switches": strategy_switches,
        "cost_model": snapshot["cost_model"],
    }


def run_abcd_experiment(
    rows: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    trace_rows = list(rows)
    if not trace_rows:
        raise ValueError("At least one decision trace row is required.")
    _validate_source_run(trace_rows)

    base = _paper_config(trace_rows)
    configs = _variant_configs(base)
    brokers = {name: PaperBroker(config) for name, config in configs.items()}
    turnovers = {name: 0.0 for name in brokers}
    blocked: dict[str, list[dict[str, Any]]] = {"B": [], "C": []}
    active_block: dict[str, tuple[str, str] | None] = {"B": None, "C": None}

    last_index = len(trace_rows) - 1
    for index, row in enumerate(trace_rows):
        tick = _tick_from_trace(row)
        is_last = index == last_index

        _feed_jev_direction(brokers["C"], row)
        _feed_jev_direction(brokers["D"], row)

        event_gate = _gate(row, "event")
        combined_gate = _gate(row, "combined_supervisor")

        plans = {
            "A": {
                "allow_entry": not is_last,
                "strategy_override": None,
                "reason": "end_of_sample" if is_last else None,
            },
            "B": {
                "allow_entry": _allow(event_gate) and not is_last,
                "strategy_override": None,
                "reason": (
                    "end_of_sample"
                    if is_last
                    else (
                        None
                        if _allow(event_gate)
                        else f"code:{event_gate.get('reason') or 'event_block'}"
                    )
                ),
            },
            "C": {
                "allow_entry": _allow(combined_gate) and not is_last,
                "strategy_override": (
                    combined_gate.get("strategy")
                    if combined_gate.get("strategy")
                    in {"momentum", "rsi_mean_reversion", "ma_trend"}
                    else None
                ),
                "reason": (
                    "end_of_sample"
                    if is_last
                    else (
                        None
                        if _allow(combined_gate)
                        else str(
                            combined_gate.get("reason")
                            or "combined_supervisor"
                        )
                    )
                ),
            },
            "D": {
                "allow_entry": not is_last,
                "strategy_override": None,
                "reason": "end_of_sample" if is_last else None,
            },
        }

        for variant, broker in brokers.items():
            plan = plans[variant]
            events = broker.on_tick(
                tick,
                allow_entry=bool(plan["allow_entry"]),
                strategy_override=plan["strategy_override"],
                entry_gate_reason=plan["reason"],
            )
            turnovers[variant] += sum(
                float(event.get("size") or 0.0) for event in events
            )

            if variant in {"B", "C"} and not is_last:
                candidate, new_key = _collect_blocked_episode(
                    variant=variant,
                    row_index=index,
                    broker=broker,
                    active_key=active_block[variant],
                )
                if candidate is not None:
                    blocked[variant].append(candidate)
                active_block[variant] = new_key

        for variant in {"B", "C"}:
            trace = brokers[variant].last_decision_trace
            if trace is None:
                active_block[variant] = None
                continue
            candidate = trace.get("code_candidate")
            reason = trace.get("blocked_entry_reason")
            if (
                not isinstance(candidate, dict)
                or candidate.get("signal") not in {"LONG", "SHORT"}
                or not _blocked_supervisor_reason(
                    None if reason is None else str(reason)
                )
            ):
                active_block[variant] = None

    final_tick = _tick_from_trace(trace_rows[-1])
    for variant, broker in brokers.items():
        event = broker.finalize(final_tick, reason="end_of_sample")
        if event is not None:
            turnovers[variant] += float(event.get("size") or 0.0)

    base_strategy = str(base.strategy)
    variants = {
        variant: {
            "label": VARIANT_DESCRIPTIONS[variant],
            **_result_row(
                broker,
                ticks=len(trace_rows),
                turnover_size=turnovers[variant],
                pause_duration_seconds=_pause_seconds(trace_rows, variant),
                strategy_switches=(
                    _strategy_switches(trace_rows, base_strategy)
                    if variant == "C"
                    else 0
                ),
            ),
        }
        for variant, broker in brokers.items()
    }

    for variant in {"B", "C"}:
        variants[variant]["counterfactual"] = _counterfactual_summary(
            trace_rows,
            blocked[variant],
            base,
        )

    source = trace_rows[0]
    return {
        "experiment_schema_version": 1,
        "source": {
            "run_id": source["run_id"],
            "instrument_id": source["instrument_id"],
            "trace_schema_version": source["schema_version"],
            "cost_model_version": source["cost_model"]["version"],
            "ticks": len(trace_rows),
            "started_at": trace_rows[0]["market"]["market_timestamp"],
            "ended_at": trace_rows[-1]["market"]["market_timestamp"],
            "source_variant": "C",
        },
        "variant_definitions": dict(VARIANT_DESCRIPTIONS),
        "variants": variants,
        "limitations": [
            "D reuses recorded Jev direction but does not replay Jev position_action, "
            "because position_action is only causally available for the source run's "
            "actual position.",
            "Blocked-entry counterfactuals are isolated one-position simulations. "
            "Overlapping blocked episodes are skipped.",
            "Results are paper-research outputs, not profit guarantees or live execution.",
        ],
    }


def run_abcd_experiment_file(
    path: Path,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    return run_abcd_experiment(read_decision_traces(path, run_id=run_id))
