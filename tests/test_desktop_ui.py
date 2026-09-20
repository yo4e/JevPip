import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from jevpip.config import Settings
from jevpip.signals import SignalPolicy
from jevpip.web.app import app
from jevpip.web.controller import UIController


def test_chart_warmup_is_optional_and_forwarded(monkeypatch):
    from jevpip.web.app import controller

    seen = []

    async def history(**kwargs):
        seen.append(kwargs)
        return {"candles": []}

    monkeypatch.setattr(controller, "fetch_chart_history", history)
    with TestClient(app) as client:
        assert client.get("/api/chart/history?date=20260920").status_code == 200
        assert client.get("/api/chart/history?date=20260920&warmup=true").status_code == 200
    assert [call["warmup"] for call in seen] == [False, True]


def test_hourly_ma200_warmup_crosses_weekends_and_stays_bounded(monkeypatch, tmp_path):
    import jevpip.web.controller as module

    requested = []

    def fetch(instrument_id, date, interval):
        requested.append(date)
        day = datetime.strptime(date, "%Y%m%d").replace(tzinfo=timezone.utc)
        if day.weekday() >= 5:
            return []
        return [
            SimpleNamespace(
                open_time_ms=int((day + timedelta(hours=hour)).timestamp() * 1000),
                open=156, high=157, low=155, close=156.5,
            )
            for hour in range(24)
        ]

    monkeypatch.setattr(module, "fetch_history", fetch)
    controller = UIController(Settings(_env_file=None, data_dir=tmp_path))
    result = asyncio.run(controller.fetch_chart_history(
        instrument_id="USD_JPY", interval="1hour", date="20260920", warmup=True,
    ))
    assert len(result["candles"]) == result["target_candles"] == 379
    assert 18 < len(requested) <= 32
    times = [row["timestamp"] for row in result["candles"]]
    assert times == sorted(set(times))


def test_running_session_exposes_public_start_time_settings(monkeypatch, tmp_path):
    import jevpip.web.controller as module

    async def context(*args, **kwargs):
        return {}

    async def observe(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(module, "observe", observe)
    controller = UIController(Settings(_env_file=None, data_dir=tmp_path))
    monkeypatch.setattr(controller, "refresh_external_context", context)
    profile = {"quote": True, "returns_seconds": [3, 10]}
    policy = SignalPolicy(min_direction_probability=0.73)

    async def run():
        await controller.start_observer(
            instrument_id="BTC", profile_name="custom / UI", profile=profile,
            with_jev=False, jev_every_seconds=2, signal_policy_name="custom / UI",
            signal_policy=policy, paper_config={"size": 0.002, "initial_balance": 200000},
        )
        try:
            status = controller.snapshot()
            assert status["running"] and status["instrument_id"] == "BTC"
            assert status["session_config"] == {
                "profile": profile,
                "signal_policy": module.asdict(policy),
                "jev_every_seconds": 2,
            }
            assert status["paper"]["config"]["size"] == 0.002
            assert status["paper"]["config"]["initial_balance"] == 200000
        finally:
            await controller.stop_observer()

    asyncio.run(run())
