from datetime import datetime, timezone

from jevpip.gmo.public_ws import parse_ticker, subscribe_message


def test_subscribe_message():
    assert subscribe_message("USD_JPY") == '{"command":"subscribe","channel":"ticker","symbol":"USD_JPY"}'
    assert subscribe_message("BTC") == '{"command":"subscribe","channel":"ticker","symbol":"BTC"}'


def test_parse_fx_ticker():
    received = datetime(2026, 9, 19, tzinfo=timezone.utc)
    tick = parse_ticker(
        {
            "symbol": "USD_JPY",
            "ask": "156.321",
            "bid": "156.301",
            "timestamp": "2026-09-19T01:02:03.000Z",
            "status": "OPEN",
        },
        instrument_id="USD_JPY",
        received_at=received,
    )
    assert str(tick.mid) == "156.311"
    assert str(tick.spread_units) == "2.0"
    assert tick.display_symbol == "USD/JPY"


def test_parse_btc_ticker_uses_yen_move_units():
    received = datetime(2026, 9, 19, tzinfo=timezone.utc)
    tick = parse_ticker(
        {
            "symbol": "BTC",
            "ask": "17001000",
            "bid": "16999000",
            "timestamp": "2026-09-19T01:02:03.000Z",
        },
        instrument_id="BTC",
        received_at=received,
    )
    assert str(tick.mid) == "17000000"
    assert str(tick.spread_units) == "2000"
    assert tick.move_unit_label == "円"
