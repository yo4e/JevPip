from decimal import Decimal

from jevpip.backtest import kline as module
from jevpip.gmo.history import HistoryCandle
from jevpip.gmo.public_rest import KLine


def test_kline_replay_keeps_spread_and_future_edges(monkeypatch):
    bid = [
        KLine(0, Decimal("100.00"), Decimal("100.00"), Decimal("100.00"), Decimal("100.00")),
        KLine(60_000, Decimal("100.03"), Decimal("100.03"), Decimal("100.03"), Decimal("100.03")),
    ]
    ask = [
        KLine(0, Decimal("100.02"), Decimal("100.02"), Decimal("100.02"), Decimal("100.02")),
        KLine(60_000, Decimal("100.05"), Decimal("100.05"), Decimal("100.05"), Decimal("100.05")),
    ]

    def fake_fetch(date, price_type, symbol="USD_JPY", interval="1min"):
        assert symbol == "USD_JPY"
        return bid if price_type == "BID" else ask

    monkeypatch.setattr(module, "fetch_klines", fake_fetch)
    rows = module.replay_kline("20260919", {"quote": True})
    assert rows[0]["features"]["quote"]["spread_units"] == 2.0
    assert rows[0]["features"]["quote"]["spread_unit"] == "pips"
    assert rows[0]["replay_mode"] == "fx_bid_ask_close"
    assert round(rows[0]["outcome_1m"]["delta_units"], 6) == 3.0
    assert round(rows[0]["outcome_1m"]["long_edge_units"], 6) == 1.0
    assert round(rows[0]["outcome_1m"]["short_edge_units"], 6) == -5.0


def test_btc_replay_uses_close_only_without_fake_spread(monkeypatch):
    candles = [
        HistoryCandle(
            open_time_ms=0,
            open=Decimal("17000000"),
            high=Decimal("17001000"),
            low=Decimal("16999000"),
            close=Decimal("17000000"),
        ),
        HistoryCandle(
            open_time_ms=60_000,
            open=Decimal("17000000"),
            high=Decimal("17003000"),
            low=Decimal("16999500"),
            close=Decimal("17002000"),
        ),
    ]

    def fake_history(instrument_id, date, interval="1min"):
        assert instrument_id == "BTC"
        assert date == "20260919"
        assert interval == "1min"
        return candles

    monkeypatch.setattr(module, "fetch_history", fake_history)
    rows = module.replay_kline(
        "20260919",
        {"quote": True},
        instrument_id="BTC",
    )

    assert rows[0]["replay_mode"] == "crypto_close_only"
    assert rows[0]["features"]["quote"]["spread_units"] == 0.0
    assert rows[0]["features"]["quote"]["spread_unit"] == "円"
    assert rows[0]["outcome_1m"]["delta_units"] == 2000.0
    assert rows[0]["outcome_1m"]["long_edge_units"] is None
    assert rows[0]["outcome_1m"]["short_edge_units"] is None
