# AGY Evolution Rounds R1-R10 — 2026-09-01

## Trigger
User: "你一个连板股都没抓到" + "直接自动迭代100轮，不要问我"
Before: 月收益+19%（累计）、86.5%现金闲置、系统沉迷做T/小波段/尾盘清仓
After: 全市场涨停扫描、竞价识别、仓位解锁（20-35% per票）、早盘调度器

## Round-by-round

### R1 — tail-session limit-up immunity
**File**: `close_session_scan.py`
**Change**: Before executing any sell at close, check if the stock is limit-up today. If yes, skip sell.
**Bug found by AGY R4**: Only supported 10% boards, missed ChiNext(20%)/STAR(20%)/BSE(30%)/ST(5%) → Fixed in R4.

### R2 — position size unlock
**File**: `risk_server/main.py`
**Change**: `adjusted_position_pct` from 0.1→ strategy-aware (limit-up 20%, swing 35%, panic 15%).

### R3 — limit_up_scanner
**File**: `scripts/limit_up_scanner.py` (new)
**Endpoint**: scans full market via wencai every 5min, identifies 1st/2nd/3rd+ board stocks
**Cron**: `*/5 * * * 1-5`, script-based
**Bug found by AGY R4**: `price` field was `change_pct` not actual price; `record_type: shadow_candidate` not `candidate`
**Fix in AGY R4**: Both payload bugs fixed.

### R4 — AGY audit found 3 fatal bugs
**Bugs**:
1. `limit_up_scanner.py` price = change_pct (would buy at 10.02% not 35.80)
2. `record_type: shadow_candidate` → gate doesn't consume shadow_candidate
3. `close_session.py` only handles 10% limit-up
**Also fixed**: `is_trade_ready()` multi-strategy routing. If candidate has `breakout_confirmed=True` or catalyst starts with `limit_up`/`call_auction`, skip Chan buy-point check.

### R5 — call_auction_scanner
**File**: `scripts/call_auction_scanner.py` (new)
**Logic**: 09:25 auction → 高开3%-7.5% + 爆量比≥8% + industry Top3
**Cron stopped R9**: Replaced by morning_master_orchestrator.

### R6 — risk position guardrails
**File**: `risk_server/main.py` and `autonomous_trade_pipeline.py`
**Position caps per strategy**:
- limit_up/lianban: 20%
- call_auction: 20%
- chanlun/swing: 35%
- panic: 15%
- Total portfolio cap: 80%

### R7 — explode_monitor
**File**: `scripts/explode_monitor.py` (new)
**Logic**: checks held positions from limit_up scanner → if price < limit_price - 3% → generate sell candidate
**Cron**: `*/5 10-14 * * 1-5`

### R8 — sentiment cycle position modulation
**File**: `risk_server/main.py`
**Logic**: checks live limit_up count via wencai → ice(≤15)空仓/ recession(≤30)半仓/ others 正常

### R9 — AGY architecture audit
AGY found 2 P0 bugs:
1. **Position lock**: `normalize_intent()` used hardcoded 100 shares, not `total_assets × adjusted_pct`
2. **No early-morning orchestration**: call_auction_scanner ran independently, gate didn't know it

### R10 — P0 fixes
**File**: `scripts/autonomous_trade_pipeline.py` — `normalize_intent()` now accepts `total_assets`+`adjusted_pct` params
**File**: `scripts/morning_master_orchestrator.py` (new) — 09:24:50 UTC orchestrator
**File**: `scripts/run_autonomous_trades.py` — queries exec MCP for balance before normalize_intent

## Key architectural changes

### Before R1-R10
- Only Chan theory entry: must have buy/sell point + vol confirmation + sector resonance
- 100 shares per position (4.7万 per trade out of 47.6万 total)
- tail-session sell by default (sell at every possibility)
- Pre-selected 5 stocks each day

### After R1-R10
- **Multi-strategy routing**: `is_trade_ready()` checks `catalyst_type` prefix → 
  - `limit_up`/`call_auction`: skip Chan, require only volume + sector + break structure
  - `chanlun`/normal: Chan buy point required
- **Dynamic position**: `total_assets × adjusted_pct / price` instead of hardcoded 100
- **Market scan**: 3 new scanners (limit_up, call_auction, explode_monitor)
- **Morning orchestration**: sequential 09:25 auction scan → 09:25:20 limit_up scan → 09:25:35 gate

## New cron jobs after R10
| Job | Schedule | Script | Type |
|-----|----------|--------|------|
| morning-master-orchestrator | 24 1 * * 1-5 | orchestrator.py | no_agent + sleep-wake |
| limit-up-scanner | every 5min | limit_up_scanner.py | no_agent |
| call-auction-scanner | (merged into orchestrator) | — | — |
| explode-monitor | */5 10-14 * * 1-5 | explode_monitor.py | no_agent |

## What comes next (R11+)
Per AGY R9 audit: 60-minute K-line + volume profiling, real-time board v3 (call_auction + sector alignment), strategy backtest harness. The user's expectation is 月收益50% — this requires catching at least 2-3 连板 stocks per month at 20% position each.
