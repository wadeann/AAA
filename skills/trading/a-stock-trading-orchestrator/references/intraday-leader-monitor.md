# Intraday Leader Monitor

## Purpose

Use a deterministic `no_agent` cron as a continuous discovery backstop for fast A-share leaders. The monitor discovers and notifies; it does not place orders.

## State Machine

`none -> breakout_alert -> confirmed -> expired`

- `breakout_alert`: a completed 30-minute bar closes above a prior platform high with volume confirmation. Notify immediately with "等待回踩确认".
- `confirmed`: the next bar(s) retest without falling back below the platform high and the shared Chan engine reports a buy point. Notify once as a buy signal, then route through the existing risk/intent pipeline.
- `expired`: no confirmation within the configured age window, or a confirmed signal is too old for a new entry. Keep it as historical evidence only.

## Data Separation

- Use raw 30-minute bars for breakout/retest timing. Inclusion processing can merge away the retest bar.
- Use inclusion-processed bars for classical fractals, strokes, segments, pivots and divergence.
- Require at least 100 recent 30-minute bars and reject stale/incomplete responses.

## Candidate Universe

Every polling cycle must inspect:

1. The latest valid watchlist (historical watchlist alone is insufficient).
2. A same-day abnormal-move universe from a structured market query, such as gain >5%, adequate turnover, non-ST and leader/sector conditions.

If the market query fails, preserve watchlist coverage but do not fabricate additional symbols.

## Deduplication

Persist state atomically under `trading/monitor/`. The event key must include symbol, breakout bar index and confirmation bar index. This prevents repeated alerts on every five-minute tick and prevents a later bar from masquerading as a new signal. Separate alert and confirmed keys so the confirmation can be notified once after an earlier alert.

## Notification Contract

For `no_agent=True`, stdout is delivered verbatim to Feishu. Keep it concise:

```text
📊盘中龙头监控 | 仅通知，不自动下单
⚠️突破预警 代码 现价X | 放量突破中枢上沿X，等待回踩确认
```

or:

```text
📊盘中龙头监控 | 仅通知，不自动下单
🟢买入信号 代码 现价X | 30分钟二买确认，需走风控闸门
```

Do not claim an order was submitted from the monitor. The execution consumer must independently produce risk approval, approved intent, order ID, order回查 and audit evidence.

## Driven by alert_plan files (not just watchlist)

The monitor reads both:
1. `~/.hermes/trading/watchlists/watchlist_*.json` — prior-day watchlist (latest day <= today)
2. `~/.hermes/trading/alert_plans/alert_plan_*.json` — close-generated buy/sell alert plans (latest day <= today)

For each alert_plan entry, `price_hit()` decides whether the live price crossed the threshold:
- `direction=buy` → triggers when `price >= buy_alert.above`
- `direction=sell` → triggers when `price <= sell_alert.below`

A price hit wakes a full audit (`evaluate()` → 100x30m Chan + news + fundamentals), and only if both `fundamental_confirmed` and `news_confirmed` are true does it write a candidate. **A price hit never authorizes an order by itself** — it routes through the risk/intent/order chain.

**To make the monitor watch a specific stock, write an alert_plan file** for today, e.g. `~/.hermes/trading/alert_plans/alert_plan_2026-08-17.json` with the buy/sell thresholds from the analysis. This is the correct way to watch a stock intraday — NOT a new dedicated cron per stock (see `references/alert-plan-format.md` in a-stock-operation-guide).

## Silent-by-design behavior

For `no_agent=True`, stdout is delivered verbatim to Feishu. **Empty stdout is correct and expected when no alert_plan threshold is hit.** The monitor is notification-only; it does not spam Feishu every 5 minutes. A manual test run:

```bash
cd /home/ubuntu/.hermes && timeout 60 python3 scripts/intraday_leader_monitor.py
```

- No output → prices did not cross any threshold. This is the healthy steady state, NOT a bug.
- Script lives at `~/.hermes/scripts/intraday_leader_monitor.py` (NOT `cron/scripts/`).
- To confirm the scheduler actually fires it, check `last_run_at` via `hermes cron list` / `cron/jobs.json`; `last_run_at: null` means the scheduler never picked it up (see trading-infra-troubleshooting §24).

## Verification

Test all of the following:

- Non-trading day exits silently.
- First alert is emitted once.
- Duplicate polling of the same alert is silent.
- A later confirmation emits once.
- A signal older than the freshness window is not emitted as a current buy.
- A monitor run never calls the order tool.
- JSON state is written atomically and malformed state fails closed.

The session's synthetic test used the sequence `alert -> duplicate alert -> confirmed` and verified exactly two notifications and two distinct persisted event keys.