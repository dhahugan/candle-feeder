#!/bin/bash
# Candle-feeder watchdog — runs via cron every 2 minutes
# Checks: containers running, bridge responding, candle-feeder polling, data freshness
# Sends Telegram alert on failure, auto-restarts if possible

COMPOSE_DIR="/home/claude_dev/candle-feeder"
TELEGRAM_TOKEN=$(cat /home/claude_dev/hive-bot/data/telegram_token.txt 2>/dev/null)
TELEGRAM_CHAT_ID="256965110"
LOG="/tmp/candle-feeder-watchdog.log"
HEALTH_URL="http://localhost:8085/health"
BRIDGE_URL="http://localhost:5008/"

ts() { date "+%Y-%m-%d %H:%M:%S"; }

alert() {
    local msg="🚨 CANDLE-FEEDER WATCHDOG\n$1"
    echo "$(ts) ALERT: $1" >> "$LOG"
    if [ -n "$TELEGRAM_TOKEN" ]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage" \
            -d "chat_id=${TELEGRAM_CHAT_ID}" \
            -d "text=${msg}" \
            -d "parse_mode=HTML" > /dev/null 2>&1
    fi
}

# 1. Check candle-feeder container
if ! docker ps --filter "name=candle-feeder" --format "{{.Status}}" | grep -q "Up"; then
    alert "candle-feeder container is DOWN — restarting"
    cd "$COMPOSE_DIR" && docker compose up -d candle-feeder >> "$LOG" 2>&1
    exit 1
fi

# 2. Check mt5-oanda container
if ! docker ps --filter "name=mt5-oanda" --format "{{.Status}}" | grep -q "Up"; then
    alert "mt5-oanda container is DOWN — restarting"
    cd "$COMPOSE_DIR" && docker compose up -d mt5-oanda >> "$LOG" 2>&1
    # Wait for MT5 to start, then restart bridge
    sleep 30
    docker exec mt5-oanda bash -c "pip install --break-system-packages flask >/dev/null 2>&1; nohup python3 /tmp/candle_bridge.py --port 4905 > /tmp/candle_bridge.log 2>&1 &"
    exit 1
fi

# 3. Check OANDA bridge responding
BRIDGE_STATUS=$(curl -s --max-time 5 "$BRIDGE_URL" 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('status',''))" 2>/dev/null)
if [ "$BRIDGE_STATUS" != "ok" ]; then
    alert "OANDA bridge not responding — restarting bridge process"
    docker exec mt5-oanda bash -c "pkill -f candle_bridge 2>/dev/null; sleep 2; nohup python3 /tmp/candle_bridge.py --port 4905 > /tmp/candle_bridge.log 2>&1 &"
    exit 1
fi

# 4. Check candle-feeder health endpoint
HEALTH=$(curl -s --max-time 5 "$HEALTH_URL" 2>/dev/null)
if [ -z "$HEALTH" ]; then
    alert "candle-feeder health endpoint not responding"
    cd "$COMPOSE_DIR" && docker compose restart candle-feeder >> "$LOG" 2>&1
    exit 1
fi

# 5. Check last poll is recent (within 60 seconds)
LAST_POLL=$(echo "$HEALTH" | python3 -c "
import sys,json
from datetime import datetime, timezone
d=json.load(sys.stdin)
lp = d.get('last_poll_completed')
if not lp:
    print('NO_POLL')
else:
    dt = datetime.fromisoformat(lp)
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    print(f'{age:.0f}')
" 2>/dev/null)

if [ "$LAST_POLL" = "NO_POLL" ]; then
    echo "$(ts) OK: bootstrap in progress" >> "$LOG"
elif [ -n "$LAST_POLL" ] && [ "$LAST_POLL" -gt 120 ] 2>/dev/null; then
    alert "candle-feeder polling stalled — last poll was ${LAST_POLL}s ago"
    cd "$COMPOSE_DIR" && docker compose restart candle-feeder >> "$LOG" 2>&1
    exit 1
fi

# 6. Check data freshness — our 9 tracked symbols M5 files updated in last 10 min
STALE_COUNT=0
TRACKED="EURUSD GBPUSD USDJPY XAUUSD EURJPY GBPJPY USDCAD NZDUSD US30"
for sym in $TRACKED; do
    f="/home/claude_dev/hive-bot/data/cache/mt5_cache/${sym}_M5.json"
    if [ -f "$f" ]; then
        AGE=$(( $(date +%s) - $(stat -c %Y "$f") ))
        if [ "$AGE" -gt 600 ]; then
            STALE_COUNT=$((STALE_COUNT + 1))
        fi
    fi
done
if [ "$STALE_COUNT" -gt 3 ]; then
    alert "Cache data stale — ${STALE_COUNT}/9 tracked M5 files older than 10 min"
fi

echo "$(ts) OK: bridge=$BRIDGE_STATUS poll_age=${LAST_POLL}s stale=${STALE_COUNT}" >> "$LOG"
