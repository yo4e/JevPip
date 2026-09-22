from __future__ import annotations

from datetime import datetime
from decimal import Decimal
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
        denom = ONE_MINUS_FEE = Decimal("1") - fee_rate
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
        },
        "target": {
            "net_take_profit_jpy": float(target_jpy),
            "net_stop_loss_jpy": float(-target_jpy),
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
            entry_fee=_d(entry["entry_fee_jpy"]),
            bid=bid,
            ask=ask,
            fee_rate=_d(cost["fee_rate"]),
            slippage_price=_d(cost["slippage_price"]),
        )
        target = _d(race["target"]["net_take_profit_jpy"])
        status = None
        if net >= target:
            status = "take_profit_first"
        elif net <= -target:
            status = "stop_loss_first"
        if status is not None:
            current.update(
                status=status,
                resolved_at=at.isoformat(),
                duration_seconds=max(0.0, (at - entry_at).total_seconds()),
                net_pnl_jpy_at_resolution=float(net),
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
