"""
Self-Learning Brain
After every trade, the bot analyzes what happened and adjusts its strategy.

Tracks per-ticker:
  - Pattern win rates (engulfing, flag, momentum, etc.)
  - RSI zone profitability
  - LONG vs SHORT performance
  - Score threshold effectiveness
  - SL hit frequency

Guardrails:
  - Min 15 trades per pattern before adjusting
  - Rolling window: last 500 trades
  - Asset isolation: per-ticker, no cross-contamination
  - SL hard cap: never exceeds 2x original
  - Direction ceiling: max ±10 probability points bias
"""

from __future__ import annotations
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

MIN_SAMPLE = 15          # Minimum trades before adjusting
MAX_TRADES = 500         # Rolling window
LOSS_AVOID_THRESHOLD = 0.70   # Avoid if >70% loss rate
WIN_PREFER_THRESHOLD = 0.65   # Prefer if >65% win rate
MAX_DIRECTION_BIAS = 10  # Max ±10 probability points


@dataclass
class PatternStats:
    pattern: str
    total: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total if self.total > 0 else 0.5

    @property
    def loss_rate(self) -> float:
        return self.losses / self.total if self.total > 0 else 0.5

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.total if self.total > 0 else 0.0

    def should_avoid(self) -> bool:
        return self.total >= MIN_SAMPLE and self.loss_rate > LOSS_AVOID_THRESHOLD

    def should_prefer(self) -> bool:
        return self.total >= MIN_SAMPLE and self.win_rate > WIN_PREFER_THRESHOLD


@dataclass
class TickerBrain:
    ticker: str
    direction_bias: float = 0.0      # ±10 max — positive = prefer LONG, negative = prefer SHORT
    sl_adjust_pct: float = 0.0       # Additional SL buffer (positive = wider)
    patterns: dict = field(default_factory=dict)
    rsi_zones: dict = field(default_factory=dict)    # e.g., "oversold", "overbought"
    direction_stats: dict = field(default_factory=dict)  # "LONG", "SHORT"
    recent_scores: list = field(default_factory=list)   # Last 50 entry scores
    recent_trades: list = field(default_factory=list)   # Last MAX_TRADES trade summaries
    total_trades: int = 0
    wins: int = 0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0.0


