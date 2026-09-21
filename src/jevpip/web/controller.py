from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from threading import Event
import time
from typing import Any
from uuid import uuid4

import httpx

from jevpip.broker.paper import PaperBroker, PaperConfig
from jevpip.broker.autopilot import AutopilotBroker, make_paper_broker
from jevpip.async_work import joined_thread
from jevpip.broker.supervisor import (
    JevSupervisorAdvice,
    SupervisorDecision,
    combine_supervisors,
    deterministic_event_supervisor,
    validate_jev_supervisor_payload,
)
from jevpip.config import Settings
from jevpip.context import ExternalContextItem, select_context, to_jev_context_state
from jevpip.context_log import append_context_fetch
from jevpip.context_sources import fetch_bls_events, fetch_boj_events, fetch_fed_events
from jevpip.decision_trace import append_decision_trace, build_decision_trace
from jevpip.gmo.history import fetch_history
from jevpip.gmo.private_rest import GMOPrivateReadClient
from jevpip.gmo.public_rest import fetch_public_ticker
from jevpip.instruments import get_instrument
from jevpip.jev_replay import (
    preview_jev_replay as build_jev_replay_preview,
    run_jev_historical_replay,
)
from jevpip.observer import observe
from jevpip.signals import SignalPolicy
from jevpip.web.research_service import ResearchService, summarize_statistical_replay


