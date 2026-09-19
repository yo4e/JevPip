from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Signal = Literal["LONG", "SHORT", "WAIT"]


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
