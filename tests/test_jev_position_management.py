from jevpip.broker.paper import PaperBroker, PaperConfig
from jevpip.jev.questions import position_question_specs
from jevpip.signals import classify_position_action


def tick(at: str, bid: str = "150.000", ask: str = "150.002"):
    return {
        "market_timestamp": at,
        "received_at": at,
        "bid": bid,
        "ask": ask,
        "status": "OPEN",
    }


def direct_broker(**overrides):
    config = PaperConfig(
        strategy="momentum",
        strategy_enabled=False,
        jev_direct_enabled=True,
        size=1000,
        price_unit=0.01,
        max_spread_units=10,
        take_profit_units=100,
        stop_loss_units=100,
        max_hold_seconds=30,
        cooldown_seconds=0,
        jev_signal_max_age_seconds=5,
        jev_position_action_max_age_seconds=5,
        jev_position_min_hold_seconds=2,
        jev_position_close_confirmations=2,
        **overrides,
    )
    return PaperBroker(config)


def direction_event(signal: str, requested: str, available: str):
    return {
        "direction_signal": signal,
        "requested_at": requested,
        "available_at": available,
        "recorded_at": available,
        "basis_market_timestamp": requested,
    }


def position_event(
    action: str | None,
    *,
    opened_at: str,
    requested: str,
    available: str,
    direction: str = "WAIT",
):
    return {
        "direction_signal": direction,
        "position_action": action,
        "position_action_detail": {"reason": f"test_{action}"},
        "requested_at": requested,
        "available_at": available,
        "recorded_at": available,
        "basis_market_timestamp": requested,
        "state": {
            "paper_context": {
                "jev_direct_enabled": True,
                "position": {
                    "side": "LONG",
                    "opened_at": opened_at,
                    "age_seconds": 1.0,
                    "position_horizon_seconds": 30,
                    "minimum_hold_seconds": 2,
                },
            }
        },
    }


def open_long(broker: PaperBroker) -> str:
    broker.on_decision(
        direction_event(
            "LONG",
            "2026-09-20T00:00:00+00:00",
            "2026-09-20T00:00:00.100000+00:00",
        )
    )
    events = broker.on_tick(tick("2026-09-20T00:00:01+00:00"))
    assert events and events[0]["action"] == "OPEN"
    return events[0]["timestamp"]


def test_position_question_is_bounded_to_hold_close():
    questions = position_question_specs()
    assert set(questions) == {"position_action"}
    assert set(questions["position_action"]["criteria"]) == {"HOLD", "CLOSE"}
    text = str(questions).lower()
    assert "quantity" in text
    assert "tp/sl" in text
    assert "leverage" in text
    assert "reverse" in text


def test_position_action_requires_strong_close_probability():
    action, detail = classify_position_action(
        {
            "answers": {
                "position_action": {
                    "type": "choice",
                    "choice": "CLOSE",
                    "confidence": 0.60,
                    "probabilities": {"HOLD": 0.40, "CLOSE": 0.60},
                }
            }
        }
    )
    assert action == "HOLD"
    assert detail["reason"] == "bounded_hold"

    action, detail = classify_position_action(
        {
            "answers": {
                "position_action": {
                    "type": "choice",
                    "choice": "CLOSE",
                    "confidence": 0.85,
                    "probabilities": {"HOLD": 0.10, "CLOSE": 0.85},
                }
            }
        }
    )
    assert action == "CLOSE"
    assert detail["reason"] == "bounded_close"


def test_jev_direct_direction_reversal_no_longer_closes_position():
    broker = direct_broker()
    opened_at = open_long(broker)

    broker.on_decision(
        position_event(
            "HOLD",
            opened_at=opened_at,
            requested="2026-09-20T00:00:02+00:00",
            available="2026-09-20T00:00:02.100000+00:00",
            direction="SHORT",
        )
    )
    events = broker.on_tick(tick("2026-09-20T00:00:04+00:00"))

    assert events == []
    snapshot = broker.snapshot()
    assert snapshot["position"]["side"] == "LONG"
    assert snapshot["jev_position_management"]["latest_action"] == "HOLD"


def test_jev_direct_close_requires_confirmation_and_minimum_hold():
    broker = direct_broker()
    opened_at = open_long(broker)

    first = position_event(
        "CLOSE",
        opened_at=opened_at,
        requested="2026-09-20T00:00:01.500000+00:00",
        available="2026-09-20T00:00:01.600000+00:00",
    )
    broker.on_decision(first)
    assert broker.on_tick(tick("2026-09-20T00:00:02+00:00")) == []

    # Re-delivering the same decision must not fake a second confirmation.
    broker.on_decision(first)
    assert broker.snapshot()["jev_position_management"]["close_confirmations"] == 1

    broker.on_decision(
        position_event(
            "CLOSE",
            opened_at=opened_at,
            requested="2026-09-20T00:00:02.200000+00:00",
            available="2026-09-20T00:00:02.300000+00:00",
        )
    )
    closed = broker.on_tick(tick("2026-09-20T00:00:03.200000+00:00"))

    assert closed and closed[0]["action"] == "CLOSE"
    assert closed[0]["reason"] == "jev_position_close"


def test_hold_resets_close_confirmation_hysteresis():
    broker = direct_broker(jev_position_min_hold_seconds=0)
    opened_at = open_long(broker)

    broker.on_decision(
        position_event(
            "CLOSE",
            opened_at=opened_at,
            requested="2026-09-20T00:00:02+00:00",
            available="2026-09-20T00:00:02.100000+00:00",
        )
    )
    assert broker.snapshot()["jev_position_management"]["close_confirmations"] == 1

    broker.on_decision(
        position_event(
            "HOLD",
            opened_at=opened_at,
            requested="2026-09-20T00:00:03+00:00",
            available="2026-09-20T00:00:03.100000+00:00",
        )
    )
    assert broker.snapshot()["jev_position_management"]["close_confirmations"] == 0

    broker.on_decision(
        position_event(
            "CLOSE",
            opened_at=opened_at,
            requested="2026-09-20T00:00:04+00:00",
            available="2026-09-20T00:00:04.100000+00:00",
        )
    )
    assert broker.on_tick(tick("2026-09-20T00:00:04.200000+00:00")) == []


def test_stale_or_wrong_position_close_advice_is_ignored():
    broker = direct_broker(
        jev_position_min_hold_seconds=0,
        jev_position_action_max_age_seconds=1,
        jev_position_close_confirmations=1,
    )
    opened_at = open_long(broker)

    broker.on_decision(
        position_event(
            "CLOSE",
            opened_at="2026-09-20T00:00:00+00:00",
            requested="2026-09-20T00:00:02+00:00",
            available="2026-09-20T00:00:02.100000+00:00",
        )
    )
    assert broker.on_tick(tick("2026-09-20T00:00:02.200000+00:00")) == []

    broker.on_decision(
        position_event(
            "CLOSE",
            opened_at=opened_at,
            requested="2026-09-20T00:00:03+00:00",
            available="2026-09-20T00:00:03.100000+00:00",
        )
    )
    assert broker.on_tick(tick("2026-09-20T00:00:04.500000+00:00")) == []
    assert broker.snapshot()["position"] is not None
