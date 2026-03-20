#!/usr/bin/env python3
"""
candle-feeder — Real-time MT5 candlestick cache system.

Connects to an MT5 terminal via RPyC, pulls candle data directly,
and writes to the shared disk cache that trading bots read from.

Startup sequence:
  1. Configure logging
  2. Start health endpoint
  3. Connect to MT5 (retry until success)
  4. Resolve broker symbol names
  5. Bootstrap deep history (50k candles)
  6. Connect to Redis (optional)
  7. Enter 10-second polling loop
"""

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import config
from mt5_client import MT5Client
from symbol_resolver import resolve_symbols
from merger import merge_and_write
from health import start_health_server, update_state
import history_bootstrap

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger("candle-feeder")

# --- Redis (optional) ---
_redis = None


def redis_connect():
    """Connect to Redis. Returns None if unavailable."""
    global _redis
    try:
        import redis
        _redis = redis.from_url(config.REDIS_URL, decode_responses=True)
        _redis.ping()
        log.info(f"Redis connected: {config.REDIS_URL}")
        return _redis
    except Exception as e:
        log.warning(f"Redis unavailable ({e}) — continuing without pub/sub")
        _redis = None
        return None


def redis_publish(channel, data):
    """Publish to Redis channel. Silently fails if Redis unavailable."""
    global _redis
    if _redis is None:
        return
    try:
        _redis.publish(channel, json.dumps(data))
    except Exception as e:
        log.warning(f"Redis publish failed: {e}")
        _redis = None  # Will skip until reconnected


# --- Graceful shutdown ---
_running = True


def _shutdown(signum, frame):
    global _running
    log.info(f"Received signal {signum}, shutting down gracefully...")
    _running = False


signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)


# --- Daily log summary ---
def log_cache_summary():
    """Log a summary of all cache file depths."""
    log.info("=" * 60)
    log.info("DAILY CACHE DEPTH SUMMARY")
    log.info("-" * 60)
    log.info(f"{'File':<30} {'Candles':>10}   {'Earliest':>12}")
    log.info("-" * 60)
    try:
        for f in sorted(config.CACHE_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                if isinstance(data, list) and data:
                    earliest = data[0].get("time", "?")[:10]
                    log.info(f"{f.stem:<30} {len(data):>10,}   {earliest:>12}")
            except Exception:
                log.info(f"{f.stem:<30}      ERROR")
    except Exception:
        pass
    log.info("=" * 60)


# --- Main ---
def main():
    global _running

    log.info("=" * 60)
    log.info("CANDLE-FEEDER starting")
    log.info("=" * 60)

    # 1. Start health endpoint
    start_health_server()

    # 2. Ensure cache directory exists
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 3. Connect to MT5 (retry forever)
    log.info(f"Connecting to MT5 at {config.MT5_HOST}:{config.MT5_PORT}...")
    client = MT5Client(
        host=config.MT5_HOST,
        port=config.MT5_PORT,
        login=config.MT5_LOGIN,
        password=config.MT5_PASSWORD,
        server=config.MT5_SERVER,
    )
    client.connect_with_retry(max_attempts=0, interval=10)

    update_state(
        mt5_connected=True,
        mt5_account=str(config.MT5_LOGIN),
        mt5_server=config.MT5_SERVER,
        all_broker_symbols=client.get_symbols(),
    )

    # 4. Resolve timeframe constants
    config.TIMEFRAMES = client.get_timeframe_constants()
    log.info(f"Timeframes: {list(config.TIMEFRAMES.keys())}")

    # 5. Resolve broker symbol names
    resolved, unresolved = resolve_symbols(client)
    if not resolved:
        log.error("No symbols resolved — cannot proceed. Check MT5 login.")
        sys.exit(1)

    update_state(
        resolved_symbols=resolved,
        unresolved_symbols=unresolved,
    )

    # 6. Bootstrap deep history
    log.info("Starting history bootstrap...")
    history_bootstrap.run(client, resolved)
    update_state(bootstrap_complete=True)
    log_cache_summary()

    # 7. Connect to Redis (optional)
    redis_connect()

    # 8. Enter polling loop
    log.info(f"Entering polling loop: interval={config.POLL_INTERVAL}s, "
             f"candles_per_poll={config.CANDLES_PER_POLL}")

    last_seen = {}
    new_bars_today = 0
    last_summary_day = datetime.now(timezone.utc).day

    while _running:
        cycle_start = time.time()
        cycle_errors = 0

        for canonical, broker_symbol in resolved.items():
            if not _running:
                break

            for tf_name in config.TIMEFRAME_NAMES:
                if not _running:
                    break

                tf_const = config.TIMEFRAMES.get(tf_name)
                if tf_const is None:
                    continue

                try:
                    candles = client.fetch_candles(
                        broker_symbol, tf_const,
                        count=config.CANDLES_PER_POLL,
                    )
                    if not candles:
                        continue

                    key = f"{canonical}_{tf_name}"
                    cache_path = config.CACHE_DIR / f"{key}.json"
                    added = merge_and_write(
                        cache_path, candles,
                        max_candles=config.MAX_CANDLES,
                    )

                    # New bar detection
                    latest = candles[-1]["time"]
                    if last_seen.get(key) != latest:
                        last_seen[key] = latest
                        new_bars_today += 1
                        log.info(
                            f"NEW BAR {key}: {latest} "
                            f"(+{added} candles merged)"
                        )
                        redis_publish("new_bar", {
                            "symbol": canonical,
                            "broker_symbol": broker_symbol,
                            "tf": tf_name,
                            "time": latest,
                            "source": "mt5",
                        })

                except Exception as e:
                    cycle_errors += 1
                    log.error(f"Poll error {canonical} {tf_name}: {e}")
                    if "connection" in str(e).lower() or "rpyc" in str(e).lower():
                        try:
                            client.reconnect()
                        except Exception as re:
                            log.error(f"Reconnect failed: {re}")
                        break  # Restart symbol loop after reconnect

                # Rate limit: brief pause between requests
                time.sleep(0.2)

        elapsed = time.time() - cycle_start
        sleep_time = max(0, config.POLL_INTERVAL - elapsed)

        now = datetime.now(timezone.utc)
        update_state(
            last_poll_completed=now.isoformat(),
            last_poll_duration=elapsed,
            new_bars_today=new_bars_today,
            mt5_connected=client._connected,
        )

        log.debug(
            f"Cycle: {elapsed:.1f}s, errors={cycle_errors}, "
            f"sleeping {sleep_time:.1f}s"
        )

        # Daily cache summary
        if now.day != last_summary_day:
            last_summary_day = now.day
            new_bars_today = 0
            log_cache_summary()

        # Interruptible sleep
        sleep_end = time.time() + sleep_time
        while _running and time.time() < sleep_end:
            time.sleep(min(1.0, sleep_end - time.time()))

    log.info("Candle-feeder stopped.")


if __name__ == "__main__":
    main()
