"""
Entry Logic v2 — Confluence Scoring (not hard gates)
=====================================================
v1 required ALL 7 conditions on the same candle → almost never triggered.
v2 uses 4 hard gates + soft scoring. Much closer to how Zoran actually trades:
"A+ setups with enough confluence pass. Min score 5."

HARD GATES (must pass or signal is killed):
  1. Price above/below 200 EMA (trend direction)
  2. 13/48 EMA cross alignment (within lookback window)
  3. 8 EMA aligned with direction
  4. Minimum score threshold

SOFT SCORING (add points, never block):
  +2  EMA alignment (8>13>48>200 or reverse)
  +3  EMA crossover recently happened
  +3  48 EMA bounce detected
  +3  Strong chart pattern (engulfing, H&S, double top/bottom)
  +2  Standard chart pattern (flag, triangle, wedge, pin bar)
  +1  Weak pattern (momentum, doji)
  +2  Volume confirms price direction
  +2  S/D zone proximity
  +1  Price momentum (3 candles same direction)
  +2  WOBI order book confirms (injected from bot.py)
  ±1  Sentiment (injected from bot.py)

Max possible: ~20+. Min score 5 to trade.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

from .ema import EMACalculator, EMAValues
from .structure import BOSCHOCHDetector, StructureEvent
from .zones import SupplyDemandZones, Zone
from .volume import VolumeConfirmation, VolumeSignal
from .patterns import PatternDetector


@dataclass
class EntrySignal:
    ticker: str
    direction: str           # 'LONG' or 'SHORT'
    entry_price: float
    confidence: float        # 0.0 – 1.0

    score: int = 0
    score_breakdown: dict = field(default_factory=dict)
    volume_signal: VolumeSignal = None
    structure_event: Optional[StructureEvent] = None
    nearest_zone: Optional[Zone] = None
    ema_values: EMAValues = None
    mtf_blocked: bool = False
    wobi_score: int = 0
    sentiment_score: int = 0

    entry_pattern: str = ""      # Best pattern at entry (for learning engine)
    entry_rsi: float = 50.0      # RSI at entry (for learning engine)

    checks_passed: dict = field(default_factory=dict)
    checks_failed: list[str] = field(default_factory=list)
    skip_reason: Optional[str] = None

    valid: bool = False

    def summary(self) -> str:
        lines = [
            f"{'✅' if self.valid else '❌'} {self.ticker} {self.direction} | Score: {self.score} | Prob: {self.confidence:.0%}",
        ]
        if self.score_breakdown:
            for k, v in self.score_breakdown.items():
                if v != 0:
                    lines.append(f"  {k}: {v:+d}")
        if self.skip_reason:
            lines.append(f"  Skip: {self.skip_reason}")
        return "\n".join(lines)


class EntryLogic:
    """
    v2: Confluence scoring with hard gates + soft scoring.
    """

    def __init__(self, config: dict):
        self.config = config
        self.min_score = config.get("scoring", {}).get("min_score", 5)
        self.min_probability = config.get("scoring", {}).get("min_probability", 0.70)

        self._ema = EMACalculator()
        self._structure = BOSCHOCHDetector(swing_lookback=5)
        self._zones = SupplyDemandZones()
        self._volume = VolumeConfirmation()
        self._patterns = PatternDetector()

        # RSI/BB params for scoring
        self._rsi_period = config.get("rsi_period", 14)
        self._rsi_oversold = config.get("rsi_oversold", 35)
        self._rsi_overbought = config.get("rsi_overbought", 65)
        self._bb_period = config.get("bb_period", 20)
        self._bb_std = config.get("bb_std", 2.0)

    def evaluate(
        self,
        df: pd.DataFrame,
        ticker: str,
        active_zones: Optional[list[Zone]] = None,
        wobi_score: int = 0,
        wobi_reason: str = "",
        sentiment_score: int = 0,
        sentiment_reason: str = "",
    ) -> EntrySignal:
        """
        Evaluate entry with hard gates + soft scoring.
        """
        price = float(df["close"].iloc[-1])

        # Calculate EMAs
        df = self._ema.calculate(df)
        ema_vals = self._ema.latest(df)

        signal = EntrySignal(
            ticker=ticker,
            direction="NEUTRAL",
            entry_price=price,
            confidence=0.0,
            ema_values=ema_vals,
        )

        breakdown = {}
        total_score = 0

        # ════════════════════════════════════════════════════════════
        # HARD GATE 1: Price vs 200 EMA (trend direction)
        # ════════════════════════════════════════════════════════════
        if ema_vals.is_bullish(price):
            direction = "LONG"
        elif ema_vals.is_bearish(price):
            direction = "SHORT"
        else:
            signal.skip_reason = "Price on 200 EMA — no clear trend"
            return signal

        signal.direction = direction

        # ════════════════════════════════════════════════════════════
        # HARD GATE 2: 13/48 EMA crossover alignment
        # ════════════════════════════════════════════════════════════
        crossover = self._ema.detect_crossover(df, fast=13, slow=48)
        cross_aligned = (
            (crossover == "BULLISH" and direction == "LONG") or
            (crossover == "BEARISH" and direction == "SHORT")
        )
        if not cross_aligned:
            signal.skip_reason = f"No aligned EMA crossover (got {crossover}, need {'BULLISH' if direction == 'LONG' else 'BEARISH'})"
            signal.checks_failed.append(signal.skip_reason)
            return signal

        signal.checks_passed["ema_cross"] = f"EMA 13/48 {crossover}"

        # ════════════════════════════════════════════════════════════
        # HARD GATE 3: 8 EMA aligned with direction
        # ════════════════════════════════════════════════════════════
        if direction == "LONG":
            ema8_ok = ema_vals.ema8 > ema_vals.ema13
        else:
            ema8_ok = ema_vals.ema8 < ema_vals.ema13

        if not ema8_ok:
            signal.skip_reason = "8 EMA not aligned with direction"
            signal.checks_failed.append(signal.skip_reason)
            return signal

        signal.checks_passed["ema8_trend"] = "8 EMA aligned"

        # ════════════════════════════════════════════════════════════
        # SOFT SCORING — all add/subtract points, never block
        # ════════════════════════════════════════════════════════════

        # --- EMA full alignment (+2) ---
        alignment = ema_vals.ema_alignment_score()
        breakdown["ema_alignment"] = alignment
        total_score += alignment

        # --- EMA crossover recency (+3) ---
        breakdown["ema_crossover"] = 3  # Already confirmed aligned above
        total_score += 3

        # --- 48 EMA bounce (+3) ---
        bounce = self._ema.bounced_off_48(df)
        expected = "BULLISH_BOUNCE" if direction == "LONG" else "BEARISH_BOUNCE"
        if bounce == expected:
            breakdown["ema48_bounce"] = 3
            total_score += 3
            signal.checks_passed["ema48_bounce"] = f"48 EMA bounce ({bounce})"
        else:
            breakdown["ema48_bounce"] = 0

        # --- Chart patterns (+1 to +3) ---
        pattern_score, pattern_desc = self._patterns.best_pattern(df, direction)
        breakdown["chart_pattern"] = pattern_score
        total_score += pattern_score
        signal.entry_pattern = pattern_desc if pattern_score > 0 else ""
        if pattern_score > 0:
            signal.checks_passed["chart_pattern"] = pattern_desc

        # --- Volume confirmation (+2) ---
        vol_signal = self._volume.confirm(df)
        signal.volume_signal = vol_signal
        if vol_signal.confirmed:
            breakdown["volume"] = 2
            total_score += 2
            signal.checks_passed["volume"] = vol_signal.reason
        else:
            breakdown["volume"] = 0
            signal.checks_failed.append(f"volume: {vol_signal.reason}")

        # --- S/D zone proximity (+2) ---
        if active_zones is None:
            try:
                events = self._structure.detect(df.iloc[-100:])
                active_zones = self._zones.build_zones(df.iloc[-100:], events)
            except Exception:
                active_zones = []

        zone_kind = "DEMAND" if direction == "LONG" else "SUPPLY"
        zone = self._zones.nearest_zone(active_zones, price, zone_kind, tolerance_pct=0.02)
        at_zone = zone is not None or self._zones.price_at_zone(active_zones, price, zone_kind)
        signal.nearest_zone = zone

        if at_zone:
            breakdown["sd_zone"] = 2
            total_score += 2
            signal.checks_passed["sd_zone"] = f"Near {zone_kind} zone"
        else:
            breakdown["sd_zone"] = 0

        # --- RSI extreme (+2) ---
        rsi = self._calc_rsi(df)
        signal.entry_rsi = rsi
        rsi_pts = 0
        if direction == "LONG" and rsi < self._rsi_oversold:
            rsi_pts = 2
        elif direction == "SHORT" and rsi > self._rsi_overbought:
            rsi_pts = 2
        breakdown["rsi"] = rsi_pts
        total_score += rsi_pts

        # --- Bollinger Band extreme (+2) ---
        bb_pts = self._calc_bb_score(df, price, direction)
        breakdown["bollinger"] = bb_pts
        total_score += bb_pts

        # --- Momentum (+1) ---
        mom_pts = self._calc_momentum(df, direction)
        breakdown["momentum"] = mom_pts
        total_score += mom_pts

        # --- WOBI (injected from bot.py) ---
        if wobi_score != 0:
            breakdown["wobi"] = wobi_score
            total_score += wobi_score
            signal.wobi_score = wobi_score
            if wobi_reason:
                signal.checks_passed["wobi"] = wobi_reason

        # --- Sentiment (injected from bot.py) ---
        if sentiment_score != 0:
            breakdown["sentiment"] = sentiment_score
            total_score += sentiment_score
            signal.sentiment_score = sentiment_score

        # ════════════════════════════════════════════════════════════
        # HARD GATE 4: Minimum score + probability
        # ════════════════════════════════════════════════════════════
        signal.score = total_score
        signal.score_breakdown = breakdown

        # Probability: score 5→70%, score 20→75%, capped at 75%
        max_possible = 20
        clamped = max(0, min(total_score, max_possible))
        if clamped <= 5:
            prob = 0.50 + (clamped / 5) * 0.20
        else:
            prob = 0.70 + ((clamped - 5) / (max_possible - 5)) * 0.05
        signal.confidence = min(prob, 0.75)

        if total_score < self.min_score:
            signal.skip_reason = f"Score {total_score} below minimum {self.min_score}"
            signal.checks_failed.append(signal.skip_reason)
            return signal

        if signal.confidence < self.min_probability:
            signal.skip_reason = f"Probability {signal.confidence:.0%} below minimum {self.min_probability:.0%}"
            signal.checks_failed.append(signal.skip_reason)
            return signal

        # ════════════════════════════════════════════════════════════
        # ALL GATES PASSED — valid signal
        # ════════════════════════════════════════════════════════════
        signal.valid = True
        return signal

    # ──────────────────────── Helper methods ────────────────────────

    def _calc_rsi(self, df: pd.DataFrame) -> float:
        import numpy as np
        closes = df["close"].astype(float)
        delta = closes.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(com=self._rsi_period - 1, min_periods=self._rsi_period).mean()
        avg_loss = loss.ewm(com=self._rsi_period - 1, min_periods=self._rsi_period).mean()
        rs = avg_gain / avg_loss.replace(0, float('nan'))
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1]) if not rsi.empty else 50.0

    def _calc_bb_score(self, df: pd.DataFrame, price: float, direction: str) -> int:
        closes = df["close"].astype(float)
        mid = closes.rolling(self._bb_period).mean().iloc[-1]
        std = closes.rolling(self._bb_period).std().iloc[-1]
        upper = float(mid + self._bb_std * std)
        lower = float(mid - self._bb_std * std)
        if direction == "LONG" and price <= lower:
            return 2
        if direction == "SHORT" and price >= upper:
            return 2
        return 0

    def _calc_momentum(self, df: pd.DataFrame, direction: str) -> int:
        if len(df) < 4:
            return 0
        tail = df["close"].astype(float).iloc[-4:].values
        moves = [tail[i + 1] - tail[i] for i in range(3)]
        if direction == "LONG" and all(m > 0 for m in moves):
            return 1
        if direction == "SHORT" and all(m < 0 for m in moves):
            return 1
        return 0
