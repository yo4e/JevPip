"""Target-position paper broker; legacy strategies keep their existing broker."""
from __future__ import annotations

from collections import deque
from dataclasses import asdict, replace
from datetime import datetime
from decimal import Decimal, ROUND_DOWN
from typing import Any
from uuid import uuid4

from jevpip.broker.paper import PaperBroker, PaperConfig, PaperPosition
from jevpip.broker.strategies import StrategyDecision
from jevpip.instruments import get_instrument
from jevpip.jev.autopilot import REASONS, finite_decimal

ZERO = Decimal("0")


def make_paper_broker(config: PaperConfig) -> PaperBroker:
    return AutopilotBroker(config) if config.autopilot_enabled else PaperBroker(config)


class AutopilotBroker(PaperBroker):
    """One net position, weighted average cost, proportional lot cost allocation.

    A closed trade is a realized closing leg (partial reductions included).
    Equity is marked at liquidation value including estimated exit fees. FX
    exposure uses configurable paper leverage (max 25x); crypto spot remains 1x.
    """

    def __init__(self, config: PaperConfig) -> None:
        self.instrument = get_instrument(config.instrument_id)
        if self.instrument.market_kind == "crypto_spot" and config.paper_leverage != 1:
            config = replace(config, paper_leverage=1.0)
        self.paper_leverage = finite_decimal(
            config.paper_leverage, "paper_leverage", positive=True
        )
        if self.paper_leverage < 1 or self.paper_leverage > 25:
            raise ValueError("paper leverage must be between 1x and 25x")
        self.quantity_step = Decimal("0.0001") if self.instrument.market_kind == "crypto_spot" else Decimal("1")
        for name in ("initial_balance", "size", "price_unit", "max_market_age_seconds", "autopilot_ttl_seconds"):
            finite_decimal(getattr(config, name), name, positive=True)
        for name in ("fee_rate", "slippage_units"):
            finite_decimal(getattr(config, name), name)
        for name, value in asdict(config).items():
            if name.startswith("autopilot_") and value is not None and name not in {
                "autopilot_enabled", "autopilot_style", "autopilot_fundamentals",
            }:
                finite_decimal(value, name)
        if config.fee_rate >= 1 or config.size < self.quantity_step:
            raise ValueError("invalid fee rate or base quantity")
        if config.autopilot_style not in {"daytrade", "scalp", "fifty"}:
            raise ValueError("unsupported autopilot style")
        if config.autopilot_horizon_seconds not in {30, 120, 600, 1800}:
            raise ValueError("unsupported autopilot horizon")
        if type(config.autopilot_confirmations) is not int or not 1 <= config.autopilot_confirmations <= 5:
            raise ValueError("confirmations must be 1..5")
        if config.autopilot_ttl_seconds > 60:
            raise ValueError("target TTL must be <= 60 seconds")
        if config.autopilot_min_confidence is not None and config.autopilot_min_confidence > 1:
            raise ValueError("confidence must be <= 1")
        if config.autopilot_max_drawdown_pct is not None and config.autopilot_max_drawdown_pct > 1:
            raise ValueError("drawdown fraction must be <= 1")
        super().__init__(config)
        self.session_id = uuid4().hex
        self.account_version = 0
        self._pending: dict[str, Any] | None = None
        self._last_request_at: datetime | None = None
        self._last_target: dict[str, Any] | None = None
        self._target_status = "waiting_for_jev"
        self._candidate: tuple[str, Decimal] | None = None
        self._confirmations = 0
        self._last_change_at: datetime | None = None
        self._halted = False
        self._executions: deque[dict[str, Any]] = deque(maxlen=1000)
        self._tick_tape: deque[dict[str, Any]] = deque(maxlen=80)
        self._entry_mid = ZERO
        self._entry_spread_cost = ZERO
        self._market_realized = ZERO
        self._spread_realized = ZERO
        self._slippage_realized = ZERO
        self._fees_realized = ZERO
        self._turnover = ZERO
        self._target_changes = 0
        self._exposure_integral = ZERO
        self._elapsed = ZERO
        self._previous_exposure = ZERO
        self._max_exposure = ZERO
        self._max_gap = 0.0

    def on_decision(self, event: dict[str, Any]) -> None:
        self._pending = None
        try:
            target = event.get("target_decision")
            if not isinstance(target, dict):
                raise ValueError(event.get("target_error") or "missing_target")
            if type(target.get("schema_version")) is not int or target["schema_version"] != 1:
                raise ValueError("unsupported_schema")
            if target.get("instrument_id") != self.instrument.id:
                raise ValueError("wrong_instrument")
            if target.get("session_id") != self.session_id:
                raise ValueError("old_session")
            if type(target.get("account_version")) is not int or target["account_version"] != self.account_version:
                raise ValueError("account_changed")
            if not isinstance(target.get("decision_id"), str) or not 1 <= len(target["decision_id"]) <= 80:
                raise ValueError("invalid_decision_id")
            side = target.get("target_side")
            quantity = finite_decimal(target.get("target_quantity"), "target_quantity")
            if side not in {"LONG", "SHORT", "FLAT"} or (side == "FLAT") != (quantity == 0):
                raise ValueError("invalid_side_quantity")
            if quantity % self.quantity_step:
                raise ValueError("invalid_quantity_step")
            confidence = finite_decimal(target.get("confidence"), "confidence")
            if confidence > 1 or target.get("reason") not in REASONS:
                raise ValueError("invalid_confidence_or_reason")
            basis, requested, available, expires = (
                self._dt(str(target[key])) for key in (
                    "basis_market_timestamp", "requested_at", "available_at", "expires_at"
                )
            )
            max_clock_skew = self.config.max_market_age_seconds
            if not requested <= available <= expires:
                raise ValueError("expired_or_invalid_clock")
            if abs((requested - basis).total_seconds()) > max_clock_skew:
                raise ValueError("basis_request_clock_skew")
            if (expires - min(requested, basis)).total_seconds() > self.config.autopilot_ttl_seconds:
                raise ValueError("invalid_expiry")
            if self._last_request_at is not None and requested <= self._last_request_at:
                raise ValueError("duplicate_or_out_of_order")
            self._last_request_at = requested
            self._pending = dict(target)
            self._last_target = dict(target)
            self._target_status = "pending"
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            self._target_status = f"rejected:{exc}"
            self._candidate = None
            self._confirmations = 0

    def _record(self, row: dict[str, Any], decision_id: str | None) -> dict[str, Any]:
        self.account_version += 1
        row.update(kind="paper_trade", decision_id=decision_id,
                   account_version=self.account_version, execution_id=f"{self.session_id}:{self.account_version}")
        self._turnover += Decimal(row["price"]) * Decimal(str(row["size"]))
        self._executions.appendleft(row)
        return row

    def _add(self, side: str, quantity: Decimal, at: datetime, bid: Decimal, ask: Decimal,
             reason: str, decision_id: str | None) -> dict[str, Any]:
        price = self._entry_price(side, bid, ask)
        mid = (bid + ask) / 2
        fee = self._fee(price, quantity)
        slip = self.slippage_price * quantity
        spread = (ask - bid) / 2 * quantity
        old = self.position
        if old is None:
            self.position = PaperPosition(side, quantity, price, at, fee, slip)
            self._entry_mid, self._entry_spread_cost = mid, spread
        else:
            size = old.size + quantity
            self._entry_mid = (self._entry_mid * old.size + mid * quantity) / size
            old.entry_price = (old.entry_price * old.size + price * quantity) / size
            old.size = size
            old.entry_fee += fee
            old.entry_slippage_cost += slip
            self._entry_spread_cost += spread
        self.fees_paid += fee
        self.slippage_cost += slip
        return self._record({
            "action": "OPEN" if old is None else "INCREASE", "side": side,
            "size": float(quantity), "price": str(price), "timestamp": at.isoformat(),
            "pnl": None, "gross_pnl": None, "market_pnl": None,
            "fees": float(fee), "execution_fee": float(fee),
            "slippage_cost": float(slip), "spread_cost": float(spread), "reason": reason,
        }, decision_id)

    def _reduce(self, quantity: Decimal, at: datetime, bid: Decimal, ask: Decimal,
                reason: str, decision_id: str | None) -> dict[str, Any]:
        old = self.position
        assert old is not None and 0 < quantity <= old.size
        fraction = quantity / old.size
        remaining = old.size - quantity
        entry_fee, entry_slip = old.entry_fee * fraction, old.entry_slippage_cost * fraction
        allocated_spread = self._entry_spread_cost * fraction
        mid = (bid + ask) / 2
        market_pnl = (mid - self._entry_mid) * quantity * (1 if old.side == "LONG" else -1)
        spread_cost = allocated_spread + (ask - bid) / 2 * quantity
        self.position = replace(old, size=quantity, entry_fee=entry_fee, entry_slippage_cost=entry_slip)
        trade = super()._close(at, bid, ask, reason)
        exit_fee = self._fee(Decimal(trade.price), quantity)
        realized_fees = entry_fee + exit_fee
        realized_slip = entry_slip + self.slippage_price * quantity
        self._market_realized += market_pnl
        self._spread_realized += spread_cost
        self._slippage_realized += realized_slip
        self._fees_realized += realized_fees
        if remaining:
            self.position = replace(old, size=remaining, entry_fee=old.entry_fee-entry_fee,
                                    entry_slippage_cost=old.entry_slippage_cost-entry_slip)
            self._entry_spread_cost -= allocated_spread
        else:
            self._entry_mid = self._entry_spread_cost = ZERO
        row = asdict(trade)
        row.update(action="REDUCE" if remaining else "CLOSE", market_pnl=float(market_pnl),
                   spread_cost=float(spread_cost), execution_fee=float(exit_fee),
                   fees=float(realized_fees), slippage_cost=float(realized_slip))
        return self._record(row, decision_id)

    def _risk_exit(self, at: datetime, bid: Decimal, ask: Decimal) -> str | None:
        cfg = self.config
        dd = self._peak_equity - self._equity()
        if ((cfg.autopilot_max_drawdown is not None and dd >= Decimal(str(cfg.autopilot_max_drawdown))) or
            (cfg.autopilot_max_drawdown_pct is not None and self._peak_equity > 0 and
             dd / self._peak_equity >= Decimal(str(cfg.autopilot_max_drawdown_pct)))):
            self._halted = True
        if self._equity() <= 0:
            self._halted = True
        if self._halted:
            return "drawdown_or_equity_stop"
        if self.position is None:
            return None
        net_pnl = self._position_net_pnl(bid, ask)
        net_units = net_pnl / self.position.size / self.price_unit
        if cfg.autopilot_style == "fifty":
            if self.instrument.market_kind == "crypto_spot":
                target_jpy = Decimal(str(cfg.autopilot_fifty_target_jpy))
                if net_pnl >= target_jpy:
                    return "fifty_take_profit"
                if net_pnl <= -target_jpy:
                    return "fifty_stop_loss"
            else:
                target_units = Decimal(str(cfg.autopilot_fifty_target_units))
                if net_units >= target_units:
                    return "fifty_take_profit"
                if net_units <= -target_units:
                    return "fifty_stop_loss"
            return None
        if cfg.autopilot_take_profit_units is not None and net_units >= Decimal(str(cfg.autopilot_take_profit_units)):
            return "net_take_profit"
        if cfg.autopilot_stop_loss_units is not None and net_units <= -Decimal(str(cfg.autopilot_stop_loss_units)):
            return "net_stop_loss"
        if cfg.autopilot_max_hold_seconds is not None and (at-self.position.opened_at).total_seconds() >= cfg.autopilot_max_hold_seconds:
            return "max_hold"
        return None

    def _capacity_block(self, side: str, quantity: Decimal, bid: Decimal, ask: Decimal,
                        *, optional_limits: bool = True) -> str | None:
        old = self.position
        if quantity == 0 or (old is not None and side == old.side and quantity <= old.size):
            return None
        notional = quantity * max(bid, ask)
        added = quantity if old is None or old.side != side else quantity-old.size
        projected_equity = self._equity() - added * self._round_trip_cost(bid, ask)
        required_margin = notional / self.paper_leverage
        if required_margin > max(ZERO, projected_equity):
            return "capital_limit"
        if not optional_limits:
            return None
        if self.config.autopilot_max_quantity is not None and quantity > Decimal(str(self.config.autopilot_max_quantity)):
            return "max_quantity"
        if self.config.autopilot_max_notional is not None and notional > Decimal(str(self.config.autopilot_max_notional)):
            return "max_notional"
        return None

    def _target_block(self, side: str, quantity: Decimal, confidence: float, at: datetime,
                      bid: Decimal, ask: Decimal, allow_entry: bool) -> str | None:
        old = self.position
        current = ZERO if old is None else old.size * (1 if old.side == "LONG" else -1)
        desired = quantity * (1 if side == "LONG" else -1)
        increasing = quantity > 0 and (old is None or side != old.side or quantity > old.size)
        cfg = self.config
        if not increasing:
            return None
        if self._halted:
            return "risk_halted"
        if cfg.autopilot_style == "fifty":
            # Fifty+ is intentionally always-in-market. Optional entry gates
            # and supervisor pauses do not turn it into an abstaining strategy;
            # only the mandatory capital invariant and fresh/open quote checks
            # outside this helper may block an entry.
            return self._capacity_block(
                side, quantity, bid, ask, optional_limits=False
            )
        if cfg.autopilot_max_change is not None and abs(desired-current) > Decimal(str(cfg.autopilot_max_change)):
            return "max_position_change"
        if not allow_entry:
            return "external_supervisor"
        capacity = self._capacity_block(side, quantity, bid, ask)
        if capacity:
            return capacity
        if cfg.autopilot_max_spread is not None and (ask-bid)/self.price_unit > Decimal(str(cfg.autopilot_max_spread)):
            return "max_spread"
        if cfg.autopilot_entry_loss is not None and self.initial_balance-self._equity() >= Decimal(str(cfg.autopilot_entry_loss)):
            return "entry_loss_stop"
        if cfg.autopilot_min_confidence is not None and confidence < cfg.autopilot_min_confidence:
            return "minimum_confidence"
        if cfg.autopilot_cooldown_seconds is not None and self._last_change_at is not None and (at-self._last_change_at).total_seconds() < cfg.autopilot_cooldown_seconds:
            return "cooldown"
        signature = (side, quantity)
        if signature != self._candidate:
            self._candidate, self._confirmations = signature, 0
        self._confirmations += 1
        if self._confirmations < cfg.autopilot_confirmations:
            return "confirming_target"
        return None

    def _apply_pending_target(
        self,
        *,
        at: datetime,
        now: datetime,
        bid: Decimal,
        ask: Decimal,
        allow_entry: bool,
        require_new_market: bool,
    ) -> list[dict[str, Any]]:
        target = self._pending
        if target is None:
            return []
        available, expires = self._dt(target["available_at"]), self._dt(target["expires_at"])
        if now > expires:
            self._pending = None
            self._target_status = "rejected:expired"
            return []
        if now < available or (require_new_market and at < available):
            return []

        self._pending = None  # one response can be applied at most once
        if target["account_version"] != self.account_version:
            self._target_status = "rejected:account_changed"
            return []

        side, quantity = target["target_side"], Decimal(str(target["target_quantity"]))
        old = self.position
        same = (old is None and quantity == 0) or (
            old is not None and old.side == side and old.size == quantity
        )
        if same:
            self._target_status = "hold"
            self._candidate, self._confirmations = None, 0
            return []

        block = self._target_block(
            side, quantity, target["confidence"], at, bid, ask, allow_entry
        )
        self._target_status = block or "executed"
        if block is not None:
            return []

        trades: list[dict[str, Any]] = []
        reason, decision_id = target["reason"], target["decision_id"]
        if old is not None and (side != old.side or quantity < old.size):
            amount = old.size if side != old.side else old.size-quantity
            trades.append(self._reduce(amount, at, bid, ask, reason, decision_id))
        current = ZERO if self.position is None else self.position.size
        if quantity > current:
            trades.append(self._add(side, quantity-current, at, bid, ask, reason, decision_id))
        return trades

    def _finish_cycle(
        self,
        *,
        at: datetime,
        now: datetime,
        bid: Decimal,
        ask: Decimal,
        before: int,
        trades: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if trades:
            self._target_changes += 1
            self._last_change_at = at
            self._candidate, self._confirmations = None, 0
        elif self._pending is None and self._target_status != "confirming_target":
            self._candidate, self._confirmations = None, 0
        self._update_drawdown()
        self._previous_exposure = ZERO if self.position is None else self.position.size*(bid+ask)/2
        self._max_exposure = max(self._max_exposure, self._previous_exposure)
        self._latest_strategy_decision = StrategyDecision(
            "WAIT" if self.position is None else self.position.side, self._target_status, {})
        empty = {"signal": "WAIT", "reason": "autopilot", "metrics": {}}
        self._last_decision_trace = {
            "market": {"market_timestamp": at.isoformat(), "received_at": now.isoformat(),
                       "bid": str(bid), "ask": str(ask), "status": self._last_market_status},
            "code_candidate": empty, "entry_candidate": asdict(self._latest_strategy_decision),
            "jev_direction": {"signal": self._latest_strategy_decision.signal},
            "deterministic_supervisor": {"state": "PAUSE_ENTRY" if self._halted else "NORMAL"},
            "blocked_entry_reason": None if trades or self._target_status == "hold" else self._target_status,
            "position_management": {"target": self._last_target, "status": self._target_status,
                                    "account_version_before": before, "account_version_after": self.account_version},
            "final_action": trades[-1]["action"] if trades else "NOOP", "holding_seconds": None,
            "turnover_size": sum(t["size"] for t in trades),
            "trade_link": {"trade": trades[0] if trades else None, "executions": trades},
        }
        return trades

    def execute_fifty_pending(self, now: datetime) -> list[dict[str, Any]]:
        """Apply a Fifty+ direction immediately on the latest still-fresh quote.

        The normal autopilot waits for a later market tick after the Jev
        response. Fifty+ instead trades once per completed round, so waiting
        for another sparse ticker update can make every decision expire. This
        paper-only path reuses the last observed BID/ASK only while that quote
        is still within max_market_age_seconds. It never fabricates a price.
        """

        if self.config.autopilot_style != "fifty" or self._pending is None:
            return []
        if (
            self._last_bid is None
            or self._last_ask is None
            or self._last_received_at is None
            or self._last_market_status != "OPEN"
        ):
            self._pending = None
            self._target_status = "rejected:market_unavailable"
            return []

        age = (now - self._last_received_at).total_seconds()
        max_age = self.config.max_market_age_seconds
        if age < 0 or age > max_age:
            self._pending = None
            self._target_status = "rejected:stale_quote"
            return []

        before = self.account_version
        trades = self._apply_pending_target(
            at=now,
            now=now,
            bid=self._last_bid,
            ask=self._last_ask,
            allow_entry=True,
            require_new_market=False,
        )
        return self._finish_cycle(
            at=now,
            now=now,
            bid=self._last_bid,
            ask=self._last_ask,
            before=before,
            trades=trades,
        )

    def on_tick(self, event: dict[str, Any], *, allow_entry: bool = True,
                strategy_override: Any = None, entry_gate_reason: str | None = None) -> list[dict[str, Any]]:
        at = self._dt(str(event["market_timestamp"]))
        now = self._dt(str(event.get("received_at") or event["market_timestamp"]))
        bid, ask = finite_decimal(event["bid"], "bid", positive=True), finite_decimal(event["ask"], "ask", positive=True)
        if ask < bid or event.get("instrument_id", self.instrument.id) != self.instrument.id:
            raise ValueError("invalid quote/instrument")
        if self._last_market_at is not None and at < self._last_market_at:
            self._target_status = "out_of_order_market"
            return []
        if self._last_market_at is not None:
            elapsed = max(0.0, (at-self._last_market_at).total_seconds())
            self._max_gap = max(self._max_gap, elapsed)
            self._elapsed += Decimal(str(elapsed))
            self._exposure_integral += self._previous_exposure * Decimal(str(elapsed))
        self._last_bid, self._last_ask = bid, ask
        self._last_market_at, self._last_received_at = at, now
        self._last_market_status = str(event.get("status", "UNKNOWN"))
        self._last_spread_units = (ask-bid)/self.price_unit
        self._remember_market(at, bid, ask)
        self._update_drawdown()
        trades: list[dict[str, Any]] = []
        before = self.account_version
        market_age = (now-at).total_seconds()
        max_age = self.config.max_market_age_seconds
        if self._last_market_status != "OPEN" or not -max_age <= market_age <= max_age:
            self._target_status = "market_closed_or_stale"
        else:
            forced = self._risk_exit(at, bid, ask)
            if forced and self.position is not None:
                trades.append(self._reduce(self.position.size, at, bid, ask, forced, None))
                self._target_status = forced
                self._pending = None
            elif self._pending is not None:
                trades.extend(self._apply_pending_target(
                    at=at,
                    now=now,
                    bid=bid,
                    ask=ask,
                    allow_entry=allow_entry,
                    require_new_market=True,
                ))
        return self._finish_cycle(
            at=at,
            now=now,
            bid=bid,
            ask=ask,
            before=before,
            trades=trades,
        )

    def _round_trip_cost(self, bid: Decimal, ask: Decimal) -> Decimal:
        return ask-bid + 2*self.slippage_price + (ask+bid)*self.fee_rate

    def _fifty_entry_gate(self, bid: Decimal, ask: Decimal) -> dict[str, Any]:
        quantity = (
            Decimal(str(self.config.size)) / self.quantity_step
        ).to_integral_value(rounding=ROUND_DOWN) * self.quantity_step
        round_trip_per_unit = self._round_trip_cost(bid, ask)
        estimated_round_trip_jpy = round_trip_per_unit * quantity
        if self.instrument.market_kind == "crypto_spot":
            target_jpy = Decimal(str(self.config.autopilot_fifty_target_jpy))
            target_units: Decimal | None = None
        else:
            target_units = Decimal(str(self.config.autopilot_fifty_target_units))
            target_jpy = target_units * quantity * self.price_unit
        ready = quantity > 0 and target_jpy > estimated_round_trip_jpy
        return {
            "ready": ready,
            "reason": None if ready else "round_trip_cost_at_or_above_target",
            "estimated_round_trip_cost_jpy": float(estimated_round_trip_jpy),
            "estimated_round_trip_cost_units": float(round_trip_per_unit / self.price_unit),
            "target_jpy": float(target_jpy),
            "target_units": None if target_units is None else float(target_units),
        }

    def _remember_market(self, at: datetime, bid: Decimal, ask: Decimal) -> None:
        mid = (bid + ask) / 2
        previous_mid = None
        if self._tick_tape:
            previous_mid = Decimal(str(self._tick_tape[-1]["mid"]))
        self._prices.append((at, mid))
        while self._prices and (at-self._prices[0][0]).total_seconds() > 1800:
            self._prices.popleft()
        self._tick_tape.append({
            "at": at.isoformat(),
            "mid": float(mid),
            "spread_units": float((ask-bid)/self.price_unit),
            "delta_units": (
                None
                if previous_mid is None
                else float((mid-previous_mid)/self.price_unit)
            ),
        })

    def warm_history(self, event: dict[str, Any]) -> None:
        """Seed only past chart observations before a replay's trading window."""
        at = self._dt(str(event["market_timestamp"]))
        bid = finite_decimal(event["bid"], "bid", positive=True)
        ask = finite_decimal(event["ask"], "ask", positive=True)
        if ask < bid:
            raise ValueError("crossed historical quote")
        self._remember_market(at, bid, ask)

    def decision_state(self, as_of: datetime) -> dict[str, Any]:
        bid, ask = self._last_bid, self._last_ask
        if bid is None or ask is None:
            raise ValueError("market not ready")
        snapshot = self.snapshot()
        current_side = "FLAT" if self.position is None else self.position.side
        current_quantity = ZERO if self.position is None else self.position.size
        targets: dict[str, Any] = {}
        fifty_entry_gate: dict[str, Any] | None = None
        if self.config.autopilot_style == "fifty":
            quantity = (Decimal(str(self.config.size))/self.quantity_step).to_integral_value(rounding=ROUND_DOWN)*self.quantity_step
            fifty_entry_gate = self._fifty_entry_gate(bid, ask)
            choices = []
            if not self._halted and fifty_entry_gate["ready"]:
                if quantity > 0 and not self._capacity_block("LONG", quantity, bid, ask, optional_limits=False):
                    choices.append(("UP", "LONG", quantity))
                if quantity > 0 and not self._capacity_block("SHORT", quantity, bid, ask, optional_limits=False):
                    choices.append(("DOWN", "SHORT", quantity))
        else:
            choices = [("KEEP", current_side, current_quantity), ("FLAT", "FLAT", ZERO)]
            for side in ("LONG", "SHORT"):
                for label, multiple in (("SMALL", "0.5"), ("BASE", "1"), ("LARGE", "2")):
                    quantity = (Decimal(str(self.config.size))*Decimal(multiple)/self.quantity_step).to_integral_value(rounding=ROUND_DOWN)*self.quantity_step
                    if quantity > 0 and not self._capacity_block(side, quantity, bid, ask):
                        choices.append((f"{side}_{label}", side, quantity))
        signed_current = current_quantity * (1 if current_side == "LONG" else -1)
        for key, side, quantity in choices:
            signed = quantity * (1 if side == "LONG" else -1)
            change = abs(signed-signed_current)
            # Transition estimate only: previously paid entry costs are sunk.
            transition = change*((ask-bid)/2+self.slippage_price+(ask+bid)/2*self.fee_rate)
            targets[key] = {"side": side, "quantity": str(quantity)}
            if self.config.autopilot_style != "fifty":
                targets[key].update(
                    notional_jpy=float(quantity*(ask+bid)/2),
                    estimated_transition_cost_jpy=float(transition),
                )
        history = [(at, price) for at, price in self._prices if at <= as_of]
        bars: dict[int, dict[str, Any]] = {}
        for at, price in history:
            bucket = int(at.timestamp())//60*60
            if bucket+60 > as_of.timestamp():
                continue  # closed bars only; incomplete current bar is the quote
            bar = bars.setdefault(bucket, {"end_unix": bucket+60, "open": float(price),
                                           "high": float(price), "low": float(price), "close": float(price), "ticks": 0})
            bar.update(high=max(bar["high"], float(price)), low=min(bar["low"], float(price)), close=float(price), ticks=bar["ticks"]+1)
        position = snapshot["position"]
        if position is not None:
            position = {**position, "age_seconds": max(0, (as_of-self.position.opened_at).total_seconds())}
        bar_limit = 5 if self.config.autopilot_style in {"scalp", "fifty"} else 30
        autopilot_state = {
            "schema_version": 1, "style": self.config.autopilot_style,
            "instrument_id": self.instrument.id, "session_id": self.session_id,
            "account_version": self.account_version, "as_of": as_of.isoformat(),
            "horizon_seconds": self.config.autopilot_horizon_seconds, "ttl_seconds": self.config.autopilot_ttl_seconds,
            "paper_leverage": float(self.paper_leverage), "risk_halted": self._halted,
            "targets": targets, "quote": {"bid": str(bid), "ask": str(ask), "spread": str(ask-bid)},
            "account": {key: snapshot[key] for key in ("balance", "equity", "realized_pnl", "unrealized_pnl")},
            "position": position, "costs": {
                "fee_per_execution": self.config.fee_rate, "slippage_per_unit": str(self.slippage_price),
                "estimated_round_trip_cost_per_unit": str(self._round_trip_cost(bid, ask)),
                "estimated_break_even_move_units": float(self._round_trip_cost(bid, ask)/self.price_unit),
                "quantity_step": str(self.quantity_step),
                "paper_leverage": float(self.paper_leverage),
                "margin_rate": float(Decimal("1") / self.paper_leverage),
                "capital_limit_notional_jpy": max(0, snapshot["equity"]) * float(self.paper_leverage),
                "short_is_synthetic": self.config.short_is_synthetic,
            },
            "constraints": {k: v for k, v in asdict(self.config).items() if k.startswith("autopilot_")},
            "recent_executions": list(self._executions)[:8],
            "closed_1m_bars": list(bars.values())[-bar_limit:],
            "history_seconds": 0 if not history else (as_of-history[0][0]).total_seconds(),
            "max_tick_gap_seconds": self._max_gap,
        }
        if self.config.autopilot_style in {"scalp", "fifty"}:
            autopilot_state["recent_ticks"] = list(self._tick_tape)[-40:]
        if self.config.autopilot_style == "fifty":
            autopilot_state["quote"] = {"mid": str((bid+ask)/2)}
            autopilot_state["recent_ticks"] = [
                {"at": row["at"], "mid": row["mid"], "delta_units": row["delta_units"]}
                for row in list(self._tick_tape)[-40:]
            ]
            autopilot_state["fifty_plus"] = {
                "always_one_position": True,
                "waiting_for_direction": self.position is None,
                "entry_gate": fifty_entry_gate,
                "target_kind": "jpy" if self.instrument.market_kind == "crypto_spot" else "units",
                "target_value": (
                    self.config.autopilot_fifty_target_jpy
                    if self.instrument.market_kind == "crypto_spot"
                    else self.config.autopilot_fifty_target_units
                ),
                "target_label": "円" if self.instrument.market_kind == "crypto_spot" else self.config.move_unit_label,
                "net_of_spread_fees_slippage": True,
            }
            # Fifty+ asks only which symmetric boundary is hit first. Account/cost
            # fields are code-owned and omitted from the model context to keep the
            # decision focused and token usage low.
            for key in ("account", "costs", "constraints", "recent_executions"):
                autopilot_state.pop(key, None)
        return {"autopilot": autopilot_state}

    def finalize(self, event: dict[str, Any], *, reason: str = "end_of_sample") -> dict[str, Any] | None:
        self._pending = None
        if self.position is None:
            return None
        at = self._dt(str(event["market_timestamp"]))
        bid, ask = finite_decimal(event["bid"], "bid", positive=True), finite_decimal(event["ask"], "ask", positive=True)
        now = self._dt(str(event.get("received_at") or event["market_timestamp"]))
        market_age = (now-at).total_seconds()
        max_age = self.config.max_market_age_seconds
        if ask < bid or event.get("status") != "OPEN" or not -max_age <= market_age <= max_age:
            return None  # do not invent an executable terminal quote
        self._last_bid, self._last_ask = bid, ask
        row = self._reduce(self.position.size, at, bid, ask, reason, None)
        self._update_drawdown()
        self._previous_exposure = ZERO
        return row

    def snapshot(self) -> dict[str, Any]:
        result = super().snapshot()
        open_fee = ZERO if self.position is None else self.position.entry_fee
        unrealized = ZERO
        if self.position is not None and self._last_bid is not None and self._last_ask is not None:
            unrealized = self._position_net_pnl(self._last_bid, self._last_ask) + open_fee
        fifty_entry_gate = None
        if (
            self.config.autopilot_style == "fifty"
            and self._last_bid is not None
            and self._last_ask is not None
        ):
            fifty_entry_gate = self._fifty_entry_gate(self._last_bid, self._last_ask)
        result.update(
            strategy="jev_autopilot", strategy_enabled=False, autopilot_enabled=True,
            fifty_entry_gate=fifty_entry_gate,
            balance=float(self.initial_balance+self.closed_net_pnl-open_fee),
            unrealized_pnl=float(unrealized),
            trades=list(self._executions)[:100], account_version=self.account_version,
            target_decision=self._last_target, target_status=self._target_status, risk_halted=self._halted,
            turnover_notional=float(self._turnover), max_exposure=float(self._max_exposure),
            average_exposure=float(self._exposure_integral/self._elapsed) if self._elapsed else 0.0,
            target_changes=self._target_changes,
            target_changes_per_minute=float(60*self._target_changes/self._elapsed) if self._elapsed else 0.0,
            max_tick_gap_seconds=self._max_gap,
            pnl_breakdown={"market_pnl": float(self._market_realized), "spread_cost": float(self._spread_realized),
                           "slippage_cost": float(self._slippage_realized), "fees": float(self._fees_realized),
                           "net_realized_pnl": float(self.closed_net_pnl)},
        )
        result["cost_model"]["version"] = "target-paper-v1"
        return result
