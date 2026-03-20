"""
Atomic merge/dedup/write logic for candle cache files.

INVARIANTS:
  - Total candle count NEVER decreases
  - Writes are always atomic (tmp + os.replace)
  - File locks prevent corruption from concurrent access
  - Empty new_candles = no file modification
"""

import json
import logging
import os
from pathlib import Path
from filelock import FileLock

log = logging.getLogger("candle-feeder.merger")


def merge_and_write(cache_path, new_candles, max_candles=50000):
    """
    Merge new candles into existing cache file.

    Args:
        cache_path: Path to the JSON cache file
        new_candles: List of candle dicts with 'time' field
        max_candles: Maximum candles to keep (trim oldest)

    Returns:
        int: Number of new candles added (0 if no change)
    """
    if not new_candles:
        return 0

    cache_path = Path(cache_path)
    lock_path = str(cache_path) + ".lock"

    with FileLock(lock_path, timeout=30):
        # Load existing candles
        existing = []
        if cache_path.exists():
            try:
                existing = json.loads(cache_path.read_text())
                if not isinstance(existing, list):
                    existing = []
            except (json.JSONDecodeError, OSError) as e:
                log.warning(f"Cache read error {cache_path.name}: {e}")
                existing = []

        # Upsert by time key — new data overwrites same timestamp
        candle_map = {c["time"]: c for c in existing}
        before = len(candle_map)

        for c in new_candles:
            candle_map[c["time"]] = c

        added = len(candle_map) - before

        # Only write if we actually added new candles
        if added == 0 and len(candle_map) == len(existing):
            return 0

        # Sort ascending by time, trim to max (keep newest)
        merged = sorted(candle_map.values(), key=lambda x: x["time"])
        if len(merged) > max_candles:
            merged = merged[-max_candles:]

        # Atomic write — bots never see a partial file
        tmp = Path(str(cache_path) + ".tmp")
        tmp.write_text(json.dumps(merged, separators=(",", ":")))
        os.replace(str(tmp), str(cache_path))

        return added


def get_candle_count(cache_path):
    """Get current candle count for a cache file. Returns 0 if not found."""
    cache_path = Path(cache_path)
    if not cache_path.exists():
        return 0
    try:
        data = json.loads(cache_path.read_text())
        return len(data) if isinstance(data, list) else 0
    except (json.JSONDecodeError, OSError):
        return 0
