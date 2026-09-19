from __future__ import annotations


def question_specs(
    horizon: str = "5s",
    instrument_label: str = "the instrument",
) -> dict:
    """Raw TypeSafe question definitions, kept atomic and composable in code."""
    return {
        "direction": {
            "type": "choice",
            "instructions": f"Based only on the supplied state, where is {instrument_label} most likely to be after {horizon}?",
            "criteria": {
                "UP": "Meaningfully higher than now, beyond ordinary short-term noise.",
                "DOWN": "Meaningfully lower than now, beyond ordinary short-term noise.",
                "FLAT": "About where it is now, inside ordinary short-term noise.",
            },
        },
        "market_is_noisy": {
            "type": "noul",
            "instructions": "Is the supplied state too noisy or directionless for a short-term directional entry?",
        },
        "reversal_risk": {
            "type": "noul",
            "instructions": f"Does the current short-term move show meaningful risk of reversing before {horizon}?",
        },
        "trend_strength": {
            "type": "score",
            "instructions": "How strong and coherent is the short-term directional trend in the supplied state?",
            "criteria": ["No meaningful trend", "Weak", "Moderate", "Strong"],
        },
    }



def supervisor_question_specs(allowed_strategies: tuple[str, ...]) -> dict:
    """Bounded supervisor questions. They never ask Jev for an order action."""

    specs = {
        "supervisor_pause_entry": {
            "type": "noul",
            "instructions": (
                "Given the supplied technical state and external_context, is there "
                "enough short-lived risk that NEW paper-strategy entries should be "
                "paused? Do not decide order direction, quantity, TP/SL, or leverage."
            ),
        },
        "supervisor_caution": {
            "type": "noul",
            "instructions": (
                "Given the supplied technical state and external_context, should the "
                "paper strategy operate in a cautious regime even if new entries are "
                "not fully paused?"
            ),
        },
    }
    unique = tuple(dict.fromkeys(allowed_strategies))
    if unique:
        criteria = {
            "KEEP_CURRENT": "Keep the currently configured code strategy.",
            **{
                name: f"Select the existing allowlisted code strategy {name}."
                for name in unique
            },
        }
        specs["supervisor_strategy"] = {
            "type": "choice",
            "instructions": (
                "Which allowlisted code strategy best fits the supplied state? "
                "Choose KEEP_CURRENT if there is not strong evidence to switch."
            ),
            "criteria": criteria,
        }
    return specs
