from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from jevpip.backtest.common import run_historical_paper_broker
from jevpip.backtest.kline import load_historical_ticks
from jevpip.broker.autopilot import AutopilotBroker
from jevpip.broker.paper import PaperConfig
from jevpip.instruments import get_instrument

SpiritualOracle = Literal["moon_phase", "zodiac_polarity", "tarot", "coin_flip"]


@dataclass(frozen=True, slots=True)
class SpiritualBacktestConfig:
    oracle: SpiritualOracle
    initial_balance: float
    size: float
    paper_leverage: float = 25.0
    target_units: float = 10.0
    target_jpy: float = 500.0
    reentry_seconds: float = 600.0
    max_spread_units: float = 1.5
    max_drawdown_pct: float = 0.20
    slippage_units: float = 0.0


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
    if config.oracle not in {"moon_phase", "zodiac_polarity", "tarot", "coin_flip"}:
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
    run = run_historical_paper_broker(
        ticks=ticks,
        replay_mode=replay_mode,
        broker=AutopilotBroker(_paper_config(instrument_id, config)),
        instrument_id=instrument_id,
        initial_balance=config.initial_balance,
        size=config.size,
        slippage_units=config.slippage_units,
    )
    opens = [event for event in run["trades"] if event.get("action") == "OPEN"]
    summary = {
        **run["summary"],
        "risk_halted": run["snapshot"].get("risk_halted", False),
        "long_entries": sum(event.get("side") == "LONG" for event in opens),
        "short_entries": sum(event.get("side") == "SHORT" for event in opens),
    }

    return {
        "analysis_kind": "pnl_backtest",
        "instrument_id": instrument_id,
        "date": date,
        "replay_mode": run["replay_mode"],
        "input_semantics": "historical_1m_close_fifty_plus",
        "oracle": config.oracle,
        "rows": run["rows"],
        "config": asdict(config),
        "summary": summary,
        "baselines": run["baselines"],
        "trades": run["trades"],
        "generated_events": run["generated_events"],
    }
