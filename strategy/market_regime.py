"""
Market Regime Gate v3.0 — Panic / Recovery / Rally / Cascade
=============================================================
Implements Zoran's Phase 7 (gates 23-26):

  23. PANIC mode: ≥3 markets DISORDERLY + negative WOBI + 15m BEAR
      → LONGs blocked globally (except oil/gold/silver)
      → SHORTs get +2 score bonus

  24. RECOVERY gate: after panic clears
      → LONGs blocked until vol stabilises + EMA turns positive

  25. RALLY mode: ≥5 markets bullish
      → SHORTs blocked, LONGs boosted

  26. CASCADE loss gate: ≥3 consecutive SL hits across markets in 10 min
      → that direction blocked for 5 min

Rationale: "My biggest problem is to teach the bot to stay away from
crashing markets. Not to think that RSI is now good and start buying."
— Zoran, 2026-04-03
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class GlobalRegime(Enum):
    NORMAL = "NORMAL"
    PANIC = "PANIC"         # Market crashing — LONGs blocked
    RECOVERY = "RECOVERY"   # Post-panic — LONGs still restricted
    RALLY = "RALLY"         # Market surging — SHORTs blocked


@dataclass
class RegimeState:
    regime: GlobalRegime = GlobalRegime.NORMAL
    long_blocked: bool = False
    short_blocked: bool = False
    long_score_bonus: int = 0
    short_score_bonus: int = 0
    reason: str = ""
    panic_cleared_at: Optional[float] = None


@dataclass
class CascadeTracker:
    """Tracks consecutive SL hits across all markets."""
    recent_sl_hits: list = field(default_factory=list)  # [(timestamp, direction), ...]
    direction_blocked: Optional[str] = None
    blocked_until: float = 0.0
    window_seconds: int = 600       # 10 min window
    trigger_count: int = 3          # 3 SL hits in window = block
    block_duration: int = 300       # Block for 5 min


class MarketRegimeGate:
    """
    Monitors global market conditions and enforces direction blocks.
    Called from bot.py scan_markets() before evaluating individual signals.
    """

    def __init__(self, config: dict = None):
        self.config = config or {}
        cfg = config.get("market_regime", {}) if config else {}

        self.enabled = cfg.get("enabled", True)
        self.panic_threshold = cfg.get("panic_threshold", 3)     # ≥3 DISORDERLY markets
        self.rally_threshold = cfg.get("rally_threshold", 5)     # ≥5 bullish markets
        self.recovery_ema_confirm = cfg.get("recovery_ema_confirm", True)

        # Assets exempt from PANIC long-block (safe havens / oil)
        self.panic_long_exempt = set(cfg.get("panic_long_exempt", ["WTI", "BRENT", "XAU", "XAG"]))

        self.state = RegimeState()
        self.cascade = CascadeTracker()
        self._market_conditions: dict = {}   # ticker → condition snapshot
        self._last_check = 0.0

    def update_market_condition(self, ticker: str, regime_value: str, wobi_score: float, htf_bear: bool):
        """
        Called for each market scanned. Updates the global picture.
        regime_value: 'DISORDERLY', 'STORM', 'TRENDING', etc.
        wobi_score: negative = bearish order book
        htf_bear: True if 15m trend is bearish
        """
        self._market_conditions[ticker] = {
            "regime": regime_value,
            "wobi": wobi_score,
            "htf_bear": htf_bear,
            "ts": time.time(),
        }
        self._recalculate()

    def _recalculate(self):
        """Recalculate global regime from current market conditions."""
        now = time.time()
        # Only consider recent data (last 5 min)
        recent = {t: v for t, v in self._market_conditions.items() if now - v["ts"] < 300}

        if not recent:
            self.state = RegimeState(regime=GlobalRegime.NORMAL, reason="No market data")
            return

        # Count disorderly markets
        disorderly = [t for t, v in recent.items() if v["regime"] in ("DISORDERLY", "STORM")]
        bearish_wobi = [t for t, v in recent.items() if v["wobi"] < -0.3]
        htf_bear_markets = [t for t, v in recent.items() if v["htf_bear"]]

        # Count bullish markets (for rally detection)
        bullish = [t for t, v in recent.items() if not v["htf_bear"] and v["wobi"] > 0.1]

        # ── PANIC: ≥3 markets DISORDERLY + negative WOBI + 15m BEAR ──
        if (
            len(disorderly) >= self.panic_threshold and
            len(bearish_wobi) >= 2 and
            len(htf_bear_markets) >= 2
        ):
            if self.state.regime != GlobalRegime.PANIC:
                logger.warning(
                    f"🚨 PANIC MODE: {len(disorderly)} DISORDERLY markets ({', '.join(disorderly[:5])}), "
                    f"{len(bearish_wobi)} neg WOBI, {len(htf_bear_markets)} HTF BEAR — LONGs blocked globally"
                )
            self.state = RegimeState(
                regime=GlobalRegime.PANIC,
                long_blocked=True,
                short_blocked=False,
                short_score_bonus=2,
                reason=f"PANIC: {len(disorderly)} disorderly, {len(htf_bear_markets)} HTF bear",
            )
            return

        # ── RECOVERY: panic cleared but not yet confirmed safe ──
        if self.state.regime == GlobalRegime.PANIC:
            if self.state.panic_cleared_at is None:
                self.state.panic_cleared_at = time.time()
                logger.info("🟡 PANIC cleared — entering RECOVERY mode. LONGs still restricted.")

            # Stay in recovery for at least 15 min after panic
            recovery_age = time.time() - (self.state.panic_cleared_at or time.time())
            if recovery_age < 900:  # 15 min minimum recovery
                self.state = RegimeState(
                    regime=GlobalRegime.RECOVERY,
                    long_blocked=True,
                    short_blocked=False,
                    reason=f"RECOVERY: {int((900 - recovery_age) / 60)}min remaining",
                    panic_cleared_at=self.state.panic_cleared_at,
                )
                return

        # ── RALLY: ≥5 markets bullish ──
        if len(bullish) >= self.rally_threshold:
            if self.state.regime != GlobalRegime.RALLY:
                logger.info(f"📈 RALLY MODE: {len(bullish)} bullish markets — SHORTs blocked")
            self.state = RegimeState(
                regime=GlobalRegime.RALLY,
                long_blocked=False,
                short_blocked=True,
                long_score_bonus=2,
                reason=f"RALLY: {len(bullish)} bullish markets",
            )
            return

        # ── NORMAL ──
        if self.state.regime not in (GlobalRegime.NORMAL,):
            logger.info(f"✅ Market regime normalised (was {self.state.regime.value})")
        self.state = RegimeState(regime=GlobalRegime.NORMAL, reason="Markets normal")

    def can_trade(self, ticker: str, direction: str) -> tuple[bool, str]:
        """
        Returns (allowed, reason).
        Check before opening any position.
        """
        if not self.enabled:
            return True, "Regime gate disabled"

        # ── Cascade loss block ──
        cascade_blocked, cascade_reason = self._check_cascade(direction)
        if cascade_blocked:
            return False, cascade_reason

        # ── Panic/Rally/Recovery blocks ──
        if direction == "LONG" and self.state.long_blocked:
            # Check if this ticker is exempt (safe haven)
            if ticker not in self.panic_long_exempt:
                return False, f"{self.state.regime.value}: LONGs blocked — {self.state.reason}"

        if direction == "SHORT" and self.state.short_blocked:
            return False, f"{self.state.regime.value}: SHORTs blocked — {self.state.reason}"

        return True, "OK"

    def get_score_bonus(self, direction: str) -> int:
        """Returns score bonus for a direction based on current regime."""
        if direction == "LONG":
            return self.state.long_score_bonus
        return self.state.short_score_bonus

    def record_sl_hit(self, direction: str):
        """
        v3.0 Cascade gate: record an SL hit.
        If ≥3 hits of same direction in 10 min → block that direction for 5 min.
        """
        now = time.time()
        self.cascade.recent_sl_hits.append((now, direction))
        # Clean old entries
        cutoff = now - self.cascade.window_seconds
        self.cascade.recent_sl_hits = [(t, d) for t, d in self.cascade.recent_sl_hits if t > cutoff]

        # Count same-direction hits in window
        same_dir_hits = [(t, d) for t, d in self.cascade.recent_sl_hits if d == direction]
        if len(same_dir_hits) >= self.cascade.trigger_count:
            self.cascade.direction_blocked = direction
            self.cascade.blocked_until = now + self.cascade.block_duration
            logger.warning(
                f"⚡ CASCADE GATE: {len(same_dir_hits)} {direction} SL hits in {self.cascade.window_seconds//60}min "
                f"— {direction} blocked for {self.cascade.block_duration//60}min"
            )

    def _check_cascade(self, direction: str) -> tuple[bool, str]:
        """Check if direction is currently cascade-blocked."""
        if self.cascade.direction_blocked != direction:
            return False, ""
        if time.time() < self.cascade.blocked_until:
            remaining = int(self.cascade.blocked_until - time.time())
            return True, f"CASCADE: {direction} blocked ({remaining}s remaining after {self.cascade.trigger_count} rapid SL hits)"
        else:
            # Block expired
            self.cascade.direction_blocked = None
            return False, ""

    def get_status(self) -> str:
        """Human-readable regime status."""
        return f"{self.state.regime.value} | {self.state.reason}"
