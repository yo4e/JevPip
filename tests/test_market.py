from datetime import datetime, timedelta, timezone
from decimal import Decimal

from jevpip.market.buffer import TickBuffer
from jevpip.market.features import build_features, rsi
from jevpip.market.models import MarketTick


def tick(at, bid="156.00", ask="156.02"):
    return MarketTick("USD_JPY", Decimal(bid), Decimal(ask), at, at, "OPEN", {})


def test_quote_and_return_features():
    start = datetime(2026, 9, 19, tzinfo=timezone.utc)
    buf = TickBuffer()
    first = tick(start)
    buf.append(first)
    second = tick(start + timedelta(seconds=5), "156.03", "156.05")
    buf.append(second)
    state = build_features(second, buf, {"quote": True, "returns_seconds": [5]})
    assert state["quote"]["mid"] == 156.04
    assert state["quote"]["spread_pips"] == 2.0
    assert state["move_pips"]["5s"] == 3.0


def test_moon_only_excludes_price():
    at = datetime(2026, 9, 19, tzinfo=timezone.utc)
    buf = TickBuffer()
    current = tick(at)
    buf.append(current)
    state = build_features(current, buf, {"quote": False, "moon_phase": True})
    assert "quote" not in state
    assert set(state["moon"]) == {"phase", "age_days", "illumination"}


def test_rsi_flat_is_neutral():
    values = [Decimal("100")] * 15
    assert rsi(values, 14) == 50.0
