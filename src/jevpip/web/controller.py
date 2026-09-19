from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from statistics import fmean
import time
from typing import Any

from jevpip.backtest.kline import replay_kline
from jevpip.backtest.strategy import StrategyBacktestConfig, run_strategy_backtest
from jevpip.broker.comparison import compare_raw_file
from jevpip.broker.paper import PaperBroker, PaperConfig
from jevpip.broker.supervisor import SupervisorDecision, deterministic_event_supervisor
from jevpip.config import Settings
from jevpip.context import ExternalContextItem
from jevpip.context_log import append_context_fetch
from jevpip.context_sources import fetch_bls_events, fetch_boj_events, fetch_fed_events
from jevpip.gmo.history import fetch_history
from jevpip.gmo.private_rest import GMOPrivateReadClient
from jevpip.instruments import get_instrument
from jevpip.observer import observe
from jevpip.signals import SignalPolicy


class UIController:
    """ローカルWeb UIからObserver、paper trading、口座参照を操作する。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._task: asyncio.Task[None] | None = None
        self._context_task: asyncio.Task[None] | None = None
        self._events: deque[dict[str, Any]] = deque(maxlen=120)
        self._chart: deque[dict[str, Any]] = deque(maxlen=900)
        self._status = "stopped"
        self._started_at: str | None = None
        self._instrument_id = "USD_JPY"
        self._profile_name: str | None = None
        self._signal_policy_name: str | None = None
        self._with_jev = False
        self._latest_market: dict[str, Any] | None = None
        self._latest_decision: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._paper: PaperBroker | None = None
        self._paper_config: PaperConfig | None = None
        self._real_account_cache: tuple[float, dict[str, Any]] | None = None
        self._external_context_items: tuple[ExternalContextItem, ...] = ()
        self._external_context_fetched_at: datetime | None = None
        self._external_context_error: str | None = None
        self._event_supervisor = SupervisorDecision("NORMAL", "event_not_loaded", True)

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def start_observer(
        self,
        *,
        instrument_id: str,
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

        instrument = get_instrument(instrument_id)
        await self.refresh_external_context(instrument.id)

        jev_client = None
        if with_jev:
            if not self.settings.typesafe_api_key:
                raise ValueError("Jevを使うには .env に TYPESAFE_API_KEY を設定してください。")
            from jevpip.jev.client import JevClient

            jev_client = JevClient(self.settings.typesafe_api_key)

        if paper_config is not None:
            normalized = dict(paper_config)
            normalized["price_unit"] = float(instrument.price_unit)
            normalized["move_unit_label"] = instrument.move_unit_label
            normalized["fee_rate"] = float(instrument.paper_fee_rate)
            normalized["fee_label"] = instrument.paper_fee_label
            normalized["short_is_synthetic"] = instrument.paper_short_is_synthetic
            config = PaperConfig(**normalized)
            if config.strategy == "jev" and not with_jev:
                raise ValueError("デモ戦略にJevを選ぶ場合は「Jevも使う」をONにしてください。")
            self._paper_config = config
            self._paper = PaperBroker(config)
        else:
            self._paper_config = None
            self._paper = None

        self._status = "running"
        self._started_at = datetime.now(timezone.utc).isoformat()
        self._instrument_id = instrument.id
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
                instrument_id=instrument.id,
                on_update=self._on_update,
                emit_console=False,
            ),
            name=f"jevpip-ui-observer-{instrument.id}",
        )
        self._task.add_done_callback(self._observer_done)
        self._context_task = asyncio.create_task(
            self._context_refresh_loop(instrument.id),
            name=f"jevpip-context-refresh-{instrument.id}",
        )
        self._context_task.add_done_callback(self._context_refresh_done)

    async def _stop_context_refresh(self) -> None:
        task = self._context_task
        if task is None:
            return
        self._context_task = None
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def stop_observer(self) -> None:
        await self._stop_context_refresh()
        task = self._task
        if task is None or task.done():
            self._status = "stopped"
            self._task = None
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
                at = self._parse_timestamp(str(event["market_timestamp"]))
                self._update_event_supervisor(at, self._instrument_id)
                for paper_event in self._paper.on_tick(
                    event,
                    allow_entry=self._event_supervisor.allow_entry,
                ):
                    self._events.appendleft(paper_event)
        elif kind == "decision":
            self._latest_decision = event
            if self._paper is not None:
                self._paper.on_decision(event)
        elif kind == "error":
            self._last_error = str(event.get("message") or "不明なエラー")

        self._events.appendleft(event)

    def _observer_done(self, task: asyncio.Task[None]) -> None:
        if self._context_task is not None and not self._context_task.done():
            self._context_task.cancel()
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

    def _context_refresh_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            return
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            message = f"context_refresh:{type(exc).__name__}: {exc}"
            self._external_context_error = (
                message
                if not self._external_context_error
                else f"{self._external_context_error}; {message}"
            )

    async def _context_refresh_loop(self, instrument_id: str) -> None:
        interval = max(60.0, float(self.settings.context_refresh_seconds))
        while True:
            await asyncio.sleep(interval)
            await self.refresh_external_context(instrument_id)

    def reset_paper(self) -> dict[str, Any]:
        if self._paper_config is None:
            raise RuntimeError("デモ口座は有効になっていません。")
        self._paper = PaperBroker(self._paper_config)
        return self._paper.snapshot()

    def snapshot(self) -> dict[str, Any]:
        if self._task is not None and self._task.done() and self._status == "running":
            self._status = "stopped"
        now = datetime.now(timezone.utc)
        if self.running and self._paper is not None:
            self._paper.heartbeat(now)
        self._update_event_supervisor(now, self._instrument_id)
        return {
            "status": self._status,
            "running": self.running,
            "started_at": self._started_at,
            "instrument_id": self._instrument_id,
            "profile_name": self._profile_name,
            "with_jev": self._with_jev,
            "signal_policy_name": self._signal_policy_name,
            "latest_market": self._latest_market,
            "latest_decision": self._latest_decision,
            "last_error": self._last_error,
            "chart": list(self._chart),
            "paper": None if self._paper is None else self._paper.snapshot(),
            "external_context": self._external_context_snapshot(now, self._instrument_id),
            "events": list(self._events)[:40],
        }

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _context_currencies(instrument_id: str) -> tuple[str, ...]:
        if instrument_id == "BTC":
            # Macro USD events are intentionally part of the first BTC experiment.
            return ("USD", "JPY")
        if "_" in instrument_id:
            return tuple(part.upper() for part in instrument_id.split("_") if part)
        return ("JPY",)

    def _relevant_external_context(
        self,
        instrument_id: str,
    ) -> tuple[ExternalContextItem, ...]:
        currencies = self._context_currencies(instrument_id)
        return tuple(
            item
            for item in self._external_context_items
            if item.relevant_to(
                instrument_id=instrument_id,
                currencies=currencies,
            )
        )

    def _update_event_supervisor(self, as_of: datetime, instrument_id: str) -> None:
        if (
            self._paper_config is not None
            and not self._paper_config.deterministic_supervisor_enabled
        ):
            self._event_supervisor = SupervisorDecision(
                "NORMAL",
                "event_supervisor_disabled",
                True,
            )
            return
        self._event_supervisor = deterministic_event_supervisor(
            self._relevant_external_context(instrument_id),
            as_of=as_of,
        )

    def _external_context_snapshot(
        self,
        as_of: datetime,
        instrument_id: str,
    ) -> dict[str, Any]:
        relevant = self._relevant_external_context(instrument_id)
        upcoming = [
            item
            for item in relevant
            if item.scheduled_at is not None
            and item.scheduled_at >= as_of - timedelta(minutes=15)
        ][:8]
        return {
            "fetched_at": (
                None
                if self._external_context_fetched_at is None
                else self._external_context_fetched_at.isoformat()
            ),
            "error": self._external_context_error,
            "supervisor": {
                "state": self._event_supervisor.state,
                "reason": self._event_supervisor.reason,
                "allow_entry": self._event_supervisor.allow_entry,
            },
            "events": [
                {
                    "source": item.source,
                    "source_id": item.source_id,
                    "title": item.title,
                    "risk": item.risk,
                    "scheduled_at": (
                        None if item.scheduled_at is None else item.scheduled_at.isoformat()
                    ),
                    "source_url": item.source_url,
                }
                for item in upcoming
            ],
        }

    async def refresh_external_context(
        self,
        instrument_id: str | None = None,
    ) -> dict[str, Any]:
        target = instrument_id or self._instrument_id
        get_instrument(target)
        observed_at = datetime.now(timezone.utc)

        fetchers = {
            "bls": fetch_bls_events,
            "boj": fetch_boj_events,
            "fed": fetch_fed_events,
        }
        results = await asyncio.gather(
            *(
                asyncio.to_thread(fetcher, observed_at)
                for fetcher in fetchers.values()
            ),
            return_exceptions=True,
        )

        by_source: dict[str, tuple[ExternalContextItem, ...]] = {}
        for item in self._external_context_items:
            by_source.setdefault(item.source, ())
            by_source[item.source] = (*by_source[item.source], item)

        errors: list[str] = []
        for (source, _fetcher), result in zip(fetchers.items(), results, strict=True):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                error = f"{type(result).__name__}: {result}"
                errors.append(f"{source}:{error}")
                try:
                    await asyncio.to_thread(
                        append_context_fetch,
                        self.settings.data_dir,
                        source=source,
                        observed_at=observed_at,
                        error=error,
                    )
                except Exception as log_exc:
                    errors.append(
                        f"context_log:{source}:{type(log_exc).__name__}: {log_exc}"
                    )
                continue

            source_items = tuple(result)
            by_source[source] = source_items
            try:
                await asyncio.to_thread(
                    append_context_fetch,
                    self.settings.data_dir,
                    source=source,
                    observed_at=observed_at,
                    events=source_items,
                )
            except Exception as log_exc:
                errors.append(
                    f"context_log:{source}:{type(log_exc).__name__}: {log_exc}"
                )

        merged = [
            item
            for source_items in by_source.values()
            for item in source_items
        ]
        self._external_context_items = tuple(
            sorted(
                merged,
                key=lambda item: item.scheduled_at
                or item.published_at
                or item.observed_at,
            )
        )
        if any(not isinstance(result, BaseException) for result in results):
            self._external_context_fetched_at = observed_at
        self._external_context_error = "; ".join(errors) if errors else None

        self._update_event_supervisor(observed_at, target)
        return self._external_context_snapshot(observed_at, target)

    async def fetch_chart_history(
        self,
        *,
        instrument_id: str,
        interval: str,
        date: str,
    ) -> dict[str, Any]:
        instrument = get_instrument(instrument_id)
        requested = datetime.strptime(date, "%Y%m%d")

        # Keep the visible candle count roughly stable, so a larger timeframe
        # naturally shows a longer time span instead of repainting the same
        # single day with fewer candles.
        target_candles = 180
        max_lookback_days = {
            "1min": 8,
            "5min": 8,
            "15min": 10,
            "1hour": 18,
        }[interval]

        by_open_time: dict[int, Any] = {}
        used_dates: list[str] = []
        empty_streak = 0
        for days_back in range(max_lookback_days):
            candidate = requested - timedelta(days=days_back)
            candidate_date = candidate.strftime("%Y%m%d")
            rows = await asyncio.to_thread(
                fetch_history,
                instrument_id,
                candidate_date,
                interval,
            )
            if rows:
                used_dates.append(candidate_date)
                empty_streak = 0
                for item in rows:
                    by_open_time[item.open_time_ms] = item
            else:
                empty_streak += 1

            if len(by_open_time) >= target_candles:
                break

            # Crypto trades continuously, so repeated empty dates usually mean
            # the requested history is unavailable. FX may legitimately have a
            # weekend/holiday gap, therefore give it more room.
            if instrument.market_kind == "crypto_spot" and empty_streak >= 2:
                break

        rows = sorted(by_open_time.values(), key=lambda item: item.open_time_ms)
        rows = rows[-target_candles:]

        return {
            "instrument_id": instrument_id,
            "interval": interval,
            "date": date,
            "dates": sorted(used_dates),
            "target_candles": target_candles,
            "candles": [
                {
                    "timestamp": datetime.fromtimestamp(
                        item.open_time_ms / 1000,
                        tz=timezone.utc,
                    ).isoformat(),
                    "open": float(item.open),
                    "high": float(item.high),
                    "low": float(item.low),
                    "close": float(item.close),
                }
                for item in rows
            ],
        }

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
        result = await asyncio.to_thread(
            run_strategy_backtest,
            date=date,
            instrument_id=instrument_id,
            config=parsed,
            limit=limit,
        )
        return result

    async def run_backtest(
        self,
        *,
        date: str,
        instrument_id: str,
        profile_name: str,
        profile: dict[str, Any],
        limit: int | None,
    ) -> dict[str, Any]:
        slug = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in profile_name)[:64] or "custom"
        instrument = get_instrument(instrument_id)
        output = self.settings.data_dir / "backtests" / f"{date}-{instrument_id}-{slug}.jsonl"
        rows = await asyncio.to_thread(
            replay_kline,
            date,
            profile,
            output,
            limit,
            instrument_id,
        )
        return {
            "date": date,
            "instrument_id": instrument_id,
            "profile_name": profile_name,
            "output": str(output),
            "summary": summarize_backtest(rows),
        }


def summarize_backtest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = [row["outcome_1m"] for row in rows if row.get("outcome_1m") is not None]
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
            else round(sum(value > 0 for value in long_values) / len(long_values), 6)
        ),
        "short_positive_ratio": (
            None
            if not short_values
            else round(sum(value > 0 for value in short_values) / len(short_values), 6)
        ),
        "up_ratio": round(sum(value > 0 for value in changes) / len(changes), 6),
        "down_ratio": round(sum(value < 0 for value in changes) / len(changes), 6),
    }

