"""
mt5linux_client — drop-in replacement for BridgeClient that talks to the
mt5linux RPC server (Wine Python) instead of HTTP+file-based EA bridges.

Interface matches BridgeClient exactly so feeder.py only needs to swap the
import, nothing else.

Benefits over BridgeClient:
  • No EA lag — bars come straight from MT5's memory
  • M1 data actually works (no file-write race)
  • Can return the current FORMING bar as well (include_forming=True)
  • Single RPC hop vs (HTTP→file→disk→file-read)
"""

import logging
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from mt5linux import MetaTrader5

log = logging.getLogger("candle-feeder.mt5linux")

# Maldives Standard Time = UTC+5, no DST transitions.
# All emitted candle times are in this zone so downstream dashboards
# read wall-clock times that match the operator's locale.
MALDIVES_TZ = ZoneInfo("Indian/Maldives")


class MT5LinuxClient:
    """Fetches candles directly from MT5 via the mt5linux RPC server."""

    # MT5 timeframe constants — mirrored so we don't need to init before map
    _TF_CONSTANTS = {
        "M1":  1,   "M5":  5,    "M15": 15,
        "M30": 30,  "H1":  16385, "H4":  16388,
        "D1":  16408,
    }

    def __init__(self, rpc_hosts: List[str], timeout: int = 15):
        """
        Args:
            rpc_hosts: List of "host:port" strings for mt5linux RPC servers
                       e.g. ["host.docker.internal:8001", "host.docker.internal:8002"]
                       Falls over to next host if the primary dies.
            timeout: RPC call timeout (seconds)
        """
        self.rpc_hosts = rpc_hosts
        self.timeout = timeout
        self._mt5: Optional[MetaTrader5] = None
        self._active_host: Optional[str] = None
        # BridgeClient-compat: feeder.py reads `_active_bridge`
        self._active_bridge: Optional[str] = None
        # BridgeClient-compat: feeder.py may check `bridge_urls`
        self.bridge_urls = rpc_hosts
        # Seconds the broker's trade-server clock is ahead of true UTC.
        # Detected on connect (OANDA typically GMT+3 during EEST).
        self._broker_offset_seconds: Optional[int] = None

    # ── BridgeClient-compatible surface ──────────────────────────────
    def connect_with_retry(self, max_attempts: int = 0, interval: int = 10) -> bool:
        """
        Retry connect() until success. max_attempts=0 means infinite.
        Matches BridgeClient's method signature for drop-in compatibility.
        """
        attempt = 0
        while True:
            attempt += 1
            if self.connect():
                return True
            if max_attempts and attempt >= max_attempts:
                log.error(f"Failed to connect after {attempt} attempts")
                return False
            log.info(f"Retry in {interval}s (attempt {attempt})")
            time.sleep(interval)

    def connect(self) -> bool:
        """Find the first responding RPC server."""
        for host_port in self.rpc_hosts:
            host, port = host_port.rsplit(":", 1)
            try:
                mt5 = MetaTrader5(host=host, port=int(port))
                mt5.initialize()
                info = mt5.account_info()
                if info is not None:
                    self._mt5 = mt5
                    self._active_host = host_port
                    self._active_bridge = f"mt5linux://{host_port}"
                    log.info(f"Connected to mt5linux at {host_port} — "
                             f"account {info.login} on {info.server}")
                    self._broker_offset_seconds = self._detect_broker_offset()
                    return True
                log.warning(f"{host_port}: account_info returned None")
            except Exception as e:
                log.warning(f"{host_port}: {e}")
        log.error(f"No mt5linux server reachable from {self.rpc_hosts}")
        return False

    def _detect_broker_offset(self) -> int:
        """
        MT5's copy_rates_from_pos returns bar.time as epoch-seconds but encoded
        in the trade-server's local clock (e.g. GMT+3 for OANDA during EEST).
        We probe a liquid M1 bar, compare its epoch to our true UTC clock, and
        round to the nearest hour — brokers only set offsets at :00.

        Falls back to +3 h (OANDA default) if probing fails, so the feeder
        can still start against an unresponsive symbol list.
        """
        for probe in ("EURUSD", "XAUUSD", "GBPUSD"):
            try:
                try:
                    self._mt5.symbol_select(probe, True)
                except Exception:
                    pass
                # M1, the most recently-closed bar
                bars = self._mt5.copy_rates_from_pos(probe, 1, 1, 1)
                if bars is not None and len(bars) > 0:
                    broker_epoch = int(bars[0]["time"])
                    utc_epoch = int(time.time())
                    hours = round((broker_epoch - utc_epoch) / 3600)
                    offset = hours * 3600
                    log.info(f"Broker timezone detected: UTC{hours:+d}h "
                             f"(probe={probe}, diff={broker_epoch - utc_epoch}s)")
                    return offset
            except Exception as e:
                log.debug(f"offset probe via {probe}: {e}")
                continue
        log.warning("Could not detect broker timezone; defaulting to UTC+3")
        return 3 * 3600

    def _ensure_connected(self) -> bool:
        if self._mt5 is None:
            return self.connect()
        # Quick ping — if it fails, reconnect
        try:
            self._mt5.account_info()
            return True
        except Exception:
            log.warning(f"Lost {self._active_host}, reconnecting…")
            self._mt5 = None
            return self.connect()

    def fetch_candles(self, symbol: str, timeframe: str,
                      count: int = 500, include_forming: bool = False) -> List[Dict]:
        """
        Fetch candles. Returns list of dicts matching the BridgeClient format:
          {"time": "2026.04.20 12:45", "open": ..., "high": ..., "low": ...,
           "close": ..., "volume": ...}

        Args:
            symbol: e.g. "XAUUSD" (without .m suffix — we auto-resolve)
            timeframe: "M1" / "M5" / "M15" / "H1" / "H4" / "D1"
            count: how many bars (including the forming bar if include_forming)
            include_forming: if True, bar index 0 (current forming) included.
                             Default False (only confirmed closed bars).

        Returns [] on failure so feeder.py's fallback logic is triggered.
        """
        if not self._ensure_connected():
            return []

        tf_const = self._TF_CONSTANTS.get(timeframe.upper())
        if tf_const is None:
            log.error(f"Unknown timeframe {timeframe}")
            return []

        # Try the raw symbol first, then try common suffixes brokers use
        # Broker-specific symbol suffixes:
        #   (bare)      most standard
        #   .m / m      Exness micro accounts
        #   .c          Exness cent accounts
        #   .sml        OANDA demo — "small" contract size aliases
        #   .a          some OANDA live naming
        candidates = [symbol, f"{symbol}.m", f"{symbol}m", f"{symbol}.c",
                      f"{symbol}.sml", f"{symbol}.a"]
        start_pos = 0 if include_forming else 1
        bars = None
        resolved = None
        for cand in candidates:
            try:
                # CRITICAL: select the symbol into MarketWatch before pulling
                # rates — otherwise unsubscribed symbols return stale data or
                # "No IPC connection" errors.
                try:
                    self._mt5.symbol_select(cand, True)
                except Exception:
                    pass
                # Always pull count+1 so we can skip the forming bar if needed
                bars = self._mt5.copy_rates_from_pos(cand, tf_const, start_pos, count)
                if bars is not None and len(bars) > 0:
                    resolved = cand
                    break
            except Exception as e:
                log.debug(f"copy_rates_from_pos({cand}, {timeframe}): {e}")
                continue

        if bars is None or len(bars) == 0:
            log.warning(f"No candles for {symbol} {timeframe} from mt5linux "
                        f"(tried {candidates})")
            return []

        if resolved != symbol:
            log.debug(f"{symbol} resolved to broker symbol {resolved}")

        # Convert MT5's numpy structured array to plain dicts.
        #
        # Time handling: MT5 returns bar.time as epoch-seconds encoded in the
        # trade-server's clock (not true UTC). We subtract the detected broker
        # offset to recover true UTC, then render in Maldives time so the
        # wall-clock string matches the operator's local expectation.
        #
        # The emitted ISO-8601 string (e.g. "2026-04-21T01:25:00+05:00") sorts
        # correctly lexicographically and is still the exact dedupe key used
        # by merger.py — all candle sources in this system must emit the same
        # shape or merger.py silently duplicates rows.
        offset = self._broker_offset_seconds if self._broker_offset_seconds is not None else 3 * 3600
        out: List[Dict] = []
        for b in bars:
            true_utc_epoch = int(b["time"]) - offset
            dt_mvt = datetime.fromtimestamp(true_utc_epoch, tz=MALDIVES_TZ)
            out.append({
                "time":   dt_mvt.isoformat(timespec="seconds"),
                "open":   float(b["open"]),
                "high":   float(b["high"]),
                "low":    float(b["low"]),
                "close":  float(b["close"]),
                "volume": int(b["tick_volume"]),
                "source": "mt5linux",
            })
        return out

    def fetch_forming_bar(self, symbol: str, timeframe: str) -> Optional[Dict]:
        """Just the single current forming bar (index 0). None if unavailable."""
        bars = self.fetch_candles(symbol, timeframe, count=1, include_forming=True)
        return bars[0] if bars else None

    def close(self):
        if self._mt5 is not None:
            try:
                self._mt5.shutdown()
            except Exception:
                pass
            self._mt5 = None
