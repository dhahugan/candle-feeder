"""
Auto-detect correct OANDA MT5 symbol names on startup.
Matches canonical names (EURUSD, US30) to broker-specific names.
"""

import logging
from config import KNOWN_SYMBOLS

log = logging.getLogger("candle-feeder.symbols")


def resolve_symbols(mt5_client):
    """
    Fetch all symbols from broker, match against known variations.

    Returns:
        dict: {"EURUSD": "EURUSD", "US30": "US30USD", ...}
        Symbols that could not be resolved are logged and skipped.
    """
    available = set(mt5_client.get_symbols())
    log.info(f"Broker has {len(available)} symbols available")

    resolved = {}
    unresolved = []

    for canonical, variants in KNOWN_SYMBOLS.items():
        found = False
        for v in variants:
            if v in available:
                resolved[canonical] = v
                log.info(f"Resolved {canonical} → {v}")
                found = True
                break
        if not found:
            unresolved.append(canonical)
            log.warning(
                f"Could not resolve {canonical} — tried {variants}. "
                f"Check /symbols endpoint for full broker symbol list."
            )

    log.info(f"Symbol resolution: {len(resolved)} resolved, "
             f"{len(unresolved)} unresolved: {unresolved}")
    return resolved, unresolved
