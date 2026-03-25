"""
WOBI — Weighted Order Book Imbalance
Zoran's Layer 2: "The bot reads the LIVE L2 order book. Not the chart —
the actual buy/sell pressure happening right now. Chart is lagging.
Order book is leading. We use both."

Metrics:
  - WOBI: Weighted imbalance (-1.0 to +1.0)
  - Bid/Ask walls: Large clusters at specific levels
  - Spread: Current spread in basis points
  - Depth ratio: Total bid vs ask volume
"""

from __future__ import annotations
import logging
import time
import math
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OrderBookSignal:
    """Order book analysis result."""
    wobi: float              # -1.0 (heavy sell) to +1.0 (heavy buy)
    depth_ratio: float       # bid_vol / ask_vol (>1 = more bids)
    spread_bps: float        # Spread in basis points
    bid_wall: Optional[float] = None    # Price level of large bid cluster
    ask_wall: Optional[float] = None    # Price level of large ask cluster
    bid_wall_size: float = 0.0
    ask_wall_size: float = 0.0
    mid_price: float = 0.0
    total_bid_vol: float = 0.0
    total_ask_vol: float = 0.0
    timestamp: float = 0.0

    @property
    def direction_bias(self) -> str:
        """Dominant direction from order book."""
        if self.wobi > 0.15:
            return "BULL"
        elif self.wobi < -0.15:
            return "BEAR"
        return "NEUTRAL"

    def confirms(self, direction: str, threshold: float = 0.3) -> bool:
        """Does the order book confirm a given trade direction?"""
        if direction == "LONG":
            return self.wobi >= threshold
        elif direction == "SHORT":
            return self.wobi <= -threshold
        return False

    def score_points(self, direction: str, threshold: float = 0.3) -> tuple[int, str]:
        """
        Returns score points for the scoring engine.
        +2 if WOBI confirms direction, 0 otherwise.
        """
        if self.confirms(direction, threshold):
            return 2, f"WOBI confirms {direction} ({self.wobi:+.3f}, threshold ±{threshold})"
        return 0, f"WOBI neutral for {direction} ({self.wobi:+.3f})"

    def summary(self) -> str:
        walls = []
        if self.bid_wall:
            walls.append(f"BID_WALL@{self.bid_wall:.2f}({self.bid_wall_size:.0f})")
        if self.ask_wall:
            walls.append(f"ASK_WALL@{self.ask_wall:.2f}({self.ask_wall_size:.0f})")
        wall_str = " | ".join(walls) if walls else "no walls"
        return (
            f"WOBI={self.wobi:+.3f} | Spread={self.spread_bps:.1f}bps | "
            f"DepthRatio={self.depth_ratio:.2f} | {wall_str}"
        )


