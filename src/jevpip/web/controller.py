from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from statistics import fmean
import time
from typing import Any

from jevpip.backtest.kline import replay_kline
from jevpip.broker.paper import PaperBroker, PaperConfig
from jevpip.config import Settings
from jevpip.gmo.private_rest import GMOPrivateReadClient
from jevpip.observer import observe
from jevpip.signals import SignalPolicy


class UIController:
    """ローカルWeb UIからObserver、paper trading、口座参照を操作する。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._task: asyncio.Task[None] | None = None
        self._events: deque[dict[str, Any]] = deque(maxlen=120)
        self._chart: deque[dict[str, Any]] = deque(maxlen=900)
        self._status = "stopped"
        self._started_at: str | None = None
        self._profile_name: str | None = None
        self._signal_policy_name: str | None = None
        self._with_jev = False
        self._latest_market: dict[str, Any] | None = None
        self._latest_decision: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._paper: PaperBroker | None = None
        self._paper_config: PaperConfig | None = None
        self._real_account_cache: tuple[float, dict[str, Any]] | None = None

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
        paper_config: dict[str, Any] | None = None,
    ) -> None:
        if self.running:
            raise RuntimeError("観測はすでに実行中です。")

        jev_client = None
        if with_jev:
            if not self.settings.typesafe_api_key:
                raise ValueError("Jevを使うには .env に TYPESAFE_API_KEY を設定してください。")
            from jevpip.jev.client import JevClient

            jev_client = JevClient(self.settings.typesafe_api_key)

        if paper_config is not None:
            config = PaperConfig(**paper_config)
            if config.strategy == "jev" and not with_jev:
                raise ValueError("デモ戦略にJevを選ぶ場合は「Jevも使う」をONにしてください。")
            self._paper_config = config
            self._paper = PaperBroker(config)
        else:
            self._paper_config = None
            self._paper = None

        self._status = "running"
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._profile_name = profile_name
        self._signal_policy_name = signal_policy_name if with_jev else None
        self._with_jev = with_jev
        self._last_error = None
        self._latest_market = None
        self._latest_decision = None
        self._chart.clear()
        self._events.clear()

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
        kind = event.get("kind")
        if kind == "tick":
            self._latest_market = event
            bid = float(event["bid"])
            ask = float(event["ask"])
            self._chart.append(
                {
                    "timestamp": event["market_timestamp"],
                    "bid": bid,
                    "ask": ask,
                    "mid": (bid + ask) / 2,
                }
            )
            if self._paper is not None:
                for paper_event in self._paper.on_tick(event):
                    self._events.appendleft(paper_event)
        elif kind == "decision":
            self._latest_decision = event
            if self._paper is not None:
                self._paper.on_decision(event)
        elif kind == "error":
            self._last_error = str(event.get("message") or "不明なエラー")

        self._events.appendleft(event)

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

    def reset_paper(self) -> dict[str, Any]:
        if self._paper_config is None:
            raise RuntimeError("デモ口座は有効になっていません。")
        self._paper = PaperBroker(self._paper_config)
        return self._paper.snapshot()

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
            "chart": list(self._chart),
            "paper": None if self._paper is None else self._paper.snapshot(),
            "events": list(self._events)[:40],
        }

    async def fetch_real_account(self, *, force: bool = False) -> dict[str, Any]:
        if not self.settings.gmo_private_read_configured:
            raise ValueError(
                "実口座を表示するには .env に GMO_FX_API_KEY と GMO_FX_API_SECRET を設定してください。"
            )
        now = time.monotonic()
        if not force and self._real_account_cache is not None:
            cached_at, payload = self._real_account_cache
            if now - cached_at < 3.0:
                return payload

        assert self.settings.gmo_fx_api_key is not None
        assert self.settings.gmo_fx_api_secret is not None
        client = GMOPrivateReadClient(
            self.settings.gmo_fx_api_key,
            self.settings.gmo_fx_api_secret,
        )
        payload = await asyncio.to_thread(client.fetch_snapshot, "USD_JPY")
        payload["fetched_at"] = datetime.now(timezone.utc).isoformat()
        self._real_account_cache = (now, payload)
        return payload

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
