from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from jevpip.backtest import spiritual as module
from jevpip.backtest.spiritual import SpiritualBacktestConfig
from jevpip.instruments import get_instrument
from jevpip.market.models import MarketTick


def _ticks(values: list[tuple[str, str]]) -> list[MarketTick]:
    instrument = get_instrument("USD_JPY")
    start = datetime(2026, 9, 20, tzinfo=timezone.utc)
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


def test_spiritual_backtest_default_reentry_wait_is_ten_minutes():
    config = SpiritualBacktestConfig(
        oracle="moon_phase",
        initial_balance=100000,
        size=1000,
    )
    assert config.reentry_seconds == 600


def test_spiritual_backtest_runs_zodiac_on_fifty_plus_engine(monkeypatch):
    ticks = _ticks(
        [
            ("150.000", "150.002"),
            ("149.940", "149.942"),
            ("149.930", "149.932"),
            ("149.870", "149.872"),
        ]
    )
    monkeypatch.setattr(
        module,
        "load_historical_ticks",
        lambda date, instrument_id, limit=None: (ticks, "fx_bid_ask_close"),
    )
    result = module.run_spiritual_backtest(
        date="20260920",
        instrument_id="USD_JPY",
        config=SpiritualBacktestConfig(
            oracle="zodiac_polarity",
            initial_balance=100000,
            size=1000,
            paper_leverage=25,
            target_units=5,
            target_jpy=500,
            reentry_seconds=60,
            max_spread_units=1.5,
            max_drawdown_pct=0.20,
            slippage_units=0,
        ),
    )

    assert result["oracle"] == "zodiac_polarity"
    assert result["input_semantics"] == "historical_1m_close_fifty_plus"
    assert result["summary"]["short_entries"] >= 1
    assert result["summary"]["long_entries"] == 0
    assert result["summary"]["closed_trades"] >= 1
    assert "buy_and_hold" in result["baselines"]
    assert "no_trade" in result["baselines"]
    assert all(trade["kind"] == "paper_trade" for trade in result["trades"])


def test_spiritual_backtest_reuses_fifty_spread_gate(monkeypatch):
    ticks = _ticks(
        [
            ("150.000", "150.030"),
            ("150.000", "150.010"),
            ("149.940", "149.950"),
        ]
    )
    monkeypatch.setattr(
        module,
        "load_historical_ticks",
        lambda date, instrument_id, limit=None: (ticks, "fx_bid_ask_close"),
    )
    result = module.run_spiritual_backtest(
        date="20260920",
        instrument_id="USD_JPY",
        config=SpiritualBacktestConfig(
            oracle="moon_phase",
            initial_balance=100000,
            size=1000,
            paper_leverage=25,
            target_units=20,
            target_jpy=500,
            reentry_seconds=60,
            max_spread_units=1.5,
            max_drawdown_pct=0.20,
            slippage_units=0,
        ),
    )

    opens = [x for x in result["trades"] if x.get("action") == "OPEN"]
    assert opens
    assert opens[0]["timestamp"] == ticks[1].market_timestamp.isoformat()


def test_spiritual_backtest_accepts_random_tarot(monkeypatch):
    ticks = _ticks(
        [
            ("150.000", "150.002"),
            ("150.010", "150.012"),
            ("150.020", "150.022"),
        ]
    )
    monkeypatch.setattr(
        module,
        "load_historical_ticks",
        lambda date, instrument_id, limit=None: (ticks, "fx_bid_ask_close"),
    )
    result = module.run_spiritual_backtest(
        date="20260920",
        instrument_id="USD_JPY",
        config=SpiritualBacktestConfig(
            oracle="tarot",
            initial_balance=100000,
            size=1000,
            paper_leverage=25,
            target_units=20,
            target_jpy=500,
            reentry_seconds=60,
            max_spread_units=1.5,
            max_drawdown_pct=0.20,
            slippage_units=0,
        ),
    )

    assert result["oracle"] == "tarot"
    assert result["generated_events"] >= 1
    assert any(x.get("action") == "OPEN" for x in result["trades"])


def test_spiritual_backtest_accepts_coin_flip_control(monkeypatch):
    ticks = _ticks(
        [
            ("150.000", "150.002"),
            ("150.010", "150.012"),
            ("150.020", "150.022"),
        ]
    )
    monkeypatch.setattr(
        module,
        "load_historical_ticks",
        lambda date, instrument_id, limit=None: (ticks, "fx_bid_ask_close"),
    )
    result = module.run_spiritual_backtest(
        date="20260920",
        instrument_id="USD_JPY",
        config=SpiritualBacktestConfig(
            oracle="coin_flip",
            initial_balance=100000,
            size=1000,
            paper_leverage=25,
            target_units=20,
            target_jpy=500,
            reentry_seconds=60,
            max_spread_units=1.5,
            max_drawdown_pct=0.20,
            slippage_units=0,
        ),
    )

    assert result["oracle"] == "coin_flip"
    assert result["generated_events"] >= 1
    assert any(x.get("action") == "OPEN" for x in result["trades"])


def test_spiritual_backtest_btc_keeps_close_only_limitation(monkeypatch):
    instrument = get_instrument("BTC")
    start = datetime(2026, 9, 20, tzinfo=timezone.utc)
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
    result = module.run_spiritual_backtest(
        date="20260920",
        instrument_id="BTC",
        config=SpiritualBacktestConfig(
            oracle="moon_phase",
            initial_balance=100000,
            size=0.001,
            paper_leverage=25,
            target_units=10,
            target_jpy=500,
            reentry_seconds=60,
            max_spread_units=5000,
            max_drawdown_pct=0.20,
            slippage_units=0,
        ),
    )
    assert result["replay_mode"] == "crypto_close_only"
    assert result["config"]["paper_leverage"] == 25
    assert result["baselines"]["buy_and_hold"]["fees_paid"] > 0
