from __future__ import annotations

import json
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


def compare_ticks(
    ticks: Iterable[dict[str, Any]],
    *,
    instrument_id: str,
    strategies: Iterable[StrategyName] = DEFAULT_COMPARISON_STRATEGIES,
    initial_balance: float = 100000.0,
    size: float | None = None,
    supervisor: bool = True,
) -> dict[str, dict[str, Any]]:
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
            )
        )
        for name in selected
    }

    seen = 0
    for tick in ticks:
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
            "supervisor": snapshot["supervisor"],
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
) -> dict[str, dict[str, Any]]:
    return compare_ticks(
        read_raw_ticks(path),
        instrument_id=instrument_id,
        strategies=strategies,
        initial_balance=initial_balance,
        size=size,
        supervisor=supervisor,
    )
