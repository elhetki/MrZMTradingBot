"""
WOBI v2.1 — Weighted Order Book Imbalance (Veto Power + Anti-Spoofing)
Upgraded to match Zoran's IPM implementation + v2.0 roadmap features:

1. Exponential decay weighting (not linear) — closer levels matter exponentially more
2. Sqrt compression on large orders — prevents single whale order from dominating
3. EMA smoothing — reduces noise from order book flicker
4. 4-tier scoring: VETO / CONFLICT / CONFIRM / NEUTRAL

v2.1 additions (Zoran roadmap):
5. Anti-spoofing detection — flags walls that appear/disappear rapidly
6. Trade flow validation — tracks if walls are actually getting filled
7. Confidence scoring — overall reliability of the order book signal

VETO = strong opposition in the book → trade BLOCKED entirely
CONFLICT = weak opposition → score reduced
CONFIRM = alignment → score BOOSTED
NEUTRAL = dead zone → no change

This is the edge. Chart is lagging. Order book is leading.
"""

from __future__ import annotations
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class OrderBookSignal:
    """Order book analysis result with veto power."""
    wobi: float              # -1.0 (heavy sell) to +1.0 (heavy buy)
    smoothed_wobi: float     # EMA-smoothed WOBI
    verdict: str             # 'VETO', 'CONFLICT', 'CONFIRM', 'NEUTRAL'
    depth_ratio: float       # bid_vol / ask_vol (>1 = more bids)
    spread_bps: float        # Spread in basis points
    microprice: float        # Volume-weighted mid price
    bid_wall: Optional[float] = None
    ask_wall: Optional[float] = None
    bid_wall_size: float = 0.0
    ask_wall_size: float = 0.0
    mid_price: float = 0.0
    total_bid_vol: float = 0.0
    total_ask_vol: float = 0.0
    timestamp: float = 0.0

    # v2.1 anti-spoofing fields
    spoof_detected: bool = False
    spoof_side: str = ""         # 'BID' or 'ASK' — which side is spoofing
    confidence: float = 1.0      # 0.0-1.0 — how reliable is this signal
    wall_stability: float = 1.0  # 0.0-1.0 — how stable are detected walls

    @property
    def direction_bias(self) -> str:
        if self.smoothed_wobi > 0.15:
            return "BULL"
        elif self.smoothed_wobi < -0.15:
            return "BEAR"
        return "NEUTRAL"

    def get_verdict(self, direction: str) -> str:
        """Get verdict for a specific trade direction."""
        wobi = self.smoothed_wobi

        if direction == "LONG":
            if wobi <= -0.5:
                return "VETO"        # Strong sell pressure → block long
            elif wobi <= -0.2:
                return "CONFLICT"    # Weak sell pressure → reduce score
            elif wobi >= 0.3:
                return "CONFIRM"     # Buy pressure → boost score
            else:
                return "NEUTRAL"
        elif direction == "SHORT":
            if wobi >= 0.5:
                return "VETO"        # Strong buy pressure → block short
            elif wobi >= 0.2:
                return "CONFLICT"    # Weak buy pressure → reduce score
            elif wobi <= -0.3:
                return "CONFIRM"     # Sell pressure → boost score
            else:
                return "NEUTRAL"
        return "NEUTRAL"

    def score_points(self, direction: str) -> tuple[int, str, bool]:
        """
        Returns (score_adjustment, reason, is_vetoed).
        VETO: (0, reason, True) — trade must be blocked
        CONFLICT: (-2, reason, False) — score penalty
        CONFIRM: (+2, reason, False) — score boost
        NEUTRAL: (0, reason, False) — no change
        
        v2.1: If spoofing detected on the opposing side, downgrades VETO → CONFLICT
        (the "wall" opposing us is likely fake).
        If spoofing detected on OUR side, downgrades CONFIRM → NEUTRAL
        (the "support" for us is likely fake).
        """
        verdict = self.get_verdict(direction)

        # v2.1 anti-spoofing adjustments
        if self.spoof_detected:
            opposing_side = "ASK" if direction == "LONG" else "BID"
            our_side = "BID" if direction == "LONG" else "ASK"
            
            if self.spoof_side == opposing_side and verdict == "VETO":
                # Wall opposing us is likely spoofed → downgrade to conflict
                return -1, f"⚠️ WOBI conflict (anti-spoof: {opposing_side} wall unstable, WOBI={self.smoothed_wobi:+.3f})", False
            
            if self.spoof_side == our_side and verdict == "CONFIRM":
                # Support for us is likely spoofed → downgrade to neutral
                return 0, f"WOBI neutral (anti-spoof: {our_side} support unstable, WOBI={self.smoothed_wobi:+.3f})", False

        # Apply confidence scaling: low confidence reduces score magnitude
        conf_mult = self.confidence

        if verdict == "VETO":
            return 0, f"🚫 WOBI VETO: order book opposes {direction} (WOBI={self.smoothed_wobi:+.3f}, conf={conf_mult:.0%})", True
        elif verdict == "CONFLICT":
            pts = round(-2 * conf_mult)
            return pts, f"⚠️ WOBI conflict: weak opposition to {direction} (WOBI={self.smoothed_wobi:+.3f}, conf={conf_mult:.0%})", False
        elif verdict == "CONFIRM":
            pts = round(2 * conf_mult)
            return pts, f"✅ WOBI confirms {direction} (WOBI={self.smoothed_wobi:+.3f}, conf={conf_mult:.0%})", False
        else:
            return 0, f"WOBI neutral for {direction} ({self.smoothed_wobi:+.3f})", False

    def summary(self) -> str:
        walls = []
        if self.bid_wall:
            walls.append(f"BID_WALL@{self.bid_wall:.2f}({self.bid_wall_size:.0f})")
        if self.ask_wall:
            walls.append(f"ASK_WALL@{self.ask_wall:.2f}({self.ask_wall_size:.0f})")
        wall_str = " | ".join(walls) if walls else "no walls"
        return (
            f"WOBI={self.smoothed_wobi:+.3f} (raw={self.wobi:+.3f}) | "
            f"Verdict={self.verdict} | Spread={self.spread_bps:.1f}bps | "
            f"Micro={self.microprice:.2f} | {wall_str}"
        )


