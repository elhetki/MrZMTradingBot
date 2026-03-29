#!/usr/bin/env python3
"""
Pegasus Daily Intelligence Coach
Runs once daily (21:00 CET) to analyze performance, tune config, and research improvements.

Phase 1: Performance Autopsy — break down trades, find patterns
Phase 2: Self-Tuning — adjust config.json based on findings
Phase 3: Research & Edge Discovery — scan web for improvements

Output: Telegram report + config changes + research notes
"""

import json
import os
import re
import sys
import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(message)s")
logger = logging.getLogger("daily_coach")

BOT_DIR = Path(__file__).parent.parent
CONFIG_PATH = BOT_DIR / "config.json"
LEARNINGS_PATH = BOT_DIR / "learnings.json"
ALERTS_LOG = BOT_DIR / "alerts.log"
CHANGELOG_PATH = BOT_DIR / "intelligence" / "changelog.json"
TRADE_JOURNAL_PATH = BOT_DIR / "intelligence" / "trade_journal.json"


def load_config() -> dict:
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_config(config: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=4)


def load_learnings() -> dict:
    if LEARNINGS_PATH.exists():
        with open(LEARNINGS_PATH) as f:
            return json.load(f)
    return {}


def parse_alerts_log(target_date: str = None) -> list[dict]:
    """Parse alerts.log for trade data. Returns list of trade dicts."""
    if not ALERTS_LOG.exists():
        return []

    with open(ALERTS_LOG) as f:
        content = f.read()

    if target_date is None:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Parse CLOSE entries
    pattern = (
        r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] '
        r'[✅❌⚡] CLOSE (LONG|SHORT) (\w+)\n'
        r'📈 Entry: \$([\d,.]+) → Exit: \$([\d,.]+)\n'
        r'💰 P&L: ([+-][\d.]+)% \(\$([+-][\d.]+)\)\n'
        r'⏱️ Duration: (.+)\n'
        r'📝 (.+)'
    )

    trades = []
    for m in re.finditer(pattern, content):
        ts, direction, ticker, entry_px, exit_px, pnl_pct, pnl_usd, duration, reason = m.groups()
        trade = {
            "timestamp": ts,
            "date": ts[:10],
            "hour": int(ts[11:13]),
            "direction": direction,
            "ticker": ticker,
            "entry_price": float(entry_px.replace(",", "")),
            "exit_price": float(exit_px.replace(",", "")),
            "pnl_pct": float(pnl_pct),
            "pnl_usd": float(pnl_usd),
            "duration": duration,
            "exit_reason": reason,
            "won": float(pnl_usd) > 0,
        }
        trades.append(trade)

    return trades


def filter_trades(trades: list[dict], date: str) -> list[dict]:
    return [t for t in trades if t["date"] == date]


# ── Phase 1: Performance Autopsy ─────────────────────────────────────

