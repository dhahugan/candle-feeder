# Migration Plan: Old Cron → candle-feeder

## Current System (what we're replacing)

1. **refresh_mt5_cache.py** — Cron every 5 min, fetches ~200 candles from MT5 EA bridges
2. **mt5_history_cache.py --incremental** — Cron twice daily, deep history from TwelveData
3. MT5 EA bridges (ports 5001-5007) — HTTP API, ~200 candle cap per request

## New System (candle-feeder)

- Docker container polling MT5 terminal directly via RPyC
- 50,000 candles on bootstrap, 500 per 10-second poll
- Same cache files, same paths — zero bot code changes

## Migration Steps

### Phase 1: Parallel Run (Day 1-3)

1. Start candle-feeder alongside existing crons:
   ```bash
   docker compose up -d
   ```

2. Both systems write to the same cache files. The merger's dedup logic
   handles this — no conflicts, no data loss.

3. Monitor candle-feeder health:
   ```bash
   curl -s http://localhost:8080/health | python3 -m json.tool
   ```

4. Compare candle counts daily:
   ```bash
   # candle-feeder should show more candles (50k vs 200-1000)
   for f in /data/cache/mt5_cache/*.json; do
     printf "%-25s %s\n" "$(basename $f)" "$(python3 -c "import json;print(len(json.load(open('$f'))))")"
   done
   ```

### Phase 2: Verify (Day 3-5)

5. Confirm all 9 symbols × 5 TFs have data:
   ```bash
   docker logs candle-feeder | grep "NEW BAR" | tail -20
   ```

6. Confirm no "no data" or reconnect errors in steady state:
   ```bash
   docker logs candle-feeder 2>&1 | grep -c "ERROR"
   # Should be 0 or very low
   ```

7. Confirm trading bots are reading the enriched data:
   ```bash
   # Bots should show candles=500 (or more) instead of candles=200
   strings logs/bot_funded_200k.log | grep "candles=" | tail -5
   ```

### Phase 3: Disable Old Crons (Day 5-7)

8. Comment out the old cron jobs:
   ```bash
   crontab -e
   # Comment these lines:
   # */5 * * * 1-5 cd /home/claude_dev/hive-bot && python3 scripts/cache/refresh_mt5_cache.py ...
   # 0 6,18 * * * python3 -m src.utils.mt5_history_cache --incremental ...
   ```

9. Keep the cron scripts in the repo (don't delete) — safety net if needed.

### Phase 4: Steady State (Day 7+)

10. candle-feeder is the sole data source
11. Monitor via `/health` endpoint
12. Cache files grow monotonically over weeks/months
13. Bootstrap only runs when candle count < 10,000 (e.g., after adding new symbol)

## Rollback Plan

If candle-feeder has issues:

1. Stop candle-feeder: `docker compose stop candle-feeder`
2. Uncomment the old crons: `crontab -e`
3. The old system immediately resumes — same cache files, same paths
4. Trading bots are completely unaffected

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| MT5 terminal crashes | `restart: always` in Docker + candle-feeder auto-reconnects |
| RPyC connection drops | `keepalive=True` + reconnect on error |
| Cache file corruption | Atomic writes (tmp + os.replace) + file locks |
| Bootstrap takes too long | 120s healthcheck start_period, bots read existing cache |
| Wrong symbol names | Auto-resolver tries multiple variations, logs unresolved |
| Redis down | Optional — feeder continues, only pub/sub affected |
