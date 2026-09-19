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
) -> SupervisorDecision:
    """Fail closed on a closed market and gate entries on spread.

    CAUTION begins at 80% of the configured max spread. This does not change
    position size or risk limits; it is a visible baseline state for future
    Jev-supervisor comparisons.
    """
    status = (market_status or "").upper()
    if status and status != "OPEN":
        return SupervisorDecision("PAUSE_ALL", f"market_status:{status}", False)

    if max_spread_units >= 0 and spread_units > max_spread_units:
        return SupervisorDecision("PAUSE_ENTRY", "spread_over_limit", False)

    caution_level = max_spread_units * 0.8
    if max_spread_units > 0 and spread_units >= caution_level:
        return SupervisorDecision("CAUTION", "spread_near_limit", True)

    return SupervisorDecision("NORMAL", "ok", True)
