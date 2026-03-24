"""
Dry Run Engine
Simulates order execution and tracks P&L internally.
Maintains its own book of simulated positions and equity.
No real money is ever touched.
"""

from __future__ import annotations
import uuid
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

from strategy.exit_manager import Position, ExitStage

logger = logging.getLogger(__name__)


@dataclass
class TradeRecord:
    """Completed trade record for journal/learnings."""
    id: str
    ticker: str
    direction: str
    entry_price: float
    exit_price: float
    size_usd: float
    leverage: int
    pnl_usd: float
    pnl_pct: float          # Leveraged P&L %
    entry_time: float
    exit_time: float
    duration_minutes: float
    exit_reason: str
    stage_reached: str       # 'INITIAL', 'BREAK_EVEN', 'PARTIAL', 'CLOSED'
    score: int = 0
    probability: float = 0.0
    pattern: str = ""


class DryRunEngine:
    """
    Simulates trading without real API calls.
    Manages a paper trading book with accurate P&L accounting.
    """

    def __init__(self, config: dict):
        self.config = config
        self.bet_size = config.get("bet_size", 10.0)
        self.initial_capital = 10_000.0  # Paper capital
        self.equity = self.initial_capital

        self.open_positions: dict[str, Position] = {}
        self.trade_history: list[TradeRecord] = []

        # Session stats
        self.session_start = time.time()
        self.total_pnl = 0.0
        self.daily_pnl = 0.0
        self.daily_losses = 0.0
        self.consecutive_losses = 0
        self.last_day = self._today()

    def _today(self) -> str:
        import datetime
        return datetime.date.today().isoformat()

    def _check_day_reset(self):
        """Reset daily counters on new day."""
        today = self._today()
        if today != self.last_day:
            logger.info(f"New day: {today} | Resetting daily counters (prev: {self.last_day})")
            self.daily_pnl = 0.0
            self.daily_losses = 0.0
            self.consecutive_losses = 0
            self.last_day = today

    def open_position(
        self,
        ticker: str,
        direction: str,
        entry_price: float,
        leverage: int,
        size_multiplier: float = 1.0,
        score: int = 0,
        probability: float = 0.0,
        pattern: str = "",
    ) -> Optional[Position]:
        """
        Simulate opening a position.

        Args:
            ticker: Market symbol
            direction: 'LONG' or 'SHORT'
            entry_price: Simulated entry price
            leverage: Position leverage
            size_multiplier: Day-of-week sizing multiplier (0.5 - 1.0)
            score: Strategy score at entry
            probability: Strategy probability estimate

        Returns:
            Position object or None if rejected
        """
        self._check_day_reset()

        size_usd = self.bet_size * size_multiplier
        pos_id = f"{ticker}_{direction}_{uuid.uuid4().hex[:8]}"

        pos = Position(
            id=pos_id,
            ticker=ticker,
            direction=direction,
            entry_price=entry_price,
            size_usd=size_usd,
            leverage=leverage,
        )

        self.open_positions[pos_id] = pos

        logger.info(
            f"[DRY RUN] OPEN {direction} {ticker} @ {entry_price:.4f} | "
            f"Size: ${size_usd:.2f} | Leverage: {leverage}x | Score: {score}"
        )

        return pos

    def close_position(
        self,
        pos_id: str,
        current_price: float,
        reason: str,
        fraction: float = 1.0,
    ) -> Optional[TradeRecord]:
        """
        Simulate closing a position (fully or partially).

        Args:
            pos_id: Position ID
            current_price: Current market price
            reason: Exit reason string
            fraction: Fraction to close (1.0 = full, 0.667 = partial)
        """
        pos = self.open_positions.get(pos_id)
        if pos is None or pos.closed:
            return None

        pnl_pct = pos.current_pnl_pct(current_price)
        effective_size = pos.size_usd * fraction
        pnl_usd = (pnl_pct / 100) * effective_size

        # Update equity
        self.equity += pnl_usd
        self.total_pnl += pnl_usd
        self.daily_pnl += pnl_usd

        # Track losses
        if pnl_usd < 0:
            self.daily_losses += abs(pnl_usd)
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        logger.info(
            f"[DRY RUN] CLOSE {'PARTIAL ' if fraction < 1.0 else ''}{pos.ticker} {pos.direction} "
            f"@ {current_price:.4f} | P&L: {pnl_pct:+.2f}% | "
            f"${pnl_usd:+.2f} | Reason: {reason}"
        )

        if fraction >= 1.0:
            # Full close
            pos.closed = True
            pos.close_price = current_price
            pos.close_time = time.time()
            pos.exit_reason = reason
            pos.stage = ExitStage.CLOSED

            record = TradeRecord(
                id=pos.id,
                ticker=pos.ticker,
                direction=pos.direction,
                entry_price=pos.entry_price,
                exit_price=current_price,
                size_usd=pos.size_usd,
                leverage=pos.leverage,
                pnl_usd=pnl_usd,
                pnl_pct=pnl_pct,
                entry_time=pos.open_time,
                exit_time=time.time(),
                duration_minutes=pos.duration_minutes(),
                exit_reason=reason,
                stage_reached=pos.stage.value,
            )
            self.trade_history.append(record)
            del self.open_positions[pos_id]
            return record
        else:
            # Partial close — update remaining fraction
            pos.partial_done = True
            pos.remaining_fraction = 1.0 - fraction
            return None

    def get_stats(self) -> dict:
        """Get current performance statistics."""
        self._check_day_reset()

        wins = [t for t in self.trade_history if t.pnl_usd > 0]
        losses = [t for t in self.trade_history if t.pnl_usd <= 0]
        total = len(self.trade_history)

        return {
            "equity": self.equity,
            "total_pnl": self.total_pnl,
            "daily_pnl": self.daily_pnl,
            "daily_losses": self.daily_losses,
            "total_trades": total,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / total if total > 0 else 0.0,
            "avg_win": sum(t.pnl_usd for t in wins) / len(wins) if wins else 0.0,
            "avg_loss": sum(t.pnl_usd for t in losses) / len(losses) if losses else 0.0,
            "consecutive_losses": self.consecutive_losses,
            "open_positions": len(self.open_positions),
        }

    def get_unrealized_pnl(self, prices: dict[str, float]) -> float:
        """Calculate total unrealized P&L across all open positions."""
        total = 0.0
        for pos in self.open_positions.values():
            price = prices.get(pos.ticker)
            if price:
                total += pos.current_pnl_usd(price)
        return total
