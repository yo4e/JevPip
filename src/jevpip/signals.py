from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Signal = Literal["LONG", "SHORT", "WAIT"]
PositionAction = Literal["HOLD", "CLOSE"]

POSITION_CLOSE_PROBABILITY = 0.70
POSITION_CLOSE_MARGIN = 0.20


@dataclass(frozen=True, slots=True)
class SignalPolicy:
    min_direction_probability: float = 0.65
    min_direction_margin: float = 0.20
    max_noise_probability: float = 0.40
    max_reversal_probability: float = 0.35
    min_trend_strength: float = 1.0
    max_spread_pips: float = 2.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SignalPolicy":
        fields = cls.__dataclass_fields__
        return cls(**{key: raw[key] for key in fields if key in raw})


def _answer(response: dict[str, Any], name: str) -> dict[str, Any]:
    answers = response.get("answers")
    if not isinstance(answers, dict):
        return {}
    item = answers.get(name)
    return item if isinstance(item, dict) else {}


def normalize_jev_signal_inputs(response: dict[str, Any]) -> dict[str, float]:
    direction = _answer(response, "direction")
    probs = direction.get("probabilities") if isinstance(direction.get("probabilities"), dict) else {}
    noisy = _answer(response, "market_is_noisy")
    reversal = _answer(response, "reversal_risk")
    trend = _answer(response, "trend_strength")
    return {
        "up": float(probs.get("UP", 0.0)),
        "down": float(probs.get("DOWN", 0.0)),
        "flat": float(probs.get("FLAT", 0.0)),
        "noise": float(noisy.get("noul", 1.0)),
        "reversal": float(reversal.get("noul", 1.0)),
        "trend_strength": float(trend.get("score", 0.0)),
    }


def classify_direction_signal(
    response: dict[str, Any],
    policy: SignalPolicy,
) -> tuple[Signal, dict[str, Any]]:
    """Classify Jev direction without mixing in quality/supervisor questions.

    This is the paper entry direction gate. Spread and other deterministic risk
    limits remain code-owned elsewhere.
    """
    values = normalize_jev_signal_inputs(response)
    long_margin = values["up"] - values["down"]
    short_margin = values["down"] - values["up"]

    if (
        values["up"] >= policy.min_direction_probability
        and long_margin >= policy.min_direction_margin
    ):
        signal: Signal = "LONG"
    elif (
        values["down"] >= policy.min_direction_probability
        and short_margin >= policy.min_direction_margin
    ):
        signal = "SHORT"
    else:
        signal = "WAIT"

    return signal, {
        "up": values["up"],
        "down": values["down"],
        "flat": values["flat"],
        "long_margin": long_margin,
        "short_margin": short_margin,
        "policy": {
            "min_direction_probability": policy.min_direction_probability,
            "min_direction_margin": policy.min_direction_margin,
        },
    }


def classify_research_signal(
    response: dict[str, Any],
    spread_pips: float,
    policy: SignalPolicy,
) -> tuple[Signal, dict[str, Any]]:
    """Turn Jev probabilities into a research label only. Never places orders."""
    values = normalize_jev_signal_inputs(response)
    common_ok = (
        spread_pips <= policy.max_spread_pips
        and values["noise"] <= policy.max_noise_probability
        and values["reversal"] <= policy.max_reversal_probability
        and values["trend_strength"] >= policy.min_trend_strength
    )
    long_margin = values["up"] - values["down"]
    short_margin = values["down"] - values["up"]
    if (
        common_ok
        and values["up"] >= policy.min_direction_probability
        and long_margin >= policy.min_direction_margin
    ):
        signal: Signal = "LONG"
    elif (
        common_ok
        and values["down"] >= policy.min_direction_probability
        and short_margin >= policy.min_direction_margin
    ):
        signal = "SHORT"
    else:
        signal = "WAIT"
    return signal, {
        **values,
        "spread_pips": spread_pips,
        "long_margin": long_margin,
        "short_margin": short_margin,
        "policy": {
            name: getattr(policy, name) for name in policy.__dataclass_fields__
        },
    }



def classify_position_action(
    response: dict[str, Any],
) -> tuple[PositionAction | None, dict[str, Any]]:
    """Classify a bounded HOLD/CLOSE answer for an already-open paper position.

    CLOSE is deliberately harder to accept than HOLD. Thresholds are code-owned;
    Jev cannot choose confirmation count, minimum hold time, or the position horizon.
    """

    answer = _answer(response, "position_action")
    raw_choice = answer.get("choice")
    choice = str(raw_choice) if raw_choice is not None else ""
    if choice not in {"HOLD", "CLOSE"}:
        return None, {"reason": "missing_or_invalid_position_action"}

    probabilities = answer.get("probabilities")
    probs = probabilities if isinstance(probabilities, dict) else {}

    def probability(name: str) -> float:
        raw = probs.get(name)
        if raw is None and choice == name:
            raw = answer.get("confidence")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.0
        return max(0.0, min(1.0, value))

    hold_probability = probability("HOLD")
    close_probability = probability("CLOSE")
    close_margin = close_probability - hold_probability
    accepted: PositionAction = "HOLD"
    reason = "bounded_hold"
    if (
        choice == "CLOSE"
        and close_probability >= POSITION_CLOSE_PROBABILITY
        and close_margin >= POSITION_CLOSE_MARGIN
    ):
        accepted = "CLOSE"
        reason = "bounded_close"

    return accepted, {
        "choice": choice,
        "hold_probability": hold_probability,
        "close_probability": close_probability,
        "close_margin": close_margin,
        "close_probability_threshold": POSITION_CLOSE_PROBABILITY,
        "close_margin_threshold": POSITION_CLOSE_MARGIN,
        "reason": reason,
    }
