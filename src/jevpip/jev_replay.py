from __future__ import annotations

import json
import time
from threading import Event
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import fmean, median
from typing import Any, Iterable
from uuid import uuid4

from jevpip.broker.paper import PaperBroker, PaperConfig
from jevpip.broker.autopilot import AutopilotBroker, make_paper_broker
from jevpip.jev.autopilot import attach_target
from jevpip.market.buffer import TickBuffer
from jevpip.market.features import build_features
from jevpip.market.models import MarketTick
from jevpip.signals import (
    SignalPolicy,
    classify_direction_signal,
    classify_position_action,
)
from jevpip.storage.jsonl import append_jsonl

MAX_JEV_REPLAY_CALLS = 10_000
JEV_INPUT_USD_PER_MILLION_TOKENS = 0.042
ALLOWED_CADENCE_SECONDS = (1, 2, 5, 10, 30, 60)


@dataclass(frozen=True, slots=True)
class JevReplayPlan:
    instrument_id: str
    date: str
    source_path: Path
    available_start: str
    available_end: str
    selected_start: str
    selected_end: str
    duration_seconds: int
    cadence_seconds: int
    selected_ticks: int
    planned_max_calls: int
    max_tick_gap_seconds: float
    median_tick_interval_seconds: float


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _tick_from_row(row: dict[str, Any]) -> MarketTick:
    market_timestamp = _parse_timestamp(str(row["market_timestamp"]))
    received_at = _parse_timestamp(
        str(row.get("received_at") or row["market_timestamp"])
    )
    return MarketTick(
        instrument_id=str(row["instrument_id"]),
        symbol=str(row.get("symbol") or row["instrument_id"]),
        display_symbol=str(
            row.get("display_symbol")
            or str(row["instrument_id"]).replace("_", "/")
        ),
        bid=Decimal(str(row["bid"])),
        ask=Decimal(str(row["ask"])),
        market_timestamp=market_timestamp,
        received_at=received_at,
        price_unit=Decimal(str(row.get("price_unit") or "0.01")),
        move_unit_label=str(row.get("move_unit_label") or "pips"),
        status=str(row.get("status") or "UNKNOWN"),
        raw=None,
    )


