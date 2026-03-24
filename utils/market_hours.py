"""
Market Hours Checker
The bot only scans markets during active sessions.

Schedule (UTC):
  Crypto:     24/7
  Commodities: Sun 22:00 → Fri 21:00
  US Stocks:   Mon-Fri 08:00 → 21:00
  Index:       Mon-Fri 08:00 → 21:00
"""

from __future__ import annotations
from datetime import datetime, time, timezone
import logging

logger = logging.getLogger(__name__)

# Day indices: Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class MarketHoursChecker:
    """
    Determines if a market is currently open for trading.
    """

    def __init__(self, config: dict):
        self.config = config
        self.hours_config = config.get("market_hours", {})

    def is_open(self, ticker: str, asset_class: str) -> bool:
        """
        Check if a market is currently open.

        Args:
            ticker: Market symbol (unused currently, for future per-ticker overrides)
            asset_class: 'crypto', 'commodity', 'index', 'stock'

        Returns:
            True if the market is open for trading
        """
        now = datetime.now(timezone.utc)
        weekday = now.weekday()  # Mon=0, Sun=6
        current_time = now.time().replace(tzinfo=None)

        asset_class = asset_class.lower()

        if asset_class == "crypto":
            return True  # 24/7

        elif asset_class == "commodity":
            return self._commodity_open(now, weekday, current_time)

        elif asset_class in ("stock", "index"):
            return self._equity_open(weekday, current_time)

        else:
            logger.warning(f"Unknown asset class: {asset_class}")
            return True  # Default to open

    def _commodity_open(self, now: datetime, weekday: int, current_time: time) -> bool:
        """
        Commodities: Sun 22:00 UTC → Fri 21:00 UTC
        """
        open_t = time(22, 0)
        close_t = time(21, 0)

        # Saturday = fully closed
        if weekday == 5:
            return False

        # Friday: close at 21:00
        if weekday == 4:
            return current_time < close_t

        # Sunday: open at 22:00
        if weekday == 6:
            return current_time >= open_t

        # Mon-Thu: always open
        return True

    def _equity_open(self, weekday: int, current_time: time) -> bool:
        """
        US Stocks / Index: Mon-Fri 08:00 → 21:00 UTC
        """
        if weekday >= 5:  # Sat or Sun
            return False

        open_t = time(8, 0)
        close_t = time(21, 0)
        return open_t <= current_time < close_t

    def get_open_markets(self, markets_config: dict) -> list[str]:
        """
        Returns a list of tickers that are currently open for trading.
        """
        open_markets = []
        for ticker, cfg in markets_config.items():
            if not cfg.get("enabled", False):
                continue
            asset_class = cfg.get("asset_class", "crypto")
            if self.is_open(ticker, asset_class):
                open_markets.append(ticker)
        return open_markets

    def time_until_open(self, asset_class: str) -> str:
        """Returns a human-readable string for time until next open."""
        if self.is_open("", asset_class):
            return "NOW OPEN"

        now = datetime.now(timezone.utc)
        weekday = now.weekday()

        if asset_class in ("stock", "index"):
            # Next weekday 08:00 UTC
            days_ahead = 1
            while (weekday + days_ahead) % 7 >= 5:
                days_ahead += 1
            return f"Opens in ~{days_ahead}d (Mon-Fri 08:00 UTC)"

        if asset_class == "commodity":
            # Sunday 22:00 UTC
            days_until_sun = (6 - weekday) % 7
            if days_until_sun == 0:
                return "Opens at 22:00 UTC"
            return f"Opens in ~{days_until_sun}d (Sunday 22:00 UTC)"

        return "OPEN"
