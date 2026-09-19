import hashlib
import hmac

import httpx

from jevpip.gmo.private_rest import GMOPrivateReadClient


def test_private_get_signature_matches_official_formula():
    client = GMOPrivateReadClient("key", "secret")
    headers = client._auth_headers("/v1/account/assets", timestamp_ms=1234567890000)
    expected = hmac.new(
        b"secret",
        b"1234567890000GET/v1/account/assets",
        hashlib.sha256,
    ).hexdigest()
    assert headers["API-KEY"] == "key"
    assert headers["API-TIMESTAMP"] == "1234567890000"
    assert headers["API-SIGN"] == expected


def test_private_snapshot_uses_get_only():
    methods = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.url.path.endswith("/account/assets"):
            return httpx.Response(200, json={"status": 0, "data": {"balance": "100000"}})
        return httpx.Response(
            200,
            json={"status": 0, "data": {"list": [{"symbol": "USD_JPY", "side": "BUY"}]}},
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        client = GMOPrivateReadClient("key", "secret", client=http_client)
        snapshot = client.fetch_snapshot()

    assert methods == ["GET", "GET"]
    assert snapshot["assets"]["balance"] == "100000"
    assert snapshot["positions"][0]["symbol"] == "USD_JPY"
