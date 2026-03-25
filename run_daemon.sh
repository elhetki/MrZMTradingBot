#!/bin/bash
# MahmudBot 24/7 Paper Trading Daemon
# Runs the bot in background, auto-restarts on crash
# Logs to logs/bot.log

cd /root/.openclaw/workspace/MrZMTradingBot

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

LOG_FILE="$LOG_DIR/bot.log"
PID_FILE="$LOG_DIR/bot.pid"

# Check if already running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Bot already running (PID $OLD_PID). Kill it first: kill $OLD_PID"
        exit 1
    fi
fi

echo "Starting MahmudBot v2.5 — 24/7 Paper Trading..."
echo "Logs: $LOG_FILE"

# Run with auto-restart
while true; do
    echo "[$(date -u)] Starting bot..." >> "$LOG_FILE"
    python3 bot.py >> "$LOG_FILE" 2>&1
    EXIT_CODE=$?
    echo "[$(date -u)] Bot exited with code $EXIT_CODE. Restarting in 10s..." >> "$LOG_FILE"
    sleep 10
done &

# Save PID
echo $! > "$PID_FILE"
echo "Bot started in background (PID $(cat $PID_FILE))"
echo "Tail logs: tail -f $LOG_FILE"
echo "Stop: kill $(cat $PID_FILE)"
