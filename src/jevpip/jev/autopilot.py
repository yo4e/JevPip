"""Bounded Jev policy. The model selects a target; code owns numbers and clocks."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any
from uuid import uuid4

REASONS = {
    "NO_EDGE": "No sufficiently clear opportunity after transaction costs.",
    "COST_TOO_HIGH": "Likely movement is insufficient to cover costs.",
    "TREND": "A sustained directional opportunity over the supplied horizon.",
    "REVERSAL": "Evidence that the market direction has changed.",
    "REDUCE_RISK": "Reduce or exit existing exposure based on future risk.",
    "KEEP_THESIS": "The existing position thesis remains valid; avoid turnover.",
    "FIFTY_PLUS": "Fifty+ forced-direction round; code owns the symmetric exit.",
}


def finite_decimal(value: object, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"invalid {name}")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"invalid {name}") from exc
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError(f"invalid {name}")
    return result


def question_specs(state: dict[str, Any]) -> dict[str, Any]:
    policy = state["autopilot"]
    style = policy.get("style", "daytrade")
    if style == "fifty":
        fifty = policy["fifty_plus"]
        target_value = float(fifty["target_value"])
        target_label = str(fifty["target_label"])
        target_text = f"{target_value:g} {target_label}"
        target_instructions = (
            f"Fifty+ round: the configured symmetric NET profit/loss width is {target_text}. "
            "Evaluate TWO INDEPENDENT hypothetical trades from the same current conditions. "
            f"For the LONG candidate, judge whether that LONG's own net +{target_text} "
            f"take-profit is likely to be reached before its own net -{target_text} stop-loss. "
            f"Independently, for the SHORT candidate, judge whether that SHORT's own net "
            f"+{target_text} take-profit is likely to be reached before its own net "
            f"-{target_text} stop-loss. Then choose the side with the stronger TP-before-SL "
            "case. LONG losing does NOT imply SHORT would have won, and the two directional "
            "win probabilities are not complements. You MUST choose exactly one option from "
            "`autopilot.targets`: UP or DOWN. UP maps to one LONG position and DOWN maps "
            "to one SHORT position. Each option includes a `directional_race` computed by "
            "code from the current BID/ASK, fixed quantity, configured fee/slippage, and the "
            "same net-PnL equation used by the broker. Its reference exit quote thresholds "
            "describe entry at the supplied basis quote; actual execution still uses the "
            "fresh executable quote when the answer becomes available, so do not assume "
            "future spread is fixed. There is no abstain, FLAT, KEEP, position sizing, or "
            "TP/SL adjustment decision. Use the supplied trader context broadly: current "
            "quote, recent ticks, 1m/5m/15m/1h price structure and indicators, clock, "
            "account/PnL history, recent executions, costs, constraints, and any supplied "
            "external context. The `fifty_plus.outcome_history` block contains only "
            "past completed answer keys known before this decision, including recent paired "
            "LONG/SHORT TP-vs-SL outcomes, aggregate rates, and confidence-band history. "
            "Use that empirical history when it is informative, but do not treat it as a "
            "mandatory rule or assume a small sample generalizes. Decide for yourself which "
            "information is useful, irrelevant, noisy, or conflicting; no technical indicator "
            "or past result is a mandatory rule. The UP/DOWN Choice probabilities are relative "
            "choice preferences and "
            "must not be interpreted as calibrated LONG/SHORT win probabilities. Confidence "
            "is not a measured win rate."
        )
    elif style == "scalp":
        target_instructions = (
            "Select the desired TOTAL paper position from `autopilot.targets` for a "
            "short-horizon scalping decision. Use the supplied trader context broadly: "
            "current quote, recent ticks, 1m/5m/15m/1h price structure and indicators, "
            "clock, account/PnL history, recent executions, costs, constraints, and any "
            "supplied external context. Decide for yourself which information is useful, "
            "irrelevant, noisy, or conflicting; no technical indicator or past result is "
            "a mandatory rule. Choose the position that is appropriate now; the system "
            "will ask again at its next scheduled review. Do not trade merely to be active. "
            "A new or larger position is worthwhile only when the prospective move can "
            "plausibly exceed round-trip costs. KEEP means retain exactly the current "
            "quantity. FLAT means close it or remain flat when no short-term edge is "
            "worthwhile. Confidence is not a measured win rate."
        )
    else:
        target_instructions = (
            "Select the desired TOTAL paper position from `autopilot.targets`. "
            "Use the supplied trader context broadly: current quote, recent ticks, "
            "1m/5m/15m/1h price structure and indicators, clock, account/PnL history, "
            "recent executions, costs, constraints, and any supplied external context. "
            "Decide for yourself which information is useful, irrelevant, noisy, or "
            "conflicting; no technical indicator or past result is a mandatory rule. "
            "Choose the position that is appropriate now; the system will ask again at "
            "its next scheduled review. Review periodically "
            "but trade only when the prospective benefit justifies the transition cost. "
            "KEEP means retain exactly the current quantity. FLAT means close it. "
            "Use FLAT when no position is worthwhile and KEEP for an unchanged thesis. "
            "Confidence is not a measured trading win rate."
        )
    questions = {
        "target_position": {
            "type": "choice",
            "instructions": target_instructions,
            "criteria": {
                key: value for key, value in policy["targets"].items()
            },
        },
    }
    if style != "fifty":
        questions["decision_factor"] = {
            "type": "choice",
            "instructions": "Which supplied market/account factor is most relevant to the current paper position decision?",
            "criteria": REASONS,
        }
    return questions


def _choice(answer: object, allowed: set[str]) -> tuple[str, float]:
    if not isinstance(answer, dict) or answer.get("choice") not in allowed:
        raise ValueError("unsupported target choice")
    confidence = answer.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("invalid target confidence")
    if not isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("invalid target confidence")
    probabilities = answer.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != allowed:
        raise ValueError("invalid target probabilities")
    values = [finite_decimal(v, "probability") for v in probabilities.values()]
    if any(v > 1 for v in values) or abs(sum(values) - 1) > Decimal("0.0001"):
        raise ValueError("invalid target probabilities")
    if finite_decimal(probabilities[answer["choice"]], "probability") < max(values):
        raise ValueError("target choice disagrees with probabilities")
    return answer["choice"], float(confidence)


def decode_target(
    answer: dict[str, Any], state: dict[str, Any], *,
    requested_at: datetime, available_at: datetime,
) -> dict[str, Any]:
    policy = state["autopilot"]
    answers = answer.get("answers", {})
    if not isinstance(answers, dict):
        raise ValueError("missing target answers")
    choice, confidence = _choice(answers.get("target_position"), set(policy["targets"]))
    if policy.get("style") == "fifty":
        factor = "FIFTY_PLUS"
    else:
        factor, _ = _choice(answers.get("decision_factor"), set(REASONS))
    target = policy["targets"][choice]
    expires_at = min(requested_at, datetime.fromisoformat(policy["as_of"])) + timedelta(seconds=policy["ttl_seconds"])
    return {
        "schema_version": 1,
        "decision_id": uuid4().hex,
        "session_id": policy["session_id"],
        "account_version": policy["account_version"],
        "instrument_id": policy["instrument_id"],
        "target_side": target["side"],
        "target_quantity": target["quantity"],
        "choice": choice,
        "confidence": confidence,
        "reason": factor,
        "basis_market_timestamp": policy["as_of"],
        "requested_at": requested_at.isoformat(),
        "available_at": available_at.isoformat(),
        "expires_at": expires_at.isoformat(),
    }


def attach_target(event: dict[str, Any], state: dict[str, Any]) -> None:
    """Keep raw rejected responses for diagnosis; never synthesize FLAT on failure."""
    if "autopilot" not in state:
        return
    event.pop("target_decision", None)
    try:
        event["target_decision"] = decode_target(
            event["jev"], state,
            requested_at=datetime.fromisoformat(event["requested_at"]),
            available_at=datetime.fromisoformat(event["available_at"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        event["target_error"] = str(exc)
