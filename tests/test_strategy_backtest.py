from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from jevpip.backtest import strategy as module
from jevpip.backtest.strategy import StrategyBacktestConfig
from jevpip.instruments import get_instrument
from jevpip.market.models import MarketTick


def _ticks(values: list[tuple[str, str]]) -> list[MarketTick]:
    instrument = get_instrument("USD_JPY")
    start = datetime(2026, 9, 19, tzinfo=timezone.utc)
    rows = []
    for index, (bid, ask) in enumerate(values):
        at = start + timedelta(minutes=index + 1)
        rows.append(
            MarketTick(
                instrument_id=instrument.id,
                symbol=instrument.api_symbol,
                display_symbol=instrument.display_symbol,
                bid=Decimal(bid),
                ask=Decimal(ask),
                market_timestamp=at,
                received_at=at,
                price_unit=instrument.price_unit,
                move_unit_label=instrument.move_unit_label,
                status="HISTORICAL",
                raw=None,
            )
        )
    return rows


def test_strategy_backtest_runs_momentum_through_paper_broker(monkeypatch):
    ticks = _ticks(
        [
            ("150.000", "150.002"),
            ("150.010", "150.012"),
            ("150.020", "150.022"),
            ("150.030", "150.032"),
        ]
    )
    monkeypatch.setattr(
        module,
        "load_historical_ticks",
        lambda date, instrument_id, limit=None: (ticks, "fx_bid_ask_close"),
    )
    result = module.run_strategy_backtest(
        date="20260919",
        instrument_id="USD_JPY",
        config=StrategyBacktestConfig(
            strategy="momentum",
            initial_balance=100000,
            size=1000,
            max_spread_units=2,
            take_profit_units=1,
            stop_loss_units=10,
            slippage_units=0,
            momentum_lookback_bars=1,
            momentum_trigger_units=0.5,
            max_hold_bars=10,
            cooldown_bars=0,
            supervisor_enabled=True,
        ),
    )

    assert result["rows"] == 4
    assert result["input_semantics"] == "historical_1m_close"
    assert result["summary"]["closed_trades"] >= 1
    assert result["summary"]["realized_pnl"] == result["summary"]["net_pnl"]
    assert "no_trade" in result["baselines"]
    assert "buy_and_hold" in result["baselines"]
    assert result["baselines"]["no_trade"]["net_pnl"] == 0.0


def test_strategy_backtest_closes_open_position_at_sample_end(monkeypatch):
    ticks = _ticks(
        [
            ("150.000", "150.002"),
            ("150.010", "150.012"),
            ("150.011", "150.013"),
        ]
    )
    monkeypatch.setattr(
        module,
        "load_historical_ticks",
        lambda date, instrument_id, limit=None: (ticks, "fx_bid_ask_close"),
    )
    result = module.run_strategy_backtest(
        date="20260919",
        instrument_id="USD_JPY",
        config=StrategyBacktestConfig(
            strategy="momentum",
            initial_balance=100000,
            size=1000,
            max_spread_units=2,
            take_profit_units=100,
            stop_loss_units=100,
            slippage_units=0,
            momentum_lookback_bars=1,
            momentum_trigger_units=0.5,
            max_hold_bars=100,
            cooldown_bars=0,
            supervisor_enabled=False,
        ),
    )
    assert result["summary"]["closed_trades"] == 1
    assert result["summary"]["exit_reasons"]["end_of_sample"]["count"] == 1


def test_strategy_backtest_btc_mode_stays_explicit(monkeypatch):
    instrument = get_instrument("BTC")
    start = datetime(2026, 9, 19, tzinfo=timezone.utc)
    ticks = [
        MarketTick(
            instrument_id=instrument.id,
            symbol=instrument.api_symbol,
            display_symbol=instrument.display_symbol,
            bid=Decimal("17000000") + Decimal(index * 2000),
            ask=Decimal("17000000") + Decimal(index * 2000),
            market_timestamp=start + timedelta(minutes=index + 1),
            received_at=start + timedelta(minutes=index + 1),
            price_unit=instrument.price_unit,
            move_unit_label=instrument.move_unit_label,
            status="HISTORICAL",
            raw=None,
        )
        for index in range(4)
    ]
    monkeypatch.setattr(
        module,
        "load_historical_ticks",
        lambda date, instrument_id, limit=None: (ticks, "crypto_close_only"),
    )
    result = module.run_strategy_backtest(
        date="20260919",
        instrument_id="BTC",
        config=StrategyBacktestConfig(
            strategy="ma_trend",
            initial_balance=100000,
            size=0.001,
            max_spread_units=5000,
            take_profit_units=100000,
            stop_loss_units=100000,
            slippage_units=0,
            ma_fast_period=2,
            ma_slow_period=3,
            ma_min_gap_units=1,
            max_hold_bars=10,
            cooldown_bars=0,
            supervisor_enabled=True,
        ),
    )
    assert result["replay_mode"] == "crypto_close_only"
    assert result["config"]["strategy"] == "ma_trend"
    assert result["baselines"]["buy_and_hold"]["fees_paid"] > 0
