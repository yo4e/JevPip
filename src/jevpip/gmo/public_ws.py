from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import AsyncIterator, Any

import websockets

from jevpip.market.models import MarketTick

PUBLIC_WS_URL = "wss://forex-api.coin.z.com/ws/public/v1"


def subscribe_message(symbol: str = "USD_JPY") -> str:
    return json.dumps({"command": "subscribe", "channel": "ticker", "symbol": symbol}, separators=(",", ":"))


def parse_ticker(payload: dict[str, Any], received_at: datetime | None = None) -> MarketTick:
    if "bid" not in payload or "ask" not in payload:
        raise ValueError("GMO ticker payload has no bid/ask")
    market_timestamp = datetime.fromisoformat(str(payload["timestamp"]).replace("Z", "+00:00"))
    return MarketTick(
        symbol=str(payload.get("symbol", "USD_JPY")),
        bid=Decimal(str(payload["bid"])),
        ask=Decimal(str(payload["ask"])),
        market_timestamp=market_timestamp,
        received_at=received_at or datetime.now(timezone.utc),
        status=str(payload.get("status", "UNKNOWN")),
        raw=payload,
    )


async def stream_ticker(symbol: str = "USD_JPY", reconnect_delay: float = 2.0) -> AsyncIterator[MarketTick]:
    """Yield ticker updates forever, reconnecting after transient failures."""
    delay = reconnect_delay
    while True:
        try:
            async with websockets.connect(PUBLIC_WS_URL, ping_interval=None, close_timeout=5) as ws:
                await ws.send(subscribe_message(symbol))
                delay = reconnect_delay
                async for message in ws:
                    received_at = datetime.now(timezone.utc)
                    payload = json.loads(message)
                    if isinstance(payload, dict) and "bid" in payload and "ask" in payload:
                        yield parse_ticker(payload, received_at)
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)
