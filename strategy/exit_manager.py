"""
Exit Manager v2.5 — Clean SL/TP Only + Funding Guard
No break-even. No partial closes. Either TP or SL. Clean.

SL: -3.5% leveraged P&L (cut the loser)
TP: +10.5% leveraged P&L (let the winner run)
R/R: 1:3. Math > emotion.

Funding Guard: Close all positions 5 minutes before the hour.
Never hold through a funding tick. Zero riba.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum
from datetime import datetime, timezone
import time


class ExitStage(Enum):
    OPEN = "OPEN"
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

    # Tracking
    peak_pnl_pct: float = 0.0
    closed: bool = False
    close_price: Optional[float] = None
    close_time: Optional[float] = None
    pnl_usd: float = 0.0
    exit_reason: Optional[str] = None

    def current_pnl_pct(self, current_price: float) -> float:
        """
        Returns the LEVERAGED P&L percentage.
        """
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
    action: str             # 'CLOSE_FULL', 'HOLD'
    position_id: str
    reason: str
    stage: ExitStage
    close_fraction: float = 1.0
    new_sl_pnl_pct: Optional[float] = None


class ExitManager:
    """
    v2.5 — Clean exits only.
    Two outcomes: Stop Loss or Take Profit. Nothing in between.
    """

    def __init__(self, config: dict):
        exit_cfg = config.get("exit", {})
        self.sl_pct = exit_cfg.get("sl_pct", -3.5)            # -3.5%
        self.tp_pct = exit_cfg.get("tp_pct", 10.5)            # +10.5%
        self.hard_stop_pct = exit_cfg.get("hard_stop_pct", -5.25)  # v2.5: absolute max loss safety net
        self.use_simple = exit_cfg.get("use_simple_exits", True)
        self.funding_guard = exit_cfg.get("funding_guard", True)
        self.funding_guard_minutes = exit_cfg.get("funding_guard_minutes", 5)  # Close 5 min before :00

    def check(self, position: Position, current_price: float) -> ExitAction:
        """
        Check if SL or TP is hit. That's it. Clean.
        """
        if position.closed:
            return ExitAction("HOLD", position.id, "Already closed", position.stage)

        pnl_pct = position.current_pnl_pct(current_price)

        # Update peak P&L tracking
        if pnl_pct > position.peak_pnl_pct:
            position.peak_pnl_pct = pnl_pct

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

        # ── HARD STOP — absolute safety net (checked FIRST) ─────────
        # v2.5: Even if price gaps through SL, this catches it.
        # A -15% loss can never happen again. Max loss: -5.25%.
        if pnl_pct <= self.hard_stop_pct:
            return ExitAction(
                action="CLOSE_FULL",
                position_id=position.id,
                reason=f"🚨 HARD STOP! {pnl_pct:.1f}% (max: {self.hard_stop_pct}%) — emergency exit",
                stage=ExitStage.CLOSED,
            )

        # ── Take Profit ──────────────────────────────────────────────
        if pnl_pct >= self.tp_pct:
            return ExitAction(
                action="CLOSE_FULL",
                position_id=position.id,
                reason=f"✅ TP hit! +{pnl_pct:.1f}% (target: +{self.tp_pct}%)",
                stage=ExitStage.CLOSED,
            )

        # ── Stop Loss ────────────────────────────────────────────────
        if pnl_pct <= self.sl_pct:
            return ExitAction(
                action="CLOSE_FULL",
                position_id=position.id,
                reason=f"❌ SL hit. {pnl_pct:.1f}% (limit: {self.sl_pct}%)",
                stage=ExitStage.CLOSED,
            )

        # ── Hold ─────────────────────────────────────────────────────
        return ExitAction(
            action="HOLD",
            position_id=position.id,
            reason=f"Holding. P&L: {pnl_pct:+.2f}% | Peak: {position.peak_pnl_pct:+.2f}%",
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

    def get_sl_threshold(self, position_id: str) -> float:
        """Get current SL P&L threshold."""
        return self.sl_pct
