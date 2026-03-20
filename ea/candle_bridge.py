"""
Candle Bridge — lightweight Flask server that serves candle data from EA-exported JSON files.

The CandleExporter EA writes JSON files to MQL5/Files/ every 5 seconds.
This bridge reads those files and serves them via HTTP /candles endpoint.

This is a DATA-ONLY bridge — no trading commands, no account management.

Usage:
    python3 candle_bridge.py                    # Default port 4905
    python3 candle_bridge.py --port 5008        # Custom port

Deploy on the OANDA demo MT5 terminal alongside CandleExporter.mq5.
"""

import json
import os
import sys
import time
from pathlib import Path

from flask import Flask, jsonify, request

app = Flask(__name__)

# MT5 MQL5/Files directory — where the EA writes candle JSON files
# Try multiple paths (kasm-user, root, Wine default)
MQL5_FILES = None
for candidate in [
    Path("/home/kasm-user/.wine/drive_c/Program Files/MetaTrader 5/MQL5/Files"),
    Path("/root/.wine/drive_c/Program Files/MetaTrader 5/MQL5/Files"),
    Path("/config/.wine/drive_c/Program Files/MetaTrader 5/MQL5/Files"),
]:
    if candidate.exists():
        MQL5_FILES = candidate
        break

if MQL5_FILES is None:
    print("WARNING: MQL5/Files directory not found — using /tmp as fallback")
    MQL5_FILES = Path("/tmp")

print(f"Candle Bridge: MQL5/Files = {MQL5_FILES}")


def read_json_safe(filename):
    """Read a JSON file with retry (EA may be writing simultaneously)."""
    path = MQL5_FILES / filename
    if not path.exists():
        return None
    for _ in range(3):
        try:
            with open(path, "r") as f:
                content = f.read().strip()
                if not content:
                    return None
                return json.loads(content)
        except (json.JSONDecodeError, OSError):
            time.sleep(0.05)
    return None


@app.route("/")
def index():
    """Health/info endpoint."""
    return jsonify({
        "service": "candle-bridge",
        "type": "data-only",
        "mql5_files": str(MQL5_FILES),
        "status": "ok",
    })


@app.route("/candles")
def candles():
    """
    Serve candle data from EA-exported JSON files.

    Query params:
        symbol: e.g., EURUSD, XAUUSD, US30
        timeframe: M5, M15, H1, H4, D1 (default: M15)
        count: number of candles to return (default: 200)
    """
    symbol = request.args.get("symbol", "").upper()
    timeframe = request.args.get("timeframe", "M15").upper()
    count = int(request.args.get("count", 200))

    if not symbol:
        return jsonify({"success": False, "error": "Missing symbol"}), 400

    # EA writes files as SYMBOL_TF.json (e.g., EURUSD_M15.json)
    filename = f"{symbol}_{timeframe}.json"
    data = read_json_safe(filename)

    if data and isinstance(data, list):
        # Return last N candles (EA exports oldest-first)
        candles_out = data[-count:] if len(data) > count else data
        return jsonify({
            "success": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "count": len(candles_out),
            "candles": candles_out,
        })

    return jsonify({
        "success": False,
        "error": f"No candle data for {symbol} {timeframe}",
    })


@app.route("/symbols")
def symbols():
    """List all available symbol/timeframe files from the EA."""
    available = []
    if MQL5_FILES.exists():
        for f in sorted(MQL5_FILES.glob("*_*.json")):
            parts = f.stem.rsplit("_", 1)
            if len(parts) == 2:
                data = read_json_safe(f.name)
                count = len(data) if data and isinstance(data, list) else 0
                available.append({
                    "symbol": parts[0],
                    "timeframe": parts[1],
                    "candles": count,
                    "file": f.name,
                })
    return jsonify({"success": True, "available": available})


@app.route("/health")
def health():
    """Health check for Docker."""
    return jsonify({
        "status": "ok",
        "mql5_files": str(MQL5_FILES),
        "uptime": int(time.time() - _start_time),
    })


_start_time = time.time()

if __name__ == "__main__":
    port = 4905
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        port = int(sys.argv[idx + 1])

    print(f"Candle Bridge starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
