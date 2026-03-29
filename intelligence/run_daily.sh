#!/bin/bash
# Pegasus Daily Intelligence Coach
# Cron: 0 19 * * * /root/.openclaw/workspace/MrZMTradingBot/intelligence/run_daily.sh
# Runs at 19:00 UTC (21:00 CET) — after US market close
#
# Phase 1+2: Run Python analysis + auto-apply config changes
# Phase 3: Trigger Jarvis session for research + deeper analysis

set -euo pipefail

BOT_DIR="/root/.openclaw/workspace/MrZMTradingBot"
INTEL_DIR="${BOT_DIR}/intelligence"

cd "$BOT_DIR"

# ── Phase 1+2: Performance Analysis + Config Tuning ──
echo "[$(date -u)] Running daily coach..."
REPORT=$(python3 intelligence/daily_coach.py 2>&1)
echo "$REPORT"

# ── Send report via Telegram ──
source /root/.openclaw/workspace/.env.secrets
BOT_TOKEN="$PEGASUS_TG_TOKEN"
CHAT_ID="$PEGASUS_TG_CHAT_ID"

# Extract just the telegram report (after the last "🧠 PEGASUS")
TG_REPORT=$(echo "$REPORT" | sed -n '/🧠 PEGASUS DAILY INTEL/,$p')

if [ -n "$TG_REPORT" ]; then
    curl -s "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${CHAT_ID}" \
        --data-urlencode "text=${TG_REPORT}" > /dev/null 2>&1
    echo "[$(date -u)] Telegram report sent"
fi

# ── Restart bot if config changed ──
if echo "$REPORT" | grep -q "Config updated"; then
    echo "[$(date -u)] Config changed — restarting bot..."
    kill $(cat "$BOT_DIR/logs/bot.pid" 2>/dev/null) 2>/dev/null || true
    sleep 3
    source /root/.openclaw/workspace/.env.secrets
    cd "$BOT_DIR"
    nohup python3 bot.py &> logs/bot.log &
    echo $! > logs/bot.pid
    echo "[$(date -u)] Bot restarted with new config (PID: $(cat logs/bot.pid))"
fi

echo "[$(date -u)] Daily coach complete"
