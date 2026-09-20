from __future__ import annotations

import logging
from typing import Any

from .questions import position_question_specs, question_specs, supervisor_question_specs


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
        from typesafe_sdk import TypeSafeClient

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
        with TypeSafeClient(api_key=self.api_key) as client:
            response = client.system_one(state=state, questions=questions, model=self.model)
        if hasattr(response, "model_dump"):
            return response.model_dump(mode="json")
        raise TypeError(f"Unexpected TypeSafe response type: {type(response)!r}")
