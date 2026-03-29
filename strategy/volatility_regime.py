"""
Volatility Regime Detection v1.0
Detects market regime and adjusts position sizing + signal thresholds.

Three regimes:
  CALM     — Low volatility, small moves. Trade cautiously (70% size).
  TRENDING — Medium volatility, directional. Full aggression (100% size).
  STORM    — High volatility, chaotic. Reduce size (30%), raise min score.

Detection uses:
  1. ATR ratio: current ATR vs 20-period average ATR
  2. Bollinger Band width expansion rate
  3. Price range vs average candle body size

Inspired by Zoran's I.P.M. framework (simplified for v1).
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


class Regime(Enum):
    CALM = "CALM"
    TRENDING = "TRENDING"
    STORM = "STORM"


@dataclass
class RegimeResult:
    regime: Regime
    atr_ratio: float          # Current ATR / Average ATR (1.0 = normal)
    bb_width_ratio: float     # Current BB width / Average BB width
    size_multiplier: float    # Position sizing adjustment
    min_score_override: Optional[int] = None  # Override min_score in storm
    reason: str = ""

    def summary(self) -> str:
        emoji = {"CALM": "☀️", "TRENDING": "🌤️", "STORM": "🌪️"}
        return (
            f"{emoji.get(self.regime.value, '?')} {self.regime.value} | "
            f"ATR ratio: {self.atr_ratio:.2f} | BB ratio: {self.bb_width_ratio:.2f} | "
            f"Size: {self.size_multiplier:.0%}"
        )


class VolatilityRegimeDetector:
    """
    Detects current market volatility regime from OHLCV data.
    """

    def __init__(self, config: dict = None):
        cfg = config or {}
        self.enabled = cfg.get("enabled", True)
        self.atr_period = cfg.get("atr_period", 14)
        self.atr_lookback = cfg.get("atr_lookback", 50)  # Average ATR over this many candles
        self.bb_period = cfg.get("bb_period", 20)
        self.bb_std = cfg.get("bb_std", 2.0)

        # Thresholds
        self.storm_atr_threshold = cfg.get("storm_atr_threshold", 1.8)   # ATR 1.8x above average = storm
        self.calm_atr_threshold = cfg.get("calm_atr_threshold", 0.6)     # ATR 0.6x below average = calm
        self.storm_bb_threshold = cfg.get("storm_bb_threshold", 2.0)     # BB width 2x above average = storm

        # Sizing adjustments
        self.calm_size = cfg.get("calm_size", 0.7)
        self.trending_size = cfg.get("trending_size", 1.0)
        self.storm_size = cfg.get("storm_size", 0.3)
        self.storm_min_score = cfg.get("storm_min_score", 8)

        # Cache: {ticker: (timestamp, RegimeResult)}
        self._cache: dict[str, tuple[float, RegimeResult]] = {}
        self._cache_ttl = 300  # 5 minutes

    def detect(self, ticker: str, df: pd.DataFrame) -> RegimeResult:
        """
        Detect volatility regime from OHLCV dataframe.

        Args:
            ticker: Market symbol
            df: DataFrame with columns: open, high, low, close

        Returns:
            RegimeResult with regime classification and adjustments
        """
        if not self.enabled or len(df) < self.atr_lookback + self.atr_period:
            return RegimeResult(
                regime=Regime.TRENDING,
                atr_ratio=1.0,
                bb_width_ratio=1.0,
                size_multiplier=1.0,
                reason="Insufficient data or disabled"
            )

        # Check cache
        import time
        now = time.time()
        cached = self._cache.get(ticker)
        if cached and (now - cached[0]) < self._cache_ttl:
            return cached[1]

        # Calculate ATR
        atr_ratio = self._calc_atr_ratio(df)

        # Calculate Bollinger Band width ratio
        bb_width_ratio = self._calc_bb_width_ratio(df)

        # Determine regime
        regime, reason = self._classify(atr_ratio, bb_width_ratio)

        # Set adjustments
        if regime == Regime.STORM:
            size_mult = self.storm_size
            min_score = self.storm_min_score
        elif regime == Regime.CALM:
            size_mult = self.calm_size
            min_score = None
        else:
            size_mult = self.trending_size
            min_score = None

        result = RegimeResult(
            regime=regime,
            atr_ratio=atr_ratio,
            bb_width_ratio=bb_width_ratio,
            size_multiplier=size_mult,
            min_score_override=min_score,
            reason=reason,
        )

        # Cache
        self._cache[ticker] = (now, result)

        logger.info(f"[REGIME] {ticker}: {result.summary()}")
        return result

    def _calc_atr_ratio(self, df: pd.DataFrame) -> float:
        """Calculate ratio of current ATR to average ATR."""
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values

        # True Range
        tr = []
        for i in range(1, len(df)):
            tr.append(max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1])
            ))

        if len(tr) < self.atr_lookback:
            return 1.0

        tr_series = pd.Series(tr)

        # Current ATR (last atr_period candles)
        current_atr = tr_series.iloc[-self.atr_period:].mean()

        # Average ATR (over lookback period)
        avg_atr = tr_series.iloc[-self.atr_lookback:].mean()

        if avg_atr == 0:
            return 1.0

        return current_atr / avg_atr

    def _calc_bb_width_ratio(self, df: pd.DataFrame) -> float:
        """Calculate ratio of current BB width to average BB width."""
        close = df['close']

        sma = close.rolling(self.bb_period).mean()
        std = close.rolling(self.bb_period).std()

        upper = sma + self.bb_std * std
        lower = sma - self.bb_std * std

        bb_width = (upper - lower) / sma  # Normalized width

        if len(bb_width.dropna()) < self.atr_lookback:
            return 1.0

        current_width = bb_width.iloc[-1]
        avg_width = bb_width.iloc[-self.atr_lookback:].mean()

        if avg_width == 0 or pd.isna(current_width) or pd.isna(avg_width):
            return 1.0

        return current_width / avg_width

    def _classify(self, atr_ratio: float, bb_ratio: float) -> tuple[Regime, str]:
        """Classify regime from ATR and BB ratios."""
        # STORM: Either ATR or BB width is way above normal
        if atr_ratio >= self.storm_atr_threshold or bb_ratio >= self.storm_bb_threshold:
            reasons = []
            if atr_ratio >= self.storm_atr_threshold:
                reasons.append(f"ATR {atr_ratio:.1f}x above normal")
            if bb_ratio >= self.storm_bb_threshold:
                reasons.append(f"BB width {bb_ratio:.1f}x expanded")
            return Regime.STORM, f"🌪️ STORM: {', '.join(reasons)}"

        # CALM: Both ATR and BB width are below normal
        if atr_ratio <= self.calm_atr_threshold and bb_ratio <= 0.8:
            return Regime.CALM, f"☀️ CALM: Low volatility (ATR {atr_ratio:.1f}x, BB {bb_ratio:.1f}x)"

        # TRENDING: Normal volatility range
        return Regime.TRENDING, f"🌤️ TRENDING: Normal conditions (ATR {atr_ratio:.1f}x)"
