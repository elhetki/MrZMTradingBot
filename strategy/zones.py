"""
Supply & Demand Zone Identifier
Uses the Conservative method from the Trading Gym Manual:

Supply Zone (conservative):
  - Distal Line (first line): Top of wick (highest wick)
  - Proximal Line (second line): Lowest body of base

Demand Zone (conservative):
  - Distal Line: Lowest wick
  - Proximal Line: Highest body of base

Zones are marked at BOS/CHOCH points using the base candles that formed before the break.
A "base" is typically 1-3 relatively small-bodied candles before the explosive move.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
import numpy as np

from .structure import StructureEvent


@dataclass
class Zone:
    kind: str           # 'SUPPLY' or 'DEMAND'
    proximal: float     # Closer price level to current price
    distal: float       # Further price level (stop zone)
    origin_index: int   # Candle index that created this zone
    origin_event: str   # 'BOS_BULL', 'BOS_BEAR', 'CHOCH_BULL', 'CHOCH_BEAR'
    active: bool = True
    touches: int = 0
    created_ts: Optional[pd.Timestamp] = None

    def contains(self, price: float) -> bool:
        """Is the price inside this zone?"""
        lo = min(self.proximal, self.distal)
        hi = max(self.proximal, self.distal)
        return lo <= price <= hi

    def near(self, price: float, tolerance_pct: float = 0.005) -> bool:
        """Is the price within tolerance of the proximal line?"""
        return abs(price - self.proximal) / self.proximal < tolerance_pct

    def size_pct(self) -> float:
        """Zone size as percentage of proximal price."""
        return abs(self.distal - self.proximal) / self.proximal * 100

    def invalidated_by(self, price: float) -> bool:
        """Zone is invalidated if price closes beyond the distal line."""
        if self.kind == "SUPPLY":
            return price > self.distal
        else:
            return price < self.distal


class SupplyDemandZones:
    """
    Identifies and manages supply and demand zones.
    Zones are created at BOS/CHOCH points using the base candles method.
    """

    def __init__(self, base_lookback: int = 5, max_zone_size_pct: float = 3.0):
        """
        Args:
            base_lookback: Number of candles to look back for the base formation.
            max_zone_size_pct: Maximum zone size as % of price (filters bad zones).
        """
        self.base_lookback = base_lookback
        self.max_zone_size_pct = max_zone_size_pct

    def _find_base_candles(
        self,
        df: pd.DataFrame,
        event_index: int,
        is_bullish_break: bool,
        n: int = 5,
    ) -> Optional[pd.DataFrame]:
        """
        Find the base candles just before the breakout candle.
        Base = small-bodied consolidation candles that led to the explosive move.
        """
        start = max(0, event_index - n)
        end = event_index
        if end <= start:
            return None

        base = df.iloc[start:end]
        if len(base) == 0:
            return None

        return base

    def _create_demand_zone(
        self,
        df: pd.DataFrame,
        event: StructureEvent,
    ) -> Optional[Zone]:
        """
        Conservative demand zone:
        Distal = lowest wick of the base
        Proximal = highest body of the base
        """
        base = self._find_base_candles(df, event.candle_index, True)
        if base is None or len(base) == 0:
            return None

        distal = float(base["low"].min())   # Lowest wick
        # Highest body = max of open/close in base candles
        proximal = float(np.maximum(base["open"], base["close"]).max())

        if proximal <= distal:
            return None

        z = Zone(
            kind="DEMAND",
            proximal=proximal,
            distal=distal,
            origin_index=event.candle_index,
            origin_event=event.event_type,
            created_ts=event.timestamp,
        )

        if z.size_pct() > self.max_zone_size_pct:
            return None

        return z

    def _create_supply_zone(
        self,
        df: pd.DataFrame,
        event: StructureEvent,
    ) -> Optional[Zone]:
        """
        Conservative supply zone:
        Distal = top of wick (highest wick)
        Proximal = lowest body of base
        """
        base = self._find_base_candles(df, event.candle_index, False)
        if base is None or len(base) == 0:
            return None

        distal = float(base["high"].max())   # Top of wick
        # Lowest body = min of open/close
        proximal = float(np.minimum(base["open"], base["close"]).min())

        if distal <= proximal:
            return None

        z = Zone(
            kind="SUPPLY",
            proximal=proximal,
            distal=distal,
            origin_index=event.candle_index,
            origin_event=event.event_type,
            created_ts=event.timestamp,
        )

        if z.size_pct() > self.max_zone_size_pct:
            return None

        return z

    def build_zones(
        self,
        df: pd.DataFrame,
        events: list[StructureEvent],
    ) -> list[Zone]:
        """
        Build supply/demand zones from BOS/CHOCH events.

        BOS_BULL / CHOCH_BULL → Demand zone (buy the retracement)
        BOS_BEAR / CHOCH_BEAR → Supply zone (sell the bounce)
        """
        zones: list[Zone] = []

        for event in events:
            if event.event_type in ("BOS_BULL", "CHOCH_BULL"):
                z = self._create_demand_zone(df, event)
                if z:
                    zones.append(z)
            elif event.event_type in ("BOS_BEAR", "CHOCH_BEAR"):
                z = self._create_supply_zone(df, event)
                if z:
                    zones.append(z)

        return zones

    def update_zones(
        self,
        zones: list[Zone],
        current_price: float,
        candle_df: pd.DataFrame | None = None,
    ) -> list[Zone]:
        """
        Update zone states:
        - Mark as touched if price enters zone
        - Mark as inactive (invalidated) if price closes beyond distal
        """
        for z in zones:
            if not z.active:
                continue

            if z.contains(current_price):
                z.touches += 1

            if z.invalidated_by(current_price):
                z.active = False

        return zones

    def nearest_zone(
        self,
        zones: list[Zone],
        price: float,
        kind: str,
        tolerance_pct: float = 0.02,
    ) -> Optional[Zone]:
        """
        Find the nearest active zone of the given kind (SUPPLY or DEMAND)
        within tolerance of current price.
        """
        active = [z for z in zones if z.active and z.kind == kind]
        if not active:
            return None

        closest = min(active, key=lambda z: abs(z.proximal - price))
        if abs(closest.proximal - price) / price < tolerance_pct:
            return closest
        return None

    def price_at_zone(
        self,
        zones: list[Zone],
        price: float,
        kind: str | None = None,
    ) -> bool:
        """
        Returns True if the current price is within any active zone
        (optionally filtered by kind).
        """
        for z in zones:
            if not z.active:
                continue
            if kind and z.kind != kind:
                continue
            if z.contains(price) or z.near(price):
                return True
        return False
