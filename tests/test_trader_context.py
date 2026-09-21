from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from jevpip.config import Settings
from jevpip.trader_context import TIMEFRAME_SPECS, build_timeframe_view
from jevpip.web.read_service import ReadOnlyDataService


def test_trader_history_loader_excludes_unclosed_future_candles(tmp_path):
    as_of = datetime(2026, 9, 21, 9, 30, tzinfo=timezone.utc)
    calls: list[tuple[str, str]] = []

    def fetch_history(instrument_id: str, date: str, interval: str):
        calls.append((date, interval))
        seconds = TIMEFRAME_SPECS[interval]["seconds"]
        rows = []
        for index in range(240):
            opened = as_of - timedelta(seconds=seconds * (241 - index))
            rows.append(
                SimpleNamespace(
                    open_time_ms=int(opened.timestamp() * 1000),
                    open=100 + index,
                    high=101 + index,
                    low=99 + index,
                    close=100.5 + index,
                )
            )
        # This candle has started but has not closed at as_of and must not leak.
        rows.append(
            SimpleNamespace(
                open_time_ms=int(as_of.timestamp() * 1000),
                open=999,
                high=1000,
                low=998,
                close=999,
            )
        )
        return rows

    service = ReadOnlyDataService(
        Settings(_env_file=None, data_dir=tmp_path),
        fetch_public_ticker_fn=lambda instrument_id: None,
        fetch_history_fn=fetch_history,
        private_client_factory=lambda key, secret: None,
    )
    result = asyncio.run(
        service.fetch_trader_history(
            instrument_id="USD_JPY",
            as_of=as_of,
        )
    )

    assert result["errors"] == {}
    assert set(result["timeframes"]) == set(TIMEFRAME_SPECS)
    assert {interval for _, interval in calls} == set(TIMEFRAME_SPECS)
    for interval, bars in result["timeframes"].items():
        assert len(bars) == 240
        assert all(datetime.fromisoformat(row["end_time"]) <= as_of for row in bars)
        assert all(row["close"] != 999 for row in bars)


def test_timeframe_view_computes_common_indicators_from_hidden_history():
    start = datetime(2026, 9, 20, tzinfo=timezone.utc)
    bars = []
    for index in range(205):
        opened = start + timedelta(minutes=index)
        value = 150 + index * 0.01
        bars.append(
            {
                "open_time": opened.isoformat(),
                "end_time": (opened + timedelta(minutes=1)).isoformat(),
                "open": value,
                "high": value + 0.02,
                "low": value - 0.02,
                "close": value + 0.01,
            }
        )

    view = build_timeframe_view("1min", bars, current_bar=None)

    assert view["closed_bars_available"] == 205
    assert len(view["closed_bars"]) == 60
    assert view["indicators"]["sma20"] is not None
    assert view["indicators"]["sma50"] is not None
    assert view["indicators"]["sma200"] is not None
    assert view["indicators"]["rsi14"] is not None
    assert view["indicators"]["atr14"] is not None
    assert 0 <= view["indicators"]["range_position_20"] <= 1
