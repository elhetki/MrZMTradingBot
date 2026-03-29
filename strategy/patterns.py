"""
Chart Pattern Detection — 23 Patterns
Replaces the basic engulfing/flag detection in scoring.py with a
comprehensive pattern library matching Zoran's v2.5.

Categories:
  Reversal:    Double Top/Bottom, Head & Shoulders (+ inverse), Pin Bars, Doji
  Continuation: Bull/Bear Flags, Ascending/Descending Triangles, Wedges, Cup & Handle
  Momentum:    Engulfing, Three Soldiers/Crows, Momentum burst
  Key Levels:  Support/Resistance bounce

Scoring:
  Strong pattern (high reliability): +3 points
  Standard pattern:                  +2 points
  Weak/early pattern:                +1 point
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class PatternMatch:
    """A detected chart pattern."""
    name: str
    category: str        # 'reversal', 'continuation', 'momentum', 'key_level'
    direction: str       # 'BULL', 'BEAR', 'NEUTRAL'
    score: int           # 1-3 points
    confidence: float    # 0.0-1.0
    description: str = ""


class PatternDetector:
    """
    Scans OHLCV data for 23 chart patterns.
    Returns all matches sorted by score (highest first).
    """

    def __init__(self, config: dict = None):
        self.config = config or {}

    def detect_all(self, df: pd.DataFrame, direction: str = "LONG") -> list[PatternMatch]:
        """
        Run all pattern detections and return matches aligned with direction.

        Args:
            df: OHLCV DataFrame (minimum 50 candles recommended)
            direction: 'LONG' or 'SHORT' — only returns patterns matching this bias

        Returns:
            List of PatternMatch sorted by score descending
        """
        if len(df) < 20:
            return []

        target_bias = "BULL" if direction == "LONG" else "BEAR"
        all_patterns = []

        # Run all detectors
        detectors = [
            self._bullish_engulfing, self._bearish_engulfing,
            self._bull_flag, self._bear_flag,
            self._double_bottom, self._double_top,
            self._head_shoulders, self._inv_head_shoulders,
            self._ascending_triangle, self._descending_triangle,
            # self._rising_wedge, self._falling_wedge,  # Disabled: 0% WR (Zoran data)
            self._cup_and_handle,
            self._pin_bar_bull, self._pin_bar_bear,
            self._doji_at_level,
            self._three_white_soldiers, self._three_black_crows,
            self._morning_star, self._evening_star,
            self._momentum_burst,
            self._support_bounce, self._resistance_rejection,
        ]

        for detector in detectors:
            try:
                match = detector(df)
                if match and (match.direction == target_bias or match.direction == "NEUTRAL"):
                    all_patterns.append(match)
            except Exception as e:
                logger.debug(f"Pattern detection error in {detector.__name__}: {e}")

        # Sort by score descending
        all_patterns.sort(key=lambda p: p.score, reverse=True)
        return all_patterns

    def best_pattern(self, df: pd.DataFrame, direction: str = "LONG") -> tuple[int, str]:
        """
        Get the best matching pattern's score and name.
        Returns (score, description) for the scoring engine.
        """
        patterns = self.detect_all(df, direction)
        if not patterns:
            return 0, "No chart pattern detected"
        best = patterns[0]
        count = len(patterns)
        extra = f" (+{count-1} more)" if count > 1 else ""
        return best.score, f"{best.name}{extra}: {best.description}"

    # ════════════════════════════════════════════════════════════════
    # Helper methods
    # ════════════════════════════════════════════════════════════════

    def _body(self, row) -> float:
        return abs(float(row["close"]) - float(row["open"]))

    def _is_bullish(self, row) -> bool:
        return float(row["close"]) > float(row["open"])

    def _is_bearish(self, row) -> bool:
        return float(row["close"]) < float(row["open"])

    def _upper_wick(self, row) -> float:
        return float(row["high"]) - max(float(row["open"]), float(row["close"]))

    def _lower_wick(self, row) -> float:
        return min(float(row["open"]), float(row["close"])) - float(row["low"])

    def _avg_body(self, df: pd.DataFrame, n: int = 10) -> float:
        tail = df.iloc[-n:]
        bodies = abs(tail["close"].astype(float) - tail["open"].astype(float))
        return float(bodies.mean()) if len(bodies) > 0 else 0.001

    # ════════════════════════════════════════════════════════════════
    # REVERSAL PATTERNS
    # ════════════════════════════════════════════════════════════════

    def _bullish_engulfing(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        if len(df) < 2:
            return None
        prev, curr = df.iloc[-2], df.iloc[-1]
        if (self._is_bearish(prev) and self._is_bullish(curr) and
                float(curr["close"]) > float(prev["open"]) and
                float(curr["open"]) < float(prev["close"])):
            return PatternMatch("Bullish Engulfing", "reversal", "BULL", 3, 0.75,
                                "Strong bullish reversal candle")
        return None

    def _bearish_engulfing(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        if len(df) < 2:
            return None
        prev, curr = df.iloc[-2], df.iloc[-1]
        if (self._is_bullish(prev) and self._is_bearish(curr) and
                float(curr["close"]) < float(prev["open"]) and
                float(curr["open"]) > float(prev["close"])):
            return PatternMatch("Bearish Engulfing", "reversal", "BEAR", 3, 0.75,
                                "Strong bearish reversal candle")
        return None

    def _double_bottom(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Two lows at similar price with a higher high between them."""
        if len(df) < 20:
            return None
        lows = df["low"].astype(float).iloc[-20:]
        # Find two lowest points
        sorted_idx = lows.nsmallest(5).index.tolist()
        if len(sorted_idx) < 2:
            return None
        # Check the two lowest are separated by at least 5 candles
        positions = [lows.index.get_loc(i) for i in sorted_idx[:2]]
        if abs(positions[0] - positions[1]) < 5:
            return None
        low1, low2 = lows[sorted_idx[0]], lows[sorted_idx[1]]
        tolerance = abs(low1) * 0.005  # 0.5% tolerance
        if abs(low1 - low2) < tolerance:
            return PatternMatch("Double Bottom", "reversal", "BULL", 3, 0.70,
                                f"Two lows at ~{low1:.4f}")
        return None

    def _double_top(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Two highs at similar price with a lower low between them."""
        if len(df) < 20:
            return None
        highs = df["high"].astype(float).iloc[-20:]
        sorted_idx = highs.nlargest(5).index.tolist()
        if len(sorted_idx) < 2:
            return None
        positions = [highs.index.get_loc(i) for i in sorted_idx[:2]]
        if abs(positions[0] - positions[1]) < 5:
            return None
        high1, high2 = highs[sorted_idx[0]], highs[sorted_idx[1]]
        tolerance = abs(high1) * 0.005
        if abs(high1 - high2) < tolerance:
            return PatternMatch("Double Top", "reversal", "BEAR", 3, 0.70,
                                f"Two highs at ~{high1:.4f}")
        return None

    def _head_shoulders(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Head & Shoulders: left shoulder, higher head, right shoulder."""
        if len(df) < 30:
            return None
        highs = df["high"].astype(float).iloc[-30:].values
        # Find 3 peaks using simple window
        peaks = []
        for i in range(3, len(highs) - 3):
            if highs[i] == max(highs[i-3:i+4]):
                peaks.append((i, highs[i]))
        if len(peaks) < 3:
            return None
        # Check pattern: middle peak is highest
        for i in range(len(peaks) - 2):
            left, head, right = peaks[i], peaks[i+1], peaks[i+2]
            if (head[1] > left[1] and head[1] > right[1] and
                    abs(left[1] - right[1]) / head[1] < 0.02):  # Shoulders within 2%
                return PatternMatch("Head & Shoulders", "reversal", "BEAR", 3, 0.65,
                                    "Classic H&S top formation")
        return None

    def _inv_head_shoulders(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Inverse Head & Shoulders: bullish reversal."""
        if len(df) < 30:
            return None
        lows = df["low"].astype(float).iloc[-30:].values
        troughs = []
        for i in range(3, len(lows) - 3):
            if lows[i] == min(lows[i-3:i+4]):
                troughs.append((i, lows[i]))
        if len(troughs) < 3:
            return None
        for i in range(len(troughs) - 2):
            left, head, right = troughs[i], troughs[i+1], troughs[i+2]
            if (head[1] < left[1] and head[1] < right[1] and
                    abs(left[1] - right[1]) / abs(head[1]) < 0.02 if head[1] != 0 else False):
                return PatternMatch("Inverse Head & Shoulders", "reversal", "BULL", 3, 0.65,
                                    "Classic iH&S bottom formation")
        return None

    def _pin_bar_bull(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Bullish pin bar: long lower wick, small body at top."""
        curr = df.iloc[-1]
        body = self._body(curr)
        lower = self._lower_wick(curr)
        upper = self._upper_wick(curr)
        if body == 0:
            return None
        if lower > body * 2.5 and upper < body * 0.5:
            return PatternMatch("Bullish Pin Bar", "reversal", "BULL", 2, 0.65,
                                "Rejection of lower prices")
        return None

    def _pin_bar_bear(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Bearish pin bar: long upper wick, small body at bottom."""
        curr = df.iloc[-1]
        body = self._body(curr)
        lower = self._lower_wick(curr)
        upper = self._upper_wick(curr)
        if body == 0:
            return None
        if upper > body * 2.5 and lower < body * 0.5:
            return PatternMatch("Bearish Pin Bar", "reversal", "BEAR", 2, 0.65,
                                "Rejection of higher prices")
        return None

    def _doji_at_level(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Doji candle (tiny body) — signals indecision, potential reversal."""
        curr = df.iloc[-1]
        body = self._body(curr)
        total_range = float(curr["high"]) - float(curr["low"])
        if total_range == 0:
            return None
        if body / total_range < 0.1:  # Body < 10% of total range
            return PatternMatch("Doji", "reversal", "NEUTRAL", 1, 0.50,
                                "Indecision candle — watch for direction")
        return None

    def _morning_star(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """3-candle bullish reversal: big bear, small body, big bull."""
        if len(df) < 3:
            return None
        c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        avg = self._avg_body(df, 10)
        if (self._is_bearish(c1) and self._body(c1) > avg * 1.2 and
                self._body(c2) < avg * 0.5 and
                self._is_bullish(c3) and self._body(c3) > avg * 1.2):
            return PatternMatch("Morning Star", "reversal", "BULL", 3, 0.70,
                                "3-candle bullish reversal")
        return None

    def _evening_star(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """3-candle bearish reversal: big bull, small body, big bear."""
        if len(df) < 3:
            return None
        c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        avg = self._avg_body(df, 10)
        if (self._is_bullish(c1) and self._body(c1) > avg * 1.2 and
                self._body(c2) < avg * 0.5 and
                self._is_bearish(c3) and self._body(c3) > avg * 1.2):
            return PatternMatch("Evening Star", "reversal", "BEAR", 3, 0.70,
                                "3-candle bearish reversal")
        return None

    # ════════════════════════════════════════════════════════════════
    # CONTINUATION PATTERNS
    # ════════════════════════════════════════════════════════════════

    def _bull_flag(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Bull flag: strong up move (pole) then tight consolidation."""
        if len(df) < 10:
            return None
        closes = df["close"].astype(float).iloc[-10:].values
        pole = closes[3] - closes[0]
        if pole <= 0:
            return None
        consol_range = max(closes[4:8]) - min(closes[4:8])
        if consol_range < abs(pole) * 0.5:
            return PatternMatch("Bull Flag", "continuation", "BULL", 2, 0.65,
                                "Pole + consolidation, bullish continuation")
        return None

    def _bear_flag(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Bear flag: strong down move then tight consolidation."""
        if len(df) < 10:
            return None
        closes = df["close"].astype(float).iloc[-10:].values
        pole = closes[3] - closes[0]
        if pole >= 0:
            return None
        consol_range = max(closes[4:8]) - min(closes[4:8])
        if consol_range < abs(pole) * 0.5:
            return PatternMatch("Bear Flag", "continuation", "BEAR", 2, 0.65,
                                "Pole + consolidation, bearish continuation")
        return None

    def _ascending_triangle(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Flat resistance + rising lows → bullish breakout expected."""
        if len(df) < 20:
            return None
        tail = df.iloc[-20:]
        highs = tail["high"].astype(float).values
        lows = tail["low"].astype(float).values
        # Flat resistance: top 5 highs within 0.5% of each other
        top_highs = sorted(highs, reverse=True)[:5]
        high_range = (max(top_highs) - min(top_highs)) / max(top_highs) if max(top_highs) > 0 else 1
        # Rising lows: linear regression slope positive
        low_slope = np.polyfit(range(len(lows)), lows, 1)[0]
        if high_range < 0.005 and low_slope > 0:
            return PatternMatch("Ascending Triangle", "continuation", "BULL", 2, 0.65,
                                "Flat resistance + rising support")
        return None

    def _descending_triangle(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Flat support + falling highs → bearish breakdown expected."""
        if len(df) < 20:
            return None
        tail = df.iloc[-20:]
        highs = tail["high"].astype(float).values
        lows = tail["low"].astype(float).values
        bottom_lows = sorted(lows)[:5]
        low_range = (max(bottom_lows) - min(bottom_lows)) / max(bottom_lows) if max(bottom_lows) > 0 else 1
        high_slope = np.polyfit(range(len(highs)), highs, 1)[0]
        if low_range < 0.005 and high_slope < 0:
            return PatternMatch("Descending Triangle", "continuation", "BEAR", 2, 0.65,
                                "Flat support + falling resistance")
        return None

    def _rising_wedge(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Both highs and lows rising but converging → bearish."""
        if len(df) < 20:
            return None
        tail = df.iloc[-20:]
        highs = tail["high"].astype(float).values
        lows = tail["low"].astype(float).values
        high_slope = np.polyfit(range(len(highs)), highs, 1)[0]
        low_slope = np.polyfit(range(len(lows)), lows, 1)[0]
        if high_slope > 0 and low_slope > 0 and low_slope > high_slope:
            return PatternMatch("Rising Wedge", "reversal", "BEAR", 2, 0.60,
                                "Converging uptrend — bearish reversal likely")
        return None

    def _falling_wedge(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Both highs and lows falling but converging → bullish."""
        if len(df) < 20:
            return None
        tail = df.iloc[-20:]
        highs = tail["high"].astype(float).values
        lows = tail["low"].astype(float).values
        high_slope = np.polyfit(range(len(highs)), highs, 1)[0]
        low_slope = np.polyfit(range(len(lows)), lows, 1)[0]
        if high_slope < 0 and low_slope < 0 and high_slope > low_slope:
            return PatternMatch("Falling Wedge", "reversal", "BULL", 2, 0.60,
                                "Converging downtrend — bullish reversal likely")
        return None

    def _cup_and_handle(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """U-shaped bottom (cup) followed by small pullback (handle)."""
        if len(df) < 30:
            return None
        closes = df["close"].astype(float).iloc[-30:].values
        # Cup: first half dips, mid is lowest, second half recovers
        mid = len(closes) // 2
        left_high = max(closes[:5])
        cup_low = min(closes[5:mid+5])
        right_high = max(closes[mid:mid+10])
        # Handle: small pullback in last 5 candles
        handle_low = min(closes[-5:])
        handle_high = max(closes[-5:])

        if (cup_low < left_high * 0.97 and  # Cup dips at least 3%
                right_high > left_high * 0.98 and  # Recovers to near left high
                handle_low > cup_low and  # Handle above cup bottom
                (handle_high - handle_low) < (right_high - cup_low) * 0.4):  # Handle < 40% of cup depth
            return PatternMatch("Cup & Handle", "continuation", "BULL", 3, 0.70,
                                "U-shaped recovery with small pullback")
        return None

    # ════════════════════════════════════════════════════════════════
    # MOMENTUM PATTERNS
    # ════════════════════════════════════════════════════════════════

    def _three_white_soldiers(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Three consecutive large bullish candles."""
        if len(df) < 3:
            return None
        avg = self._avg_body(df, 10)
        c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        if (self._is_bullish(c1) and self._is_bullish(c2) and self._is_bullish(c3) and
                self._body(c1) > avg and self._body(c2) > avg and self._body(c3) > avg and
                float(c2["close"]) > float(c1["close"]) and float(c3["close"]) > float(c2["close"])):
            return PatternMatch("Three White Soldiers", "momentum", "BULL", 2, 0.65,
                                "Strong bullish momentum — 3 consecutive big green candles")
        return None

    def _three_black_crows(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Three consecutive large bearish candles."""
        if len(df) < 3:
            return None
        avg = self._avg_body(df, 10)
        c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
        if (self._is_bearish(c1) and self._is_bearish(c2) and self._is_bearish(c3) and
                self._body(c1) > avg and self._body(c2) > avg and self._body(c3) > avg and
                float(c2["close"]) < float(c1["close"]) and float(c3["close"]) < float(c2["close"])):
            return PatternMatch("Three Black Crows", "momentum", "BEAR", 2, 0.65,
                                "Strong bearish momentum — 3 consecutive big red candles")
        return None

    def _momentum_burst(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Last 3 candles all moving in same direction with increasing volume."""
        if len(df) < 4:
            return None
        tail = df.iloc[-4:]
        closes = tail["close"].astype(float).values
        vols = tail["volume"].astype(float).values

        moves = [closes[i+1] - closes[i] for i in range(3)]
        vol_increasing = vols[-1] > vols[-2] > vols[-3]

        if all(m > 0 for m in moves) and vol_increasing:
            return PatternMatch("Momentum Burst Up", "momentum", "BULL", 1, 0.55,
                                "3-candle bullish momentum + increasing volume")
        if all(m < 0 for m in moves) and vol_increasing:
            return PatternMatch("Momentum Burst Down", "momentum", "BEAR", 1, 0.55,
                                "3-candle bearish momentum + increasing volume")
        return None

    # ════════════════════════════════════════════════════════════════
    # KEY LEVEL PATTERNS
    # ════════════════════════════════════════════════════════════════

    def _support_bounce(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Price touches recent support level and bounces up."""
        if len(df) < 30:
            return None
        lows = df["low"].astype(float).iloc[-30:]
        # Support = cluster of lows within 0.3%
        recent_low = float(lows.iloc[-1])
        near_lows = lows[abs(lows - recent_low) / recent_low < 0.003]
        if len(near_lows) >= 3 and self._is_bullish(df.iloc[-1]):
            return PatternMatch("Support Bounce", "key_level", "BULL", 2, 0.60,
                                f"Bounced off support at ~{recent_low:.4f} ({len(near_lows)} touches)")
        return None

    def _resistance_rejection(self, df: pd.DataFrame) -> Optional[PatternMatch]:
        """Price touches recent resistance and gets rejected down."""
        if len(df) < 30:
            return None
        highs = df["high"].astype(float).iloc[-30:]
        recent_high = float(highs.iloc[-1])
        near_highs = highs[abs(highs - recent_high) / recent_high < 0.003]
        if len(near_highs) >= 3 and self._is_bearish(df.iloc[-1]):
            return PatternMatch("Resistance Rejection", "key_level", "BEAR", 2, 0.60,
                                f"Rejected at resistance ~{recent_high:.4f} ({len(near_highs)} touches)")
        return None
