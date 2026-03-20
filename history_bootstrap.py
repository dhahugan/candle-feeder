"""
Deep historical candle pull — runs once on startup before the polling loop.

Uses bridges for recent data + TwelveData for deeper history backfill.
"""

import logging
import time
from config import (
    CACHE_DIR, BOOTSTRAP_THRESHOLD, BOOTSTRAP_FETCH_COUNT,
    TIMEFRAME_NAMES, TD_BOOTSTRAP_COUNT,
)
from merger import merge_and_write, get_candle_count

log = logging.getLogger("candle-feeder.bootstrap")


def run(bridge_client, td_client, resolved_symbols):
    """
    Pull maximum history for all symbols and timeframes.

    Bridge provides ~200 recent candles. TwelveData provides ~800 historical.
    Combined via merge: ~1000 candles per symbol/TF on first bootstrap.
    Cache grows monotonically over time via polling.
    """
    log.info("=" * 60)
    log.info("HISTORY BOOTSTRAP — pulling data from bridges + TwelveData")
    log.info("=" * 60)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    total_added = 0
    start = time.time()

    for canonical in resolved_symbols:
        for tf_name in TIMEFRAME_NAMES:
            key = f"{canonical}_{tf_name}"
            cache_path = CACHE_DIR / f"{key}.json"
            current_count = get_candle_count(cache_path)

            if current_count >= BOOTSTRAP_THRESHOLD:
                log.info(f"Already rich: {key} = {current_count:,} candles — skip")
                results.append((canonical, tf_name, current_count, "skip"))
                continue

            log.info(f"Bootstrapping {key} (current: {current_count:,})...")
            added_total = 0

            # 1. Bridge data (recent ~200 candles)
            bridge_candles = bridge_client.fetch_candles(
                canonical, tf_name, count=BOOTSTRAP_FETCH_COUNT
            )
            if bridge_candles:
                added = merge_and_write(cache_path, bridge_candles)
                added_total += added
                log.info(f"  Bridge: +{added} candles ({len(bridge_candles)} fetched)")

            # 2. TwelveData backfill (historical ~800 candles)
            if td_client and td_client.enabled:
                td_candles = td_client.fetch_candles(
                    canonical, tf_name, count=TD_BOOTSTRAP_COUNT
                )
                if td_candles:
                    added = merge_and_write(cache_path, td_candles)
                    added_total += added
                    log.info(f"  TwelveData: +{added} candles ({len(td_candles)} fetched)")
                time.sleep(1)  # Rate limit TwelveData

            new_count = get_candle_count(cache_path)
            total_added += added_total
            results.append((canonical, tf_name, new_count, "ok" if added_total > 0 else "no_data"))

            time.sleep(0.2)

    elapsed = time.time() - start

    # Print summary table
    log.info("")
    log.info("=" * 60)
    log.info("BOOTSTRAP COMPLETE")
    log.info(f"Duration: {elapsed:.1f}s | New candles added: {total_added:,}")
    log.info("-" * 60)
    log.info(f"{'Symbol':<12} {'TF':<6} {'Candles':>10}   Status")
    log.info("-" * 60)
    for symbol, tf, count, status in results:
        log.info(f"{symbol:<12} {tf:<6} {count:>10,}   {status}")
    log.info("=" * 60)

    return results
