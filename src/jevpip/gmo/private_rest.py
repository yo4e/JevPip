from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import httpx

PRIVATE_REST_URL = "https://forex-api.coin.z.com/private"


class GMOPrivateReadClient:
    """Read-only GMO FX Private REST client.

    This class intentionally exposes GET endpoints only. JevPip does not implement
    any order endpoint here.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        self.api_key = api_key
        self.api_secret = api_secret
        self._client = client

    def _auth_headers(self, path: str, *, timestamp_ms: int | None = None) -> dict[str, str]:
        timestamp = str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000))
        text = f"{timestamp}GET{path}".encode("ascii")
        signature = hmac.new(
            self.api_secret.encode("ascii"),
            text,
            hashlib.sha256,
        ).hexdigest()
        return {
            "API-KEY": self.api_key,
            "API-TIMESTAMP": timestamp,
            "API-SIGN": signature,
        }

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        client = self._client or httpx
        response = client.get(
            f"{PRIVATE_REST_URL}{path}",
            headers=self._auth_headers(path),
            params=params,
            timeout=10.0,
        )
        response.raise_for_status()
        body = response.json()
        if body.get("status") != 0:
            messages = body.get("messages") or []
            message = ", ".join(str(item.get("message", item)) for item in messages) or "unknown error"
            raise RuntimeError(f"GMO FX Private API error: {message}")
        return body.get("data")

    def fetch_account_assets(self) -> dict[str, Any]:
        data = self._get("/v1/account/assets")
        return dict(data or {})

    def fetch_open_positions(self, symbol: str = "USD_JPY") -> list[dict[str, Any]]:
        data = self._get(
            "/v1/openPositions",
            params={"symbol": symbol, "page": 1, "count": 100},
        )
        if not isinstance(data, dict):
            return []
        rows = data.get("list", [])
        return [dict(row) for row in rows if isinstance(row, dict)]

    def fetch_snapshot(self, symbol: str = "USD_JPY") -> dict[str, Any]:
        return {
            "assets": self.fetch_account_assets(),
            "positions": self.fetch_open_positions(symbol),
        }
