# write_candidate() Field Contract (2026-08-27)

## Background

`intraday_leader_monitor.py`'s `write_candidate()` and `run_autonomous_trades.py`'s `is_trade_ready()` must agree on field shape. Old code: `write_candidate()` wrote minimal fields (chan+volume+thesis+price), `is_trade_ready()` demanded 10+ fields including researcher-level ones — all candidates silently blocked.

## Required fields (both buy and sell)

| Field | Type | Source | Mandatory |
|-------|------|--------|-----------|
| `chan_confirmed` | bool | Chan engine | yes |
| `volume_confirmed` | bool | Price/volume check | yes |
| `sector_confirmed` | bool | Sector flow check | yes |
| `fundamental_confirmed` | bool | Financial/order check | buy only |
| `realtime_confirmed` | bool | Realtime order book | yes |
| `news_confirmed` | bool | News search | buy only |
| `leader_score` | int | MCP watchlist or 55 default | yes |
| `quantity` | int | MCP position (sell) or watchlist (buy) | yes |
| `entry_rule` | str | Price trigger description | yes |
| `thesis` | str | Investment rationale | buy: must start with `[缺口逻辑]` unless AGY-approved |

## SELL field exemption (2026-08-27)

`is_trade_ready()` exempts `direction == "sell"` from:
- `sector_confirmed` — stock was already researched during purchase
- `fundamental_confirmed` — ditto
- `realtime_confirmed` — price-trigger is sufficient
- `news_confirmed` — sell trigger is technical, news is contextual
- `leader_score` — no need for held positions
- `thesis` — the Chan structure is the thesis

Sell candidates only need: `chan_confirmed` + `volume_confirmed` + valid sell point + `quantity` from MCP positions.

## AGY-approved thesis prefix exemption (2026-08-27)

`is_trade_ready()` exempts candidates with `llm_approved: true` from the `[缺口逻辑]` thesis prefix check. This is required because AGY's thesis summary does not include this prefix.

## Delivery failure pitfall

`no_agent=True` cron scripts' `print()` stdout IS the Feishu message. Never print raw JSON arrays or large dicts — they cause delivery failure. Print human-readable one-liners:
- `✅ 🟢买入/🔴卖出 CODE N股@price ORDID`
- `⛔ 拒绝 REASON`
- `⏭️ 跳过 REASON`
- `无信号`

Detailed JSON goes to `trading/feedback/trade_gate_report_{today}.json`.

## ⚠️ Write vs Read return-value mismatch (2026-09-01 diagnosis)

**Critical pitfall discovered in Rongchang Bio (688331.SH) debug session:**

`write_candidate()` calls `dedup_append()` which internally calls `check_direction_conflict()` and returns `False` on conflict — **but the caller may ignore the return value**.

**Affected code pattern** (intraday_leader_monitor.py, ~L458):
```python
# write_candidate returns a result dict, not a boolean
result = dedup_append(filepath, [record])
# But caller checks if result is truthy — and dedup_append always returns
# a dict even when the record was rejected!
if result:
    # This branch is ALWAYS taken even on conflict
    ...
```

**How to debug this**: When investigating a direction conflict that should have been caught:
1. `grep -n 'dedup_append\|dedup_append_many' scripts/<script>.py` — find all call sites
2. Check what the caller does with the return value: `if result:` vs `if result.get('written')` vs `if result.get('rejected')`
3. `dedup_append_many()` returns `{"written": count, "rejected": count}` — the caller must check `result["written"] > 0`

**Best practice**: Always check the actual written count from dedup_append_many, not just truthiness:
```python
result = dedup_append_many(path, records)
saved = result.get("written", 0)
blocked = result.get("rejected", 0) or result.get("skipped", 0)
if saved == 0 and blocked > 0:
    logger.warning(f"All {blocked} records rejected (direction conflict?)")
    return  # Don't proceed as if write succeeded
```
