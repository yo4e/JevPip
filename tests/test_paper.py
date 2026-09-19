from jevpip.broker.paper import PaperBroker, PaperConfig


def tick(at: str, bid: str, ask: str):
    return {
        "market_timestamp": at,
        "bid": bid,
        "ask": ask,
    }


def test_momentum_paper_trade_uses_ask_to_enter_and_bid_to_exit():
    broker = PaperBroker(
        PaperConfig(
            initial_balance=100000,
            size=1000,
            price_unit=0.01,
            move_unit_label="pips",
            momentum_window_seconds=5,
            momentum_trigger_units=0.5,
            max_spread_units=2,
            take_profit_units=1,
            stop_loss_units=2,
            max_hold_seconds=30,
            cooldown_seconds=0,
        )
    )

    broker.on_tick(tick("2026-09-19T00:00:00+00:00", "150.000", "150.002"))
    opened = broker.on_tick(tick("2026-09-19T00:00:05+00:00", "150.010", "150.012"))
    assert opened[0]["action"] == "OPEN"
    assert opened[0]["side"] == "LONG"
    assert opened[0]["price"] == "150.012"

    closed = broker.on_tick(tick("2026-09-19T00:00:06+00:00", "150.022", "150.024"))
    assert closed[0]["action"] == "CLOSE"
    assert closed[0]["price"] == "150.022"
    assert closed[0]["pnl"] == 10.0
    assert broker.snapshot()["balance"] == 100010.0


def test_btc_paper_trade_uses_fractional_btc_and_yen_units():
    broker = PaperBroker(
        PaperConfig(
            initial_balance=100000,
            size=0.001,
            price_unit=1,
            move_unit_label="円",
            momentum_window_seconds=5,
            momentum_trigger_units=1000,
            max_spread_units=5000,
            take_profit_units=3000,
            stop_loss_units=3000,
            max_hold_seconds=30,
            cooldown_seconds=0,
        )
    )
    broker.on_tick(tick("2026-09-19T00:00:00+00:00", "17000000", "17001000"))
    opened = broker.on_tick(tick("2026-09-19T00:00:05+00:00", "17002000", "17003000"))
    assert opened[0]["side"] == "LONG"
    assert opened[0]["size"] == 0.001
    closed = broker.on_tick(tick("2026-09-19T00:00:06+00:00", "17006000", "17007000"))
    assert closed[0]["pnl"] == 3.0


def test_jev_paper_waits_for_recent_signal():
    broker = PaperBroker(PaperConfig(strategy="jev", max_spread_units=2))
    broker.on_decision(
        {
            "research_signal": "SHORT",
            "recorded_at": "2026-09-19T00:00:00+00:00",
        }
    )
    events = broker.on_tick(tick("2026-09-19T00:00:01+00:00", "150.000", "150.002"))
    assert events[0]["side"] == "SHORT"
