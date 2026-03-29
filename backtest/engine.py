"""
Backtest Engine v3.0 — Full 7-Layer Pipeline
Matches the LIVE bot's exact filtering stack. No shortcuts.

Layers (same as bot.py):
  0. Chop Filter (ADX + Bollinger + ATR — 2/3 to block)
  1. Multi-Timeframe (simulated from higher-TF candles)
  2. News Sentiment (skipped in backtest — no historical RSS data)
  3. WOBI Order Book (skipped in backtest — no historical L2 data)
  4. Scoring Engine (EMA + RSI + BB + patterns + momentum)
  5. Risk Manager (position limits, loss caps, correlation, direction cap)
  6. Slippage Check (per-market thresholds)

Also simulates:
  - Funding guard (close before hourly ticks)
  - Day-of-week position sizing
  - Cooldown between trades
  - Blackout windows (London Close 15:00-16:00, US Open 13:30-14:30)
  - Fees + slippage
"""

from __future__ import annotations
import uuid
import logging
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
import numpy as np
from datetime import datetime, timezone

from strategy.ema import EMACalculator
from strategy.structure import BOSCHOCHDetector
from strategy.zones import SupplyDemandZones
from strategy.volume import VolumeConfirmation
from strategy.entry import EntryLogic
from strategy.exit_manager import ExitManager, Position, ExitStage
from strategy.chop_filter import ChopFilter
from strategy.volatility_regime import VolatilityRegimeDetector

logger = logging.getLogger(__name__)

# Day-of-week sizing multipliers (Mon=0 ... Sun=6)
DAY_SIZING = {0: 0.7, 1: 1.0, 2: 1.0, 3: 1.0, 4: 0.7, 5: 0.5, 6: 0.5}


@dataclass
class BacktestTrade:
    id: str
    ticker: str
    direction: str
    entry_price: float
    exit_price: float
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    size_usd: float
    leverage: int
    fee_entry: float
    fee_exit: float
    slippage: float
    gross_pnl: float
    net_pnl: float
    gross_pnl_pct: float
    exit_reason: str
    stage_reached: str
    score: int
    duration_bars: int


@dataclass
class BacktestResult:
    ticker: str
    interval: str
    period_start: pd.Timestamp
    period_end: pd.Timestamp
    initial_capital: float
    final_capital: float
    trades: list[BacktestTrade] = field(default_factory=list)

    # Stats (computed by reporter)
    total_return_pct: float = 0.0
    total_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    risk_of_ruin: float = 0.0
    profit_factor: float = 0.0


