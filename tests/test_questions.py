from jevpip.jev.questions import question_specs, supervisor_question_specs


def test_questions_are_atomic_and_do_not_include_trade_action():
    questions = question_specs("5s")
    assert set(questions) == {"direction", "market_is_noisy", "reversal_risk", "trend_strength"}
    assert set(questions["direction"]["criteria"]) == {"UP", "DOWN", "FLAT"}
    assert "action" not in questions



def test_supervisor_questions_are_bounded_and_allowlisted():
    questions = supervisor_question_specs(("momentum", "ma_trend"))
    assert set(questions) == {
        "supervisor_pause_entry",
        "supervisor_caution",
        "supervisor_strategy",
    }
    assert set(questions["supervisor_strategy"]["criteria"]) == {
        "KEEP_CURRENT",
        "momentum",
        "ma_trend",
    }
    text = " ".join(str(value) for value in questions.values()).lower()
    assert "quantity" in text
    assert "leverage" in text
    assert "buy" not in questions
    assert "sell" not in questions
