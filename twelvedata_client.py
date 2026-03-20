"""
TwelveData client — optional fallback for deep history backfill.
Uses the existing 4 API keys with round-robin rotation.
"""

import logging
import time
from datetime import datetime, timezone

import requests

from config import TWELVEDATA_KEYS, TD_SYMBOL_MAP, TD_TF_MAP

log = logging.getLogger("candle-feeder.twelvedata")


class TwelveDataClient:
    """Fetches historical candles from TwelveData API."""

    def __init__(self):
        self.keys = TWELVEDATA_KEYS
        self._key_index = 0
        self._session = requests.Session()
        self.enabled = len(self.keys) > 0

    def _next_key(self):
        if not self.keys:
            return None
        key = self.keys[self._key_index % len(self.keys)]
        self._key_index += 1
        return key

    def fetch_candles(self, symbol, timeframe_name, count=800):
        """
        Fetch candles from TwelveData. Returns normalized list sorted ascending.
        Returns empty list if no keys configured or API fails.
        """
        if not self.enabled:
            return []

        td_symbol = TD_SYMBOL_MAP.get(symbol)
        td_tf = TD_TF_MAP.get(timeframe_name)
        if not td_symbol or not td_tf:
            return []

        key = self._next_key()
        if not key:
            return []

        try:
            resp = self._session.get(
                "https://api.twelvedata.com/time_series",
                params={
                    "symbol": td_symbol,
                    "interval": td_tf,
                    "outputsize": count,
                    "apikey": key,
                },
                timeout=30,
            )
            data = resp.json()

            if data.get("status") == "error":
                log.warning(f"TwelveData error for {symbol}: {data.get('message', '?')}")
                return []

            values = data.get("values", [])
            if not values:
                return []

            normalized = [self._normalize(v) for v in values]
            normalized.sort(key=lambda x: x["time"])

            log.info(f"TwelveData: {symbol} {timeframe_name} = {len(normalized)} candles")
            return normalized

        except Exception as e:
            log.warning(f"TwelveData fetch error {symbol}: {e}")
            return []

    def _normalize(self, val):
        """Convert TwelveData candle to standard cache format."""
        # TwelveData returns "2024-01-15 10:00:00" in UTC
        raw_time = val.get("datetime", "")
        try:
            dt = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
            time_str = dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        except ValueError:
            time_str = raw_time

        return {
            "time": time_str,
            "open": float(val.get("open", 0)),
            "high": float(val.get("high", 0)),
            "low": float(val.get("low", 0)),
            "close": float(val.get("close", 0)),
            "volume": int(float(val.get("volume", 0))),
            "source": "twelvedata",
        }
