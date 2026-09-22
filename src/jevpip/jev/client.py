from __future__ import annotations

import logging
from typing import Any

from .questions import position_question_specs, question_specs, supervisor_question_specs
from .autopilot import question_specs as autopilot_questions


def _system_one_state(state: dict[str, Any]) -> dict[str, Any]:
    """Remove event candidate tables that are already carried by questions.

    The caller's full state remains untouched so target decoding and broker-side
    validation continue to use the exact generated plans.
    """
    autopilot = state.get("autopilot")
    if not isinstance(autopilot, dict) or autopilot.get("style") != "event":
        return state

    compact_state = dict(state)
    compact_autopilot = dict(autopilot)
    compact_autopilot.pop("targets", None)
    # Event triggers are monitored locally from raw ticks. Jev only needs the
    # current quote plus multi-timeframe structure/indicators, so do not spend
    # TypeSafe context on the tick tape or the duplicate legacy 1m bar list.
    compact_autopilot.pop("recent_ticks", None)
    compact_autopilot.pop("closed_1m_bars", None)
    event_plan = compact_autopilot.get("event_plan")
    if isinstance(event_plan, dict):
        compact_event_plan = dict(event_plan)
        for key in ("trade_plans", "wake_plans", "expiry_plans"):
            compact_event_plan.pop(key, None)
        compact_autopilot["event_plan"] = compact_event_plan
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
