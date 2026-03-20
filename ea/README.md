# CandleExporter EA + Bridge

Dedicated candlestick data extraction system for the OANDA demo MT5 terminal.

**This does NOT trade** — it only reads and exports price data.

## Components

1. **CandleExporter.mq5** — MQL5 Expert Advisor that exports candle data every 5 seconds
2. **candle_bridge.py** — Flask HTTP server that serves the EA's JSON files via `/candles`

## Architecture

```
OANDA Demo MT5 Terminal
    ↓ (CopyRates every 5s)
CandleExporter EA
    ↓ (writes JSON to MQL5/Files/)
EURUSD_M15.json, XAUUSD_H4.json, ...
    ↓ (reads files)
candle_bridge.py (port 5008)
    ↓ (HTTP /candles)
candle-feeder Docker container
```

## Setup Steps

### 1. Copy EA to MT5 Terminal

Via VNC (http://your-server:3001):

1. Open MT5 terminal
2. Go to **File → Open Data Folder**
3. Navigate to `MQL5/Experts/`
4. Copy `CandleExporter.mq5` into this folder
5. In MT5: **Tools → MetaEditor** (or press F4)
6. Open `CandleExporter.mq5` and click **Compile** (F7)
7. Close MetaEditor

### 2. Attach EA to Chart

1. In MT5 terminal, open any chart (e.g., EURUSD M15)
2. Drag **CandleExporter** from Navigator → Expert Advisors onto the chart
3. In the EA settings dialog:
   - **CandlesPerExport**: 500 (default)
   - **ExportIntervalSeconds**: 5 (default)
   - Check **Allow Algo Trading**
4. Click OK
5. Verify the EA is running: look for the smiley face icon on the chart

### 3. Start the Candle Bridge

```bash
# Inside the MT5 terminal Docker container:
pip install flask
python3 candle_bridge.py --port 4905 &

# Or if running as a separate process on the host:
python3 ea/candle_bridge.py --port 5008 &
```

### 4. Update candle-feeder to use the dedicated bridge

In `docker-compose.yml`, add the dedicated bridge as primary:

```yaml
- BRIDGE_URLS=http://host.docker.internal:5008,http://host.docker.internal:5003,...
```

### 5. Verify

```bash
# Check available symbols
curl http://localhost:5008/symbols | python3 -m json.tool

# Fetch candles
curl "http://localhost:5008/candles?symbol=EURUSD&timeframe=M15&count=10"

# Health check
curl http://localhost:5008/health
```

## EA Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| CandlesPerExport | 500 | Candles per symbol/TF per export |
| ExportIntervalSeconds | 5 | How often to re-export (seconds) |
| CustomSymbols | (empty) | Override symbol list (comma-separated) |

## Exported Symbols

Default: EURUSD, GBPUSD, USDJPY, USDCHF, USDCAD, AUDUSD, NZDUSD, EURJPY, GBPJPY, XAUUSD, US30

## File Format

```json
[
  {"datetime": "2026.03.20 17:30", "open": 1.08542, "high": 1.08610, "low": 1.08490, "close": 1.08598, "volume": 1284},
  ...
]
```

Files are written atomically by the EA (FileOpen → FileWrite → FileClose).
The bridge reads them with retry logic to handle concurrent access.
