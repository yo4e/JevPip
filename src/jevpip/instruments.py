from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

MarketKind = Literal["fx", "crypto_spot"]


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
    default_paper_size: Decimal
    default_momentum_trigger: Decimal
    default_max_spread: Decimal
    default_take_profit: Decimal
    default_stop_loss: Decimal


INSTRUMENTS: dict[str, Instrument] = {
    "USD_JPY": Instrument(
        id="USD_JPY",
        api_symbol="USD_JPY",
        display_symbol="USD/JPY",
        market_kind="fx",
        ws_url="wss://forex-api.coin.z.com/ws/public/v1",
        price_unit=Decimal("0.01"),
        move_unit_label="pips",
        price_decimals=3,
        quantity_label="通貨",
        default_paper_size=Decimal("1000"),
        default_momentum_trigger=Decimal("0.6"),
        default_max_spread=Decimal("1.5"),
        default_take_profit=Decimal("1.0"),
        default_stop_loss=Decimal("1.0"),
    ),
    "BTC": Instrument(
        id="BTC",
        api_symbol="BTC",
        display_symbol="BTC/JPY",
        market_kind="crypto_spot",
        ws_url="wss://api.coin.z.com/ws/public/v1",
        price_unit=Decimal("1"),
        move_unit_label="円",
        price_decimals=0,
        quantity_label="BTC",
        default_paper_size=Decimal("0.001"),
        default_momentum_trigger=Decimal("1000"),
        default_max_spread=Decimal("5000"),
        default_take_profit=Decimal("3000"),
        default_stop_loss=Decimal("3000"),
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
            "default_paper_size": float(item.default_paper_size),
            "default_momentum_trigger": float(item.default_momentum_trigger),
            "default_max_spread": float(item.default_max_spread),
            "default_take_profit": float(item.default_take_profit),
            "default_stop_loss": float(item.default_stop_loss),
        }
        for key, item in INSTRUMENTS.items()
    }
