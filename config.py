"""
Configuration constants for the candle-feeder service.
All values can be overridden via environment variables.
"""

import os
from pathlib import Path

# Bridge URLs — existing MT5 EA bridges (priority order: freshest first)
BRIDGE_URLS = os.environ.get(
    "BRIDGE_URLS",
    "http://host.docker.internal:5005,"
    "http://host.docker.internal:5006,"
    "http://host.docker.internal:5007,"
    "http://host.docker.internal:5003"
).split(",")

# TwelveData fallback (optional, for deep history)
TWELVEDATA_KEYS = [k.strip() for k in os.environ.get("TWELVEDATA_KEYS", "").split(",") if k.strip()]

# Cache
CACHE_DIR = Path(os.environ.get("CACHE_DIR", "/data/cache/mt5_cache"))
MAX_CANDLES = int(os.environ.get("MAX_CANDLES", "50000"))

# Polling
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "10"))
CANDLES_PER_POLL = int(os.environ.get("CANDLES_PER_POLL", "500"))

# Bootstrap
BOOTSTRAP_THRESHOLD = int(os.environ.get("BOOTSTRAP_THRESHOLD", "10000"))
BOOTSTRAP_FETCH_COUNT = int(os.environ.get("BOOTSTRAP_FETCH_COUNT", "500"))  # Bridge max ~200

# TwelveData bootstrap (deeper history)
TD_BOOTSTRAP_COUNT = 800

# Redis
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")

# Health
HEALTH_PORT = int(os.environ.get("HEALTH_PORT", "8080"))

# Assumed broker trade-server offset from UTC, used only by the HTTP bridge
# fallback path (bridge_client) where we can't probe the server directly.
# OANDA during EEST = +3. mt5linux_client auto-detects and ignores this value.
BROKER_UTC_OFFSET_HOURS = int(os.environ.get("BROKER_UTC_OFFSET_HOURS", "3"))

# Canonical symbols to track
SYMBOLS = [
    # Majors / liquid (original 11)
    "EURUSD", "GBPUSD", "USDJPY", "XAUUSD",
    "EURJPY", "GBPJPY", "USDCAD", "NZDUSD", "US30",
    "AUDUSD", "USDCHF",
    # AUD crosses
    "AUDCAD", "AUDCHF", "AUDJPY", "AUDNZD",
    # EUR crosses
    "EURAUD", "EURCAD", "EURCHF", "EURGBP", "EURNZD",
    # GBP crosses
    "GBPAUD", "GBPCAD", "GBPCHF", "GBPNZD",
    # NZD / CAD / CHF crosses
    "NZDCAD", "NZDCHF", "NZDJPY", "CADCHF", "CADJPY", "CHFJPY",
    # Indices & crypto
    "NAS100", "BTCUSD", "ETHUSD",
]

# Timeframes
TIMEFRAME_NAMES = ["M1", "M5", "M15", "H1", "H4", "D1"]

# TwelveData symbol mapping (used only for deep-history backfill fallback)
TD_SYMBOL_MAP = {
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY",
    "XAUUSD": "XAU/USD", "EURJPY": "EUR/JPY", "GBPJPY": "GBP/JPY",
    "USDCAD": "USD/CAD", "NZDUSD": "NZD/USD", "US30": "DJI",
    "AUDUSD": "AUD/USD", "USDCHF": "USD/CHF",
    "AUDCAD": "AUD/CAD", "AUDCHF": "AUD/CHF", "AUDJPY": "AUD/JPY", "AUDNZD": "AUD/NZD",
    "EURAUD": "EUR/AUD", "EURCAD": "EUR/CAD", "EURCHF": "EUR/CHF",
    "EURGBP": "EUR/GBP", "EURNZD": "EUR/NZD",
    "GBPAUD": "GBP/AUD", "GBPCAD": "GBP/CAD", "GBPCHF": "GBP/CHF", "GBPNZD": "GBP/NZD",
    "NZDCAD": "NZD/CAD", "NZDCHF": "NZD/CHF", "NZDJPY": "NZD/JPY",
    "CADCHF": "CAD/CHF", "CADJPY": "CAD/JPY", "CHFJPY": "CHF/JPY",
    "NAS100": "NDX", "BTCUSD": "BTC/USD", "ETHUSD": "ETH/USD",
}

# TwelveData timeframe mapping
TD_TF_MAP = {
    "M1": "1min", "M5": "5min", "M15": "15min", "H1": "1h", "H4": "4h", "D1": "1day",
}