class OrderBookIntelligence:
    """
    Analyzes L2 order book data from Hyperliquid.
    Uses REST polling via existing get_orderbook() method.
    """

    def __init__(self, config: dict, hl_client=None):
        """
        Args:
            config: Bot config with 'orderbook' section
            hl_client: HyperliquidClient instance
        """
        ob_cfg = config.get("orderbook", {})
        self.enabled = ob_cfg.get("enabled", True)
        self.depth = ob_cfg.get("depth", 20)
        self.wobi_threshold = ob_cfg.get("wobi_threshold", 0.3)
        self.wall_multiplier = ob_cfg.get("wall_multiplier", 3.0)
        self.refresh_seconds = ob_cfg.get("refresh_seconds", 2)
        self.score_points_val = ob_cfg.get("score_points", 2)
        self.hl_client = hl_client

        # Cache: {ticker: (timestamp, OrderBookSignal)}
        self._cache: dict[str, tuple[float, OrderBookSignal]] = {}

    def _parse_l2(self, raw: dict) -> Optional[OrderBookSignal]:
        """
        Parse Hyperliquid L2 snapshot into OrderBookSignal.
        
        Hyperliquid L2 format:
        {
            "levels": [
                [{"px": "87000.0", "sz": "1.5", "n": 3}, ...],  # bids
                [{"px": "87001.0", "sz": "0.8", "n": 2}, ...]   # asks
            ]
        }
        """
        if not raw or "levels" not in raw:
            return None

        levels = raw["levels"]
        if len(levels) < 2:
            return None

        bids_raw = levels[0]  # sorted best (highest) first
        asks_raw = levels[1]  # sorted best (lowest) first

        if not bids_raw or not asks_raw:
            return None

        # Parse into (price, size) tuples
        bids = [(float(b["px"]), float(b["sz"])) for b in bids_raw[:self.depth]]
        asks = [(float(a["px"]), float(a["sz"])) for a in asks_raw[:self.depth]]

        if not bids or not asks:
            return None

        best_bid = bids[0][0]
        best_ask = asks[0][0]
        mid_price = (best_bid + best_ask) / 2.0

        if mid_price == 0:
            return None

        # Spread in basis points
        spread_bps = (best_ask - best_bid) / mid_price * 10000

        # ── WOBI: Weighted Order Book Imbalance ──────────────────────
        # Weight by proximity to mid price (closer levels matter more)
        # Weight = 1 / (1 + distance_pct * 100)  → closest level ≈ weight 1.0
        weighted_bid_vol = 0.0
        weighted_ask_vol = 0.0

        for price, size in bids:
            distance_pct = abs(mid_price - price) / mid_price
            weight = 1.0 / (1.0 + distance_pct * 100)
            weighted_bid_vol += size * weight

        for price, size in asks:
            distance_pct = abs(price - mid_price) / mid_price
            weight = 1.0 / (1.0 + distance_pct * 100)
            weighted_ask_vol += size * weight

        total_weighted = weighted_bid_vol + weighted_ask_vol
        if total_weighted == 0:
            wobi = 0.0
        else:
            wobi = (weighted_bid_vol - weighted_ask_vol) / total_weighted

        # ── Raw depth ratio ──────────────────────────────────────────
        total_bid_vol = sum(s for _, s in bids)
        total_ask_vol = sum(s for _, s in asks)
        depth_ratio = total_bid_vol / total_ask_vol if total_ask_vol > 0 else 1.0

        # ── Wall detection ───────────────────────────────────────────
        # A "wall" = level with size > wall_multiplier × average level size
        all_sizes = [s for _, s in bids] + [s for _, s in asks]
        avg_size = sum(all_sizes) / len(all_sizes) if all_sizes else 1.0
        wall_threshold = avg_size * self.wall_multiplier

        bid_wall = None
        bid_wall_size = 0.0
        for price, size in bids:
            if size > wall_threshold and size > bid_wall_size:
                bid_wall = price
                bid_wall_size = size

        ask_wall = None
        ask_wall_size = 0.0
        for price, size in asks:
            if size > wall_threshold and size > ask_wall_size:
                ask_wall = price
                ask_wall_size = size

        return OrderBookSignal(
            wobi=wobi,
            depth_ratio=depth_ratio,
            spread_bps=spread_bps,
            bid_wall=bid_wall,
            ask_wall=ask_wall,
            bid_wall_size=bid_wall_size,
            ask_wall_size=ask_wall_size,
            mid_price=mid_price,
            total_bid_vol=total_bid_vol,
            total_ask_vol=total_ask_vol,
            timestamp=time.time(),
        )

    def analyze(self, ticker: str, force_refresh: bool = False) -> Optional[OrderBookSignal]:
        """
        Analyze the order book for a ticker.
        Uses cache with configurable refresh rate.

        Args:
            ticker: Market symbol
            force_refresh: Skip cache

        Returns:
            OrderBookSignal or None on failure
        """
        if not self.enabled:
            return None

        # Check cache
        if not force_refresh and ticker in self._cache:
            ts, signal = self._cache[ticker]
            if time.time() - ts < self.refresh_seconds:
                return signal

        if self.hl_client is None:
            logger.warning("OrderBook: No Hyperliquid client")
            return None

        try:
            raw = self.hl_client.get_orderbook(ticker, depth=self.depth)
            if raw is None:
                return None

            signal = self._parse_l2(raw)
            if signal:
                self._cache[ticker] = (time.time(), signal)
                logger.debug(f"OrderBook {ticker}: {signal.summary()}")

            return signal

        except Exception as e:
            logger.error(f"OrderBook: Error analyzing {ticker}: {e}")
            return None

    def get_score(self, ticker: str, direction: str) -> tuple[int, str]:
        """
        Get scoring points for a trade direction.
        
        Returns:
            (points, reason) — 0 or 2 points
        """
        signal = self.analyze(ticker)
        if signal is None:
            return 0, "Order book data unavailable"
        return signal.score_points(direction, self.wobi_threshold)

    def get_status(self, ticker: str) -> dict:
        """Get current order book status for dashboard."""
        signal = self.analyze(ticker)
        if signal is None:
            return {"ticker": ticker, "enabled": self.enabled, "data": None}
        return {
            "ticker": ticker,
            "enabled": self.enabled,
            "wobi": round(signal.wobi, 4),
            "depth_ratio": round(signal.depth_ratio, 3),
            "spread_bps": round(signal.spread_bps, 2),
            "bid_wall": signal.bid_wall,
            "ask_wall": signal.ask_wall,
            "direction_bias": signal.direction_bias,
            "mid_price": signal.mid_price,
        }
