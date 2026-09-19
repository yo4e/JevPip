from datetime import datetime, timedelta, timezone
from decimal import Decimal

from jevpip.market.buffer import TickBuffer
from jevpip.market.features import build_features, rsi
from jevpip.market.models import MarketTick


def tick(at, bid="156.00", ask="156.02"):
    return MarketTick(
        instrument_id="USD_JPY",
        symbol="USD_JPY",
        display_symbol="USD/JPY",
        bid=Decimal(bid),
        ask=Decimal(ask),
        market_timestamp=at,
        received_at=at,
        price_unit=Decimal("0.01"),
        move_unit_label="pips",
        status="OPEN",
        raw={},
    )


def test_quote_and_return_features():
    start = datetime(2026, 9, 19, tzinfo=timezone.utc)
    buf = TickBuffer()
    first = tick(start)
    buf.append(first)
    second = tick(start + timedelta(seconds=5), "156.03", "156.05")
    buf.append(second)
    state = build_features(second, buf, {"quote": True, "returns_seconds": [5]})
    assert state["quote"]["mid"] == 156.04
    assert state["quote"]["spread_units"] == 2.0
    assert state["quote"]["spread_unit"] == "pips"
    assert state["move_units"]["values"]["5s"] == 3.0


def test_moon_only_really_contains_only_moon():
    at = datetime(2026, 9, 19, tzinfo=timezone.utc)
    buf = TickBuffer()
    current = tick(at)
    buf.append(current)
    state = build_features(current, buf, {"quote": False, "moon_phase": True})
    assert set(state) == {"moon"}
    assert set(state["moon"]) == {"phase", "age_days", "illumination"}


def test_rsi_flat_is_neutral():
    values = [Decimal("100")] * 15
    assert rsi(values, 14) == 50.0
