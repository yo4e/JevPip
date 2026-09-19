from jevpip.broker.paper import PaperBroker, PaperConfig


def tick(at: str, bid: str, ask: str):
    return {
        "market_timestamp": at,
        "bid": bid,
        "ask": ask,
        "spread_pips": (float(ask) - float(bid)) / 0.01,
    }


def test_momentum_paper_trade_uses_ask_to_enter_and_bid_to_exit():
    broker = PaperBroker(
        PaperConfig(
            initial_balance=100000,
            size=1000,
            momentum_window_seconds=5,
            momentum_trigger_pips=0.5,
            max_spread_pips=2,
            take_profit_pips=1,
            stop_loss_pips=2,
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


def test_jev_paper_waits_for_recent_signal():
    broker = PaperBroker(PaperConfig(strategy="jev", max_spread_pips=2))
    broker.on_decision(
        {
            "research_signal": "SHORT",
            "recorded_at": "2026-09-19T00:00:00+00:00",
        }
    )
    events = broker.on_tick(tick("2026-09-19T00:00:01+00:00", "150.000", "150.002"))
    assert events[0]["side"] == "SHORT"
