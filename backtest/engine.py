"""
Backtest Engine
Runs the Z.M strategy against historical data and produces statistics.

Accounts for:
  - 0.045% taker fee per trade (entry + exit)
  - Configurable slippage estimate
  - The full 4-stage exit system
  - Day-of-week position sizing
"""

from __future__ import annotations
import uuid
import logging
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
import numpy as np
from datetime import datetime

from strategy.ema import EMACalculator
from strategy.structure import BOSCHOCHDetector
from strategy.zones import SupplyDemandZones
from strategy.volume import VolumeConfirmation
from strategy.scoring import ScoringEngine
from strategy.entry import EntryLogic
from strategy.exit_manager import ExitManager, Position, ExitStage

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
    Event-driven backtest engine.
    Iterates bar-by-bar through historical candles, applying the strategy.
    """

    def __init__(self, config: dict):
        self.config = config
        self.bt_config = config.get("backtest", {})
        self.fee_rate = self.bt_config.get("fee_rate", 0.00045)
        self.slippage_estimate = self.bt_config.get("slippage_estimate", 0.001)
        self.initial_capital = self.bt_config.get("initial_capital", 10_000.0)
        self.bet_size = config.get("bet_size", 10.0)

        # Strategy components
        self._ema = EMACalculator()
        self._entry = EntryLogic(config)
        self._exit = ExitManager(config)

        # Warm-up period: need at least 200 candles for EMA200
        self.warmup_bars = 250

    def run(
        self,
        df: pd.DataFrame,
        ticker: str,
        leverage: int = 10,
        interval: str = "5m",
    ) -> BacktestResult:
        """
        Run a backtest on historical OHLCV data.

        Args:
            df: Historical OHLCV DataFrame indexed by timestamp
            ticker: Market symbol
            leverage: Position leverage
            interval: Candle interval (informational)

        Returns:
            BacktestResult with all trades and statistics
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
        open_position: Optional[Position] = None
        active_zones = []
        zone_update_interval = 50  # Rebuild zones every N bars

        # Precompute EMAs for the full dataset
        df = self._ema.calculate(df)

        for i in range(self.warmup_bars, len(df)):
            window = df.iloc[:i + 1]
            current_candle = df.iloc[i]
            current_ts = df.index[i]
            current_close = float(current_candle["close"])
            current_high = float(current_candle["high"])
            current_low = float(current_candle["low"])

            # ── Manage open position ──────────────────────────────────────
            if open_position is not None and not open_position.closed:
                # Simulate intra-bar exit checking
                # Check both high and low of bar for SL/TP triggers
                for test_price in [current_low, current_high, current_close]:
                    action = self._exit.check(open_position, test_price)

                    if action.action in ("CLOSE_FULL", "CLOSE_PARTIAL"):
                        # Apply slippage to exit
                        slippage_price = self._apply_slippage(
                            test_price,
                            "SELL" if open_position.direction == "LONG" else "BUY",
                        )

                        pnl_pct = open_position.current_pnl_pct(slippage_price)
                        gross_pnl = (pnl_pct / 100) * open_position.size_usd

                        # Fees: entry + exit
                        fee_entry = open_position.size_usd * self.fee_rate
                        fee_exit = open_position.size_usd * self.fee_rate
                        net_pnl = gross_pnl - fee_entry - fee_exit

                        capital += net_pnl

                        duration_bars = i - self._entry_bar if hasattr(self, "_entry_bar") else 0

                        trade = BacktestTrade(
                            id=open_position.id,
                            ticker=ticker,
                            direction=open_position.direction,
                            entry_price=open_position.entry_price,
                            exit_price=slippage_price,
                            entry_time=self._entry_time,
                            exit_time=current_ts,
                            size_usd=open_position.size_usd,
                            leverage=leverage,
                            fee_entry=fee_entry,
                            fee_exit=fee_exit,
                            slippage=abs(test_price - slippage_price),
                            gross_pnl=gross_pnl,
                            net_pnl=net_pnl,
                            gross_pnl_pct=pnl_pct,
                            exit_reason=action.reason,
                            stage_reached=open_position.stage.value,
                            score=getattr(self, "_last_score", 0),
                            duration_bars=duration_bars,
                        )
                        result.trades.append(trade)

                        if action.action == "CLOSE_FULL":
                            open_position = None
                        else:
                            # Partial close — update remaining fraction
                            self._exit.apply_action(action, open_position, test_price)

                        break

                    elif action.action == "MOVE_SL":
                        self._exit.apply_action(action, open_position, test_price)

            # ── Look for new entry (only if no open position) ─────────────
            if open_position is None:
                # Periodically rebuild zones
                if i % zone_update_interval == 0:
                    try:
                        from strategy.structure import BOSCHOCHDetector
                        from strategy.zones import SupplyDemandZones
                        detector = BOSCHOCHDetector()
                        zone_builder = SupplyDemandZones()
                        events = detector.detect(window.iloc[-100:])  # Use last 100 bars
                        active_zones = zone_builder.build_zones(window.iloc[-100:], events)
                    except Exception:
                        active_zones = []

                # Day-of-week sizing
                dow = current_ts.weekday()
                size_mult = DAY_SIZING.get(dow, 1.0)
                position_size = self.bet_size * size_mult

                # Evaluate entry
                try:
                    entry_signal = self._entry.evaluate(window, ticker, active_zones)
                except Exception as e:
                    logger.debug(f"Entry eval error at {current_ts}: {e}")
                    continue

                if entry_signal.valid:
                    # Apply slippage to entry
                    entry_price = self._apply_slippage(
                        current_close,
                        "BUY" if entry_signal.direction == "LONG" else "SELL",
                    )

                    open_position = Position(
                        id=f"{ticker}_{uuid.uuid4().hex[:8]}",
                        ticker=ticker,
                        direction=entry_signal.direction,
                        entry_price=entry_price,
                        size_usd=position_size,
                        leverage=leverage,
                    )

                    self._entry_bar = i
                    self._entry_time = current_ts
                    self._last_score = entry_signal.score.total if entry_signal.score else 0

                    logger.debug(
                        f"Entry: {entry_signal.direction} {ticker} @ {entry_price:.4f} | "
                        f"Score: {self._last_score} | {current_ts}"
                    )

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
