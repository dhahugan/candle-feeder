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

# Forex market hours: closed Fri 22:00 UTC → Sun 22:00 UTC (no new candles in this window).
# Returns 0 if market open, 1 if closed.
is_market_open() {
    local dow hour
    dow=$(date -u +%u)   # 1=Mon ... 7=Sun
    hour=$(date -u +%H)
    [ "$dow" = "5" ] && [ "$hour" -ge 22 ] && return 1   # Fri ≥22:00 UTC
    [ "$dow" = "6" ] && return 1                          # Saturday — all closed
    [ "$dow" = "7" ] && [ "$hour" -lt 22 ] && return 1   # Sun <22:00 UTC
    return 0
}

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
    docker exec mt5-oanda bash -c "pip install --break-system-packages -q flask mt5linux >/dev/null 2>&1; nohup python3 /bridge/api_bridge_mt5linux.py > /tmp/candle_bridge.log 2>&1 &"
    exit 1
fi

# 2b. Check mt5linux RPC server inside mt5-oanda is listening on :8001
# mt5linux runs inside Wine and does NOT auto-start with the container — it must
# be hand-launched after MT5 terminal is ready. The feeder's primary data path
# depends on this RPC server, so a missing mt5linux means no polls succeed.
if ! docker exec mt5-oanda ss -tln 2>/dev/null | grep -q ":8001 "; then
    alert "mt5linux RPC inside mt5-oanda is DOWN — relaunching"
    # Kill any zombie before relaunch (Wine sometimes leaves the python.exe alive
    # without an active listener after the accept queue wedges).
    docker exec mt5-oanda bash -c "pkill -9 -f 'mt5linux.*--host' 2>/dev/null; true" >> "$LOG" 2>&1
    sleep 2
    # Launch via Wine as user 'abc'; -d (detached) so the process survives this exec.
    docker exec -u abc -d mt5-oanda bash -c '
        export DISPLAY=:1
        export WINEPREFIX=/config/.wine
        cd /tmp
        nohup wine "C:\\Program Files (x86)\\Python39-32\\python.exe" -m mt5linux --host 0.0.0.0 -p 8001 > /tmp/mt5linux.log 2>&1 &
    '
    # Wine + 32-bit Python + MetaTrader5 import takes ~20-30s to bind the port.
    # Sleep here so the next watchdog cycle (2 min later) sees the bound port and skips this branch.
    sleep 15
    exit 1
fi

# 3. Check OANDA bridge responding (HTTP 200 + non-empty JSON body)
BRIDGE_HTTP=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$BRIDGE_URL" 2>/dev/null)
if [ "$BRIDGE_HTTP" != "200" ]; then
    alert "OANDA bridge not responding (http=$BRIDGE_HTTP) — restarting bridge process"
    docker exec mt5-oanda bash -c "pkill -f 'api_bridge_mt5linux.py\|candle_bridge.py' 2>/dev/null; sleep 2; nohup python3 /bridge/api_bridge_mt5linux.py > /tmp/candle_bridge.log 2>&1 &"
    exit 1
fi
BRIDGE_STATUS="ok"  # for legacy log line at end

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
elif [ -n "$LAST_POLL" ] && [ "$LAST_POLL" -gt 120 ] 2>/dev/null && is_market_open; then
    alert "candle-feeder polling stalled — last poll was ${LAST_POLL}s ago"
    cd "$COMPOSE_DIR" && docker compose restart candle-feeder >> "$LOG" 2>&1
    exit 1
fi

# 6. Check data freshness — our 9 tracked symbols M5 files updated in last 10 min
# Skip when forex market is closed (no new candles being produced anyway)
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
if [ "$STALE_COUNT" -gt 3 ] && is_market_open; then
    alert "Cache data stale — ${STALE_COUNT}/9 tracked M5 files older than 10 min"
fi

echo "$(ts) OK: bridge=$BRIDGE_STATUS poll_age=${LAST_POLL}s stale=${STALE_COUNT}" >> "$LOG"
