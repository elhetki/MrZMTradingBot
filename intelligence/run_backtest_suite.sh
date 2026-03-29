#!/bin/bash
# Pegasus Backtest Suite — runs comprehensive backtests and reports results
# Can be triggered by cron or manually
set -euo pipefail

BOT_DIR="/root/.openclaw/workspace/MrZMTradingBot"
INTEL_DIR="${BOT_DIR}/intelligence"
RESULTS_DIR="${BOT_DIR}/intelligence/backtest_results"
TIMESTAMP=$(date -u +%Y%m%d_%H%M)

cd "$BOT_DIR"
source /root/.openclaw/workspace/.env.secrets
mkdir -p "$RESULTS_DIR"

echo "[$(date -u)] Starting backtest suite..."

# Run backtest on all enabled markets with 5m candles (18 days available)
echo "[$(date -u)] Running 5m backtest (all markets)..."
python3 run_backtest.py --months 1 --output "$RESULTS_DIR/bt_5m_${TIMESTAMP}.json" 2>&1 | tail -5

# Run backtest with 1h candles for longer history (3 months)
echo "[$(date -u)] Running 1h backtest (all markets, 3 months)..."
python3 run_backtest.py --months 3 --interval 1h --output "$RESULTS_DIR/bt_1h_${TIMESTAMP}.json" 2>&1 | tail -5

# Generate summary report
echo "[$(date -u)] Generating summary..."
python3 << 'PYEOF'
import json, glob, os, sys
from datetime import datetime

results_dir = os.environ.get('RESULTS_DIR', 'intelligence/backtest_results')
timestamp = os.environ.get('TIMESTAMP', '')

report_lines = [f"📊 PEGASUS BACKTEST REPORT — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}", ""]

for label, fname in [("5m (18 days)", f"bt_5m_{timestamp}.json"), ("1h (3 months)", f"bt_1h_{timestamp}.json")]:
    path = os.path.join(results_dir, fname)
    if not os.path.exists(path):
        report_lines.append(f"⚠️ {label}: file not found")
        continue
    
    with open(path) as f:
        data = json.load(f)
    
    total_trades = sum(m.get('stats', {}).get('total_trades', 0) for m in data)
    total_pnl = sum(m['final_capital'] - m['initial_capital'] for m in data)
    
    if total_trades == 0:
        report_lines.append(f"📉 {label}: 0 trades (filters too tight or insufficient data)")
        continue
    
    total_wins = sum(
        sum(1 for t in m.get('trades', []) if t.get('net_pnl', 0) > 0)
        for m in data
    )
    overall_wr = total_wins / total_trades * 100 if total_trades else 0
    
    # Exit reasons
    tp = sl = fg = other = 0
    for m in data:
        for t in m.get('trades', []):
            r = t.get('exit_reason', '')
            if 'TP' in r: tp += 1
            elif 'SL' in r: sl += 1
            elif 'Funding' in r: fg += 1
            else: other += 1
    
    report_lines.append(f"📈 {label}:")
    report_lines.append(f"  Trades: {total_trades} | WR: {overall_wr:.1f}% | P&L: ${total_pnl:+.2f}")
    report_lines.append(f"  Exits: TP:{tp} SL:{sl} Fund:{fg} Other:{other}")
    
    # Per market
    sorted_markets = sorted(data, key=lambda m: m['final_capital'] - m['initial_capital'], reverse=True)
    for m in sorted_markets:
        s = m.get('stats', {})
        if s.get('total_trades', 0) > 0:
            pnl = m['final_capital'] - m['initial_capital']
            icon = "🟢" if pnl > 0 else "🔴"
            report_lines.append(f"    {icon} {m['ticker']}: {s['total_trades']}t {s['win_rate']:.0f}%WR ${pnl:+.2f}")
    report_lines.append("")

# Save report
report = "\n".join(report_lines)
print(report)

report_path = os.path.join(results_dir, f"report_{timestamp}.txt")
with open(report_path, 'w') as f:
    f.write(report)

# Send via Telegram
import urllib.request
token = os.environ.get('PEGASUS_TG_TOKEN', '')
chat_id = os.environ.get('PEGASUS_TG_CHAT_ID', '')
if token and chat_id:
    import urllib.parse
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data_encoded = urllib.parse.urlencode({'chat_id': chat_id, 'text': report}).encode()
    try:
        urllib.request.urlopen(url, data_encoded, timeout=10)
        print("\n[Telegram report sent]")
    except Exception as e:
        print(f"\n[Telegram send failed: {e}]")
PYEOF

echo "[$(date -u)] Backtest suite complete."
