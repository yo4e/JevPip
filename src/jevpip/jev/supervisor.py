from __future__ import annotations

from typing import Any, Iterable

from jevpip.broker.supervisor import JevSupervisorAdvice, validate_jev_supervisor_payload


PAUSE_THRESHOLD = 0.65
CAUTION_THRESHOLD = 0.60
STRATEGY_CONFIDENCE_THRESHOLD = 0.60


def _answer(response: dict[str, Any], name: str) -> dict[str, Any]:
    answers = response.get("answers")
    if not isinstance(answers, dict):
        return {}
    item = answers.get(name)
    return item if isinstance(item, dict) else {}


def _probability(response: dict[str, Any], name: str, *, fallback: float = 0.0) -> float:
    raw = _answer(response, name).get("noul", fallback)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(1.0, value))


def _choice_confidence(answer: dict[str, Any], choice: str) -> float:
    raw = answer.get("confidence")
    try:
        confidence = float(raw)
    except (TypeError, ValueError):
        probabilities = answer.get("probabilities")
        if isinstance(probabilities, dict):
            try:
                confidence = float(probabilities.get(choice, 0.0))
            except (TypeError, ValueError):
                confidence = 0.0
        else:
            confidence = 0.0
    return max(0.0, min(1.0, confidence))


def derive_jev_supervisor_advice(
    response: dict[str, Any],
    *,
    allowed_strategies: Iterable[str],
) -> tuple[JevSupervisorAdvice, dict[str, Any]]:
    """Compose narrow Jev answers into the fixed bounded supervisor schema.

    Jev never supplies quantity, TP/SL, leverage, arbitrary commands, or a free
    form reason. Thresholds, TTL, and final validation remain code-owned.
    """

    allowed = tuple(dict.fromkeys(str(name) for name in allowed_strategies))
    pause_probability = _probability(response, "supervisor_pause_entry")
    caution_probability = _probability(response, "supervisor_caution")

    if pause_probability >= PAUSE_THRESHOLD:
        state = "PAUSE_ENTRY"
        confidence = pause_probability
        ttl_seconds = 30
    elif caution_probability >= CAUTION_THRESHOLD:
        state = "CAUTION"
        confidence = caution_probability
        ttl_seconds = 20
    else:
        state = "NORMAL"
        confidence = min(1.0 - pause_probability, 1.0 - caution_probability)
        ttl_seconds = 15

    strategy: str | None = None
    strategy_answer = _answer(response, "supervisor_strategy")
    raw_choice = strategy_answer.get("choice")
    choice = str(raw_choice) if raw_choice is not None else ""
    strategy_confidence = _choice_confidence(strategy_answer, choice)
    if (
        state != "PAUSE_ENTRY"
        and choice in allowed
        and strategy_confidence >= STRATEGY_CONFIDENCE_THRESHOLD
    ):
        strategy = choice

    reason = (
        f"bounded pause={pause_probability:.3f} "
        f"caution={caution_probability:.3f}"
    )
    advice = validate_jev_supervisor_payload(
        {
            "state": state,
            "strategy": strategy,
            "confidence": confidence,
            "ttl_seconds": ttl_seconds,
            "reason": reason,
        },
        allowed_strategies=allowed,
    )
    return advice, {
        "pause_probability": pause_probability,
        "caution_probability": caution_probability,
        "strategy_choice": choice or None,
        "strategy_confidence": strategy_confidence,
        "pause_threshold": PAUSE_THRESHOLD,
        "caution_threshold": CAUTION_THRESHOLD,
        "strategy_confidence_threshold": STRATEGY_CONFIDENCE_THRESHOLD,
    }
