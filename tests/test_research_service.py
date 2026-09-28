from __future__ import annotations

import asyncio
import csv
import io
import json
from pathlib import Path

import pytest

from jevpip.config import Settings
from jevpip.web import research_service as module
from jevpip.web.research_service import ResearchService


def test_raw_tick_dates_are_sorted_newest_first(tmp_path: Path):
    directory = tmp_path / "raw_ticks" / "USD_JPY"
    directory.mkdir(parents=True)
    (directory / "2026-09-19.jsonl").write_text("{}\n", encoding="utf-8")
    (directory / "2026-09-21.jsonl").write_text("{}\n", encoding="utf-8")
    (directory / "ignore.txt").write_text("x", encoding="utf-8")

    service = ResearchService(Settings(data_dir=tmp_path))

    assert service.raw_tick_dates("USD_JPY") == [
        "2026-09-21",
        "2026-09-19",
    ]


def test_export_dates_and_jsonl_passthrough(tmp_path: Path):
    directory = tmp_path / "decision_traces" / "USD_JPY"
    directory.mkdir(parents=True)
    source = '{"market":{"timestamp":"2026-09-28T09:00:00Z"},"direction":"UP"}\n'
    (directory / "2026-09-28.jsonl").write_text(source, encoding="utf-8")
    (directory / "2026-09-27.jsonl").write_text("{}\n", encoding="utf-8")

    service = ResearchService(Settings(data_dir=tmp_path))
    assert service.export_dates("decision_traces", "USD_JPY") == [
        "2026-09-28",
        "2026-09-27",
    ]

    content, media_type, filename = service.export_research_data(
        dataset="decision_traces",
        instrument_id="USD_JPY",
        date="2026-09-28",
        format="jsonl",
    )
    assert content == source
    assert media_type.startswith("application/x-ndjson")
    assert filename == "jevpip-decision_traces-USD_JPY-2026-09-28.jsonl"


def test_export_csv_flattens_nested_records_and_preserves_unicode(tmp_path: Path):
    directory = tmp_path / "fifty_outcomes" / "USD_JPY"
    directory.mkdir(parents=True)
    record = {
        "timestamp": "2026-09-28T09:00:00Z",
        "direction": "UP",
        "result": {"outcome": "take_profit_first", "pnl": 12.5},
        "tags": ["栗", "fifty"],
    }
    (directory / "2026-09-28.jsonl").write_text(
        json.dumps(record, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    service = ResearchService(Settings(data_dir=tmp_path))
    content, media_type, filename = service.export_research_data(
        dataset="fifty_outcomes",
        instrument_id="USD_JPY",
        date="2026-09-28",
        format="csv",
    )
    rows = list(csv.DictReader(io.StringIO(content)))
    assert rows == [{
        "direction": "UP",
        "result.outcome": "take_profit_first",
        "result.pnl": "12.5",
        "tags": '["栗","fifty"]',
        "timestamp": "2026-09-28T09:00:00Z",
    }]
    assert media_type.startswith("text/csv")
    assert filename == "jevpip-fifty_outcomes-USD_JPY-2026-09-28.csv"


def test_export_csv_empty_jsonl_returns_empty_file(tmp_path: Path):
    directory = tmp_path / "decision_traces" / "USD_JPY"
    directory.mkdir(parents=True)
    (directory / "2026-09-28.jsonl").write_text("", encoding="utf-8")

    service = ResearchService(Settings(data_dir=tmp_path))
    content, _, _ = service.export_research_data(
        dataset="decision_traces",
        instrument_id="USD_JPY",
        date="2026-09-28",
        format="csv",
    )
    assert content == ""


def test_export_rejects_non_iso_date_before_path_resolution(tmp_path: Path):
    service = ResearchService(Settings(data_dir=tmp_path))
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        service.export_research_data(
            dataset="decision_traces",
            instrument_id="USD_JPY",
            date="../../secrets",
            format="jsonl",
        )


def test_statistical_replay_uses_data_dir_and_explicit_analysis_kind(
    tmp_path: Path,
    monkeypatch,
):
    captured: dict[str, object] = {}

    def fake_run_statistical_replay(
        date,
        profile,
        output,
        limit,
        instrument_id,
    ):
        captured.update(
            date=date,
            profile=profile,
            output=output,
            limit=limit,
            instrument_id=instrument_id,
        )
        return [
            {
                "replay_mode": "fx_bid_ask_close",
                "outcome_1m": {
                    "delta_units": 1.0,
                    "long_edge_units": 0.5,
                    "short_edge_units": -1.5,
                },
            }
        ]

    monkeypatch.setattr(
        module,
        "run_statistical_replay",
        fake_run_statistical_replay,
    )

    result = asyncio.run(
        ResearchService(Settings(data_dir=tmp_path)).run_statistical_replay(
            date="20260921",
            instrument_id="USD_JPY",
            profile_name="test / UI",
            profile={"quote": True},
            limit=10,
        )
    )

    assert result["analysis_kind"] == "statistical_replay"
    assert result["summary"]["rows"] == 1
    assert result["summary"]["mean_change_units"] == 1.0
    assert captured["output"] == (
        tmp_path / "backtests" / "20260921-USD_JPY-test___UI.jsonl"
    )
    assert captured["instrument_id"] == "USD_JPY"
