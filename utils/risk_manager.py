"""
Risk Manager
Enforces position limits, daily loss cap, consecutive loss pause,
correlation guards, and day-of-week sizing.
"""

from __future__ import annotations
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Day-of-week sizing: Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
DAY_SIZING = {0: 0.7, 1: 1.0, 2: 1.0, 3: 1.0, 4: 0.7, 5: 0.5, 6: 0.5}
DAY_NAMES = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday",
             4: "Friday", 5: "Saturday", 6: "Sunday"}


class RiskManager:
    """
    Central risk enforcement layer.
    All position opens must pass through here.
    """

    def __init__(self, config: dict):
        self.config = config
        self.max_positions = config.get("max_positions", 3)
        self.daily_loss_cap = config.get("daily_loss_cap", 50.0)
        self.consecutive_loss_limit = config.get("consecutive_loss_limit", 3)
        self.cooldown_seconds = config.get("cooldown_seconds", 300)

        self._last_day: Optional[str] = None
        self._daily_loss: float = 0.0
        self._consecutive_losses: int = 0
        self._paused: bool = False
        self._paused_reason: str = ""
        self._first_trade_of_day: bool = True
        self._last_trade_per_market: dict[str, float] = {}  # ticker → timestamp

        # Correlation guard: track same-direction crypto positions
        self._open_crypto_longs: int = 0
        self._open_crypto_shorts: int = 0

    def _today(self) -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _check_day_reset(self):
        """Reset daily counters on new trading day."""
        today = self._today()
        if today != self._last_day:
            logger.info(f"New trading day: {today} | Resetting risk counters")
            self._daily_loss = 0.0
            self._consecutive_losses = 0
            self._first_trade_of_day = True
            self._last_day = today
            # Reset pause if paused for daily loss (consecutive loss pause remains)
            if self._paused and "daily loss" in self._paused_reason.lower():
                self._paused = False
                self._paused_reason = ""

    def can_open_position(
        self,
        ticker: str,
        direction: str,
        asset_class: str,
        open_positions: list,
    ) -> tuple[bool, str]:
        """
        Check if a new position can be opened.

        Returns:
            (allowed: bool, reason: str)
        """
        self._check_day_reset()

        # Paused check
        if self._paused:
            return False, f"Bot paused: {self._paused_reason}"

        # Max positions check
        if len(open_positions) >= self.max_positions:
            return False, f"Max positions reached ({self.max_positions})"

        # Daily loss cap
        if self._daily_loss >= self.daily_loss_cap:
            self._paused = True
            self._paused_reason = f"Daily loss cap hit (${self._daily_loss:.2f} ≥ ${self.daily_loss_cap})"
            return False, self._paused_reason

        # Consecutive loss pause
        if self._consecutive_losses >= self.consecutive_loss_limit:
            self._paused = True
            self._paused_reason = f"{self.consecutive_loss_limit} consecutive losses — taking a break"
            return False, self._paused_reason

        # Cooldown check
        import time
        last_trade_ts = self._last_trade_per_market.get(ticker, 0)
        elapsed = time.time() - last_trade_ts
        if elapsed < self.cooldown_seconds:
            remaining = self.cooldown_seconds - elapsed
            return False, f"Cooldown active for {ticker}: {remaining:.0f}s remaining"

        # Correlation guard: max 1 same-direction crypto position
        if asset_class == "crypto":
            if direction == "LONG" and self._open_crypto_longs >= 1:
                return False, "Correlation guard: already have a crypto LONG position"
            if direction == "SHORT" and self._open_crypto_shorts >= 1:
                return False, "Correlation guard: already have a crypto SHORT position"

        return True, "OK"

    def get_size_multiplier(self, is_first_trade: bool = False) -> float:
        """
        Returns position size multiplier based on:
        - Day of week
        - First trade of day (always lighter)
        """
        dow = datetime.now(timezone.utc).weekday()
        multiplier = DAY_SIZING.get(dow, 1.0)

        # First trade of every day is always light (50% of already reduced day size)
        if is_first_trade or self._first_trade_of_day:
            multiplier *= 0.5
            logger.debug(f"First trade of day — sizing at {multiplier:.0%}")

        day_name = DAY_NAMES.get(dow, "Unknown")
        logger.debug(f"Position sizing: {day_name} → {multiplier:.0%}")
        return multiplier

    def record_trade_opened(self, ticker: str, direction: str, asset_class: str):
        """Call this when a new position is opened."""
        import time
        self._last_trade_per_market[ticker] = time.time()
        self._first_trade_of_day = False

        if asset_class == "crypto":
            if direction == "LONG":
                self._open_crypto_longs += 1
            else:
                self._open_crypto_shorts += 1

    def record_trade_closed(
        self,
        ticker: str,
        direction: str,
        asset_class: str,
        pnl_usd: float,
    ):
        """Call this when a position is closed. Updates loss tracking."""
        if pnl_usd < 0:
            self._daily_loss += abs(pnl_usd)
            self._consecutive_losses += 1
            logger.info(
                f"Loss recorded: ${pnl_usd:.2f} | "
                f"Daily: ${self._daily_loss:.2f} | "
                f"Consecutive: {self._consecutive_losses}"
            )
        else:
            self._consecutive_losses = 0

        if asset_class == "crypto":
            if direction == "LONG":
                self._open_crypto_longs = max(0, self._open_crypto_longs - 1)
            else:
                self._open_crypto_shorts = max(0, self._open_crypto_shorts - 1)

    def manual_resume(self):
        """Manually resume after a pause."""
        self._paused = False
        self._paused_reason = ""
        self._consecutive_losses = 0
        logger.info("Bot manually resumed")

    def get_status(self) -> dict:
        """Get current risk status for dashboard."""
        self._check_day_reset()
        dow = datetime.now(timezone.utc).weekday()
        return {
            "paused": self._paused,
            "paused_reason": self._paused_reason,
            "daily_loss": self._daily_loss,
            "daily_loss_cap": self.daily_loss_cap,
            "consecutive_losses": self._consecutive_losses,
            "consecutive_loss_limit": self.consecutive_loss_limit,
            "day_of_week": DAY_NAMES.get(dow, "Unknown"),
            "size_multiplier": DAY_SIZING.get(dow, 1.0),
            "open_crypto_longs": self._open_crypto_longs,
            "open_crypto_shorts": self._open_crypto_shorts,
        }