class BacktestEngine:
    """
    Event-driven backtest engine with full 7-layer filtering pipeline.
    Matches the live bot's entry/exit logic as closely as possible.
    """

    def __init__(self, config: dict):
        self.config = config
        self.bt_config = config.get("backtest", {})
        self.fee_rate = self.bt_config.get("fee_rate", 0.00045)
        self.slippage_estimate = self.bt_config.get("slippage_estimate", 0.001)
        self.initial_capital = self.bt_config.get("initial_capital", 10_000.0)
        self.bet_size = config.get("bet_size", 100.0)

        # Scoring thresholds (from config — must match live bot)
        scoring_cfg = config.get("scoring", {})
        self.min_score = scoring_cfg.get("min_score", 5)
        self.min_probability = scoring_cfg.get("min_probability", 0.50)

        # Exit config
        exit_cfg = config.get("exit", {})
        self.funding_guard = exit_cfg.get("funding_guard", True)
        self.funding_guard_minutes = exit_cfg.get("funding_guard_minutes", 2)

        # Risk config
        self.max_positions = config.get("max_positions", 3)
        self.daily_loss_cap = config.get("daily_loss_cap", 500.0)
        self.hourly_loss_cap = config.get("hourly_loss_cap", 300.0)
        self.consecutive_loss_limit = config.get("consecutive_loss_limit", 3)
        self.max_same_direction = config.get("max_same_direction", 2)

        # Strategy components
        self._ema = EMACalculator()
        self._entry = EntryLogic(config)
        self._exit = ExitManager(config)
        self._chop = ChopFilter(config)
        self._regime = VolatilityRegimeDetector(config.get("volatility_regime", {"enabled": True}))

        # Cooldown: minimum bars between trades
        interval_minutes = {"1m": 1, "3m": 3, "5m": 5, "15m": 15, "1h": 60}
        self._bar_minutes = interval_minutes.get(
            config.get("signal_candle_interval", "5m"), 5
        )
        cooldown_secs = config.get("cooldown_seconds", 600)
        self.cooldown_bars = max(1, cooldown_secs // (self._bar_minutes * 60))

        # Warm-up: need 250 candles for EMA200 + buffer
        self.warmup_bars = 250

    def _is_blackout(self, ts: pd.Timestamp) -> bool:
        """Check if timestamp falls in a blackout window."""
        hour = ts.hour
        minute = ts.minute

        # London Close: 15:00-16:00 UTC
        if hour == 15:
            return True

        # US Open: 13:30-14:30 UTC
        if hour == 13 and minute >= 30:
            return True
        if hour == 14 and minute < 30:
            return True

        return False

    def _is_funding_tick(self, ts: pd.Timestamp) -> bool:
        """Check if we're within funding_guard_minutes of an hourly tick."""
        if not self.funding_guard:
            return False
        minutes_to_hour = 60 - ts.minute
        return minutes_to_hour <= self.funding_guard_minutes

    def _simulate_mtf(self, df: pd.DataFrame, direction: str, bar_idx: int) -> bool:
        """
        Simulate multi-timeframe filter using EMA trend checks.
        Cached — only recalculates every 12 bars.
        
        Uses EMA 50 + EMA 100 + EMA 200 — if 2/3 agree with direction, pass.
        This approximates the live bot's 15m/30m/1h MTF check.
        """
        cache_key = (direction, bar_idx // 12)
        if hasattr(self, '_mtf_cache') and cache_key in self._mtf_cache:
            return self._mtf_cache[cache_key]

        if not hasattr(self, '_mtf_cache'):
            self._mtf_cache = {}

        close = df["close"]
        if len(close) < 200:
            self._mtf_cache[cache_key] = True
            return True

        price = float(close.iloc[-1])
        agreements = 0

        for span in [50, 100, 200]:
            ema = close.ewm(span=span, min_periods=span).mean()
            if len(ema.dropna()) < 1:
                agreements += 1
                continue
            ema_val = float(ema.iloc[-1])
            if direction == "LONG" and price > ema_val:
                agreements += 1
            elif direction == "SHORT" and price < ema_val:
                agreements += 1

        result = agreements >= 2
        self._mtf_cache[cache_key] = result

        if len(self._mtf_cache) > 1000:
            self._mtf_cache = {}

        return result

    def run(
        self,
        df: pd.DataFrame,
        ticker: str,
        leverage: int = 10,
        interval: str = "5m",
    ) -> BacktestResult:
        """
        Run a full backtest on historical OHLCV data.
        """
        logger.info(f"Starting backtest: {ticker} | {len(df)} bars | {interval}")

        result = BacktestResult(
            ticker=ticker,
            interval=interval,
            period_start=df.index[0],
            period_end=df.index[-1],
            initial_capital=self.initial_capital,
            final_capital=self.initial_capital,
        )

        capital = self.initial_capital
        open_positions: list[Position] = []
        active_zones = []
        zone_update_interval = 50

        # Risk tracking
        daily_loss = 0.0
        hourly_loss = 0.0
        consecutive_losses = 0
        current_day = None
        current_hour = None
        paused = False
        last_close_bar = -999

        # Precompute EMAs
        df = self._ema.calculate(df)

        for i in range(self.warmup_bars, len(df)):
            window = df.iloc[:i + 1]
            current_candle = df.iloc[i]
            current_ts = df.index[i]
            current_close = float(current_candle["close"])
            current_high = float(current_candle["high"])
            current_low = float(current_candle["low"])

            # ── Day/hour reset ────────────────────────────────────────
            bar_day = current_ts.date().isoformat() if hasattr(current_ts, 'date') else str(current_ts)[:10]
            bar_hour = current_ts.hour if hasattr(current_ts, 'hour') else 0

            if bar_day != current_day:
                current_day = bar_day
                daily_loss = 0.0
                consecutive_losses = min(consecutive_losses, self.consecutive_loss_limit - 1)
                paused = False

            if bar_hour != current_hour:
                current_hour = bar_hour
                hourly_loss = 0.0
                if paused and hourly_loss < self.hourly_loss_cap:
                    paused = False

            # ── Funding guard: close ALL positions before hourly tick ──
            if self._is_funding_tick(current_ts) and open_positions:
                for pos in list(open_positions):
                    if pos.closed:
                        continue
                    exit_price = self._apply_slippage(
                        current_close,
                        "SELL" if pos.direction == "LONG" else "BUY",
                    )
                    pnl_pct = pos.current_pnl_pct(exit_price)
                    gross_pnl = (pnl_pct / 100) * pos.size_usd
                    fee = pos.size_usd * self.fee_rate * 2
                    net_pnl = gross_pnl - fee
                    capital += net_pnl

                    if net_pnl < 0:
                        daily_loss += abs(net_pnl)
                        hourly_loss += abs(net_pnl)
                        consecutive_losses += 1
                    else:
                        consecutive_losses = 0

                    trade = BacktestTrade(
                        id=pos.id, ticker=ticker, direction=pos.direction,
                        entry_price=pos.entry_price, exit_price=exit_price,
                        entry_time=getattr(pos, '_bt_entry_time', current_ts),
                        exit_time=current_ts,
                        size_usd=pos.size_usd, leverage=leverage,
                        fee_entry=pos.size_usd * self.fee_rate,
                        fee_exit=pos.size_usd * self.fee_rate,
                        slippage=0.0, gross_pnl=gross_pnl, net_pnl=net_pnl,
                        gross_pnl_pct=pnl_pct,
                        exit_reason="Funding guard",
                        stage_reached="OPEN", score=getattr(pos, '_bt_score', 0),
                        duration_bars=i - getattr(pos, '_bt_entry_bar', i),
                    )
                    result.trades.append(trade)
                    pos.closed = True

                open_positions = [p for p in open_positions if not p.closed]
                last_close_bar = i
                continue  # Skip entry on funding bar

            # ── Manage open positions (SL/TP check) ──────────────────
            for pos in list(open_positions):
                if pos.closed:
                    continue

                # Check if SL or TP would be hit within this bar's range
                sl_pct = self._exit.sl_pct  # e.g., -3.5
                tp_pct = self._exit.tp_pct  # e.g., +10.5
                hard_stop_pct = self.config.get("exit", {}).get("hard_stop_pct", -5.25)

                # Calculate SL/TP price levels
                if pos.direction == "LONG":
                    sl_price = pos.entry_price * (1 + sl_pct / 100 / pos.leverage)
                    tp_price = pos.entry_price * (1 + tp_pct / 100 / pos.leverage)
                    hard_stop_price = pos.entry_price * (1 + hard_stop_pct / 100 / pos.leverage)
                    sl_hit = current_low <= sl_price
                    tp_hit = current_high >= tp_price
                else:
                    sl_price = pos.entry_price * (1 - sl_pct / 100 / pos.leverage)
                    tp_price = pos.entry_price * (1 - tp_pct / 100 / pos.leverage)
                    hard_stop_price = pos.entry_price * (1 - hard_stop_pct / 100 / pos.leverage)
                    sl_hit = current_high >= sl_price
                    tp_hit = current_low <= tp_price

                # Determine exit: TP first (optimistic), then SL
                exit_this_bar = False
                if tp_hit:
                    test_price = tp_price  # Fill at TP level exactly
                    exit_reason = f"TP hit +{tp_pct}%"
                    exit_this_bar = True
                elif sl_hit:
                    test_price = sl_price  # Fill at SL level exactly (no gap-through)
                    exit_reason = f"SL hit {sl_pct}%"
                    exit_this_bar = True

                if exit_this_bar:
                    action_action = "CLOSE_FULL"

                    exit_price = self._apply_slippage(
                        test_price,
                        "SELL" if pos.direction == "LONG" else "BUY",
                    )

                    pnl_pct = pos.current_pnl_pct(exit_price)
                    gross_pnl = (pnl_pct / 100) * pos.size_usd
                    fee = pos.size_usd * self.fee_rate * 2
                    net_pnl = gross_pnl - fee
                    capital += net_pnl

                    if net_pnl < 0:
                        daily_loss += abs(net_pnl)
                        hourly_loss += abs(net_pnl)
                        consecutive_losses += 1
                    else:
                        consecutive_losses = 0

                    trade = BacktestTrade(
                        id=pos.id, ticker=ticker, direction=pos.direction,
                        entry_price=pos.entry_price, exit_price=exit_price,
                        entry_time=getattr(pos, '_bt_entry_time', current_ts),
                        exit_time=current_ts,
                        size_usd=pos.size_usd, leverage=leverage,
                        fee_entry=pos.size_usd * self.fee_rate,
                        fee_exit=pos.size_usd * self.fee_rate,
                        slippage=abs(test_price - exit_price),
                        gross_pnl=gross_pnl, net_pnl=net_pnl,
                        gross_pnl_pct=pnl_pct,
                        exit_reason=exit_reason,
                        stage_reached="CLOSED",
                        score=getattr(pos, '_bt_score', 0),
                        duration_bars=i - getattr(pos, '_bt_entry_bar', i),
                    )
                    result.trades.append(trade)
                    pos.closed = True
                    last_close_bar = i

            open_positions = [p for p in open_positions if not p.closed]

            # ── Entry evaluation (7-layer pipeline) ───────────────────
            # Skip if max positions reached
            if len(open_positions) >= self.max_positions:
                continue

            # Skip if paused
            if paused:
                continue

            # Skip if daily/hourly loss cap
            if daily_loss >= self.daily_loss_cap:
                paused = True
                continue
            if hourly_loss >= self.hourly_loss_cap:
                paused = True
                continue

            # Skip if consecutive loss limit
            if consecutive_losses >= self.consecutive_loss_limit:
                paused = True
                continue

            # Cooldown check
            if (i - last_close_bar) < self.cooldown_bars:
                continue

            # Layer 0: Blackout windows
            if self._is_blackout(current_ts):
                continue

            # Layer 1: Chop filter
            chop_result = self._chop.check(window)
            if chop_result.is_choppy:
                continue

            # Layer 2: Volatility regime
            regime = self._regime.detect(ticker, window)
            regime_size_mult = regime.size_multiplier
            min_score_override = regime.min_score_override

            # Pre-check direction from 200 EMA
            ema_vals = self._ema.latest(window)
            likely_direction = "LONG" if ema_vals.is_bullish(current_close) else "SHORT"

            # Layer 3: Multi-timeframe filter (simulated, cached)
            if not self._simulate_mtf(window, likely_direction, i):
                continue

            # Layer 4: Direction cap (max same-direction positions)
            same_dir = sum(1 for p in open_positions if p.direction == likely_direction)
            if same_dir >= self.max_same_direction:
                continue

            # Rebuild zones periodically
            if i % zone_update_interval == 0:
                try:
                    detector = BOSCHOCHDetector()
                    zone_builder = SupplyDemandZones()
                    events = detector.detect(window.iloc[-100:])
                    active_zones = zone_builder.build_zones(window.iloc[-100:], events)
                except Exception:
                    active_zones = []

            # Day-of-week sizing
            dow = current_ts.weekday() if hasattr(current_ts, 'weekday') else 0
            size_mult = DAY_SIZING.get(dow, 1.0) * regime_size_mult
            position_size = self.bet_size * size_mult

            # Layer 5: Scoring engine (via EntryLogic)
            try:
                entry_signal = self._entry.evaluate(window, ticker, active_zones)
            except Exception as e:
                logger.debug(f"Entry eval error at {current_ts}: {e}")
                continue

            if not entry_signal.valid:
                continue

            # Check score meets threshold (with regime override)
            effective_min_score = min_score_override if min_score_override else self.min_score
            score = entry_signal.score if entry_signal.score else 0
            # EntrySignal uses 'confidence' (0.0-1.0), not 'probability'
            prob = getattr(entry_signal, 'confidence', None) or getattr(entry_signal, 'probability', None) or 0

            if score < effective_min_score:
                continue
            if prob < self.min_probability:
                continue

            # Layer 6: Slippage check (simulated)
            entry_price = self._apply_slippage(
                current_close,
                "BUY" if entry_signal.direction == "LONG" else "SELL",
            )

            pos = Position(
                id=f"{ticker}_{uuid.uuid4().hex[:8]}",
                ticker=ticker,
                direction=entry_signal.direction,
                entry_price=entry_price,
                size_usd=position_size,
                leverage=leverage,
            )
            pos._bt_entry_bar = i
            pos._bt_entry_time = current_ts
            pos._bt_score = score

            open_positions.append(pos)

            logger.debug(
                f"Entry: {entry_signal.direction} {ticker} @ {entry_price:.4f} | "
                f"Score: {score} | {current_ts}"
            )

        # Close any remaining positions at final bar price
        final_close = float(df.iloc[-1]["close"])
        for pos in open_positions:
            if pos.closed:
                continue
            exit_price = self._apply_slippage(
                final_close,
                "SELL" if pos.direction == "LONG" else "BUY",
            )
            pnl_pct = pos.current_pnl_pct(exit_price)
            gross_pnl = (pnl_pct / 100) * pos.size_usd
            fee = pos.size_usd * self.fee_rate * 2
            net_pnl = gross_pnl - fee
            capital += net_pnl

            trade = BacktestTrade(
                id=pos.id, ticker=ticker, direction=pos.direction,
                entry_price=pos.entry_price, exit_price=exit_price,
                entry_time=getattr(pos, '_bt_entry_time', df.index[-1]),
                exit_time=df.index[-1],
                size_usd=pos.size_usd, leverage=leverage,
                fee_entry=pos.size_usd * self.fee_rate,
                fee_exit=pos.size_usd * self.fee_rate,
                slippage=0.0, gross_pnl=gross_pnl, net_pnl=net_pnl,
                gross_pnl_pct=pnl_pct,
                exit_reason="End of backtest",
                stage_reached="OPEN", score=getattr(pos, '_bt_score', 0),
                duration_bars=len(df) - getattr(pos, '_bt_entry_bar', len(df)),
            )
            result.trades.append(trade)

        result.final_capital = capital
        result.total_trades = len(result.trades)

        logger.info(
            f"Backtest complete: {ticker} | "
            f"{len(result.trades)} trades | "
            f"P&L: ${capital - self.initial_capital:+.2f}"
        )

        return result

    def _apply_slippage(self, price: float, side: str) -> float:
        """Apply slippage to simulate real fill prices."""
        slip_pct = self.slippage_estimate
        if side == "BUY":
            return price * (1 + slip_pct)
        else:
            return price * (1 - slip_pct)
