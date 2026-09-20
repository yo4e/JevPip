from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime, timezone
import inspect
from pathlib import Path
import time
from typing import Any

from jevpip.gmo.public_ws import stream_ticker
from jevpip.jev.supervisor import derive_jev_supervisor_advice
from jevpip.jev.autopilot import attach_target
from jevpip.async_work import joined_thread
from jevpip.market.buffer import TickBuffer
from jevpip.market.features import build_features
from jevpip.signals import (
    SignalPolicy,
    classify_direction_signal,
    classify_position_action,
    classify_research_signal,
)
from jevpip.storage.jsonl import append_jsonl

UpdateCallback = Callable[[dict[str, Any]], Awaitable[None] | None]
JevStateContextProvider = Callable[[datetime, str], dict[str, Any]]


async def _notify(callback: UpdateCallback | None, event: dict[str, Any]) -> None:
    if callback is None:
        return
    result = callback(event)
    if inspect.isawaitable(result):
        await result


def _should_request_jev(state: dict[str, Any]) -> bool:
    policy = state.get("autopilot")
    if not isinstance(policy, dict):
        return True
    if policy.get("style") != "fifty":
        return True
    # Fifty+ calls Jev only while flat. Once a direction is returned the
    # broker owns the position until the symmetric TP/SL closes it.
    return policy.get("position") is None and bool(policy.get("targets"))


