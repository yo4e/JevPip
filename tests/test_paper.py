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
    assert snapshot["cost_model"]["estimated_fee_break_even_units"] > 3000


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


def test_rsi_bar_strategy_waits_for_closed_bars():
    broker = PaperBroker(
        PaperConfig(
            strategy="rsi_mean_reversion",
            size=1000,
            price_unit=0.01,
            max_spread_units=2,
            rsi_period=3,
            rsi_oversold=30,
            rsi_overbought=70,
            take_profit_units=1000,
            stop_loss_units=1000,
            max_hold_seconds=1000,
            strategy_bar_seconds=5,
        )
    )

    # Intra-bar ticks alone must not trigger the bar-based strategy.
    assert broker.on_tick(tick("2026-09-19T00:00:00+00:00", "150.099", "150.101")) == []
    assert broker.on_tick(tick("2026-09-19T00:00:02+00:00", "150.089", "150.091")) == []
    assert broker.snapshot()["strategy_decision"]["reason"] == "bar_wait"

    events = []
    # Complete four falling 5-second bars. RSI(3) needs four closes.
    for second, mid in [
        (5, 150.08),
        (10, 150.07),
        (15, 150.06),
        (20, 150.05),
        (25, 150.04),
    ]:
        events = broker.on_tick(
            tick(
                f"2026-09-19T00:00:{second:02d}+00:00",
                f"{mid - 0.001:.3f}",
                f"{mid + 0.001:.3f}",
            )
        )
        if events:
            break

    assert events
    assert events[0]["side"] == "LONG"
    snapshot = broker.snapshot()
    assert snapshot["strategy_bar_seconds"] == 5
    assert snapshot["strategy_decision"]["metrics"]["semantics"] == "5s_bar_close"


def test_ma_bar_strategy_only_decides_on_bar_close():
    broker = PaperBroker(
        PaperConfig(
            strategy="ma_trend",
            size=1000,
            price_unit=0.01,
            max_spread_units=2,
            ma_fast_period=2,
            ma_slow_period=3,
            ma_min_gap_units=0.1,
            take_profit_units=1000,
            stop_loss_units=1000,
            max_hold_seconds=1000,
            strategy_bar_seconds=5,
        )
    )

    events = []
    for second, mid in [
        (0, 150.00),
        (5, 150.01),
        (10, 150.02),
        (15, 150.03),
        (20, 150.04),
    ]:
        events = broker.on_tick(
            tick(
                f"2026-09-19T00:00:{second:02d}+00:00",
                f"{mid - 0.001:.3f}",
                f"{mid + 0.001:.3f}",
            )
        )
        if events:
            break

    assert events
    assert events[0]["side"] == "LONG"
    assert broker.snapshot()["strategy_decision"]["metrics"]["semantics"] == "5s_bar_close"


def test_trade_diagnostics_include_averages_and_exit_reasons():
    broker = PaperBroker(
        PaperConfig(
            initial_balance=100000,
            size=1000,
            price_unit=0.01,
            momentum_window_seconds=1,
            momentum_trigger_units=0.5,
            max_spread_units=2,
            take_profit_units=1,
            stop_loss_units=2,
            max_hold_seconds=30,
            cooldown_seconds=0,
        )
    )
    broker.on_tick(tick("2026-09-19T00:00:00+00:00", "150.000", "150.002"))
    broker.on_tick(tick("2026-09-19T00:00:01+00:00", "150.010", "150.012"))
    broker.on_tick(tick("2026-09-19T00:00:02+00:00", "150.022", "150.024"))

    snapshot = broker.snapshot()
    assert snapshot["closed_trades"] == 1
    assert snapshot["average_trade_pnl"] == 10.0
    assert snapshot["average_win_pnl"] == 10.0
    assert snapshot["average_loss_pnl"] is None
    assert snapshot["exit_reasons"]["take_profit"]["count"] == 1
    assert snapshot["exit_reasons"]["take_profit"]["net_pnl"] == 10.0



