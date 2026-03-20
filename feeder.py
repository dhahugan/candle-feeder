#!/usr/bin/env python3
"""
candle-feeder — Real-time candlestick cache system via MT5 EA bridges.

Polls existing MT5 bridges for candle data, merges into shared cache files.
Uses TwelveData as optional fallback for deep history backfill.

Startup sequence:
  1. Configure logging, start health endpoint
  2. Connect to MT5 bridges (retry until success)
  3. Resolve which symbols the bridges serve
  4. Bootstrap history (bridges + TwelveData)
  5. Connect to Redis (optional)
  6. Enter 10-second polling loop
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
from bridge_client import BridgeClient
from twelvedata_client import TwelveDataClient
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

# OTel: send logs + metrics to SigNoz (AFTER basicConfig so console handler exists)
from telemetry import setup_telemetry, init_metrics, record_new_bar, record_poll_duration, update_cache_depths
try:
    setup_telemetry()
    log.info("OTel telemetry initialized — sending to SigNoz")
except Exception as _e:
    log.warning(f"OTel init failed (non-fatal): {_e}")

# --- Redis (optional) ---
_redis = None


def redis_connect():
    global _redis
    try:
        import redis as redis_lib
        _redis = redis_lib.from_url(config.REDIS_URL, decode_responses=True)
        _redis.ping()
        log.info(f"Redis connected: {config.REDIS_URL}")
    except Exception as e:
        log.warning(f"Redis unavailable ({e}) — continuing without pub/sub")
        _redis = None


def redis_publish(channel, data):
    global _redis
    if _redis is None:
        return
    try:
        _redis.publish(channel, json.dumps(data))
    except Exception as e:
        log.warning(f"Redis publish failed: {e}")
        _redis = None


# --- Graceful shutdown ---
_running = True


def _shutdown(signum, frame):
    global _running
    log.info(f"Received signal {signum}, shutting down...")
    _running = False


signal.signal(signal.SIGTERM, _shutdown)
signal.signal(signal.SIGINT, _shutdown)


def log_cache_summary():
    """Log daily summary of all cache file depths."""
    log.info("=" * 60)
    log.info("CACHE DEPTH SUMMARY")
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


def main():
    global _running

    log.info("=" * 60)
    log.info("CANDLE-FEEDER starting (bridge mode)")
    log.info(f"Bridges: {config.BRIDGE_URLS}")
    log.info(f"TwelveData keys: {len(config.TWELVEDATA_KEYS)}")
    log.info("=" * 60)

    # 1. Start health endpoint
    start_health_server()

    # 2. Ensure cache directory exists
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # 3. Connect to bridges
    client = BridgeClient(config.BRIDGE_URLS)
    client.connect_with_retry(max_attempts=0, interval=10)

    update_state(
        mt5_connected=True,
        mt5_account="bridge",
        mt5_server=client._active_bridge or "none",
    )

    # 4. Resolve symbols
    resolved, unresolved = resolve_symbols(client)
    if not resolved:
        log.error("No symbols resolved — check bridge connectivity")
        sys.exit(1)

    update_state(
        resolved_symbols=resolved,
        unresolved_symbols=unresolved,
    )

    # 5. Bootstrap history
    td_client = TwelveDataClient()
    history_bootstrap.run(client, td_client, resolved)
    update_state(bootstrap_complete=True)
    log_cache_summary()

    # 6. Redis (optional)
    redis_connect()

    # 7. Init OTel metrics (after setup_telemetry, before loop)
    try:
        init_metrics()
    except Exception as e:
        log.warning(f"OTel metrics init warning: {e}")

    # 8. Polling loop
    log.info(f"Entering polling loop: interval={config.POLL_INTERVAL}s, "
             f"candles_per_poll={config.CANDLES_PER_POLL}")

    last_seen = {}
    new_bars_today = 0
    last_summary_day = datetime.now(timezone.utc).day

    while _running:
        cycle_start = time.time()
        cycle_errors = 0

        for canonical in resolved:
            if not _running:
                break

            for tf_name in config.TIMEFRAME_NAMES:
                if not _running:
                    break

                try:
                    candles = client.fetch_candles(
                        canonical, tf_name,
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
                        log.info(f"NEW BAR {key}: {latest} (+{added} candles merged)")
                        record_new_bar(canonical, tf_name)
                        redis_publish("new_bar", {
                            "symbol": canonical,
                            "tf": tf_name,
                            "time": latest,
                            "source": "bridge",
                        })

                except Exception as e:
                    cycle_errors += 1
                    log.error(f"Poll error {canonical} {tf_name}: {e}")

                time.sleep(0.2)  # Brief pause between requests

        elapsed = time.time() - cycle_start
        sleep_time = max(0, config.POLL_INTERVAL - elapsed)

        now = datetime.now(timezone.utc)
        update_state(
            last_poll_completed=now.isoformat(),
            last_poll_duration=elapsed,
            new_bars_today=new_bars_today,
        )

        record_poll_duration(elapsed)
        log.debug(f"Cycle: {elapsed:.1f}s, errors={cycle_errors}, sleeping {sleep_time:.1f}s")

        # Update cache depth gauge for OTel
        try:
            depths = {}
            for f in config.CACHE_DIR.glob("*.json"):
                try:
                    data = json.loads(f.read_text())
                    if isinstance(data, list):
                        depths[f.stem] = len(data)
                except Exception:
                    pass
            update_cache_depths(depths)
        except Exception:
            pass

        # Daily summary
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
