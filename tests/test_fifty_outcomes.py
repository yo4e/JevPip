from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest

from jevpip.fifty_outcomes import (
    build_directional_races,
    build_fifty_outcome_context,
    finalize_outcome_record,
    hypothetical_net_pnl,
    load_fifty_outcomes,
    new_outcome_record,
    summarize_outcomes,
    update_outcome_record,
)

START = datetime(2026, 9, 20, tzinfo=timezone.utc)


def races(*, fee_rate=0, slippage_price=0):
    return build_directional_races(
        bid=Decimal("99"),
        ask=Decimal("101"),
        quantity=Decimal("10"),
        price_unit=Decimal("1"),
        fee_rate=Decimal(str(fee_rate)),
        slippage_price=Decimal(str(slippage_price)),
        target_value=Decimal("5"),
        target_label="pips",
        target_kind="units",
    )


def decision(choice="UP"):
    return {
        "decision_id": "decision-1",
        "choice": choice,
        "target_side": "LONG" if choice == "UP" else "SHORT",
        "basis_market_timestamp": START.isoformat(),
        "requested_at": START.isoformat(),
        "available_at": (START + timedelta(milliseconds=100)).isoformat(),
    }


def test_reference_thresholds_match_net_pnl_equation_with_costs():
    built = races(fee_rate="0.001", slippage_price="0.5")
    for key in ("UP", "DOWN"):
        race = built[key]
        side = race["side"]
        quote_side = race["reference_exit_conditions"]["quote_side"]
        tp = Decimal(race["reference_exit_conditions"]["take_profit"]["quote_price"])
        sl = Decimal(race["reference_exit_conditions"]["stop_loss"]["quote_price"])
        base_bid = Decimal("100")
        base_ask = Decimal("100")
        tp_bid, tp_ask = (tp, base_ask) if quote_side == "bid" else (base_bid, tp)
        sl_bid, sl_ask = (sl, base_ask) if quote_side == "bid" else (base_bid, sl)
        entry = race["entry"]
        cost = race["cost_model"]
        target = Decimal(str(race["target"]["net_take_profit_jpy"]))

        tp_net = hypothetical_net_pnl(
            side=side,
            quantity=Decimal(race["quantity"]),
            entry_price=Decimal(entry["execution_price"]),
            entry_fee=Decimal(str(entry["entry_fee_jpy"])),
            bid=tp_bid,
            ask=tp_ask,
            fee_rate=Decimal(str(cost["fee_rate"])),
            slippage_price=Decimal(cost["slippage_price"]),
        )
        sl_net = hypothetical_net_pnl(
            side=side,
            quantity=Decimal(race["quantity"]),
            entry_price=Decimal(entry["execution_price"]),
            entry_fee=Decimal(str(entry["entry_fee_jpy"])),
            bid=sl_bid,
            ask=sl_ask,
            fee_rate=Decimal(str(cost["fee_rate"])),
            slippage_price=Decimal(cost["slippage_price"]),
        )
        assert float(tp_net) == pytest.approx(float(target), abs=1e-8)
        assert float(sl_net) == pytest.approx(float(-target), abs=1e-8)


def test_both_directions_can_independently_stop_out():
    record = new_outcome_record(
        decision=decision("UP"),
        races=races(),
        entry_at=START,
        source_kind="raw_ticks",
    )

    # Rising first stops the hypothetical SHORT, but is not enough for LONG TP.
    assert not update_outcome_record(
        record,
        at=START + timedelta(seconds=1),
        bid=Decimal("102"),
        ask=Decimal("104"),
        market_status="OPEN",
    )
    assert record["outcomes"]["SHORT"]["status"] == "stop_loss_first"
    assert record["outcomes"]["LONG"]["status"] == "pending"

    # Falling later stops the hypothetical LONG. The SHORT label is not inverted.
    assert update_outcome_record(
        record,
        at=START + timedelta(seconds=2),
        bid=Decimal("96"),
        ask=Decimal("98"),
        market_status="OPEN",
    )
    assert record["outcomes"]["LONG"]["status"] == "stop_loss_first"
    assert record["outcomes"]["SHORT"]["status"] == "stop_loss_first"

    summary = summarize_outcomes([record])
    assert summary["both_stop_loss_first"] == 1
    assert summary["chosen_tp_first_rate"] == 0


