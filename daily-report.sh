#!/bin/bash
# Sends daily Pegasus performance report at midnight UTC via Telegram
# Cron: 0 0 * * * /root/.openclaw/workspace/MrZMTradingBot/daily-report.sh

cd /root/.openclaw/workspace/MrZMTradingBot

source /root/.openclaw/workspace/.env.secrets
BOT_TOKEN="$PEGASUS_TG_TOKEN"
CHAT_ID="$PEGASUS_TG_CHAT_ID"

REPORT=$(python3 << 'PYEOF'
import re
from collections import defaultdict
from datetime import datetime, timezone, timedelta

with open('alerts.log') as f:
    content = f.read()

# Yesterday's date (report runs at midnight, so "today" in the log is yesterday)
yesterday = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime('%Y-%m-%d')

pattern = r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC)\] [✅❌⚡] CLOSE (LONG|SHORT) (\w+)\n📈 Entry: \$([\d,.]+) → Exit: \$([\d,.]+)\n💰 P&L: ([+-][\d.]+)% \(\$([+-][\d.]+)\)\n⏱️ Duration: (.+)\n📝 (.+)'
matches = re.findall(pattern, content)

today_trades = [m for m in matches if m[0].startswith(yesterday)]
all_trades = matches

if not today_trades:
    print(f"📊 PEGASUS DAILY REPORT — {yesterday}\n\n😴 No trades today. Bot was idle or all signals filtered.")
else:
    total_pnl = sum(float(m[6]) for m in today_trades)
    wins = sum(1 for m in today_trades if float(m[6]) > 0)
    losses = sum(1 for m in today_trades if float(m[6]) < 0)
    be = len(today_trades) - wins - losses
    wr = wins/len(today_trades)*100 if today_trades else 0
    
    # Per market
    mkts = defaultdict(lambda: {'pnl': 0, 'trades': 0, 'wins': 0})
    for m in today_trades:
        pnl = float(m[6])
        mkts[m[2]]['pnl'] += pnl
        mkts[m[2]]['trades'] += 1
        if pnl > 0: mkts[m[2]]['wins'] += 1
    
    best = max(mkts.items(), key=lambda x: x[1]['pnl'])
    worst = min(mkts.items(), key=lambda x: x[1]['pnl'])
    
    # Exit reasons
    tp = sum(1 for m in today_trades if 'TP hit' in m[8])
    sl = sum(1 for m in today_trades if 'SL hit' in m[8])
    fg = sum(1 for m in today_trades if 'Funding guard' in m[8])
    
    # All time
    all_pnl = sum(float(m[6]) for m in all_trades)
    all_wr = sum(1 for m in all_trades if float(m[6]) > 0) / len(all_trades) * 100 if all_trades else 0
    
    lines = [
        f"📊 PEGASUS DAILY REPORT — {yesterday}",
        f"",
        f"💰 Today P&L: ${total_pnl:+.2f}",
        f"🎯 Trades: {len(today_trades)} | W:{wins} L:{losses} BE:{be}",
        f"📈 Win Rate: {wr:.0f}%",
        f"",
        f"Exit breakdown:",
        f"  TP hits: {tp} | SL hits: {sl} | Funding: {fg}",
        f"",
        f"🏆 Best market: {best[0]} (${best[1]['pnl']:+.2f})",
        f"💀 Worst market: {worst[0]} (${worst[1]['pnl']:+.2f})",
        f"",
        f"Per market:",
    ]
    
    for asset, d in sorted(mkts.items(), key=lambda x: -x[1]['pnl']):
        mwr = d['wins']/d['trades']*100 if d['trades'] else 0
        lines.append(f"  {asset}: {d['trades']}t {mwr:.0f}%WR ${d['pnl']:+.2f}")
    
    lines.extend([
        f"",
        f"━━━ ALL TIME ━━━",
        f"Total P&L: ${all_pnl:+.2f} ({len(all_trades)} trades, {all_wr:.0f}% WR)",
    ])
    
    print("\n".join(lines))
PYEOF
)

# Send via Telegram
curl -s "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
  -d "chat_id=${CHAT_ID}" \
  --data-urlencode "text=${REPORT}" > /dev/null 2>&1
