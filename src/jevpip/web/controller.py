from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Any

from jevpip.backtest.kline import replay_kline
from jevpip.config import Settings
from jevpip.observer import observe
from jevpip.signals import SignalPolicy


class UIController:
    """ローカルWeb UIからObserverと粗いKLine replayを操作する。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._task: asyncio.Task[None] | None = None
        self._events: deque[dict[str, Any]] = deque(maxlen=100)
        self._status = "stopped"
        self._started_at: str | None = None
        self._profile_name: str | None = None
        self._signal_policy_name: str | None = None
        self._with_jev = False
        self._latest_market: dict[str, Any] | None = None
        self._latest_decision: dict[str, Any] | None = None
        self._last_error: str | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start_observer(
        self,
        *,
        profile_name: str,
        profile: dict[str, Any],
        with_jev: bool,
        jev_every_seconds: float,
        signal_policy_name: str,
        signal_policy: SignalPolicy,
    ) -> None:
        if self.running:
            raise RuntimeError("観測はすでに実行中です。")

        jev_client = None
        if with_jev:
            if not self.settings.typesafe_api_key:
                raise ValueError("Jevを使うには .env に TYPESAFE_API_KEY を設定してください。")
            from jevpip.jev.client import JevClient

            jev_client = JevClient(self.settings.typesafe_api_key)

        self._status = "running"
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._profile_name = profile_name
        self._signal_policy_name = signal_policy_name if with_jev else None
        self._with_jev = with_jev
        self._last_error = None
        self._latest_market = None
        self._latest_decision = None

        self._task = asyncio.create_task(
            observe(
                profile,
                self.settings.data_dir,
                jev_client,
                jev_every_seconds,
                None,
                signal_policy if with_jev else None,
                signal_policy_name if with_jev else None,
                on_update=self._on_update,
                emit_console=False,
            ),
            name="jevpip-ui-observer",
        )
        self._task.add_done_callback(self._observer_done)

    async def stop_observer(self) -> None:
        task = self._task
        if task is None or task.done():
            self._status = "stopped"
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            self._status = "stopped"
            self._task = None

    async def close(self) -> None:
        await self.stop_observer()

    async def _on_update(self, event: dict[str, Any]) -> None:
        self._events.appendleft(event)
        kind = event.get("kind")
        if kind == "tick":
            self._latest_market = event
        elif kind == "decision":
            self._latest_decision = event
        elif kind == "error":
            self._last_error = str(event.get("message") or "不明なエラー")

    def _observer_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            self._status = "stopped"
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            self._status = "stopped"
            return
        if exc is not None:
            self._status = "error"
            self._last_error = f"{type(exc).__name__}: {exc}"
        else:
            self._status = "stopped"

    def snapshot(self) -> dict[str, Any]:
        if self._task is not None and self._task.done() and self._status == "running":
            self._status = "stopped"
        return {
            "status": self._status,
            "running": self.running,
            "started_at": self._started_at,
            "profile_name": self._profile_name,
            "with_jev": self._with_jev,
            "signal_policy_name": self._signal_policy_name,
            "latest_market": self._latest_market,
            "latest_decision": self._latest_decision,
            "last_error": self._last_error,
            "events": list(self._events)[:30],
        }

    async def run_backtest(
        self,
        *,
        date: str,
        profile_name: str,
        profile: dict[str, Any],
        limit: int | None,
    ) -> dict[str, Any]:
        slug = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in profile_name)[:64] or "custom"
        output = self.settings.data_dir / "backtests" / f"{date}-{slug}.jsonl"
        rows = await asyncio.to_thread(
            replay_kline,
            date,
            profile,
            output,
            limit,
        )
        return {
            "date": date,
            "profile_name": profile_name,
            "output": str(output),
            "summary": summarize_backtest(rows),
        }


def summarize_backtest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = [row["outcome_1m"] for row in rows if row.get("outcome_1m") is not None]
    if not outcomes:
        return {
            "rows": len(rows),
            "outcomes": 0,
            "mean_delta_mid_pips": None,
            "mean_long_edge_pips": None,
            "mean_short_edge_pips": None,
            "long_positive_ratio": None,
            "short_positive_ratio": None,
        }

    def mean(key: str) -> float:
        return round(fmean(float(item[key]) for item in outcomes), 6)

    return {
        "rows": len(rows),
        "outcomes": len(outcomes),
        "mean_delta_mid_pips": mean("delta_mid_pips"),
        "mean_long_edge_pips": mean("long_edge_pips"),
        "mean_short_edge_pips": mean("short_edge_pips"),
        "long_positive_ratio": round(
            sum(float(item["long_edge_pips"]) > 0 for item in outcomes) / len(outcomes),
            6,
        ),
        "short_positive_ratio": round(
            sum(float(item["short_edge_pips"]) > 0 for item in outcomes) / len(outcomes),
            6,
        ),
    }
