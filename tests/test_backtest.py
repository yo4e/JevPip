from decimal import Decimal

from jevpip.backtest import kline as module
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

    def fake_fetch(date, price_type):
        return bid if price_type == "BID" else ask

    monkeypatch.setattr(module, "fetch_klines", fake_fetch)
    rows = module.replay_kline("20260919", {"quote": True})
    assert rows[0]["features"]["quote"]["spread_pips"] == 2.0
    assert round(rows[0]["outcome_1m"]["delta_mid_pips"], 6) == 3.0
    assert round(rows[0]["outcome_1m"]["long_edge_pips"], 6) == 1.0
    assert round(rows[0]["outcome_1m"]["short_edge_pips"], 6) == -5.0
