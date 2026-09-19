from decimal import Decimal

from jevpip.instruments import get_instrument, public_instruments


def test_btc_instrument_defaults_are_crypto_specific():
    btc = get_instrument("BTC")
    assert btc.api_symbol == "BTC"
    assert btc.display_symbol == "BTC/JPY"
    assert btc.market_kind == "crypto_spot"
    assert btc.price_unit == Decimal("1")
    assert btc.default_paper_size == Decimal("0.001")


def test_public_instruments_hide_ws_endpoint_and_expose_ui_defaults():
    payload = public_instruments()
    assert payload["BTC"]["quantity_label"] == "BTC"
    assert "ws_url" not in payload["BTC"]
