#!/usr/bin/env python3
"""
MahmudBot v1.0 — Z.M Trading Gym Strategy
Automated perpetual futures trading bot for Hyperliquid.

Modes:
  DRY RUN (default): Scans markets, generates signals, tracks paper P&L
  LIVE:              Executes real trades via Hyperliquid API

Usage:
    python bot.py                  # Dry run with default config
    python bot.py --live           # Live trading (requires API key!)
    python bot.py --dashboard      # Start with web dashboard
"""

from __future__ import annotations
import argparse
import json
import logging
import signal
import sys
import time
import threading
from datetime import datetime

import pandas as pd

from strategy.entry import EntryLogic
from strategy.exit_manager import ExitManager, ExitAction, Position
from strategy.structure import BOSCHOCHDetector
from strategy.zones import SupplyDemandZones
from strategy.mtf import MTFFilter
from strategy.orderbook import OrderBookIntelligence
from strategy.chop_filter import ChopFilter
from exchange.dry_run import DryRunEngine
from utils.risk_manager import RiskManager
from utils.learning_brain import LearningBrain
from utils.market_hours import MarketHoursChecker
from utils.news_sentiment import NewsSentiment
from utils.google_news import GoogleNewsSentiment
from strategy.volatility_regime import VolatilityRegimeDetector
from strategy.volume_gate import VolumeGate
from strategy.key_levels import KeyLevelDetector
from strategy.market_regime import MarketRegimeGate
from utils.telegram_alerts import alert_trade_open, alert_trade_close, alert_daily_summary

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-18s | %(levelname)-5s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mahmudbot")

# ── Graceful shutdown ─────────────────────────────────────────────────
_running = True

def _shutdown(sig, frame):
    global _running
    logger.info("Shutdown signal received. Closing gracefully...")
    _running = False

signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


