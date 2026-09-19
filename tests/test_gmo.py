from datetime import datetime, timezone

from jevpip.gmo.public_ws import parse_ticker, subscribe_message


def test_subscribe_message():
    assert subscribe_message() == '{"command":"subscribe","channel":"ticker","symbol":"USD_JPY"}'


def test_parse_ticker():
    received = datetime(2026, 9, 19, tzinfo=timezone.utc)
    tick = parse_ticker(
        {
            "symbol": "USD_JPY",
            "ask": "156.321",
            "bid": "156.301",
            "timestamp": "2026-09-19T01:02:03.000Z",
            "status": "OPEN",
        },
        received,
    )
    assert str(tick.mid) == "156.311"
    assert str(tick.spread_pips) == "2.0"
