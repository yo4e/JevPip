from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")
    autopilot_enabled: bool = False
    autopilot_style: Literal["daytrade", "scalp", "fifty", "event"] = "daytrade"
    autopilot_fundamentals: bool = False
    autopilot_horizon_seconds: Literal[30, 120, 600, 1800] = 600
    autopilot_fifty_target_units: float = Field(default=5.0, gt=0, le=100000000)
    autopilot_fifty_target_jpy: float = Field(default=500.0, gt=0, le=1000000000)
    autopilot_fifty_reentry_seconds: float = Field(default=60.0, ge=0, le=3600)
    autopilot_fifty_oracle: Literal[
        "jev",
        "moon_phase",
        "zodiac_polarity",
        "tarot",
        "coin_flip",
    ] = "jev"
    autopilot_ttl_seconds: float = Field(default=5, gt=0, le=60)
    autopilot_confirmations: int = Field(default=2, ge=1, le=5)
    autopilot_max_quantity: float | None = Field(default=None, gt=0, le=100000000)
    autopilot_max_notional: float | None = Field(default=None, gt=0, le=1000000000)
    autopilot_max_drawdown: float | None = Field(default=None, gt=0, le=1000000000)
    autopilot_max_drawdown_pct: float | None = Field(default=0.20, gt=0, le=1)
    autopilot_max_risk_pct: float = Field(default=0.01, gt=0, le=0.25)
    autopilot_max_change: float | None = Field(default=None, gt=0, le=100000000)
    autopilot_entry_loss: float | None = Field(default=None, gt=0, le=1000000000)
    autopilot_max_spread: float | None = Field(default=None, ge=0, le=100000000)
    autopilot_min_confidence: float | None = Field(default=None, ge=0, le=1)
    autopilot_cooldown_seconds: float | None = Field(default=None, ge=0, le=3600)
    autopilot_max_hold_seconds: float | None = Field(default=None, gt=0, le=86400)
    autopilot_take_profit_units: float | None = Field(default=None, gt=0, le=100000000)
    autopilot_stop_loss_units: float | None = Field(default=None, gt=0, le=100000000)
    initial_balance: float = Field(default=100000, gt=0, le=1000000000)
    size: float = Field(default=1000, gt=0, le=100000000)
    paper_leverage: float = Field(default=25.0, ge=1, le=25)
    strategy: Literal["momentum", "rsi_mean_reversion", "ma_trend", "jev"] = "momentum"
    strategy_enabled: bool = True
    momentum_window_seconds: float = Field(default=5.0, ge=1, le=60)
    momentum_trigger_units: float = Field(default=0.6, gt=0, le=100000000)
    max_spread_units: float = Field(default=1.0, ge=0, le=100000000)
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
    strategy_bar_seconds: Literal[0, 5, 15, 60, 300] = 0


class CredentialSettingsInput(BaseModel):
    typesafe_api_key: str | None = Field(default=None, max_length=4096)
    gmo_fx_api_key: str | None = Field(default=None, max_length=4096)
    gmo_fx_api_secret: str | None = Field(default=None, max_length=4096)
    clear_typesafe_api_key: bool = False
    clear_gmo_private_credentials: bool = False

    @field_validator(
        "typesafe_api_key",
        "gmo_fx_api_key",
        "gmo_fx_api_secret",
    )
    @classmethod
    def normalize_secret_input(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ObserverStartRequest(BaseModel):
    instrument_id: str = Field(default="USD_JPY", min_length=1, max_length=32)
    paper_decision_mode: Literal["jev", "strategy", "spiritual"] | None = None
    profile_name: str = Field(default="custom", min_length=1, max_length=80)
    profile: FeatureSelection
    with_jev: bool = False
    jev_every_seconds: float = Field(default=900.0, ge=0.25, le=3600)
    signal_policy_name: str = Field(default="custom", min_length=1, max_length=80)
    signal_policy: SignalPolicyInput
    paper_demo: PaperDemoInput | None = None


class JevReplayPreviewRequest(BaseModel):
    instrument_id: str = Field(default="USD_JPY", min_length=1, max_length=32)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    start_time: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}:\d{2}$")
    duration_seconds: int = Field(default=60, ge=1, le=86400)
    cadence_seconds: Literal[1, 2, 5, 10, 30, 60, 300, 900] = 1
    event_driven: bool = False


