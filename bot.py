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

        chop_status = "ON" if config.get("chop_filter", {}).get("enabled", True) else "OFF"
        mtf_status = "ON" if config.get("mtf", {}).get("enabled", True) else "OFF"
        ob_status = "ON" if config.get("orderbook", {}).get("enabled", True) else "OFF"
        sent_status = "ON" if config.get("sentiment", {}).get("enabled", True) else "OFF"
        logger.info(f"🧠 Intelligence layers: Chop={chop_status} | MTF={mtf_status} | WOBI={ob_status} | Sentiment={sent_status}")

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

            # Update zones
            self._update_zones(ticker, df)
            zones = self._zone_cache.get(ticker, [])

            # ── v2.5+ Layer 0: Chop Filter (before anything else) ────
            chop_result = self.chop_filter.check(df)
            if chop_result.is_choppy:
                logger.debug(f"Chop filter blocked {ticker}: {chop_result.summary()}")
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
                continue

            # ── v2.5+ Layer 2: Order Book Intelligence ────────────────
            wobi_score, wobi_reason = self.orderbook.get_score(ticker, likely_direction)

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
                leverage = market_cfg.get("leverage", 10)
                size_mult = self._day_sizing_multiplier()

                # Learning brain adjustments
                brain_adj = self.learning_brain.get_adjustments(
                    ticker,
                    signal.direction,
                    signal.score.total if signal.score else 0,
                )

                # Build WOBI display
                ob_signal = self.orderbook.analyze(ticker)
                wobi_str = f"{ob_signal.wobi:+.3f}" if ob_signal else "N/A"
                mtf_str = f"{mtf_result.consensus_direction or 'N/A'} ({mtf_result.agreement_count}/{len(self.mtf_filter.higher_timeframes)})"

                logger.info(
                    f"\n{'='*50}\n"
                    f"🎯 SIGNAL: {signal.direction} {ticker}\n"
                    f"   Price:  {signal.entry_price:.4f}\n"
                    f"   Score:  {signal.score.total if signal.score else 'N/A'} (WOBI:{signal.wobi_score} Sent:{signal.sentiment_score})\n"
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
                        score=signal.score.total if signal.score else 0,
                        probability=signal.confidence,
                    )
                    if pos:
                        alert_trade_open(
                            ticker=ticker,
                            direction=signal.direction,
                            entry_price=signal.entry_price,
                            size_usd=self.config.get("bet_size", 10) * size_mult,
                            leverage=leverage,
                            score=signal.score.total if signal.score else 0,
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
                    self.learning_brain.record_trade(
                        ticker=record.ticker,
                        direction=record.direction,
                        pnl_usd=record.pnl_usd,
                        pnl_pct=record.pnl_pct,
                        sl_hit=(record.pnl_usd < 0),
                    )
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
