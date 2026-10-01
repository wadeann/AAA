# Cron Reliability Debugging

## Failure pattern
A healthy MCP server can still appear failed when a model provider times out after oversized tool results. Repeated close-review jobs in the same window amplify the load. A watchdog that asks a model to invent or interpret unsupported CLI syntax is not a reliable recovery mechanism.

## Evidence-first sequence
1. Inspect `hermes cron <subcommand> --help` before changing watchdog commands.
2. Inspect `hermes cron list --all` and the raw job state in `~/.hermes/cron/jobs.json`.
3. Compare job names, schedules, prompts, scripts, `no_agent`, `id`, `last_run_at`, and `paused_at`.
4. Reproduce the target Python scripts directly and capture exit status.
5. Run the real close-review script against MCP, then verify the report path and parse every JSONL line.
6. Re-list cron jobs and confirm the intended duplicate is paused or removed.

## CLI facts verified in one session
- `hermes cron list` accepts `--all`, not `--json`.
- `hermes cron run` takes the job ID as a positional argument, not `--job-id`.
- `hermes cron edit <job_id>` supports `--script`, `--no-agent`, `--agent`, `--prompt`, and skill attachment flags.
- A manually launched script without `HERMES_CRON_JOB_ID` may write output under an `unknown` directory; cron execution supplies the real job ID.

## Guardrails
- Do not reinstall or reconfigure MCP when evidence isolates the fault to provider timeout, oversized context, duplicate concurrency, or scheduler prompts.
- Do not claim a cron is fixed from `last_status=ok` alone; `ok` can mean the wrapper completed while the intended business action was wrong.
- Candidate snapshots may write a run marker, but they must not invent stock signals without real market/news/fundamental evidence.

## croniter multi-segment expression pitfall

### The problem
croniter (the Python library used by Hermes Gateway's scheduler to compute next run times) does **not** support Unix cron's comma-separated multi-segment syntax. This is valid Unix cron:

```
31-59/5 1 * * 1-5,*/5 2-3 * * 1-5,*/5 5-6 * * 1-5
```

But croniter rejects it with:

```
Exactly 5, 6 or 7 columns has to be specified for iterator expression.
```

### What happens when croniter fails
1. The cron job's `state` changes to `error` (not `scheduled`).
2. `next_run_at` is set to `null` — the scheduler will never attempt to run it again.
3. The job's `last_run_at` stays at the last successful run — it **does not auto-recover**.
4. The cron-fallback log (at `~/.hermes/logs/cron-fallback.log`) repeats the error every 60 seconds.
5. The job's `last_status` remains `ok` (the last run succeeded), but `state` is `error`.

### Detection
Check `cron/jobs.json` for jobs with `"state": "error"` and `"next_run_at": null`. The `last_error` field will contain the croniter error message.

### Fixes

**Option A — Split into separate cron jobs** (cleanest):
Create multiple cron jobs, each with a simple 5-field expression:
- `31-59/5 1 * * 1-5` (UTC 01:31-01:59 every 5 min)
- `*/5 2-3 * * 1-5` (UTC 02:00-03:59 every 5 min)
- `*/5 5-6 * * 1-5` (UTC 05:00-06:59 every 5 min)

**Option B — Use a broader expression with script-level window check** (simplest):
Use `*/5 1-3,5-6 * * 1-5` (every 5 min across all trading hours) and let the Python script's `in_monitor_window()` function filter out unwanted times (e.g., 09:00-09:30 CST before the auction closes).

### Real-world example
The `intraday-leader-monitor` job (id: `intraday-leader-monitor`) was originally created with the multi-segment expression. After a Gateway restart on 2026-08-17, the cron scheduler lost its in-memory state and tried to recompute the next run via croniter, which failed. The job entered `state=error, next_run_at=null` and never ran again, silently missing 5 trading days of intraday monitoring.

## HTTP 429 cascading failure pattern

### The problem
When multiple LLM-agent cron jobs are scheduled close together in the morning session (< 10 min apart), the first job can exhaust the model provider's token quota (TPM — tokens per minute), causing subsequent jobs to fail with:

```
RuntimeError: HTTP 429: inference tpm exhausted
RuntimeError: HTTP 429: All credentials for model deepseek-v4-flash are cooling down
```

### The cascade
```
09:25 盘前扫描 (LLM + self-evolution 2000行) → 耗尽配额
09:35 开盘狙击 (LLM) → 冷却中，失败
10:00 盘中分析 (LLM) → 冷却中，失败
13:30 盘中分析 (LLM) → 配额恢复，成功
```

### Mitigation
- Remove large skills (especially `a-stock-self-evolution` at 2000+ lines) from intraday LLM agents that only need price checking and sell signals.
- Replace intraday LLM agents with `no_agent=True` Python scripts for deterministic tasks (price scan, threshold checks).
- Keep LLM agent mode only for research-heavy tasks (盘前扫描, 策略进化审计) that genuinely need reasoning.
- Space morning LLM agents at least 10-15 min apart to let quota recover.