from __future__ import annotations

import asyncio
from pathlib import Path

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
