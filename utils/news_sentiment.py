"""
News & Sentiment Layer
Zoran's Layer 3 mentions DeItaone (Walter Bloomberg) for news sentiment.
We can't access DeItaone directly, so we implement two free alternatives:

1. Funding Rate Sentiment — from Hyperliquid (leading indicator)
   - Extreme positive funding = overleveraged longs → bearish pressure
   - Extreme negative funding = overleveraged shorts → bullish pressure

2. Crypto Fear & Greed Index — from alternative.me (contrarian indicator)
   - Extreme Fear (<25) → contrarian bullish
   - Extreme Greed (>75) → contrarian bearish

Both are soft signals: ±1 score point, never blocking.
"""

from __future__ import annotations
import logging
import time
import json
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SentimentSignal:
    """Combined sentiment analysis result."""
    funding_rate: Optional[float] = None      # Raw funding rate
    funding_bias: str = "NEUTRAL"             # 'BULL', 'BEAR', 'NEUTRAL'
    fear_greed_value: Optional[int] = None    # 0-100
    fear_greed_label: str = ""                # 'Extreme Fear', 'Fear', etc.
    fear_greed_bias: str = "NEUTRAL"          # 'BULL', 'BEAR', 'NEUTRAL'
    overall_bias: str = "NEUTRAL"             # Combined bias
    timestamp: float = 0.0

    def score_adjustment(self, direction: str) -> tuple[int, str]:
        """
        Returns score adjustment (±1) based on sentiment.
        Positive = sentiment supports the direction.
        """
        score = 0
        reasons = []

        # Funding rate signal
        if self.funding_bias == "BULL" and direction == "LONG":
            score += 1
            reasons.append(f"Funding bearish ({self.funding_rate:+.4%}) → contrarian LONG")
        elif self.funding_bias == "BEAR" and direction == "SHORT":
            score += 1
            reasons.append(f"Funding bullish ({self.funding_rate:+.4%}) → contrarian SHORT")
        elif self.funding_bias == "BULL" and direction == "SHORT":
            score -= 1
            reasons.append(f"Funding bearish but going SHORT → caution")
        elif self.funding_bias == "BEAR" and direction == "LONG":
            score -= 1
            reasons.append(f"Funding bullish but going LONG → caution")

        # Fear & Greed signal (only if extreme)
        if self.fear_greed_bias == "BULL" and direction == "LONG":
            score += 1
            reasons.append(f"F&G={self.fear_greed_value} (extreme fear) → contrarian LONG")
        elif self.fear_greed_bias == "BEAR" and direction == "SHORT":
            score += 1
            reasons.append(f"F&G={self.fear_greed_value} (extreme greed) → contrarian SHORT")

        # Clamp to ±1 total
        score = max(-1, min(1, score))

        reason = " | ".join(reasons) if reasons else "Sentiment neutral"
        return score, reason

    def summary(self) -> str:
        parts = []
        if self.funding_rate is not None:
            parts.append(f"Funding={self.funding_rate:+.4%}({self.funding_bias})")
        if self.fear_greed_value is not None:
            parts.append(f"F&G={self.fear_greed_value}({self.fear_greed_label})")
        return " | ".join(parts) if parts else "No sentiment data"


