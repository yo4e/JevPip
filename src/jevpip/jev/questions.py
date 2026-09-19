from __future__ import annotations


def question_specs(horizon: str = "5s") -> dict:
    """Raw TypeSafe question definitions, kept atomic and composable in code."""
    return {
        "direction": {
            "type": "choice",
            "instructions": f"Based only on the supplied state, where is USD/JPY most likely to be after {horizon}?",
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
