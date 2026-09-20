from datetime import datetime, timezone

import pytest

from jevpip.gmo.public_rest import fetch_public_ticker
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


class _TickerResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fetch_public_fx_ticker_uses_all_symbol_endpoint(monkeypatch):
    calls = []

    def fake_get(url, *, params=None, timeout):
        calls.append((url, params, timeout))
        return _TickerResponse({
            "status": 0,
            "data": [
                {"symbol": "EUR_JPY", "bid": "183.100", "ask": "183.130", "timestamp": "2026-09-21T00:00:00Z", "status": "OPEN"},
                {"symbol": "USD_JPY", "bid": "157.000", "ask": "157.015", "timestamp": "2026-09-21T00:00:01Z", "status": "OPEN"},
            ],
        })

    monkeypatch.setattr("jevpip.gmo.public_rest.httpx.get", fake_get)
    quote = fetch_public_ticker("USD_JPY")
    assert str(quote.bid) == "157.000"
    assert str(quote.ask) == "157.015"
    assert quote.status == "OPEN"
    assert calls == [("https://forex-api.coin.z.com/public/v1/ticker", None, 10.0)]


def test_fetch_public_btc_ticker_uses_symbol_parameter(monkeypatch):
    calls = []

    def fake_get(url, *, params=None, timeout):
        calls.append((url, params, timeout))
        return _TickerResponse({
            "status": 0,
            "data": [{"symbol": "BTC", "bid": "16999000", "ask": "17001000", "timestamp": "2026-09-21T00:00:00Z"}],
        })

    monkeypatch.setattr("jevpip.gmo.public_rest.httpx.get", fake_get)
    quote = fetch_public_ticker("BTC")
    assert str(quote.bid) == "16999000"
    assert str(quote.ask) == "17001000"
    assert quote.status == "OPEN"
    assert calls == [("https://api.coin.z.com/public/v1/ticker", {"symbol": "BTC"}, 10.0)]


def test_fetch_public_ticker_rejects_crossed_quote(monkeypatch):
    def fake_get(url, *, params=None, timeout):
        return _TickerResponse({
            "status": 0,
            "data": [{"symbol": "USD_JPY", "bid": "157.020", "ask": "157.010", "timestamp": "2026-09-21T00:00:00Z", "status": "OPEN"}],
        })

    monkeypatch.setattr("jevpip.gmo.public_rest.httpx.get", fake_get)
    with pytest.raises(RuntimeError, match="crossed quote"):
        fetch_public_ticker("USD_JPY")
