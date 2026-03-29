#!/usr/bin/env python3
"""
Deep Analysis Tool — inspired by Zoran's deep_analysis.py
Analyzes trading performance by score, probability, pattern, market, direction, and hour.
"""
import re
import json
from collections import defaultdict

ALERTS_FILE = "alerts.log"
LEARNINGS_FILE = "learnings.json"

def parse_trades():
    with open(ALERTS_FILE) as f:
        content = f.read()
    
    # Parse CLOSE trades
    pattern = r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] [✅❌⚡] CLOSE (LONG|SHORT) (\w+)\n📈 Entry: \$([\d,.]+) → Exit: \$([\d,.]+)\n💰 P&L: ([+-][\d.]+)% \(\$([+-][\d.]+)\)\n⏱️ Duration: (.+)\n📝 (.+)'
    return re.findall(pattern, content)

def parse_opens():
    with open(ALERTS_FILE) as f:
        content = f.read()
    pattern = r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] [🟢🔴] OPEN (LONG|SHORT) (\w+)\n💰 Entry: \$([\d,.]+)\n📊 Size: \$([\d.]+) @ (\d+)x\n🎯 Score: (\d+) \| Prob: (\d+)%'
    return re.findall(pattern, content)

def main():
    trades = parse_trades()
    opens = parse_opens()
    
    if not trades:
        print("No trades found.")
        return
    
    print(f"\nTotal: {len(trades)} trades\n")
    
    # ═══ MARKET + DIRECTION ═══
    print("=" * 60)
    print(" MARKET + DIRECTION (best to worst)")
    print("=" * 60)
    mkts = defaultdict(lambda: {'trades': 0, 'wins': 0, 'losses': 0, 'pnl': 0})
    for t in trades:
        key = f"{t[2]} {t[1]}"
        pnl = float(t[6])
        mkts[key]['trades'] += 1
        mkts[key]['pnl'] += pnl
        if pnl > 0: mkts[key]['wins'] += 1
        else: mkts[key]['losses'] += 1
    
    for key, d in sorted(mkts.items(), key=lambda x: -x[1]['pnl']):
        wr = d['wins']/d['trades']*100 if d['trades'] else 0
        marker = " <<<" if d['pnl'] > 0 and wr >= 40 else ""
        print(f" {key:<20} | {d['trades']} trades | {d['wins']}W/{d['losses']}L | WR:{wr:.0f}% | ${d['pnl']:+.2f}{marker}")
    
    # ═══ EXIT REASONS ═══
    print(f"\n{'='*60}")
    print(" EXIT REASONS")
    print(f"{'='*60}")
    reasons = defaultdict(lambda: {'count': 0, 'pnl': 0})
    for t in trades:
        reason_text = t[8]
        if 'SL hit' in reason_text: r = 'STOP_LOSS'
        elif 'TP hit' in reason_text: r = 'TAKE_PROFIT'
        elif 'Funding guard' in reason_text: r = 'FUNDING_GUARD'
        else: r = 'OTHER'
        reasons[r]['count'] += 1
        reasons[r]['pnl'] += float(t[6])
    for r, d in sorted(reasons.items(), key=lambda x: -x[1]['count']):
        print(f" {r:<15} | {d['count']:>4} trades ({d['count']/len(trades)*100:.0f}%) | ${d['pnl']:+.2f}")
    
    # ═══ HOURLY ANALYSIS ═══
    print(f"\n{'='*60}")
    print(" HOURLY P&L (UTC) — find your best/worst hours")
    print(f"{'='*60}")
    hourly = defaultdict(lambda: {'pnl': 0, 'trades': 0, 'wins': 0})
    for t in trades:
        hour = int(t[0].split(' ')[1].split(':')[0])
        pnl = float(t[6])
        hourly[hour]['pnl'] += pnl
        hourly[hour]['trades'] += 1
        if pnl > 0: hourly[hour]['wins'] += 1
    
    for h in sorted(hourly.keys()):
        d = hourly[h]
        wr = d['wins']/d['trades']*100 if d['trades'] else 0
        bar = '█' * max(1, int(abs(d['pnl'])))
        marker = " ⚠️ BAD HOUR" if wr < 25 and d['trades'] >= 5 else ""
        marker = " 🔥 GOOD HOUR" if wr >= 45 and d['trades'] >= 5 else marker
        print(f" {h:02d}:00 | {d['trades']:>3} trades | {wr:>4.0f}% WR | ${d['pnl']:>+7.2f} {bar}{marker}")
    
    # ═══ DIRECTION ANALYSIS ═══
    print(f"\n{'='*60}")
    print(" DIRECTION ANALYSIS")
    print(f"{'='*60}")
    dirs = defaultdict(lambda: {'pnl': 0, 'trades': 0, 'wins': 0})
    for t in trades:
        pnl = float(t[6])
        dirs[t[1]]['pnl'] += pnl
        dirs[t[1]]['trades'] += 1
        if pnl > 0: dirs[t[1]]['wins'] += 1
    for d, s in sorted(dirs.items(), key=lambda x: -x[1]['pnl']):
        wr = s['wins']/s['trades']*100 if s['trades'] else 0
        print(f" {d:>6} | {s['trades']} trades | {wr:.0f}% WR | ${s['pnl']:+.2f}")
    
    # ═══ LEARNING ENGINE STATUS ═══
    print(f"\n{'='*60}")
    print(" LEARNING ENGINE STATUS")
    print(f"{'='*60}")
    try:
        with open(LEARNINGS_FILE) as f:
            learn = json.load(f)
        
        for ticker, data in sorted(learn.items()):
            bias = data.get('direction_bias', 0)
            sl_adj = data.get('sl_adjust_pct', 0)
            patterns = data.get('patterns', {})
            ds = data.get('direction_stats', {})
            total = sum(v.get('total', 0) for v in ds.values())
            
            if total == 0:
                continue
            
            pnl = sum(v.get('pnl', 0) for v in ds.values())
            wins = sum(v.get('wins', 0) for v in ds.values())
            wr = wins/total*100 if total else 0
            
            pattern_str = ""
            if patterns:
                pattern_str = " | Patterns: " + ", ".join(f"{k}({v.get('wins',0)}W/{v.get('total',0)-v.get('wins',0)}L)" for k, v in patterns.items() if v.get('total', 0) > 0)
            
            bias_str = ""
            if abs(bias) > 0:
                bias_str = f" | Bias: {'LONG' if bias > 0 else 'SHORT'} {abs(bias):.1f}pts"
            
            sl_str = ""
            if abs(sl_adj) > 0:
                sl_str = f" | SL adj: {sl_adj:+.1f}%"
            
            print(f" {ticker:<8} | {total} trades | {wr:.0f}% WR | ${pnl:+.2f}{bias_str}{sl_str}{pattern_str}")
    except Exception as e:
        print(f" Error reading learnings: {e}")
    
    # ═══ KEY FINDINGS ═══
    print(f"\n{'='*60}")
    print(" KEY FINDINGS")
    print(f"{'='*60}")
    
    # Best/worst markets
    best_mkt = max(mkts.items(), key=lambda x: x[1]['pnl'])
    worst_mkt = min(mkts.items(), key=lambda x: x[1]['pnl'])
    print(f" 🏆 Best: {best_mkt[0]} (${best_mkt[1]['pnl']:+.2f}, {best_mkt[1]['wins']}W/{best_mkt[1]['losses']}L)")
    print(f" 💀 Worst: {worst_mkt[0]} (${worst_mkt[1]['pnl']:+.2f}, {worst_mkt[1]['wins']}W/{worst_mkt[1]['losses']}L)")
    
    # Funding guard impact
    fg = reasons.get('FUNDING_GUARD', {'count': 0, 'pnl': 0})
    if fg['count'] > 0:
        print(f" ⚠️ Funding guard: {fg['count']} trades ({fg['count']/len(trades)*100:.0f}%) — ${fg['pnl']:+.2f}")
    
    # Best/worst hours
    if hourly:
        best_hour = max(hourly.items(), key=lambda x: x[1]['pnl'])
        worst_hour = min(hourly.items(), key=lambda x: x[1]['pnl'])
        print(f" 🕐 Best hour: {best_hour[0]:02d}:00 UTC (${best_hour[1]['pnl']:+.2f})")
        print(f" 🕐 Worst hour: {worst_hour[0]:02d}:00 UTC (${worst_hour[1]['pnl']:+.2f})")

if __name__ == "__main__":
    main()
