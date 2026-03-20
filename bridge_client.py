"""
Bridge client — fetches candle data from existing MT5 EA bridges (HTTP).

Tries multiple bridges in priority order, picks the one with the freshest data.
No API keys, no rate limits — local HTTP calls to existing infrastructure.
"""

import logging
import time
from datetime import datetime, timezone

import requests

log = logging.getLogger("candle-feeder.bridge")

# MT5 timeframe name → bridge API parameter
TF_MAP = {
    "M5": "M5",
    "M15": "M15",
    "H1": "H1",
    "H4": "H4",
    "D1": "D1",
}


class BridgeClient:
    """Fetches candles from MT5 EA bridges via HTTP."""

    def __init__(self, bridge_urls, timeout=15):
        """
        Args:
            bridge_urls: List of bridge URLs in priority order
                         e.g. ["http://host.docker.internal:5005", ...]
            timeout: HTTP request timeout in seconds
        """
        self.bridge_urls = bridge_urls
        self.timeout = timeout
        self._active_bridge = None
        self._session = requests.Session()

    def connect(self):
        """Find the first responding bridge."""
        for url in self.bridge_urls:
            try:
                resp = self._session.get(f"{url}/", timeout=5)
                if resp.status_code == 200:
                    self._active_bridge = url
                    log.info(f"Bridge connected: {url}")
                    return
            except Exception:
                continue
        raise RuntimeError(f"No bridge responding from: {self.bridge_urls}")

    def connect_with_retry(self, max_attempts=0, interval=10):
        """Keep trying to connect until success."""
        attempt = 0
        while True:
            attempt += 1
            try:
                self.connect()
                return
            except Exception as e:
                log.error(f"Bridge connect attempt {attempt} failed: {e}")
                if max_attempts > 0 and attempt >= max_attempts:
                    raise
                log.info(f"Retrying in {interval}s...")
                time.sleep(interval)

    def reconnect(self):
        """Re-probe all bridges to find a working one."""
        log.warning("Bridge reconnecting...")
        self._active_bridge = None
        self.connect()

    def fetch_candles(self, symbol, timeframe_name, count=500):
        """
        Fetch candles from the active bridge.

        Tries all bridges if active one fails. Returns list of
        normalized candle dicts sorted ascending by time.
        """
        tf_param = TF_MAP.get(timeframe_name, timeframe_name)
        urls_to_try = [self._active_bridge] if self._active_bridge else []
        urls_to_try += [u for u in self.bridge_urls if u != self._active_bridge]

        for url in urls_to_try:
            try:
                resp = self._session.get(
                    f"{url}/candles",
                    params={"symbol": symbol, "timeframe": tf_param, "count": count},
                    timeout=self.timeout,
                )
                if resp.status_code != 200:
                    continue

                data = resp.json()
                candles_raw = []

                # Handle different bridge response formats
                if isinstance(data, dict):
                    candles_raw = data.get("candles", data.get("data", data.get("history", [])))
                elif isinstance(data, list):
                    candles_raw = data

                if not candles_raw:
                    continue

                # Normalize and sort ascending
                normalized = [self._normalize(c) for c in candles_raw]
                normalized.sort(key=lambda x: x["time"])

                if url != self._active_bridge:
                    self._active_bridge = url
                    log.info(f"Switched to bridge {url}")

                return normalized

            except Exception as e:
                log.debug(f"Bridge {url} failed for {symbol} {tf_param}: {e}")
                continue

        log.warning(f"All bridges failed for {symbol} {timeframe_name} "
                    f"(tried {len(urls_to_try)} bridges)")
        return []

    def get_symbols(self):
        """
        Not directly available from bridges — return the configured symbol list.
        Symbol resolution happens via probe (try fetching candles).
        """
        return []

    def get_timeframe_constants(self):
        """Return timeframe name mapping (bridges use string names, not constants)."""
        return dict(TF_MAP)

    def _normalize(self, candle):
        """Convert bridge candle to standard cache format."""
        # Bridge returns datetime as "2026.03.20 02:15" or ISO format
        raw_time = candle.get("datetime", candle.get("time", ""))

        # Parse various formats
        parsed_time = None
        for fmt in ("%Y.%m.%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                     "%Y-%m-%dT%H:%M:%S+00:00", "%Y.%m.%d %H:%M:%S"):
            try:
                parsed_time = datetime.strptime(str(raw_time), fmt)
                break
            except ValueError:
                continue

        if parsed_time is None:
            # Fallback: use raw string
            time_str = str(raw_time)
        else:
            time_str = parsed_time.strftime("%Y-%m-%dT%H:%M:%S+00:00")

        return {
            "time": time_str,
            "open": float(candle.get("open", 0)),
            "high": float(candle.get("high", 0)),
            "low": float(candle.get("low", 0)),
            "close": float(candle.get("close", 0)),
            "volume": int(candle.get("volume", candle.get("tick_volume", 0))),
            "source": "bridge",
        }