class UIController:
    """ローカルWeb UIからObserver、paper trading、口座参照を操作する。"""

    def __init__(self, settings: Settings | None = None) -> None:
        self._jev_replay_running = False
        self._observer_starting = False
        self.settings = settings or Settings()
        self._research = ResearchService(self.settings.data_dir)
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
        self._session_config: dict[str, Any] | None = None
        self._latest_market: dict[str, Any] | None = None
        self._latest_decision: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._paper: PaperBroker | None = None
        self._paper_config: PaperConfig | None = None
        self._trace_run_id: str | None = None
        self._trace_run_config: dict[str, Any] | None = None
        self._last_decision_trace: dict[str, Any] | None = None
        self._real_account_cache: tuple[float, dict[str, Any]] | None = None
        self._public_quote_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._external_context_items: tuple[ExternalContextItem, ...] = ()
        self._external_context_fetched_at: datetime | None = None
        self._external_context_error: str | None = None
        self._event_supervisor = SupervisorDecision("NORMAL", "event_not_loaded", True)
        self._jev_supervisor_advice: JevSupervisorAdvice | None = None
        self._jev_supervisor_available_at: datetime | None = None
        self._jev_supervisor_expires_at: datetime | None = None
        self._jev_supervisor_error: str | None = None
        self._jev_usage_calls = 0
        self._jev_usage_reported_calls = 0
        self._jev_usage_input_tokens = 0
        self._jev_usage_output_tokens = 0
        self._jev_usage_latest: dict[str, int | None] = {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }

    @property
    def running(self) -> bool:
        return self._observer_starting or (self._task is not None and not self._task.done())

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
        if self.running or self._jev_replay_running:
            raise RuntimeError("観測はすでに実行中です。")

        self._observer_starting = True
        try:
            instrument = get_instrument(instrument_id)
            await self.refresh_external_context(instrument.id)

            jev_client = None
            jev_supervisor_strategies: tuple[str, ...] = ()
            if with_jev:
                if not self.settings.typesafe_api_key:
                    raise ValueError("Jevを使うには .env に TYPESAFE_API_KEY を設定してください。")
                from jevpip.jev.client import JevClient

                jev_client = JevClient(self.settings.typesafe_api_key)

            if paper_config is not None:
                normalized = dict(paper_config)
                normalized["instrument_id"] = instrument.id
                if normalized.get("autopilot_enabled"):
                    oracle = normalized.get("autopilot_fifty_oracle", "jev")
                    if oracle == "jev" and not with_jev:
                        raise ValueError("JevモードにはJevをONにしてください。")
                    if oracle != "jev" and with_jev:
                        raise ValueError("スピリチュアルFifty+ではJevを同時に使えません。")
                    normalized["strategy_enabled"] = False
                normalized["price_unit"] = float(instrument.price_unit)
                normalized["move_unit_label"] = instrument.move_unit_label
                normalized["fee_rate"] = float(instrument.paper_fee_rate)
                normalized["fee_label"] = instrument.paper_fee_label
                normalized["short_is_synthetic"] = instrument.paper_short_is_synthetic

                legacy_jev_strategy = normalized.get("strategy") == "jev"
                if legacy_jev_strategy and not with_jev:
                    raise ValueError("デモ戦略にJevを選ぶ場合は「Jevも使う」をONにしてください。")
                if legacy_jev_strategy:
                    normalized["strategy"] = "momentum"
                    normalized["strategy_enabled"] = False

                strategy_enabled = bool(normalized.get("strategy_enabled", True))
                normalized["strategy_enabled"] = strategy_enabled
                normalized["jev_direct_enabled"] = bool(with_jev and not strategy_enabled)
                normalized["jev_direction_gate_enabled"] = bool(
                    with_jev
                    and strategy_enabled
                )
                config = PaperConfig(**normalized)
                self._paper_config = config
                self._paper = make_paper_broker(config)
                if (
                    with_jev
                    and config.strategy_enabled
                    and config.deterministic_supervisor_enabled
                ):
                    jev_supervisor_strategies = (
                        "momentum",
                        "rsi_mean_reversion",
                        "ma_trend",
                    )
            else:
                self._paper_config = None
                self._paper = None

            self._status = "running"
            self._started_at = datetime.now(timezone.utc).isoformat()
            self._instrument_id = instrument.id
            self._profile_name = profile_name
            self._signal_policy_name = signal_policy_name if with_jev else None
            self._with_jev = with_jev
            # Public start-time settings let a reloaded UI describe the running
            # session faithfully. Credentials never enter this payload.
            self._session_config = {
                "profile": dict(profile),
                "signal_policy": asdict(signal_policy),
                "jev_every_seconds": jev_every_seconds,
            }
            self._trace_run_id = uuid4().hex if self._paper is not None else None
            self._trace_run_config = (
                None
                if self._paper_config is None
                else {
                    "started_at": self._started_at,
                    "profile_name": profile_name,
                    "with_jev": with_jev,
                    "signal_policy_name": (
                        signal_policy_name if with_jev else None
                    ),
                    "paper": asdict(self._paper_config),
                }
            )
            self._last_decision_trace = None
            self._last_error = None
            self._latest_market = None
            self._latest_decision = None
            self._jev_supervisor_advice = None
            self._jev_supervisor_available_at = None
            self._jev_supervisor_expires_at = None
            self._jev_supervisor_error = None
            self._reset_jev_usage()
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
                    jev_state_context_provider=(
                        self._jev_state_context if with_jev else None
                    ),
                    jev_supervisor_strategies=jev_supervisor_strategies,
                ),
                name=f"jevpip-ui-observer-{instrument.id}",
            )
            self._task.add_done_callback(self._observer_done)
            self._context_task = asyncio.create_task(
                self._context_refresh_loop(instrument.id),
                name=f"jevpip-context-refresh-{instrument.id}",
            )
            self._context_task.add_done_callback(self._context_refresh_done)
        finally:
            self._observer_starting = False

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
                decision_clock = self._parse_timestamp(
                    str(event.get("received_at") or event["market_timestamp"])
                )
                self._update_event_supervisor(at, self._instrument_id)
                jev_advice = self._active_jev_supervisor(decision_clock)
                supervisor_plan = combine_supervisors(
                    self._event_supervisor,
                    jev_advice,
                )
                for paper_event in self._paper.on_tick(
                    event,
                    allow_entry=supervisor_plan.allow_entry,
                    strategy_override=supervisor_plan.strategy,
                    entry_gate_reason=supervisor_plan.reason,
                ):
                    self._events.appendleft(paper_event)

                broker_trace = self._paper.last_decision_trace
                if (
                    broker_trace is not None
                    and self._trace_run_id is not None
                    and self._trace_run_config is not None
                ):
                    jev_supervisor_trace = (
                        None
                        if jev_advice is None
                        else {
                            **asdict(jev_advice),
                            "available_at": (
                                None
                                if self._jev_supervisor_available_at is None
                                else self._jev_supervisor_available_at.isoformat()
                            ),
                            "expires_at": (
                                None
                                if self._jev_supervisor_expires_at is None
                                else self._jev_supervisor_expires_at.isoformat()
                            ),
                        }
                    )
                    paper_snapshot = self._paper.snapshot()
                    trace = build_decision_trace(
                        run_id=self._trace_run_id,
                        instrument_id=self._instrument_id,
                        recorded_at=datetime.now(timezone.utc).isoformat(),
                        run_config=self._trace_run_config,
                        cost_model=dict(paper_snapshot["cost_model"]),
                        broker_trace=broker_trace,
                        event_supervisor=asdict(self._event_supervisor),
                        jev_supervisor=jev_supervisor_trace,
                        combined_supervisor=asdict(supervisor_plan),
                    )
                    append_decision_trace(self.settings.data_dir, trace)
                    self._last_decision_trace = trace
        elif kind == "decision":
            self._latest_decision = event
            self._record_jev_usage(event)
            if self._paper is not None:
                self._paper.on_decision(event)
                if (
                    isinstance(self._paper, AutopilotBroker)
                    and self._paper.config.autopilot_style == "fifty"
                    and event.get("available_at")
                ):
                    available_at = self._parse_timestamp(str(event["available_at"]))
                    for paper_event in self._paper.execute_fifty_pending(available_at):
                        self._events.appendleft(paper_event)
            self._update_jev_supervisor(event)
        elif kind == "error":
            self._last_error = str(event.get("message") or "不明なエラー")
            if isinstance(self._paper, AutopilotBroker):
                self._paper.on_decision({"target_error": "api_error"})

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
        self._paper = make_paper_broker(self._paper_config)
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
            "session_config": self._session_config,
            "signal_policy_name": self._signal_policy_name,
            "latest_market": self._latest_market,
            "latest_decision": self._latest_decision,
            "latest_decision_trace": self._last_decision_trace,
            "last_error": self._last_error,
            "chart": list(self._chart),
            "paper": None if self._paper is None else self._paper.snapshot(),
            "external_context": self._external_context_snapshot(now, self._instrument_id),
            "jev_supervisor": self._jev_supervisor_snapshot(now),
            "jev_usage": self._jev_usage_snapshot(),
            "events": list(self._events)[:40],
        }

    @staticmethod
    def _parse_timestamp(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _supervisor_strategies() -> tuple[str, ...]:
        return ("momentum", "rsi_mean_reversion", "ma_trend")

    def _jev_context_state(
        self,
        as_of: datetime,
        instrument_id: str,
    ) -> dict[str, Any]:
        selected = select_context(
            self._external_context_items,
            as_of=as_of,
            instrument_id=instrument_id,
            currencies=self._context_currencies(instrument_id),
        )
        return to_jev_context_state(selected, as_of=as_of)

    def _jev_state_context(
        self,
        as_of: datetime,
        instrument_id: str,
    ) -> dict[str, Any]:
        """Context visible to Jev without exposing account credentials or commands."""

        if isinstance(self._paper, AutopilotBroker):
            state = self._paper.decision_state(as_of)
            if self._paper.config.autopilot_fundamentals:
                state.update(self._jev_context_state(as_of, instrument_id))
            return state
        state = self._jev_context_state(as_of, instrument_id)
        if self._paper is None or self._paper_config is None:
            return state

        snapshot = self._paper.snapshot()
        position = snapshot.get("position")
        position_state: dict[str, Any] | None = None
        if isinstance(position, dict):
            opened_raw = position.get("opened_at")
            age_seconds: float | None = None
            if opened_raw:
                try:
                    opened_at = self._parse_timestamp(str(opened_raw))
                    age_seconds = round(max(0.0, (as_of - opened_at).total_seconds()), 3)
                except (TypeError, ValueError):
                    age_seconds = None
            position_state = {
                "side": position.get("side"),
                "opened_at": position.get("opened_at"),
                "age_seconds": age_seconds,
                "position_horizon_seconds": self._paper_config.max_hold_seconds,
                "minimum_hold_seconds": self._paper_config.jev_position_min_hold_seconds,
            }

        strategy_decision = snapshot.get("strategy_decision")
        state["paper_context"] = {
            "strategy_enabled": self._paper_config.strategy_enabled,
            "configured_strategy": (
                self._paper_config.strategy
                if self._paper_config.strategy_enabled
                else None
            ),
            "jev_direct_enabled": self._paper_config.jev_direct_enabled,
            "jev_direction_gate_enabled": self._paper_config.jev_direction_gate_enabled,
            "latest_strategy_decision": (
                {
                    "signal": strategy_decision.get("signal"),
                    "reason": strategy_decision.get("reason"),
                }
                if isinstance(strategy_decision, dict)
                else None
            ),
            "position": position_state,
        }
        return state

    @staticmethod
    def _usage_token(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    def _reset_jev_usage(self) -> None:
        self._jev_usage_calls = 0
        self._jev_usage_reported_calls = 0
        self._jev_usage_input_tokens = 0
        self._jev_usage_output_tokens = 0
        self._jev_usage_latest = {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }

    def _record_jev_usage(self, event: dict[str, Any]) -> None:
        jev = event.get("jev")
        if not isinstance(jev, dict):
            return
        self._jev_usage_calls += 1
        usage = jev.get("usage")
        if not isinstance(usage, dict):
            self._jev_usage_latest = {
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
            }
            return

        input_tokens = self._usage_token(usage.get("input_tokens"))
        output_tokens = self._usage_token(usage.get("output_tokens"))
        if input_tokens is not None or output_tokens is not None:
            self._jev_usage_reported_calls += 1
        if input_tokens is not None:
            self._jev_usage_input_tokens += input_tokens
        if output_tokens is not None:
            self._jev_usage_output_tokens += output_tokens
        self._jev_usage_latest = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": (
                None
                if input_tokens is None or output_tokens is None
                else input_tokens + output_tokens
            ),
        }

    def _jev_usage_snapshot(self) -> dict[str, Any]:
        return {
            "calls": self._jev_usage_calls,
            "reported_calls": self._jev_usage_reported_calls,
            "input_tokens": self._jev_usage_input_tokens,
            "output_tokens": self._jev_usage_output_tokens,
            "total_tokens": self._jev_usage_input_tokens + self._jev_usage_output_tokens,
            "latest": dict(self._jev_usage_latest),
        }

    def _update_jev_supervisor(self, event: dict[str, Any]) -> None:
        if (
            not self._with_jev
            or self._paper_config is None
            or not self._paper_config.strategy_enabled
            or self._paper_config.strategy == "jev"
            or not self._paper_config.deterministic_supervisor_enabled
        ):
            return

        raw = event.get("jev_supervisor")
        if not isinstance(raw, dict):
            error = event.get("jev_supervisor_error")
            if error:
                self._jev_supervisor_error = str(error)
            return

        try:
            advice = validate_jev_supervisor_payload(
                raw,
                allowed_strategies=self._supervisor_strategies(),
            )
            raw_at = event.get("recorded_at") or event.get("market_timestamp")
            if not raw_at:
                raise ValueError("Jev supervisor decision timestamp is required")
            raw_requested = event.get("requested_at") or raw_at
            raw_available = event.get("available_at") or raw_at
            requested_at = self._parse_timestamp(str(raw_requested))
            available_at = self._parse_timestamp(str(raw_available))
        except Exception as exc:
            self._jev_supervisor_error = f"{type(exc).__name__}: {exc}"
            return

        self._jev_supervisor_advice = advice
        self._jev_supervisor_available_at = available_at
        self._jev_supervisor_expires_at = requested_at + timedelta(
            seconds=advice.ttl_seconds
        )
        self._jev_supervisor_error = None

    def _active_jev_supervisor(
        self,
        as_of: datetime,
    ) -> JevSupervisorAdvice | None:
        advice = self._jev_supervisor_advice
        available_at = self._jev_supervisor_available_at
        expires_at = self._jev_supervisor_expires_at
        if advice is None or available_at is None or expires_at is None:
            return None

        at = (
            as_of
            if as_of.tzinfo is not None
            else as_of.replace(tzinfo=timezone.utc)
        ).astimezone(timezone.utc)
        if at < available_at:
            return None
        if at > expires_at:
            self._jev_supervisor_advice = None
            self._jev_supervisor_available_at = None
            self._jev_supervisor_expires_at = None
            return None
        return advice

    def _jev_supervisor_snapshot(self, as_of: datetime) -> dict[str, Any]:
        advice = self._active_jev_supervisor(as_of)
        enabled = bool(
            self._with_jev
            and self._paper_config is not None
            and self._paper_config.strategy_enabled
            and self._paper_config.strategy != "jev"
            and self._paper_config.deterministic_supervisor_enabled
        )
        return {
            "enabled": enabled,
            "active": advice is not None,
            "available_at": (
                None
                if advice is None or self._jev_supervisor_available_at is None
                else self._jev_supervisor_available_at.isoformat()
            ),
            "expires_at": (
                None
                if advice is None or self._jev_supervisor_expires_at is None
                else self._jev_supervisor_expires_at.isoformat()
            ),
            "error": self._jev_supervisor_error,
            "advice": (
                None
                if advice is None
                else {
                    "state": advice.state,
                    "strategy": advice.strategy,
                    "confidence": advice.confidence,
                    "ttl_seconds": advice.ttl_seconds,
                    "reason": advice.reason,
                }
            ),
        }

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
            isinstance(self._paper, AutopilotBroker)
            and self._paper.config.autopilot_fifty_oracle == "jev"
        ):
            self._event_supervisor = SupervisorDecision(
                "NORMAL", "jev_owns_event_judgment", True
            )
            return
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

    async def fetch_public_quote(
        self,
        instrument_id: str,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """Return a non-trading Public REST quote for the stopped UI."""
        instrument = get_instrument(instrument_id)
        now = time.monotonic()
        cached = self._public_quote_cache.get(instrument.id)
        if not force and cached is not None and now - cached[0] < 3.0:
            return dict(cached[1])

        ticker = await asyncio.to_thread(fetch_public_ticker, instrument.id)
        payload = {
            "instrument_id": instrument.id,
            "display_symbol": instrument.display_symbol,
            "bid": float(ticker.bid),
            "ask": float(ticker.ask),
            "spread_units": float((ticker.ask - ticker.bid) / instrument.price_unit),
            "move_unit_label": instrument.move_unit_label,
            "market_timestamp": ticker.timestamp,
            "status": ticker.status,
            "source": "public_rest_preview",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        self._public_quote_cache[instrument.id] = (now, payload)
        return dict(payload)

    async def fetch_chart_history(
        self,
        *,
        instrument_id: str,
        interval: str,
        date: str,
        warmup: bool = False,
    ) -> dict[str, Any]:
        instrument = get_instrument(instrument_id)
        requested = datetime.strptime(date, "%Y%m%d")

        # Keep the visible candle count roughly stable, so a larger timeframe
        # naturally shows a longer time span instead of repainting the same
        # single day with fewer candles.
        target_candles = 379 if warmup else 180
        max_lookback_days = {
            "1min": 8,
            "5min": 8,
            "15min": 10,
            "1hour": 32 if warmup else 18,
        }[interval]

        by_open_time: dict[int, Any] = {}
        used_dates: list[str] = []
        empty_streak = 0
        for days_back in range(max_lookback_days):
            candidate = requested - timedelta(days=days_back)
            candidate_date = candidate.strftime("%Y%m%d")
            try:
                rows = await asyncio.to_thread(
                    fetch_history,
                    instrument_id,
                    candidate_date,
                    interval,
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
                # GMO FX KLine returns 404 when no candle set exists for the
                # requested date (for example weekends / market holidays).
                # In chart history mode this means "try an earlier date", not
                # "abort the entire chart request".
                rows = []
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
        return self._research.raw_tick_dates(instrument_id)

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
        return await self._research.compare_raw_date(
            instrument_id=instrument_id,
            date=date,
            strategies=strategies,
            initial_balance=initial_balance,
            size=size,
            supervisor=supervisor,
            bar_seconds=bar_seconds,
        )

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

    async def preview_jev_replay(
        self,
        *,
        instrument_id: str,
        date: str,
        start_time: str | None,
        duration_seconds: int,
        cadence_seconds: int,
    ) -> dict[str, Any]:
        get_instrument(instrument_id)
        return await asyncio.to_thread(
            build_jev_replay_preview,
            self.settings.data_dir,
            instrument_id=instrument_id,
            date=date,
            start_time=start_time,
            duration_seconds=duration_seconds,
            cadence_seconds=cadence_seconds,
        )

    async def run_jev_replay(
        self,
        *,
        instrument_id: str,
        date: str,
        start_time: str | None,
        duration_seconds: int,
        cadence_seconds: int,
        profile: dict[str, Any],
        signal_policy: SignalPolicy,
        paper_config: dict[str, Any],
        acknowledged_token_use: bool,
    ) -> dict[str, Any]:
        if self.running or self._jev_replay_running:
            raise RuntimeError(
                "live Observer実行中はJev historical replayを開始できません。"
            )
        if not self.settings.typesafe_api_key:
            raise ValueError(
                "Jev historical replayにはTYPESAFE_API_KEYが必要です。"
            )

        instrument = get_instrument(instrument_id)
        normalized = dict(paper_config)
        normalized["instrument_id"] = instrument.id
        if normalized.get("autopilot_enabled") and normalized.get("autopilot_fundamentals"):
            raise ValueError("historical fundamentals unavailable: ファンダをOFFにしてください。")
        normalized["price_unit"] = float(instrument.price_unit)
        normalized["move_unit_label"] = instrument.move_unit_label
        normalized["fee_rate"] = float(instrument.paper_fee_rate)
        normalized["fee_label"] = instrument.paper_fee_label
        normalized["short_is_synthetic"] = instrument.paper_short_is_synthetic
        normalized["strategy"] = "momentum"
        normalized["strategy_enabled"] = False
        normalized["jev_direct_enabled"] = True
        normalized["jev_direction_gate_enabled"] = False
        parsed_config = PaperConfig(**normalized)

        from jevpip.jev.client import JevClient

        client = JevClient(self.settings.typesafe_api_key)
        self._jev_replay_running = True
        cancel_event = Event()
        try:
            return await joined_thread(
                run_jev_historical_replay,
                self.settings.data_dir,
                instrument_id=instrument_id,
                date=date,
                start_time=start_time,
                duration_seconds=duration_seconds,
                cadence_seconds=cadence_seconds,
                profile=profile,
                signal_policy=signal_policy,
                paper_config=parsed_config,
                jev_client=client,
                acknowledged_token_use=acknowledged_token_use,
                cancel_event=cancel_event,
                on_cancel=cancel_event.set,
            )
        finally:
            self._jev_replay_running = False

    async def run_strategy_backtest(
        self,
        *,
        date: str,
        instrument_id: str,
        config: dict[str, Any],
        limit: int | None,
    ) -> dict[str, Any]:
        return await self._research.run_strategy_backtest(
            date=date,
            instrument_id=instrument_id,
            config=config,
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
        return await self._research.run_spiritual_backtest(
            date=date,
            instrument_id=instrument_id,
            config=config,
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
        return await self._research.run_statistical_replay(
            date=date,
            instrument_id=instrument_id,
            profile_name=profile_name,
            profile=profile,
            limit=limit,
        )

    async def run_backtest(
        self,
        *,
        date: str,
        instrument_id: str,
        profile_name: str,
        profile: dict[str, Any],
        limit: int | None,
    ) -> dict[str, Any]:
        """Backward-compatible alias for the old generic backtest name."""
        return await self.run_statistical_replay(
            date=date,
            instrument_id=instrument_id,
            profile_name=profile_name,
            profile=profile,
            limit=limit,
        )



# Backward-compatible import used by older tests/consumers.
summarize_backtest = summarize_statistical_replay
