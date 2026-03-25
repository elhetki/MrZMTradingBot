"""
Telegram Trade Alerts
Sends notifications on every trade open/close via OpenClaw's message system.
Since we're already running inside OpenClaw on Telegram, we just write to a file
that the main session picks up, or use a simple HTTP callback.

For now: writes alerts to alerts.log which Jarvis monitors and forwards.
"""

from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

ALERTS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "alerts.log")


def send_alert(message: str):
    """Write an alert to the alerts log file."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    alert_line = f"[{timestamp}] {message}\n"
    
    try:
        with open(ALERTS_FILE, "a") as f:
            f.write(alert_line)
        logger.info(f"Alert: {message}")
    except Exception as e:
        logger.error(f"Failed to write alert: {e}")


def alert_trade_open(
    ticker: str,
    direction: str,
    entry_price: float,
    size_usd: float,
    leverage: int,
    score: int,
    probability: float,
    mtf_consensus: str = "",
    wobi: float = 0.0,
    sentiment: str = "",
):
    """Alert when a new trade is opened."""
    emoji = "🟢" if direction == "LONG" else "🔴"
    lines = [
        f"{emoji} OPEN {direction} {ticker}",
        f"💰 Entry: ${entry_price:,.2f}",
        f"📊 Size: ${size_usd:.2f} @ {leverage}x",
        f"🎯 Score: {score} | Prob: {probability:.0%}",
    ]
    if mtf_consensus:
        lines.append(f"📈 MTF: {mtf_consensus}")
    if wobi != 0.0:
        lines.append(f"📖 WOBI: {wobi:+.3f}")
    if sentiment:
        lines.append(f"🌡️ Sentiment: {sentiment}")
    lines.append("🛑 SL: -3.5% | TP: +10.5% | R/R 1:3")
    send_alert("\n".join(lines))


def alert_trade_close(
    ticker: str,
    direction: str,
    entry_price: float,
    exit_price: float,
    pnl_pct: float,
    pnl_usd: float,
    reason: str,
    duration_min: float,
):
    """Alert when a trade is closed."""
    emoji = "✅" if pnl_usd > 0 else "❌"
    msg = (
        f"{emoji} CLOSE {direction} {ticker}\n"
        f"📈 Entry: ${entry_price:,.2f} → Exit: ${exit_price:,.2f}\n"
        f"💰 P&L: {pnl_pct:+.1f}% (${pnl_usd:+.2f})\n"
        f"⏱️ Duration: {duration_min:.0f}min\n"
        f"📝 {reason}"
    )
    send_alert(msg)


def alert_daily_summary(
    equity: float,
    daily_pnl: float,
    total_trades: int,
    win_rate: float,
    open_positions: int,
):
    """Daily performance summary."""
    msg = (
        f"📊 DAILY SUMMARY\n"
        f"💎 Equity: ${equity:,.2f}\n"
        f"📈 Today: ${daily_pnl:+.2f}\n"
        f"🎯 Trades: {total_trades} ({win_rate:.0%} WR)\n"
        f"📂 Open: {open_positions}"
    )
    send_alert(msg)
