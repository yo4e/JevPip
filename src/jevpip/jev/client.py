from __future__ import annotations

import logging
from typing import Any

from .questions import position_question_specs, question_specs, supervisor_question_specs
from .autopilot import question_specs as autopilot_questions


BOUNDED_TIMEFRAME_BAR_LIMIT = 16
BOUNDED_RECENT_EXECUTION_LIMIT = 10


def _compact_bounded_bar(bar: object) -> dict[str, Any] | None:
    if not isinstance(bar, dict):
        return None
    fields = ("open_time", "end_time", "open", "high", "low", "close")
    return {key: bar[key] for key in fields if key in bar}


def _compact_bounded_timeframes(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for interval, raw_view in value.items():
        if not isinstance(raw_view, dict):
            continue
        bars = raw_view.get("closed_bars")
        recent = bars[-BOUNDED_TIMEFRAME_BAR_LIMIT:] if isinstance(bars, list) else []
        compact_bars = [row for row in (_compact_bounded_bar(bar) for bar in recent) if row is not None]
        current = _compact_bounded_bar(raw_view.get("current_bar"))
        result[str(interval)] = {
            "interval": raw_view.get("interval", interval),
            "closed_bars_available": raw_view.get("closed_bars_available", len(compact_bars)),
            "closed_bars": compact_bars,
            "current_bar": current,
            "indicators": dict(raw_view.get("indicators", {})) if isinstance(raw_view.get("indicators"), dict) else {},
        }
    return result


def _system_one_state(state: dict[str, Any]) -> dict[str, Any]:
    """Bound heavy Jev contexts without mutating caller/broker state.

    Event and Fifty+ keep their code-owned semantics and dedicated state while
    raw tick history and long repeated lists are omitted from the SDK payload.
    """
    autopilot = state.get("autopilot")
    if not isinstance(autopilot, dict):
        return state
    style = autopilot.get("style")
    if style not in {"event", "fifty"}:
        return state

    compact_state = dict(state)
    compact_autopilot = dict(autopilot)
    # Event/Fifty+ execution semantics are code-owned. Jev needs the current
    # quote and bounded multi-timeframe structure, not the raw tick tape or the
    # duplicate legacy 1m bar list.
    compact_autopilot.pop("recent_ticks", None)
    compact_autopilot.pop("closed_1m_bars", None)
    compact_autopilot["timeframes"] = _compact_bounded_timeframes(
        compact_autopilot.get("timeframes")
    )
    recent_executions = compact_autopilot.get("recent_executions")
    if isinstance(recent_executions, list):
        compact_autopilot["recent_executions"] = recent_executions[:BOUNDED_RECENT_EXECUTION_LIMIT]

    if style == "event":
        # Event trade/wake/expiry candidates are already carried by Choice
        # questions. Keep the full generated plans only in caller/broker state.
        compact_autopilot.pop("targets", None)
        event_plan = compact_autopilot.get("event_plan")
        if isinstance(event_plan, dict):
            compact_event_plan = dict(event_plan)
            for key in ("trade_plans", "wake_plans", "expiry_plans"):
                compact_event_plan.pop(key, None)
            compact_autopilot["event_plan"] = compact_event_plan

    # Fifty+ keeps its dedicated race/outcome context intact. Its two bounded
    # UP/DOWN targets also remain available in state and Choice criteria.
    compact_state["autopilot"] = compact_autopilot
    return compact_state


class JevClient:
    """Thin adapter so the rest of JevPip does not depend on SDK response internals."""

    def __init__(self, api_key: str, model: str = "jev-latest") -> None:
        if not api_key:
            raise ValueError("TYPESAFE_API_KEY is required")
        self.api_key = api_key
        self.model = model
        logging.getLogger("typesafe_sdk").setLevel(logging.WARNING)

    def decide(
        self,
        state: dict[str, Any],
        horizon: str = "5s",
        *,
        supervisor_strategies: tuple[str, ...] = (),
        instrument_label: str = "the instrument",
    ) -> dict[str, Any]:
        from typesafe_sdk import RetryPolicy, TypeSafeClient

        if "autopilot" in state:
            questions = autopilot_questions(state)
        else:
            questions = question_specs(horizon, instrument_label)
        paper_context = state.get("paper_context")
        if (
            isinstance(paper_context, dict)
            and paper_context.get("jev_direct_enabled") is True
            and isinstance(paper_context.get("position"), dict)
        ):
            questions.update(position_question_specs())
        if supervisor_strategies:
            questions.update(supervisor_question_specs(supervisor_strategies))
        options = {"timeout": 10.0, "retry": RetryPolicy(max_retries=0)} if "autopilot" in state else {}
        api_state = _system_one_state(state)
        with TypeSafeClient(api_key=self.api_key, **options) as client:
            response = client.system_one(state=api_state, questions=questions, model=self.model)
        if hasattr(response, "model_dump"):
            return response.model_dump(mode="json")
        raise TypeError(f"Unexpected TypeSafe response type: {type(response)!r}")
