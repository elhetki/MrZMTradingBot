"""
Chop Filter — Sideways Market Detection
"The bot now knows when NOT to trade."

Three independent checks:
  1. Range Check: Is the price range over N candles small vs avg candle size?
  2. EMA Squeeze: Are fast/slow EMAs converging (flat, no trend)?
  3. Bollinger Band Width: Are bands narrow (low volatility)?

If 2/3 checks say "choppy" → NO TRADE.
All configurable via config.json.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ChopResult:
    """Result of chop detection."""
    is_choppy: bool
    checks_triggered: int          # How many of 3 checks flagged choppy
    range_choppy: bool = False
    squeeze_choppy: bool = False
    bb_choppy: bool = False
    range_ratio: float = 0.0       # price_range / avg_candle_size
    ema_spread_pct: float = 0.0    # |ema13 - ema48| / price as %
    bb_width_pct: float = 0.0      # BB width / mid as %
    reason: str = ""

    def summary(self) -> str:
        flags = []
        if self.range_choppy:
            flags.append(f"RANGE({self.range_ratio:.1f}x)")
        if self.squeeze_choppy:
            flags.append(f"SQUEEZE({self.ema_spread_pct:.3f}%)")
        if self.bb_choppy:
            flags.append(f"BB_NARROW({self.bb_width_pct:.2f}%)")
        status = "🔴 CHOPPY" if self.is_choppy else "🟢 TRENDING"
        return f"{status} [{self.checks_triggered}/3] {' | '.join(flags) if flags else 'all clear'}"


class ChopFilter:
    """
    Detects sideways/ranging markets to prevent getting chopped up.
    Uses three independent methods — if 2/3 trigger, market is choppy.
    """

    def __init__(self, config: dict):
        chop_cfg = config.get("chop_filter", {})
        self.enabled = chop_cfg.get("enabled", True)
        self.lookback = chop_cfg.get("lookback", 20)          # Candles to analyze
        self.min_triggers = chop_cfg.get("min_triggers", 2)    # 2/3 must trigger

        # Check 1: Range vs avg candle size
        # If total range < range_threshold × avg candle size → choppy
        self.range_threshold = chop_cfg.get("range_threshold", 3.0)

        # Check 2: EMA squeeze
        # If |EMA13 - EMA48| / price < squeeze_threshold% → choppy
        self.squeeze_threshold = chop_cfg.get("squeeze_threshold", 0.15)  # 0.15%

        # Check 3: Bollinger Band width
        # If BB_width / BB_mid < bb_width_threshold% → choppy
        self.bb_width_threshold = chop_cfg.get("bb_width_threshold", 1.5)  # 1.5%
        self.bb_period = chop_cfg.get("bb_period", 20)
        self.bb_std = chop_cfg.get("bb_std", 2.0)

    def check(self, df: pd.DataFrame) -> ChopResult:
        """
        Run all 3 chop detection checks on the given candle data.

        Args:
            df: OHLCV DataFrame with at least `lookback` candles.
                Must have columns: open, high, low, close, and optionally ema13, ema48.

        Returns:
            ChopResult with is_choppy=True if market is ranging.
        """
        if not self.enabled:
            return ChopResult(is_choppy=False, checks_triggered=0, reason="Chop filter disabled")

        if len(df) < max(self.lookback, self.bb_period):
            return ChopResult(is_choppy=False, checks_triggered=0, reason="Insufficient data")

        tail = df.iloc[-self.lookback:]
        result = ChopResult(is_choppy=False, checks_triggered=0)

        # ── Check 1: Price Range vs Average Candle Size ──────────────
        highs = tail["high"].astype(float).values
        lows = tail["low"].astype(float).values
        closes = tail["close"].astype(float).values

        price_range = highs.max() - lows.min()
        avg_candle_size = np.mean(highs - lows)

        if avg_candle_size > 0:
            result.range_ratio = price_range / avg_candle_size
            if result.range_ratio < self.range_threshold:
                result.range_choppy = True
                result.checks_triggered += 1

        # ── Check 2: EMA Squeeze Detection ───────────────────────────
        # Calculate EMAs if not present
        close_series = df["close"].astype(float)
        if "ema13" not in df.columns:
            ema13 = close_series.ewm(span=13, adjust=False).mean()
        else:
            ema13 = df["ema13"].astype(float)

        if "ema48" not in df.columns:
            ema48 = close_series.ewm(span=48, adjust=False).mean()
        else:
            ema48 = df["ema48"].astype(float)

        current_price = float(closes[-1])
        ema13_val = float(ema13.iloc[-1])
        ema48_val = float(ema48.iloc[-1])

        if current_price > 0:
            result.ema_spread_pct = abs(ema13_val - ema48_val) / current_price * 100
            if result.ema_spread_pct < self.squeeze_threshold:
                result.squeeze_choppy = True
                result.checks_triggered += 1

        # ── Check 3: Bollinger Band Width ────────────────────────────
        bb_data = df["close"].astype(float).iloc[-self.bb_period:]
        if len(bb_data) >= self.bb_period:
            bb_mid = float(bb_data.rolling(self.bb_period).mean().iloc[-1])
            bb_std_val = float(bb_data.rolling(self.bb_period).std().iloc[-1])
            bb_upper = bb_mid + self.bb_std * bb_std_val
            bb_lower = bb_mid - self.bb_std * bb_std_val
            bb_width = bb_upper - bb_lower

            if bb_mid > 0:
                result.bb_width_pct = bb_width / bb_mid * 100
                if result.bb_width_pct < self.bb_width_threshold:
                    result.bb_choppy = True
                    result.checks_triggered += 1

        # ── Verdict ──────────────────────────────────────────────────
        result.is_choppy = result.checks_triggered >= self.min_triggers

        if result.is_choppy:
            result.reason = f"Market is choppy ({result.checks_triggered}/3 checks triggered)"
        else:
            result.reason = f"Market trending ({result.checks_triggered}/3 chop signals — below threshold)"

        return result