def read_raw_market_ticks(path: Path) -> list[MarketTick]:
    ticks: list[MarketTick] = []
    with path.open("r", encoding="utf-8") as fh:
        for number, line in enumerate(fh, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{number}: {exc}") from exc
            if not isinstance(raw, dict):
                raise ValueError(f"Expected object at {path}:{number}")
            try:
                ticks.append(_tick_from_row(raw))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Invalid raw tick at {path}:{number}: {exc}") from exc
    ticks.sort(key=lambda tick: tick.market_timestamp)
    return ticks


def _resolve_start(
    ticks: list[MarketTick],
    start_time: str | None,
) -> datetime:
    if not ticks:
        raise ValueError("raw tick file is empty")
    first = ticks[0].market_timestamp
    if not start_time:
        return first

    try:
        parsed_time = datetime.strptime(start_time, "%H:%M:%S").time()
    except ValueError as exc:
        raise ValueError("start_time must be HH:MM:SS") from exc

    candidate = datetime.combine(first.date(), parsed_time, tzinfo=timezone.utc)
    if candidate < first:
        return first
    return candidate


def _scheduled_basis_ticks(
    ticks: Iterable[MarketTick],
    *,
    start_at: datetime,
    end_at: datetime,
    cadence_seconds: int,
) -> list[MarketTick]:
    selected: list[MarketTick] = []
    next_at = start_at
    cadence = timedelta(seconds=cadence_seconds)
    for tick in ticks:
        if tick.market_timestamp < start_at:
            continue
        if tick.market_timestamp > end_at:
            break
        if tick.market_timestamp < next_at:
            continue
        selected.append(tick)
        next_at = tick.market_timestamp + cadence
    return selected


def plan_jev_replay(
    data_dir: Path,
    *,
    instrument_id: str,
    date: str,
    start_time: str | None,
    duration_seconds: int,
    cadence_seconds: int,
) -> JevReplayPlan:
    if cadence_seconds not in ALLOWED_CADENCE_SECONDS:
        allowed = ", ".join(str(value) for value in ALLOWED_CADENCE_SECONDS)
        raise ValueError(f"cadence_seconds must be one of: {allowed}")
    if duration_seconds < 1 or duration_seconds > 86_400:
        raise ValueError("duration_seconds must be between 1 and 86400")

    path = data_dir / "raw_ticks" / instrument_id / f"{date}.jsonl"
    if not path.exists():
        raise ValueError(f"raw tick data not found: {path}")

    ticks = read_raw_market_ticks(path)
    if not ticks:
        raise ValueError("raw tick file is empty")
    if any(tick.instrument_id != instrument_id for tick in ticks):
        raise ValueError("raw tick file contains a different instrument")

    start_at = _resolve_start(ticks, start_time)
    available_end = ticks[-1].market_timestamp
    if start_at > available_end:
        raise ValueError("start_time is after the available raw tick range")

    requested_end = start_at + timedelta(seconds=duration_seconds)
    end_at = min(requested_end, available_end)
    selected_ticks = [
        tick
        for tick in ticks
        if start_at <= tick.market_timestamp <= end_at
    ]
    if not selected_ticks:
        raise ValueError("selected window contains no raw ticks")

    basis = _scheduled_basis_ticks(
        selected_ticks,
        start_at=start_at,
        end_at=end_at,
        cadence_seconds=cadence_seconds,
    )
    gaps = [(right.market_timestamp-left.market_timestamp).total_seconds()
            for left, right in zip(selected_ticks, selected_ticks[1:])]
    return JevReplayPlan(
        instrument_id=instrument_id,
        date=date,
        source_path=path,
        available_start=ticks[0].market_timestamp.isoformat(),
        available_end=available_end.isoformat(),
        selected_start=start_at.isoformat(),
        selected_end=end_at.isoformat(),
        duration_seconds=max(0, int((end_at - start_at).total_seconds())),
        cadence_seconds=cadence_seconds,
        selected_ticks=len(selected_ticks),
        planned_max_calls=len(basis),
        max_tick_gap_seconds=max(gaps, default=0.0),
        median_tick_interval_seconds=median(gaps) if gaps else 0.0,
    )


def _usage_tokens(value: object) -> tuple[int | None, int | None]:
    if not isinstance(value, dict):
        return None, None
    raw_input = value.get("input_tokens")
    raw_output = value.get("output_tokens")

    def valid(raw: object) -> int | None:
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            return None
        return raw

    return valid(raw_input), valid(raw_output)


def _input_cost_usd(input_tokens: int | None) -> float | None:
    if input_tokens is None:
        return None
    return round(
        input_tokens * JEV_INPUT_USD_PER_MILLION_TOKENS / 1_000_000,
        10,
    )


def recent_token_average(
    data_dir: Path,
    *,
    max_reported_calls: int = 100,
) -> dict[str, Any]:
    samples: list[tuple[int, int]] = []
    decisions_dir = data_dir / "decisions"
    replay_dir = data_dir / "jev_replays"
    candidates: list[Path] = []
    for root in (decisions_dir, replay_dir):
        if root.exists():
            candidates.extend(root.rglob("*.jsonl"))

    for path in sorted(
        candidates,
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    ):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            jev = row.get("jev")
            if not isinstance(jev, dict):
                continue
            input_tokens, output_tokens = _usage_tokens(jev.get("usage"))
            if input_tokens is None or output_tokens is None:
                continue
            samples.append((input_tokens, output_tokens))
            if len(samples) >= max_reported_calls:
                break
        if len(samples) >= max_reported_calls:
            break

    if not samples:
        return {
            "reported_calls": 0,
            "average_input_tokens": None,
            "average_output_tokens": None,
            "average_total_tokens": None,
        }

    inputs = [item[0] for item in samples]
    outputs = [item[1] for item in samples]
    return {
        "reported_calls": len(samples),
        "average_input_tokens": round(fmean(inputs), 1),
        "average_output_tokens": round(fmean(outputs), 1),
        "average_total_tokens": round(
            fmean(left + right for left, right in samples),
            1,
        ),
    }


def preview_jev_replay(
    data_dir: Path,
    *,
    instrument_id: str,
    date: str,
    start_time: str | None,
    duration_seconds: int,
    cadence_seconds: int,
) -> dict[str, Any]:
    plan = plan_jev_replay(
        data_dir,
        instrument_id=instrument_id,
        date=date,
        start_time=start_time,
        duration_seconds=duration_seconds,
        cadence_seconds=cadence_seconds,
    )
    average = recent_token_average(data_dir)
    avg_input = average["average_input_tokens"]
    avg_output = average["average_output_tokens"]
    estimated_input = (
        None
        if avg_input is None
        else int(round(float(avg_input) * plan.planned_max_calls))
    )
    estimated_output = (
        None
        if avg_output is None
        else int(round(float(avg_output) * plan.planned_max_calls))
    )
    estimated_total = (
        None
        if estimated_input is None or estimated_output is None
        else estimated_input + estimated_output
    )
    return {
        **asdict(plan),
        "source_path": str(plan.source_path),
        "max_calls_limit": MAX_JEV_REPLAY_CALLS,
        "within_call_limit": plan.planned_max_calls <= MAX_JEV_REPLAY_CALLS,
        "token_estimate": {
            **average,
            "estimated_input_tokens": estimated_input,
            "estimated_output_tokens": estimated_output,
            "estimated_total_tokens": estimated_total,
            "estimated_billable_input_tokens": estimated_input,
            "estimated_cost_usd": _input_cost_usd(estimated_input),
            "input_price_usd_per_million_tokens": JEV_INPUT_USD_PER_MILLION_TOKENS,
            "output_price_usd_per_million_tokens": 0.0,
            "basis": (
                "recent_reported_usage"
                if average["reported_calls"]
                else "unavailable"
            ),
        },
        "warning": (
            "Jev APIを実際に呼び出します。現在の公開価格ではinput tokenが課金対象で、"
            "output tokenは無料です。見積りは最大call数と直近usage平均からの概算で、"
            "実際の請求額を保証しません。"
        ),
    }


def _paper_context(
    broker: PaperBroker,
    config: PaperConfig,
    *,
    as_of: datetime,
) -> dict[str, Any]:
    snapshot = broker.snapshot()
    position = snapshot.get("position")
    position_state: dict[str, Any] | None = None
    if isinstance(position, dict):
        opened_at = _parse_timestamp(str(position["opened_at"]))
        position_state = {
            "side": position.get("side"),
            "opened_at": position.get("opened_at"),
            "age_seconds": round(
                max(0.0, (as_of - opened_at).total_seconds()),
                3,
            ),
            "position_horizon_seconds": config.max_hold_seconds,
            "minimum_hold_seconds": config.jev_position_min_hold_seconds,
        }
    return {
        "paper_context": {
            "strategy_enabled": False,
            "configured_strategy": None,
            "jev_direct_enabled": True,
            "jev_direction_gate_enabled": False,
            "latest_strategy_decision": None,
            "position": position_state,
        }
    }


def _decision_event(
    *,
    tick: MarketTick,
    requested_at: datetime,
    available_at: datetime,
    answer: dict[str, Any],
    signal_policy: SignalPolicy,
    latency_ms: float,
    autopilot: bool = False,
) -> dict[str, Any]:
    direction_signal, direction_detail = ("WAIT", {}) if autopilot else classify_direction_signal(
        answer,
        signal_policy,
    )
    position_action, position_action_detail = (None, {}) if autopilot else classify_position_action(answer)
    return {
        "kind": "jev_historical_decision",
        "instrument_id": tick.instrument_id,
        "basis_market_timestamp": tick.market_timestamp.isoformat(),
        "requested_at": requested_at.isoformat(),
        "available_at": available_at.isoformat(),
        "bid": str(tick.bid),
        "ask": str(tick.ask),
        "spread_units": float(tick.spread_units),
        "jev": answer,
        "jev_latency_ms": round(latency_ms, 2),
        "direction_signal": direction_signal,
        "direction_detail": direction_detail,
        "research_signal": direction_signal,
        "position_action": position_action,
        "position_action_detail": position_action_detail,
    }


def _summary(
    broker: PaperBroker,
    *,
    planned_max_calls: int,
    calls: int,
    skipped_by_latency: int,
    usages: list[tuple[int, int]],
    latencies: list[float],
) -> dict[str, Any]:
    snapshot = broker.snapshot()
    return {
        "gross_realized_pnl": snapshot["gross_realized_pnl"],
        **{key: snapshot[key] for key in (
            "pnl_breakdown", "turnover_notional", "max_exposure", "average_exposure",
            "target_changes", "target_changes_per_minute", "max_tick_gap_seconds", "target_status",
        ) if key in snapshot},
        "planned_max_calls": planned_max_calls,
        "calls": calls,
        "skipped_by_latency": skipped_by_latency,
        "reported_usage_calls": len(usages),
        "input_tokens": sum(item[0] for item in usages),
        "output_tokens": sum(item[1] for item in usages),
        "total_tokens": sum(left + right for left, right in usages),
        "billable_input_tokens": sum(item[0] for item in usages),
        "estimated_cost_usd": _input_cost_usd(sum(item[0] for item in usages)),
        "input_price_usd_per_million_tokens": JEV_INPUT_USD_PER_MILLION_TOKENS,
        "output_price_usd_per_million_tokens": 0.0,
        "average_latency_ms": (
            None if not latencies else round(fmean(latencies), 2)
        ),
        "net_pnl": round(
            float(snapshot["equity"]) - float(snapshot["initial_balance"]),
            3,
        ),
        "equity": snapshot["equity"],
        "profit_factor": snapshot["profit_factor"],
        "max_drawdown": snapshot["max_drawdown"],
        "max_drawdown_pct": snapshot["max_drawdown_pct"],
        "closed_trades": snapshot["closed_trades"],
        "win_rate": snapshot["win_rate"],
        "fees_paid": snapshot["fees_paid"],
        "slippage_cost": snapshot["slippage_cost"],
        "average_trade_pnl": snapshot["average_trade_pnl"],
        "exit_reasons": snapshot["exit_reasons"],
        "trades": snapshot["trades"],
    }


def run_jev_historical_replay(
    data_dir: Path,
    *,
    instrument_id: str,
    date: str,
    start_time: str | None,
    duration_seconds: int,
    cadence_seconds: int,
    profile: dict[str, Any],
    signal_policy: SignalPolicy,
    paper_config: PaperConfig,
    jev_client: Any,
    acknowledged_token_use: bool,
    cancel_event: Event | None = None,
) -> dict[str, Any]:
    if not acknowledged_token_use:
        raise ValueError("Token-use acknowledgement is required.")
    if paper_config.autopilot_enabled and paper_config.autopilot_fundamentals:
        raise ValueError("historical fundamentals unavailable: disable fundamentals for replay")

    plan = plan_jev_replay(
        data_dir,
        instrument_id=instrument_id,
        date=date,
        start_time=start_time,
        duration_seconds=duration_seconds,
        cadence_seconds=cadence_seconds,
    )
    if plan.planned_max_calls > MAX_JEV_REPLAY_CALLS:
        raise ValueError(
            f"Planned Jev calls ({plan.planned_max_calls}) exceed the "
            f"per-run limit ({MAX_JEV_REPLAY_CALLS}). "
            "Shorten the duration or increase cadence_seconds."
        )

    all_ticks = read_raw_market_ticks(plan.source_path)
    if paper_config.autopilot_enabled and (
        any(t.received_at < t.market_timestamp for t in all_ticks)
        or any(b.received_at < a.received_at for a, b in zip(all_ticks, all_ticks[1:]))
    ):
        raise ValueError("autopilot replay requires causal, ordered raw tick timestamps")
    start_at = _parse_timestamp(plan.selected_start)
    end_at = _parse_timestamp(plan.selected_end)
    config = replace(
        paper_config,
        instrument_id=instrument_id,
        strategy_enabled=False,
        jev_direct_enabled=True,
        jev_direction_gate_enabled=False,
    )
    broker = make_paper_broker(config)
    buffer = TickBuffer(max_age_seconds=86_400)

    run_id = (
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-"
        f"{instrument_id}-{cadence_seconds}s-{uuid4().hex[:8]}"
    )
    output = data_dir / "jev_replays" / instrument_id / f"{run_id}.jsonl"
    append_jsonl(output, {"kind": "jev_replay_config", "schema_version": 1,
                          "config": asdict(config), "profile": profile,
                          "signal_policy": asdict(signal_policy), "cadence_seconds": cadence_seconds,
                          "source_path": str(plan.source_path), "plan": {**asdict(plan), "source_path": str(plan.source_path)}})
    pending_decision: tuple[datetime, dict[str, Any]] | None = None
    next_request_at = start_at
    cadence = timedelta(seconds=cadence_seconds)
    calls = 0
    skipped_by_latency = 0
    usages: list[tuple[int, int]] = []
    latencies: list[float] = []
    selected_ticks = 0
    final_market_at = max(t.market_timestamp for t in all_ticks if start_at <= t.market_timestamp <= end_at)

    for tick in all_ticks:
        if cancel_event is not None and cancel_event.is_set():
            append_jsonl(output, {"kind": "jev_replay_cancelled", "calls": calls})
            return {"cancelled": True, "output": str(output), "calls": calls}
        if tick.market_timestamp > end_at:
            break

        buffer.append(tick)
        if tick.market_timestamp < start_at:
            if isinstance(broker, AutopilotBroker):
                broker.warm_history(tick.as_json_dict())
            continue

        selected_ticks += 1
        clock = tick.received_at if config.autopilot_enabled else tick.market_timestamp
        if (
            pending_decision is not None
            and pending_decision[0] <= clock
        ):
            broker.on_decision(pending_decision[1])
            pending_decision = None

        generated = broker.on_tick(tick.as_json_dict(), allow_entry=(not config.autopilot_enabled or tick.market_timestamp < final_market_at))
        for execution in generated:
            append_jsonl(output, execution)
        if config.autopilot_enabled and broker.last_decision_trace is not None:
            append_jsonl(output, {"kind": "target_decision_trace", **broker.last_decision_trace})

        if config.autopilot_enabled and tick.market_timestamp == final_market_at:
            continue

        if clock < next_request_at:
            continue
        if pending_decision is not None:
            skipped_by_latency += 1
            continue
        if calls >= min(plan.planned_max_calls, MAX_JEV_REPLAY_CALLS):
            continue  # the acknowledged preview is also a runtime spending cap

        state = build_features(tick, buffer, profile)
        state.update(broker.decision_state(tick.market_timestamp) if isinstance(broker, AutopilotBroker)
                     else _paper_context(broker, config, as_of=tick.market_timestamp))

        requested_at = clock
        started = time.perf_counter()
        call_error = None
        try:
            answer = jev_client.decide(
                state,
                f"{config.autopilot_horizon_seconds}s" if config.autopilot_enabled else "5s",
                instrument_label=tick.display_symbol,
            )
        except Exception as exc:
            if not config.autopilot_enabled:
                raise
            answer = {}
            call_error = type(exc).__name__
        latency_ms = (time.perf_counter() - started) * 1000
        if not isinstance(answer, dict):
            answer = {"malformed_response_type": type(answer).__name__}
        latency = timedelta(milliseconds=latency_ms)
        available_at = requested_at + latency
        event = _decision_event(
            tick=tick,
            requested_at=requested_at,
            available_at=available_at,
            answer=answer,
            signal_policy=signal_policy,
            latency_ms=latency_ms,
            autopilot=config.autopilot_enabled,
        )
        event["state"] = state
        if call_error:
            event["call_error"] = call_error
        attach_target(event, state)
        append_jsonl(output, event)
        calls += 1
        latencies.append(latency_ms)
        input_tokens, output_tokens = _usage_tokens(
            answer.get("usage") if isinstance(answer, dict) else None
        )
        if input_tokens is not None and output_tokens is not None:
            usages.append((input_tokens, output_tokens))

        pending_decision = (available_at, event)
        next_request_at = (requested_at if config.autopilot_enabled else available_at) + cadence

    last_tick = next(
        (
            tick
            for tick in reversed(all_ticks)
            if start_at <= tick.market_timestamp <= end_at
        ),
        None,
    )
    if last_tick is None:
        raise ValueError("selected window contains no raw ticks")

    if (
        pending_decision is not None
        and pending_decision[0] <= last_tick.market_timestamp
    ):
        broker.on_decision(pending_decision[1])

    final_trade = broker.finalize(
        last_tick.as_json_dict(),
        reason="end_of_replay",
    )
    if final_trade is not None:
        append_jsonl(
            output,
            {
                "kind": "paper_trade",
                **final_trade,
            },
        )

    summary = _summary(
        broker,
        planned_max_calls=plan.planned_max_calls,
        calls=calls,
        skipped_by_latency=skipped_by_latency,
        usages=usages,
        latencies=latencies,
    )
    result = {
        "kind": "jev_historical_replay_summary",
        "run_id": run_id,
        "instrument_id": instrument_id,
        "date": date,
        "selected_start": plan.selected_start,
        "selected_end": plan.selected_end,
        "duration_seconds": plan.duration_seconds,
        "cadence_seconds": cadence_seconds,
        "selected_ticks": selected_ticks,
        "output": str(output),
        "summary": summary,
        "limitations": [
            "This is a historical replay using the current Jev model, not a recreation "
            "of the model as it existed at the historical time.",
            "Only information built from raw ticks up to each basis timestamp is sent. "
            "Official-event context is not injected in this first replay version.",
            "Actual API latency is mapped onto historical market time; while one Jev "
            "decision is pending, another call is not started.",
        ],
    }
    append_jsonl(output, result)
    return result
