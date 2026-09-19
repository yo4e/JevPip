import json

from fastapi.testclient import TestClient

from jevpip.web.app import app
from jevpip.web.controller import summarize_backtest


def test_web_root_is_japanese_and_has_dashboard_features():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "過去チャート" in response.text
        assert "MA20" in response.text
        assert "MA200" in response.text
        assert "BTC/JPY" in response.text
        assert "デモ自動売買" in response.text
        assert "RSI逆張り" in response.text
        assert "MAトレンド" in response.text
        assert "RSI/MA入力" in response.text
        assert "戦略比較" in response.text
        assert "No Trade" in response.text
        assert "Buy & Hold" in response.text
        assert "baseline含む5者比較" in response.text
        assert "1分bar" in response.text
        assert "安全監督" in response.text
        assert "tick age" in response.text
        assert "Take Profit" in response.text
        assert "Stop Loss" in response.text
        assert "売買条件を読み込み中" in response.text
        assert "デモ口座" in response.text
        assert "外国為替FX 実口座（参照専用）" in response.text
        assert "月相" in response.text
        assert "過去日付を自由に選べます" in response.text
        assert "terminal-resizer" in response.text


def test_config_exposes_btc_profiles_and_safety_flags():
    with TestClient(app) as client:
        response = client.get("/api/config")
        assert response.status_code == 200
        payload = response.json()
        assert payload["instruments"]["BTC"]["display_symbol"] == "BTC/JPY"
        assert payload["instruments"]["BTC"]["move_unit_label"] == "円"
        assert payload["instruments"]["USD_JPY"]["move_unit_label"] == "pips"
        assert payload["instruments"]["EUR_JPY"]["display_symbol"] == "EUR/JPY"
        assert payload["instruments"]["GBP_JPY"]["quote_currency"] == "JPY"
        assert "moon_only" in payload["profiles"]
        assert "research_default" in payload["signal_policies"]
        assert payload["live_trading_available"] is False
        assert "gmo_private_credentials_configured" in payload


def test_chart_history_endpoint_routes_btc(monkeypatch):
    from jevpip.web.app import controller

    async def fake_history(*, instrument_id, interval, date):
        assert instrument_id == "BTC"
        assert interval == "5min"
        assert date == "20260919"
        return {
            "instrument_id": "BTC",
            "interval": "5min",
            "date": "20260919",
            "candles": [{"timestamp": "2026-09-19T00:00:00+00:00", "close": 17000000}],
        }

    monkeypatch.setattr(controller, "fetch_chart_history", fake_history)
    with TestClient(app) as client:
        response = client.get(
            "/api/chart/history?instrument_id=BTC&interval=5min&date=20260919"
        )
        assert response.status_code == 200
        assert response.json()["candles"][0]["close"] == 17000000


def test_account_endpoint_requires_local_credentials(monkeypatch):
    from jevpip.web.app import controller

    monkeypatch.setattr(controller.settings, "gmo_fx_api_key", None)
    monkeypatch.setattr(controller.settings, "gmo_fx_api_secret", None)
    with TestClient(app) as client:
        response = client.get("/api/account")
        assert response.status_code == 400
        assert "GMO_FX_API_KEY" in response.json()["detail"]


def test_backtest_summary():
    rows = [
        {
            "replay_mode": "fx_bid_ask_close",
            "outcome_1m": {
                "delta_units": 2.0,
                "long_edge_units": 1.0,
                "short_edge_units": -3.0,
            },
        },
        {
            "replay_mode": "fx_bid_ask_close",
            "outcome_1m": {
                "delta_units": -1.0,
                "long_edge_units": -2.0,
                "short_edge_units": 0.5,
            },
        },
        {"replay_mode": "fx_bid_ask_close", "outcome_1m": None},
    ]
    summary = summarize_backtest(rows)
    assert summary["rows"] == 3
    assert summary["outcomes"] == 2
    assert summary["mode"] == "fx_bid_ask_close"
    assert summary["mean_change_units"] == 0.5
    assert summary["max_change_units"] == 2.0
    assert summary["min_change_units"] == -1.0
    assert summary["up_ratio"] == 0.5
    assert summary["down_ratio"] == 0.5
    assert summary["long_positive_ratio"] == 0.5
    assert summary["short_positive_ratio"] == 0.5


def test_btc_backtest_api_is_allowed(monkeypatch):
    from jevpip.web.app import controller

    async def fake_run_backtest(**kwargs):
        assert kwargs["instrument_id"] == "BTC"
        assert kwargs["date"] == "20260919"
        return {
            "date": "20260919",
            "instrument_id": "BTC",
            "profile_name": "test",
            "output": "data/backtests/test.jsonl",
            "summary": {
                "rows": 2,
                "outcomes": 1,
                "mode": "crypto_close_only",
                "mean_change_units": 1200.0,
                "max_change_units": 1200.0,
                "min_change_units": 1200.0,
                "mean_long_edge_units": None,
                "mean_short_edge_units": None,
                "long_positive_ratio": None,
                "short_positive_ratio": None,
                "up_ratio": 1.0,
                "down_ratio": 0.0,
            },
        }

    monkeypatch.setattr(controller, "run_backtest", fake_run_backtest)
    with TestClient(app) as client:
        response = client.post(
            "/api/backtest",
            json={
                "instrument_id": "BTC",
                "date": "20260919",
                "profile_name": "test",
                "profile": {"quote": True},
                "limit": 2,
            },
        )
        assert response.status_code == 200
        assert response.json()["summary"]["mode"] == "crypto_close_only"


