from __future__ import annotations

import logging
from typing import Any

from .questions import question_specs, supervisor_question_specs


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
    ) -> dict[str, Any]:
        from typesafe_sdk import TypeSafeClient

        questions = question_specs(horizon)
        if supervisor_strategies:
            questions.update(supervisor_question_specs(supervisor_strategies))
        with TypeSafeClient(api_key=self.api_key) as client:
            response = client.system_one(state=state, questions=questions, model=self.model)
        if hasattr(response, "model_dump"):
            return response.model_dump(mode="json")
        raise TypeError(f"Unexpected TypeSafe response type: {type(response)!r}")