class JevReplayRunRequest(JevReplayPreviewRequest):
    profile: FeatureSelection
    signal_policy: SignalPolicyInput
    paper_demo: PaperDemoInput
    acknowledged_token_use: bool = False


class RawCompareRequest(BaseModel):
    instrument_id: str = Field(min_length=1, max_length=32)
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    strategies: list[Literal["momentum", "rsi_mean_reversion", "ma_trend"]] = Field(
        default_factory=lambda: ["momentum", "rsi_mean_reversion", "ma_trend"],
        min_length=1,
        max_length=3,
    )
    initial_balance: float = Field(default=100000, gt=0, le=1000000000)
    size: float | None = Field(default=None, gt=0, le=100000000)
    supervisor: bool = True
    bar_seconds: Literal[0, 5, 15, 60, 300] = 0


class StrategyBacktestRequest(BaseModel):
    instrument_id: str = Field(default="USD_JPY", min_length=1, max_length=32)
    date: str = Field(pattern=r"^\d{8}$")
    strategy: Literal["momentum", "rsi_mean_reversion", "ma_trend"]
    initial_balance: float = Field(default=100000, gt=0, le=1000000000)
    size: float = Field(gt=0, le=100000000)
    max_spread_units: float = Field(ge=0, le=100000000)
    take_profit_units: float = Field(gt=0, le=100000000)
    stop_loss_units: float = Field(gt=0, le=100000000)
    slippage_units: float = Field(default=0, ge=0, le=100000000)
    momentum_lookback_bars: int = Field(default=1, ge=1, le=1440)
    momentum_trigger_units: float = Field(gt=0, le=100000000)
    rsi_period: int = Field(default=14, ge=2, le=500)
    rsi_oversold: float = Field(default=30, ge=0, le=100)
    rsi_overbought: float = Field(default=70, ge=0, le=100)
    ma_fast_period: int = Field(default=5, ge=1, le=5000)
    ma_slow_period: int = Field(default=20, ge=2, le=5000)
    ma_min_gap_units: float = Field(default=0.2, ge=0, le=100000000)
    max_hold_bars: int = Field(default=8, ge=1, le=1440)
    cooldown_bars: int = Field(default=1, ge=0, le=1440)
    supervisor_enabled: bool = True
    limit: int | None = Field(default=None, ge=2, le=10000)

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError as exc:
            raise ValueError("日付はYYYYMMDD形式で指定してください。") from exc
        return value


class SpiritualBacktestRequest(BaseModel):
    instrument_id: str = Field(default="USD_JPY", min_length=1, max_length=32)
    date: str = Field(pattern=r"^\d{8}$")
    oracle: Literal["moon_phase", "zodiac_polarity", "tarot", "coin_flip"] = "moon_phase"
    initial_balance: float = Field(default=100000, gt=0, le=1000000000)
    size: float = Field(gt=0, le=100000000)
    paper_leverage: float = Field(default=25.0, ge=1, le=25)
    target_units: float = Field(default=10.0, gt=0, le=100000000)
    target_jpy: float = Field(default=500.0, gt=0, le=1000000000)
    reentry_seconds: float = Field(default=60.0, ge=0, le=3600)
    max_spread_units: float = Field(default=1.0, ge=0, le=100000000)
    max_drawdown_pct: float = Field(default=0.20, gt=0, le=1)
    slippage_units: float = Field(default=0.0, ge=0, le=100000000)
    limit: int | None = Field(default=None, ge=2, le=10000)

    @field_validator("date")
    @classmethod
    def validate_date(cls, value: str) -> str:
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError as exc:
            raise ValueError("日付はYYYYMMDD形式で指定してください。") from exc
        return value


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
