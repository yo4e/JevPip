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
        assert "戦略BT" in response.text
        assert "統計リプレイ" in response.text
        assert "現在設定で戦略バックテスト" in response.text
        assert "戦略比較" in response.text
        assert "No Trade" in response.text
        assert "Buy & Hold" in response.text
        assert "baseline含む5者比較" in response.text
        assert "1分bar" in response.text
        assert "安全監督" in response.text
        assert "Jev監督" in response.text
        assert "公式イベント更新" in response.text
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


def test_strategy_backtest_api(monkeypatch):
    from jevpip.web.app import controller

    async def fake_strategy_backtest(**kwargs):
        assert kwargs["instrument_id"] == "USD_JPY"
        assert kwargs["date"] == "20260919"
        assert kwargs["config"]["strategy"] == "ma_trend"
        assert kwargs["config"]["max_hold_bars"] == 8
        return {
            "instrument_id": "USD_JPY",
            "date": "20260919",
            "replay_mode": "fx_bid_ask_close",
            "input_semantics": "historical_1m_close",
            "rows": 100,
            "config": kwargs["config"],
            "summary": {
                "net_pnl": 12.0,
                "equity": 100012.0,
                "realized_pnl": 12.0,
                "gross_realized_pnl": 20.0,
                "fees_paid": 8.0,
                "slippage_cost": 0.0,
                "profit_factor": 1.5,
                "max_drawdown": 5.0,
                "max_drawdown_pct": 0.00005,
                "closed_trades": 4,
                "wins": 3,
                "win_rate": 0.75,
                "average_trade_pnl": 3.0,
                "average_win_pnl": 5.0,
                "average_loss_pnl": -3.0,
                "exit_reasons": {"take_profit": {"count": 3, "net_pnl": 15.0}},
            },
            "baselines": {
                "no_trade": {"net_pnl": 0.0},
                "buy_and_hold": {"net_pnl": 7.0},
            },
            "trades": [],
            "generated_events": 8,
        }

    monkeypatch.setattr(controller, "run_strategy_backtest", fake_strategy_backtest)
    with TestClient(app) as client:
        response = client.post(
            "/api/strategy-backtest",
            json={
                "instrument_id": "USD_JPY",
                "date": "20260919",
                "strategy": "ma_trend",
                "initial_balance": 100000,
                "size": 1000,
                "max_spread_units": 2,
                "take_profit_units": 1,
                "stop_loss_units": 1,
                "slippage_units": 0,
                "momentum_lookback_bars": 1,
                "momentum_trigger_units": 0.6,
                "rsi_period": 14,
                "rsi_oversold": 30,
                "rsi_overbought": 70,
                "ma_fast_period": 5,
                "ma_slow_period": 20,
                "ma_min_gap_units": 0.2,
                "max_hold_bars": 8,
                "cooldown_bars": 1,
                "supervisor_enabled": True,
                "limit": 100,
            },
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["summary"]["net_pnl"] == 12.0
        assert payload["baselines"]["buy_and_hold"]["net_pnl"] == 7.0


def test_strategy_backtest_rejects_jev():
    with TestClient(app) as client:
        response = client.post(
            "/api/strategy-backtest",
            json={
                "instrument_id": "USD_JPY",
                "date": "20260919",
                "strategy": "jev",
                "initial_balance": 100000,
                "size": 1000,
                "max_spread_units": 2,
                "take_profit_units": 1,
                "stop_loss_units": 1,
                "momentum_trigger_units": 0.6,
            },
        )
        assert response.status_code == 422


def test_context_refresh_api(monkeypatch):
    from jevpip.web.app import controller

    async def fake_refresh(instrument_id):
        assert instrument_id == "USD_JPY"
        return {
            "fetched_at": "2026-09-19T13:00:00+00:00",
            "error": None,
            "supervisor": {
                "state": "NORMAL",
                "reason": "event_ok",
                "allow_entry": True,
            },
            "events": [],
        }

    monkeypatch.setattr(controller, "refresh_external_context", fake_refresh)
    with TestClient(app) as client:
        response = client.post("/api/context/refresh?instrument_id=USD_JPY")
        assert response.status_code == 200
        assert response.json()["supervisor"]["state"] == "NORMAL"


def test_controller_event_supervisor_blocks_paper_entry():
    import asyncio
    from datetime import datetime, timezone

    from jevpip.broker.paper import PaperBroker, PaperConfig
    from jevpip.context import ExternalContextItem
    from jevpip.web.controller import UIController

    controller = UIController()
    config = PaperConfig(
        strategy="momentum",
        momentum_window_seconds=10,
        momentum_trigger_units=0,
        max_spread_units=100,
        take_profit_units=100,
        stop_loss_units=100,
        deterministic_supervisor_enabled=True,
    )
    controller._paper_config = config
    controller._paper = PaperBroker(config)
    controller._instrument_id = "USD_JPY"
    controller._external_context_items = (
        ExternalContextItem(
            source="bls",
            source_id="cpi-test",
            kind="scheduled_event",
            title="Consumer Price Index",
            observed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            source_url="https://example.test/cpi",
            scheduled_at=datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc),
            currencies=("USD",),
            risk="high",
        ),
    )

    async def feed():
        for second, bid in [(0, 100.00), (1, 100.02), (2, 100.04)]:
            timestamp = f"2026-09-11T12:05:{second:02d}+00:00"
            await controller._on_update(
                {
                    "kind": "tick",
                    "instrument_id": "USD_JPY",
                    "symbol": "USD_JPY",
                    "market_timestamp": timestamp,
                    "received_at": timestamp,
                    "bid": f"{bid:.2f}",
                    "ask": f"{bid + 0.01:.2f}",
                    "status": "OPEN",
                }
            )

    asyncio.run(feed())

    assert controller._event_supervisor.state == "PAUSE_ENTRY"
    assert not any(
        event.get("kind") == "paper_trade" and event.get("action") == "OPEN"
        for event in controller._events
    )


