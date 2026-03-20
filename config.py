"""
Configuration constants for the candle-feeder service.
All values can be overridden via environment variables.
"""

import os
from pathlib import Path

# MT5 connection
MT5_LOGIN = int(os.environ.get("MT5_LOGIN", "1600109304"))
MT5_PASSWORD = os.environ.get("MT5_PASSWORD", "")
MT5_SERVER = os.environ.get("MT5_SERVER", "OANDA_Global-Demo-13")
MT5_HOST = os.environ.get("MT5_HOST", "mt5-terminal")
MT5_PORT = int(os.environ.get("MT5_PORT", "8001"))

# Cache
CACHE_DIR = Path(os.environ.get("CACHE_DIR", "/data/cache/mt5_cache"))
MAX_CANDLES = int(os.environ.get("MAX_CANDLES", "50000"))

# Polling
POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "10"))
CANDLES_PER_POLL = int(os.environ.get("CANDLES_PER_POLL", "500"))

# Bootstrap
BOOTSTRAP_THRESHOLD = int(os.environ.get("BOOTSTRAP_THRESHOLD", "10000"))
BOOTSTRAP_FETCH_COUNT = 50000

# Redis
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")

# Health
HEALTH_PORT = int(os.environ.get("HEALTH_PORT", "8080"))

# Canonical symbols → list of known broker variations
KNOWN_SYMBOLS = {
    "EURUSD": ["EURUSD", "EUR/USD", "EURUSD.", "EURUSDm"],
    "GBPUSD": ["GBPUSD", "GBP/USD", "GBPUSD.", "GBPUSDm"],
    "USDJPY": ["USDJPY", "USD/JPY", "USDJPY.", "USDJPYm"],
    "XAUUSD": ["XAUUSD", "XAU/USD", "GOLD", "XAUUSD.", "XAUUSDm"],
    "EURJPY": ["EURJPY", "EUR/JPY", "EURJPY.", "EURJPYm"],
    "GBPJPY": ["GBPJPY", "GBP/JPY", "GBPJPY.", "GBPJPYm"],
    "USDCAD": ["USDCAD", "USD/CAD", "USDCAD.", "USDCADm"],
    "NZDUSD": ["NZDUSD", "NZD/USD", "NZDUSD.", "NZDUSDm"],
    "US30":   ["US30", "US30USD", "DJ30", "DJI", "US30.cash",
               "USA30", "#DJ30", "WallSt30", "US30m"],
}

# Timeframe name → mt5linux constant name (resolved at runtime)
TIMEFRAME_NAMES = ["M5", "M15", "H1", "H4", "D1"]

# Will be populated after MT5 connection with actual mt5.TIMEFRAME_* values
TIMEFRAMES = {}
