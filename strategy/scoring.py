"""
Multi-Signal Scoring System
From the README — minimum score 5 required, probability 65%+

Signal Scoring Table:
  RSI extreme zone (<35 / >65)          → +2
  EMA trend alignment                   → +2
  EMA crossover (just happened)         → +3
  Bollinger Band extreme                → +2
  Chart pattern (engulfing, S/D bounce) → +3
  Chart pattern (flag, triangle, mom)   → +2
  Price momentum confirmation           → +1
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
import numpy as np

from .ema import EMACalculator, EMAValues


@dataclass
class ScoreBreakdown:
    total: int = 0
    rsi_score: int = 0
    ema_alignment_score: int = 0
    ema_crossover_score: int = 0
    bb_score: int = 0
    chart_pattern_score: int = 0
    momentum_score: int = 0
    probability: float = 0.0
    direction: str = "NEUTRAL"  # 'LONG' or 'SHORT' or 'NEUTRAL'
    reasons: list[str] = field(default_factory=list)

    def passes(self, min_score: int = 5, min_prob: float = 0.65) -> bool:
        return self.total >= min_score and self.probability >= min_prob


class ScoringEngine:
    """
    Calculates the multi-signal score for a potential trade setup.
    Each signal contributes points toward the minimum threshold.
    """

    def __init__(
        self,
        rsi_period: int = 14,
        rsi_oversold: float = 35.0,
        rsi_overbought: float = 65.0,
        bb_period: int = 20,
        bb_std: float = 2.0,
        min_score: int = 5,
        min_probability: float = 0.65,
    ):
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.min_score = min_score
        self.min_probability = min_probability
        self._ema = EMACalculator()

    # ──────────────────────── RSI ────────────────────────

    def _calc_rsi(self, df: pd.DataFrame) -> float:
        """Compute RSI using the standard Wilder method."""
        closes = df["close"].astype(float)
        delta = closes.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=self.rsi_period - 1, min_periods=self.rsi_period).mean()
        avg_loss = loss.ewm(com=self.rsi_period - 1, min_periods=self.rsi_period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not rsi.empty else 50.0

    def _rsi_score(self, rsi: float, direction: str) -> tuple[int, str]:
        """RSI extreme zone = +2 if aligned with trade direction."""
        if direction == "LONG" and rsi < self.rsi_oversold:
            return 2, f"RSI oversold ({rsi:.1f} < {self.rsi_oversold})"
        if direction == "SHORT" and rsi > self.rsi_overbought:
            return 2, f"RSI overbought ({rsi:.1f} > {self.rsi_overbought})"
        return 0, f"RSI neutral ({rsi:.1f})"

    # ──────────────────────── Bollinger Bands ────────────────────────

    def _calc_bb(self, df: pd.DataFrame) -> tuple[float, float, float]:
        """Returns (upper, middle, lower) Bollinger Bands."""
        closes = df["close"].astype(float)
        mid = closes.rolling(self.bb_period).mean().iloc[-1]
        std = closes.rolling(self.bb_period).std().iloc[-1]
        return float(mid + self.bb_std * std), float(mid), float(mid - self.bb_std * std)

    def _bb_score(
        self, price: float, upper: float, lower: float, direction: str
    ) -> tuple[int, str]:
        """BB extreme = +2 if price touches band aligned with direction."""
        if direction == "LONG" and price <= lower:
            return 2, f"Price at lower BB ({price:.4f} ≤ {lower:.4f})"
        if direction == "SHORT" and price >= upper:
            return 2, f"Price at upper BB ({price:.4f} ≥ {upper:.4f})"
        return 0, "Price not at BB extreme"

    # ──────────────────────── Chart Patterns ────────────────────────

    def _detect_engulfing(self, df: pd.DataFrame) -> tuple[int, str]:
        """
        Bullish/bearish engulfing = +3 (high-quality reversal pattern)
        """
        if len(df) < 2:
            return 0, "Not enough data for engulfing"

        prev = df.iloc[-2]
        curr = df.iloc[-1]

        prev_body_lo = min(float(prev["open"]), float(prev["close"]))
        prev_body_hi = max(float(prev["open"]), float(prev["close"]))
        curr_body_lo = min(float(curr["open"]), float(curr["close"]))
        curr_body_hi = max(float(curr["open"]), float(curr["close"]))

        # Bullish engulfing: prev candle bearish, curr candle bullish and larger
        if (float(prev["close"]) < float(prev["open"]) and
                float(curr["close"]) > float(curr["open"]) and
                curr_body_lo < prev_body_lo and curr_body_hi > prev_body_hi):
            return 3, "Bullish engulfing pattern"

        # Bearish engulfing: prev candle bullish, curr candle bearish and larger
        if (float(prev["close"]) > float(prev["open"]) and
                float(curr["close"]) < float(curr["open"]) and
                curr_body_lo < prev_body_lo and curr_body_hi > prev_body_hi):
            return 3, "Bearish engulfing pattern"

        return 0, "No engulfing pattern"

    def _detect_flag(self, df: pd.DataFrame, direction: str) -> tuple[int, str]:
        """
        Bull/bear flag = +2 (continuation pattern)
        Simplified: pole then consolidation then breakout.
        """
        if len(df) < 10:
            return 0, "Insufficient data for flag"

        # Look at last 10 candles
        tail = df.iloc[-10:]
        closes = tail["close"].values.astype(float)

        # Check for pole (large move in first 3-4 candles)
        pole = closes[3] - closes[0]
        consolidation_range = max(closes[4:8]) - min(closes[4:8])

        if abs(pole) == 0:
            return 0, "No flag detected"

        # Consolidation should be < 50% of pole
        if consolidation_range < abs(pole) * 0.5:
            if direction == "LONG" and pole > 0:
                return 2, "Bull flag pattern detected"
            if direction == "SHORT" and pole < 0:
                return 2, "Bear flag pattern detected"

        return 0, "No flag pattern"

    def _detect_momentum(self, df: pd.DataFrame, direction: str) -> tuple[int, str]:
        """Price momentum = +1 if last 3 candles moving in trade direction."""
        if len(df) < 4:
            return 0, "Insufficient data for momentum"

        tail = df["close"].iloc[-4:].values.astype(float)
        moves = [tail[i + 1] - tail[i] for i in range(3)]

        if direction == "LONG" and all(m > 0 for m in moves):
            return 1, "3-candle bullish momentum"
        if direction == "SHORT" and all(m < 0 for m in moves):
            return 1, "3-candle bearish momentum"

        return 0, "No clear momentum"

    # ──────────────────────── Main Scorer ────────────────────────

    def score(
        self,
        df: pd.DataFrame,
        direction: str,
        ema_values: Optional[EMAValues] = None,
    ) -> ScoreBreakdown:
        """
        Calculate the full score for a trade setup.

        Args:
            df: OHLCV DataFrame (at least 200 candles recommended)
            direction: 'LONG' or 'SHORT'
            ema_values: Pre-calculated EMA values (optional)

        Returns:
            ScoreBreakdown with total score, breakdown, and probability estimate
        """
        result = ScoreBreakdown(direction=direction)
        price = float(df["close"].iloc[-1])

        # 1. RSI score (+2)
        rsi = self._calc_rsi(df)
        pts, reason = self._rsi_score(rsi, direction)
        result.rsi_score = pts
        result.total += pts
        result.reasons.append(reason)

        # 2. EMA alignment score (+2)
        if ema_values is None:
            ema_values = self._ema.latest(df)
        pts = ema_values.ema_alignment_score()
        result.ema_alignment_score = pts
        result.total += pts
        if pts > 0:
            result.reasons.append(f"EMA fully aligned ({ema_values.trend_direction()})")
        else:
            result.reasons.append("EMAs not fully aligned")

        # 3. EMA crossover (+3)
        crossover = self._ema.detect_crossover(df)
        if crossover == "BULLISH" and direction == "LONG":
            result.ema_crossover_score = 3
            result.total += 3
            result.reasons.append("Bullish 13/48 EMA crossover")
        elif crossover == "BEARISH" and direction == "SHORT":
            result.ema_crossover_score = 3
            result.total += 3
            result.reasons.append("Bearish 13/48 EMA crossover")
        else:
            result.reasons.append(f"No EMA crossover (crossover={crossover})")

        # 4. Bollinger Band extreme (+2)
        try:
            upper, mid, lower = self._calc_bb(df)
            pts, reason = self._bb_score(price, upper, lower, direction)
            result.bb_score = pts
            result.total += pts
            result.reasons.append(reason)
        except Exception:
            result.reasons.append("BB calculation failed")

        # 5. Chart pattern — engulfing (+3) or flag (+2)
        eng_pts, eng_reason = self._detect_engulfing(df)
        flag_pts, flag_reason = self._detect_flag(df, direction)
        # Take the higher of the two
        pattern_pts = max(eng_pts, flag_pts)
        pattern_reason = eng_reason if eng_pts >= flag_pts else flag_reason
        result.chart_pattern_score = pattern_pts
        result.total += pattern_pts
        result.reasons.append(pattern_reason)

        # 6. Momentum (+1)
        pts, reason = self._detect_momentum(df, direction)
        result.momentum_score = pts
        result.total += pts
        result.reasons.append(reason)

        # Calculate probability estimate
        # Simple linear map: score 5 → 65%, score 14 (max) → 90%
        max_possible = 2 + 2 + 3 + 2 + 3 + 1  # = 13
        clamped = max(0, min(result.total, max_possible))
        result.probability = 0.50 + (clamped / max_possible) * 0.45

        return result
