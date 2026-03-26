"""
Volume Confirmation Module
From the Trading Gym Manual:

  Price ↑ + Volume ↑ → Strong uptrend ✅ (enter)
  Price ↓ + Volume ↑ → Strong downtrend ✅ (enter)
  Price ↑ + Volume ↓ → Weak / reversal sign ❌ (skip)
  Price ↓ + Volume ↓ → Weak / reversal sign ❌ (skip)

Volume is confirmed by comparing current candle's volume to the moving average.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np


@dataclass
class VolumeSignal:
    confirmed: bool        # True if volume confirms the price move
    strength: str          # 'STRONG', 'WEAK', 'NEUTRAL'
    price_direction: str   # 'UP', 'DOWN'
    volume_direction: str  # 'UP', 'DOWN', 'NEUTRAL'
    volume_ratio: float    # Current volume / MA volume
    reason: str


class VolumeConfirmation:
    """
    Confirms volume alignment with price direction.
    Uses a rolling average as baseline for 'up' vs 'down' volume.
    """

    def __init__(self, ma_period: int = 20, above_avg_threshold: float = 0.7):
        """
        Args:
            ma_period: Period for volume moving average.
            above_avg_threshold: Volume must be > this multiple of MA to be 'strong'.
                                 0.7 = 70% of average (accounts for off-peak hours in crypto).
        """
        self.ma_period = ma_period
        self.above_avg_threshold = above_avg_threshold

    def confirm(self, df: pd.DataFrame, lookback: int = 3) -> VolumeSignal:
        """
        Analyze the last N candles for volume/price alignment.

        Args:
            df: OHLCV DataFrame (requires 'close', 'open', 'volume' columns)
            lookback: How many candles to consider for directional analysis

        Returns:
            VolumeSignal with confirmation result and details
        """
        if len(df) < max(self.ma_period, lookback) + 1:
            return VolumeSignal(
                confirmed=False,
                strength="NEUTRAL",
                price_direction="NEUTRAL",
                volume_direction="NEUTRAL",
                volume_ratio=1.0,
                reason="Insufficient data",
            )

        # Volume moving average
        vol_ma = df["volume"].rolling(self.ma_period).mean()
        current_vol = float(df["volume"].iloc[-1])
        current_vol_ma = float(vol_ma.iloc[-1])

        if current_vol_ma == 0:
            return VolumeSignal(
                confirmed=False,
                strength="NEUTRAL",
                price_direction="NEUTRAL",
                volume_direction="NEUTRAL",
                volume_ratio=1.0,
                reason="Volume MA is zero",
            )

        vol_ratio = current_vol / current_vol_ma

        # Price direction: compare recent close to N candles ago
        recent = df.iloc[-lookback:]
        price_start = float(recent["close"].iloc[0])
        price_end = float(recent["close"].iloc[-1])
        price_change = price_end - price_start

        if price_change > 0:
            price_dir = "UP"
        elif price_change < 0:
            price_dir = "DOWN"
        else:
            price_dir = "NEUTRAL"

        # Volume direction: is current volume above or below average?
        if vol_ratio >= self.above_avg_threshold:
            vol_dir = "UP"
        else:
            vol_dir = "DOWN"

        # Alignment check
        # Strong: price and volume both up, or both down (by convention)
        if price_dir == "UP" and vol_dir == "UP":
            confirmed = True
            strength = "STRONG"
            reason = f"Price ↑ Volume ↑ (ratio={vol_ratio:.2f}x) — strong uptrend"
        elif price_dir == "DOWN" and vol_dir == "UP":
            confirmed = True
            strength = "STRONG"
            reason = f"Price ↓ Volume ↑ (ratio={vol_ratio:.2f}x) — strong downtrend"
        elif price_dir == "UP" and vol_dir == "DOWN":
            confirmed = False
            strength = "WEAK"
            reason = f"Price ↑ Volume ↓ (ratio={vol_ratio:.2f}x) — weak / potential reversal"
        elif price_dir == "DOWN" and vol_dir == "DOWN":
            confirmed = False
            strength = "WEAK"
            reason = f"Price ↓ Volume ↓ (ratio={vol_ratio:.2f}x) — weak / potential reversal"
        else:
            confirmed = False
            strength = "NEUTRAL"
            reason = "Neutral price movement"

        return VolumeSignal(
            confirmed=confirmed,
            strength=strength,
            price_direction=price_dir,
            volume_direction=vol_dir,
            volume_ratio=vol_ratio,
            reason=reason,
        )

    def is_above_average(self, df: pd.DataFrame, multiplier: float = 1.2) -> bool:
        """Quick check if latest candle has above-average volume."""
        if len(df) < self.ma_period:
            return False
        vol_ma = df["volume"].rolling(self.ma_period).mean().iloc[-1]
        current = df["volume"].iloc[-1]
        return current > vol_ma * multiplier