def test_context_refresh_writes_per_source_revision_logs(tmp_path, monkeypatch):
    import asyncio
    import json
    from datetime import datetime, timezone

    import jevpip.web.controller as controller_module
    from jevpip.config import Settings
    from jevpip.context import ExternalContextItem
    from jevpip.web.controller import UIController

    def event(source, source_id, currency):
        return ExternalContextItem(
            source=source,
            source_id=source_id,
            kind="scheduled_event",
            title=f"{source} test event",
            observed_at=datetime(2026, 9, 19, 14, 0, tzinfo=timezone.utc),
            source_url=f"https://example.test/{source}",
            scheduled_at=datetime(2026, 9, 20, 14, 0, tzinfo=timezone.utc),
            currencies=(currency,),
            risk="high",
        )

    monkeypatch.setattr(
        controller_module,
        "fetch_bls_events",
        lambda observed_at: (event("bls", "bls-1", "USD"),),
    )
    monkeypatch.setattr(
        controller_module,
        "fetch_boj_events",
        lambda observed_at: (event("boj", "boj-1", "JPY"),),
    )
    monkeypatch.setattr(
        controller_module,
        "fetch_fed_events",
        lambda observed_at: (event("fed", "fed-1", "USD"),),
    )

    controller = UIController(Settings(data_dir=tmp_path))
    asyncio.run(controller.refresh_external_context("USD_JPY"))

    for source in ("bls", "boj", "fed"):
        paths = list((tmp_path / "context" / source).glob("*.jsonl"))
        assert len(paths) == 1
        row = json.loads(paths[0].read_text(encoding="utf-8").strip())
        assert row["source"] == source
        assert row["status"] == "ok"
        assert row["event_count"] == 1


