"""
Backtest Reporter
Computes statistics and formats results to JSON and human-readable summary.

Statistics tracked:
  - Win rate, avg win, avg loss
  - Max drawdown
  - Sharpe ratio
  - Risk of ruin
  - Profit factor
  - Fee impact
"""

from __future__ import annotations
import json
import logging
import math
from datetime import datetime
from typing import Optional
import numpy as np
import pandas as pd

from .engine import BacktestResult, BacktestTrade

logger = logging.getLogger(__name__)


def _risk_of_ruin(win_rate: float, rr_ratio: float, risk_per_trade: float) -> float:
    """
    Kelly criterion-based risk of ruin estimate.
    
    Args:
        win_rate: 0.0 – 1.0
        rr_ratio: Average win / Average loss (reward:risk)
        risk_per_trade: Fraction of capital at risk per trade

    Returns:
        Probability of ruin (0.0 – 1.0)
    """
    if win_rate <= 0 or win_rate >= 1 or rr_ratio <= 0:
        return 1.0

    # Probability of ruin formula (simplified)
    loss_rate = 1.0 - win_rate
    try:
        # Using the geometric decline formula
        r = (loss_rate / win_rate) * (1.0 / rr_ratio)
        if r >= 1:
            return 1.0
        # Probability of ruin from N trades
        p_ruin = r ** (1.0 / risk_per_trade) if risk_per_trade > 0 else 1.0
        return min(1.0, max(0.0, p_ruin))
    except (ZeroDivisionError, ValueError, OverflowError):
        return 1.0


class BacktestReporter:
    """Compute and report backtest statistics."""

    def __init__(self, results: list[BacktestResult]):
        self.results = results

    def compute_stats(self) -> list[BacktestResult]:
        """Compute all statistics for each result."""
        for r in self.results:
            self._compute_single(r)
        return self.results

    def _compute_single(self, r: BacktestResult) -> None:
        """Compute stats for a single backtest result."""
        if not r.trades:
            return

        pnls = [t.net_pnl for t in r.trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        r.total_trades = len(pnls)
        r.win_rate = len(wins) / len(pnls) if pnls else 0.0
        r.avg_win = sum(wins) / len(wins) if wins else 0.0
        r.avg_loss = sum(losses) / len(losses) if losses else 0.0
        r.total_return_pct = (r.final_capital - r.initial_capital) / r.initial_capital * 100

        # Max drawdown
        r.max_drawdown = self._max_drawdown(pnls, r.initial_capital)

        # Sharpe ratio (assuming 0% risk-free rate, annualized from daily)
        r.sharpe_ratio = self._sharpe(pnls, r)

        # Profit factor
        total_profit = sum(wins) if wins else 0
        total_loss = abs(sum(losses)) if losses else 1
        r.profit_factor = total_profit / total_loss if total_loss > 0 else 0.0

        # Risk of ruin
        if r.avg_loss != 0 and r.avg_win != 0:
            rr_ratio = abs(r.avg_win / r.avg_loss)
            risk_per_trade = abs(r.avg_loss) / r.initial_capital
            r.risk_of_ruin = _risk_of_ruin(r.win_rate, rr_ratio, risk_per_trade)

    def _max_drawdown(self, pnls: list[float], initial: float) -> float:
        """Calculate maximum drawdown as a percentage."""
        if not pnls:
            return 0.0

        equity = initial
        peak = initial
        max_dd = 0.0

        for pnl in pnls:
            equity += pnl
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def _sharpe(self, pnls: list[float], r: BacktestResult) -> float:
        """Compute annualized Sharpe ratio."""
        if len(pnls) < 2:
            return 0.0

        pnl_arr = np.array(pnls)
        mean = np.mean(pnl_arr)
        std = np.std(pnl_arr, ddof=1)

        if std == 0:
            return 0.0

        # Estimate trades per year based on backtest period
        if r.period_start and r.period_end:
            days = (r.period_end - r.period_start).days or 1
            trades_per_day = len(pnls) / days
            ann_factor = math.sqrt(252 * trades_per_day)
        else:
            ann_factor = math.sqrt(252)

        return float((mean / std) * ann_factor)

    def to_json(self, output_path: str = "backtest_results.json") -> str:
        """Write all results to a JSON file."""
        data = []
        for r in self.results:
            trades_data = []
            for t in r.trades:
                trades_data.append({
                    "id": t.id,
                    "ticker": t.ticker,
                    "direction": t.direction,
                    "entry_price": t.entry_price,
                    "exit_price": t.exit_price,
                    "entry_time": str(t.entry_time),
                    "exit_time": str(t.exit_time),
                    "size_usd": t.size_usd,
                    "leverage": t.leverage,
                    "fee_total": t.fee_entry + t.fee_exit,
                    "slippage": t.slippage,
                    "gross_pnl": t.gross_pnl,
                    "net_pnl": t.net_pnl,
                    "pnl_pct": t.gross_pnl_pct,
                    "exit_reason": t.exit_reason,
                    "stage": t.stage_reached,
                    "score": t.score,
                    "duration_bars": t.duration_bars,
                })

            data.append({
                "ticker": r.ticker,
                "interval": r.interval,
                "period_start": str(r.period_start),
                "period_end": str(r.period_end),
                "initial_capital": r.initial_capital,
                "final_capital": r.final_capital,
                "stats": {
                    "total_return_pct": round(r.total_return_pct, 2),
                    "total_trades": r.total_trades,
                    "win_rate": round(r.win_rate * 100, 1),
                    "avg_win": round(r.avg_win, 4),
                    "avg_loss": round(r.avg_loss, 4),
                    "max_drawdown_pct": round(r.max_drawdown, 2),
                    "sharpe_ratio": round(r.sharpe_ratio, 2),
                    "profit_factor": round(r.profit_factor, 2),
                    "risk_of_ruin_pct": round(r.risk_of_ruin * 100, 1),
                },
                "trades": trades_data,
            })

        with open(output_path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info(f"Backtest results written to {output_path}")
        return output_path

    def summary(self) -> str:
        """Return a human-readable summary of all backtest results."""
        lines = [
            "=" * 70,
            "MAHMUDBOT BACKTEST RESULTS — Z.M SYSTEM v2.0",
            "=" * 70,
            "",
        ]

        for r in self.results:
            wins = [t for t in r.trades if t.net_pnl > 0]
            losses = [t for t in r.trades if t.net_pnl <= 0]
            total_fees = sum(t.fee_entry + t.fee_exit for t in r.trades)

            lines.extend([
                f"📊 {r.ticker} ({r.interval}) | {str(r.period_start)[:10]} → {str(r.period_end)[:10]}",
                f"   Trades:      {r.total_trades} total | {len(wins)} wins | {len(losses)} losses",
                f"   Win Rate:    {r.win_rate*100:.1f}%",
                f"   Avg Win:     ${r.avg_win:.2f}",
                f"   Avg Loss:    ${r.avg_loss:.2f}",
                f"   P&L:         ${r.final_capital - r.initial_capital:+.2f} ({r.total_return_pct:+.1f}%)",
                f"   Max DD:      -{r.max_drawdown:.1f}%",
                f"   Sharpe:      {r.sharpe_ratio:.2f}",
                f"   PF:          {r.profit_factor:.2f}",
                f"   Risk/Ruin:   {r.risk_of_ruin*100:.1f}%",
                f"   Fees Paid:   ${total_fees:.2f}",
                "",
            ])

        lines.append("=" * 70)
        return "\n".join(lines)

    def print_summary(self) -> None:
        """Print summary to stdout."""
        print(self.summary())