def analyze_performance(trades: list[dict]) -> dict:
    """Deep analysis of a day's trades."""
    if not trades:
        return {"empty": True, "summary": "No trades today."}

    total_pnl = sum(t["pnl_usd"] for t in trades)
    wins = [t for t in trades if t["won"]]
    losses = [t for t in trades if not t["won"]]
    win_rate = len(wins) / len(trades) * 100

    avg_win = sum(t["pnl_usd"] for t in wins) / len(wins) if wins else 0
    avg_loss = sum(t["pnl_usd"] for t in losses) / len(losses) if losses else 0
    rr_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else float("inf")

    # Per-market breakdown
    by_market = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0, "avg_pnl": 0.0})
    for t in trades:
        m = by_market[t["ticker"]]
        m["trades"] += 1
        m["pnl"] += t["pnl_usd"]
        if t["won"]:
            m["wins"] += 1
    for mk in by_market.values():
        mk["win_rate"] = mk["wins"] / mk["trades"] * 100 if mk["trades"] else 0
        mk["avg_pnl"] = mk["pnl"] / mk["trades"]

    # Per-hour breakdown
    by_hour = defaultdict(lambda: {"trades": 0, "wins": 0, "pnl": 0.0})
    for t in trades:
        h = by_hour[t["hour"]]
        h["trades"] += 1
        h["pnl"] += t["pnl_usd"]
        if t["won"]:
            h["wins"] += 1

    # Exit reason breakdown
    exit_reasons = defaultdict(int)
    for t in trades:
        reason = t["exit_reason"]
        if "TP" in reason or "TAKE_PROFIT" in reason:
            exit_reasons["TP"] += 1
        elif "SL" in reason or "STOP_LOSS" in reason:
            exit_reasons["SL"] += 1
        elif "Funding" in reason:
            exit_reasons["FUNDING"] += 1
        elif "HARD_STOP" in reason:
            exit_reasons["HARD_STOP"] += 1
        else:
            exit_reasons["OTHER"] += 1

    # Direction analysis
    longs = [t for t in trades if t["direction"] == "LONG"]
    shorts = [t for t in trades if t["direction"] == "SHORT"]
    long_wr = sum(1 for t in longs if t["won"]) / len(longs) * 100 if longs else 0
    short_wr = sum(1 for t in shorts if t["won"]) / len(shorts) * 100 if shorts else 0
    long_pnl = sum(t["pnl_usd"] for t in longs)
    short_pnl = sum(t["pnl_usd"] for t in shorts)

    # Consecutive loss streaks
    max_streak = 0
    current_streak = 0
    for t in trades:
        if not t["won"]:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
        else:
            current_streak = 0

    # Best and worst individual trades
    best_trade = max(trades, key=lambda t: t["pnl_usd"])
    worst_trade = min(trades, key=lambda t: t["pnl_usd"])

    return {
        "empty": False,
        "total_trades": len(trades),
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "wins": len(wins),
        "losses": len(losses),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "rr_ratio": rr_ratio,
        "by_market": dict(by_market),
        "by_hour": dict(by_hour),
        "exit_reasons": dict(exit_reasons),
        "long_wr": long_wr,
        "short_wr": short_wr,
        "long_pnl": long_pnl,
        "short_pnl": short_pnl,
        "max_loss_streak": max_streak,
        "best_trade": best_trade,
        "worst_trade": worst_trade,
    }


# ── Phase 2: Self-Tuning Engine ──────────────────────────────────────