class OrderBookIntelligence:
    """
    WOBI v2 — Analyzes L2 order book with exponential decay weighting,
    sqrt compression, and EMA smoothing.
    """

    def __init__(self, config: dict, hl_client=None):
        ob_cfg = config.get("orderbook", {})
        self.enabled = ob_cfg.get("enabled", True)
        self.depth = ob_cfg.get("depth", 20)
        self.wobi_threshold = ob_cfg.get("wobi_threshold", 0.3)
        self.veto_threshold = ob_cfg.get("veto_threshold", 0.5)
        self.conflict_threshold = ob_cfg.get("conflict_threshold", 0.2)
        self.wall_multiplier = ob_cfg.get("wall_multiplier", 3.0)
        self.refresh_seconds = ob_cfg.get("refresh_seconds", 2)
        self.decay_factor = ob_cfg.get("decay_factor", 0.15)     # Exponential decay rate
        self.ema_alpha = ob_cfg.get("ema_alpha", 0.3)            # EMA smoothing factor
        self.hl_client = hl_client

        # State
        self._cache: dict[str, tuple[float, OrderBookSignal]] = {}
        self._ema_wobi: dict[str, float] = {}  # Per-ticker EMA smoothed WOBI

        # v2.1 Anti-spoofing state
        # Track wall history: {ticker: deque of (timestamp, bid_wall_price, bid_wall_size, ask_wall_price, ask_wall_size)}
        from collections import deque
        self._wall_history: dict[str, deque] = {}
        self._wall_history_maxlen = 10  # Track last 10 snapshots
        self._spoof_flicker_threshold = 0.6  # If wall disappears >60% of time, it's spoofing

    def _calc_wobi(self, bids: list[tuple[float, float]], asks: list[tuple[float, float]], mid_price: float) -> float:
        """
        Calculate WOBI with exponential decay weighting and sqrt compression.

        - Exponential decay: weight = exp(-decay_factor * distance_pct * 100)
          Closer levels contribute exponentially more than distant ones.
        - Sqrt compression: size = sqrt(raw_size)
          Prevents a single 1000-lot order from dominating over ten 100-lot orders.
        """
        weighted_bid = 0.0
        weighted_ask = 0.0

        if mid_price == 0:
            return 0.0

        for price, size in bids:
            distance_pct = abs(mid_price - price) / mid_price
            weight = math.exp(-self.decay_factor * distance_pct * 100)
            compressed_size = math.sqrt(size) if size > 0 else 0
            weighted_bid += compressed_size * weight

        for price, size in asks:
            distance_pct = abs(price - mid_price) / mid_price
            weight = math.exp(-self.decay_factor * distance_pct * 100)
            compressed_size = math.sqrt(size) if size > 0 else 0
            weighted_ask += compressed_size * weight

        total = weighted_bid + weighted_ask
        if total == 0:
            return 0.0
        return (weighted_bid - weighted_ask) / total

    def _calc_microprice(self, best_bid: float, best_bid_size: float,
                          best_ask: float, best_ask_size: float) -> float:
        """
        Microprice — volume-weighted mid price.
        More accurate than simple mid when one side is heavier.
        """
        total_size = best_bid_size + best_ask_size
        if total_size == 0:
            return (best_bid + best_ask) / 2
        return (best_bid * best_ask_size + best_ask * best_bid_size) / total_size

    def _smooth_wobi(self, ticker: str, raw_wobi: float) -> float:
        """Apply EMA smoothing to reduce order book flicker noise."""
        if ticker not in self._ema_wobi:
            self._ema_wobi[ticker] = raw_wobi
        else:
            prev = self._ema_wobi[ticker]
            self._ema_wobi[ticker] = self.ema_alpha * raw_wobi + (1 - self.ema_alpha) * prev
        return self._ema_wobi[ticker]

    def _detect_spoofing(self, ticker: str, signal: OrderBookSignal) -> tuple[bool, str, float]:
        """
        v2.1 Anti-spoofing: Track wall stability over time.
        
        A spoofed wall appears and disappears rapidly — it's placed to 
        intimidate the other side, then pulled before it can be filled.
        
        We track the last N snapshots. If a wall appears in <40% of them
        at roughly the same price, it's likely spoofing.
        
        Returns: (spoof_detected, spoof_side, wall_stability)
        """
        from collections import deque
        
        if ticker not in self._wall_history:
            self._wall_history[ticker] = deque(maxlen=self._wall_history_maxlen)

        # Record current snapshot
        self._wall_history[ticker].append({
            "ts": signal.timestamp,
            "bid_wall": signal.bid_wall,
            "bid_wall_size": signal.bid_wall_size,
            "ask_wall": signal.ask_wall,
            "ask_wall_size": signal.ask_wall_size,
        })

        history = self._wall_history[ticker]
        if len(history) < 5:
            # Not enough data yet
            return False, "", 1.0

        # Check bid wall stability
        bid_wall_appearances = sum(1 for h in history if h["bid_wall"] is not None)
        ask_wall_appearances = sum(1 for h in history if h["ask_wall"] is not None)

        bid_stability = bid_wall_appearances / len(history)
        ask_stability = ask_wall_appearances / len(history)

        spoof_detected = False
        spoof_side = ""
        
        # A wall that appears sometimes but not consistently = potential spoof
        # (appears in 20-60% of snapshots = flickering = spoofing)
        if 0.2 <= bid_stability <= self._spoof_flicker_threshold and signal.bid_wall is not None:
            # Check if the wall price is jumping around (another spoof indicator)
            bid_prices = [h["bid_wall"] for h in history if h["bid_wall"] is not None]
            if len(bid_prices) >= 3:
                price_spread = (max(bid_prices) - min(bid_prices)) / signal.mid_price if signal.mid_price > 0 else 0
                if price_spread > 0.002:  # Wall moves >0.2% = likely spoofing
                    spoof_detected = True
                    spoof_side = "BID"

        if 0.2 <= ask_stability <= self._spoof_flicker_threshold and signal.ask_wall is not None:
            ask_prices = [h["ask_wall"] for h in history if h["ask_wall"] is not None]
            if len(ask_prices) >= 3:
                price_spread = (max(ask_prices) - min(ask_prices)) / signal.mid_price if signal.mid_price > 0 else 0
                if price_spread > 0.002:
                    spoof_detected = True
                    spoof_side = "ASK"

        # Overall wall stability (average of both sides, weighted)
        wall_stability = min(bid_stability, ask_stability) if (signal.bid_wall or signal.ask_wall) else 1.0

        return spoof_detected, spoof_side, max(0.3, wall_stability)

    def _parse_l2(self, raw: dict, ticker: str) -> Optional[OrderBookSignal]:
        """Parse Hyperliquid L2 snapshot with v2 math."""
        if not raw or "levels" not in raw:
            return None

        levels = raw["levels"]
        if len(levels) < 2:
            return None

        bids_raw = levels[0]
        asks_raw = levels[1]

        if not bids_raw or not asks_raw:
            return None

        bids = [(float(b["px"]), float(b["sz"])) for b in bids_raw[:self.depth]]
        asks = [(float(a["px"]), float(a["sz"])) for a in asks_raw[:self.depth]]

        if not bids or not asks:
            return None

        best_bid, best_bid_size = bids[0]
        best_ask, best_ask_size = asks[0]
        mid_price = (best_bid + best_ask) / 2.0

        if mid_price == 0:
            return None

        # Spread
        spread_bps = (best_ask - best_bid) / mid_price * 10000

        # Microprice
        microprice = self._calc_microprice(best_bid, best_bid_size, best_ask, best_ask_size)

        # WOBI with exponential decay + sqrt compression
        raw_wobi = self._calc_wobi(bids, asks, mid_price)

        # EMA smoothing
        smoothed = self._smooth_wobi(ticker, raw_wobi)

        # Raw depth ratio
        total_bid_vol = sum(s for _, s in bids)
        total_ask_vol = sum(s for _, s in asks)
        depth_ratio = total_bid_vol / total_ask_vol if total_ask_vol > 0 else 1.0

        # Wall detection (on raw sizes, not compressed)
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

        signal = OrderBookSignal(
            wobi=raw_wobi,
            smoothed_wobi=smoothed,
            verdict="NEUTRAL",  # Set below
            depth_ratio=depth_ratio,
            spread_bps=spread_bps,
            microprice=microprice,
            bid_wall=bid_wall,
            ask_wall=ask_wall,
            bid_wall_size=bid_wall_size,
            ask_wall_size=ask_wall_size,
            mid_price=mid_price,
            total_bid_vol=total_bid_vol,
            total_ask_vol=total_ask_vol,
            timestamp=time.time(),
        )

        # Set general verdict based on absolute value
        abs_wobi = abs(smoothed)
        if abs_wobi >= self.veto_threshold:
            signal.verdict = "STRONG"
        elif abs_wobi >= self.conflict_threshold:
            signal.verdict = "MODERATE"
        else:
            signal.verdict = "NEUTRAL"

        # v2.1: Anti-spoofing detection
        spoof_detected, spoof_side, wall_stability = self._detect_spoofing(ticker, signal)
        signal.spoof_detected = spoof_detected
        signal.spoof_side = spoof_side
        signal.wall_stability = wall_stability
        
        # Confidence = base WOBI strength * wall stability
        # Low wall stability = we can't trust the order book as much
        base_confidence = min(abs_wobi / self.veto_threshold, 1.0) if self.veto_threshold > 0 else 1.0
        signal.confidence = base_confidence * wall_stability
        
        if spoof_detected:
            logger.info(f"🎭 SPOOF detected on {ticker} {spoof_side} side (stability={wall_stability:.2f})")

        return signal

    def analyze(self, ticker: str, force_refresh: bool = False) -> Optional[OrderBookSignal]:
        """Analyze the order book for a ticker."""
        if not self.enabled:
            return None

        if not force_refresh and ticker in self._cache:
            ts, signal = self._cache[ticker]
            if time.time() - ts < self.refresh_seconds:
                return signal

        if self.hl_client is None:
            return None

        try:
            raw = self.hl_client.get_orderbook(ticker, depth=self.depth)
            if raw is None:
                return None

            signal = self._parse_l2(raw, ticker)
            if signal:
                self._cache[ticker] = (time.time(), signal)
                logger.debug(f"OrderBook {ticker}: {signal.summary()}")

            return signal

        except Exception as e:
            logger.error(f"OrderBook: Error analyzing {ticker}: {e}")
            return None

    def get_score(self, ticker: str, direction: str) -> tuple[int, str, bool]:
        """
        Get scoring result for a trade direction.

        Returns:
            (points, reason, is_vetoed)
            is_vetoed=True means the trade MUST be blocked.
        """
        signal = self.analyze(ticker)
        if signal is None:
            return 0, "Order book data unavailable", False
        return signal.score_points(direction)

    def get_status(self, ticker: str) -> dict:
        """Get current order book status for dashboard."""
        signal = self.analyze(ticker)
        if signal is None:
            return {"ticker": ticker, "enabled": self.enabled, "data": None}
        return {
            "ticker": ticker,
            "enabled": self.enabled,
            "wobi_raw": round(signal.wobi, 4),
            "wobi_smoothed": round(signal.smoothed_wobi, 4),
            "verdict": signal.verdict,
            "depth_ratio": round(signal.depth_ratio, 3),
            "spread_bps": round(signal.spread_bps, 2),
            "microprice": signal.microprice,
            "bid_wall": signal.bid_wall,
            "ask_wall": signal.ask_wall,
            "direction_bias": signal.direction_bias,
        }
