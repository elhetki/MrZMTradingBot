"""
Multi-Timeframe Filter (MTF)
Zoran's rule: "Checks 5m, 15m, 30m, 1h charts. If 2 out of 3 higher
timeframes agree on trend direction, the bot will not trade against it."

Implementation:
  - For each signal, check 3 higher TFs (15m, 30m, 1h)
  - On each TF: price vs 200 EMA → BULL or BEAR
  - If 2/3 agree → that's the allowed direction
  - Signal direction must match MTF consensus or get rejected
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class MTFResult:
    """Result of multi-timeframe analysis."""
    allowed: bool
    consensus_direction: Optional[str]  # 'BULL', 'BEAR', or None (no consensus)
    signal_direction: str               # 'LONG' or 'SHORT'
    tf_votes: dict[str, str] = field(default_factory=dict)  # {'15m': 'BULL', ...}
    agreement_count: int = 0
    reason: str = ""

    def summary(self) -> str:
        votes = " | ".join(f"{tf}={d}" for tf, d in self.tf_votes.items())
        return f"MTF [{votes}] → {self.consensus_direction or 'NO_CONSENSUS'} ({self.agreement_count}/3) | Signal: {self.signal_direction} → {'✅ PASS' if self.allowed else '❌ BLOCKED'}"


class MTFFilter:
    """
    Multi-timeframe trend filter.
    Fetches higher TF candles and checks 200 EMA alignment.
    """

    def __init__(self, config: dict, hl_client=None):
        """
        Args:
            config: Bot config dict with 'mtf' section
            hl_client: HyperliquidClient instance for fetching candles
        """
        mtf_cfg = config.get("mtf", {})
        self.enabled = mtf_cfg.get("enabled", True)
        self.higher_timeframes = mtf_cfg.get("higher_timeframes", ["15m", "30m", "1h"])
        self.min_agreement = mtf_cfg.get("min_agreement", 2)
        self.ema_period = mtf_cfg.get("ema_period", 200)
        self.hl_client = hl_client

        # Cache: {(ticker, tf): (timestamp, direction)}
        self._cache: dict[tuple[str, str], tuple[float, str]] = {}
        # Cache TTL per timeframe (seconds)
        self._cache_ttl = {
            "15m": 300,   # refresh every 5 min
            "30m": 900,   # refresh every 15 min
            "1h": 900,    # refresh every 15 min
            "4h": 3600,   # refresh every 60 min
        }

    def _get_cache_ttl(self, tf: str) -> int:
        return self._cache_ttl.get(tf, 300)

    def _is_cached(self, ticker: str, tf: str) -> Optional[str]:
        """Return cached direction if still valid, else None."""
        key = (ticker, tf)
        if key not in self._cache:
            return None
        ts, direction = self._cache[key]
        if time.time() - ts > self._get_cache_ttl(tf):
            return None
        return direction

    def _analyze_tf(self, ticker: str, tf: str) -> Optional[str]:
        """
        Fetch candles for a single timeframe and determine trend via 200 EMA.
        Returns 'BULL' or 'BEAR' or None on failure.
        """
        # Check cache first
        cached = self._is_cached(ticker, tf)
        if cached:
            return cached

        if self.hl_client is None:
            logger.warning("MTF: No Hyperliquid client — cannot fetch higher TF data")
            return None

        try:
            df = self.hl_client.get_candles(ticker, interval=tf, limit=self.ema_period + 50)
            if df is None or len(df) < self.ema_period:
                logger.debug(f"MTF: Insufficient data for {ticker} {tf} (got {len(df) if df is not None else 0} candles)")
                return None

            # Calculate 200 EMA
            closes = df["close"].astype(float)
            ema200 = closes.ewm(span=self.ema_period, adjust=False).mean().iloc[-1]
            price = float(closes.iloc[-1])

            direction = "BULL" if price > ema200 else "BEAR"

            # Cache the result
            self._cache[(ticker, tf)] = (time.time(), direction)
            logger.debug(f"MTF: {ticker} {tf} → {direction} (price={price:.2f}, EMA200={ema200:.2f})")
            return direction

        except Exception as e:
            logger.error(f"MTF: Error analyzing {ticker} {tf}: {e}")
            return None

    def check(self, ticker: str, signal_direction: str) -> MTFResult:
        """
        Check if a signal direction aligns with higher timeframe consensus.

        Args:
            ticker: Market symbol (e.g., 'BTC')
            signal_direction: 'LONG' or 'SHORT'

        Returns:
            MTFResult with allowed=True/False and details
        """
        if not self.enabled:
            return MTFResult(
                allowed=True,
                consensus_direction=None,
                signal_direction=signal_direction,
                reason="MTF filter disabled",
            )

        tf_votes: dict[str, str] = {}
        bull_count = 0
        bear_count = 0

        for tf in self.higher_timeframes:
            direction = self._analyze_tf(ticker, tf)
            if direction is None:
                tf_votes[tf] = "N/A"
                continue

            tf_votes[tf] = direction
            if direction == "BULL":
                bull_count += 1
            else:
                bear_count += 1

        # Determine consensus
        consensus = None
        agreement = 0
        if bull_count >= self.min_agreement:
            consensus = "BULL"
            agreement = bull_count
        elif bear_count >= self.min_agreement:
            consensus = "BEAR"
            agreement = bear_count

        # Check alignment
        if consensus is None:
            # No consensus — allow the trade (no strong opposing signal)
            return MTFResult(
                allowed=True,
                consensus_direction=None,
                signal_direction=signal_direction,
                tf_votes=tf_votes,
                agreement_count=max(bull_count, bear_count),
                reason=f"No MTF consensus (BULL:{bull_count} BEAR:{bear_count}) — allowing trade",
            )

        # Map signal direction to trend direction
        signal_trend = "BULL" if signal_direction == "LONG" else "BEAR"
        allowed = signal_trend == consensus

        if allowed:
            reason = f"MTF confirms {consensus} trend ({agreement}/{len(self.higher_timeframes)} TFs agree)"
        else:
            reason = f"MTF BLOCKS {signal_direction}: consensus is {consensus} ({agreement}/{len(self.higher_timeframes)} TFs agree)"

        result = MTFResult(
            allowed=allowed,
            consensus_direction=consensus,
            signal_direction=signal_direction,
            tf_votes=tf_votes,
            agreement_count=agreement,
            reason=reason,
        )

        logger.info(f"MTF: {result.summary()}")
        return result

    def get_status(self, ticker: str) -> dict:
        """Get current MTF status for a ticker (for dashboard)."""
        tf_status = {}
        for tf in self.higher_timeframes:
            cached = self._is_cached(ticker, tf)
            tf_status[tf] = cached or "STALE"

        return {
            "ticker": ticker,
            "enabled": self.enabled,
            "timeframes": tf_status,
        }

    def clear_cache(self, ticker: str = None):
        """Clear cache for a specific ticker or all."""
        if ticker:
            self._cache = {k: v for k, v in self._cache.items() if k[0] != ticker}
        else:
            self._cache.clear()
