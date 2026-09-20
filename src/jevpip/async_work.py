"""Keep a synchronous API worker owned until it actually finishes."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any


async def joined_thread(function: Callable[..., Any], *args: Any,
                        on_cancel: Callable[[], None] | None = None, **kwargs: Any) -> Any:
    worker = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        if on_cancel is not None:
            on_cancel()
        # Cancelling to_thread does not stop the HTTP request. Drain it before
        # allowing a new session/replay to start, and discard its late result.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not worker.cancelled():
            worker.exception()  # retrieve any error after cancellation
        raise