async def observe(
    profile: dict[str, Any],
    data_dir: Path,
    jev_client: Any | None = None,
    jev_every_seconds: float = 1.0,
    max_ticks: int | None = None,
    signal_policy: SignalPolicy | None = None,
    signal_policy_name: str | None = None,
    *,
    instrument_id: str = "USD_JPY",
    on_update: UpdateCallback | None = None,
    emit_console: bool = True,
    jev_state_context_provider: JevStateContextProvider | None = None,
    jev_supervisor_strategies: tuple[str, ...] = (),
) -> None:
    buffer = TickBuffer()
    count = 0
    jev_task: asyncio.Task[None] | None = None
    last_jev_completed_at = float("-inf")
    last_jev_started_at = float("-inf")
    autopilot_mode = False

    async def run_jev_decision(
        *,
        tick: Any,
        features: dict[str, Any],
        jev_state: dict[str, Any],
        day: str,
    ) -> None:
        nonlocal last_jev_completed_at
        requested_at = datetime.now(timezone.utc)
        started = time.perf_counter()
        try:
            answer = await joined_thread(
                jev_client.decide,
                jev_state,
                f"{jev_state['autopilot']['horizon_seconds']}s" if "autopilot" in jev_state else "5s",
                supervisor_strategies=jev_supervisor_strategies,
                instrument_label=tick.display_symbol,
            )
            available_at = datetime.now(timezone.utc)
            if not isinstance(answer, dict):
                answer = {"malformed_response_type": type(answer).__name__}
            latency_ms = round((time.perf_counter() - started) * 1000, 2)
            direction_signal = None
            direction_detail = None
            research_signal = None
            signal_detail = None
            position_action, position_action_detail = (None, {}) if "autopilot" in jev_state else classify_position_action(answer)
            if signal_policy is not None and "autopilot" not in jev_state:
                direction_signal, direction_detail = classify_direction_signal(
                    answer,
                    signal_policy,
                )
                research_signal, signal_detail = classify_research_signal(
                    answer,
                    float(tick.spread_units),
                    signal_policy,
                )
            jev_supervisor = None
            jev_supervisor_detail = None
            jev_supervisor_error = None
            if jev_supervisor_strategies:
                try:
                    advice, jev_supervisor_detail = derive_jev_supervisor_advice(
                        answer,
                        allowed_strategies=jev_supervisor_strategies,
                    )
                    jev_supervisor = asdict(advice)
                except Exception as exc:
                    jev_supervisor_error = f"{type(exc).__name__}: {exc}"

            event = {
                "kind": "decision",
                "instrument_id": tick.instrument_id,
                "display_symbol": tick.display_symbol,
                "recorded_at": available_at.isoformat(),
                "basis_market_timestamp": tick.market_timestamp.isoformat(),
                "basis_received_at": tick.received_at.isoformat(),
                "requested_at": requested_at.isoformat(),
                "available_at": available_at.isoformat(),
                "market_timestamp": tick.market_timestamp.isoformat(),
                "bid": str(tick.bid),
                "ask": str(tick.ask),
                "spread_units": float(tick.spread_units),
                "spread_pips": float(tick.spread_units),
                "move_unit_label": tick.move_unit_label,
                "profile": profile,
                "state": jev_state,
                "jev": answer,
                "jev_latency_ms": latency_ms,
                "direction_signal": direction_signal,
                "direction_detail": direction_detail,
                "research_signal": research_signal,
                "position_action": position_action,
                "position_action_detail": position_action_detail,
                "signal_policy": signal_policy_name,
                "signal_detail": signal_detail,
                "jev_supervisor": jev_supervisor,
                "jev_supervisor_detail": jev_supervisor_detail,
                "jev_supervisor_error": jev_supervisor_error,
            }
            attach_target(event, jev_state)
            append_jsonl(
                data_dir / "decisions" / tick.instrument_id / f"{day}.jsonl",
                event,
            )
            await _notify(on_update, event)
            if emit_console:
                suffix = (
                    f" direction={direction_signal} research={research_signal}"
                    if direction_signal or research_signal
                    else ""
                )
                print(f"Jev decision saved ({latency_ms} ms){suffix}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error_event = {
                "kind": "error",
                "instrument_id": tick.instrument_id,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "message": f"Jev error: {type(exc).__name__}: {exc}",
            }
            await _notify(on_update, error_event)
            if emit_console:
                print(error_event["message"])
        finally:
            last_jev_completed_at = time.monotonic()

    try:
        async for tick in stream_ticker(instrument_id):
            count += 1
            buffer.append(tick)

            day = tick.received_at.astimezone(timezone.utc).date().isoformat()
            raw_path = data_dir / "raw_ticks" / tick.instrument_id / f"{day}.jsonl"
            append_jsonl(raw_path, tick.as_json_dict())

            features = build_features(tick, buffer, profile)
            tick_event = {
                "kind": "tick",
                "instrument_id": tick.instrument_id,
                "display_symbol": tick.display_symbol,
                "received_at": tick.received_at.isoformat(),
                "market_timestamp": tick.market_timestamp.isoformat(),
                "symbol": tick.symbol,
                "bid": str(tick.bid),
                "ask": str(tick.ask),
                "spread_units": float(tick.spread_units),
                "spread_pips": float(tick.spread_units),
                "move_unit_label": tick.move_unit_label,
                "status": tick.status,
                "features": features,
            }
            await _notify(on_update, tick_event)

            if emit_console:
                print(
                    f"{tick.display_symbol} bid={tick.bid} ask={tick.ask} "
                    f"spread={tick.spread_units:.3f}{tick.move_unit_label} status={tick.status}"
                )

            now = time.monotonic()
            task_running = jev_task is not None and not jev_task.done()
            cadence_ready = now - (last_jev_started_at if autopilot_mode else last_jev_completed_at) >= jev_every_seconds
            if jev_client is not None and not task_running and cadence_ready:
                jev_state = dict(features)
                if jev_state_context_provider is not None:
                    context_state = jev_state_context_provider(
                        tick.market_timestamp,
                        tick.instrument_id,
                    )
                    if not isinstance(context_state, dict):
                        raise TypeError("Jev state context provider must return a dict")
                    jev_state.update(context_state)

                autopilot_mode = "autopilot" in jev_state
                if not _should_request_jev(jev_state):
                    continue
                last_jev_started_at = now

                jev_task = asyncio.create_task(
                    run_jev_decision(
                        tick=tick,
                        features=features,
                        jev_state=jev_state,
                        day=day,
                    )
                )

            if max_ticks is not None and count >= max_ticks:
                if jev_task is not None:
                    await jev_task
                return
    finally:
        if jev_task is not None and not jev_task.done():
            jev_task.cancel()
            try:
                await jev_task
            except asyncio.CancelledError:
                pass
