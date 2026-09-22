from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

ZERO = Decimal("0")


def _d(value: object) -> Decimal:
    return Decimal(str(value))


def hypothetical_net_pnl(
    *,
    side: str,
    quantity: Decimal,
    entry_price: Decimal,
    entry_fee: Decimal,
    bid: Decimal,
    ask: Decimal,
    fee_rate: Decimal,
    slippage_price: Decimal,
) -> Decimal:
    """Net PnL using the same entry/exit fee and slippage semantics as PaperBroker."""
    if side not in {"LONG", "SHORT"}:
        raise ValueError("side must be LONG or SHORT")
    exit_price = bid - slippage_price if side == "LONG" else ask + slippage_price
    gross = (
        (exit_price - entry_price) * quantity
        if side == "LONG"
        else (entry_price - exit_price) * quantity
    )
    exit_fee = abs(exit_price * quantity) * fee_rate if fee_rate > 0 else ZERO
    return gross - entry_fee - exit_fee


def _direction_contract(
    *,
    side: str,
    bid: Decimal,
    ask: Decimal,
    quantity: Decimal,
    fee_rate: Decimal,
    slippage_price: Decimal,
    target_jpy: Decimal,
    target_value: Decimal,
    target_label: str,
) -> dict[str, Any]:
    entry_price = ask + slippage_price if side == "LONG" else bid - slippage_price
    entry_fee = abs(entry_price * quantity) * fee_rate if fee_rate > 0 else ZERO

    # Solve the broker's exact net-PnL equation for the executable future
    # quote side, assuming configured fee/slippage stay fixed. Future spread
    # itself is not assumed fixed: LONG settles against BID, SHORT against ASK.
    if side == "LONG":
        denom = Decimal("1") - fee_rate
        if denom <= 0:
            raise ValueError("fee_rate must be below 1")
        tp_exit = (entry_price * (Decimal("1") + fee_rate) + target_jpy / quantity) / denom
        sl_exit = (entry_price * (Decimal("1") + fee_rate) - target_jpy / quantity) / denom
        tp_quote = tp_exit + slippage_price
        sl_quote = sl_exit + slippage_price
        quote_side = "bid"
        tp_operator = ">="
        sl_operator = "<="
    else:
        denom = Decimal("1") + fee_rate
        tp_exit = (entry_price * (Decimal("1") - fee_rate) - target_jpy / quantity) / denom
        sl_exit = (entry_price * (Decimal("1") - fee_rate) + target_jpy / quantity) / denom
        tp_quote = tp_exit - slippage_price
        sl_quote = sl_exit - slippage_price
        quote_side = "ask"
        tp_operator = "<="
        sl_operator = ">="

    return {
        "side": side,
        "quantity": str(quantity),
        "entry": {
            "bid": str(bid),
            "ask": str(ask),
            "execution_price": str(entry_price),
            "entry_fee_jpy": float(entry_fee),
            "entry_fee_exact": str(entry_fee),
        },
        "target": {
            "net_take_profit_jpy": float(target_jpy),
            "net_stop_loss_jpy": float(-target_jpy),
            "net_take_profit_jpy_exact": str(target_jpy),
            "display_value": float(target_value),
            "display_label": target_label,
        },
        "reference_exit_conditions": {
            "quote_side": quote_side,
            "take_profit": {
                "operator": tp_operator,
                "quote_price": str(tp_quote),
            },
            "stop_loss": {
                "operator": sl_operator,
                "quote_price": str(sl_quote),
            },
            "note": (
                "Reference thresholds use the supplied entry quote and configured "
                "fee/slippage. Future spread is not assumed fixed; LONG is evaluated "
                "against executable BID and SHORT against executable ASK."
            ),
        },
        "cost_model": {
            "fee_rate": float(fee_rate),
            "slippage_price": str(slippage_price),
        },
    }