def generate_tuning_recommendations(analysis: dict, config: dict, learnings: dict, history: list[dict] = None) -> list[dict]:
    """
    Generate config change recommendations based on analysis.
    Each recommendation: {param, old_value, new_value, reason, confidence}
    """
    if analysis.get("empty"):
        return []

    recommendations = []
    markets_cfg = config.get("markets", {})

    # ── Rule 1: Disable bleeding markets (>10 trades, <25% WR, negative P&L) ──
    for ticker, stats in analysis["by_market"].items():
        if stats["trades"] >= 10 and stats["win_rate"] < 25 and stats["pnl"] < 0:
            recommendations.append({
                "param": f"markets.{ticker}.enabled",
                "old_value": True,
                "new_value": False,
                "reason": f"{ticker}: {stats['trades']}t, {stats['win_rate']:.0f}% WR, ${stats['pnl']:+.2f}. Disabling until conditions improve.",
                "confidence": "high",
                "reversible": True,
            })

    # ── Rule 2: Adjust TP if consistently exiting early or late ──
    tp_hits = analysis["exit_reasons"].get("TP", 0)
    sl_hits = analysis["exit_reasons"].get("SL", 0)
    total = analysis["total_trades"]

    if total >= 15:
        tp_rate = tp_hits / total
        sl_rate = sl_hits / total

        current_tp = config.get("exit", {}).get("tp_pct", 10.5)

        # If TP hit rate >60% and win rate >50%, price is running past TP — widen
        if tp_rate > 0.6 and analysis["win_rate"] > 50:
            new_tp = min(current_tp * 1.15, 15.0)  # Max 15%
            if new_tp != current_tp:
                recommendations.append({
                    "param": "exit.tp_pct",
                    "old_value": current_tp,
                    "new_value": round(new_tp, 1),
                    "reason": f"TP hit {tp_rate:.0%} of trades with {analysis['win_rate']:.0f}% WR — price running past target. Widening TP.",
                    "confidence": "medium",
                })

        # If SL hit rate >50%, SL too tight — widen slightly
        current_sl = abs(config.get("exit", {}).get("sl_pct", 3.5))
        if sl_rate > 0.5:
            new_sl = min(current_sl * 1.2, 5.0)  # Max -5%
            if new_sl != current_sl:
                recommendations.append({
                    "param": "exit.sl_pct",
                    "old_value": -current_sl,
                    "new_value": -round(new_sl, 1),
                    "reason": f"SL hit {sl_rate:.0%} of trades. Getting stopped out too often. Widening SL.",
                    "confidence": "medium",
                })

    # ── Rule 3: Direction imbalance — if one direction clearly dominates ──
    if analysis["total_trades"] >= 20:
        if analysis["long_wr"] > 60 and analysis["short_wr"] < 30:
            recommendations.append({
                "param": "note",
                "old_value": None,
                "new_value": "LONG-dominant day",
                "reason": f"Longs: {analysis['long_wr']:.0f}% WR (${analysis['long_pnl']:+.2f}) vs Shorts: {analysis['short_wr']:.0f}% WR (${analysis['short_pnl']:+.2f}). Trending day — consider tightening short filters.",
                "confidence": "low",
            })
        elif analysis["short_wr"] > 60 and analysis["long_wr"] < 30:
            recommendations.append({
                "param": "note",
                "old_value": None,
                "new_value": "SHORT-dominant day",
                "reason": f"Shorts: {analysis['short_wr']:.0f}% WR vs Longs: {analysis['long_wr']:.0f}% WR. Bearish day — consider tightening long filters.",
                "confidence": "low",
            })

    # ── Rule 4: Weekend sizing check ──
    now = datetime.now(timezone.utc)
    if now.weekday() in (5, 6):  # Saturday/Sunday
        if analysis["win_rate"] < 35 and total >= 10:
            current_weekend = config.get("day_sizing", {}).get(str(now.weekday()), 0.5)
            new_sizing = max(current_weekend * 0.7, 0.2)
            recommendations.append({
                "param": f"day_sizing.{now.weekday()}",
                "old_value": current_weekend,
                "new_value": round(new_sizing, 2),
                "reason": f"Weekend WR {analysis['win_rate']:.0f}% across {total} trades. Reducing weekend position size.",
                "confidence": "medium",
            })

    # ── Rule 5: Score threshold check via learnings ──
    for ticker, brain_data in learnings.items():
        recent_scores = brain_data.get("recent_scores", [])
        if len(recent_scores) >= 20:
            # Check if score 5 trades are mostly losers
            # (Would need per-trade score-to-outcome mapping; flag for research)
            pass

    return recommendations


def apply_recommendations(config: dict, recommendations: list[dict]) -> tuple[dict, list[str]]:
    """Apply approved recommendations to config. Returns updated config and list of changes made."""
    changes = []

    for rec in recommendations:
        if rec.get("confidence") == "low":
            # Low confidence = log only, don't auto-apply
            changes.append(f"📝 NOTE: {rec['reason']}")
            continue

        param = rec["param"]
        if param == "note":
            changes.append(f"📝 {rec['reason']}")
            continue

        parts = param.split(".")
        obj = config
        for part in parts[:-1]:
            obj = obj.setdefault(part, {})

        old = obj.get(parts[-1])
        obj[parts[-1]] = rec["new_value"]
        changes.append(f"🔧 {param}: {old} → {rec['new_value']} ({rec['reason']})")

    return config, changes


# ── Phase 3: Research Agenda (generates search queries for Jarvis) ────

