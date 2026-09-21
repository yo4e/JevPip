from __future__ import annotations

from typing import Any, Iterable

from jevpip.broker.comparison import build_baselines


def historical_event(tick: Any) -> dict[str, Any]:
    """Convert one historical market point into the broker event contract."""
    return {
        "instrument_id": tick.instrument_id,
        "symbol": tick.symbol,
        "market_timestamp": tick.market_timestamp.isoformat(),
        "received_at": tick.received_at.isoformat(),
        "bid": str(tick.bid),
        "ask": str(tick.ask),
        # Historical points are finite replay samples. Treat each point as
        # executable while keeping the approximation explicit in replay_mode.
        "status": "OPEN",
    }


def summarize_paper_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the metrics shared by PnL-oriented historical runs."""
    return {
        "net_pnl": round(
            float(snapshot["equity"] - snapshot["initial_balance"]),
            3,
        ),
        "equity": snapshot["equity"],
        "realized_pnl": snapshot["realized_pnl"],
        "gross_realized_pnl": snapshot["gross_realized_pnl"],
        "fees_paid": snapshot["fees_paid"],
        "slippage_cost": snapshot["slippage_cost"],
        "profit_factor": snapshot["profit_factor"],
        "max_drawdown": snapshot["max_drawdown"],
        "max_drawdown_pct": snapshot["max_drawdown_pct"],
        "closed_trades": snapshot["closed_trades"],
        "wins": snapshot["wins"],
        "win_rate": snapshot["win_rate"],
        "average_trade_pnl": snapshot["average_trade_pnl"],
        "average_win_pnl": snapshot["average_win_pnl"],
        "average_loss_pnl": snapshot["average_loss_pnl"],
        "exit_reasons": snapshot["exit_reasons"],
    }


def run_historical_paper_broker(
    *,
    ticks: Iterable[Any],
    replay_mode: str,
    broker: Any,
    instrument_id: str,
    initial_balance: float,
    size: float,
    slippage_units: float,
) -> dict[str, Any]:
    """Replay historical points through a paper broker with common accounting.

    The caller owns strategy/oracle-specific configuration. This helper only
    standardizes the market-event conversion, end-of-sample finalization,
    shared PnL summary, baselines and trade extraction.
    """
    events = [historical_event(tick) for tick in ticks]

    generated: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        generated.extend(
            broker.on_tick(
                event,
                allow_entry=index < len(events) - 1,
            )
        )

    if events:
        final_trade = broker.finalize(events[-1])
        if final_trade is not None:
            generated.append(final_trade)

    snapshot = broker.snapshot()
    baselines = build_baselines(
        events,
        instrument_id=instrument_id,
        initial_balance=initial_balance,
        size=size,
        slippage_units=slippage_units,
    )
    trades = [event for event in generated if event.get("kind") == "paper_trade"]

    return {
        "replay_mode": replay_mode,
        "rows": len(events),
        "summary": summarize_paper_snapshot(snapshot),
        "baselines": baselines,
        "trades": trades,
        "generated_events": len(generated),
        "snapshot": snapshot,
    }
