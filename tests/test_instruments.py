from decimal import Decimal

from jevpip.instruments import get_instrument, public_instruments


def test_btc_instrument_defaults_are_crypto_specific():
    btc = get_instrument("BTC")
    assert btc.api_symbol == "BTC"
    assert btc.display_symbol == "BTC/JPY"
    assert btc.market_kind == "crypto_spot"
    assert btc.price_unit == Decimal("1")
    assert btc.default_paper_size == Decimal("0.001")
    assert btc.paper_fee_rate == Decimal("0.0005")
    assert btc.paper_short_is_synthetic is True


def test_jpy_fx_pairs_are_available_for_paper_pnl_in_jpy():
    expected = {
        "USD_JPY",
        "EUR_JPY",
        "GBP_JPY",
        "AUD_JPY",
        "NZD_JPY",
        "CAD_JPY",
        "CHF_JPY",
        "TRY_JPY",
        "ZAR_JPY",
        "MXN_JPY",
        "HUF_JPY",
        "SEK_JPY",
    }
    payload = public_instruments()
    assert expected <= payload.keys()
    for instrument_id in expected:
        instrument = get_instrument(instrument_id)
        assert instrument.market_kind == "fx"
        assert instrument.quote_currency == "JPY"
        assert instrument.price_unit == Decimal("0.01")
        assert instrument.paper_fee_rate == Decimal("0.00002")


def test_public_instruments_hide_ws_endpoint_and_expose_ui_defaults():
    payload = public_instruments()
    assert payload["BTC"]["quantity_label"] == "BTC"
    assert payload["EUR_JPY"]["display_symbol"] == "EUR/JPY"
    assert payload["BTC"]["paper_fee_rate"] == 0.0005
    assert "ws_url" not in payload["BTC"]
