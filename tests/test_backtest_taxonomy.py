from __future__ import annotations

from fastapi.testclient import TestClient

from jevpip.web.app import app


def test_statistical_replay_api_uses_explicit_name(monkeypatch):
    from jevpip.web.app import controller

    async def fake_run_statistical_replay(**kwargs):
        assert kwargs["instrument_id"] == "USD_JPY"
        assert kwargs["date"] == "20260920"
        return {
            "analysis_kind": "statistical_replay",
            "date": kwargs["date"],
            "instrument_id": kwargs["instrument_id"],
            "profile_name": kwargs["profile_name"],
            "output": "data/backtests/test.jsonl",
            "summary": {
                "rows": 2,
                "outcomes": 1,
                "mode": "fx_bid_ask_close",
            },
        }

    monkeypatch.setattr(
        controller,
        "run_statistical_replay",
        fake_run_statistical_replay,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/statistical-replay",
            json={
                "instrument_id": "USD_JPY",
                "date": "20260920",
                "profile_name": "test",
                "profile": {"quote": True},
                "limit": 2,
            },
        )

    assert response.status_code == 200
    assert response.json()["analysis_kind"] == "statistical_replay"
