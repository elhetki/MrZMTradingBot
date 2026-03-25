"""
EMA Calculator — 4-EMA System
Periods: 8, 13, 48, 200
Role:
  200 → Long-term trend direction
   48 → Last line of defense / pullback level
   13 → Pullback entries (above 200 = long, below 200 = short)
    8 → Trend indicator — follow the 8, follow the money
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class EMAValues:
    ema8: float
    ema13: float
    ema48: float
    ema200: float

    def trend_direction(self) -> str:
        """Returns 'BULL', 'BEAR', or 'NEUTRAL' based on 200 EMA vs price context."""
        if self.ema8 > self.ema13 > self.ema48 > self.ema200:
            return "BULL"
        if self.ema8 < self.ema13 < self.ema48 < self.ema200:
            return "BEAR"
        return "NEUTRAL"

    def is_bullish(self, price: float) -> bool:
        """Price above 200 EMA = bullish bias."""
        return price > self.ema200

    def is_bearish(self, price: float) -> bool:
        """Price below 200 EMA = bearish bias."""
        return price < self.ema200

    def ema_alignment_score(self) -> int:
        """
        Returns +2 score if EMAs are fully aligned (8 > 13 > 48 > 200 or reverse).
        From the scoring table: EMA trend alignment = +2
        """
        if self.ema8 > self.ema13 > self.ema48 > self.ema200:
            return 2
        if self.ema8 < self.ema13 < self.ema48 < self.ema200:
            return 2
        return 0


class EMACalculator:
    """
    Calculates 8, 13, 48, 200 EMAs from OHLCV candle data.
    Uses pandas EWM for efficient computation.
    """

    PERIODS = [8, 13, 48, 200]

    def __init__(self, periods: list[int] | None = None):
        self.periods = periods or self.PERIODS

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Compute EMAs and add as columns to the dataframe.

        Args:
            df: DataFrame with at least a 'close' column.

        Returns:
            DataFrame with added ema8, ema13, ema48, ema200 columns.
        """
        if "close" not in df.columns:
            raise ValueError("DataFrame must have a 'close' column")

        closes = df["close"].astype(float)
        for p in self.periods:
            col = f"ema{p}"
            df[col] = closes.ewm(span=p, adjust=False).mean()

        return df

    def latest(self, df: pd.DataFrame) -> EMAValues:
        """
        Returns the most recent EMA values.
        Calculates EMAs if not already present.
        """
        required = [f"ema{p}" for p in self.PERIODS]
        if not all(c in df.columns for c in required):
            df = self.calculate(df)

        row = df.iloc[-1]
        return EMAValues(
            ema8=float(row["ema8"]),
            ema13=float(row["ema13"]),
            ema48=float(row["ema48"]),
            ema200=float(row["ema200"]),
        )

    def detect_crossover(self, df: pd.DataFrame, fast: int = 13, slow: int = 48, lookback: int = 60) -> Optional[str]:
        """
        Detect if fast EMA is aligned above/below slow EMA (crossover happened recently).
        
        v2.5: Instead of requiring the exact crossover candle, we check:
        1. Current alignment (fast above slow = bullish, below = bearish)
        2. The crossover happened within the last `lookback` candles (confirms momentum shift)
        
        Returns 'BULLISH', 'BEARISH', or None.
        """
        fast_col = f"ema{fast}"
        slow_col = f"ema{slow}"

        required = [fast_col, slow_col]
        if not all(c in df.columns for c in required):
            df = self.calculate(df)

        if len(df) < lookback:
            return None

        # Current alignment
        current_fast = float(df[fast_col].iloc[-1])
        current_slow = float(df[slow_col].iloc[-1])
        
        if current_fast > current_slow:
            # Bullish alignment — verify crossover happened within lookback window
            tail = df[[fast_col, slow_col]].iloc[-lookback:]
            diffs = tail[fast_col] - tail[slow_col]
            # Was there a point where fast was below slow? (= cross happened)
            if (diffs < 0).any():
                return "BULLISH"
            # Even if no cross in window, sustained alignment is bullish
            if (diffs > 0).all():
                return "BULLISH"
        elif current_fast < current_slow:
            # Bearish alignment
            tail = df[[fast_col, slow_col]].iloc[-lookback:]
            diffs = tail[fast_col] - tail[slow_col]
            if (diffs > 0).any():
                return "BEARISH"
            if (diffs < 0).all():
                return "BEARISH"

        return None

    def bounced_off_48(self, df: pd.DataFrame, tolerance_pct: float = 0.005) -> Optional[str]:
        """
        Detect if price recently bounced off the 48 EMA.
        This is the 'last line of defense' bounce confirmation.
        Returns 'BULLISH_BOUNCE', 'BEARISH_BOUNCE', or None.
        """
        if "ema48" not in df.columns:
            df = self.calculate(df)

        if len(df) < 5:
            return None

        tail = df.iloc[-5:]
        closes = tail["close"].values
        lows = tail["low"].values
        highs = tail["high"].values
        ema48 = tail["ema48"].values

        # Bullish bounce: low touched 48 EMA, close recovered above
        for i in range(len(tail) - 2, -1, -1):
            low_near_ema = abs(lows[i] - ema48[i]) / ema48[i] < tolerance_pct
            close_above = closes[-1] > ema48[-1]
            if low_near_ema and close_above:
                return "BULLISH_BOUNCE"

        # Bearish bounce: high touched 48 EMA, close recovered below
        for i in range(len(tail) - 2, -1, -1):
            high_near_ema = abs(highs[i] - ema48[i]) / ema48[i] < tolerance_pct
            close_below = closes[-1] < ema48[-1]
            if high_near_ema and close_below:
                return "BEARISH_BOUNCE"

        return None
