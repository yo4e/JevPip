from jevpip.jev.questions import question_specs


def test_questions_are_atomic_and_do_not_include_trade_action():
    questions = question_specs("5s")
    assert set(questions) == {"direction", "market_is_noisy", "reversal_risk", "trend_strength"}
    assert set(questions["direction"]["criteria"]) == {"UP", "DOWN", "FLAT"}
    assert "action" not in questions
