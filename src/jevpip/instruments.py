from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

MarketKind = Literal["fx", "crypto_spot"]

FX_WS_URL = "wss://forex-api.coin.z.com/ws/public/v1"
CRYPTO_WS_URL = "wss://api.coin.z.com/ws/public/v1"


@dataclass(frozen=True, slots=True)
class Instrument:
    id: str
    api_symbol: str
    display_symbol: str
    market_kind: MarketKind
    ws_url: str
    price_unit: Decimal
    move_unit_label: str
    price_decimals: int
    quantity_label: str
    quote_currency: str
    default_paper_size: Decimal
    default_momentum_trigger: Decimal
    default_max_spread: Decimal
    default_take_profit: Decimal
    default_stop_loss: Decimal
    default_slippage_units: Decimal
    paper_fee_rate: Decimal
    paper_fee_label: str
    paper_short_is_synthetic: bool = False


def _jpy_fx(
    symbol: str,
    display: str,
    *,
    size: str = "1000",
    trigger: str = "0.6",
    max_spread: str = "3.0",
    take_profit: str = "1.5",
    stop_loss: str = "1.5",
) -> Instrument:
    return Instrument(
        id=symbol,
        api_symbol=symbol,
        display_symbol=display,
        market_kind="fx",
        ws_url=FX_WS_URL,
        price_unit=Decimal("0.01"),
        move_unit_label="pips",
        price_decimals=3,
        quantity_label="通貨",
        quote_currency="JPY",
        default_paper_size=Decimal(size),
        default_momentum_trigger=Decimal(trigger),
        default_max_spread=Decimal(max_spread),
        default_take_profit=Decimal(take_profit),
        default_stop_loss=Decimal(stop_loss),
        default_slippage_units=Decimal("0"),
        # GMO外国為替FX API手数料: 約定金額 × 0.002% / 約定。
        # Paperでは「将来APIで成行相当の売買をした場合の参考コスト」として使う。
        paper_fee_rate=Decimal("0.00002"),
        paper_fee_label="FX API参考: 約定金額×0.002% / 約定",
    )


INSTRUMENTS: dict[str, Instrument] = {
    # 対円FX。Paper PnLをJPYのまま正しく扱えるペアだけ先に有効化する。
    "USD_JPY": _jpy_fx(
        "USD_JPY",
        "USD/JPY",
        max_spread="1.5",
        take_profit="1.0",
        stop_loss="1.0",
    ),
    "EUR_JPY": _jpy_fx("EUR_JPY", "EUR/JPY"),
    "GBP_JPY": _jpy_fx("GBP_JPY", "GBP/JPY", max_spread="4.0", take_profit="2.0", stop_loss="2.0"),
    "AUD_JPY": _jpy_fx("AUD_JPY", "AUD/JPY"),
    "NZD_JPY": _jpy_fx("NZD_JPY", "NZD/JPY"),
    "CAD_JPY": _jpy_fx("CAD_JPY", "CAD/JPY"),
    "CHF_JPY": _jpy_fx("CHF_JPY", "CHF/JPY"),
    "TRY_JPY": _jpy_fx("TRY_JPY", "TRY/JPY", size="10000", trigger="1.0", max_spread="10.0", take_profit="3.0", stop_loss="3.0"),
    "ZAR_JPY": _jpy_fx("ZAR_JPY", "ZAR/JPY", size="10000", trigger="1.0", max_spread="10.0", take_profit="3.0", stop_loss="3.0"),
    "MXN_JPY": _jpy_fx("MXN_JPY", "MXN/JPY", size="10000", trigger="1.0", max_spread="10.0", take_profit="3.0", stop_loss="3.0"),
    "HUF_JPY": _jpy_fx("HUF_JPY", "HUF/JPY", size="10000", trigger="1.0", max_spread="10.0", take_profit="3.0", stop_loss="3.0"),
    "SEK_JPY": _jpy_fx("SEK_JPY", "SEK/JPY", size="10000", trigger="1.0", max_spread="10.0", take_profit="3.0", stop_loss="3.0"),
    "BTC": Instrument(
        id="BTC",
        api_symbol="BTC",
        display_symbol="BTC/JPY",
        market_kind="crypto_spot",
        ws_url=CRYPTO_WS_URL,
        price_unit=Decimal("1"),
        move_unit_label="円",
        price_decimals=0,
        quantity_label="BTC",
        quote_currency="JPY",
        default_paper_size=Decimal("0.001"),
        default_momentum_trigger=Decimal("1000"),
        default_max_spread=Decimal("5000"),
        default_take_profit=Decimal("3000"),
        default_stop_loss=Decimal("3000"),
        default_slippage_units=Decimal("0"),
        # 即時BID/ASK約定はTaker相当として保守的にモデル化。
        paper_fee_rate=Decimal("0.0005"),
        paper_fee_label="BTC現物Taker参考: 約定金額×0.05% / 約定",
        # 現物Public tickerを使うが、paper SHORTは実現物売りではない。
        paper_short_is_synthetic=True,
    ),
}


def get_instrument(instrument_id: str) -> Instrument:
    try:
        return INSTRUMENTS[instrument_id]
    except KeyError as exc:
        available = ", ".join(INSTRUMENTS)
        raise ValueError(f"Unknown instrument {instrument_id!r}. Available: {available}") from exc


def public_instruments() -> dict[str, dict[str, object]]:
    return {
        key: {
            "id": item.id,
            "display_symbol": item.display_symbol,
            "market_kind": item.market_kind,
            "move_unit_label": item.move_unit_label,
            "price_decimals": item.price_decimals,
            "quantity_label": item.quantity_label,
            "quote_currency": item.quote_currency,
            "default_paper_size": float(item.default_paper_size),
            "default_momentum_trigger": float(item.default_momentum_trigger),
            "default_max_spread": float(item.default_max_spread),
            "default_take_profit": float(item.default_take_profit),
            "default_stop_loss": float(item.default_stop_loss),
            "default_slippage_units": float(item.default_slippage_units),
            "paper_fee_rate": float(item.paper_fee_rate),
            "paper_fee_label": item.paper_fee_label,
            "paper_short_is_synthetic": item.paper_short_is_synthetic,
        }
        for key, item in INSTRUMENTS.items()
    }