def test_supervisor_strategy_override_changes_entry_strategy():
    broker = PaperBroker(
        PaperConfig(
            strategy="momentum",
            momentum_trigger_units=9999,
            max_spread_units=10,
            take_profit_units=100,
            stop_loss_units=100,
            max_hold_seconds=100,
            cooldown_seconds=0,
            ma_fast_period=2,
            ma_slow_period=3,
            ma_min_gap_units=0,
        )
    )

    events = []
    for second, mid in enumerate([100.00, 100.02, 100.04, 100.06]):
        at = f"2026-09-19T00:00:{second:02d}+00:00"
        events.extend(
            broker.on_tick(
                {
                    "market_timestamp": at,
                    "received_at": at,
                    "bid": mid,
                    "ask": mid + 0.001,
                    "status": "OPEN",
                },
                strategy_override="ma_trend",
            )
        )

    opens = [event for event in events if event["action"] == "OPEN"]
    assert len(opens) == 1
    assert opens[0]["reason"] == "ma_trend"


def test_supervisor_strategy_override_rejects_jev_and_unknown_values():
    import pytest

    broker = PaperBroker(PaperConfig())
    event = {
        "market_timestamp": "2026-09-19T00:00:00+00:00",
        "received_at": "2026-09-19T00:00:00+00:00",
        "bid": 100,
        "ask": 100.01,
        "status": "OPEN",
    }
    with pytest.raises(ValueError, match="Unsupported"):
        broker.on_tick(event, strategy_override="jev")



def test_jev_direction_gate_requires_fresh_agreement():
    config = PaperConfig(
        strategy="momentum",
        jev_direction_gate_enabled=True,
        jev_signal_max_age_seconds=3,
        size=1000,
        price_unit=0.01,
        momentum_window_seconds=1,
        momentum_trigger_units=0.5,
        max_spread_units=2,
        take_profit_units=100,
        stop_loss_units=100,
        cooldown_seconds=0,
    )

    broker = PaperBroker(config)
    broker.on_tick(tick("2026-09-19T00:00:00+00:00", "150.000", "150.002"))
    blocked = broker.on_tick(tick("2026-09-19T00:00:01+00:00", "150.010", "150.012"))
    assert blocked == []
    assert broker.snapshot()["strategy_decision"]["reason"] == "jev_gate_warmup"

    broker.on_decision(
        {
            "research_signal": "WAIT",
            "recorded_at": "2026-09-19T00:00:01+00:00",
        }
    )
    blocked = broker.on_tick(tick("2026-09-19T00:00:02+00:00", "150.020", "150.022"))
    assert blocked == []
    assert broker.snapshot()["strategy_decision"]["reason"] == "jev_gate_wait"

    broker.on_decision(
        {
            "research_signal": "SHORT",
            "recorded_at": "2026-09-19T00:00:02+00:00",
        }
    )
    blocked = broker.on_tick(tick("2026-09-19T00:00:03+00:00", "150.030", "150.032"))
    assert blocked == []
    assert broker.snapshot()["strategy_decision"]["reason"] == "jev_gate_disagree"

    broker.on_decision(
        {
            "research_signal": "LONG",
            "recorded_at": "2026-09-19T00:00:03+00:00",
        }
    )
    opened = broker.on_tick(tick("2026-09-19T00:00:04+00:00", "150.040", "150.042"))
    assert len(opened) == 1
    assert opened[0]["action"] == "OPEN"
    assert opened[0]["side"] == "LONG"
    assert opened[0]["reason"].startswith("jev_gate_agree:")


def test_jev_direction_gate_does_not_block_position_exit():
    broker = PaperBroker(
        PaperConfig(
            strategy="momentum",
            jev_direction_gate_enabled=True,
            jev_signal_max_age_seconds=3,
            size=1000,
            price_unit=0.01,
            momentum_window_seconds=1,
            momentum_trigger_units=0.5,
            max_spread_units=2,
            take_profit_units=1,
            stop_loss_units=100,
            cooldown_seconds=0,
        )
    )
    broker.on_tick(tick("2026-09-19T00:00:00+00:00", "150.000", "150.002"))
    broker.on_decision(
        {
            "research_signal": "LONG",
            "recorded_at": "2026-09-19T00:00:00+00:00",
        }
    )
    opened = broker.on_tick(tick("2026-09-19T00:00:01+00:00", "150.010", "150.012"))
    assert opened and opened[0]["action"] == "OPEN"

    broker.on_decision(
        {
            "research_signal": "WAIT",
            "recorded_at": "2026-09-19T00:00:01+00:00",
        }
    )
    closed = broker.on_tick(tick("2026-09-19T00:00:02+00:00", "150.024", "150.026"))
    assert closed and closed[0]["action"] == "CLOSE"
    assert closed[0]["reason"] == "take_profit"



