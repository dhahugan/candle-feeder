"""
Auto-detect which symbols the bridges can serve by probing.
Tries fetching 1 candle for each symbol to verify it works.
"""

import logging
from config import SYMBOLS

log = logging.getLogger("candle-feeder.symbols")


def resolve_symbols(bridge_client):
    """
    Probe each symbol against the bridge to find working names.
    Returns (resolved_dict, unresolved_list).
    """
    resolved = {}
    unresolved = []

    for symbol in SYMBOLS:
        candles = bridge_client.fetch_candles(symbol, "H1", count=1)
        if candles:
            resolved[symbol] = symbol
            log.info(f"Resolved {symbol} ✓")
        else:
            unresolved.append(symbol)
            log.warning(f"Could not resolve {symbol} — bridge returned no data")

    log.info(f"Symbol resolution: {len(resolved)} resolved, "
             f"{len(unresolved)} unresolved: {unresolved}")
    return resolved, unresolved
