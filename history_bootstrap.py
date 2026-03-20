"""
Deep historical candle pull — runs once on startup before the polling loop.

For each symbol × timeframe:
  - If cache already has >= BOOTSTRAP_THRESHOLD candles: skip
  - Otherwise: fetch up to 50,000 candles from MT5 and merge into cache
"""

import logging
import time
from config import (
    CACHE_DIR, BOOTSTRAP_THRESHOLD, BOOTSTRAP_FETCH_COUNT,
    TIMEFRAME_NAMES, TIMEFRAMES,
)
from merger import merge_and_write, get_candle_count

log = logging.getLogger("candle-feeder.bootstrap")


def run(mt5_client, resolved_symbols):
    """
    Pull maximum history for all symbols and timeframes.

    Args:
        mt5_client: Connected MT5Client instance
        resolved_symbols: Dict of canonical → broker symbol names
    """
    log.info("=" * 60)
    log.info("HISTORY BOOTSTRAP — pulling deep history from MT5")
    log.info("=" * 60)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    results = []
    total_added = 0
    start = time.time()

    for canonical, broker_symbol in resolved_symbols.items():
        for tf_name in TIMEFRAME_NAMES:
            tf_const = TIMEFRAMES.get(tf_name)
            if tf_const is None:
                continue

            key = f"{canonical}_{tf_name}"
            cache_path = CACHE_DIR / f"{key}.json"
            current_count = get_candle_count(cache_path)

            if current_count >= BOOTSTRAP_THRESHOLD:
                log.info(f"Already rich: {key} = {current_count:,} candles — skip")
                results.append((canonical, tf_name, current_count, "skip"))
                continue

            log.info(f"Bootstrapping {key} (current: {current_count:,})...")

            candles = mt5_client.fetch_candles(
                broker_symbol, tf_const, count=BOOTSTRAP_FETCH_COUNT
            )

            if not candles:
                log.warning(f"Bootstrap {key}: no data returned")
                results.append((canonical, tf_name, current_count, "no_data"))
                continue

            added = merge_and_write(cache_path, candles)
            new_count = get_candle_count(cache_path)
            total_added += added

            earliest = candles[0]["time"][:10] if candles else "?"
            latest = candles[-1]["time"][:10] if candles else "?"

            log.info(
                f"Bootstrap {key}: +{added:,} candles added "
                f"(total: {new_count:,}), range: {earliest} → {latest}"
            )
            results.append((canonical, tf_name, new_count, "ok"))

            # Brief pause between large fetches
            time.sleep(0.5)

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
    log.info("")

    return results
