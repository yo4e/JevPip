from fastapi.testclient import TestClient

from jevpip.web.app import app
from jevpip.web.controller import summarize_backtest


def test_web_root_is_japanese_and_has_dashboard_features():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "リアルタイムチャート" in response.text
        assert "デモ口座" in response.text
        assert "実口座（参照専用）" in response.text
        assert "月の満ち欠け" in response.text


def test_config_exposes_profiles_and_safety_flags():
    with TestClient(app) as client:
        response = client.get("/api/config")
        assert response.status_code == 200
        payload = response.json()
        assert "moon_only" in payload["profiles"]
        assert "research_default" in payload["signal_policies"]
        assert payload["live_trading_available"] is False
        assert "gmo_private_credentials_configured" in payload


def test_account_endpoint_requires_local_credentials():
    with TestClient(app) as client:
        response = client.get("/api/account")
        assert response.status_code == 400
        assert "GMO_FX_API_KEY" in response.json()["detail"]


def test_backtest_summary():
    rows = [
        {
            "outcome_1m": {
                "delta_mid_pips": 2.0,
                "long_edge_pips": 1.0,
                "short_edge_pips": -3.0,
            }
        },
        {
            "outcome_1m": {
                "delta_mid_pips": -1.0,
                "long_edge_pips": -2.0,
                "short_edge_pips": 0.5,
            }
        },
        {"outcome_1m": None},
    ]
    summary = summarize_backtest(rows)
    assert summary["rows"] == 3
    assert summary["outcomes"] == 2
    assert summary["mean_delta_mid_pips"] == 0.5
    assert summary["long_positive_ratio"] == 0.5
    assert summary["short_positive_ratio"] == 0.5