def test_context_refresh_preserves_last_good_source_on_partial_failure(tmp_path, monkeypatch):
    import asyncio
    from datetime import datetime, timezone

    import jevpip.web.controller as controller_module
    from jevpip.config import Settings
    from jevpip.context import ExternalContextItem
    from jevpip.web.controller import UIController

    cached = ExternalContextItem(
        source="fed",
        source_id="cached-fed",
        kind="scheduled_event",
        title="cached FOMC",
        observed_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        source_url="https://example.test/fed",
        scheduled_at=datetime(2026, 9, 20, 18, 0, tzinfo=timezone.utc),
        currencies=("USD",),
        risk="high",
    )

    monkeypatch.setattr(controller_module, "fetch_bls_events", lambda observed_at: ())
    monkeypatch.setattr(controller_module, "fetch_boj_events", lambda observed_at: ())

    def fail_fed(observed_at):
        raise TimeoutError("fed unavailable")

    monkeypatch.setattr(controller_module, "fetch_fed_events", fail_fed)

    controller = UIController(Settings(data_dir=tmp_path))
    controller._external_context_items = (cached,)
    payload = asyncio.run(controller.refresh_external_context("USD_JPY"))

    assert any(item.source_id == "cached-fed" for item in controller._external_context_items)
    assert "fed:TimeoutError" in payload["error"]
    log_path = next((tmp_path / "context" / "fed").glob("*.jsonl"))
    assert '"status":"error"' in log_path.read_text(encoding="utf-8")


def test_periodic_context_refresh_has_minimum_interval(monkeypatch):
    import asyncio

    import jevpip.web.controller as controller_module
    from jevpip.config import Settings
    from jevpip.web.controller import UIController

    delays = []

    async def fake_sleep(delay):
        delays.append(delay)
        raise asyncio.CancelledError

    monkeypatch.setattr(controller_module.asyncio, "sleep", fake_sleep)
    controller = UIController(Settings(context_refresh_seconds=1))

    async def run_once():
        try:
            await controller._context_refresh_loop("USD_JPY")
        except asyncio.CancelledError:
            pass

    asyncio.run(run_once())
    assert delays == [60.0]


def test_controller_jev_supervisor_ttl_and_strategy(monkeypatch):
    import asyncio
    from datetime import datetime, timedelta, timezone

    from jevpip.broker.paper import PaperBroker, PaperConfig
    from jevpip.web.controller import UIController

    controller = UIController()
    config = PaperConfig(
        strategy="momentum",
        momentum_window_seconds=10,
        momentum_trigger_units=0,
        max_spread_units=100,
        take_profit_units=100,
        stop_loss_units=100,
        deterministic_supervisor_enabled=True,
    )
    controller._with_jev = True
    controller._paper_config = config
    controller._paper = PaperBroker(config)
    controller._instrument_id = "USD_JPY"

    recorded_at = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    asyncio.run(
        controller._on_update(
            {
                "kind": "decision",
                "recorded_at": recorded_at.isoformat(),
                "market_timestamp": recorded_at.isoformat(),
                "research_signal": "WAIT",
                "jev_supervisor": {
                    "state": "CAUTION",
                    "strategy": "ma_trend",
                    "confidence": 0.8,
                    "ttl_seconds": 20,
                    "reason": "bounded test",
                },
                "jev_supervisor_error": None,
            }
        )
    )

    active = controller._active_jev_supervisor(recorded_at + timedelta(seconds=19))
    assert active is not None
    assert active.strategy == "ma_trend"

    expired = controller._active_jev_supervisor(recorded_at + timedelta(seconds=21))
    assert expired is None


def test_controller_jev_supervisor_can_pause_new_entries():
    import asyncio
    from datetime import datetime, timezone

    from jevpip.broker.paper import PaperBroker, PaperConfig
    from jevpip.web.controller import UIController

    controller = UIController()
    config = PaperConfig(
        strategy="momentum",
        momentum_window_seconds=10,
        momentum_trigger_units=0,
        max_spread_units=100,
        take_profit_units=100,
        stop_loss_units=100,
        deterministic_supervisor_enabled=True,
    )
    controller._with_jev = True
    controller._paper_config = config
    controller._paper = PaperBroker(config)
    controller._instrument_id = "USD_JPY"

    at = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)
    asyncio.run(
        controller._on_update(
            {
                "kind": "decision",
                "recorded_at": at.isoformat(),
                "market_timestamp": at.isoformat(),
                "research_signal": "WAIT",
                "jev_supervisor": {
                    "state": "PAUSE_ENTRY",
                    "strategy": None,
                    "confidence": 0.9,
                    "ttl_seconds": 30,
                    "reason": "bounded test pause",
                },
                "jev_supervisor_error": None,
            }
        )
    )

    async def feed():
        for second, bid in [(1, 100.00), (2, 100.02), (3, 100.04)]:
            timestamp = f"2026-09-19T12:00:{second:02d}+00:00"
            await controller._on_update(
                {
                    "kind": "tick",
                    "instrument_id": "USD_JPY",
                    "symbol": "USD_JPY",
                    "market_timestamp": timestamp,
                    "received_at": timestamp,
                    "bid": f"{bid:.2f}",
                    "ask": f"{bid + 0.01:.2f}",
                    "status": "OPEN",
                }
            )

    asyncio.run(feed())

    assert not any(
        event.get("kind") == "paper_trade" and event.get("action") == "OPEN"
        for event in controller._events
    )


