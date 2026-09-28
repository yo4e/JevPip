from __future__ import annotations

import asyncio
import csv
from datetime import date as calendar_date
import io
import json
from statistics import fmean
from typing import Any, Literal

from jevpip.backtest.kline import run_statistical_replay
from jevpip.backtest.spiritual import SpiritualBacktestConfig, run_spiritual_backtest
from jevpip.backtest.strategy import StrategyBacktestConfig, run_strategy_backtest
from jevpip.broker.comparison import compare_raw_file
from jevpip.config import Settings
from jevpip.instruments import get_instrument


ExportDataset = Literal["decision_traces", "fifty_outcomes"]
ExportFormat = Literal["csv", "jsonl"]
_EXPORT_DIRECTORIES: dict[ExportDataset, str] = {
    "decision_traces": "decision_traces",
    "fifty_outcomes": "fifty_outcomes",
}


class ResearchService:
    """Historical/research operations that do not depend on live UI state."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def raw_tick_dates(self, instrument_id: str) -> list[str]:
        get_instrument(instrument_id)
        directory = self.settings.data_dir / "raw_ticks" / instrument_id
        if not directory.exists():
            return []
        return sorted(
            (
                path.stem
                for path in directory.glob("*.jsonl")
                if path.is_file()
            ),
            reverse=True,
        )

    def export_dates(self, dataset: ExportDataset, instrument_id: str) -> list[str]:
        get_instrument(instrument_id)
        directory = self.settings.data_dir / _EXPORT_DIRECTORIES[dataset] / instrument_id
        if not directory.exists():
            return []
        return sorted(
            (path.stem for path in directory.glob("*.jsonl") if path.is_file()),
            reverse=True,
        )

    def export_research_data(
        self,
        *,
        dataset: ExportDataset,
        instrument_id: str,
        date: str,
        format: ExportFormat,
    ) -> tuple[str, str, str]:
        get_instrument(instrument_id)
        _validate_export_date(date)
        directory = self.settings.data_dir / _EXPORT_DIRECTORIES[dataset] / instrument_id
        path = directory / f"{date}.jsonl"
        if not path.is_file():
            raise ValueError(f"export data がありません: {dataset} / {instrument_id} / {date}")

        text = path.read_text(encoding="utf-8")
        filename = f"jevpip-{dataset}-{instrument_id}-{date}.{format}"
        if format == "jsonl":
            return text, "application/x-ndjson; charset=utf-8", filename

        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        flattened = [_flatten_export_row(row) for row in rows]
        if not flattened:
            return "", "text/csv; charset=utf-8", filename
        fieldnames = sorted({key for row in flattened for key in row})
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flattened)
        return output.getvalue(), "text/csv; charset=utf-8", filename

    async def compare_raw_date(
        self,
        *,
        instrument_id: str,
        date: str,
        strategies: tuple[str, ...],
        initial_balance: float,
        size: float | None,
        supervisor: bool,
        bar_seconds: int,
    ) -> dict[str, Any]:
        get_instrument(instrument_id)
        path = self.settings.data_dir / "raw_ticks" / instrument_id / f"{date}.jsonl"
        if not path.is_file():
            raise ValueError(f"raw tick data がありません: {instrument_id} / {date}")
        results = await asyncio.to_thread(
            compare_raw_file,
            path,
            instrument_id=instrument_id,
            strategies=strategies,
            initial_balance=initial_balance,
            size=size,
            supervisor=supervisor,
            bar_seconds=bar_seconds,
        )
        return {
            "instrument_id": instrument_id,
            "date": date,
            "source": str(path),
            "bar_seconds": bar_seconds,
            "supervisor": supervisor,
            "results": results,
        }

    async def run_strategy_backtest(
        self,
        *,
        date: str,
        instrument_id: str,
        config: dict[str, Any],
        limit: int | None,
    ) -> dict[str, Any]:
        get_instrument(instrument_id)
        parsed = StrategyBacktestConfig(**config)
        return await asyncio.to_thread(
            run_strategy_backtest,
            date=date,
            instrument_id=instrument_id,
            config=parsed,
            limit=limit,
        )

    async def run_spiritual_backtest(
        self,
        *,
        date: str,
        instrument_id: str,
        config: dict[str, Any],
        limit: int | None,
    ) -> dict[str, Any]:
        get_instrument(instrument_id)
        parsed = SpiritualBacktestConfig(**config)
        return await asyncio.to_thread(
            run_spiritual_backtest,
            date=date,
            instrument_id=instrument_id,
            config=parsed,
            limit=limit,
        )

    async def run_statistical_replay(
        self,
        *,
        date: str,
        instrument_id: str,
        profile_name: str,
        profile: dict[str, Any],
        limit: int | None,
    ) -> dict[str, Any]:
        slug = "".join(
            ch if ch.isalnum() or ch in "_-" else "_"
            for ch in profile_name
        )[:64] or "custom"
        get_instrument(instrument_id)
        output = self.settings.data_dir / "backtests" / f"{date}-{instrument_id}-{slug}.jsonl"
        rows = await asyncio.to_thread(
            run_statistical_replay,
            date,
            profile,
            output,
            limit,
            instrument_id,
        )
        return {
            "analysis_kind": "statistical_replay",
            "date": date,
            "instrument_id": instrument_id,
            "profile_name": profile_name,
            "output": str(output),
            "summary": summarize_statistical_replay(rows),
        }


def _validate_export_date(value: str) -> None:
    try:
        parsed = calendar_date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("export date は YYYY-MM-DD 形式で指定してください。") from exc
    if parsed.isoformat() != value:
        raise ValueError("export date は YYYY-MM-DD 形式で指定してください。")


def _flatten_export_row(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, item in value.items():
        name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, dict):
            flat.update(_flatten_export_row(item, name))
        elif isinstance(item, (list, tuple)):
            flat[name] = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        elif item is None or isinstance(item, (str, int, float, bool)):
            flat[name] = item
        else:
            flat[name] = str(item)
    return flat


def summarize_statistical_replay(rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = [
        row["outcome_1m"]
        for row in rows
        if row.get("outcome_1m") is not None
    ]
    mode = rows[0].get("replay_mode") if rows else None
    if not outcomes:
        return {
            "rows": len(rows),
            "outcomes": 0,
            "mode": mode,
            "mean_change_units": None,
            "max_change_units": None,
            "min_change_units": None,
            "mean_long_edge_units": None,
            "mean_short_edge_units": None,
            "long_positive_ratio": None,
            "short_positive_ratio": None,
            "up_ratio": None,
            "down_ratio": None,
        }

    changes = [float(item["delta_units"]) for item in outcomes]

    def mean_nullable(key: str) -> float | None:
        values = [float(item[key]) for item in outcomes if item.get(key) is not None]
        return None if not values else round(fmean(values), 6)

    long_values = [
        float(item["long_edge_units"])
        for item in outcomes
        if item.get("long_edge_units") is not None
    ]
    short_values = [
        float(item["short_edge_units"])
        for item in outcomes
        if item.get("short_edge_units") is not None
    ]

    return {
        "rows": len(rows),
        "outcomes": len(outcomes),
        "mode": mode,
        "mean_change_units": round(fmean(changes), 6),
        "max_change_units": round(max(changes), 6),
        "min_change_units": round(min(changes), 6),
        "mean_long_edge_units": mean_nullable("long_edge_units"),
        "mean_short_edge_units": mean_nullable("short_edge_units"),
        "long_positive_ratio": (
            None
            if not long_values
            else round(
                sum(value > 0 for value in long_values) / len(long_values),
                6,
            )
        ),
        "short_positive_ratio": (
            None
            if not short_values
            else round(
                sum(value > 0 for value in short_values) / len(short_values),
                6,
            )
        ),
        "up_ratio": round(sum(value > 0 for value in changes) / len(changes), 6),
        "down_ratio": round(sum(value < 0 for value in changes) / len(changes), 6),
    }
