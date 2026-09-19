from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SupervisorState = Literal["NORMAL", "CAUTION", "PAUSE_ENTRY", "PAUSE_ALL"]


@dataclass(frozen=True, slots=True)
class SupervisorDecision:
    state: SupervisorState
    reason: str
    allow_entry: bool


def deterministic_supervisor(
    *,
    market_status: str | None,
    spread_units: float,
    max_spread_units: float,
    market_age_seconds: float | None = None,
    max_market_age_seconds: float = 5.0,
) -> SupervisorDecision:
    """Code-only safety supervisor used as a baseline for future Jev supervision.

    It can only tighten behaviour. It never increases size, widens risk limits,
    or creates orders.
    """
    status = (market_status or "").upper()
    if status and status != "OPEN":
        return SupervisorDecision("PAUSE_ALL", f"market_status:{status}", False)

    if (
        market_age_seconds is not None
        and max_market_age_seconds >= 0
        and market_age_seconds > max_market_age_seconds
    ):
        return SupervisorDecision("PAUSE_ALL", "stale_market_data", False)

    if max_spread_units >= 0 and spread_units > max_spread_units:
        return SupervisorDecision("PAUSE_ENTRY", "spread_over_limit", False)

    caution_level = max_spread_units * 0.8
    if max_spread_units > 0 and spread_units >= caution_level:
        return SupervisorDecision("CAUTION", "spread_near_limit", True)

    return SupervisorDecision("NORMAL", "ok", True)
