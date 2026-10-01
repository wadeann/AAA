# a-stock-trading-orchestrator — A-Stock Trading Session Orchestrator

Master timing orchestrator for A-share full-session trading: premarket scan, opening sniper, intraday evaluation, close review, and emergency stop. Covers the entire daily trading window from 09:25 to 15:10 CST with deterministic cron scheduling, no_agent script pipelines, and LLM-agent deep-review gates.

## 🔴 Iron Rules (All Windows)

### 09:25 Must NOT Use Wencai for Real-Time Auction
Wencai auction data lags 60-150 seconds. The 09:25-09:30 window is the lowest-tolerance 300 seconds of the day. Use local quote API for auction matrix filtering instead.

**09:25 Auction Matrix** (implemented in `ignition_v1_sniper.py evaluate_auction()`):
1. Auction change +1.5% ~ +4.5%
2. Auction volume ratio >= 2% of T-1 volume
3. Unmatched net buy orders > 0
4. Sector resonance > 0

**Composite Score** = T-1 Ignition score (40%) + Auction price-volume (40%) + Sector resonance (20%)

### Data Timestamp Must Be Explicitly Labeled
Before 09:30, all MCP quote APIs return previous day's close. Label data correctly:
- Before 09:30: "昨日收盘价" (yesterday's close)
- 09:30-09:35: "竞价数据" (auction data)
- 09:35+: current price

Output template:
```
数据时间戳显示为昨日（YYYY-MM-DD）收盘，目前未开盘
```

### Feishu Output = Command Channel, Not Report Channel
Maximum 3 lines. Full reports go to files.

Format:
```
[emoji window] | 大盘XXXX +/-X% | 账户XXXX
HOLD/操作 代码 现价 缠论结构简述 | 其次
缠论风控备注或"无异常"
```

## Golden Timeline (v4)

| Window | CST Trigger | UTC | cron job ID | Loaded Skills | Description |
|--------|-------------|-----|-------------|---------------|-------------|
| Candidate Snapshot | 09:15 | 01:15 | `00621b27537f` | no_agent script | Create candidates.jsonl |
| Morning Scheduler | 09:24 | 01:24 | `c32583d2193e` | no_agent script | Auction scan → limit-up scan → risk gate |
| Premarket Scan | 09:25 | 01:25 | `da4d9fc60390` | `researcher` + `cron-feishu-format` + `operation-guide` | 5/10-day gain + ladder + catalyst trace |
| Open Watchlist Review | 09:35 | 01:35 | `open-watchlist-review` | no_agent script | Yesterday limit-up watchlist review |
| Opening Sniper | 09:40 | 01:40 | `bdd5437b4b7c` | `operation-guide` + `chanlun-analyzer` + `chanlun-risk` | First 5min bar verification |
| Intraday Leader Monitor | Every 5min 09:31-14:57 | */5 1-3,5-6 | `intraday-leader-monitor` | no_agent script | Price trigger → pre-screen → awaiting_llm_review |
| Price Trigger LLM Review | Every 15min (:02 offset) | :02/:17/:32/:47 | `009a6882d5cc` | `price-trigger-llm-review` | LLM deep review → APPROVE/REJECT/HOLD |
| Full Market Discovery | Every 5min 09:31-14:51 | 31-56/5 1-3,5-6 | `3186985bc23d` | no_agent script | 5 parallel wencai entrances → `intraday_latest.json` |
| Theme Detonation | Every 5min 09:33-14:53 | 33-58/5 1-3,5-6 | `fa763ca049ba` | `a-stock-short-horizon-sniper-playbooks` | Top 8 themes x 8 seeds → deep screen → iron gate |
| Intraday 10:00 Scan | 09:50 | 01:50 | `907b2ca9dcdf` | no_agent script | Position + 30min Chan → buy/sell points → candidates |
| Intraday 13:30 Scan | 13:50 | 05:50 | `907b2ca9dcdf` (reused) | no_agent script | Same as above |
| Close Session 14:15 | 14:16-14:56 every 10min | 6:16-6:56 | `7f5916e3340f` | no_agent script | Normal: sell only; Panic (SH -1.5%): add panic buy |
| Trade Gate | Every 15min from 09:55 | 55 1-6 | `autonomous-trade-gate` | no_agent script | Central execution: skip awaiting_llm_review → process llm_approved → risk → register → order |
| Account EOD Snapshot | 15:10 | 07:10 | `account-eod-snapshot` | no_agent script | Account data → Feishu |
| Next-Day Alert Plan | 15:20 | 07:20 | `build-next-day-alert-plan` | no_agent script | Watchlist + positions → alert_plan.json |
| Strategy Evolution Audit | 15:22 | 07:22 | `fd611873c01f` | `a-stock-self-evolution` + `cron-feishu-format` | Statistics + rule upgrade |
| Limit-up Review & Watchlist | 15:25 | 07:25 | `limitup-watchlist-close` | no_agent script | Wencai limit-up → screen → leader_score → watchlist |
| Sector Flow | 15:30 | 07:30 | `770b03427acb` | `chanlun-screener` + `cron-feishu-format` | Ladder + duration + archive |
| Close Review | 15:35 | 07:35 | `b90d3891ac50` | no_agent script | 4-index + position Chan + volume + next-day ops |
| Weekly Watchlist | Fri 20:00 | 12:00 | `5e1d54df5743` | `a-stock-researcher` | Deep watchlist maintenance |

## Step 0: Priority Action Items (All Windows)

Before any discovery flow, read `~/.hermes/trading/strategy-feedback.md` and extract [P0]/[P1] unexecuted items. P0 (e.g., reduce position, stop-loss) → direct SELL TradeIntent. P1 → merge with new signals.

## Window A: Premarket Scan (09:25 CST)

Three core sections:

**Section A: Market Wave Premarket Judgment**
- Parallel: `MCPClient.instance().call('fetch_market_health')` + wencai sector flow + index MA20
- Determine market_condition (BULL/NEUTRAL/BEAR) and market_phase (BULL_3/BULL_4/etc.)

**Section B: Auction Candidate Scan**
- Read `candidates.json` (T-1 postmarket wencai scan)
- Fetch 09:25 auction snapshot per candidate
- Auction matrix filter → Top 2

**Section C: Position 8-Dimension Deep Analysis**
- News check mandatory per position
- Full 8-dimension: trend → capital → sector → market → cost → wave → 3-scenario → ops → risk level

## Window B: Opening Sniper (09:35 CST)

First 5-minute K-line just closed. Verify auction candidates + check position open risk.

**Input sources**: Premarket auction candidates + current positions (both empty → cancel).

**Auction Open Classification**:
| Verdict | Condition | Action |
|---------|-----------|--------|
| Green: True Breakout | 5min gain > auction gain AND 5min vol > auction vol*0.5 AND yang-line AND sector inflow | Chase confidence 0.72, position 3-5%, time_horizon 1d |
| Yellow: Pending | Price within auction +/-1.5%, volume moderate | Defer to 10:00 re-eval |
| Red: False Breakout | 5min price < auction and drop >1.5%, yin-line, net big order outflow | Abandon |

## Window C: Intraday Evaluation (09:50 / 13:50 / 14:15 CST)

All converted to no_agent Python scripts. Script directly connects MCP ports for data → Chan analysis → write candidates → trigger gate.

**Position 6-dimension mini-analysis** per stock: intraday → capital → market correlation → cost → wave → ops + risk rating.

**New opportunity constraints** (more conservative than premarket):
- General: confidence cap 0.70, time_horizon 1d, max_position 5%
- Main uptrend leader relay: confidence base 0.75
- Position major announcement: confidence base 0.80

## Window D: Emergency Stop (Manual Trigger)

**Step 1**: Cancel all orders unconditionally. `MCPClient.instance().call('get_orders')` → `MCPClient.instance().call('cancel_order')` per order.

**Step 2**: Assess reduction needs:
- Market health < 30: Clear/halve all positions, `auto_execute_reduction: true`
- Daily loss >= 5%: Stop-loss reduction no confirmation needed
- Daily loss >= 3% and < 5%: Allow stop-loss/reduction

## Close Review (15:10 CST)

Delegate review subagent to:
1. Collect trades + orders
2. Account PnL stats
3. Position close prices
4. News post-hoc attribution
5. Confidence segment win rate + catalyst_type PnL distribution
6. B-wave verification table
7. Structured action_items
8. Strategy feedback archive (append to `~/.hermes/trading/strategy-feedback.md`)

## Multi-Strategy Routing Architecture

`is_trade_ready()` passage conditions by catalyst_type prefix:

| Strategy | catalyst prefix | Chan buy point | Volume-price confirm | Sector resonance | News verify |
|----------|----------------|:--------------:|:-------------------:|:----------------:|:-----------:|
| Chan/Band | chanlun/default | Required | Required | Required | Required |
| Limit-up/Ladder | limit_up_* | Skip | Required | Required | Required |
| Call Auction | call_auction_* | Skip | Required | Required | Required |
| Explode Stop | explode_* | Skip | N/A | Skip | Skip |

## Leader Lifecycle Framework

```
Phase 1: Leader Confirmation (1-to-2 or 2-to-3) → Core Buy Point
  Golden entry: Divergence-to-consensus volume board
  Position: 25-35% (soul stock during main uptrend)

Phase 2: Leader Strengthening (3+) → Concurrently mine supplements
  Hold leader, mine same-theme low-position seeds
  Supplement: ≤5% probe, confirm then add

Phase 3: Leader Acceleration (5-6) → No new opens, no chase
  Prohibited: shrink-volume board tail-end queue, gap-up cannonball catch

Phase 4: Leader Break/Gap Divergence (7+) → Switch window
  Switch to supplement dragon (already held from Phase 2)

Phase 5: No Main Leader (Chaos/Ebb) → Small first-board probe
  ≤5% position
```

## Dynamic Position Calculation (R10 P0 Fix)

`normalize_intent(candidate, total_assets, adjusted_pct)`:
- Limit-up/Ladder = total_assets × 20%
- Chan/Band = total_assets × 35%
- Panic bottom-fish = total_assets × 15%
- Total cap: 80%

## Cron Job Creation Iron Rules

1. **Multi-segment cron expressions incompatible**: Use single-segment coarse cron + script-level time gating
2. **No two cron jobs at same minute** → queue blocking
3. **No large skill loaded into cron prompt** → agents drown in rules, don't execute data collection
4. **Pure data collection → no_agent=True + script** (HTTP POST directly to MCP ports)
5. **enabled_toolsets must be complete** for LLM agent mode: `["terminal", "file", "web", "search", "delegation"]`

## Monday Open Recovery Checklist

Agent must self-check on Monday trading day without waiting for user:
1. `cronjob action=list` → check LLM cron `last_run_at` is today
2. If last_run_at is last Friday → manual `cronjob action=run` each
3. Confirm MCP connectivity: 4-index quotes + trading session + positions + PnL
4. Check Feishu config: `config.yaml` must have `feishu: enabled: true`

## Cross-Pipeline Direction Conflict

**Same-direction blocking only**: `check_direction_conflict` blocks a second buy if buy already executed today (same for sell). Opposite directions (buy→sell or sell→buy) are allowed for T-trading corrections.

Detection based on executed orders, not candidates. Each script must read day's full JSONL before writing own candidate.

## Key References (abridged)

- `references/negative-decision-notification.md` — 09:25 no-buy notification contract
- `references/intraday-leader-monitor.md` — Leader breakout monitor contract
- `references/autonomous-execution-closure.md` — Autonomous trade closure contract
- `references/cross-pipeline-direction-conflict.md` — Cross-pipeline direction conflict fix
- `references/sector-volume-breakout-pattern.md` — Sector resonance low-position mid-army breakout pattern
- `references/playbook-pipeline.md` — Premarket playbook card generation pipeline
- `references/full-market-intraday-discovery.md` — Full market intraday discovery system
