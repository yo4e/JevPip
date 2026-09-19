from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

Side = Literal["LONG", "SHORT"]
Strategy = Literal["momentum", "jev"]


@dataclass(frozen=True, slots=True)
class PaperConfig:
    initial_balance: float = 100000.0
    size: float = 1000.0
    strategy: Strategy = "momentum"
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
    fee_rate: float = 0.0
    fee_label: str = "手数料なし"
    slippage_units: float = 0.0
    short_is_synthetic: bool = False


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
        self._latest_jev_signal = "WAIT"
        self._latest_jev_at: datetime | None = None
        self._last_exit_at: datetime | None = None
        self._last_bid: Decimal | None = None
        self._last_ask: Decimal | None = None
        self._last_market_at: datetime | None = None
        self._peak_equity = self.initial_balance
        self._max_drawdown = Decimal("0")
        self._max_drawdown_pct = Decimal("0")

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
        signal = str(event.get("research_signal") or "WAIT")
        if signal not in {"LONG", "SHORT", "WAIT"}:
            signal = "WAIT"
        self._latest_jev_signal = signal
        raw_at = event.get("recorded_at") or event.get("market_timestamp")
        self._latest_jev_at = self._dt(str(raw_at)) if raw_at else None

    def on_tick(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        at = self._dt(str(event["market_timestamp"]))
        bid = Decimal(str(event["bid"]))
        ask = Decimal(str(event["ask"]))
        mid = (bid + ask) / Decimal("2")
        spread_units = (ask - bid) / self.price_unit

        self._last_bid = bid
        self._last_ask = ask
        self._last_market_at = at
        self._prices.append((at, mid))
        self._prune_prices(at)

        generated: list[dict[str, Any]] = []
        if self.position is not None:
            exit_reason = self._exit_reason(at, bid, ask)
            if exit_reason is not None:
                trade = self._close(at, bid, ask, exit_reason)
                generated.append({"kind": "paper_trade", **asdict(trade)})

        if self.position is None and self._can_enter(at, spread_units):
            desired = self._desired_signal(at, mid)
            if desired in {"LONG", "SHORT"}:
                trade = self._open(desired, at, bid, ask)
                generated.append({"kind": "paper_trade", **asdict(trade)})

        self._update_drawdown()
        return generated

    def _prune_prices(self, now: datetime) -> None:
        keep_seconds = max(60.0, self.config.momentum_window_seconds * 4)
        while self._prices and (now - self._prices[0][0]).total_seconds() > keep_seconds:
            self._prices.popleft()

    def _can_enter(self, at: datetime, spread_units: Decimal) -> bool:
        if spread_units > Decimal(str(self.config.max_spread_units)):
            return False
        if self._last_exit_at is None:
            return True
        return (at - self._last_exit_at).total_seconds() >= self.config.cooldown_seconds

    def _desired_signal(self, at: datetime, mid: Decimal) -> str:
        if self.config.strategy == "jev":
            if self._latest_jev_at is None:
                return "WAIT"
            age = abs((at - self._latest_jev_at).total_seconds())
            return self._latest_jev_signal if age <= self.config.jev_signal_max_age_seconds else "WAIT"

        previous: Decimal | None = None
        for seen_at, seen_mid in reversed(self._prices):
            if (at - seen_at).total_seconds() >= self.config.momentum_window_seconds:
                previous = seen_mid
                break
        if previous is None:
            return "WAIT"

        move_units = (mid - previous) / self.price_unit
        trigger = Decimal(str(self.config.momentum_trigger_units))
        if move_units >= trigger:
            return "LONG"
        if move_units <= -trigger:
            return "SHORT"
        return "WAIT"

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
            desired = self._desired_signal(at, (bid + ask) / Decimal("2"))
            if desired == "SHORT" and self.position.side == "LONG":
                return "opposite_jev_signal"
            if desired == "LONG" and self.position.side == "SHORT":
                return "opposite_jev_signal"
        return None

    def _open(self, side: Side, at: datetime, bid: Decimal, ask: Decimal) -> PaperTrade:
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
            reason="momentum" if self.config.strategy == "momentum" else "jev_signal",
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
        closed = [trade for trade in self.trades if trade.action == "CLOSE"]
        wins = sum(1 for trade in closed if (trade.pnl or 0) > 0)
        gross_profit = sum(Decimal(str(trade.pnl or 0)) for trade in closed if (trade.pnl or 0) > 0)
        gross_loss = abs(sum(Decimal(str(trade.pnl or 0)) for trade in closed if (trade.pnl or 0) < 0))
        profit_factor = None
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss

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
            "closed_trades": len(closed),
            "wins": wins,
            "win_rate": None if not closed else round(wins / len(closed), 4),
            "profit_factor": None if profit_factor is None else round(float(profit_factor), 4),
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
