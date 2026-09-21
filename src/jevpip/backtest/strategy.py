from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from jevpip.backtest.common import run_historical_paper_broker
from jevpip.backtest.kline import load_historical_ticks
from jevpip.broker.paper import PaperBroker, PaperConfig
from jevpip.instruments import get_instrument

CodeStrategy = Literal["momentum", "rsi_mean_reversion", "ma_trend"]


@dataclass(frozen=True, slots=True)
class StrategyBacktestConfig:
    strategy: CodeStrategy
    initial_balance: float
    size: float
    max_spread_units: float
    take_profit_units: float
    stop_loss_units: float
    slippage_units: float
    momentum_lookback_bars: int = 1
    momentum_trigger_units: float = 0.6
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    ma_fast_period: int = 5
    ma_slow_period: int = 20
    ma_min_gap_units: float = 0.2
    max_hold_bars: int = 8
    cooldown_bars: int = 1
    supervisor_enabled: bool = True


def _paper_config(
    instrument_id: str,
    config: StrategyBacktestConfig,
) -> PaperConfig:
    instrument = get_instrument(instrument_id)
    return PaperConfig(
        initial_balance=config.initial_balance,
        size=config.size,
        strategy=config.strategy,
        price_unit=float(instrument.price_unit),
        move_unit_label=instrument.move_unit_label,
        momentum_window_seconds=float(config.momentum_lookback_bars * 60),
        momentum_trigger_units=config.momentum_trigger_units,
        max_spread_units=config.max_spread_units,
        take_profit_units=config.take_profit_units,
        stop_loss_units=config.stop_loss_units,
        max_hold_seconds=float(config.max_hold_bars * 60),
        cooldown_seconds=float(config.cooldown_bars * 60),
        fee_rate=float(instrument.paper_fee_rate),
        fee_label=instrument.paper_fee_label,
        slippage_units=config.slippage_units,
        short_is_synthetic=instrument.paper_short_is_synthetic,
        rsi_period=config.rsi_period,
        rsi_oversold=config.rsi_oversold,
        rsi_overbought=config.rsi_overbought,
        ma_fast_period=config.ma_fast_period,
        ma_slow_period=config.ma_slow_period,
        ma_min_gap_units=config.ma_min_gap_units,
        deterministic_supervisor_enabled=config.supervisor_enabled,
        # Each historical point is already one closed 1-minute bar. RSI/MA use
        # the incoming close sequence directly instead of rebuilding bars.
        strategy_bar_seconds=0,
    )


def run_strategy_backtest(
    *,
    date: str,
    instrument_id: str,
    config: StrategyBacktestConfig,
    limit: int | None = None,
) -> dict[str, Any]:
    if config.momentum_lookback_bars < 1:
        raise ValueError("momentum_lookback_bars must be >= 1")
    if config.max_hold_bars < 1:
        raise ValueError("max_hold_bars must be >= 1")
    if config.cooldown_bars < 0:
        raise ValueError("cooldown_bars must be >= 0")
    if config.rsi_period < 2:
        raise ValueError("rsi_period must be >= 2")
    if config.ma_fast_period < 1 or config.ma_slow_period <= config.ma_fast_period:
        raise ValueError("MA periods must satisfy 1 <= fast < slow")

    ticks, replay_mode = load_historical_ticks(
        date,
        instrument_id=instrument_id,
        limit=limit,
    )
    run = run_historical_paper_broker(
        ticks=ticks,
        replay_mode=replay_mode,
        broker=PaperBroker(_paper_config(instrument_id, config)),
        instrument_id=instrument_id,
        initial_balance=config.initial_balance,
        size=config.size,
        slippage_units=config.slippage_units,
    )

    result = {
        "analysis_kind": "pnl_backtest",
        "instrument_id": instrument_id,
        "date": date,
        "replay_mode": run["replay_mode"],
        "input_semantics": "historical_1m_close",
        "rows": run["rows"],
        "config": asdict(config),
        "summary": run["summary"],
        "baselines": run["baselines"],
        "trades": run["trades"],
        "generated_events": run["generated_events"],
    }
    return result