def generate_research_agenda(analysis: dict, config: dict) -> list[dict]:
    """Generate targeted research queries based on today's performance gaps."""
    agenda = []

    if analysis.get("empty"):
        agenda.append({
            "topic": "general",
            "query": "hyperliquid perpetual futures trading bot strategy optimization 2026",
            "reason": "No trades today — general research for improvement",
        })
        return agenda

    # If SL hit rate high → research optimal SL placement
    sl_rate = analysis["exit_reasons"].get("SL", 0) / analysis["total_trades"] if analysis["total_trades"] else 0
    if sl_rate > 0.4:
        agenda.append({
            "topic": "stop_loss_optimization",
            "query": "optimal stop loss placement perpetual futures ATR-based dynamic stop loss algotrading",
            "reason": f"SL hit rate {sl_rate:.0%} — researching smarter SL strategies",
        })

    # If win rate low → research entry filters
    if analysis["win_rate"] < 40:
        agenda.append({
            "topic": "entry_filters",
            "query": "EMA crossover false signal filter algotrading reddit 2026",
            "reason": f"Win rate {analysis['win_rate']:.0f}% — need better entry filtering",
        })

    # If R:R poor → research exit optimization
    if analysis["rr_ratio"] < 2.0:
        agenda.append({
            "topic": "exit_optimization",
            "query": "take profit optimization trailing stop vs fixed target futures trading",
            "reason": f"R:R ratio {analysis['rr_ratio']:.2f}:1 — need better exit strategy",
        })

    # Always check what others are doing
    agenda.append({
        "topic": "community_intel",
        "query": "hyperliquid trading bot strategy reddit algotrading site:reddit.com",
        "reason": "Community intelligence — what strategies are working now",
    })

    # Check for Hyperliquid platform updates
    agenda.append({
        "topic": "platform_updates",
        "query": "hyperliquid new markets features update 2026",
        "reason": "Platform changes that could affect our bot",
    })

    return agenda


# ── Trade Journal ─────────────────────────────────────────────────────

def update_trade_journal(date: str, analysis: dict, recommendations: list, changes: list, research: list):
    """Append today's analysis to the persistent trade journal."""
    journal = []
    if TRADE_JOURNAL_PATH.exists():
        try:
            with open(TRADE_JOURNAL_PATH) as f:
                journal = json.load(f)
        except Exception:
            journal = []

    entry = {
        "date": date,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "analysis": {
            "total_trades": analysis.get("total_trades", 0),
            "total_pnl": analysis.get("total_pnl", 0),
            "win_rate": analysis.get("win_rate", 0),
            "rr_ratio": analysis.get("rr_ratio", 0),
            "best_market": None,
            "worst_market": None,
            "max_loss_streak": analysis.get("max_loss_streak", 0),
        },
        "config_changes": changes,
        "research_agenda": [r["topic"] for r in research],
        "recommendations_count": len(recommendations),
    }

    # Best/worst market
    if analysis.get("by_market"):
        sorted_markets = sorted(analysis["by_market"].items(), key=lambda x: x[1]["pnl"], reverse=True)
        if sorted_markets:
            entry["analysis"]["best_market"] = {"ticker": sorted_markets[0][0], "pnl": sorted_markets[0][1]["pnl"]}
            entry["analysis"]["worst_market"] = {"ticker": sorted_markets[-1][0], "pnl": sorted_markets[-1][1]["pnl"]}

    journal.append(entry)

    # Keep last 90 days
    journal = journal[-90:]

    with open(TRADE_JOURNAL_PATH, "w") as f:
        json.dump(journal, f, indent=2)

    logger.info(f"Trade journal updated: {len(journal)} entries")


# ── Changelog ─────────────────────────────────────────────────────────

def log_changes(date: str, changes: list[str]):
    """Append config changes to changelog."""
    changelog = []
    if CHANGELOG_PATH.exists():
        try:
            with open(CHANGELOG_PATH) as f:
                changelog = json.load(f)
        except Exception:
            changelog = []

    if changes:
        changelog.append({
            "date": date,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "changes": changes,
        })

    # Keep last 90 days
    changelog = changelog[-90:]

    with open(CHANGELOG_PATH, "w") as f:
        json.dump(changelog, f, indent=2)


# ── Telegram Report Builder ──────────────────────────────────────────

