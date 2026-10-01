# Cron Scheduler Paralysis — Stuck Agent Blocks Entire Queue

## Symptoms

- `cronjob list` shows all jobs `state: scheduled`, `enabled: true`
- `last_run_at` timestamps are stale (last run was days ago for ALL jobs)
- Gateway process is running (`ps aux | grep gateway` — PID alive, uptime normal)
- `cron ticker started` log exists in gateway.log
- No new output files in `~/.hermes/cron/output/` for current date
- **No cron jobs fire at all** — not even `no_agent` scripts

## Root Cause

A single LLM agent cron job enters an infinite retry loop due to API failures (e.g., HTTP 504 from proxy/server). The stuck agent thread holds the cron scheduler's execution slot. Since the gateway processes cron jobs **serially** (one at a time), all subsequent jobs — including `no_agent` scripts and other LLM agent jobs — are queued behind the stuck job and never execute.

Common triggers:
- Proxy/API endpoint returns persistent 504 Gateway Timeout
- Provider credit exhaustion causes repeated auth failures
- Model returns empty responses triggering continuous retries

## Diagnosis

```bash
# 1. Confirm gateway is running but cron is dead
ps aux | grep gateway | grep -v grep
date -u && TZ='Asia/Shanghai' date

# 2. Check cron list — look for uniformly stale last_run_at
hermes cron list

# 3. Check errors.log for stuck session ID
grep "$(date -u +%Y-%m-%d)" ~/.hermes/logs/errors.log | grep -v "504\|BLOCKED\|context_compressor" | head -20

# 4. Identify the stuck session — it will have repeated API failures across a wide time range
# Look for a session ID (e.g., 20260816_040814_797f6bda) that appears from yesterday into today
grep "504\|API call failed\|retry\|Empty response" ~/.hermes/logs/errors.log | tail -30
```

Key diagnostic indicators:
- A single `[session_id]` appears across many hours in errors.log
- Repeated `API call failed (attempt 1/3)` → `(attempt 2/3)` → `(attempt 3/3)` → fallback → more failures
- `credential pool provider mismatch` warnings accompany the failures
- `Empty response (no content or reasoning)` retries

## Fix

### Immediate: Restart Gateway

```bash
# Kill the stuck gateway
pkill -f "hermes_cli.main gateway run"

# Wait for it to die
sleep 3

# Restart
cd ~/.hermes && nohup hermes-agent/venv/bin/python -m hermes_cli.main gateway run --replace &

# Verify cron ticker started
sleep 5
grep "Cron ticker started" ~/.hermes/logs/gateway.log | tail -1
```

### Backfill Missed Jobs

After restart, manually trigger missed cron jobs:

```bash
# List jobs to find which ones missed their window
hermes cron list

# Run missed jobs (LLM agent jobs)
hermes cron run <job_id>

# Run missed no_agent script jobs
hermes cron run <script_job_id>
```

**Important**: `hermes cron run` sets `next_run` to now and the gateway scheduler executes on next tick. Jobs execute serially, so multiple `cron run` calls will queue up. Wait for delivery before triggering more.

### Check Results

```bash
# Monitor for new output
ls -lt ~/.hermes/cron/output/ | head -5

# Check gateway log for fire events
grep "cron.*fire\|job.*start\|job.*complete" ~/.hermes/logs/gateway.log | tail -10
```

## Prevention

1. **Reduce agent cron timeout/retry**: If the API endpoint is unreliable, consider lowering max_turns or switching to `no_agent` script mode for critical time-sensitive tasks
2. **Add fallback provider**: Configure `fallback_providers` in `config.yaml` so stuck agents can switch models instead of looping
3. **Watchdog can't save you**: The trading watchdog (`trading_watchdog.py`) is itself a `no_agent` cron — if the scheduler is paralyzed, the watchdog never fires either
4. **Monitor cron health proactively**: Check `hermes cron list` periodically — if `last_run_at` is >1 day old for daily jobs, investigate immediately

## Real Case (2026-08-17)

API endpoint `cli.hajimu.cc.cd` returned persistent 504 Gateway Timeout. A strategy evolution audit cron agent (`20260816_040814_797f6bda`) from Sunday got stuck retrying through Monday morning. All 12 morning cron jobs (pre-market scan, open sniper, watchlist review, trade gate, morning check, intraday leader monitor, watchdog, candidate snapshot) were skipped. Gateway restart + manual `cron run` backfill recovered the afternoon schedule.
