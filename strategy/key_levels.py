"""
Key Level Detection — Dynamic Support/Resistance from 1H candles
================================================================
Zoran's approach: Scan last 60 hourly candles, find real S/R pivots.
Entries near key levels get a score bonus. Mid-range entries don't.

Pivot Logic:
- A pivot HIGH is a candle high that is higher than N candles on each side
- A pivot LOW is a candle low that is lower than N candles on each side
- Multiple touches at similar price = stronger level
- Levels are clustered within a tolerance band (ATR-based)

Scoring:
- Entry within 0.5% of a key level: +3 (high conviction)
- Entry within 1.0% of a key level: +2 (decent proximity)
- Entry within 1.5% of a key level: +1 (marginal)
- Entry far from any level: 0 (no bonus)

Additional: If direction aligns with level type (LONG near support, SHORT near resistance),
the bonus is full. Misaligned trades (LONG at resistance) get 0.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class KeyLevel:
    price: float
    level_type: str      # 'SUPPORT' or 'RESISTANCE'
    strength: int        # Number of touches/pivots at this level
    last_touch_idx: int  # Index of most recent touch
    
    def __repr__(self):
        return f"{self.level_type}@{self.price:.4f} (str={self.strength})"


@dataclass
class KeyLevelResult:
    score_bonus: int           # Points to add to entry score
    nearest_level: Optional[KeyLevel] = None
    distance_pct: float = 0.0  # Distance to nearest relevant level as %
    reason: str = ""
    all_levels: list[KeyLevel] = field(default_factory=list)

    def summary(self) -> str:
        if self.nearest_level:
            return f"Score +{self.score_bonus} | {self.nearest_level} | dist={self.distance_pct:.3f}% | {self.reason}"
        return f"Score +{self.score_bonus} | {self.reason}"


class KeyLevelDetector:
    """
    Detects dynamic support and resistance levels from hourly candles.
    
    Config keys (under "key_levels"):
        enabled: bool (default True)
        hourly_lookback: int (default 60) — how many 1H candles to scan
        pivot_window: int (default 3) — candles on each side for pivot detection
        cluster_tolerance_atr: float (default 0.5) — ATR multiplier for clustering
        proximity_tiers: list — [0.5, 1.0, 1.5] % distance tiers for scoring
        score_tiers: list — [3, 2, 1] points per tier
    """

    def __init__(self, config: dict, hl_client=None):
        kl_cfg = config.get("key_levels", {})
        self.enabled = kl_cfg.get("enabled", True)
        self.hourly_lookback = kl_cfg.get("hourly_lookback", 60)
        self.pivot_window = kl_cfg.get("pivot_window", 3)
        self.cluster_tolerance_atr = kl_cfg.get("cluster_tolerance_atr", 0.5)
        self.proximity_tiers = kl_cfg.get("proximity_tiers", [0.5, 1.0, 1.5])
        self.score_tiers = kl_cfg.get("score_tiers", [3, 2, 1])
        self.hl_client = hl_client

        # Cache: {ticker: (timestamp, levels)}
        self._cache: dict[str, tuple[float, list[KeyLevel]]] = {}
        self._cache_ttl = 300  # Refresh every 5 minutes

    def _find_pivots(self, df: pd.DataFrame) -> list[tuple[float, str, int]]:
        """
        Find pivot highs and lows in the dataframe.
        
        Returns list of (price, 'HIGH'|'LOW', index)
        """
        pivots = []
        highs = df["high"].values.astype(float)
        lows = df["low"].values.astype(float)
        w = self.pivot_window

        for i in range(w, len(df) - w):
            # Pivot high: higher than w candles on each side
            is_pivot_high = True
            for j in range(1, w + 1):
                if highs[i] <= highs[i - j] or highs[i] <= highs[i + j]:
                    is_pivot_high = False
                    break
            if is_pivot_high:
                pivots.append((highs[i], "HIGH", i))

            # Pivot low: lower than w candles on each side
            is_pivot_low = True
            for j in range(1, w + 1):
                if lows[i] >= lows[i - j] or lows[i] >= lows[i + j]:
                    is_pivot_low = False
                    break
            if is_pivot_low:
                pivots.append((lows[i], "LOW", i))

        return pivots

    def _cluster_levels(self, pivots: list[tuple[float, str, int]], atr: float) -> list[KeyLevel]:
        """
        Cluster nearby pivots into key levels.
        Pivots within (cluster_tolerance_atr * ATR) of each other are merged.
        """
        if not pivots or atr == 0:
            return []

        tolerance = atr * self.cluster_tolerance_atr
        
        # Sort by price
        sorted_pivots = sorted(pivots, key=lambda x: x[0])
        
        levels: list[KeyLevel] = []
        used = set()

        for i, (price, ptype, idx) in enumerate(sorted_pivots):
            if i in used:
                continue

            cluster_prices = [price]
            cluster_types = [ptype]
            cluster_indices = [idx]
            used.add(i)

            for j in range(i + 1, len(sorted_pivots)):
                if j in used:
                    continue
                if abs(sorted_pivots[j][0] - price) <= tolerance:
                    cluster_prices.append(sorted_pivots[j][0])
                    cluster_types.append(sorted_pivots[j][1])
                    cluster_indices.append(sorted_pivots[j][2])
                    used.add(j)
                else:
                    break  # Sorted, so no more matches

            # Determine level type from cluster composition
            highs = cluster_types.count("HIGH")
            lows = cluster_types.count("LOW")
            level_type = "RESISTANCE" if highs >= lows else "SUPPORT"

            avg_price = np.mean(cluster_prices)
            strength = len(cluster_prices)  # More touches = stronger
            last_touch = max(cluster_indices)

            levels.append(KeyLevel(
                price=float(avg_price),
                level_type=level_type,
                strength=strength,
                last_touch_idx=last_touch,
            ))

        # Sort by strength descending, keep top 10
        levels.sort(key=lambda x: x.strength, reverse=True)
        return levels[:10]

    def _calc_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range."""
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        close = df["close"].astype(float)
        
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period).mean()
        
        return float(atr.iloc[-1]) if not atr.empty and not pd.isna(atr.iloc[-1]) else 0.0

    def detect_levels(self, ticker: str) -> list[KeyLevel]:
        """
        Detect key S/R levels for a ticker using 1H candles.
        Results are cached for 5 minutes.
        """
        if not self.enabled:
            return []

        import time
        now = time.time()
        
        if ticker in self._cache:
            ts, levels = self._cache[ticker]
            if now - ts < self._cache_ttl:
                return levels

        if self.hl_client is None:
            return []

        try:
            # Fetch 1H candles
            df = self.hl_client.get_candles(ticker, interval="1h", limit=self.hourly_lookback + 5)
            if df is None or len(df) < 20:
                return []

            # Find pivots
            pivots = self._find_pivots(df)
            if not pivots:
                return []

            # Calculate ATR for clustering tolerance
            atr = self._calc_atr(df)
            if atr == 0:
                return []

            # Cluster into key levels
            levels = self._cluster_levels(pivots, atr)

            self._cache[ticker] = (now, levels)
            
            if levels:
                logger.debug(f"Key levels for {ticker}: {[str(l) for l in levels[:5]]}")

            return levels

        except Exception as e:
            logger.error(f"Key level detection failed for {ticker}: {e}")
            return []

    def score_entry(self, ticker: str, price: float, direction: str) -> KeyLevelResult:
        """
        Score an entry based on proximity to key levels.
        
        Rules:
        - LONG near SUPPORT = bonus (buying at support)
        - SHORT near RESISTANCE = bonus (selling at resistance)
        - LONG near RESISTANCE = no bonus (buying into ceiling)
        - SHORT near SUPPORT = no bonus (selling into floor)
        
        Args:
            ticker: Market symbol
            price: Current entry price
            direction: 'LONG' or 'SHORT'
            
        Returns:
            KeyLevelResult with score_bonus and details
        """
        if not self.enabled:
            return KeyLevelResult(score_bonus=0, reason="Key levels disabled")

        levels = self.detect_levels(ticker)
        if not levels:
            return KeyLevelResult(score_bonus=0, reason="No key levels detected")

        # Find nearest ALIGNED level
        # LONG → look for SUPPORT levels nearby
        # SHORT → look for RESISTANCE levels nearby
        target_type = "SUPPORT" if direction == "LONG" else "RESISTANCE"
        
        best_score = 0
        best_level = None
        best_dist = float("inf")

        for level in levels:
            if level.level_type != target_type:
                continue

            dist_pct = abs(price - level.price) / level.price * 100

            # Check proximity tiers
            for tier_pct, tier_score in zip(self.proximity_tiers, self.score_tiers):
                if dist_pct <= tier_pct:
                    # Stronger levels get a slight bonus
                    effective_score = tier_score
                    if level.strength >= 3:
                        effective_score = min(tier_score + 1, 3)  # Cap at 3
                    
                    if effective_score > best_score or (effective_score == best_score and dist_pct < best_dist):
                        best_score = effective_score
                        best_level = level
                        best_dist = dist_pct
                    break  # Found tier for this level, move to next level

        if best_level:
            return KeyLevelResult(
                score_bonus=best_score,
                nearest_level=best_level,
                distance_pct=best_dist,
                reason=f"{direction} near {best_level.level_type}@{best_level.price:.4f} ({best_dist:.2f}% away, str={best_level.strength})",
                all_levels=levels,
            )

        return KeyLevelResult(
            score_bonus=0,
            reason=f"No aligned {target_type} level within {self.proximity_tiers[-1]}% of price {price:.4f}",
            all_levels=levels,
        )