def build_telegram_report(date: str, analysis: dict, changes: list, research: list) -> str:
    """Build the daily intelligence report for Telegram."""
    lines = [f"🧠 PEGASUS DAILY INTEL — {date}", ""]

    if analysis.get("empty"):
        lines.append("😴 No trades today. Bot idle or all signals filtered.")
        return "\n".join(lines)

    # Summary
    emoji = "🟢" if analysis["total_pnl"] >= 0 else "🔴"
    lines.append(f"{emoji} P&L: ${analysis['total_pnl']:+.2f} | {analysis['total_trades']} trades | {analysis['win_rate']:.0f}% WR")
    lines.append(f"📊 Avg Win: ${analysis['avg_win']:+.2f} | Avg Loss: ${analysis['avg_loss']:+.2f} | R:R: {analysis['rr_ratio']:.1f}:1")
    lines.append(f"📈 Longs: {analysis['long_wr']:.0f}% WR (${analysis['long_pnl']:+.2f}) | Shorts: {analysis['short_wr']:.0f}% WR (${analysis['short_pnl']:+.2f})")

    if analysis["max_loss_streak"] >= 3:
        lines.append(f"⚠️ Max loss streak: {analysis['max_loss_streak']}")

    lines.append("")

    # Exit breakdown
    er = analysis["exit_reasons"]
    lines.append(f"Exits: TP:{er.get('TP',0)} | SL:{er.get('SL',0)} | Hard:{er.get('HARD_STOP',0)} | Fund:{er.get('FUNDING',0)} | Other:{er.get('OTHER',0)}")
    lines.append("")

    # Per market (sorted by P&L)
    sorted_markets = sorted(analysis["by_market"].items(), key=lambda x: x[1]["pnl"], reverse=True)
    lines.append("By market:")
    for ticker, stats in sorted_markets:
        icon = "🏆" if stats["pnl"] > 0 else "💀"
        lines.append(f"  {icon} {ticker}: {stats['trades']}t {stats['win_rate']:.0f}%WR ${stats['pnl']:+.2f}")
    lines.append("")

    # Best/worst individual trades
    bt = analysis["best_trade"]
    wt = analysis["worst_trade"]
    lines.append(f"🌟 Best: {bt['direction']} {bt['ticker']} ${bt['pnl_usd']:+.2f} ({bt['exit_reason']})")
    lines.append(f"💩 Worst: {wt['direction']} {wt['ticker']} ${wt['pnl_usd']:+.2f} ({wt['exit_reason']})")
    lines.append("")

    # Config changes
    if changes:
        lines.append("🔧 Changes made:")
        for c in changes:
            lines.append(f"  {c}")
        lines.append("")

    # Research agenda
    if research:
        lines.append("🔬 Research queue:")
        for r in research[:3]:
            lines.append(f"  • {r['reason']}")

    return "\n".join(lines)


# ── Main Entry Point ─────────────────────────────────────────────────

def run_daily_coach(target_date: str = None) -> dict:
    """
    Run the full daily intelligence cycle.
    Returns a dict with analysis, changes, research agenda, and Telegram report.
    
    Called by:
      1. Cron (via shell wrapper) — auto-applies medium+ confidence changes
      2. Jarvis (via import) — reviews, adds research findings, applies changes
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    logger.info(f"🧠 Daily Coach starting for {target_date}")

    # Load data
    config = load_config()
    learnings = load_learnings()
    all_trades = parse_alerts_log()
    today_trades = filter_trades(all_trades, target_date)

    logger.info(f"Parsed {len(all_trades)} total trades, {len(today_trades)} for {target_date}")

    # Phase 1: Analyze
    analysis = analyze_performance(today_trades)

    # Phase 2: Generate recommendations
    recommendations = generate_tuning_recommendations(analysis, config, learnings)

    # Phase 3: Apply changes
    config, changes = apply_recommendations(config, recommendations)
    if any("🔧" in c for c in changes):
        save_config(config)
        logger.info("Config updated and saved")

    # Phase 3b: Research agenda
    research = generate_research_agenda(analysis, config)

    # Update journal + changelog
    update_trade_journal(target_date, analysis, recommendations, changes, research)
    log_changes(target_date, changes)

    # Build report
    report = build_telegram_report(target_date, analysis, changes, research)

    logger.info("Daily Coach complete")

    return {
        "date": target_date,
        "analysis": analysis,
        "recommendations": recommendations,
        "changes": changes,
        "research_agenda": research,
        "telegram_report": report,
    }


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    result = run_daily_coach(target)
    print("\n" + result["telegram_report"])
