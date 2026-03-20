"""
MT5 client — connects to MetaTrader 5 terminal via RPyC (mt5linux).
Fetches candles and ticks. Auto-reconnects on failure.
"""

import logging
import time
from datetime import datetime, timezone

log = logging.getLogger("candle-feeder.mt5")


class MT5Client:
    """Wrapper around mt5linux.MetaTrader5 with reconnection logic."""

    def __init__(self, host, port, login, password, server):
        self.host = host
        self.port = port
        self.login = int(login)
        self.password = password
        self.server = server
        self.mt5 = None
        self._connected = False

    def connect(self):
        """Initialize MT5 connection and login."""
        from mt5linux import MetaTrader5
        self.mt5 = MetaTrader5(host=self.host, port=self.port)

        if not self.mt5.initialize():
            err = self.mt5.last_error()
            raise RuntimeError(f"MT5 initialize failed: {err}")

        authorized = self.mt5.login(
            self.login,
            password=self.password,
            server=self.server,
        )
        if not authorized:
            err = self.mt5.last_error()
            raise RuntimeError(f"MT5 login failed: {err}")

        self._connected = True
        info = self.mt5.account_info()
        log.info(f"MT5 connected: login={info.login}, server={info.server}, "
                 f"balance={info.balance}, company={info.company}")

    def reconnect(self):
        """Tear down and reconnect. Called on any RPyC/connection error."""
        log.warning("MT5 reconnecting...")
        try:
            self.mt5.shutdown()
        except Exception:
            pass
        self._connected = False
        time.sleep(5)
        self.connect()

    def connect_with_retry(self, max_attempts=0, interval=10):
        """Keep trying to connect until success. max_attempts=0 means forever."""
        attempt = 0
        while True:
            attempt += 1
            try:
                self.connect()
                return
            except Exception as e:
                log.error(f"MT5 connect attempt {attempt} failed: {e}")
                if max_attempts > 0 and attempt >= max_attempts:
                    raise
                log.info(f"Retrying in {interval}s...")
                time.sleep(interval)

    def fetch_candles(self, symbol, timeframe, count=50000):
        """
        Fetch up to 50,000 candles using copy_rates_from_pos.
        Always returns fresh live data (pos=0 = current bar, going back).
        Returns list of normalized dicts sorted ascending by time.
        """
        try:
            rates = self.mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
            if rates is None or len(rates) == 0:
                err = self.mt5.last_error()
                log.warning(f"No data for {symbol} tf={timeframe}: {err}")
                return []
            return [self._normalize(r) for r in rates]
        except Exception as e:
            log.error(f"fetch_candles error {symbol}: {e}")
            self.reconnect()
            return []

    def fetch_ticks(self, symbol, from_dt, to_dt):
        """Fetch raw tick data between two UTC datetime objects."""
        try:
            ticks = self.mt5.copy_ticks_range(
                symbol, from_dt, to_dt,
                self.mt5.COPY_TICKS_ALL,
            )
            if ticks is None:
                return []
            return [{
                "time": datetime.fromtimestamp(
                    t["time"], tz=timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
                "bid": float(t["bid"]),
                "ask": float(t["ask"]),
                "last": float(t["last"]),
                "volume": int(t["volume"]),
                "flags": int(t["flags"]),
            } for t in ticks]
        except Exception as e:
            log.error(f"fetch_ticks error {symbol}: {e}")
            return []

    def get_symbols(self):
        """Returns list of all available symbol names from broker."""
        try:
            symbols = self.mt5.symbols_get()
            return [s.name for s in symbols] if symbols else []
        except Exception as e:
            log.error(f"get_symbols error: {e}")
            return []

    def get_timeframe_constants(self):
        """Return dict of timeframe name → MT5 constant."""
        return {
            "M5": self.mt5.TIMEFRAME_M5,
            "M15": self.mt5.TIMEFRAME_M15,
            "H1": self.mt5.TIMEFRAME_H1,
            "H4": self.mt5.TIMEFRAME_H4,
            "D1": self.mt5.TIMEFRAME_D1,
        }

    def _normalize(self, rate):
        """Convert MT5 rate struct to the standard cache dict format."""
        return {
            "time": datetime.fromtimestamp(
                rate["time"], tz=timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S+00:00"),
            "open": float(rate["open"]),
            "high": float(rate["high"]),
            "low": float(rate["low"]),
            "close": float(rate["close"]),
            "volume": int(rate["tick_volume"]),
            "source": "mt5",
        }