class LearningBrain:
    """
    Persistent self-learning engine.
    Loaded at bot start, updated after each trade, saved to learnings.json.
    """

    def __init__(self, learnings_file: str = "learnings.json", config: dict = None):
        self.learnings_file = learnings_file
        self.config = config or {}
        self._base_sl = abs(self.config.get("exit", {}).get("sl_pct", 3.0))
        self._max_sl = self._base_sl * 2  # Hard cap at 2x original
        self.tickers: dict[str, TickerBrain] = {}
        self._load()

    def _load(self):
        """Load brain from disk."""
        if os.path.exists(self.learnings_file):
            try:
                with open(self.learnings_file, "r") as f:
                    data = json.load(f)
                self._deserialize(data)
                logger.info(f"Brain loaded: {len(self.tickers)} tickers from {self.learnings_file}")
            except Exception as e:
                logger.warning(f"Could not load learnings: {e}. Starting fresh.")
                self.tickers = {}
        else:
            logger.info("No learnings file found. Starting with empty brain.")

    def save(self):
        """Persist brain to disk."""
        try:
            data = self._serialize()
            with open(self.learnings_file, "w") as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Brain saved to {self.learnings_file}")
        except Exception as e:
            logger.error(f"Could not save learnings: {e}")

    def _serialize(self) -> dict:
        """Convert brain to JSON-serializable dict."""
        result = {}
        for ticker, brain in self.tickers.items():
            result[ticker] = {
                "direction_bias": brain.direction_bias,
                "sl_adjust_pct": brain.sl_adjust_pct,
                "patterns": brain.patterns,
                "rsi_zones": brain.rsi_zones,
                "direction_stats": brain.direction_stats,
                "recent_scores": brain.recent_scores[-100:],  # Keep last 100
                "total_trades": brain.total_trades,
                "wins": brain.wins,
            }
        return result

    def _deserialize(self, data: dict):
        """Load brain from dict."""
        for ticker, d in data.items():
            brain = TickerBrain(ticker=ticker)
            brain.direction_bias = d.get("direction_bias", 0.0)
            brain.sl_adjust_pct = d.get("sl_adjust_pct", 0.0)
            brain.patterns = d.get("patterns", {})
            brain.rsi_zones = d.get("rsi_zones", {})
            brain.direction_stats = d.get("direction_stats", {})
            brain.recent_scores = d.get("recent_scores", [])
            brain.total_trades = d.get("total_trades", 0)
            brain.wins = d.get("wins", 0)
            self.tickers[ticker] = brain

    def _get_brain(self, ticker: str) -> TickerBrain:
        """Get or create a brain for a ticker."""
        if ticker not in self.tickers:
            self.tickers[ticker] = TickerBrain(ticker=ticker)
        return self.tickers[ticker]

    def record_trade(
        self,
        ticker: str,
        direction: str,
        pnl_usd: float,
        pnl_pct: float,
        pattern: str = "",
        score: int = 0,
        rsi_at_entry: float = 50.0,
        sl_hit: bool = False,
    ):
        """
        Record a completed trade and update patterns.

        Args:
            ticker: Market symbol
            direction: 'LONG' or 'SHORT'
            pnl_usd: Net P&L in USD
            pnl_pct: Leveraged P&L %
            pattern: Chart pattern at entry (e.g., 'engulfing', 'flag')
            score: Strategy score at entry
            rsi_at_entry: RSI value at entry
            sl_hit: Whether the stop loss was hit
        """
        brain = self._get_brain(ticker)
        won = pnl_usd > 0

        # Update totals
        brain.total_trades += 1
        if won:
            brain.wins += 1

        # Trim rolling window
        trade_summary = {
            "direction": direction,
            "pnl_usd": pnl_usd,
            "pnl_pct": pnl_pct,
            "pattern": pattern,
            "score": score,
            "rsi": rsi_at_entry,
            "sl_hit": sl_hit,
            "won": won,
        }
        brain.recent_trades.append(trade_summary)
        if len(brain.recent_trades) > MAX_TRADES:
            brain.recent_trades = brain.recent_trades[-MAX_TRADES:]

        # Update pattern stats
        if pattern:
            if pattern not in brain.patterns:
                brain.patterns[pattern] = {"total": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}
            p = brain.patterns[pattern]
            p["total"] += 1
            p["wins" if won else "losses"] += 1
            p["total_pnl"] += pnl_usd

        # Update RSI zone stats
        rsi_zone = "oversold" if rsi_at_entry < 35 else ("overbought" if rsi_at_entry > 65 else "neutral")
        if rsi_zone not in brain.rsi_zones:
            brain.rsi_zones[rsi_zone] = {"total": 0, "wins": 0, "losses": 0}
        rz = brain.rsi_zones[rsi_zone]
        rz["total"] += 1
        rz["wins" if won else "losses"] += 1

        # Update direction stats
        if direction not in brain.direction_stats:
            brain.direction_stats[direction] = {"total": 0, "wins": 0, "losses": 0, "pnl": 0.0}
        ds = brain.direction_stats[direction]
        ds["total"] += 1
        ds["wins" if won else "losses"] += 1
        ds["pnl"] += pnl_usd

        # Update score tracking
        brain.recent_scores.append(score)
        if len(brain.recent_scores) > 100:
            brain.recent_scores = brain.recent_scores[-100:]

        # ── Adapt strategy based on new data ─────────────────────────────
        self._adapt(brain)
        self.save()

    def _adapt(self, brain: TickerBrain):
        """
        Adjust strategy parameters based on accumulated data.
        Guardrails prevent extreme adjustments.
        """
        recent = brain.recent_trades[-100:]
        if len(recent) < MIN_SAMPLE:
            return

        # Direction bias adjustment
        long_trades = [t for t in recent if t["direction"] == "LONG"]
        short_trades = [t for t in recent if t["direction"] == "SHORT"]

        long_wr = sum(1 for t in long_trades if t["won"]) / len(long_trades) if long_trades else 0.5
        short_wr = sum(1 for t in short_trades if t["won"]) / len(short_trades) if short_trades else 0.5

        # Positive bias = prefer LONG; negative = prefer SHORT
        raw_bias = (long_wr - short_wr) * 20  # Scale to -10..+10 range
        brain.direction_bias = max(-MAX_DIRECTION_BIAS, min(MAX_DIRECTION_BIAS, raw_bias))

        # SL widening: if too many SL hits recently
        sl_hits = sum(1 for t in recent if t.get("sl_hit", False))
        sl_rate = sl_hits / len(recent)

        if sl_rate > 0.6:  # More than 60% hit SL
            # Widen SL up to the hard cap
            new_sl_adjust = min(self._base_sl * 0.5, self._max_sl - self._base_sl)
            if new_sl_adjust > brain.sl_adjust_pct:
                brain.sl_adjust_pct = new_sl_adjust
                logger.info(f"Brain [{brain.ticker}]: SL widened by +{new_sl_adjust:.1f}% (SL hit rate: {sl_rate:.0%})")
        elif sl_rate < 0.2:
            # Tighten SL back toward normal
            brain.sl_adjust_pct = max(0.0, brain.sl_adjust_pct - 0.1)

    def get_direction_bias(self, ticker: str) -> float:
        """Returns direction bias for a ticker (-10 to +10)."""
        brain = self._get_brain(ticker)
        return brain.direction_bias

    def get_sl_adjustment(self, ticker: str) -> float:
        """Returns additional SL buffer for a ticker (in %)."""
        brain = self._get_brain(ticker)
        return brain.sl_adjust_pct

    def should_avoid_pattern(self, ticker: str, pattern: str) -> bool:
        """Returns True if the brain has learned to avoid this pattern."""
        if not pattern:
            return False
        brain = self._get_brain(ticker)
        if pattern not in brain.patterns:
            return False
        p = brain.patterns[pattern]
        total = p.get("total", 0)
        losses = p.get("losses", 0)
        if total < MIN_SAMPLE:
            return False
        return (losses / total) > LOSS_AVOID_THRESHOLD

    def should_prefer_pattern(self, ticker: str, pattern: str) -> bool:
        """Returns True if the brain has learned to prefer this pattern."""
        if not pattern:
            return False
        brain = self._get_brain(ticker)
        if pattern not in brain.patterns:
            return False
        p = brain.patterns[pattern]
        total = p.get("total", 0)
        wins = p.get("wins", 0)
        if total < MIN_SAMPLE:
            return False
        return (wins / total) > WIN_PREFER_THRESHOLD

    def get_stats_summary(self, ticker: str) -> dict:
        """Get a summary of brain stats for a ticker (for dashboard)."""
        brain = self._get_brain(ticker)
        return {
            "ticker": ticker,
            "total_trades": brain.total_trades,
            "win_rate": round(brain.win_rate * 100, 1),
            "direction_bias": round(brain.direction_bias, 1),
            "sl_adjust_pct": round(brain.sl_adjust_pct, 2),
            "patterns": {
                k: {
                    "total": v.get("total", 0),
                    "win_rate": round(v.get("wins", 0) / v.get("total", 1) * 100, 1) if v.get("total", 0) > 0 else 0,
                }
                for k, v in brain.patterns.items()
            },
        }

    def get_all_stats(self) -> list[dict]:
        """Get brain stats for all tickers."""
        return [self.get_stats_summary(t) for t in sorted(self.tickers.keys())]