class NewsSentiment:
    """
    Aggregates sentiment from multiple free sources.
    Updates on configurable intervals. Never blocks trades.
    """

    def __init__(self, config: dict, hl_client=None):
        """
        Args:
            config: Bot config with 'sentiment' section
            hl_client: HyperliquidClient for funding rates
        """
        sent_cfg = config.get("sentiment", {})
        self.enabled = sent_cfg.get("enabled", True)
        self.funding_extreme = sent_cfg.get("funding_rate_extreme", 0.0001)  # 0.01%
        self.fg_enabled = sent_cfg.get("fear_greed_enabled", True)
        self.fg_url = sent_cfg.get("fear_greed_url", "https://api.alternative.me/fng/")
        self.refresh_seconds = sent_cfg.get("refresh_seconds", 3600)  # 1 hour default
        self.hl_client = hl_client

        # Cache
        self._last_update: float = 0
        self._signal: Optional[SentimentSignal] = None
        self._funding_cache: dict[str, tuple[float, float]] = {}  # ticker: (ts, rate)

    def _fetch_fear_greed(self) -> tuple[Optional[int], str]:
        """Fetch Crypto Fear & Greed Index (free, no API key)."""
        try:
            import urllib.request
            req = urllib.request.Request(
                self.fg_url,
                headers={"User-Agent": "MahmudBot/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if "data" in data and len(data["data"]) > 0:
                    entry = data["data"][0]
                    value = int(entry.get("value", 50))
                    label = entry.get("value_classification", "")
                    return value, label
        except Exception as e:
            logger.debug(f"Fear & Greed fetch failed: {e}")
        return None, ""

    def _fetch_funding_rate(self, ticker: str) -> Optional[float]:
        """Fetch current funding rate from Hyperliquid."""
        # Check cache (funding updates every hour, cache for 5 min)
        if ticker in self._funding_cache:
            ts, rate = self._funding_cache[ticker]
            if time.time() - ts < 300:
                return rate

        if self.hl_client is None:
            return None

        try:
            # Use the info API to get meta + funding data
            # Hyperliquid SDK: info.meta_and_asset_ctxs() returns funding rates
            if hasattr(self.hl_client, '_info') and self.hl_client._info is not None:
                meta = self.hl_client._info.meta_and_asset_ctxs()
                if meta and len(meta) >= 2:
                    asset_ctxs = meta[1]
                    # Find the ticker in asset contexts
                    universe = meta[0].get("universe", [])
                    for i, asset in enumerate(universe):
                        if asset.get("name") == ticker and i < len(asset_ctxs):
                            funding = float(asset_ctxs[i].get("funding", 0))
                            self._funding_cache[ticker] = (time.time(), funding)
                            return funding
        except Exception as e:
            logger.debug(f"Funding rate fetch failed for {ticker}: {e}")
        return None

    def update(self, ticker: str = "BTC") -> SentimentSignal:
        """
        Update sentiment data. Uses BTC as default reference for Fear & Greed
        and per-ticker for funding rates.
        """
        if not self.enabled:
            return SentimentSignal()

        now = time.time()
        if self._signal and (now - self._last_update) < self.refresh_seconds:
            # Update just the funding rate (cheaper) if within refresh window
            funding = self._fetch_funding_rate(ticker)
            if funding is not None:
                self._signal.funding_rate = funding
                self._signal.funding_bias = self._funding_to_bias(funding)
            return self._signal

        signal = SentimentSignal(timestamp=now)

        # 1. Funding rate
        funding = self._fetch_funding_rate(ticker)
        if funding is not None:
            signal.funding_rate = funding
            signal.funding_bias = self._funding_to_bias(funding)

        # 2. Fear & Greed Index
        if self.fg_enabled:
            value, label = self._fetch_fear_greed()
            if value is not None:
                signal.fear_greed_value = value
                signal.fear_greed_label = label
                signal.fear_greed_bias = self._fg_to_bias(value)

        # Combined bias
        biases = [signal.funding_bias, signal.fear_greed_bias]
        bull_count = biases.count("BULL")
        bear_count = biases.count("BEAR")
        if bull_count > bear_count:
            signal.overall_bias = "BULL"
        elif bear_count > bull_count:
            signal.overall_bias = "BEAR"
        else:
            signal.overall_bias = "NEUTRAL"

        self._signal = signal
        self._last_update = now
        logger.info(f"Sentiment updated: {signal.summary()}")
        return signal

    def _funding_to_bias(self, rate: float) -> str:
        """
        Convert funding rate to contrarian bias.
        Extreme positive funding = overleveraged longs → bearish pressure
        Extreme negative funding = overleveraged shorts → bullish pressure
        """
        if rate > self.funding_extreme:
            return "BEAR"   # Overleveraged longs → bearish pressure
        elif rate < -self.funding_extreme:
            return "BULL"   # Overleveraged shorts → bullish pressure
        return "NEUTRAL"

    def _fg_to_bias(self, value: int) -> str:
        """
        Convert Fear & Greed index to contrarian bias.
        Extreme Fear (<25) = buy signal (contrarian)
        Extreme Greed (>75) = sell signal (contrarian)
        """
        if value <= 25:
            return "BULL"   # Extreme fear → contrarian buy
        elif value >= 75:
            return "BEAR"   # Extreme greed → contrarian sell
        return "NEUTRAL"

    def get_score(self, ticker: str, direction: str) -> tuple[int, str]:
        """
        Get score adjustment for a trade direction.
        Returns (±1 or 0, reason string).
        """
        signal = self.update(ticker)
        return signal.score_adjustment(direction)

    def get_status(self) -> dict:
        """Get current sentiment status for dashboard."""
        if self._signal is None:
            return {"enabled": self.enabled, "data": None}
        s = self._signal
        return {
            "enabled": self.enabled,
            "funding_rate": s.funding_rate,
            "funding_bias": s.funding_bias,
            "fear_greed_value": s.fear_greed_value,
            "fear_greed_label": s.fear_greed_label,
            "fear_greed_bias": s.fear_greed_bias,
            "overall_bias": s.overall_bias,
            "last_update": s.timestamp,
        }
