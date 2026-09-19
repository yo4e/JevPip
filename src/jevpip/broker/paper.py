from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from jevpip.broker.bars import TimeBarBuilder
from jevpip.broker.strategies import (
    StrategyDecision,
    StrategyName,
    ma_trend_signal,
    momentum_signal,
    rsi_mean_reversion_signal,
)
from jevpip.broker.supervisor import SupervisorDecision, deterministic_supervisor

Side = Literal["LONG", "SHORT"]


@dataclass(frozen=True, slots=True)
class PaperConfig:
    initial_balance: float = 100000.0
    size: float = 1000.0
    strategy: StrategyName = "momentum"
    price_unit: float = 0.01
    move_unit_label: str = "pips"
    momentum_window_seconds: float = 5.0
    momentum_trigger_units: float = 0.6
    max_spread_units: float = 1.5
    take_profit_units: float = 1.0
    stop_loss_units: float = 1.0
    max_hold_seconds: float = 8.0
    cooldown_seconds: float = 2.0
    jev_signal_max_age_seconds: float = 3.0
    jev_direction_gate_enabled: bool = False
    fee_rate: float = 0.0
    fee_label: str = "手数料なし"
    slippage_units: float = 0.0
    short_is_synthetic: bool = False
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    ma_fast_period: int = 5
    ma_slow_period: int = 20
    ma_min_gap_units: float = 0.2
    deterministic_supervisor_enabled: bool = False
    max_market_age_seconds: float = 5.0
    strategy_bar_seconds: int = 0


@dataclass(slots=True)
class PaperPosition:
    side: Side
    size: Decimal
    entry_price: Decimal
    opened_at: datetime
    entry_fee: Decimal
    entry_slippage_cost: Decimal


@dataclass(frozen=True, slots=True)
class PaperTrade:
    action: Literal["OPEN", "CLOSE"]
    side: Side
    size: float
    price: str
    timestamp: str
    pnl: float | None
    gross_pnl: float | None
    fees: float
    slippage_cost: float
    reason: str


