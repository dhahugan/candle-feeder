# candle-feeder

Dockerized real-time candlestick cache system for the Hive trading bot. Connects directly to an MT5 terminal via RPyC, pulls candle data from OANDA's servers, and writes to the shared disk cache that all trading bots read from.

**100% free** — no API keys, no rate limits, no paid plans. Uses an OANDA MT5 demo account.

## Architecture

```
┌──────────────┐     RPyC (8001)     ┌──────────────────┐
│ MT5 Terminal │◄────────────────────│  candle-feeder    │
│ (Wine/Docker)│                     │                   │
│              │                     │ 1. Bootstrap 50k  │
│ OANDA Demo   │                     │ 2. Poll every 10s │
│ Live prices  │                     │ 3. Atomic merge   │
└──────────────┘                     └────────┬──────────┘
                                              │ write
                                    ┌─────────▼──────────┐
                                    │ /data/cache/        │
                                    │   mt5_cache/        │
                                    │   EURUSD_M15.json   │  ◄── Trading bots
                                    │   XAUUSD_H4.json    │      read from here
                                    │   US30_D1.json      │      (no changes)
                                    └────────────────────┘
```

## Quick Start

### 1. Get an OANDA Demo Account (free)

1. Go to https://www.oanda.com/register/#/sign-up/demo
2. Register (no credit card needed)
3. Download MT5 platform → note your **login**, **password**, **server**
4. Copy credentials to `.env`:

```bash
cp .env.example .env
# Edit .env with your OANDA credentials
```

### 2. Start the MT5 Terminal

```bash
docker compose up -d mt5-terminal
# Wait ~5 minutes for MT5 to install inside the container
```

### 3. Login to MT5 (one-time manual step)

1. Open browser: `http://your-server-ip:3000`
2. Login with VNC credentials (MT5_VNC_USER / MT5_VNC_PASSWORD)
3. In MT5: **File → Login to Trade Account**
   - Login: `1600109304`
   - Password: `lWhBAHP3oPcw#`
   - Server: `OANDA_Global-Demo-13`
4. Confirm charts load with live data

This only needs to be done once — the `mt5_config` volume preserves the login.

### 4. Start the Candle Feeder

```bash
docker compose up -d candle-feeder
```

Watch the bootstrap pull 50,000 candles per symbol:
```bash
docker logs -f candle-feeder
```

### 5. Verify

```bash
# Health check
curl -s http://localhost:8080/health | python3 -m json.tool

# Watch new bars live
docker logs -f candle-feeder | grep "NEW BAR"

# Check all cache depths
for f in /data/cache/mt5_cache/*.json; do
  printf "%-25s %s candles\n" "$(basename $f)" "$(python3 -c "import json;print(len(json.load(open('$f'))))")"
done | sort

# Verify XAUUSD H4 depth
python3 -c "import json; d=json.load(open('/data/cache/mt5_cache/XAUUSD_H4.json')); print(f'{len(d)} candles, earliest: {d[0][\"time\"]}')"

# Check source field
python3 -c "import json; d=json.load(open('/data/cache/mt5_cache/EURUSD_M15.json')); print(set(c['source'] for c in d))"
# Expected: {'mt5'}
```

## How It Works

1. **Bootstrap** (first startup): Pulls up to 50,000 candles per symbol/TF from MT5. H4/D1 data typically goes back 10-20+ years.

2. **Polling loop** (continuous): Every 10 seconds, fetches 500 latest candles for each symbol/TF. Merges with existing cache atomically.

3. **New bar detection**: When the latest candle timestamp changes, logs `NEW BAR` and publishes to Redis `new_bar` channel.

4. **Atomic writes**: Uses `os.replace(tmp, final)` + file locks. Trading bots never see partial files.

5. **Cache grows monotonically**: The merger only adds candles, never removes. Max 50,000 per file (configurable).

## Health Endpoint

```
GET http://localhost:8080/health  → full status JSON
GET http://localhost:8080/symbols → all broker symbol names
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MT5_LOGIN` | — | OANDA demo account login |
| `MT5_PASSWORD` | — | OANDA demo account password |
| `MT5_SERVER` | — | OANDA MT5 server name |
| `MT5_HOST` | `mt5-terminal` | MT5 container hostname |
| `MT5_PORT` | `8001` | RPyC port |
| `CACHE_DIR` | `/data/cache/mt5_cache` | Cache file directory |
| `MAX_CANDLES` | `50000` | Max candles per file |
| `POLL_INTERVAL` | `10` | Seconds between poll cycles |
| `CANDLES_PER_POLL` | `500` | Candles fetched per poll |
| `BOOTSTRAP_THRESHOLD` | `10000` | Skip bootstrap if cache already has this many |
| `REDIS_URL` | `redis://redis:6379` | Redis for pub/sub (optional) |
