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
    assert closed[0]["gross_pnl"] == 10.0
    assert closed[0]["pnl"] == 10.0
    assert broker.snapshot()["balance"] == 100010.0


def test_btc_taker_fee_can_turn_small_gross_profit_into_net_loss():
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
            fee_rate=0.0005,
            fee_label="BTC taker",
        )
    )
    broker.on_tick(tick("2026-09-19T00:00:00+00:00", "17000000", "17001000"))
    broker.on_tick(tick("2026-09-19T00:00:05+00:00", "17002000", "17003000"))
    closed = broker.on_tick(tick("2026-09-19T00:00:06+00:00", "17006000", "17007000"))[0]

    assert closed["gross_pnl"] == 3.0
    assert closed["fees"] > 17.0
    assert closed["pnl"] < 0
    snapshot = broker.snapshot()
    assert snapshot["realized_pnl"] < 0
    assert snapshot["fees_paid"] > 17.0
    assert snapshot["max_drawdown"] > 0


def test_slippage_is_applied_adversely_on_both_sides():
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
            stop_loss_units=5,
            max_hold_seconds=30,
            cooldown_seconds=0,
            slippage_units=0.1,
        )
    )
    broker.on_tick(tick("2026-09-19T00:00:00+00:00", "150.000", "150.002"))
    opened = broker.on_tick(tick("2026-09-19T00:00:05+00:00", "150.010", "150.012"))[0]
    assert opened["price"] == "150.013"
    closed = broker.on_tick(tick("2026-09-19T00:00:06+00:00", "150.024", "150.026"))[0]
    assert closed["price"] == "150.023"
    assert closed["gross_pnl"] == 10.0
    assert closed["slippage_cost"] == 2.0


def test_profit_factor_after_one_win_and_one_loss():
    broker = PaperBroker(
        PaperConfig(
            initial_balance=100000,
            size=1000,
            price_unit=0.01,
            momentum_window_seconds=1,
            momentum_trigger_units=0.5,
            max_spread_units=2,
            take_profit_units=1,
            stop_loss_units=1,
            max_hold_seconds=30,
            cooldown_seconds=0,
        )
    )
    broker.on_tick(tick("2026-09-19T00:00:00+00:00", "150.000", "150.002"))
    broker.on_tick(tick("2026-09-19T00:00:01+00:00", "150.010", "150.012"))
    broker.on_tick(tick("2026-09-19T00:00:02+00:00", "150.022", "150.024"))
    # Force a short on falling momentum, then lose on reversal.
    broker.on_tick(tick("2026-09-19T00:00:03+00:00", "150.010", "150.012"))
    broker.on_tick(tick("2026-09-19T00:00:04+00:00", "150.024", "150.026"))
    snapshot = broker.snapshot()
    assert snapshot["closed_trades"] >= 2
    assert snapshot["profit_factor"] is not None


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


def test_rsi_strategy_opens_long_after_falling_ticks():
    broker = PaperBroker(
        PaperConfig(
            strategy="rsi_mean_reversion",
            size=1000,
            price_unit=0.01,
            max_spread_units=2,
            rsi_period=5,
            rsi_oversold=30,
            rsi_overbought=70,
            take_profit_units=100,
            stop_loss_units=100,
        )
    )
    for second, mid in enumerate([150.10, 150.09, 150.08, 150.07, 150.06, 150.05]):
        events = broker.on_tick(
            tick(
                f"2026-09-19T00:00:0{second}+00:00",
                f"{mid - 0.001:.3f}",
                f"{mid + 0.001:.3f}",
            )
        )
    assert events
    assert events[0]["action"] == "OPEN"
    assert events[0]["side"] == "LONG"
    assert events[0]["reason"] == "rsi_mean_reversion"


def test_ma_trend_strategy_opens_long():
    broker = PaperBroker(
        PaperConfig(
            strategy="ma_trend",
            size=1000,
            price_unit=0.01,
            max_spread_units=2,
            ma_fast_period=3,
            ma_slow_period=5,
            ma_min_gap_units=0.2,
            take_profit_units=100,
            stop_loss_units=100,
        )
    )
    events = []
    for second, mid in enumerate([150.00, 150.01, 150.02, 150.03, 150.04]):
        events = broker.on_tick(
            tick(
                f"2026-09-19T00:00:0{second}+00:00",
                f"{mid - 0.001:.3f}",
                f"{mid + 0.001:.3f}",
            )
        )
    assert events
    assert events[0]["side"] == "LONG"
    assert events[0]["reason"] == "ma_trend"


def test_supervisor_blocks_stale_tick_entry():
    broker = PaperBroker(
        PaperConfig(
            strategy="momentum",
            size=1000,
            price_unit=0.01,
            momentum_window_seconds=1,
            momentum_trigger_units=0.5,
            max_spread_units=2,
            deterministic_supervisor_enabled=True,
            max_market_age_seconds=5,
        )
    )
    broker.on_tick(
        {
            "market_timestamp": "2026-09-19T00:00:00+00:00",
            "received_at": "2026-09-19T00:00:00+00:00",
            "status": "OPEN",
            "bid": "150.000",
            "ask": "150.002",
        }
    )
    events = broker.on_tick(
        {
            "market_timestamp": "2026-09-19T00:00:01+00:00",
            "received_at": "2026-09-19T00:00:11+00:00",
            "status": "OPEN",
            "bid": "150.010",
            "ask": "150.012",
        }
    )
    assert events == []
    snapshot = broker.snapshot()
    assert snapshot["supervisor"]["state"] == "PAUSE_ALL"
    assert snapshot["supervisor"]["reason"] == "stale_market_data"


def test_supervisor_heartbeat_detects_silent_feed():
    from datetime import datetime, timezone

    broker = PaperBroker(
        PaperConfig(
            strategy="momentum",
            price_unit=0.01,
            max_spread_units=2,
            deterministic_supervisor_enabled=True,
            max_market_age_seconds=5,
        )
    )
    broker.on_tick(
        {
            "market_timestamp": "2026-09-19T00:00:00+00:00",
            "received_at": "2026-09-19T00:00:00+00:00",
            "status": "OPEN",
            "bid": "150.000",
            "ask": "150.002",
        }
    )
    broker.heartbeat(datetime(2026, 9, 19, 0, 0, 7, tzinfo=timezone.utc))
    snapshot = broker.snapshot()
    assert snapshot["supervisor"]["state"] == "PAUSE_ALL"
    assert snapshot["supervisor"]["reason"] == "stale_market_data"
    assert snapshot["supervisor"]["last_tick_age_seconds"] == 7.0
