from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

PIP = Decimal("0.01")
Side = Literal["LONG", "SHORT"]
Strategy = Literal["momentum", "jev"]


@dataclass(frozen=True, slots=True)
class PaperConfig:
    initial_balance: float = 100000.0
    size: int = 1000
    strategy: Strategy = "momentum"
    momentum_window_seconds: float = 5.0
    momentum_trigger_pips: float = 0.6
    max_spread_pips: float = 1.5
    take_profit_pips: float = 1.0
    stop_loss_pips: float = 1.0
    max_hold_seconds: float = 8.0
    cooldown_seconds: float = 2.0
    jev_signal_max_age_seconds: float = 3.0


@dataclass(slots=True)
class PaperPosition:
    side: Side
    size: int
    entry_price: Decimal
    opened_at: datetime


@dataclass(frozen=True, slots=True)
class PaperTrade:
    action: Literal["OPEN", "CLOSE"]
    side: Side
    size: int
    price: str
    timestamp: str
    pnl: float | None
    reason: str


class PaperBroker:
    """Single-position paper scalper driven by real BID/ASK ticks."""

    def __init__(self, config: PaperConfig) -> None:
        self.config = config
        self.initial_balance = Decimal(str(config.initial_balance))
        self.realized_pnl = Decimal("0")
        self.position: PaperPosition | None = None
        self.trades: deque[PaperTrade] = deque(maxlen=200)
        self._prices: deque[tuple[datetime, Decimal]] = deque(maxlen=50000)
        self._latest_jev_signal = "WAIT"
        self._latest_jev_at: datetime | None = None
        self._last_exit_at: datetime | None = None
        self._last_bid: Decimal | None = None
        self._last_ask: Decimal | None = None
        self._last_market_at: datetime | None = None

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
        spread_pips = (ask - bid) / PIP

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

        if self.position is None and self._can_enter(at, spread_pips):
            desired = self._desired_signal(at, mid)
            if desired in {"LONG", "SHORT"}:
                trade = self._open(desired, at, bid, ask)
                generated.append({"kind": "paper_trade", **asdict(trade)})

        return generated

    def _prune_prices(self, now: datetime) -> None:
        keep_seconds = max(60.0, self.config.momentum_window_seconds * 4)
        while self._prices and (now - self._prices[0][0]).total_seconds() > keep_seconds:
            self._prices.popleft()

    def _can_enter(self, at: datetime, spread_pips: Decimal) -> bool:
        if spread_pips > Decimal(str(self.config.max_spread_pips)):
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

        target_age = self.config.momentum_window_seconds
        previous: Decimal | None = None
        for seen_at, seen_mid in reversed(self._prices):
            if (at - seen_at).total_seconds() >= target_age:
                previous = seen_mid
                break
        if previous is None:
            return "WAIT"

        move_pips = (mid - previous) / PIP
        trigger = Decimal(str(self.config.momentum_trigger_pips))
        if move_pips >= trigger:
            return "LONG"
        if move_pips <= -trigger:
            return "SHORT"
        return "WAIT"

    def _position_pips(self, bid: Decimal, ask: Decimal) -> Decimal:
        if self.position is None:
            return Decimal("0")
        if self.position.side == "LONG":
            return (bid - self.position.entry_price) / PIP
        return (self.position.entry_price - ask) / PIP

    def _position_pnl(self, bid: Decimal, ask: Decimal) -> Decimal:
        if self.position is None:
            return Decimal("0")
        if self.position.side == "LONG":
            return (bid - self.position.entry_price) * self.position.size
        return (self.position.entry_price - ask) * self.position.size

    def _exit_reason(self, at: datetime, bid: Decimal, ask: Decimal) -> str | None:
        if self.position is None:
            return None
        pips = self._position_pips(bid, ask)
        if pips >= Decimal(str(self.config.take_profit_pips)):
            return "take_profit"
        if pips <= -Decimal(str(self.config.stop_loss_pips)):
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
        price = ask if side == "LONG" else bid
        self.position = PaperPosition(side=side, size=self.config.size, entry_price=price, opened_at=at)
        trade = PaperTrade(
            action="OPEN",
            side=side,
            size=self.config.size,
            price=str(price),
            timestamp=at.isoformat(),
            pnl=None,
            reason="momentum" if self.config.strategy == "momentum" else "jev_signal",
        )
        self.trades.appendleft(trade)
        return trade

    def _close(self, at: datetime, bid: Decimal, ask: Decimal, reason: str) -> PaperTrade:
        assert self.position is not None
        position = self.position
        price = bid if position.side == "LONG" else ask
        pnl = self._position_pnl(bid, ask)
        self.realized_pnl += pnl
        self.position = None
        self._last_exit_at = at
        trade = PaperTrade(
            action="CLOSE",
            side=position.side,
            size=position.size,
            price=str(price),
            timestamp=at.isoformat(),
            pnl=round(float(pnl), 3),
            reason=reason,
        )
        self.trades.appendleft(trade)
        return trade

    def snapshot(self) -> dict[str, Any]:
        unrealized = Decimal("0")
        current_pips = Decimal("0")
        if self.position is not None and self._last_bid is not None and self._last_ask is not None:
            unrealized = self._position_pnl(self._last_bid, self._last_ask)
            current_pips = self._position_pips(self._last_bid, self._last_ask)

        balance = self.initial_balance + self.realized_pnl
        equity = balance + unrealized
        closed = [trade for trade in self.trades if trade.action == "CLOSE"]
        wins = sum(1 for trade in closed if (trade.pnl or 0) > 0)

        position: dict[str, Any] | None = None
        if self.position is not None:
            position = {
                "side": self.position.side,
                "size": self.position.size,
                "entry_price": str(self.position.entry_price),
                "opened_at": self.position.opened_at.isoformat(),
                "unrealized_pnl": round(float(unrealized), 3),
                "current_pips": round(float(current_pips), 3),
            }

        return {
            "enabled": True,
            "strategy": self.config.strategy,
            "initial_balance": round(float(self.initial_balance), 3),
            "balance": round(float(balance), 3),
            "equity": round(float(equity), 3),
            "realized_pnl": round(float(self.realized_pnl), 3),
            "unrealized_pnl": round(float(unrealized), 3),
            "position": position,
            "closed_trades": len(closed),
            "wins": wins,
            "win_rate": None if not closed else round(wins / len(closed), 4),
            "config": asdict(self.config),
            "trades": [asdict(trade) for trade in list(self.trades)[:50]],
            "cost_model": {
                "spread": "real_bid_ask",
                "api_fee": "not_modeled_yet",
                "slippage": "not_modeled_yet",
            },
        }
