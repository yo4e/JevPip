from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
import json
from typing import AsyncIterator, Any

import websockets

from jevpip.instruments import get_instrument
from jevpip.market.models import MarketTick


def subscribe_message(symbol: str) -> str:
    return json.dumps(
        {"command": "subscribe", "channel": "ticker", "symbol": symbol},
        separators=(",", ":"),
    )


def parse_ticker(
    payload: dict[str, Any],
    *,
    instrument_id: str = "USD_JPY",
    received_at: datetime | None = None,
) -> MarketTick:
    if "bid" not in payload or "ask" not in payload:
        raise ValueError("GMO ticker payload has no bid/ask")
    instrument = get_instrument(instrument_id)
    market_timestamp = datetime.fromisoformat(str(payload["timestamp"]).replace("Z", "+00:00"))
    return MarketTick(
        instrument_id=instrument.id,
        symbol=instrument.api_symbol,
        display_symbol=instrument.display_symbol,
        bid=Decimal(str(payload["bid"])),
        ask=Decimal(str(payload["ask"])),
        market_timestamp=market_timestamp,
        received_at=received_at or datetime.now(timezone.utc),
        status=str(payload.get("status", "OPEN")),
        price_unit=instrument.price_unit,
        move_unit_label=instrument.move_unit_label,
        raw=payload,
    )


async def stream_ticker(
    instrument_id: str = "USD_JPY",
    reconnect_delay: float = 2.0,
) -> AsyncIterator[MarketTick]:
    """Yield ticker updates forever, reconnecting after transient failures."""
    instrument = get_instrument(instrument_id)
    delay = reconnect_delay
    while True:
        try:
            async with websockets.connect(
                instrument.ws_url,
                ping_interval=None,
                close_timeout=5,
            ) as ws:
                await ws.send(subscribe_message(instrument.api_symbol))
                delay = reconnect_delay
                async for message in ws:
                    received_at = datetime.now(timezone.utc)
                    payload = json.loads(message)
                    if isinstance(payload, dict) and "bid" in payload and "ask" in payload:
                        yield parse_ticker(
                            payload,
                            instrument_id=instrument_id,
                            received_at=received_at,
                        )
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)
