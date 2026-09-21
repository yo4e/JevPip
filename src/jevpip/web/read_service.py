from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import time
from typing import Any, Callable

import httpx

from jevpip.config import Settings
from jevpip.instruments import get_instrument


class ReadOnlyDataService:
    """Read-only market/account access and its short-lived UI caches."""

    def __init__(
        self,
        settings: Settings,
        *,
        fetch_public_ticker_fn: Callable[[str], Any],
        fetch_history_fn: Callable[[str, str, str], list[Any]],
        private_client_factory: Callable[[str, str], Any],
    ) -> None:
        self.settings = settings
        self._fetch_public_ticker = fetch_public_ticker_fn
        self._fetch_history = fetch_history_fn
        self._private_client_factory = private_client_factory
        self._real_account_cache: tuple[float, dict[str, Any]] | None = None
        self._public_quote_cache: dict[str, tuple[float, dict[str, Any]]] = {}

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

        ticker = await asyncio.to_thread(self._fetch_public_ticker, instrument.id)
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
                    self._fetch_history,
                    instrument_id,
                    candidate_date,
                    interval,
                )
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 404:
                    raise
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
        client = self._private_client_factory(
            self.settings.gmo_fx_api_key,
            self.settings.gmo_fx_api_secret,
        )
        payload = await asyncio.to_thread(client.fetch_snapshot, "USD_JPY")
        payload["fetched_at"] = datetime.now(timezone.utc).isoformat()
        self._real_account_cache = (now, payload)
        return payload
