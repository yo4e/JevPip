from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from jevpip.broker.paper import PaperBroker, PaperConfig
from jevpip.broker.strategies import StrategyName
from jevpip.instruments import get_instrument

DEFAULT_COMPARISON_STRATEGIES: tuple[StrategyName, ...] = (
    "momentum",
    "rsi_mean_reversion",
    "ma_trend",
)


def default_paper_config(
    instrument_id: str,
    strategy: StrategyName,
    *,
    initial_balance: float = 100000.0,
    size: float | None = None,
    supervisor: bool = True,
    bar_seconds: int = 0,
) -> PaperConfig:
    instrument = get_instrument(instrument_id)
    return PaperConfig(
        initial_balance=initial_balance,
        size=float(instrument.default_paper_size) if size is None else size,
        strategy=strategy,
        price_unit=float(instrument.price_unit),
        move_unit_label=instrument.move_unit_label,
        momentum_window_seconds=5.0,
        momentum_trigger_units=float(instrument.default_momentum_trigger),
        max_spread_units=float(instrument.default_max_spread),
        take_profit_units=float(instrument.default_take_profit),
        stop_loss_units=float(instrument.default_stop_loss),
        max_hold_seconds=8.0,
        cooldown_seconds=2.0,
        fee_rate=float(instrument.paper_fee_rate),
        fee_label=instrument.paper_fee_label,
        slippage_units=float(instrument.default_slippage_units),
        short_is_synthetic=instrument.paper_short_is_synthetic,
        deterministic_supervisor_enabled=supervisor,
        strategy_bar_seconds=bar_seconds,
    )


def read_raw_ticks(path: Path) -> list[dict[str, Any]]:
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
            rows.append(row)
    return rows


def _baseline_no_trade(
    *,
    ticks: int,
    initial_balance: float,
) -> dict[str, Any]:
    return {
        "ticks": ticks,
        "strategy": "no_trade",
        "strategy_bar_seconds": 0,
        "equity": round(initial_balance, 3),
        "net_pnl": 0.0,
        "realized_pnl": 0.0,
        "unrealized_pnl": 0.0,
        "profit_factor": None,
        "max_drawdown": 0.0,
        "max_drawdown_pct": 0.0,
        "closed_trades": 0,
        "win_rate": None,
        "fees_paid": 0.0,
        "average_trade_pnl": None,
        "average_win_pnl": None,
        "average_loss_pnl": None,
        "exit_reasons": {},
        "supervisor": {"state": "NORMAL", "reason": "baseline", "allow_entry": False},
    }


def _baseline_buy_and_hold(
    ticks: list[dict[str, Any]],
    *,
    instrument_id: str,
    initial_balance: float,
    size: float | None,
    slippage_units: float | None = None,
) -> dict[str, Any]:
    instrument = get_instrument(instrument_id)
    quantity = (
        instrument.default_paper_size
        if size is None
        else Decimal(str(size))
    )
    if not ticks:
        return {
            **_baseline_no_trade(ticks=0, initial_balance=initial_balance),
            "strategy": "buy_and_hold",
        }

    price_unit = instrument.price_unit
    configured_slippage = (
        instrument.default_slippage_units
        if slippage_units is None
        else Decimal(str(slippage_units))
    )
    slippage_price = price_unit * configured_slippage
    fee_rate = instrument.paper_fee_rate

    first_ask = Decimal(str(ticks[0]["ask"]))
    entry_price = first_ask + slippage_price
    entry_fee = abs(entry_price * quantity) * fee_rate

    initial = Decimal(str(initial_balance))
    peak_equity = initial
    max_drawdown = Decimal("0")
    final_exit_price = entry_price
    final_exit_fee = Decimal("0")
    final_gross = Decimal("0")
    final_net = -entry_fee

    for tick in ticks:
        bid = Decimal(str(tick["bid"]))
        exit_price = bid - slippage_price
        exit_fee = abs(exit_price * quantity) * fee_rate
        gross = (exit_price - entry_price) * quantity
        net = gross - entry_fee - exit_fee
        equity = initial + net
        if equity > peak_equity:
            peak_equity = equity
        drawdown = peak_equity - equity
        if drawdown > max_drawdown:
            max_drawdown = drawdown
        final_exit_price = exit_price
        final_exit_fee = exit_fee
        final_gross = gross
        final_net = net

    max_drawdown_pct = (
        max_drawdown / peak_equity if peak_equity > 0 else Decimal("0")
    )
    net_float = round(float(final_net), 3)
    wins = 1 if final_net > 0 else 0
    losses = 1 if final_net < 0 else 0
    return {
        "ticks": len(ticks),
        "strategy": "buy_and_hold",
        "strategy_bar_seconds": 0,
        "equity": round(float(initial + final_net), 3),
        "net_pnl": net_float,
        "realized_pnl": net_float,
        "unrealized_pnl": 0.0,
        "gross_realized_pnl": round(float(final_gross), 3),
        "profit_factor": None,
        "max_drawdown": round(float(max_drawdown), 3),
        "max_drawdown_pct": round(float(max_drawdown_pct), 6),
        "closed_trades": 1,
        "win_rate": 1.0 if wins else 0.0 if losses else None,
        "fees_paid": round(float(entry_fee + final_exit_fee), 3),
        "average_trade_pnl": net_float,
        "average_win_pnl": net_float if wins else None,
        "average_loss_pnl": net_float if losses else None,
        "exit_reasons": {
            "end_of_sample": {
                "count": 1,
                "net_pnl": net_float,
                "gross_pnl": round(float(final_gross), 3),
                "average_net_pnl": net_float,
            }
        },
        "entry_price": str(entry_price),
        "exit_price": str(final_exit_price),
        "supervisor": {"state": "NORMAL", "reason": "baseline", "allow_entry": False},
    }


