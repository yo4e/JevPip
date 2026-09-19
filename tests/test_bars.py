from datetime import datetime, timezone
from decimal import Decimal

import pytest

from jevpip.broker.bars import TimeBarBuilder


def dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_builds_ohlc_and_closes_on_next_bucket():
    builder = TimeBarBuilder(60)
    assert builder.update(dt("2026-09-19T00:00:05Z"), Decimal("100")) == []
    assert builder.update(dt("2026-09-19T00:00:20Z"), Decimal("102")) == []
    assert builder.update(dt("2026-09-19T00:00:50Z"), Decimal("99")) == []

    completed = builder.update(dt("2026-09-19T00:01:00Z"), Decimal("101"))
    assert len(completed) == 1
    bar = completed[0]
    assert bar.open == Decimal("100")
    assert bar.high == Decimal("102")
    assert bar.low == Decimal("99")
    assert bar.close == Decimal("99")
    assert bar.tick_count == 3
    assert bar.start == dt("2026-09-19T00:00:00Z")
    assert bar.end == dt("2026-09-19T00:01:00Z")

    assert builder.current is not None
    assert builder.current.open == Decimal("101")


def test_gap_does_not_invent_empty_bars():
    builder = TimeBarBuilder(60)
    builder.update(dt("2026-09-19T00:00:10Z"), Decimal("100"))
    completed = builder.update(dt("2026-09-19T00:05:10Z"), Decimal("105"))
    assert len(completed) == 1
    assert completed[0].start == dt("2026-09-19T00:00:00Z")
    assert builder.current is not None
    assert builder.current.start == dt("2026-09-19T00:05:00Z")


def test_timezone_is_normalized_to_utc():
    builder = TimeBarBuilder(300)
    builder.update(dt("2026-09-19T09:02:00+09:00"), Decimal("100"))
    assert builder.current is not None
    assert builder.current.start == datetime(2026, 9, 19, 0, 0, tzinfo=timezone.utc)


def test_rejects_out_of_order_tick():
    builder = TimeBarBuilder(60)
    builder.update(dt("2026-09-19T00:01:10Z"), Decimal("100"))
    with pytest.raises(ValueError, match="non-decreasing"):
        builder.update(dt("2026-09-19T00:00:10Z"), Decimal("99"))


def test_flush_returns_current_bar():
    builder = TimeBarBuilder(10)
    builder.update(dt("2026-09-19T00:00:01Z"), Decimal("10"))
    bar = builder.flush()
    assert bar is not None
    assert bar.close == Decimal("10")
    assert builder.current is None
