from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from jevpip.backtest.kline import load_historical_ticks
from jevpip.broker.autopilot import AutopilotBroker
from jevpip.broker.comparison import build_baselines
from jevpip.broker.paper import PaperConfig
from jevpip.instruments import get_instrument

SpiritualOracle = Literal["moon_phase", "zodiac_polarity", "tarot"]


@dataclass(frozen=True, slots=True)
class SpiritualBacktestConfig:
    oracle: SpiritualOracle
    initial_balance: float
    size: float
    paper_leverage: float = 25.0
    target_units: float = 10.0
    target_jpy: float = 500.0
    reentry_seconds: float = 60.0
    max_spread_units: float = 1.5
    max_drawdown_pct: float = 0.20
    slippage_units: float = 0.0


def _event_from_tick(tick: Any) -> dict[str, Any]:
    return {
        "instrument_id": tick.instrument_id,
        "symbol": tick.symbol,
        "market_timestamp": tick.market_timestamp.isoformat(),
        "received_at": tick.received_at.isoformat(),
        "bid": str(tick.bid),
        "ask": str(tick.ask),
        # Historical 1m points are replay samples. Treat each point as executable
        # for the shared Fifty+ broker while preserving the approximation in
        # replay_mode / input_semantics.
        "status": "OPEN",
    }


def _paper_config(
    instrument_id: str,
    config: SpiritualBacktestConfig,
) -> PaperConfig:
    instrument = get_instrument(instrument_id)
    return PaperConfig(
        instrument_id=instrument.id,
        initial_balance=config.initial_balance,
        size=config.size,
        paper_leverage=config.paper_leverage,
        price_unit=float(instrument.price_unit),
        move_unit_label=instrument.move_unit_label,
        fee_rate=float(instrument.paper_fee_rate),
        fee_label=instrument.paper_fee_label,
        slippage_units=config.slippage_units,
        short_is_synthetic=instrument.paper_short_is_synthetic,
        strategy_enabled=False,
        deterministic_supervisor_enabled=False,
        autopilot_enabled=True,
        autopilot_style="fifty",
        autopilot_fundamentals=False,
        autopilot_horizon_seconds=30,
        autopilot_confirmations=1,
        autopilot_fifty_oracle=config.oracle,
        autopilot_fifty_target_units=config.target_units,
        autopilot_fifty_target_jpy=config.target_jpy,
        autopilot_fifty_reentry_seconds=config.reentry_seconds,
        autopilot_max_spread=config.max_spread_units,
        autopilot_max_drawdown_pct=config.max_drawdown_pct,
    )


def run_spiritual_backtest(
    *,
    date: str,
    instrument_id: str,
    config: SpiritualBacktestConfig,
    limit: int | None = None,
) -> dict[str, Any]:
    if config.oracle not in {"moon_phase", "zodiac_polarity", "tarot"}:
        raise ValueError("unsupported spiritual oracle")
    if config.reentry_seconds < 0:
        raise ValueError("reentry_seconds must be >= 0")
    if not 0 < config.max_drawdown_pct <= 1:
        raise ValueError("max_drawdown_pct must be within (0, 1]")
    if config.target_units <= 0 or config.target_jpy <= 0:
        raise ValueError("Fifty+ target must be positive")

    ticks, replay_mode = load_historical_ticks(
        date,
        instrument_id=instrument_id,
        limit=limit,
    )
    events = [_event_from_tick(tick) for tick in ticks]
    broker = AutopilotBroker(_paper_config(instrument_id, config))

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
        initial_balance=config.initial_balance,
        size=config.size,
        slippage_units=config.slippage_units,
    )
    trades = [event for event in generated if event.get("kind") == "paper_trade"]
    opens = [event for event in trades if event.get("action") == "OPEN"]

    return {
        "instrument_id": instrument_id,
        "date": date,
        "replay_mode": replay_mode,
        "input_semantics": "historical_1m_close_fifty_plus",
        "oracle": config.oracle,
        "rows": len(events),
        "config": asdict(config),
        "summary": {
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
            "risk_halted": snapshot.get("risk_halted", False),
            "long_entries": sum(event.get("side") == "LONG" for event in opens),
            "short_entries": sum(event.get("side") == "SHORT" for event in opens),
        },
        "baselines": baselines,
        "trades": trades,
        "generated_events": len(generated),
    }
