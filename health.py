"""
Flask health endpoint for monitoring.

GET /health  → queue/cache status JSON
GET /symbols → full list of broker symbols
"""

import json
import logging
import threading
import time
from pathlib import Path

from flask import Flask, jsonify
from config import CACHE_DIR, HEALTH_PORT

log = logging.getLogger("candle-feeder.health")

app = Flask(__name__)

# Shared state — set by feeder.py
_state = {
    "mt5_connected": False,
    "mt5_account": "",
    "mt5_server": "",
    "resolved_symbols": {},
    "unresolved_symbols": [],
    "last_poll_completed": None,
    "last_poll_duration": 0,
    "new_bars_today": 0,
    "bootstrap_complete": False,
    "started_at": time.time(),
    "all_broker_symbols": [],
}


def update_state(**kwargs):
    """Called by feeder.py to update health state."""
    _state.update(kwargs)


@app.route("/health")
def health():
    cache_depths = {}
    try:
        for f in sorted(CACHE_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                if isinstance(data, list):
                    cache_depths[f.stem] = len(data)
            except (json.JSONDecodeError, OSError):
                cache_depths[f.stem] = -1
    except Exception:
        pass

    uptime = time.time() - _state["started_at"]

    return jsonify({
        "status": "ok" if _state["mt5_connected"] else "degraded",
        "mt5_connected": _state["mt5_connected"],
        "mt5_account": _state["mt5_account"],
        "mt5_server": _state["mt5_server"],
        "resolved_symbols": _state["resolved_symbols"],
        "unresolved_symbols": _state["unresolved_symbols"],
        "uptime_seconds": round(uptime),
        "last_poll_completed": _state["last_poll_completed"],
        "last_poll_duration_seconds": round(_state["last_poll_duration"], 1),
        "cache_depths": cache_depths,
        "new_bars_today": _state["new_bars_today"],
        "bootstrap_complete": _state["bootstrap_complete"],
    })


@app.route("/symbols")
def symbols():
    return jsonify({
        "broker_symbols": _state["all_broker_symbols"],
        "resolved": _state["resolved_symbols"],
        "unresolved": _state["unresolved_symbols"],
        "count": len(_state["all_broker_symbols"]),
    })


def start_health_server():
    """Start Flask in a daemon thread — doesn't block the main loop."""
    thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=HEALTH_PORT, debug=False),
        daemon=True,
    )
    thread.start()
    log.info(f"Health endpoint started on port {HEALTH_PORT}")
