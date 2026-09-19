from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from importlib.resources import files
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, field_validator

from jevpip.config import Settings, list_profiles, list_signal_policies
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
    max_spread_pips: float = Field(default=2.0, ge=0, le=100)


class ObserverStartRequest(BaseModel):
    profile_name: str = Field(default="custom", min_length=1, max_length=80)
    profile: FeatureSelection
    with_jev: bool = False
    jev_every_seconds: float = Field(default=1.0, ge=0.25, le=60)
    signal_policy_name: str = Field(default="custom", min_length=1, max_length=80)
    signal_policy: SignalPolicyInput


class BacktestRequest(BaseModel):
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
    description="GMO外国為替FX × TypeSafe Jev のローカル研究UI",
    lifespan=lifespan,
)


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html = files("jevpip.web").joinpath("index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/api/config")
async def get_config() -> dict[str, Any]:
    return {
        "profiles": list_profiles(),
        "signal_policies": list_signal_policies(),
        "typesafe_api_key_configured": bool(settings.typesafe_api_key),
        "live_trading_available": False,
    }


@app.get("/api/status")
async def get_status() -> dict[str, Any]:
    return controller.snapshot()


@app.post("/api/observer/start")
async def start_observer(request: ObserverStartRequest) -> dict[str, Any]:
    try:
        await controller.start_observer(
            profile_name=request.profile_name,
            profile=request.profile.model_dump(),
            with_jev=request.with_jev,
            jev_every_seconds=request.jev_every_seconds,
            signal_policy_name=request.signal_policy_name,
            signal_policy=SignalPolicy(**request.signal_policy.model_dump()),
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return controller.snapshot()


@app.post("/api/observer/stop")
async def stop_observer() -> dict[str, Any]:
    await controller.stop_observer()
    return controller.snapshot()


@app.post("/api/backtest")
async def run_backtest(request: BacktestRequest) -> dict[str, Any]:
    try:
        return await controller.run_backtest(
            date=request.date,
            profile_name=request.profile_name,
            profile=request.profile.model_dump(),
            limit=request.limit,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"GMO KLineリプレイに失敗しました: {type(exc).__name__}: {exc}",
        ) from exc


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