def build_directional_races(
    *,
    bid: Decimal,
    ask: Decimal,
    quantity: Decimal,
    price_unit: Decimal,
    fee_rate: Decimal,
    slippage_price: Decimal,
    target_value: Decimal,
    target_label: str,
    target_kind: str,
) -> dict[str, Any]:
    if quantity <= 0 or price_unit <= 0 or target_value <= 0:
        raise ValueError("quantity, price_unit, and target_value must be positive")
    if ask < bid:
        raise ValueError("crossed quote")
    if target_kind == "jpy":
        target_jpy = target_value
    elif target_kind == "units":
        target_jpy = target_value * quantity * price_unit
    else:
        raise ValueError("unsupported target_kind")
    return {
        "UP": _direction_contract(
            side="LONG",
            bid=bid,
            ask=ask,
            quantity=quantity,
            fee_rate=fee_rate,
            slippage_price=slippage_price,
            target_jpy=target_jpy,
            target_value=target_value,
            target_label=target_label,
        ),
        "DOWN": _direction_contract(
            side="SHORT",
            bid=bid,
            ask=ask,
            quantity=quantity,
            fee_rate=fee_rate,
            slippage_price=slippage_price,
            target_jpy=target_jpy,
            target_value=target_value,
            target_label=target_label,
        ),
    }


def new_outcome_record(
    *,
    decision: dict[str, Any],
    races: dict[str, Any],
    entry_at: datetime,
    source_kind: str,
    prediction: dict[str, Any] | None = None,
    context_version: str | None = None,
) -> dict[str, Any]:
    return {
        "kind": "fifty_directional_outcome",
        "schema_version": 1,
        "decision_id": decision.get("decision_id"),
        "choice": decision.get("choice"),
        "chosen_side": decision.get("target_side"),
        "basis_market_timestamp": decision.get("basis_market_timestamp"),
        "requested_at": decision.get("requested_at"),
        "available_at": decision.get("available_at"),
        "entry_at": entry_at.isoformat(),
        "source_kind": source_kind,
        "label_semantics": "independent_counterfactual_net_tp_vs_sl",
        "context_version": context_version,
        "prediction": prediction or {},
        "races": races,
        "outcomes": {
            "LONG": {"status": "pending"},
            "SHORT": {"status": "pending"},
        },
        "complete": False,
    }


def _race_for_side(record: dict[str, Any], side: str) -> dict[str, Any]:
    return record["races"]["UP" if side == "LONG" else "DOWN"]


def update_outcome_record(
    record: dict[str, Any],
    *,
    at: datetime,
    bid: Decimal,
    ask: Decimal,
    market_status: str,
) -> bool:
    """Update one paired LONG/SHORT race. Returns True when both are resolved."""
    if market_status != "OPEN":
        return bool(record.get("complete"))

    entry_at = datetime.fromisoformat(str(record["entry_at"]))
    for side in ("LONG", "SHORT"):
        current = record["outcomes"][side]
        if current.get("status") != "pending":
            continue
        race = _race_for_side(record, side)
        entry = race["entry"]
        cost = race["cost_model"]
        net = hypothetical_net_pnl(
            side=side,
            quantity=_d(race["quantity"]),
            entry_price=_d(entry["execution_price"]),
            entry_fee=_d(entry.get("entry_fee_exact", entry["entry_fee_jpy"])),
            bid=bid,
            ask=ask,
            fee_rate=_d(cost["fee_rate"]),
            slippage_price=_d(cost["slippage_price"]),
        )
        target = _d(race["target"].get("net_take_profit_jpy_exact", race["target"]["net_take_profit_jpy"]))
        status = None
        boundary_net = None
        if net >= target:
            status = "take_profit_first"
            boundary_net = target
        elif net <= -target:
            status = "stop_loss_first"
            boundary_net = -target
        if status is not None and boundary_net is not None:
            current.update(
                status=status,
                resolved_at=at.isoformat(),
                duration_seconds=max(0.0, (at - entry_at).total_seconds()),
                # Match paper OCO accounting. The observed tick may already be
                # far beyond the order level, but the research fill is pinned
                # to the registered NET boundary.
                net_pnl_jpy_at_resolution=float(boundary_net),
                observed_tick_net_pnl_jpy=float(net),
                quote={"bid": str(bid), "ask": str(ask)},
            )

    record["complete"] = all(
        record["outcomes"][side]["status"] != "pending"
        for side in ("LONG", "SHORT")
    )
    return bool(record["complete"])


