"""
BOS/CHOCH Detector — Market Structure Analysis
BOS  (Break of Structure) → Trend continuation
CHOCH (Change of Character) → Trend reversal — catch the flip early

From the manual:
  BOS in bearish trend: break of a lower low → bearish continuation
  BOS in bullish trend: break of a higher high → bullish continuation
  CHOCH in bullish trend: price breaks a higher low → bearish reversal signal
  CHOCH in bearish trend: price breaks a lower high → bullish reversal signal
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import pandas as pd
import numpy as np


@dataclass
class SwingPoint:
    index: int
    price: float
    kind: str  # 'HIGH' or 'LOW'
    timestamp: Optional[pd.Timestamp] = None


@dataclass
class StructureEvent:
    event_type: str       # 'BOS_BULL', 'BOS_BEAR', 'CHOCH_BULL', 'CHOCH_BEAR'
    price: float          # price at which the break occurred
    swing_level: float    # the swing high/low that was broken
    candle_index: int
    timestamp: Optional[pd.Timestamp] = None

    def is_bullish(self) -> bool:
        return "BULL" in self.event_type

    def is_bearish(self) -> bool:
        return "BEAR" in self.event_type

    def is_bos(self) -> bool:
        return self.event_type.startswith("BOS")

    def is_choch(self) -> bool:
        return self.event_type.startswith("CHOCH")


class BOSCHOCHDetector:
    """
    Detects Break of Structure (BOS) and Change of Character (CHOCH) events
    by tracking swing highs and swing lows.

    Swing detection uses a look-left/look-right approach:
      - Swing High: local high with N lower highs on each side
      - Swing Low:  local low with N higher lows on each side
    """

    def __init__(self, swing_lookback: int = 5):
        """
        Args:
            swing_lookback: Number of candles on each side to confirm a swing point.
        """
        self.swing_lookback = swing_lookback

    def find_swings(self, df: pd.DataFrame) -> list[SwingPoint]:
        """
        Identify all swing highs and swing lows in the dataset.
        """
        n = self.swing_lookback
        swings: list[SwingPoint] = []

        highs = df["high"].values
        lows = df["low"].values
        timestamps = df.index if hasattr(df.index, "__iter__") else None

        for i in range(n, len(df) - n):
            # Swing High
            if all(highs[i] > highs[i - j] for j in range(1, n + 1)) and \
               all(highs[i] > highs[i + j] for j in range(1, n + 1)):
                ts = df.index[i] if timestamps is not None else None
                swings.append(SwingPoint(index=i, price=highs[i], kind="HIGH", timestamp=ts))

            # Swing Low
            if all(lows[i] < lows[i - j] for j in range(1, n + 1)) and \
               all(lows[i] < lows[i + j] for j in range(1, n + 1)):
                ts = df.index[i] if timestamps is not None else None
                swings.append(SwingPoint(index=i, price=lows[i], kind="LOW", timestamp=ts))

        return sorted(swings, key=lambda s: s.index)

    def detect(self, df: pd.DataFrame) -> list[StructureEvent]:
        """
        Detect all BOS and CHOCH events in the candle data.

        Returns a list of StructureEvent objects in chronological order.
        """
        swings = self.find_swings(df)
        if len(swings) < 4:
            return []

        events: list[StructureEvent] = []
        closes = df["close"].values

        # Track the trend: start with NEUTRAL, determine from first swings
        trend = "NEUTRAL"

        # Separate swing highs and lows
        swing_highs = [s for s in swings if s.kind == "HIGH"]
        swing_lows = [s for s in swings if s.kind == "LOW"]

        if not swing_highs or not swing_lows:
            return []

        # Determine initial trend from first two swing highs/lows
        if len(swing_highs) >= 2 and len(swing_lows) >= 2:
            hh_trend = swing_highs[1].price > swing_highs[0].price  # Higher Highs
            hl_trend = swing_lows[1].price > swing_lows[0].price    # Higher Lows
            lh_trend = swing_highs[1].price < swing_highs[0].price  # Lower Highs
            ll_trend = swing_lows[1].price < swing_lows[0].price    # Lower Lows

            if hh_trend and hl_trend:
                trend = "BULL"
            elif lh_trend and ll_trend:
                trend = "BEAR"

        # Scan candle by candle for breaks
        last_sh_index = 0  # index into swing_highs
        last_sl_index = 0  # index into swing_lows

        for i in range(1, len(df)):
            close = closes[i]
            ts = df.index[i] if hasattr(df.index, "__getitem__") else None

            # Get the most recent relevant swing points up to candle i
            relevant_highs = [s for s in swing_highs if s.index < i]
            relevant_lows = [s for s in swing_lows if s.index < i]

            if not relevant_highs or not relevant_lows:
                continue

            last_high = relevant_highs[-1]
            last_low = relevant_lows[-1]

            if trend == "BULL":
                # BOS_BULL: breaks above a previous swing high → trend continuation
                if close > last_high.price:
                    # Confirm it's a new HH
                    prev_highs = relevant_highs[:-1]
                    if prev_highs and last_high.price > prev_highs[-1].price:
                        events.append(StructureEvent(
                            event_type="BOS_BULL",
                            price=close,
                            swing_level=last_high.price,
                            candle_index=i,
                            timestamp=ts,
                        ))
                # CHOCH_BEAR: breaks below a previous swing low → reversal
                if len(relevant_lows) >= 2:
                    prev_low = relevant_lows[-2]
                    if close < prev_low.price:
                        events.append(StructureEvent(
                            event_type="CHOCH_BEAR",
                            price=close,
                            swing_level=prev_low.price,
                            candle_index=i,
                            timestamp=ts,
                        ))
                        trend = "BEAR"

            elif trend == "BEAR":
                # BOS_BEAR: breaks below a previous swing low → trend continuation
                if close < last_low.price:
                    prev_lows = relevant_lows[:-1]
                    if prev_lows and last_low.price < prev_lows[-1].price:
                        events.append(StructureEvent(
                            event_type="BOS_BEAR",
                            price=close,
                            swing_level=last_low.price,
                            candle_index=i,
                            timestamp=ts,
                        ))
                # CHOCH_BULL: breaks above a previous swing high → reversal
                if len(relevant_highs) >= 2:
                    prev_high = relevant_highs[-2]
                    if close > prev_high.price:
                        events.append(StructureEvent(
                            event_type="CHOCH_BULL",
                            price=close,
                            swing_level=prev_high.price,
                            candle_index=i,
                            timestamp=ts,
                        ))
                        trend = "BULL"

            else:
                # NEUTRAL: determine trend from first break
                if len(relevant_highs) >= 2 and close > relevant_highs[-1].price:
                    trend = "BULL"
                elif len(relevant_lows) >= 2 and close < relevant_lows[-1].price:
                    trend = "BEAR"

        # Deduplicate events that are very close together (within 3 candles)
        deduped = []
        for ev in events:
            if not deduped or ev.candle_index - deduped[-1].candle_index > 3:
                deduped.append(ev)

        return deduped

    def latest_event(self, df: pd.DataFrame) -> Optional[StructureEvent]:
        """Returns the most recent BOS/CHOCH event."""
        events = self.detect(df)
        return events[-1] if events else None

    def recent_events(self, df: pd.DataFrame, n: int = 5) -> list[StructureEvent]:
        """Returns the N most recent BOS/CHOCH events."""
        events = self.detect(df)
        return events[-n:] if events else []