def build_baselines(
    ticks: list[dict[str, Any]],
    *,
    instrument_id: str,
    initial_balance: float = 100000.0,
    size: float | None = None,
    slippage_units: float | None = None,
) -> dict[str, dict[str, Any]]:
    return {
        "no_trade": _baseline_no_trade(
            ticks=len(ticks),
            initial_balance=initial_balance,
        ),
        "buy_and_hold": _baseline_buy_and_hold(
            ticks,
            instrument_id=instrument_id,
            initial_balance=initial_balance,
            size=size,
            slippage_units=slippage_units,
        ),
    }


def compare_ticks(
    ticks: Iterable[dict[str, Any]],
    *,
    instrument_id: str,
    strategies: Iterable[StrategyName] = DEFAULT_COMPARISON_STRATEGIES,
    initial_balance: float = 100000.0,
    size: float | None = None,
    supervisor: bool = True,
    bar_seconds: int = 0,
    include_baselines: bool = True,
) -> dict[str, dict[str, Any]]:
    tick_rows = list(ticks)
    selected = tuple(dict.fromkeys(strategies))
    if not selected:
        raise ValueError("At least one strategy is required.")
    if "jev" in selected:
        raise ValueError("Raw-tick comparison does not call Jev. Use code-only strategies.")

    brokers = {
        name: PaperBroker(
            default_paper_config(
                instrument_id,
                name,
                initial_balance=initial_balance,
                size=size,
                supervisor=supervisor,
                bar_seconds=bar_seconds,
            )
        )
        for name in selected
    }

    seen = 0
    for tick in tick_rows:
        tick_instrument = str(tick.get("instrument_id") or tick.get("symbol") or "")
        if tick_instrument and tick_instrument != instrument_id:
            raise ValueError(
                f"Tick instrument mismatch: expected {instrument_id}, got {tick_instrument}"
            )
        seen += 1
        for broker in brokers.values():
            broker.on_tick(tick)

    results: dict[str, dict[str, Any]] = {}
    for name, broker in brokers.items():
        snapshot = broker.snapshot()
        results[name] = {
            "ticks": seen,
            "strategy": name,
            "strategy_bar_seconds": snapshot["strategy_bar_seconds"],
            "equity": snapshot["equity"],
            "net_pnl": round(snapshot["equity"] - snapshot["initial_balance"], 3),
            "realized_pnl": snapshot["realized_pnl"],
            "unrealized_pnl": snapshot["unrealized_pnl"],
            "profit_factor": snapshot["profit_factor"],
            "max_drawdown": snapshot["max_drawdown"],
            "max_drawdown_pct": snapshot["max_drawdown_pct"],
            "closed_trades": snapshot["closed_trades"],
            "win_rate": snapshot["win_rate"],
            "fees_paid": snapshot["fees_paid"],
            "average_trade_pnl": snapshot["average_trade_pnl"],
            "average_win_pnl": snapshot["average_win_pnl"],
            "average_loss_pnl": snapshot["average_loss_pnl"],
            "exit_reasons": snapshot["exit_reasons"],
            "supervisor": snapshot["supervisor"],
        }

    if include_baselines:
        results = {
            **build_baselines(
                tick_rows,
                instrument_id=instrument_id,
                initial_balance=initial_balance,
                size=size,
            ),
            **results,
        }
    return results


def compare_raw_file(
    path: Path,
    *,
    instrument_id: str,
    strategies: Iterable[StrategyName] = DEFAULT_COMPARISON_STRATEGIES,
    initial_balance: float = 100000.0,
    size: float | None = None,
    supervisor: bool = True,
    bar_seconds: int = 0,
    include_baselines: bool = True,
) -> dict[str, dict[str, Any]]:
    return compare_ticks(
        read_raw_ticks(path),
        instrument_id=instrument_id,
        strategies=strategies,
        initial_balance=initial_balance,
        size=size,
        supervisor=supervisor,
        bar_seconds=bar_seconds,
        include_baselines=include_baselines,
    )