def test_direction_signal_takes_precedence_over_research_wait():
    broker = PaperBroker(
        PaperConfig(
            strategy="momentum",
            jev_direction_gate_enabled=True,
            size=1000,
            price_unit=0.01,
            momentum_window_seconds=1,
            momentum_trigger_units=0.5,
            max_spread_units=2,
            take_profit_units=100,
            stop_loss_units=100,
            cooldown_seconds=0,
        )
    )
    broker.on_tick(tick("2026-09-19T00:00:00+00:00", "150.000", "150.002"))
    broker.on_decision(
        {
            "direction_signal": "LONG",
            "research_signal": "WAIT",
            "recorded_at": "2026-09-19T00:00:00+00:00",
        }
    )
    opened = broker.on_tick(tick("2026-09-19T00:00:01+00:00", "150.010", "150.012"))
    assert opened and opened[0]["action"] == "OPEN"
    assert opened[0]["side"] == "LONG"



def test_strategy_off_jev_on_uses_jev_direct_signal():
    broker = PaperBroker(
        PaperConfig(
            strategy="momentum",
            strategy_enabled=False,
            jev_direct_enabled=True,
            size=1000,
            price_unit=0.01,
            max_spread_units=2,
            take_profit_units=100,
            stop_loss_units=100,
            cooldown_seconds=0,
        )
    )
    broker.on_decision(
        {
            "direction_signal": "SHORT",
            "recorded_at": "2026-09-20T00:00:00+00:00",
        }
    )
    opened = broker.on_tick(
        tick("2026-09-20T00:00:01+00:00", "150.000", "150.002")
    )
    assert opened and opened[0]["action"] == "OPEN"
    assert opened[0]["side"] == "SHORT"
    snapshot = broker.snapshot()
    assert snapshot["strategy_enabled"] is False
    assert snapshot["jev_direct_enabled"] is True


def test_strategy_off_jev_off_never_opens_new_position():
    broker = PaperBroker(
        PaperConfig(
            strategy="momentum",
            strategy_enabled=False,
            jev_direct_enabled=False,
            size=1000,
            price_unit=0.01,
            momentum_window_seconds=1,
            momentum_trigger_units=0.1,
            max_spread_units=100,
            cooldown_seconds=0,
        )
    )
    broker.on_tick(tick("2026-09-20T00:00:00+00:00", "150.000", "150.002"))
    events = broker.on_tick(
        tick("2026-09-20T00:00:01+00:00", "150.100", "150.102")
    )
    assert events == []
    assert broker.snapshot()["strategy_decision"]["reason"] == "strategy_disabled"


def test_safety_off_does_not_apply_spread_entry_gate():
    broker = PaperBroker(
        PaperConfig(
            strategy="momentum",
            strategy_enabled=True,
            deterministic_supervisor_enabled=False,
            size=1000,
            price_unit=0.01,
            momentum_window_seconds=1,
            momentum_trigger_units=0.1,
            max_spread_units=0.1,
            take_profit_units=100,
            stop_loss_units=100,
            cooldown_seconds=0,
        )
    )
    broker.on_tick(tick("2026-09-20T00:00:00+00:00", "150.000", "150.100"))
    opened = broker.on_tick(
        tick("2026-09-20T00:00:01+00:00", "150.200", "150.300")
    )
    assert opened and opened[0]["action"] == "OPEN"



def test_jev_decision_cannot_apply_before_it_was_available():
    broker = PaperBroker(
        PaperConfig(
            strategy="momentum",
            strategy_enabled=False,
            jev_direct_enabled=True,
            price_unit=0.01,
            max_spread_units=2,
            take_profit_units=100,
            stop_loss_units=100,
            cooldown_seconds=0,
            jev_signal_max_age_seconds=3,
        )
    )
    broker.on_decision(
        {
            "direction_signal": "LONG",
            "basis_market_timestamp": "2026-09-20T00:00:00+00:00",
            "requested_at": "2026-09-20T00:00:00+00:00",
            "available_at": "2026-09-20T00:00:02+00:00",
            "recorded_at": "2026-09-20T00:00:02+00:00",
        }
    )

    past_tick = {
        "market_timestamp": "2026-09-20T00:00:00.500000+00:00",
        "received_at": "2026-09-20T00:00:01.500000+00:00",
        "bid": "150.000",
        "ask": "150.002",
    }
    assert broker.on_tick(past_tick) == []
    assert broker.snapshot()["strategy_decision"]["reason"] == "jev_future"

    usable_tick = {
        "market_timestamp": "2026-09-20T00:00:02.100000+00:00",
        "received_at": "2026-09-20T00:00:02.100000+00:00",
        "bid": "150.000",
        "ask": "150.002",
    }
    opened = broker.on_tick(usable_tick)
    assert opened and opened[0]["action"] == "OPEN"
    assert opened[0]["side"] == "LONG"