def test_controller_jev_context_state_is_lookahead_safe():
    from datetime import datetime, timezone

    from jevpip.context import ExternalContextItem
    from jevpip.web.controller import UIController

    controller = UIController()
    controller._external_context_items = (
        ExternalContextItem(
            source="bls",
            source_id="future-observation",
            kind="scheduled_event",
            title="Consumer Price Index",
            observed_at=datetime(2026, 9, 19, 12, 30, tzinfo=timezone.utc),
            source_url="https://example.test/cpi",
            scheduled_at=datetime(2026, 9, 19, 13, 0, tzinfo=timezone.utc),
            currencies=("USD",),
            risk="high",
        ),
    )

    state = controller._jev_context_state(
        datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc),
        "USD_JPY",
    )
    assert state["external_context"] == []


def test_chart_history_treats_fx_404_as_empty_day_and_looks_back(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    import httpx
    import jevpip.web.controller as controller_module
    from jevpip.web.app import controller

    calls = []

    def fake_fetch(instrument_id, date, interval):
        calls.append((instrument_id, date, interval))
        if date in {"20260920", "20260919"}:
            request = httpx.Request(
                "GET",
                f"https://forex-api.coin.z.com/public/v1/klines?date={date}",
            )
            response = httpx.Response(404, request=request)
            raise httpx.HTTPStatusError(
                "404 Not Found",
                request=request,
                response=response,
            )
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

    assert [date for _, date, _ in calls] == [
        "20260920",
        "20260919",
        "20260918",
    ]
    assert payload["dates"] == ["20260918"]
    assert len(payload["candles"]) == 180


def test_chart_history_does_not_hide_non_404_http_errors(monkeypatch):
    import asyncio

    import httpx
    import pytest
    import jevpip.web.controller as controller_module
    from jevpip.web.app import controller

    def fake_fetch(instrument_id, date, interval):
        request = httpx.Request("GET", "https://example.test/klines")
        response = httpx.Response(503, request=request)
        raise httpx.HTTPStatusError(
            "503 Service Unavailable",
            request=request,
            response=response,
        )

    monkeypatch.setattr(controller_module, "fetch_history", fake_fetch)

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(
            controller.fetch_chart_history(
                instrument_id="USD_JPY",
                interval="1min",
                date="20260920",
            )
        )



def test_credentials_api_saves_secrets_without_returning_them(tmp_path, monkeypatch):
    from jevpip.web.app import controller, settings

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "typesafe_api_key", None)
    monkeypatch.setattr(settings, "gmo_fx_api_key", None)
    monkeypatch.setattr(settings, "gmo_fx_api_secret", None)

    with TestClient(app) as client:
        response = client.post(
            "/api/config/credentials",
            json={
                "typesafe_api_key": "jev-secret",
                "gmo_fx_api_key": "gmo-key",
                "gmo_fx_api_secret": "gmo-secret",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["typesafe_api_key_configured"] is True
    assert payload["gmo_private_credentials_configured"] is True
    assert "jev-secret" not in response.text
    assert "gmo-secret" not in response.text
    saved = (tmp_path / ".env").read_text(encoding="utf-8")
    assert 'TYPESAFE_API_KEY="jev-secret"' in saved
    assert 'GMO_FX_API_KEY="gmo-key"' in saved
    assert 'GMO_FX_API_SECRET="gmo-secret"' in saved
    assert controller.settings is settings


def test_controller_tracks_typesafe_reported_token_usage():
    import asyncio

    from jevpip.config import Settings
    from jevpip.web.controller import UIController

    controller = UIController(Settings(_env_file=None))
    asyncio.run(
        controller._on_update(
            {
                "kind": "decision",
                "instrument_id": "BTC",
                "recorded_at": "2026-09-20T00:00:00+00:00",
                "market_timestamp": "2026-09-20T00:00:00+00:00",
                "jev": {
                    "model": "jev-latest",
                    "usage": {"input_tokens": 120, "output_tokens": 8},
                    "answers": {},
                },
            }
        )
    )
    asyncio.run(
        controller._on_update(
            {
                "kind": "decision",
                "instrument_id": "BTC",
                "recorded_at": "2026-09-20T00:00:01+00:00",
                "market_timestamp": "2026-09-20T00:00:01+00:00",
                "jev": {
                    "model": "jev-latest",
                    "usage": {"input_tokens": 100, "output_tokens": 6},
                    "answers": {},
                },
            }
        )
    )

    usage = controller.snapshot()["jev_usage"]
    assert usage == {
        "calls": 2,
        "reported_calls": 2,
        "input_tokens": 220,
        "output_tokens": 14,
        "total_tokens": 234,
        "latest": {
            "input_tokens": 100,
            "output_tokens": 6,
            "total_tokens": 106,
        },
    }


def test_homepage_has_local_api_settings_ui():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "⚙ 設定" in response.text
    assert "settings-jev-key" in response.text
    assert "settings-gmo-secret" in response.text
    assert "Jev API使用量" in response.text



def test_homepage_aggregates_live_ticks_into_selected_chart_interval():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "function mergeChartPoints(history,live,interval=" in response.text
    assert "Math.floor(at/bucketMs)*bucketMs" in response.text
    assert ".slice(-180)" in response.text
    assert "drawChart(activeChartPoints()" in response.text



def test_homepage_explains_wait_signal_gate_failures():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert 'id="signal-detail"' in response.text
    assert "WAIT理由:" in response.text
    assert "signalGateSummary" in response.text



def test_controller_jev_state_context_includes_minimal_paper_state():
    from datetime import datetime, timezone

    from jevpip.broker.paper import PaperBroker, PaperConfig
    from jevpip.web.controller import UIController

    config = PaperConfig(
        strategy="momentum",
        jev_direction_gate_enabled=True,
        size=1000,
        price_unit=0.01,
        momentum_window_seconds=1,
        momentum_trigger_units=0.5,
        max_spread_units=2,
        take_profit_units=100,
        stop_loss_units=100,
        cooldown_seconds=0,
    )
    controller = UIController()
    controller._paper_config = config
    controller._paper = PaperBroker(config)

    controller._paper.on_tick(
        {
            "market_timestamp": "2026-09-20T00:00:00+00:00",
            "bid": "150.000",
            "ask": "150.002",
        }
    )
    controller._paper.on_decision(
        {
            "research_signal": "LONG",
            "recorded_at": "2026-09-20T00:00:00+00:00",
        }
    )
    controller._paper.on_tick(
        {
            "market_timestamp": "2026-09-20T00:00:01+00:00",
            "bid": "150.010",
            "ask": "150.012",
        }
    )

    state = controller._jev_state_context(
        datetime(2026, 9, 20, 0, 0, 2, tzinfo=timezone.utc),
        "USD_JPY",
    )
    paper = state["paper_context"]
    assert paper["configured_strategy"] == "momentum"
    assert paper["jev_direction_gate_enabled"] is True
    assert paper["latest_strategy_decision"]["signal"] == "LONG"
    assert paper["position"]["side"] == "LONG"
    assert paper["position"]["age_seconds"] == 1.0


def test_homepage_describes_jev_as_direction_gate():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Jev方向一致必須" in response.text
    assert "WAIT・反対方向・古い判断ではentryしません" in response.text