def test_unresolved_is_not_forced_into_tp_or_sl():
    record = new_outcome_record(
        decision=decision("DOWN"),
        races=races(),
        entry_at=START,
        source_kind="raw_ticks",
    )
    update_outcome_record(
        record,
        at=START + timedelta(seconds=3),
        bid=Decimal("99"),
        ask=Decimal("101"),
        market_status="OPEN",
    )
    finalize_outcome_record(
        record,
        at=START + timedelta(seconds=10),
        reason="end_of_sample",
    )
    assert record["outcomes"]["LONG"]["status"] == "unresolved"
    assert record["outcomes"]["SHORT"]["status"] == "unresolved"
    assert record["outcomes"]["LONG"]["unresolved_reason"] == "end_of_sample"

    summary = summarize_outcomes([record])
    assert summary["chosen_resolved"] == 0
    assert summary["directions"]["LONG"]["unresolved"] == 1
    assert summary["directions"]["SHORT"]["unresolved"] == 1



def completed_record(*, choice="UP", confidence=0.66, completed_after=10):
    record = new_outcome_record(
        decision=decision(choice),
        races=races(),
        entry_at=START,
        source_kind="live_raw_ticks",
        prediction={
            "confidence": confidence,
            "target_position": {
                "choice": choice,
                "confidence": confidence,
            },
        },
        context_version="trader_context_v1",
    )
    if choice == "UP":
        update_outcome_record(
            record,
            at=START + timedelta(seconds=completed_after),
            bid=Decimal("106"),
            ask=Decimal("108"),
            market_status="OPEN",
        )
        update_outcome_record(
            record,
            at=START + timedelta(seconds=completed_after + 1),
            bid=Decimal("106"),
            ask=Decimal("108"),
            market_status="OPEN",
        )
    else:
        update_outcome_record(
            record,
            at=START + timedelta(seconds=completed_after),
            bid=Decimal("92"),
            ask=Decimal("94"),
            market_status="OPEN",
        )
        update_outcome_record(
            record,
            at=START + timedelta(seconds=completed_after + 1),
            bid=Decimal("92"),
            ask=Decimal("94"),
            market_status="OPEN",
        )
    if not record["complete"]:
        finalize_outcome_record(
            record,
            at=START + timedelta(seconds=completed_after + 2),
            reason="test_end",
        )
    return record


def test_outcome_context_is_compact_and_excludes_future_results():
    known = completed_record(choice="UP", confidence=0.66, completed_after=10)
    future = completed_record(choice="DOWN", confidence=0.91, completed_after=100)
    context = build_fifty_outcome_context(
        [known, future],
        as_of=START + timedelta(seconds=50),
    )

    assert context["future_results_excluded"] is True
    assert context["sample_count"] == 1
    assert len(context["recent"]) == 1
    assert context["recent"][0]["choice"] == "UP"
    assert "races" not in context["recent"][0]
    assert context["aggregate"]["chosen_resolved"] == 1
    assert context["confidence_bands"]["0.6-0.7"]["resolved"] == 1
    assert "0.9-1.0" not in context["confidence_bands"]


def test_load_fifty_outcomes_survives_restart_without_future_leak(tmp_path):
    root = tmp_path / "fifty_outcomes" / "USD_JPY"
    root.mkdir(parents=True)
    known = completed_record(choice="UP", completed_after=10)
    future = completed_record(choice="DOWN", completed_after=100)
    started_only = {
        "kind": "fifty_directional_outcome_started",
        "decision_id": "started",
    }
    path = root / "2026-09-20.jsonl"
    path.write_text(
        "\n".join(json.dumps(row) for row in (started_only, known, future)) + "\n",
        encoding="utf-8",
    )

    loaded = load_fifty_outcomes(
        tmp_path,
        instrument_id="USD_JPY",
        as_of=START + timedelta(seconds=50),
    )
    assert [row["choice"] for row in loaded] == ["UP"]
