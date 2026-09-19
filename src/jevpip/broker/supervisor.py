from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Literal, Mapping, Any

from jevpip.context import ExternalContextItem

SupervisorState = Literal["NORMAL", "CAUTION", "PAUSE_ENTRY", "PAUSE_ALL"]

_STATE_RANK: dict[SupervisorState, int] = {
    "NORMAL": 0,
    "CAUTION": 1,
    "PAUSE_ENTRY": 2,
    "PAUSE_ALL": 3,
}


@dataclass(frozen=True, slots=True)
class SupervisorDecision:
    state: SupervisorState
    reason: str
    allow_entry: bool


@dataclass(frozen=True, slots=True)
class JevSupervisorAdvice:
    """Validated advisory output from Jev.

    This object is intentionally incapable of carrying order side, quantity,
    TP/SL, leverage, or arbitrary code. It can only tighten/shape the paper
    strategy through a bounded supervisor state and an allowlisted strategy.
    """

    state: SupervisorState
    strategy: str | None
    confidence: float
    ttl_seconds: int
    reason: str


@dataclass(frozen=True, slots=True)
class SupervisorPlan:
    """Effective supervisor plan after deterministic and Jev advice are merged."""

    state: SupervisorState
    allow_entry: bool
    reason: str
    strategy: str | None
    confidence: float | None
    ttl_seconds: int | None


def _state(value: object) -> SupervisorState:
    text = str(value or "").upper()
    if text not in _STATE_RANK:
        raise ValueError(f"Unknown supervisor state: {value!r}")
    return text  # type: ignore[return-value]


def validate_jev_supervisor_payload(
    payload: Mapping[str, Any],
    *,
    allowed_strategies: Iterable[str],
    max_ttl_seconds: int = 300,
) -> JevSupervisorAdvice:
    """Validate a fixed Jev supervisor schema.

    The payload cannot create an arbitrary strategy. A strategy, when present,
    must already exist in the caller-provided allowlist.
    """

    state = _state(payload.get("state"))
    allowed = set(allowed_strategies)
    raw_strategy = payload.get("strategy")
    if raw_strategy is None or raw_strategy == "" or raw_strategy == "NONE":
        strategy = None
    elif not isinstance(raw_strategy, str):
        raise ValueError("strategy must be a string or null")
    else:
        strategy = raw_strategy
    if strategy is not None and strategy not in allowed:
        raise ValueError(f"Strategy is not allowlisted: {strategy!r}")

    try:
        confidence = float(payload.get("confidence"))
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be a number") from exc
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")

    raw_ttl = payload.get("ttl_seconds")
    if isinstance(raw_ttl, bool):
        raise ValueError("ttl_seconds must be an integer")
    if isinstance(raw_ttl, int):
        ttl_seconds = raw_ttl
    elif isinstance(raw_ttl, str) and raw_ttl.strip().isdigit():
        ttl_seconds = int(raw_ttl.strip())
    else:
        raise ValueError("ttl_seconds must be an integer")
    if ttl_seconds < 1 or ttl_seconds > max_ttl_seconds:
        raise ValueError(f"ttl_seconds must be between 1 and {max_ttl_seconds}")

    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValueError("reason is required")
    if len(reason) > 500:
        raise ValueError("reason is too long")

    return JevSupervisorAdvice(
        state=state,
        strategy=strategy,
        confidence=confidence,
        ttl_seconds=ttl_seconds,
        reason=reason,
    )


def combine_supervisors(
    deterministic: SupervisorDecision,
    jev: JevSupervisorAdvice | None,
) -> SupervisorPlan:
    """Merge supervisors so Jev can never relax the deterministic safety gate."""

    deterministic_state = _state(deterministic.state)
    if jev is None:
        return SupervisorPlan(
            state=deterministic_state,
            allow_entry=deterministic.allow_entry,
            reason=f"code:{deterministic.reason}",
            strategy=None,
            confidence=None,
            ttl_seconds=None,
        )

    effective_state = (
        deterministic_state
        if _STATE_RANK[deterministic_state] >= _STATE_RANK[jev.state]
        else jev.state
    )
    allow_entry = deterministic.allow_entry and _STATE_RANK[effective_state] < _STATE_RANK["PAUSE_ENTRY"]

    # Strategy selection is advisory and only meaningful while entries remain
    # possible. It never changes size, TP/SL, spread limits, or other risk caps.
    strategy = jev.strategy if allow_entry else None

    return SupervisorPlan(
        state=effective_state,
        allow_entry=allow_entry,
        reason=f"code:{deterministic.reason}; jev:{jev.reason}",
        strategy=strategy,
        confidence=jev.confidence,
        ttl_seconds=jev.ttl_seconds,
    )




def combine_code_supervisors(*decisions: SupervisorDecision) -> SupervisorDecision:
    """Merge deterministic supervisors by taking the strictest state."""

    if not decisions:
        return SupervisorDecision("NORMAL", "ok", True)
    strictest = max(decisions, key=lambda item: _STATE_RANK[_state(item.state)])
    reasons = [item.reason for item in decisions if item.reason not in {"ok", "disabled"}]
    return SupervisorDecision(
        state=_state(strictest.state),
        reason="; ".join(reasons) if reasons else strictest.reason,
        allow_entry=all(item.allow_entry for item in decisions)
        and _STATE_RANK[_state(strictest.state)] < _STATE_RANK["PAUSE_ENTRY"],
    )


def deterministic_event_supervisor(
    items: Iterable[ExternalContextItem],
    *,
    as_of: datetime,
    high_lead: timedelta = timedelta(minutes=30),
    high_lag: timedelta = timedelta(minutes=15),
    medium_lead: timedelta = timedelta(minutes=10),
    medium_lag: timedelta = timedelta(minutes=5),
) -> SupervisorDecision:
    """Code-only scheduled-event guard used as the external-context baseline."""

    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    at = as_of.astimezone(timezone.utc)

    high_hits: list[ExternalContextItem] = []
    medium_hits: list[ExternalContextItem] = []

    for item in items:
        if item.kind != "scheduled_event" or item.scheduled_at is None:
            continue
        if not item.known_at(at):
            continue
        event_at = item.scheduled_at.astimezone(timezone.utc)
        if item.risk in {"critical", "high"}:
            if event_at - high_lead <= at <= event_at + high_lag:
                high_hits.append(item)
        elif item.risk == "medium":
            if event_at - medium_lead <= at <= event_at + medium_lag:
                medium_hits.append(item)

    if high_hits:
        names = ",".join(item.source_id for item in high_hits[:3])
        return SupervisorDecision("PAUSE_ENTRY", f"scheduled_event_high:{names}", False)
    if medium_hits:
        names = ",".join(item.source_id for item in medium_hits[:3])
        return SupervisorDecision("CAUTION", f"scheduled_event_medium:{names}", True)
    return SupervisorDecision("NORMAL", "event_ok", True)


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