class PaperBroker:
    """Single-position paper scalper driven by real BID/ASK ticks.

    The simulator intentionally keeps execution simple:
    - real BID/ASK spread
    - optional adverse slippage
    - per-execution proportional fee
    - one position at a time

    It is a research approximation, not an execution simulator.
    """

    def __init__(self, config: PaperConfig) -> None:
        self.config = config
        self.initial_balance = Decimal(str(config.initial_balance))
        self.closed_net_pnl = Decimal("0")
        self.gross_realized_pnl = Decimal("0")
        self.fees_paid = Decimal("0")
        self.slippage_cost = Decimal("0")
        self.position: PaperPosition | None = None
        self.trades: deque[PaperTrade] = deque(maxlen=200)
        self._prices: deque[tuple[datetime, Decimal]] = deque(maxlen=50000)
        self._bar_prices: deque[tuple[datetime, Decimal]] = deque(maxlen=5000)
        self._bar_builder = (
            TimeBarBuilder(config.strategy_bar_seconds)
            if config.strategy_bar_seconds > 0
            else None
        )
        self._bar_completed_this_tick = False
        self._latest_jev_signal = "WAIT"
        self._latest_jev_at: datetime | None = None
        self._last_exit_at: datetime | None = None
        self._last_bid: Decimal | None = None
        self._last_ask: Decimal | None = None
        self._last_market_at: datetime | None = None
        self._last_received_at: datetime | None = None
        self._last_market_status = ""
        self._last_spread_units: Decimal | None = None
        self._last_supervisor_age_seconds: float | None = None
        self._peak_equity = self.initial_balance
        self._max_drawdown = Decimal("0")
        self._max_drawdown_pct = Decimal("0")
        self._closed_trade_count = 0
        self._win_count = 0
        self._sum_wins = Decimal("0")
        self._sum_losses_abs = Decimal("0")
        self._sum_closed_net = Decimal("0")
        self._exit_reason_stats: dict[str, dict[str, Decimal | int]] = {}
        self._latest_strategy_decision = StrategyDecision("WAIT", "not_started", {})
        self._supervisor = SupervisorDecision("NORMAL", "disabled", True)

    @property
    def price_unit(self) -> Decimal:
        return Decimal(str(self.config.price_unit))

    @property
    def fee_rate(self) -> Decimal:
        return Decimal(str(self.config.fee_rate))

    @property
    def slippage_price(self) -> Decimal:
        return self.price_unit * Decimal(str(self.config.slippage_units))

    @staticmethod
    def _dt(value: str) -> datetime:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)

    def on_decision(self, event: dict[str, Any]) -> None:
        signal = str(
            event.get("direction_signal")
            or event.get("research_signal")
            or "WAIT"
        )
        if signal not in {"LONG", "SHORT", "WAIT"}:
            signal = "WAIT"
        self._latest_jev_signal = signal
        raw_at = event.get("recorded_at") or event.get("market_timestamp")
        self._latest_jev_at = self._dt(str(raw_at)) if raw_at else None

    def on_tick(
        self,
        event: dict[str, Any],
        *,
        allow_entry: bool = True,
        strategy_override: StrategyName | None = None,
    ) -> list[dict[str, Any]]:
        if strategy_override not in {
            None,
            "momentum",
            "rsi_mean_reversion",
            "ma_trend",
        }:
            raise ValueError(f"Unsupported supervisor strategy override: {strategy_override!r}")

        at = self._dt(str(event["market_timestamp"]))
        bid = Decimal(str(event["bid"]))
        ask = Decimal(str(event["ask"]))
        mid = (bid + ask) / Decimal("2")
        spread_units = (ask - bid) / self.price_unit
        market_status = str(event.get("status") or "")
        received_raw = event.get("received_at")
        received_at = self._dt(str(received_raw)) if received_raw else at
        market_age_seconds = max(0.0, (received_at - at).total_seconds())

        self._last_bid = bid
        self._last_ask = ask
        self._last_market_at = at
        self._last_received_at = received_at
        self._last_market_status = market_status
        self._last_spread_units = spread_units
        self._last_supervisor_age_seconds = market_age_seconds
        self._prices.append((at, mid))
        self._prune_prices(at)
        self._bar_completed_this_tick = False
        if self._bar_builder is not None:
            completed = self._bar_builder.update(at, mid)
            for bar in completed:
                self._bar_prices.append((bar.end, bar.close))
            self._bar_completed_this_tick = bool(completed)

        if self.config.deterministic_supervisor_enabled:
            self._supervisor = deterministic_supervisor(
                market_status=market_status,
                spread_units=float(spread_units),
                max_spread_units=self.config.max_spread_units,
                market_age_seconds=market_age_seconds,
                max_market_age_seconds=self.config.max_market_age_seconds,
            )
        else:
            self._supervisor = SupervisorDecision("NORMAL", "disabled", True)

        generated: list[dict[str, Any]] = []
        if self.position is not None:
            exit_reason = self._exit_reason(at, bid, ask)
            if exit_reason is not None:
                trade = self._close(at, bid, ask, exit_reason)
                generated.append({"kind": "paper_trade", **asdict(trade)})

        if allow_entry and self.position is None and self._can_enter(at, spread_units):
            decision = self._strategy_decision(
                at,
                mid,
                strategy_override=strategy_override,
            )
            if self.config.jev_direction_gate_enabled and self.config.strategy != "jev":
                decision = self._apply_jev_direction_gate(decision, at)
            self._latest_strategy_decision = decision
            if decision.signal in {"LONG", "SHORT"}:
                trade = self._open(decision.signal, at, bid, ask, decision.reason)
                generated.append({"kind": "paper_trade", **asdict(trade)})

        self._update_drawdown()
        return generated

    def finalize(
        self,
        event: dict[str, Any],
        *,
        reason: str = "end_of_sample",
    ) -> dict[str, Any] | None:
        """Close an open research position at the end of a replay.

        This method never opens a new position. It exists so finite historical
        samples finish with realized PnL rather than a dangling position.
        """
        at = self._dt(str(event["market_timestamp"]))
        bid = Decimal(str(event["bid"]))
        ask = Decimal(str(event["ask"]))
        self._last_bid = bid
        self._last_ask = ask
        self._last_market_at = at
        if self.position is None:
            self._update_drawdown()
            return None
        trade = self._close(at, bid, ask, reason)
        self._update_drawdown()
        return {"kind": "paper_trade", **asdict(trade)}

    def heartbeat(self, now: datetime) -> None:
        """Refresh supervisor state even when the market feed goes quiet.

        This never creates or closes a position. It only tightens the entry gate
        and updates the visible supervisor state.
        """
        if not self.config.deterministic_supervisor_enabled:
            self._supervisor = SupervisorDecision("NORMAL", "disabled", True)
            self._last_supervisor_age_seconds = None
            return
        if self._last_received_at is None or self._last_spread_units is None:
            return

        normalized_now = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
        normalized_now = normalized_now.astimezone(timezone.utc)
        age = max(0.0, (normalized_now - self._last_received_at).total_seconds())
        self._last_supervisor_age_seconds = age
        self._supervisor = deterministic_supervisor(
            market_status=self._last_market_status,
            spread_units=float(self._last_spread_units),
            max_spread_units=self.config.max_spread_units,
            market_age_seconds=age,
            max_market_age_seconds=self.config.max_market_age_seconds,
        )

    def _prune_prices(self, now: datetime) -> None:
        keep_seconds = max(60.0, self.config.momentum_window_seconds * 4)
        while self._prices and (now - self._prices[0][0]).total_seconds() > keep_seconds:
            self._prices.popleft()

    def _can_enter(self, at: datetime, spread_units: Decimal) -> bool:
        if not self._supervisor.allow_entry:
            return False
        if spread_units > Decimal(str(self.config.max_spread_units)):
            return False
        if self._last_exit_at is None:
            return True
        return (at - self._last_exit_at).total_seconds() >= self.config.cooldown_seconds

    def _apply_jev_direction_gate(
        self,
        decision: StrategyDecision,
        at: datetime,
    ) -> StrategyDecision:
        """Require fresh Jev agreement before a code-strategy entry.

        The gate only affects new-entry direction. Position exits remain fully
        code-owned so WAIT/stale Jev output can never trap an open position.
        """

        if decision.signal not in {"LONG", "SHORT"}:
            return decision

        metrics = {
            **decision.metrics,
            "code_signal": decision.signal,
            "code_reason": decision.reason,
            "jev_signal": self._latest_jev_signal,
        }
        if self._latest_jev_at is None:
            return StrategyDecision("WAIT", "jev_gate_warmup", metrics)

        age = abs((at - self._latest_jev_at).total_seconds())
        metrics["jev_signal_age_seconds"] = round(age, 3)
        if age > self.config.jev_signal_max_age_seconds:
            return StrategyDecision("WAIT", "jev_gate_stale", metrics)
        if self._latest_jev_signal == "WAIT":
            return StrategyDecision("WAIT", "jev_gate_wait", metrics)
        if self._latest_jev_signal != decision.signal:
            return StrategyDecision("WAIT", "jev_gate_disagree", metrics)
        return StrategyDecision(
            decision.signal,
            f"jev_gate_agree:{decision.reason}",
            metrics,
        )

    def _strategy_decision(
        self,
        at: datetime,
        mid: Decimal,
        *,
        strategy_override: StrategyName | None = None,
    ) -> StrategyDecision:
        strategy = strategy_override or self.config.strategy
        if strategy == "jev":
            if self._latest_jev_at is None:
                return StrategyDecision("WAIT", "jev_warmup", {})
            age = abs((at - self._latest_jev_at).total_seconds())
            signal = self._latest_jev_signal if age <= self.config.jev_signal_max_age_seconds else "WAIT"
            return StrategyDecision(
                signal,
                "jev_signal" if signal != "WAIT" else "jev_stale_or_wait",
                {"signal_age_seconds": round(age, 3)},
            )

        strategy_prices = self._prices
        semantics = "tick_count"
        if self._bar_builder is not None and strategy in {
            "rsi_mean_reversion",
            "ma_trend",
        }:
            semantics = f"{self.config.strategy_bar_seconds}s_bar_close"
            if not self._bar_completed_this_tick:
                return StrategyDecision(
                    "WAIT",
                    "bar_wait",
                    {
                        "semantics": semantics,
                        "bars": len(self._bar_prices),
                    },
                )
            strategy_prices = self._bar_prices

        if strategy == "rsi_mean_reversion":
            decision = rsi_mean_reversion_signal(
                strategy_prices,
                period=self.config.rsi_period,
                oversold=self.config.rsi_oversold,
                overbought=self.config.rsi_overbought,
            )
            return StrategyDecision(
                decision.signal,
                decision.reason,
                {**decision.metrics, "semantics": semantics},
            )

        if strategy == "ma_trend":
            decision = ma_trend_signal(
                strategy_prices,
                price_unit=self.price_unit,
                fast_period=self.config.ma_fast_period,
                slow_period=self.config.ma_slow_period,
                min_gap_units=self.config.ma_min_gap_units,
            )
            return StrategyDecision(
                decision.signal,
                decision.reason,
                {**decision.metrics, "semantics": semantics},
            )

        return momentum_signal(
            self._prices,
            at=at,
            mid=mid,
            price_unit=self.price_unit,
            window_seconds=self.config.momentum_window_seconds,
            trigger_units=self.config.momentum_trigger_units,
        )

    def _entry_price(self, side: Side, bid: Decimal, ask: Decimal) -> Decimal:
        slip = self.slippage_price
        return ask + slip if side == "LONG" else bid - slip

    def _exit_price(self, side: Side, bid: Decimal, ask: Decimal) -> Decimal:
        slip = self.slippage_price
        return bid - slip if side == "LONG" else ask + slip

    def _fee(self, price: Decimal, size: Decimal) -> Decimal:
        if self.fee_rate <= 0:
            return Decimal("0")
        return abs(price * size) * self.fee_rate

    def _position_units(self, bid: Decimal, ask: Decimal) -> Decimal:
        if self.position is None:
            return Decimal("0")
        exit_price = self._exit_price(self.position.side, bid, ask)
        if self.position.side == "LONG":
            return (exit_price - self.position.entry_price) / self.price_unit
        return (self.position.entry_price - exit_price) / self.price_unit

    def _position_gross_pnl(self, bid: Decimal, ask: Decimal) -> Decimal:
        if self.position is None:
            return Decimal("0")
        exit_price = self._exit_price(self.position.side, bid, ask)
        if self.position.side == "LONG":
            return (exit_price - self.position.entry_price) * self.position.size
        return (self.position.entry_price - exit_price) * self.position.size

    def _position_net_pnl(self, bid: Decimal, ask: Decimal) -> Decimal:
        if self.position is None:
            return Decimal("0")
        gross = self._position_gross_pnl(bid, ask)
        exit_price = self._exit_price(self.position.side, bid, ask)
        exit_fee = self._fee(exit_price, self.position.size)
        return gross - self.position.entry_fee - exit_fee

    def _exit_reason(self, at: datetime, bid: Decimal, ask: Decimal) -> str | None:
        if self.position is None:
            return None
        units = self._position_units(bid, ask)
        if units >= Decimal(str(self.config.take_profit_units)):
            return "take_profit"
        if units <= -Decimal(str(self.config.stop_loss_units)):
            return "stop_loss"
        if (at - self.position.opened_at).total_seconds() >= self.config.max_hold_seconds:
            return "max_hold"
        if self.config.strategy == "jev":
            desired = self._strategy_decision(at, (bid + ask) / Decimal("2")).signal
            if desired == "SHORT" and self.position.side == "LONG":
                return "opposite_jev_signal"
            if desired == "LONG" and self.position.side == "SHORT":
                return "opposite_jev_signal"
        return None

    def _open(self, side: Side, at: datetime, bid: Decimal, ask: Decimal, reason: str) -> PaperTrade:
        size = Decimal(str(self.config.size))
        raw_price = ask if side == "LONG" else bid
        price = self._entry_price(side, bid, ask)
        entry_fee = self._fee(price, size)
        entry_slippage = abs(price - raw_price) * size

        self.position = PaperPosition(
            side=side,
            size=size,
            entry_price=price,
            opened_at=at,
            entry_fee=entry_fee,
            entry_slippage_cost=entry_slippage,
        )
        self.fees_paid += entry_fee
        self.slippage_cost += entry_slippage

        trade = PaperTrade(
            action="OPEN",
            side=side,
            size=float(size),
            price=str(price),
            timestamp=at.isoformat(),
            pnl=None,
            gross_pnl=None,
            fees=round(float(entry_fee), 3),
            slippage_cost=round(float(entry_slippage), 3),
            reason=reason,
        )
        self.trades.appendleft(trade)
        return trade

    def _close(self, at: datetime, bid: Decimal, ask: Decimal, reason: str) -> PaperTrade:
        assert self.position is not None
        position = self.position
        raw_price = bid if position.side == "LONG" else ask
        price = self._exit_price(position.side, bid, ask)
        gross_pnl = self._position_gross_pnl(bid, ask)
        exit_fee = self._fee(price, position.size)
        exit_slippage = abs(price - raw_price) * position.size
        net_pnl = gross_pnl - position.entry_fee - exit_fee

        self.gross_realized_pnl += gross_pnl
        self.closed_net_pnl += net_pnl
        self.fees_paid += exit_fee
        self.slippage_cost += exit_slippage
        self._closed_trade_count += 1
        self._sum_closed_net += net_pnl
        if net_pnl > 0:
            self._win_count += 1
            self._sum_wins += net_pnl
        elif net_pnl < 0:
            self._sum_losses_abs += abs(net_pnl)
        stats = self._exit_reason_stats.setdefault(
            reason,
            {"count": 0, "net_pnl": Decimal("0"), "gross_pnl": Decimal("0")},
        )
        stats["count"] = int(stats["count"]) + 1
        stats["net_pnl"] = Decimal(stats["net_pnl"]) + net_pnl
        stats["gross_pnl"] = Decimal(stats["gross_pnl"]) + gross_pnl
        self.position = None
        self._last_exit_at = at

        trade = PaperTrade(
            action="CLOSE",
            side=position.side,
            size=float(position.size),
            price=str(price),
            timestamp=at.isoformat(),
            pnl=round(float(net_pnl), 3),
            gross_pnl=round(float(gross_pnl), 3),
            fees=round(float(position.entry_fee + exit_fee), 3),
            slippage_cost=round(float(position.entry_slippage_cost + exit_slippage), 3),
            reason=reason,
        )
        self.trades.appendleft(trade)
        return trade

    def _equity(self) -> Decimal:
        unrealized = Decimal("0")
        if self.position is not None and self._last_bid is not None and self._last_ask is not None:
            unrealized = self._position_net_pnl(self._last_bid, self._last_ask)
        return self.initial_balance + self.closed_net_pnl + unrealized

    def _update_drawdown(self) -> None:
        equity = self._equity()
        if equity > self._peak_equity:
            self._peak_equity = equity
        drawdown = self._peak_equity - equity
        if drawdown > self._max_drawdown:
            self._max_drawdown = drawdown
            if self._peak_equity > 0:
                self._max_drawdown_pct = drawdown / self._peak_equity

    def snapshot(self) -> dict[str, Any]:
        unrealized_net = Decimal("0")
        unrealized_gross = Decimal("0")
        current_units = Decimal("0")
        if self.position is not None and self._last_bid is not None and self._last_ask is not None:
            unrealized_gross = self._position_gross_pnl(self._last_bid, self._last_ask)
            unrealized_net = self._position_net_pnl(self._last_bid, self._last_ask)
            current_units = self._position_units(self._last_bid, self._last_ask)

        balance = self.initial_balance + self.closed_net_pnl
        equity = balance + unrealized_net
        closed_count = self._closed_trade_count
        wins = self._win_count
        profit_factor = None
        if self._sum_losses_abs > 0:
            profit_factor = self._sum_wins / self._sum_losses_abs

        average_trade_pnl = None
        if closed_count:
            average_trade_pnl = self._sum_closed_net / Decimal(closed_count)
        average_win_pnl = None
        if wins:
            average_win_pnl = self._sum_wins / Decimal(wins)
        losses = closed_count - wins
        average_loss_pnl = None
        if losses:
            average_loss_pnl = -(self._sum_losses_abs / Decimal(losses))

        exit_reason_stats = {
            reason: {
                "count": int(stats["count"]),
                "net_pnl": round(float(Decimal(stats["net_pnl"])), 3),
                "gross_pnl": round(float(Decimal(stats["gross_pnl"])), 3),
                "average_net_pnl": round(
                    float(Decimal(stats["net_pnl"]) / Decimal(int(stats["count"]))),
                    3,
                ),
            }
            for reason, stats in sorted(self._exit_reason_stats.items())
        }

        position: dict[str, Any] | None = None
        if self.position is not None:
            position = {
                "side": self.position.side,
                "size": float(self.position.size),
                "entry_price": str(self.position.entry_price),
                "opened_at": self.position.opened_at.isoformat(),
                "unrealized_pnl": round(float(unrealized_net), 3),
                "unrealized_gross_pnl": round(float(unrealized_gross), 3),
                "current_units": round(float(current_units), 3),
                "move_unit_label": self.config.move_unit_label,
            }

        return {
            "enabled": True,
            "strategy": self.config.strategy,
            "jev_direction_gate_enabled": self.config.jev_direction_gate_enabled,
            "latest_jev_signal": self._latest_jev_signal,
            "strategy_bar_seconds": self.config.strategy_bar_seconds,
            "strategy_bars": len(self._bar_prices),
            "strategy_decision": asdict(self._latest_strategy_decision),
            "supervisor": {
                **asdict(self._supervisor),
                "last_tick_age_seconds": (
                    None
                    if self._last_supervisor_age_seconds is None
                    else round(self._last_supervisor_age_seconds, 3)
                ),
            },
            "initial_balance": round(float(self.initial_balance), 3),
            "balance": round(float(balance), 3),
            "equity": round(float(equity), 3),
            "realized_pnl": round(float(self.closed_net_pnl), 3),
            "gross_realized_pnl": round(float(self.gross_realized_pnl), 3),
            "unrealized_pnl": round(float(unrealized_net), 3),
            "unrealized_gross_pnl": round(float(unrealized_gross), 3),
            "fees_paid": round(float(self.fees_paid), 3),
            "slippage_cost": round(float(self.slippage_cost), 3),
            "position": position,
            "closed_trades": closed_count,
            "wins": wins,
            "win_rate": None if not closed_count else round(wins / closed_count, 4),
            "profit_factor": None if profit_factor is None else round(float(profit_factor), 4),
            "average_trade_pnl": None if average_trade_pnl is None else round(float(average_trade_pnl), 3),
            "average_win_pnl": None if average_win_pnl is None else round(float(average_win_pnl), 3),
            "average_loss_pnl": None if average_loss_pnl is None else round(float(average_loss_pnl), 3),
            "exit_reasons": exit_reason_stats,
            "max_drawdown": round(float(self._max_drawdown), 3),
            "max_drawdown_pct": round(float(self._max_drawdown_pct), 6),
            "config": asdict(self.config),
            "trades": [asdict(trade) for trade in list(self.trades)[:50]],
            "cost_model": {
                "spread": "real_bid_ask",
                "fee_rate_per_execution": self.config.fee_rate,
                "fee_label": self.config.fee_label,
                "slippage_units": self.config.slippage_units,
                "short_is_synthetic": self.config.short_is_synthetic,
            },
        }
