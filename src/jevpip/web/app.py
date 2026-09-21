from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from importlib.resources import files
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from jevpip.config import (
    Settings,
    list_profiles,
    list_signal_policies,
    update_local_credentials,
)
from jevpip.instruments import get_instrument, public_instruments
from jevpip.signals import SignalPolicy
from jevpip.web.controller import UIController
from jevpip.web.schemas import (
    BacktestRequest,
    CredentialSettingsInput,
    FeatureSelection,
    JevReplayPreviewRequest,
    JevReplayRunRequest,
    ObserverStartRequest,
    PaperDemoInput,
    RawCompareRequest,
    SignalPolicyInput,
    SpiritualBacktestRequest,
    StrategyBacktestRequest,
)


settings = Settings()
controller = UIController(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await controller.close()


app = FastAPI(
    title="JevPip",
    description="GMOのFX / 暗号資産Public API × TypeSafe Jev のローカル研究UI",
    lifespan=lifespan,
)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html = files("jevpip.web").joinpath("index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    return {
        "instruments": public_instruments(),
        "profiles": list_profiles(),
        "signal_policies": list_signal_policies(),
        "typesafe_api_key_configured": bool(settings.typesafe_api_key),
        "gmo_private_credentials_configured": settings.gmo_private_read_configured,
        "live_trading_available": False,
    }


@app.post("/api/config/credentials")
async def update_credentials(request: CredentialSettingsInput) -> dict[str, Any]:
    jev_changed = bool(
        request.typesafe_api_key is not None or request.clear_typesafe_api_key
    )
    try:
        update_local_credentials(
            settings,
            typesafe_api_key=request.typesafe_api_key,
            gmo_fx_api_key=request.gmo_fx_api_key,
            gmo_fx_api_secret=request.gmo_fx_api_secret,
            clear_typesafe_api_key=request.clear_typesafe_api_key,
            clear_gmo_private_credentials=request.clear_gmo_private_credentials,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"ローカル設定の保存に失敗しました: {type(exc).__name__}: {exc}",
        ) from exc

    return {
        "typesafe_api_key_configured": bool(settings.typesafe_api_key),
        "gmo_private_credentials_configured": settings.gmo_private_read_configured,
        "jev_applies_next_observer_start": bool(controller.running and jev_changed),
    }


@app.get("/api/status")
async def get_status() -> dict[str, Any]:
    return controller.snapshot()


@app.get("/api/quote")
async def get_public_quote(
    instrument_id: str = "USD_JPY",
    force: bool = False,
) -> dict[str, Any]:
    try:
        get_instrument(instrument_id)
        return await controller.fetch_public_quote(instrument_id, force=force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"最新レート取得に失敗しました: {type(exc).__name__}: {exc}",
        ) from exc


@app.post("/api/context/refresh")
async def refresh_context(
    instrument_id: str = "USD_JPY",
) -> dict[str, Any]:
    try:
        get_instrument(instrument_id)
        return await controller.refresh_external_context(instrument_id)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/chart/history")
async def get_chart_history(
    instrument_id: str = "USD_JPY",
    interval: Literal["1min", "5min", "15min", "1hour"] = "1min",
    date: str = "",
    warmup: bool = False,
) -> dict[str, Any]:
    if not date:
        date = datetime.now().strftime("%Y%m%d")
    try:
        get_instrument(instrument_id)
        datetime.strptime(date, "%Y%m%d")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return await controller.fetch_chart_history(
            instrument_id=instrument_id,
            interval=interval,
            date=date,
            warmup=warmup,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"過去チャート取得に失敗しました: {type(exc).__name__}: {exc}",
        ) from exc


@app.post("/api/observer/start")
async def start_observer(request: ObserverStartRequest) -> dict[str, Any]:
    try:
        get_instrument(request.instrument_id)
        if request.paper_demo is not None and request.paper_decision_mode is not None:
            cfg = request.paper_demo
            mode = request.paper_decision_mode
            oracle = cfg.autopilot_fifty_oracle
            if mode == "jev" and (
                not request.with_jev
                or not cfg.autopilot_enabled
                or cfg.strategy_enabled
                or oracle != "jev"
            ):
                raise ValueError("JevモードはJev専用です。戦略モードと同時には動かせません。")
            if mode == "strategy" and (
                request.with_jev or cfg.autopilot_enabled or not cfg.strategy_enabled
            ):
                raise ValueError("戦略モードではJevを使わず、通常のコード戦略だけを実行します。")
            if mode == "spiritual" and (
                request.with_jev
                or not cfg.autopilot_enabled
                or cfg.autopilot_style != "fifty"
                or cfg.strategy_enabled
                or oracle not in {"moon_phase", "zodiac_polarity", "tarot", "coin_flip"}
            ):
                raise ValueError("スピリチュアルモードはFifty+骨格で、月相/星座/タロット/コイントスの二択だけを使います。")
        await controller.start_observer(
            instrument_id=request.instrument_id,
            profile_name=request.profile_name,
            profile=request.profile.model_dump(),
            with_jev=request.with_jev,
            jev_every_seconds=request.jev_every_seconds,
            signal_policy_name=request.signal_policy_name,
            signal_policy=SignalPolicy(**request.signal_policy.model_dump()),
            paper_config=None if request.paper_demo is None else request.paper_demo.model_dump(),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return controller.snapshot()


@app.post("/api/observer/stop")
async def stop_observer() -> dict[str, Any]:
    await controller.stop_observer()
    return controller.snapshot()


@app.post("/api/paper/reset")
async def reset_paper() -> dict[str, Any]:
    try:
        return controller.reset_paper()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/account")
async def get_account(force: bool = False) -> dict[str, Any]:
    try:
        return await controller.fetch_real_account(force=force)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"GMO実口座の参照に失敗しました: {type(exc).__name__}: {exc}",
        ) from exc


@app.get("/api/raw/dates")
async def get_raw_dates(instrument_id: str = "USD_JPY") -> dict[str, Any]:
    try:
        return {
            "instrument_id": instrument_id,
            "dates": controller.raw_tick_dates(instrument_id),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/compare/raw")
async def compare_raw(request: RawCompareRequest) -> dict[str, Any]:
    try:
        return await controller.compare_raw_date(
            instrument_id=request.instrument_id,
            date=request.date,
            strategies=tuple(dict.fromkeys(request.strategies)),
            initial_balance=request.initial_balance,
            size=request.size,
            supervisor=request.supervisor,
            bar_seconds=request.bar_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"raw tick比較に失敗しました: {type(exc).__name__}: {exc}",
        ) from exc


@app.post("/api/jev-replay/preview")
async def preview_jev_replay_api(
    request: JevReplayPreviewRequest,
) -> dict[str, Any]:
    try:
        get_instrument(request.instrument_id)
        return await controller.preview_jev_replay(
            instrument_id=request.instrument_id,
            date=request.date,
            start_time=request.start_time,
            duration_seconds=request.duration_seconds,
            cadence_seconds=request.cadence_seconds,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Jev replay見積りに失敗しました: {type(exc).__name__}: {exc}",
        ) from exc


@app.post("/api/jev-replay/run")
async def run_jev_replay_api(
    request: JevReplayRunRequest,
) -> dict[str, Any]:
    if not request.acknowledged_token_use:
        raise HTTPException(
            status_code=400,
            detail="Jev APIのトークン消費への確認が必要です。",
        )
    try:
        get_instrument(request.instrument_id)
        return await controller.run_jev_replay(
            instrument_id=request.instrument_id,
            date=request.date,
            start_time=request.start_time,
            duration_seconds=request.duration_seconds,
            cadence_seconds=request.cadence_seconds,
            profile=request.profile.model_dump(),
            signal_policy=SignalPolicy(**request.signal_policy.model_dump()),
            paper_config=request.paper_demo.model_dump(),
            acknowledged_token_use=request.acknowledged_token_use,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Jev historical replayに失敗しました: {type(exc).__name__}: {exc}",
        ) from exc


@app.post("/api/strategy-backtest")
async def run_strategy_backtest_api(
    request: StrategyBacktestRequest,
) -> dict[str, Any]:
    try:
        get_instrument(request.instrument_id)
        payload = request.model_dump()
        instrument_id = payload.pop("instrument_id")
        date = payload.pop("date")
        limit = payload.pop("limit")
        return await controller.run_strategy_backtest(
            date=date,
            instrument_id=instrument_id,
            config=payload,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"戦略バックテストに失敗しました: {type(exc).__name__}: {exc}",
        ) from exc


@app.post("/api/spiritual-backtest")
async def run_spiritual_backtest_api(
    request: SpiritualBacktestRequest,
) -> dict[str, Any]:
    try:
        get_instrument(request.instrument_id)
        payload = request.model_dump()
        instrument_id = payload.pop("instrument_id")
        date = payload.pop("date")
        limit = payload.pop("limit")
        return await controller.run_spiritual_backtest(
            date=date,
            instrument_id=instrument_id,
            config=payload,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"スピバックテストに失敗しました: {type(exc).__name__}: {exc}",
        ) from exc


@app.post("/api/backtest")
async def run_backtest(request: BacktestRequest) -> dict[str, Any]:
    try:
        get_instrument(request.instrument_id)
        return await controller.run_backtest(
            date=request.date,
            instrument_id=request.instrument_id,
            profile_name=request.profile_name,
            profile=request.profile.model_dump(),
            limit=request.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"GMO KLineリプレイに失敗しました: {type(exc).__name__}: {exc}",
        ) from exc


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
