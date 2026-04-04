"""
Exit Manager v3.0 — Break-Even + Clean SL/TP + Funding Guard
=============================================================
v3.0 changes (Zoran v3.0 alignment):
  - Break-even RE-ENABLED: 6% trigger → move SL to entry+0.1%
  - TP: 20% (was 10.5%) — 4:1 R:R
  - SL: 5% (was 3.5%)
  - Break-even offset accounts for real fees (not a nominal $5 gain)

Zoran: "86% of all wins came from BE exits."
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
from datetime import datetime, timezone
import time


class ExitStage(Enum):
    OPEN = "OPEN"
    BE_ACTIVE = "BE_ACTIVE"     # Break-even triggered, SL moved to entry+offset
    CLOSED = "CLOSED"


@dataclass
class Position:
    """Represents an open position."""
    id: str
    ticker: str
    direction: str          # 'LONG' or 'SHORT'
    entry_price: float
    size_usd: float         # Total position size in USD
    leverage: int
    open_time: float = field(default_factory=time.time)

    # Current state
    stage: ExitStage = ExitStage.OPEN
    remaining_fraction: float = 1.0
    partial_done: bool = False
    be_triggered: bool = False      # v3.0: break-even activated flag

    # Entry signal info (for learning engine)
    entry_pattern: str = ""
    entry_score: int = 0
    entry_rsi: float = 50.0

    # Tracking
    peak_pnl_pct: float = 0.0
    closed: bool = False
    close_price: Optional[float] = None
    close_time: Optional[float] = None
    pnl_usd: float = 0.0
    exit_reason: Optional[str] = None

    def current_pnl_pct(self, current_price: float) -> float:
        """Returns the LEVERAGED P&L percentage."""
        if self.direction == "LONG":
            raw_pct = (current_price - self.entry_price) / self.entry_price * 100
        else:
            raw_pct = (self.entry_price - current_price) / self.entry_price * 100
        return raw_pct * self.leverage

    def current_pnl_usd(self, current_price: float) -> float:
        """Returns P&L in USD for the remaining position size."""
        pnl_pct = self.current_pnl_pct(current_price)
        return (pnl_pct / 100) * self.size_usd * self.remaining_fraction

    def duration_minutes(self) -> float:
        return (time.time() - self.open_time) / 60


@dataclass
class ExitAction:
    """Represents an action the exit manager wants to take."""
    action: str             # 'CLOSE_FULL', 'MOVE_SL', 'HOLD'
    position_id: str
    reason: str
    stage: ExitStage
    close_fraction: float = 1.0
    new_sl_pnl_pct: Optional[float] = None


class ExitManager:
    """
    v3.0 — Break-Even + SL/TP + Funding Guard.
    BE activates at 6% → SL moves to entry+0.1% leveraged.
    """

    def __init__(self, config: dict):
        exit_cfg = config.get("exit", {})
        self.sl_pct = exit_cfg.get("sl_pct", -5.0)             # -5%
        self.tp_pct = exit_cfg.get("tp_pct", 20.0)             # +20% (4:1 R:R)
        self.hard_stop_pct = exit_cfg.get("hard_stop_pct", -5.25)
        self.use_simple = exit_cfg.get("use_simple_exits", False)
        self.funding_guard = exit_cfg.get("funding_guard", True)
        self.funding_guard_minutes = exit_cfg.get("funding_guard_minutes", 2)

        # Break-even config (v3.0)
        be_cfg = exit_cfg.get("break_even", {})
        self.be_enabled = be_cfg.get("enabled", True)
        self.be_trigger_pct = be_cfg.get("trigger_pct", 6.0)   # Trigger at +6% leveraged gain
        self.be_offset_pct = be_cfg.get("offset_pct", 0.1)     # Move SL to entry+0.1%

        # Per-position dynamic SL tracker (position_id → current_sl_pct)
        self._dynamic_sl: dict[str, float] = {}

    def check(self, position: Position, current_price: float) -> ExitAction:
        """Check exit conditions. BE → TP → SL in priority order."""
        if position.closed:
            return ExitAction("HOLD", position.id, "Already closed", position.stage)

        pnl_pct = position.current_pnl_pct(current_price)

        # Update peak P&L tracking
        if pnl_pct > position.peak_pnl_pct:
            position.peak_pnl_pct = pnl_pct

        # Get current effective SL (may have been moved to BE)
        effective_sl = self._dynamic_sl.get(position.id, self.sl_pct)

        # ── Funding Guard — close before the hour ─────────────────────
        if self.funding_guard:
            now = datetime.now(timezone.utc)
            minutes_to_hour = 60 - now.minute
            if minutes_to_hour <= self.funding_guard_minutes and now.minute >= (60 - self.funding_guard_minutes):
                return ExitAction(
                    action="CLOSE_FULL",
                    position_id=position.id,
                    reason=f"🕐 Funding guard: closing at :{now.minute:02d} ({minutes_to_hour}min to funding tick). P&L: {pnl_pct:+.1f}%",
                    stage=ExitStage.CLOSED,
                )

        # ── HARD STOP — absolute safety net ─────────────────────────
        if pnl_pct <= self.hard_stop_pct:
            return ExitAction(
                action="CLOSE_FULL",
                position_id=position.id,
                reason=f"🚨 HARD STOP! {pnl_pct:.1f}% (max: {self.hard_stop_pct}%) — emergency exit",
                stage=ExitStage.CLOSED,
            )

        # ── Break-Even Check (v3.0) ──────────────────────────────────
        if self.be_enabled and not position.be_triggered:
            if pnl_pct >= self.be_trigger_pct:
                # Move SL to entry + offset (positive leveraged %)
                new_sl = self.be_offset_pct
                self._dynamic_sl[position.id] = new_sl
                position.be_triggered = True
                position.stage = ExitStage.BE_ACTIVE
                return ExitAction(
                    action="MOVE_SL",
                    position_id=position.id,
                    reason=f"🔒 BE activated at {pnl_pct:+.1f}% → SL moved to +{self.be_offset_pct}% (entry+offset). Protected.",
                    stage=ExitStage.BE_ACTIVE,
                    new_sl_pnl_pct=new_sl,
                )

        # ── Take Profit ──────────────────────────────────────────────
        if pnl_pct >= self.tp_pct:
            return ExitAction(
                action="CLOSE_FULL",
                position_id=position.id,
                reason=f"✅ TP hit! +{pnl_pct:.1f}% (target: +{self.tp_pct}%)",
                stage=ExitStage.CLOSED,
            )

        # ── Stop Loss (or Break-Even SL) ─────────────────────────────
        if pnl_pct <= effective_sl:
            be_label = " [BE exit]" if position.be_triggered else ""
            return ExitAction(
                action="CLOSE_FULL",
                position_id=position.id,
                reason=f"{'🔒' if position.be_triggered else '❌'} SL hit{be_label}. {pnl_pct:.1f}% (limit: {effective_sl}%)",
                stage=ExitStage.CLOSED,
            )

        # ── Hold ─────────────────────────────────────────────────────
        be_status = f" | BE: {'✅' if position.be_triggered else '⏳ @{:.0f}%'.format(self.be_trigger_pct)}"
        return ExitAction(
            action="HOLD",
            position_id=position.id,
            reason=f"Holding. P&L: {pnl_pct:+.2f}% | Peak: {position.peak_pnl_pct:+.2f}%{be_status}",
            stage=position.stage,
        )

    def apply_action(
        self,
        action: ExitAction,
        position: Position,
        current_price: float,
    ) -> None:
        """Apply an exit action to the position object."""
        if action.action == "CLOSE_FULL":
            position.closed = True
            position.close_price = current_price
            position.close_time = time.time()
            position.pnl_usd = position.current_pnl_usd(current_price)
            position.exit_reason = action.reason
            position.stage = ExitStage.CLOSED
            # Clean up dynamic SL
            self._dynamic_sl.pop(position.id, None)
        elif action.action == "MOVE_SL":
            # SL already updated in _dynamic_sl above
            pass

    def get_sl_threshold(self, position_id: str) -> float:
        """Get current effective SL threshold for a position."""
        return self._dynamic_sl.get(position_id, self.sl_pct)