class MahmudBot:
    """Main bot orchestrator."""

    def __init__(self, config: dict):
        self.config = config
        self.dry_run = config.get("dry_run", True)
        self.interval = config.get("signal_candle_interval", "5m")
        self.exit_check_interval = config.get("exit_check_interval", 2)

        # Core components
        self.entry_logic = EntryLogic(config)
        self.exit_manager = ExitManager(config)
        self.risk_manager = RiskManager(config)
        self.learning_brain = LearningBrain(config.get("learnings_file", "learnings.json"))
        self.market_hours = MarketHoursChecker(config.get("market_hours", {}))

        # Shared Hyperliquid client for data fetching
        from exchange.client import HyperliquidClient
        self._hl_client = HyperliquidClient(config)

        # v2.5+ Intelligence layers
        self.chop_filter = ChopFilter(config)
        self.mtf_filter = MTFFilter(config, hl_client=self._hl_client)
        self.orderbook = OrderBookIntelligence(config, hl_client=self._hl_client)
        self.sentiment = NewsSentiment(config, hl_client=self._hl_client)
        self.google_news = GoogleNewsSentiment(config.get("google_news", {"enabled": True}))
        self.regime_detector = VolatilityRegimeDetector(config.get("volatility_regime", {"enabled": True}))
        self.volume_gate = VolumeGate(config)
        self.key_levels = KeyLevelDetector(config, hl_client=self._hl_client)
        self.market_regime = MarketRegimeGate(config)   # v3.0: Panic/Rally/Cascade

        chop_status = "ON" if config.get("chop_filter", {}).get("enabled", True) else "OFF"
        mtf_status = "ON" if config.get("mtf", {}).get("enabled", True) else "OFF"
        ob_status = "ON" if config.get("orderbook", {}).get("enabled", True) else "OFF"
        sent_status = "ON" if config.get("sentiment", {}).get("enabled", True) else "OFF"
        news_status = "ON" if config.get("google_news", {}).get("enabled", True) else "OFF"
        vg_status = "ON" if config.get("volume_gate", {}).get("enabled", True) else "OFF"
        kl_status = "ON" if config.get("key_levels", {}).get("enabled", True) else "OFF"
        logger.info(f"🧠 Intelligence layers: Chop={chop_status} | MTF={mtf_status} | WOBI={ob_status} | Sentiment={sent_status} | News={news_status} | VolGate={vg_status} | KeyLvl={kl_status}")

        # Execution engine
        if self.dry_run:
            self.engine = DryRunEngine(config)
            logger.info("🔒 DRY RUN mode — no real money at risk")
        else:
            from exchange.client import HyperliquidClient
            self.client = HyperliquidClient(config)
            self.engine = None  # Live trades go through client
            logger.info("🔴 LIVE mode — real trades will be executed!")

        # Market data cache: {ticker: DataFrame}
        self._candle_cache: dict[str, pd.DataFrame] = {}
        self._zone_cache: dict[str, list] = {}
        self._last_zone_update: dict[str, float] = {}

        # Enabled markets
        self.markets = {
            sym: cfg for sym, cfg in config.get("markets", {}).items()
            if cfg.get("enabled", False)
        }

        logger.info(f"📊 Scanning {len(self.markets)} markets: {', '.join(self.markets.keys())}")

    def _fetch_candles(self, ticker: str) -> pd.DataFrame | None:
        """Fetch recent candles for a market."""
        try:
            return self._hl_client.get_candles(ticker, interval=self.interval, limit=301)
        except Exception as e:
            logger.error(f"Failed to fetch candles for {ticker}: {e}")
            return None

    def _get_current_price(self, ticker: str) -> float | None:
        """Get current price for a ticker."""
        try:
            return self._hl_client.get_price(ticker)
        except Exception as e:
            logger.debug(f"Price fetch failed for {ticker}: {e}")
            return None

    def _update_zones(self, ticker: str, df: pd.DataFrame):
        """Update S/D zones periodically."""
        now = time.time()
        last = self._last_zone_update.get(ticker, 0)
        if now - last < 300:  # Every 5 minutes
            return

        try:
            detector = BOSCHOCHDetector(swing_lookback=5)
            zone_builder = SupplyDemandZones()
            events = detector.detect(df.iloc[-100:])
            self._zone_cache[ticker] = zone_builder.build_zones(df.iloc[-100:], events)
            self._last_zone_update[ticker] = now
        except Exception as e:
            logger.debug(f"Zone update failed for {ticker}: {e}")

    def _day_sizing_multiplier(self) -> float:
        """Get position sizing multiplier based on day of week."""
        dow = datetime.utcnow().weekday()
        return self.config.get("day_sizing", {}).get(str(dow), 1.0)

    def scan_markets(self):
        """Scan all enabled markets for entry signals."""
        from datetime import datetime, timezone

        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour

        # London Close blackout: 15:00-16:00 UTC
        # Zoran data: 9% WR, -$1,526 in this hour alone
        if hour == 15:
            logger.debug("[BLACKOUT] London Close hour (15:00-16:00 UTC) — skipping all signals")
            return

        # US Open chaos: 13:30-14:30 UTC (Z.M rule)
        if hour == 13 and now_utc.minute >= 30:
            logger.debug("[BLACKOUT] US Open first 30min (13:30-14:00 UTC) — skipping")
            return
        if hour == 14 and now_utc.minute < 30:
            logger.debug("[BLACKOUT] US Open (14:00-14:30 UTC) — skipping")
            return

        # Dead zone blackouts (our data: consistent losers)
        # 07:00 UTC = -$40.59, 25% WR (European open noise)
        # 01:00 UTC = -$15.86, 17% WR (Asian dead zone)
        # 20:00 UTC = -$8.58, 19% WR (US close chop)
        if hour in (7, 1, 20):
            logger.debug(f"[BLACKOUT] Dead zone hour {hour:02d}:00 UTC — skipping signals")
            return

        # No new entries within 5 min of funding tick (Deep Research rec #2)
        # Funding is hourly at :00. Entries after :55 can never reach TP before forced close.
        minutes_to_hour = 60 - now_utc.minute if now_utc.minute > 0 else 0
        if 0 < minutes_to_hour <= 5:
            logger.debug(f"[FUNDING GUARD] No new entries {minutes_to_hour}min before funding tick")
            return

        for ticker, market_cfg in self.markets.items():
            asset_class = market_cfg.get("asset_class", "crypto")

            # Check market hours
            if not self.market_hours.is_open(ticker, asset_class):
                continue

            # Risk checks
            open_pos_list = list(self.engine.open_positions.values()) if self.dry_run else []
            allowed, reason = self.risk_manager.can_open_position(
                ticker=ticker,
                direction="",  # Not known yet, will recheck after signal
                asset_class=asset_class,
                open_positions=open_pos_list,
            )
            if not allowed:
                logger.debug(f"Risk blocked {ticker}: {reason}")
                continue

            # Fetch candles
            df = self._fetch_candles(ticker)
            if df is None or len(df) < 250:
                continue

            self._candle_cache[ticker] = df

            # ── v2.6 Layer: Volatility Regime Detection ──
            regime = self.regime_detector.detect(ticker, df)
            regime_size_mult = regime.size_multiplier

            # In STORM mode, raise minimum score
            if regime.min_score_override and regime.regime.value == "STORM":
                logger.info(f"🌪️ STORM regime on {ticker} — min score raised to {regime.min_score_override}, size at {regime.size_multiplier:.0%}")

            # ── v3.0 Layer: Feed market condition into global regime gate ──
            from strategy.ema import EMACalculator as _EMACalc
            _ema_tmp = _EMACalc()
            _df_tmp = _ema_tmp.calculate(df.copy())
            _ema_tmp_vals = _ema_tmp.latest(_df_tmp)
            _price_tmp = float(df["close"].iloc[-1])
            _likely_dir_tmp = "LONG" if _ema_tmp_vals.is_bullish(_price_tmp) else "SHORT"
            _ob_tmp = self.orderbook.analyze(ticker)
            _wobi_tmp = _ob_tmp.wobi if _ob_tmp else 0.0
            _htf_bear_tmp = (_likely_dir_tmp == "SHORT")
            self.market_regime.update_market_condition(
                ticker=ticker,
                regime_value=regime.regime.value,
                wobi_score=_wobi_tmp,
                htf_bear=_htf_bear_tmp,
            )

            # Update zones
            self._update_zones(ticker, df)
            zones = self._zone_cache.get(ticker, [])

            # ── v2.5+ Layer 0: Chop Filter (before anything else) ────
            chop_result = self.chop_filter.check(df)
            if chop_result.is_choppy:
                logger.debug(f"Chop filter blocked {ticker}: {chop_result.summary()}")
                self._chop_blocked += 1
                continue

            # ── v2.7 Layer 0b: Volume Gate (Zoran rule: no volume = no trade) ──
            vol_gate_result = self.volume_gate.check(df)
            if not vol_gate_result.allowed:
                logger.debug(f"Volume gate blocked {ticker}: {vol_gate_result.summary()}")
                self._vol_blocked += 1
                continue

            # ── v2.5+ Layer 1: Multi-Timeframe Filter ────────────────
            # Quick pre-check: determine likely direction from 200 EMA before full eval
            from strategy.ema import EMACalculator
            _ema_calc = EMACalculator()
            _df_ema = _ema_calc.calculate(df.copy())
            _ema_vals = _ema_calc.latest(_df_ema)
            price = float(df["close"].iloc[-1])
            likely_direction = "LONG" if _ema_vals.is_bullish(price) else "SHORT"

            mtf_result = self.mtf_filter.check(ticker, likely_direction)
            if not mtf_result.allowed:
                logger.debug(f"MTF blocked {ticker} {likely_direction}: {mtf_result.reason}")
                self._mtf_blocked += 1
                continue

            # ── v2.6 Layer: Google News Sentiment (BLOCK POWER) ──
            news_blocked, news_reason = self.google_news.should_block(ticker, likely_direction)
            if news_blocked:
                logger.info(f"📰 NEWS blocked {ticker} {likely_direction}: {news_reason}")
                continue

            # ── v2.5+ Layer 2: Order Book Intelligence (VETO POWER) ──
            wobi_score, wobi_reason, wobi_vetoed = self.orderbook.get_score(ticker, likely_direction)
            if wobi_vetoed:
                logger.info(f"📖 WOBI VETO {ticker} {likely_direction}: {wobi_reason}")
                self._wobi_vetoed += 1
                continue

            # ── v2.5+ Layer 3: Sentiment ──────────────────────────────
            sentiment_score, sentiment_reason = self.sentiment.get_score(ticker, likely_direction)

            # Check for entry (with WOBI + sentiment scores injected)
            try:
                signal = self.entry_logic.evaluate(
                    df, ticker, zones,
                    wobi_score=wobi_score,
                    wobi_reason=wobi_reason,
                    sentiment_score=sentiment_score,
                    sentiment_reason=sentiment_reason,
                )
            except Exception as e:
                logger.debug(f"Entry eval error for {ticker}: {e}")
                continue

            if signal.valid:
                # ── v3.0 Layer: Global Regime Gate (Panic/Rally/Cascade) ──
                regime_allowed, regime_reason = self.market_regime.can_trade(ticker, signal.direction)
                if not regime_allowed:
                    logger.info(f"🌍 REGIME GATE blocked {ticker} {signal.direction}: {regime_reason}")
                    continue

                # Apply regime score bonus (rally/panic boosters)
                regime_bonus = self.market_regime.get_score_bonus(signal.direction)
                if regime_bonus:
                    signal.score += regime_bonus
                    signal.score_breakdown["regime_bonus"] = regime_bonus

                # ── v3.0 Layer: Learning Hard Veto ──
                if self.learning_brain.is_hard_vetoed(ticker, signal.entry_pattern):
                    logger.info(f"🚫 LEARN VETO blocked {ticker} {signal.direction} pattern={signal.entry_pattern}")
                    continue

                # ── v2.7 Layer: Key Level Score Bonus ──
                kl_result = self.key_levels.score_entry(ticker, signal.entry_price, signal.direction)
                if kl_result.score_bonus > 0:
                    signal.score += kl_result.score_bonus
                    signal.score_breakdown["key_level"] = kl_result.score_bonus
                    signal.checks_passed["key_level"] = kl_result.reason
                    logger.info(f"🔑 Key level bonus +{kl_result.score_bonus} for {ticker}: {kl_result.reason}")

                # Check storm override on min score
                effective_min_score = self.config.get("scoring", {}).get("min_score", 6)
                if regime.min_score_override and regime.regime.value == "STORM":
                    effective_min_score = regime.min_score_override
                if signal.score < effective_min_score:
                    logger.debug(f"Score {signal.score} below min {effective_min_score} for {ticker} (regime: {regime.regime.value})")
                    continue

                leverage = market_cfg.get("leverage", 10)
                size_mult = self._day_sizing_multiplier() * regime_size_mult

                # Build WOBI display
                ob_signal = self.orderbook.analyze(ticker)
                wobi_str = f"{ob_signal.smoothed_wobi:+.3f}" if ob_signal else "N/A"
                mtf_str = f"{mtf_result.consensus_direction or 'N/A'} ({mtf_result.agreement_count}/{len(self.mtf_filter.higher_timeframes)})"

                logger.info(
                    f"\n{'='*50}\n"
                    f"🎯 SIGNAL: {signal.direction} {ticker}\n"
                    f"   Price:  {signal.entry_price:.4f}\n"
                    f"   Score:  {signal.score} (WOBI:{signal.wobi_score} Sent:{signal.sentiment_score})\n"
                    f"   Prob:   {signal.confidence:.1%}\n"
                    f"   Volume: {signal.volume_signal.strength if signal.volume_signal else 'N/A'}\n"
                    f"   MTF:    {mtf_str}\n"
                    f"   WOBI:   {wobi_str}\n"
                    f"{'='*50}"
                )

                if self.dry_run:
                    pos = self.engine.open_position(
                        ticker=ticker,
                        direction=signal.direction,
                        entry_price=signal.entry_price,
                        leverage=leverage,
                        size_multiplier=size_mult,
                        score=signal.score,
                        probability=signal.confidence,
                        pattern=signal.entry_pattern,
                    )
                    if pos:
                        alert_trade_open(
                            ticker=ticker,
                            direction=signal.direction,
                            entry_price=signal.entry_price,
                            size_usd=self.config.get("bet_size", 10) * size_mult,
                            leverage=leverage,
                            score=signal.score,
                            probability=signal.confidence,
                            mtf_consensus=mtf_result.consensus_direction or "",
                            wobi=ob_signal.wobi if ob_signal else 0.0,
                            sentiment=self.sentiment._signal.overall_bias if self.sentiment._signal else "",
                        )
                else:
                    # Live order placement
                    self.client.place_order(
                        ticker=ticker,
                        direction=signal.direction,
                        size_usd=self.config.get("bet_size", 10) * size_mult,
                        leverage=leverage,
                    )

    def manage_exits(self):
        """Check all open positions for exit conditions."""
        if not self.dry_run:
            return  # Live exits handled by exchange SL/TP orders

        positions = list(self.engine.open_positions.values())
        for pos in positions:
            price = self._get_current_price(pos.ticker)
            if price is None:
                # Use cached candle close
                cached = self._candle_cache.get(pos.ticker)
                if cached is not None and len(cached) > 0:
                    price = float(cached["close"].iloc[-1])
                else:
                    continue

            action = self.exit_manager.check(pos, price)

            if action.action == "CLOSE_FULL":
                record = self.engine.close_position(
                    pos.id, price, action.reason, fraction=1.0
                )
                if record:
                    sl_hit = record.pnl_usd < 0
                    self.learning_brain.record_trade(
                        ticker=record.ticker,
                        direction=record.direction,
                        pnl_usd=record.pnl_usd,
                        pnl_pct=record.pnl_pct,
                        sl_hit=sl_hit,
                        pattern=getattr(pos, 'entry_pattern', ''),
                        score=getattr(pos, 'entry_score', 0),
                        rsi_at_entry=getattr(pos, 'entry_rsi', 50.0),
                    )
                    # v3.0: Feed SL hits into cascade tracker
                    if sl_hit and not getattr(pos, 'be_triggered', False):
                        self.market_regime.record_sl_hit(record.direction)
                    logger.info(f"📕 Closed: {record.ticker} {record.direction} | P&L: {record.pnl_pct:+.1f}% (${record.pnl_usd:+.2f})")
                    alert_trade_close(
                        ticker=record.ticker,
                        direction=record.direction,
                        entry_price=record.entry_price,
                        exit_price=record.exit_price,
                        pnl_pct=record.pnl_pct,
                        pnl_usd=record.pnl_usd,
                        reason=record.exit_reason,
                        duration_min=record.duration_minutes,
                    )

            # v2.5: No partial closes, no SL moves. Clean SL/TP only.

    def print_status(self):
        """Print current bot status."""
        if self.dry_run:
            stats = self.engine.get_stats()
            open_pos = len(self.engine.open_positions)
            logger.info(
                f"📊 Equity: ${stats['equity']:.2f} | "
                f"P&L: ${stats['total_pnl']:+.2f} | "
                f"Today: ${stats['daily_pnl']:+.2f} | "
                f"Trades: {stats['total_trades']} ({stats['win_rate']:.0%} WR) | "
                f"Open: {open_pos}"
            )

    def _send_30min_report(self):
        """Send 30-minute auto stats report to Telegram."""
        if not self.dry_run:
            return  # TODO: live stats

        stats = self.engine.get_stats()

        # Per-market breakdown from trade history
        per_market = {}
        for trade in self.engine.trade_history:
            t = trade.ticker
            if t not in per_market:
                per_market[t] = {"trades": 0, "pnl": 0, "wins": 0, "losses": 0}
            per_market[t]["trades"] += 1
            per_market[t]["pnl"] += trade.pnl_usd
            if trade.pnl_usd > 0:
                per_market[t]["wins"] += 1
            else:
                per_market[t]["losses"] += 1

        for t, d in per_market.items():
            d["win_rate"] = d["wins"] / d["trades"] if d["trades"] > 0 else 0
            # Direction bias from learning brain
            bias = self.learning_brain.get_direction_bias(t)
            d["bias"] = "LONG" if bias > 2 else ("SHORT" if bias < -2 else "NEUTRAL")

        from utils.telegram_alerts import alert_30min_stats
        alert_30min_stats(
            equity=stats["equity"],
            daily_pnl=stats["daily_pnl"],
            total_pnl=stats["total_pnl"],
            total_trades=stats["total_trades"],
            wins=stats["wins"],
            losses=stats["losses"],
            win_rate=stats["win_rate"],
            open_positions=stats["open_positions"],
            markets_scanned=len(self.markets),
            chop_blocked=self._chop_blocked,
            mtf_blocked=self._mtf_blocked,
            vol_blocked=self._vol_blocked,
            per_market=per_market if per_market else None,
        )
        # Reset counters
        self._chop_blocked = 0
        self._mtf_blocked = 0
        self._wobi_vetoed = 0
        self._vol_blocked = 0

    def run(self):
        """Main bot loop."""
        global _running

        logger.info("\n" + "="*60)
        logger.info("   🤖 MahmudBot v2.5 — Z.M Trading Gym Strategy")
        logger.info(f"   Mode: {'DRY RUN' if self.dry_run else '🔴 LIVE'}")
        logger.info(f"   Markets: {len(self.markets)}")
        logger.info(f"   Interval: {self.interval}")
        logger.info(f"   Bet Size: ${self.config.get('bet_size', 10)}")
        logger.info(f"   Chop Filter: 3-check ({self.chop_filter.min_triggers}/3 to block)")
        logger.info(f"   MTF: {', '.join(self.mtf_filter.higher_timeframes)} ({self.mtf_filter.min_agreement}/{len(self.mtf_filter.higher_timeframes)} agree)")
        logger.info(f"   WOBI: depth={self.orderbook.depth}, threshold=±{self.orderbook.wobi_threshold}")
        logger.info(f"   Hard Stop: {self.exit_manager.hard_stop_pct}% max loss")
        logger.info(f"   Patterns: 23 active")
        logger.info(f"   Vol Gate: min {self.volume_gate.min_ratio:.0%} of 20-candle avg")
        logger.info(f"   Key Levels: {self.key_levels.hourly_lookback} hourly candles, pivot_w={self.key_levels.pivot_window}")
        logger.info(f"   WOBI: v2.1 (anti-spoofing ON)")
        logger.info(f"   Prob Cap: 75% max (honest probability)")
        logger.info("="*60 + "\n")

        # Signal scan interval based on candle size
        interval_seconds = {
            "1m": 60, "3m": 180, "5m": 300,
            "15m": 900, "1h": 3600,
        }
        scan_interval = interval_seconds.get(self.interval, 300)
        last_scan = 0
        status_interval = 60  # Print status every 60 seconds
        last_status = 0
        report_interval = 1800  # 30-min auto stats report
        last_report = 0
        self._chop_blocked = 0
        self._mtf_blocked = 0
        self._wobi_vetoed = 0
        self._vol_blocked = 0

        while _running:
            now = time.time()

            # Signal scan on candle close
            if now - last_scan >= scan_interval:
                try:
                    self.scan_markets()
                except Exception as e:
                    logger.error(f"Scan error: {e}")
                last_scan = now

            # Exit management every 2 seconds
            try:
                self.manage_exits()
            except Exception as e:
                logger.error(f"Exit management error: {e}")

            # Periodic status
            if now - last_status >= status_interval:
                self.print_status()
                last_status = now

            # 30-min auto stats report
            if now - last_report >= report_interval:
                self._send_30min_report()
                last_report = now

            time.sleep(self.exit_check_interval)

        # Shutdown
        logger.info("\n🛑 Bot stopped.")
        if self.dry_run:
            stats = self.engine.get_stats()
            logger.info(f"Session P&L: ${stats['total_pnl']:+.2f} | Trades: {stats['total_trades']}")

        # Save learnings
        self.learning_brain.save()
        logger.info("Brain saved. See you next time. 🧠")


def main():
    parser = argparse.ArgumentParser(description="MahmudBot — Z.M Trading Bot")
    parser.add_argument("--config", default="config.json", help="Config file path")
    parser.add_argument("--live", action="store_true", help="Enable live trading (CAREFUL!)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Debug logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config = load_config(args.config)

    if args.live:
        config["dry_run"] = False
        if not config.get("private_key"):
            logger.error("❌ Live mode requires private_key in config.json!")
            sys.exit(1)
        logger.warning("⚠️  LIVE MODE — Real money at risk! Press Ctrl+C within 5 seconds to abort.")
        time.sleep(5)

    bot = MahmudBot(config)
    bot.run()


if __name__ == "__main__":
    main()
