from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
import inspect
from pathlib import Path
import time
from typing import Any

from jevpip.gmo.public_ws import stream_ticker
from jevpip.market.buffer import TickBuffer
from jevpip.market.features import build_features
from jevpip.signals import SignalPolicy, classify_research_signal
from jevpip.storage.jsonl import append_jsonl

UpdateCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


async def _notify(callback: UpdateCallback | None, event: dict[str, Any]) -> None:
    if callback is None:
        return
    result = callback(event)
    if inspect.isawaitable(result):
        await result


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
) -> None:
    buffer = TickBuffer()
    count = 0
    last_jev_at = 0.0

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
        if jev_client is not None and now - last_jev_at >= jev_every_seconds:
            started = time.perf_counter()
            try:
                answer = await asyncio.to_thread(jev_client.decide, features, "5s")
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                research_signal = None
                signal_detail = None
                if signal_policy is not None:
                    research_signal, signal_detail = classify_research_signal(
                        answer,
                        float(tick.spread_units),
                        signal_policy,
                    )
                event = {
                    "kind": "decision",
                    "instrument_id": tick.instrument_id,
                    "display_symbol": tick.display_symbol,
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                    "market_timestamp": tick.market_timestamp.isoformat(),
                    "bid": str(tick.bid),
                    "ask": str(tick.ask),
                    "spread_units": float(tick.spread_units),
                    "spread_pips": float(tick.spread_units),
                    "move_unit_label": tick.move_unit_label,
                    "profile": profile,
                    "state": features,
                    "jev": answer,
                    "jev_latency_ms": latency_ms,
                    "research_signal": research_signal,
                    "signal_policy": signal_policy_name,
                    "signal_detail": signal_detail,
                }
                append_jsonl(
                    data_dir / "decisions" / tick.instrument_id / f"{day}.jsonl",
                    event,
                )
                await _notify(on_update, event)
                if emit_console:
                    suffix = f" signal={research_signal}" if research_signal else ""
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
            last_jev_at = now

        if max_ticks is not None and count >= max_ticks:
            return
