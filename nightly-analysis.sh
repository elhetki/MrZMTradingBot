#!/bin/bash
# Nightly Pegasus Analysis — runs at 23:00 UTC daily
# Analyzes today's trades, updates learnings, sends summary to Telegram

cd /root/.openclaw/workspace/MrZMTradingBot
source /root/.openclaw/workspace/.env.secrets

# Run deep analysis and capture output
ANALYSIS=$(python3 deep_analysis.py 2>&1)

# Only send if there are actual trades
if echo "$ANALYSIS" | grep -q "Total:.*trades"; then
    # Send to Telegram (Mahmud's chat)
    CHAT_ID="6670320636"
    BOT_TOKEN="$PEGASUS_BOT_TOKEN"
    
    # Truncate if too long for Telegram (4096 char limit)
    MSG=$(echo "$ANALYSIS" | head -80)
    
    if [ -n "$BOT_TOKEN" ]; then
        curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
            -d chat_id="$CHAT_ID" \
            -d text="📊 NIGHTLY PEGASUS ANALYSIS

${MSG}" \
            -d parse_mode="" \
            > /dev/null 2>&1
    fi
fi

# Also save to daily log
DATE=$(date +%Y-%m-%d)
echo "=== Nightly Analysis ${DATE} ===" >> logs/analysis_history.log
echo "$ANALYSIS" >> logs/analysis_history.log
echo "" >> logs/analysis_history.log
