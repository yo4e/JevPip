from __future__ import annotations

import json
from pathlib import Path

import pytest

from jevpip.broker.comparison import compare_raw_file, compare_ticks, read_raw_ticks


def _tick(second: int, bid: float, ask: float, instrument: str = "USD_JPY") -> dict:
    timestamp = f"2026-09-19T00:00:{second:02d}+00:00"
    return {
        "instrument_id": instrument,
        "symbol": instrument,
        "market_timestamp": timestamp,
        "received_at": timestamp,
        "bid": str(bid),
        "ask": str(ask),
        "status": "OPEN",
    }


def test_compare_ticks_runs_same_data_through_code_only_strategies():
    ticks = [
        _tick(0, 150.000, 150.002),
        _tick(1, 150.010, 150.012),
        _tick(2, 150.020, 150.022),
        _tick(3, 150.030, 150.032),
        _tick(4, 150.040, 150.042),
        _tick(5, 150.050, 150.052),
        _tick(6, 150.060, 150.062),
    ]
    results = compare_ticks(
        ticks,
        instrument_id="USD_JPY",
        strategies=("momentum", "ma_trend"),
    )
    assert set(results) == {"momentum", "ma_trend"}
    assert results["momentum"]["ticks"] == len(ticks)
    assert "net_pnl" in results["momentum"]
    assert "max_drawdown" in results["ma_trend"]
    assert results["momentum"]["supervisor"]["state"] in {
        "NORMAL",
        "CAUTION",
        "PAUSE_ENTRY",
        "PAUSE_ALL",
    }


def test_compare_ticks_rejects_jev_and_instrument_mismatch():
    with pytest.raises(ValueError, match="does not call Jev"):
        compare_ticks([], instrument_id="USD_JPY", strategies=("jev",))

    with pytest.raises(ValueError, match="instrument mismatch"):
        compare_ticks(
            [_tick(0, 150.0, 150.002, instrument="EUR_JPY")],
            instrument_id="USD_JPY",
            strategies=("momentum",),
        )


def test_read_and_compare_raw_jsonl(tmp_path: Path):
    path = tmp_path / "ticks.jsonl"
    rows = [
        _tick(0, 150.000, 150.002),
        _tick(1, 150.010, 150.012),
        _tick(2, 150.020, 150.022),
    ]
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    assert read_raw_ticks(path) == rows
    result = compare_raw_file(
        path,
        instrument_id="USD_JPY",
        strategies=("momentum",),
    )
    assert result["momentum"]["ticks"] == 3


def test_read_raw_ticks_reports_bad_line(tmp_path: Path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"ok": 1}\nnot-json\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad\.jsonl:2"):
        read_raw_ticks(path)


def test_compare_ticks_records_bar_input_mode():
    ticks = [
        _tick(second, 150.0 + second * 0.001, 150.002 + second * 0.001)
        for second in range(0, 31, 5)
    ]
    result = compare_ticks(
        ticks,
        instrument_id="USD_JPY",
        strategies=("ma_trend",),
        bar_seconds=5,
    )
    assert result["ma_trend"]["strategy_bar_seconds"] == 5
