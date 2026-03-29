#!/bin/bash
# Forwards trading bot alerts via Pegasus Telegram Bot
# Cron: * * * * * /root/.openclaw/workspace/MrZMTradingBot/alert-forwarder.sh

ALERTS_FILE="/root/.openclaw/workspace/MrZMTradingBot/alerts.log"
POS_FILE="/root/.openclaw/workspace/MrZMTradingBot/.alert-pos"

# Initialize position file if missing
if [ ! -f "$POS_FILE" ]; then
    wc -c < "$ALERTS_FILE" > "$POS_FILE"
    exit 0
fi

LAST_POS=$(cat "$POS_FILE")
CURRENT_SIZE=$(wc -c < "$ALERTS_FILE")

# Nothing new
[ "$CURRENT_SIZE" -le "$LAST_POS" ] && exit 0

# Read new content
NEW_CONTENT=$(tail -c +$((LAST_POS + 1)) "$ALERTS_FILE")

# Update position
echo "$CURRENT_SIZE" > "$POS_FILE"

# Parse and forward via Telegram Bot API
echo "$NEW_CONTENT" | python3 -c "
import sys, urllib.request, urllib.parse, time, re

BOT_TOKEN = os.environ.get('PEGASUS_TG_TOKEN', '')
CHAT_ID = '6670320636'

def send(msg):
    msg = msg.strip()
    if len(msg) < 10:
        return
    url = f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
    data = urllib.parse.urlencode({
        'chat_id': CHAT_ID,
        'text': msg,
        'disable_notification': 'false'
    }).encode()
    try:
        urllib.request.urlopen(url, data, timeout=10)
    except:
        pass

raw = sys.stdin.read()

# Remove all ═══ decoration lines
lines = [l for l in raw.split('\n') if not l.strip().startswith('═')]

# Rejoin and split by timestamp markers [YYYY-MM-DD HH:MM:SS UTC]
text = '\n'.join(lines)
# Split into blocks starting with [timestamp]
blocks = re.split(r'(?=\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC\])', text)

for block in blocks:
    block = block.strip()
    if not block:
        continue
    
    # TRADE OPEN
    if 'OPEN LONG' in block or 'OPEN SHORT' in block:
        send(block)
        time.sleep(0.5)
    
    # TRADE CLOSE
    elif 'CLOSE LONG' in block or 'CLOSE SHORT' in block:
        send(block)
        time.sleep(0.5)
    
    # Skip status reports (too noisy — will add daily summary instead)
"
