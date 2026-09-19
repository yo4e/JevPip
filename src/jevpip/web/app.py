from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from importlib.resources import files
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator

from jevpip.config import Settings, list_profiles, list_signal_policies
from jevpip.instruments import get_instrument, public_instruments
from jevpip.signals import SignalPolicy
from jevpip.web.controller import UIController


class FeatureSelection(BaseModel):
    quote: bool = True
    returns_seconds: list[int] = Field(default_factory=list, max_length=24)
    range_seconds: list[int] = Field(default_factory=list, max_length=24)
    tick_count_seconds: list[int] = Field(default_factory=list, max_length=24)
    realized_vol_seconds: list[int] = Field(default_factory=list, max_length=24)
    moon_phase: bool = False
    rsi_period: int = Field(default=0, ge=0, le=500)
    sma_periods: list[int] = Field(default_factory=list, max_length=24)
    random_control: bool = False

    @field_validator(
        "returns_seconds",
        "range_seconds",
        "tick_count_seconds",
        "realized_vol_seconds",
    )
    @classmethod
    def validate_windows(cls, values: list[int]) -> list[int]:
        if any(value < 1 or value > 3600 for value in values):
            raise ValueError("時間窓は1〜3600秒で指定してください。")
        return sorted(set(values))

    @field_validator("sma_periods")
    @classmethod
    def validate_sma(cls, values: list[int]) -> list[int]:
        if any(value < 1 or value > 5000 for value in values):
            raise ValueError("SMA期間は1〜5000で指定してください。")
        return sorted(set(values))


class SignalPolicyInput(BaseModel):
    min_direction_probability: float = Field(default=0.65, ge=0, le=1)
    min_direction_margin: float = Field(default=0.20, ge=0, le=1)
    max_noise_probability: float = Field(default=0.40, ge=0, le=1)
    max_reversal_probability: float = Field(default=0.35, ge=0, le=1)
    min_trend_strength: float = Field(default=1.0, ge=0, le=3)
    max_spread_pips: float = Field(default=2.0, ge=0, le=100000000)


class PaperDemoInput(BaseModel):
    initial_balance: float = Field(default=100000, gt=0, le=1000000000)
    size: float = Field(default=1000, gt=0, le=100000000)
    strategy: Literal["momentum", "rsi_mean_reversion", "ma_trend", "jev"] = "momentum"
    momentum_window_seconds: float = Field(default=5.0, ge=1, le=60)
    momentum_trigger_units: float = Field(default=0.6, gt=0, le=100000000)
    max_spread_units: float = Field(default=1.5, ge=0, le=100000000)
    take_profit_units: float = Field(default=1.0, gt=0, le=100000000)
    stop_loss_units: float = Field(default=1.0, gt=0, le=100000000)
    max_hold_seconds: float = Field(default=8.0, ge=1, le=600)
    cooldown_seconds: float = Field(default=2.0, ge=0, le=600)
    jev_signal_max_age_seconds: float = Field(default=3.0, ge=0.5, le=60)
    slippage_units: float = Field(default=0.0, ge=0, le=100000000)
    rsi_period: int = Field(default=14, ge=2, le=500)
    rsi_oversold: float = Field(default=30.0, ge=0, le=100)
    rsi_overbought: float = Field(default=70.0, ge=0, le=100)
    ma_fast_period: int = Field(default=5, ge=1, le=5000)
    ma_slow_period: int = Field(default=20, ge=2, le=5000)
    ma_min_gap_units: float = Field(default=0.2, ge=0, le=100000000)
    deterministic_supervisor_enabled: bool = False
    max_market_age_seconds: float = Field(default=5.0, ge=0.1, le=60)


class ObserverStartRequest(BaseModel):
    instrument_id: str = Field(default="USD_JPY", min_length=1, max_length=32)
    profile_name: str = Field(default="custom", min_length=1, max_length=80)
    profile: FeatureSelection
    with_jev: bool = False
    jev_every_seconds: float = Field(default=1.0, ge=0.25, le=60)
    signal_policy_name: str = Field(default="custom", min_length=1, max_length=80)
    signal_policy: SignalPolicyInput
    paper_demo: PaperDemoInput | None = None


class BacktestRequest(BaseModel):
    instrument_id: str = Field(default="USD_JPY", min_length=1, max_length=32)
    date: str = Field(pattern=r"^\d{8}$")
    profile_name: str = Field(default="custom", min_length=1, max_length=80)
    profile: FeatureSelection
    limit: int | None = Field(default=None, ge=1, le=10000)

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError as exc:
            raise ValueError("日付はYYYYMMDD形式で指定してください。") from exc
        return value


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


@app.get("/api/status")
async def get_status() -> dict[str, Any]:
    return controller.snapshot()


@app.get("/api/chart/history")
async def get_chart_history(
    instrument_id: str = "USD_JPY",
    interval: Literal["1min", "5min", "15min", "1hour"] = "1min",
    date: str = "",
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


@app.post("/api/backtest")
async def run_backtest(request: BacktestRequest) -> dict[str, Any]:
    try:
        instrument = get_instrument(request.instrument_id)
        if instrument.market_kind != "fx" or instrument.quote_currency != "JPY":
            raise ValueError("統計リプレイは現在、対円FXペアのみ対応しています。")
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
