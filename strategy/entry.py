"""
Entry Logic — Full Confluence Required
All 7 conditions must align for an A+ entry:

  1. Price above/below 200 EMA (trend direction)
  2. 13/48 EMA cross (momentum shift)
  3. Bounce off 48 EMA (last defense holds)
  4. 8 EMA trend confirmed (riding the wave)
  5. Bull Flag or Bear Flag (continuation pattern)
  6. Volume confirms the move
  7. Supply/Demand zone alignment

No confluence = no trade.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

from .ema import EMACalculator, EMAValues
from .structure import BOSCHOCHDetector, StructureEvent
from .zones import SupplyDemandZones, Zone
from .volume import VolumeConfirmation, VolumeSignal
from .scoring import ScoringEngine, ScoreBreakdown


@dataclass
class EntrySignal:
    ticker: str
    direction: str           # 'LONG' or 'SHORT'
    entry_price: float
    confidence: float        # 0.0 – 1.0

    score: ScoreBreakdown = None
    volume_signal: VolumeSignal = None
    structure_event: Optional[StructureEvent] = None
    nearest_zone: Optional[Zone] = None
    ema_values: EMAValues = None
    mtf_blocked: bool = False      # v2.5+: blocked by multi-timeframe filter
    wobi_score: int = 0            # v2.5+: order book score contribution
    sentiment_score: int = 0       # v2.5+: sentiment score contribution

    checks_passed: dict = field(default_factory=dict)
    checks_failed: list[str] = field(default_factory=list)
    skip_reason: Optional[str] = None

    valid: bool = False

    def summary(self) -> str:
        lines = [
            f"{'✅' if self.valid else '❌'} Entry Signal — {self.ticker} {self.direction}",
            f"  Price: {self.entry_price:.4f}",
            f"  Score: {self.score.total if self.score else 'N/A'} | Prob: {self.score.probability:.1%}" if self.score else "",
            f"  Volume: {self.volume_signal.strength if self.volume_signal else 'N/A'}",
        ]
        if self.skip_reason:
            lines.append(f"  Skip: {self.skip_reason}")
        if self.checks_failed:
            lines.append(f"  Failed checks: {', '.join(self.checks_failed)}")
        return "\n".join(l for l in lines if l)


class EntryLogic:
    """
    Evaluates all 7 confluence conditions and generates entry signals.
    Only produces a signal when ALL conditions are met.
    """

    def __init__(
        self,
        config: dict,
    ):
        self.config = config
        self.min_score = config.get("scoring", {}).get("min_score", 5)
        self.min_probability = config.get("scoring", {}).get("min_probability", 0.65)

        self._ema = EMACalculator()
        self._structure = BOSCHOCHDetector(swing_lookback=5)
        self._zones = SupplyDemandZones()
        self._volume = VolumeConfirmation()
        self._scoring = ScoringEngine(
            rsi_period=config.get("rsi_period", 14),
            rsi_oversold=config.get("rsi_oversold", 35),
            rsi_overbought=config.get("rsi_overbought", 65),
            bb_period=config.get("bb_period", 20),
            bb_std=config.get("bb_std", 2.0),
            min_score=self.min_score,
            min_probability=self.min_probability,
        )

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
        Run the full 7-condition confluence check + WOBI/sentiment scoring.

        Args:
            df: OHLCV DataFrame with at least 250 candles (5m timeframe)
            ticker: Market symbol
            active_zones: Pre-built S/D zones (or None to build from data)
            wobi_score: Order book score contribution (0 or +2)
            wobi_reason: Order book reason string
            sentiment_score: Sentiment score contribution (±1)
            sentiment_reason: Sentiment reason string

        Returns:
            EntrySignal (valid=True only if all conditions pass)
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

        # ── Condition 1: Price vs 200 EMA (trend direction) ──────────────
        if ema_vals.is_bullish(price):
            direction = "LONG"
            signal.checks_passed["ema200_trend"] = f"Price {price:.4f} > EMA200 {ema_vals.ema200:.4f}"
        elif ema_vals.is_bearish(price):
            direction = "SHORT"
            signal.checks_passed["ema200_trend"] = f"Price {price:.4f} < EMA200 {ema_vals.ema200:.4f}"
        else:
            signal.checks_failed.append("ema200_trend: price on 200 EMA — no clear trend")
            signal.skip_reason = "Price on 200 EMA — no clear trend bias"
            return signal

        signal.direction = direction

        # ── Condition 2: 13/48 EMA Cross ─────────────────────────────────
        crossover = self._ema.detect_crossover(df, fast=13, slow=48)
        if crossover == "BULLISH" and direction == "LONG":
            signal.checks_passed["ema_cross"] = "Bullish 13/48 cross confirmed"
        elif crossover == "BEARISH" and direction == "SHORT":
            signal.checks_passed["ema_cross"] = "Bearish 13/48 cross confirmed"
        else:
            signal.checks_failed.append(f"ema_cross: crossover={crossover}, need {'BULLISH' if direction == 'LONG' else 'BEARISH'}")
            signal.skip_reason = "No aligned EMA crossover"
            return signal

        # ── Condition 3: Bounce off 48 EMA ───────────────────────────────
        bounce = self._ema.bounced_off_48(df)
        expected_bounce = "BULLISH_BOUNCE" if direction == "LONG" else "BEARISH_BOUNCE"
        if bounce == expected_bounce:
            signal.checks_passed["ema48_bounce"] = f"48 EMA bounce confirmed ({bounce})"
        else:
            signal.checks_failed.append(f"ema48_bounce: expected {expected_bounce}, got {bounce}")
            signal.skip_reason = "No 48 EMA bounce"
            return signal

        # ── Condition 4: 8 EMA trend confirmation ────────────────────────
        if direction == "LONG":
            ema8_ok = ema_vals.ema8 > ema_vals.ema13
            cond_desc = f"EMA8 {ema_vals.ema8:.4f} > EMA13 {ema_vals.ema13:.4f}"
        else:
            ema8_ok = ema_vals.ema8 < ema_vals.ema13
            cond_desc = f"EMA8 {ema_vals.ema8:.4f} < EMA13 {ema_vals.ema13:.4f}"

        if ema8_ok:
            signal.checks_passed["ema8_trend"] = cond_desc
        else:
            signal.checks_failed.append(f"ema8_trend: {cond_desc} — not aligned")
            signal.skip_reason = "8 EMA not aligned with direction"
            return signal

        # ── Condition 5: Chart pattern (Flag or equivalent) ──────────────
        # Scoring engine handles pattern detection; check if score has pattern points
        score = self._scoring.score(df, direction, ema_vals)
        signal.score = score
        if score.chart_pattern_score > 0:
            signal.checks_passed["chart_pattern"] = f"Pattern detected (+{score.chart_pattern_score}pts)"
        else:
            signal.checks_failed.append("chart_pattern: no flag/engulfing detected")
            signal.skip_reason = "No chart pattern confirmation"
            return signal

        # ── Condition 6: Volume confirmation ─────────────────────────────
        vol_signal = self._volume.confirm(df)
        signal.volume_signal = vol_signal
        if vol_signal.confirmed:
            signal.checks_passed["volume"] = vol_signal.reason
        else:
            signal.checks_failed.append(f"volume: {vol_signal.reason}")
            signal.skip_reason = f"Volume not confirmed: {vol_signal.reason}"
            return signal

        # ── Condition 7: Supply/Demand zone alignment ─────────────────────
        if active_zones is None:
            events = self._structure.detect(df)
            active_zones = self._zones.build_zones(df, events)

        zone_kind = "DEMAND" if direction == "LONG" else "SUPPLY"
        zone = self._zones.nearest_zone(active_zones, price, zone_kind, tolerance_pct=0.02)
        signal.nearest_zone = zone

        if zone is not None:
            signal.checks_passed["sd_zone"] = f"{zone_kind} zone at {zone.proximal:.4f}–{zone.distal:.4f}"
        else:
            # Soft check: if price is AT a zone it's fine; if no zone found, skip
            at_zone = self._zones.price_at_zone(active_zones, price, zone_kind)
            if at_zone:
                signal.checks_passed["sd_zone"] = f"Price inside active {zone_kind} zone"
            else:
                signal.checks_failed.append(f"sd_zone: no active {zone_kind} zone near price")
                signal.skip_reason = f"No {zone_kind} zone alignment"
                return signal

        # ── WOBI + Sentiment Score Integration (v2.5+) ────────────────────
        if wobi_score != 0:
            score.wobi_score = wobi_score
            score.total += wobi_score
            score.reasons.append(wobi_reason)
            signal.wobi_score = wobi_score
            signal.checks_passed["wobi"] = wobi_reason

        if sentiment_score != 0:
            score.sentiment_score = sentiment_score
            score.total += sentiment_score
            score.reasons.append(sentiment_reason)
            signal.sentiment_score = sentiment_score
            if sentiment_score > 0:
                signal.checks_passed["sentiment"] = sentiment_reason
            else:
                signal.checks_failed.append(f"sentiment: {sentiment_reason}")

        # Recalculate probability with updated total
        max_possible = 16
        clamped = max(0, min(score.total, max_possible))
        score.probability = 0.50 + (clamped / max_possible) * 0.45

        # ── Minimum Score + Probability Filter ───────────────────────────
        if not score.passes(self.min_score, self.min_probability):
            signal.checks_failed.append(
                f"score_filter: score={score.total} (need {self.min_score}), "
                f"prob={score.probability:.1%} (need {self.min_probability:.0%})"
            )
            signal.skip_reason = (
                f"Score {score.total}/{self.min_score} or probability "
                f"{score.probability:.1%}/{self.min_probability:.0%} below threshold"
            )
            return signal

        # ── All checks passed! ────────────────────────────────────────────
        signal.valid = True
        signal.confidence = score.probability
        return signal
