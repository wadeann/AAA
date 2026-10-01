#!/usr/bin/env python3
"""
A-share trading session watchdog: checks every 15 minutes if pre-market/mid-session/
post-market tasks have run today, and auto-retriggers any missed runs.

2026-09 R19: Uses jobs.json for dynamic task discovery instead of hardcoded JOB dict.
            All MCP via MCPClient.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from typing import Any

from config import STATE_DIR
from mcp_client import get_mcp_client

STATE_PATH = STATE_DIR / "watchdog-runs.json"
JOBS_PATH = STATE_DIR / "jobs.json"


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def is_today(s: str | None) -> bool:
    if not s:
        return False
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d.date() == now_utc().date()
    except Exception:
        return False


def run_cmd(cmd: str, timeout: int = 120) -> tuple[int, str]:
    r = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def load_watchdog_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, TypeError):
        return {}


def save_watchdog_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE_PATH)


def load_jobs() -> list[dict[str, Any]]:
    try:
        with open(JOBS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data.get("jobs", data) if isinstance(data, dict) else data
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def parse_cron_schedule(schedule: str) -> list[tuple[int, int]]:
    """Parse cron expression to extract all (hour, minute) tuples in UTC."""
    if not schedule:
        return []
    parts = schedule.strip().split()
    if len(parts) < 2:
        return []
    minute_expr = parts[0]
    hour_expr = parts[1]

    results: list[tuple[int, int]] = []

    # Parse minutes
    minutes: list[int] = []
    if "," in minute_expr:
        for m in minute_expr.split(","):
            if "/" in m:
                base_str, step_str = m.split("/")
                b_val = 0 if base_str == "*" else int(base_str)
                minutes.extend(range(b_val, 60, int(step_str)))
            elif "-" in m:
                a_str, b_str = m.split("-")
                minutes.extend(range(int(a_str), int(b_str) + 1))
            else:
                minutes.append(int(m))
    elif "/" in minute_expr:
        base_str, step_str = minute_expr.split("/")
        b_val = 0 if base_str == "*" else int(base_str)
        minutes.extend(range(b_val, 60, int(step_str)))
    elif minute_expr == "*":
        minutes = list(range(0, 60, 5))
    else:
        try:
            minutes = [int(minute_expr)]
        except ValueError:
            return []

    # Parse hours
    hours: list[int] = []
    if "/" in hour_expr:
        base_str, step_str = hour_expr.split("/")
        b_val = 0 if base_str == "*" else int(base_str)
        hours.extend(range(b_val, 24, int(step_str)))
    elif "," in hour_expr:
        for h in hour_expr.split(","):
            if "-" in h:
                a_str, b_str = h.split("-")
                hours.extend(range(int(a_str), int(b_str) + 1))
            else:
                hours.append(int(h))
    elif "-" in hour_expr:
        a_str, b_str = hour_expr.split("-")
        hours.extend(range(int(a_str), int(b_str) + 1))
    elif hour_expr == "*":
        hours = list(range(0, 24))
    else:
        try:
            hours = [int(hour_expr)]
        except ValueError:
            return []

    for h in hours:
        for m in minutes:
            results.append((h, m))
    return results


def _run_python_script(script_path: str) -> tuple[int, str]:
    """Run a Python module via python3 -m."""
    return run_cmd(f"python3 -m {script_path}")


def main() -> None:
    """Check for missed cron runs and retrigger them."""
    now = now_utc()
    client = get_mcp_client()

    # MCP microservice health check
    for port, svc in [(9001, "Intel"), (9002, "Risk"), (9003, "Exec")]:
        try:
            client.call("tools/list", port=port)
        except Exception as e:
            print(f"Watchdog: MCP {svc}(Port {port}) 异常: {e}", flush=True)

    # Check if today is a trading day
    try:
        if not client.is_trading_day():
            return
    except Exception:
        return

    try:
        jobs = load_jobs()
    except Exception:
        return

    if not jobs:
        print("Watchdog: no jobs found, using script scheduler instead", flush=True)
        return

    # Build watch set: jobs that run during 01:00-07:55 UTC (09:00-15:55 CST)
    watch_jobs: list[dict[str, Any]] = []
    for j in jobs:
        jid = j.get("job_id", j.get("id"))
        if not jid:
            continue
        script = j.get("script") or ""
        name = j.get("name") or ""
        schedule = j.get("schedule") or ""
        if isinstance(schedule, dict):
            schedule = schedule.get("expr", "") or schedule.get("expression", "") or ""
        schedule = str(schedule)

        if not schedule or not script:
            continue
        if j.get("paused_at"):
            continue

        triggers = parse_cron_schedule(schedule)
        if not triggers:
            continue

        # Filter to trading-hour triggers (01:00-07:55 UTC = 09:00-15:55 CST)
        relevant_triggers = [(h, m) for h, m in triggers if 1 <= h <= 7 and m >= 0]
        if not relevant_triggers:
            continue

        # Map script name to Astock Python module path
        module_path = _script_to_module(script)
        if not module_path:
            continue

        watch_jobs.append({
            "id": jid,
            "name": name or script,
            "module": module_path,
            "triggers": relevant_triggers,
        })

    retriggered: list[str] = []
    watchdog_state = load_watchdog_state()
    state_date = now.date().isoformat()
    day_state = watchdog_state.setdefault(state_date, {})

    for wj in watch_jobs:
        jid = wj["id"]
        name = wj["name"]

        if day_state.get(jid):
            continue  # already attempted recovery today

        # Find the most recent trigger that should have already fired
        last_passed: dt.datetime | None = None
        for h, m in sorted(wj["triggers"]):
            target = dt.datetime.combine(now.date(), dt.time(h, m, 0), tzinfo=dt.timezone.utc)
            if now >= target:
                last_passed = target

        if last_passed is None:
            continue  # nothing due yet

        # Check if job has already run today
        has_run = False
        for j in jobs:
            jid2 = j.get("job_id", j.get("id"))
            if jid2 != jid:
                continue
            last_run = j.get("last_run_at") or j.get("last_run")
            if is_today(last_run):
                has_run = True
                day_state[jid] = {"status": "already_ran_today"}
                break
        if has_run or day_state.get(jid):
            continue

        # Job hasn't run today — trigger recovery via direct Python invocation
        rc2, output = _run_python_script(wj["module"])
        day_state[jid] = {
            "attempted_at": now.isoformat(),
            "returncode": rc2,
            "output_tail": output[-500:],
        }
        retriggered.append(name + (" OK" if rc2 == 0 else " FAIL"))

    # Prune old state (keep last 10 days)
    for old_date in sorted(watchdog_state)[:-10]:
        del watchdog_state[old_date]
    save_watchdog_state(watchdog_state)

    if retriggered:
        print(f"发现漏发轮次，已自动补跑: {', '.join(retriggered)}", flush=True)


def _script_to_module(script: str) -> str | None:
    """Map myhermes script names to Astock module paths."""
    mapping = {
        "morning_master_orchestrator.py": "orchestrator.morning_master",
        "direct_executor.py": "execution.direct_executor",
        "full_market_intraday_discovery.py": "discovery.full_market_discovery",
        "run_autonomous_trades.py": "execution.batch_trade_gate",
        "close_session_scan.py": "defense.close_session_defense",
        "intraday_leader_monitor.py": "discovery.leader_monitor",
        "call_auction_scanner.py": "discovery.auction_scanner",
        "limit_up_scanner.py": "discovery.limitup_scanner",
        "intraday_theme_trigger.py": "discovery.theme_trigger",
        "explode_monitor.py": "defense.explode_monitor",
        "sector_flow.py": "intelligence.sector_flow",
        "performance_reporter.py": "evolution.performance_reporter",
        "evolution_audit.py": "evolution.strategy_audit",
        "market_regime_check.py": "market_regime_check",
        "condition_evaluator.py": "condition_evaluator",
        "sentiment_engine.py": "core.sentiment_engine",
    }
    # Try to strip path prefixes
    base = script.split("/")[-1]
    return mapping.get(base, None)


if __name__ == "__main__":
    main()