def test_jev_signal_ttl_counts_from_request_time_not_response_time():
    broker = PaperBroker(
        PaperConfig(
            strategy_enabled=False,
            jev_direct_enabled=True,
            price_unit=0.01,
            max_spread_units=2,
            cooldown_seconds=0,
            jev_signal_max_age_seconds=3,
        )
    )
    broker.on_decision(
        {
            "direction_signal": "LONG",
            "basis_market_timestamp": "2026-09-20T00:00:00+00:00",
            "requested_at": "2026-09-20T00:00:00+00:00",
            "available_at": "2026-09-20T00:00:02.500000+00:00",
        }
    )
    events = broker.on_tick(
        {
            "market_timestamp": "2026-09-20T00:00:03.100000+00:00",
            "received_at": "2026-09-20T00:00:03.100000+00:00",
            "bid": "150.000",
            "ask": "150.002",
        }
    )
    assert events == []
    assert broker.snapshot()["strategy_decision"]["reason"] == "jev_stale_or_wait"


def test_jev_direct_close_never_reverses_on_the_same_tick():
    broker = PaperBroker(
        PaperConfig(
            strategy_enabled=False,
            jev_direct_enabled=True,
            price_unit=0.01,
            max_spread_units=2,
            take_profit_units=100,
            stop_loss_units=100,
            max_hold_seconds=100,
            cooldown_seconds=0,
        )
    )
    broker.on_decision(
        {
            "direction_signal": "LONG",
            "recorded_at": "2026-09-20T00:00:00+00:00",
        }
    )
    opened = broker.on_tick(
        tick("2026-09-20T00:00:00.500000+00:00", "150.000", "150.002")
    )
    assert [event["action"] for event in opened] == ["OPEN"]
    assert opened[0]["side"] == "LONG"

    broker.on_decision(
        {
            "direction_signal": "SHORT",
            "recorded_at": "2026-09-20T00:00:01+00:00",
        }
    )
    flipped = broker.on_tick(
        tick("2026-09-20T00:00:01.500000+00:00", "150.000", "150.002")
    )
    assert [event["action"] for event in flipped] == ["CLOSE"]
    assert flipped[0]["reason"] == "opposite_jev_signal"
    assert broker.snapshot()["position"] is None

    next_tick = broker.on_tick(
        tick("2026-09-20T00:00:02+00:00", "150.000", "150.002")
    )
    assert [event["action"] for event in next_tick] == ["OPEN"]
    assert next_tick[0]["side"] == "SHORT"



def test_breakeven_trade_is_not_counted_as_a_loss():
    broker = PaperBroker(
        PaperConfig(
            strategy_enabled=False,
            jev_direct_enabled=True,
            price_unit=0.01,
            max_spread_units=2,
            take_profit_units=100,
            stop_loss_units=100,
            max_hold_seconds=1,
            cooldown_seconds=0,
        )
    )
    broker.on_decision(
        {
            "direction_signal": "LONG",
            "recorded_at": "2026-09-20T00:00:00+00:00",
        }
    )
    opened = broker.on_tick(
        tick("2026-09-20T00:00:00.500000+00:00", "150.000", "150.000")
    )
    assert opened and opened[0]["action"] == "OPEN"

    closed = broker.on_tick(
        tick("2026-09-20T00:00:01.500000+00:00", "150.000", "150.000")
    )
    assert closed and closed[0]["action"] == "CLOSE"
    assert closed[0]["pnl"] == 0.0

    snapshot = broker.snapshot()
    assert snapshot["closed_trades"] == 1
    assert snapshot["wins"] == 0
    assert snapshot["losses"] == 0
    assert snapshot["average_loss_pnl"] is None
