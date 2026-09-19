from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from jevpip.gmo.public_ws import stream_ticker
from jevpip.market.buffer import TickBuffer
from jevpip.market.features import build_features
from jevpip.storage.jsonl import append_jsonl


async def observe(
    profile: dict[str, Any],
    data_dir: Path,
    jev_client: Any | None = None,
    jev_every_seconds: float = 1.0,
    max_ticks: int | None = None,
) -> None:
    buffer = TickBuffer()
    count = 0
    last_jev_at = 0.0

    async for tick in stream_ticker("USD_JPY"):
        count += 1
        buffer.append(tick)

        day = tick.received_at.astimezone(timezone.utc).date().isoformat()
        raw_path = data_dir / "raw_ticks" / f"{day}.jsonl"
        append_jsonl(raw_path, tick.as_json_dict())

        features = build_features(tick, buffer, profile)
        print(
            f"USD_JPY bid={tick.bid} ask={tick.ask} "
            f"spread={tick.spread_pips:.3f}p status={tick.status}"
        )

        now = time.monotonic()
        if jev_client is not None and now - last_jev_at >= jev_every_seconds:
            started = time.perf_counter()
            try:
                answer = await asyncio.to_thread(jev_client.decide, features, "5s")
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                event = {
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                    "market_timestamp": tick.market_timestamp.isoformat(),
                    "profile": profile,
                    "state": features,
                    "jev": answer,
                    "jev_latency_ms": latency_ms,
                }
                append_jsonl(data_dir / "decisions" / f"{day}.jsonl", event)
                print(f"Jev decision saved ({latency_ms} ms)")
            except Exception as exc:
                print(f"Jev error: {type(exc).__name__}: {exc}")
            last_jev_at = now

        if max_ticks is not None and count >= max_ticks:
            return
