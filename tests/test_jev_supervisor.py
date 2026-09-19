from jevpip.jev.supervisor import derive_jev_supervisor_advice


def response(
    *,
    pause=0.2,
    caution=0.3,
    strategy="KEEP_CURRENT",
    strategy_confidence=0.8,
):
    return {
        "answers": {
            "supervisor_pause_entry": {"type": "noul", "noul": pause},
            "supervisor_caution": {"type": "noul", "noul": caution},
            "supervisor_strategy": {
                "type": "choice",
                "choice": strategy,
                "confidence": strategy_confidence,
                "probabilities": {strategy: strategy_confidence},
            },
        }
    }


def test_jev_supervisor_can_tighten_to_pause_entry():
    advice, detail = derive_jev_supervisor_advice(
        response(pause=0.8, caution=0.7, strategy="ma_trend"),
        allowed_strategies=("momentum", "ma_trend"),
    )
    assert advice.state == "PAUSE_ENTRY"
    assert advice.strategy is None
    assert advice.ttl_seconds == 30
    assert detail["pause_probability"] == 0.8


def test_jev_supervisor_can_mark_caution_and_select_allowlisted_strategy():
    advice, _ = derive_jev_supervisor_advice(
        response(pause=0.2, caution=0.75, strategy="ma_trend"),
        allowed_strategies=("momentum", "ma_trend"),
    )
    assert advice.state == "CAUTION"
    assert advice.strategy == "ma_trend"
    assert advice.ttl_seconds == 20


def test_jev_supervisor_rejects_non_allowlisted_choice_by_ignoring_it():
    advice, _ = derive_jev_supervisor_advice(
        response(strategy="invented_magic", strategy_confidence=0.99),
        allowed_strategies=("momentum", "ma_trend"),
    )
    assert advice.state == "NORMAL"
    assert advice.strategy is None


def test_jev_supervisor_needs_strategy_confidence():
    advice, _ = derive_jev_supervisor_advice(
        response(strategy="momentum", strategy_confidence=0.3),
        allowed_strategies=("momentum", "ma_trend"),
    )
    assert advice.strategy is None



def test_jev_supervisor_rejects_missing_required_answers():
    import pytest

    with pytest.raises(ValueError, match="missing required"):
        derive_jev_supervisor_advice(
            {"answers": {"supervisor_pause_entry": {"noul": 0.2}}},
            allowed_strategies=("momentum",),
        )