def finalize_outcome_record(
    record: dict[str, Any],
    *,
    at: datetime,
    reason: str,
) -> dict[str, Any]:
    entry_at = datetime.fromisoformat(str(record["entry_at"]))
    for side in ("LONG", "SHORT"):
        current = record["outcomes"][side]
        if current.get("status") == "pending":
            current.update(
                status="unresolved",
                unresolved_reason=reason,
                observed_until=at.isoformat(),
                observed_seconds=max(0.0, (at - entry_at).total_seconds()),
            )
    record["complete"] = True
    return record


def summarize_outcomes(
    records: list[dict[str, Any]],
    *,
    actual_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    direction = {}
    for side in ("LONG", "SHORT"):
        rows = [r["outcomes"][side] for r in records]
        resolved = [x for x in rows if x.get("status") in {"take_profit_first", "stop_loss_first"}]
        wins = [x for x in resolved if x["status"] == "take_profit_first"]
        durations = [float(x["duration_seconds"]) for x in resolved if x.get("duration_seconds") is not None]
        direction[side] = {
            "samples": len(rows),
            "resolved": len(resolved),
            "take_profit_first": len(wins),
            "stop_loss_first": len(resolved) - len(wins),
            "unresolved": len(rows) - len(resolved),
            "tp_first_rate": None if not resolved else len(wins) / len(resolved),
            "average_resolution_seconds": None if not durations else sum(durations) / len(durations),
        }

    chosen_resolved = 0
    chosen_tp = 0
    both_sl = 0
    both_tp = 0
    for record in records:
        outcomes = record["outcomes"]
        if outcomes["LONG"]["status"] == "stop_loss_first" and outcomes["SHORT"]["status"] == "stop_loss_first":
            both_sl += 1
        if outcomes["LONG"]["status"] == "take_profit_first" and outcomes["SHORT"]["status"] == "take_profit_first":
            both_tp += 1
        side = str(record.get("chosen_side") or "")
        if side in outcomes and outcomes[side]["status"] in {"take_profit_first", "stop_loss_first"}:
            chosen_resolved += 1
            if outcomes[side]["status"] == "take_profit_first":
                chosen_tp += 1

    result = {
        "samples": len(records),
        "chosen_resolved": chosen_resolved,
        "chosen_tp_first": chosen_tp,
        "chosen_tp_first_rate": None if not chosen_resolved else chosen_tp / chosen_resolved,
        "both_stop_loss_first": both_sl,
        "both_take_profit_first": both_tp,
        "directions": direction,
    }
    if actual_summary is not None:
        result["actual_trading"] = {
            key: actual_summary.get(key)
            for key in (
                "closed_trades",
                "win_rate",
                "average_trade_pnl",
                "average_win_pnl",
                "average_loss_pnl",
                "net_pnl",
                "profit_factor",
                "max_drawdown",
            )
        }
    return result



def _parsed_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def outcome_completed_at(record: dict[str, Any]) -> datetime | None:
    """Return when both directional labels became known, or None if incomplete."""
    if not record.get("complete"):
        return None
    times: list[datetime] = []
    outcomes = record.get("outcomes")
    if not isinstance(outcomes, dict):
        return None
    for side in ("LONG", "SHORT"):
        row = outcomes.get(side)
        if not isinstance(row, dict):
            return None
        raw = row.get("resolved_at") or row.get("observed_until")
        parsed = _parsed_time(raw)
        if parsed is None:
            return None
        times.append(parsed)
    return max(times) if times else None


def load_fifty_outcomes(
    data_dir: Path,
    *,
    instrument_id: str,
    as_of: datetime,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Load completed live outcome labels known by *as_of*, newest last.

    Only canonical completed rows are loaded. "started" rows are intentionally
    ignored, and future completions are excluded so a restart cannot leak a
    later answer into an earlier decision/replay.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    root = data_dir / "fifty_outcomes" / instrument_id
    if not root.exists():
        return []
    rows: list[tuple[datetime, dict[str, Any]]] = []
    for path in sorted(root.glob("*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            if record.get("kind") != "fifty_directional_outcome":
                continue
            completed_at = outcome_completed_at(record)
            if completed_at is None or completed_at > as_of.astimezone(timezone.utc):
                continue
            rows.append((completed_at, record))
    rows.sort(key=lambda item: item[0])
    if limit > 0:
        rows = rows[-limit:]
    return [record for _, record in rows]


def _compact_outcome(record: dict[str, Any]) -> dict[str, Any]:
    outcomes = record.get("outcomes") if isinstance(record.get("outcomes"), dict) else {}
    compact_outcomes: dict[str, Any] = {}
    for side in ("LONG", "SHORT"):
        row = outcomes.get(side) if isinstance(outcomes, dict) else None
        if not isinstance(row, dict):
            continue
        compact_outcomes[side] = {
            key: row.get(key)
            for key in (
                "status",
                "resolved_at",
                "duration_seconds",
                "unresolved_reason",
                "observed_seconds",
            )
            if row.get(key) is not None
        }
    prediction = record.get("prediction")
    confidence = None
    target_position = None
    if isinstance(prediction, dict):
        confidence = prediction.get("confidence")
        raw_target = prediction.get("target_position")
        if isinstance(raw_target, dict):
            target_position = {
                key: raw_target.get(key)
                for key in ("choice", "probability", "confidence", "reason")
                if raw_target.get(key) is not None
            }
    race = None
    races = record.get("races")
    if isinstance(races, dict):
        up = races.get("UP")
        if isinstance(up, dict):
            target = up.get("target")
            if isinstance(target, dict):
                race = {
                    "target_value": target.get("display_value"),
                    "target_label": target.get("display_label"),
                }
    return {
        "decision_id": record.get("decision_id"),
        "choice": record.get("choice"),
        "chosen_side": record.get("chosen_side"),
        "basis_market_timestamp": record.get("basis_market_timestamp"),
        "entry_at": record.get("entry_at"),
        "completed_at": (
            None
            if outcome_completed_at(record) is None
            else outcome_completed_at(record).isoformat()
        ),
        "confidence": confidence,
        "target_position_answer": target_position,
        "race": race,
        "outcomes": compact_outcomes,
    }


def _confidence_band(value: object) -> str | None:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if not 0 <= confidence <= 1:
        return None
    lower = min(0.9, int(confidence * 10) / 10)
    upper = 1.0 if lower >= 0.9 else lower + 0.1
    return f"{lower:.1f}-{upper:.1f}"


def build_fifty_outcome_context(
    records: list[dict[str, Any]],
    *,
    as_of: datetime,
    recent_limit: int = 20,
) -> dict[str, Any]:
    """Compact, causal answer-key context suitable for the next Jev request."""
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    cutoff = as_of.astimezone(timezone.utc)
    eligible = [
        record
        for record in records
        if (completed := outcome_completed_at(record)) is not None
        and completed <= cutoff
    ]
    eligible.sort(key=lambda record: outcome_completed_at(record) or datetime.min.replace(tzinfo=timezone.utc))
    aggregate = summarize_outcomes(eligible)

    bands: dict[str, dict[str, Any]] = {}
    for record in eligible:
        prediction = record.get("prediction")
        confidence = prediction.get("confidence") if isinstance(prediction, dict) else None
        band = _confidence_band(confidence)
        side = str(record.get("chosen_side") or "")
        outcomes = record.get("outcomes")
        if band is None or side not in {"LONG", "SHORT"} or not isinstance(outcomes, dict):
            continue
        row = outcomes.get(side)
        if not isinstance(row, dict) or row.get("status") not in {
            "take_profit_first",
            "stop_loss_first",
        }:
            continue
        bucket = bands.setdefault(
            band,
            {"resolved": 0, "take_profit_first": 0, "tp_first_rate": None},
        )
        bucket["resolved"] += 1
        if row["status"] == "take_profit_first":
            bucket["take_profit_first"] += 1
    for bucket in bands.values():
        bucket["tp_first_rate"] = (
            None
            if not bucket["resolved"]
            else bucket["take_profit_first"] / bucket["resolved"]
        )

    recent = eligible[-max(0, recent_limit):] if recent_limit else []
    return {
        "schema_version": 1,
        "semantics": "past_completed_independent_counterfactual_net_tp_vs_sl",
        "as_of": cutoff.isoformat(),
        "future_results_excluded": True,
        "sample_count": len(eligible),
        "aggregate": aggregate,
        "confidence_bands": bands,
        "recent": [_compact_outcome(record) for record in recent],
        "guidance": (
            "These are past completed answer keys only. Use them as empirical context, "
            "not as mandatory rules. Choice probabilities are relative preferences and "
            "must not be treated as calibrated win probabilities."
        ),
    }