def test_chart_history_collects_multiple_days_for_stable_candle_count(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import jevpip.web.controller as controller_module
    from jevpip.web.app import controller

    calls = []

    def fake_fetch(instrument_id, date, interval):
        calls.append((instrument_id, date, interval))
        if date in {"20260920", "20260919"}:
            return []
        if date == "20260918":
            return [
                SimpleNamespace(
                    open_time_ms=1758153600000 + i * 60_000,
                    open=147.0 + i * 0.001,
                    high=147.1 + i * 0.001,
                    low=146.9 + i * 0.001,
                    close=147.05 + i * 0.001,
                )
                for i in range(200)
            ]
        return []

    monkeypatch.setattr(controller_module, "fetch_history", fake_fetch)
    payload = asyncio.run(
        controller.fetch_chart_history(
            instrument_id="USD_JPY",
            interval="1min",
            date="20260920",
        )
    )

    assert [date for _, date, _ in calls] == ["20260920", "20260919", "20260918"]
    assert payload["date"] == "20260920"
    assert payload["dates"] == ["20260918"]
    assert payload["target_candles"] == 180
    assert len(payload["candles"]) == 180


def test_longer_chart_interval_looks_back_farther(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    import jevpip.web.controller as controller_module
    from jevpip.web.app import controller

    calls = []

    def fake_fetch(instrument_id, date, interval):
        calls.append((date, interval))
        day = int(date[-2:])
        count = 24 if interval == "1hour" else 180
        return [
            SimpleNamespace(
                open_time_ms=(day * 86_400_000) + i * 3_600_000,
                open=100 + i,
                high=101 + i,
                low=99 + i,
                close=100.5 + i,
            )
            for i in range(count)
        ]

    monkeypatch.setattr(controller_module, "fetch_history", fake_fetch)

    one_min = asyncio.run(
        controller.fetch_chart_history(
            instrument_id="BTC",
            interval="1min",
            date="20260919",
        )
    )
    hourly = asyncio.run(
        controller.fetch_chart_history(
            instrument_id="BTC",
            interval="1hour",
            date="20260919",
        )
    )

    one_min_dates = [date for date, interval in calls if interval == "1min"]
    hourly_dates = [date for date, interval in calls if interval == "1hour"]
    assert len(one_min_dates) == 1
    assert len(hourly_dates) > 1
    assert len(one_min["candles"]) == 180
    assert len(hourly["candles"]) == 180

def test_chart_renderer_has_non_finite_and_bid_ask_fallback_guards():
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "function chartPrice" in response.text
        assert "表示できるチャートデータがありません" in response.text
        assert "historyCache" in response.text


def test_raw_dates_and_strategy_compare_api(tmp_path, monkeypatch):
    from jevpip.web.app import controller

    monkeypatch.setattr(controller.settings, "data_dir", tmp_path)
    raw_dir = tmp_path / "raw_ticks" / "USD_JPY"
    raw_dir.mkdir(parents=True)
    path = raw_dir / "2026-09-19.jsonl"
    rows = []
    for second in range(7):
        mid = 150.0 + second * 0.01
        timestamp = f"2026-09-19T00:00:{second:02d}+00:00"
        rows.append(
            {
                "instrument_id": "USD_JPY",
                "symbol": "USD_JPY",
                "market_timestamp": timestamp,
                "received_at": timestamp,
                "bid": f"{mid:.3f}",
                "ask": f"{mid + 0.002:.3f}",
                "status": "OPEN",
            }
        )
    path.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    with TestClient(app) as client:
        dates = client.get("/api/raw/dates?instrument_id=USD_JPY")
        assert dates.status_code == 200
        assert dates.json()["dates"] == ["2026-09-19"]

        response = client.post(
            "/api/compare/raw",
            json={
                "instrument_id": "USD_JPY",
                "date": "2026-09-19",
                "strategies": ["momentum", "ma_trend"],
                "initial_balance": 100000,
                "supervisor": True,
                "bar_seconds": 0,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert set(payload["results"]) == {"no_trade", "buy_and_hold", "momentum", "ma_trend"}
        assert payload["results"]["no_trade"]["net_pnl"] == 0.0
        assert payload["source"].endswith("2026-09-19.jsonl")
        assert payload["results"]["momentum"]["ticks"] == 7


def test_raw_strategy_compare_missing_file_is_400(tmp_path, monkeypatch):
    from jevpip.web.app import controller

    monkeypatch.setattr(controller.settings, "data_dir", tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/compare/raw",
            json={
                "instrument_id": "BTC",
                "date": "2026-09-19",
                "strategies": ["momentum"],
                "supervisor": True,
                "bar_seconds": 0,
            },
        )
        assert response.status_code == 400
        assert "raw tick data" in response.json()["detail"]
