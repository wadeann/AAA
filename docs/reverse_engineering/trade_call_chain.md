# Trade Call Chain — Astock BUY Signal

## Overview

This document traces every function call along the three primary execution paths in Astock: (1) the **live trading** path from cron trigger to order placement, (2) the **discovery** path that feeds candidates into the pipeline, and (3) the **backtest** path that evaluates strategies historically.

---

## 1. Flow Diagram (Text-Based)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         DISCOVERY (CANDIDATE GENERATION)                      │
│                                                                              │
│  full_market_discovery.py         leader_monitor.py                          │
│  discover_wide_pool()             monitor_leaders()                          │
│    ├─ wencai_search (5 queries)     ├─ get_limitup_ladder                    │
│    ├─ dedup                        ├─ get_positions                          │
│    └─ normalized candidates        └─ check_exit_triggers                    │
│                                                                              │
│  limitup_scanner.py                call_auction_scanner.py                   │
│  get_ladder()                      scan_call_auction()                       │
│                                                                              │
│  dragon_screener_engine.py                                                   │
│  grade_dragon_tier()                                                         │
│                                                                              │
│  morning_master.py (09:24:50 cron)                                           │
│  main() ─── orchestrates all scanners above, then hands off to executor      │
└──────────────────────────────────┬───────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                  EXECUTION PIPELINE (direct_executor.py)                      │
│                                                                              │
│  cron: * * * * 1-5 python3 -m execution.direct_executor                      │
│                                                                              │
│  1. main() (direct_executor.py:417)                                          │
│     ├── in_trading_session()             time window guard                   │
│     ├── reconcile_pending_orders()       timeout cancel + fill poll          │
│     ├── load_processed_ids()             read JSONL for "done" set           │
│     ├── load_candidates()                DataManager → candidates list       │
│     ├── is_catalyst_enabled()            strategy cooldown filter            │
│     ├── _check_direction_conflict()      T+1 conflict detection              │
│     ├── sell_only_mode / cooldown / blocked_sector  guard layers             │
│     ├── get_account_snapshot()           total_assets/cash/market_val        │
│     ├── iron_rule_gate()                 AGY 4-in-1 gate (market_regime)     │
│     ├── condition_evaluator.evaluate_all() 8-condition micro-gate            │
│     ├── position sizing (adj_pct × sentiment)                                │
│     ├── normalize_intent()               candidate → TradeIntent             │
│     └── risk_check_and_execute()         pipeline core                       │
│          ├── RiskManager.batch_check()   13-layer risk (risk_manager)        │
│          ├── register_approved_intent()  MCP exec server (port 9003)         │
│          ├── place_order()               MCP exec server (port 9003)         │
│          └── feishu_notifier             trade notification                  │
└──────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         BACKTEST PATH (scripts/backtest_2yr.py)               │
│                                                                              │
│  run_backtest(config_override, profile)                                      │
│    ├── load_strategy_config()           strategy_params.json                 │
│    ├── get_profile(profile)             strategy_profiles.py                 │
│    ├── fetch_klines() (×4000 stocks)    MCP Intel (9001)                     │
│    ├── Main loop over trading days                                          │
│    │   ├── get_regime()                 index-based regime detection         │
│    │   ├── SELL: SellRules.evaluate()   6-rule exit engine                   │
│    │   ├── BUY:                                                              │
│    │   │   ├── screen_candidates()      bar-based hard filter                │
│    │   │   ├── score_momentum_core()    8-factor momentum score              │
│    │   │   └── position sizing          regime_cap × score → quantity        │
│    │   └── equity tracking              cash + position value                │
│    └── statistics: ret, sharpe, mdd, wr, pf, monthly                        │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Live Trading Call Chain (Entry Point: `direct_executor.py`)

### 2.1 Entry Gate

#### `execution/direct_executor.py` — `main()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/execution/direct_executor.py` |
| **Line** | 417 |
| **Signature** | `def main() -> int` |
| **Input** | None (reads system clock, JSONL files, MCP state) |
| **Output** | `0` (success) |
| **What it does** | Cron entry point. Checks trading session (09:30-11:30 / 13:00-14:50), loads candidates from JSONL ledger, runs all filters, position sizing, risk checks, and order placement. Called every minute on trading days. Called by direct subprocess from `morning_master.py` Phase 2.5. |

```
cron line: * * * * 1-5 cd /home/wade/workspace/ai/Astock && python3 -m execution.direct_executor
```

### 2.2 Session Guard

#### `execution/direct_executor.py` — `in_trading_session()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/execution/direct_executor.py` |
| **Line** | 31 |
| **Signature** | `def in_trading_session(now_cst: dt.datetime) -> bool` |
| **Input** | `now_cst` — current CST datetime |
| **Output** | `True` if 09:30-11:30 or 13:00-14:50, else `False` |
| **What it does** | Hard time window guard. Returns early (exit code 0) if outside trading hours, preventing any processing. |

### 2.3 Order Reconciliation

#### `execution/direct_executor.py` — `reconcile_pending_orders()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/execution/direct_executor.py` |
| **Line** | 299 |
| **Signature** | `def reconcile_pending_orders() -> None` |
| **Input** | None (reads MCP state: `get_orders()`, `get_today_trades()`) |
| **Output** | None (side effects: cancel orders, write trade records to JSONL) |
| **What it does** | R37 timeout cancel + fill polling. At 09:29:55 triggers `check_call_auction_unmatched_cancel()` to cancel unfilled auction bids. Cancels orders with >1.5% price deviation or >5 minute timeout. Writes `trade_execution` events for filled trades. |

### 2.4 Candidate Loading

#### `data/__init__.py` — `DataManager.load_candidates()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/data/__init__.py` |
| **Line** | 78 |
| **Signature** | `def load_candidates(self, date: str | None = None) -> list[dict[str, Any]]` |
| **Input** | `date` — ISO date string (default: today) |
| **Output** | `list[dict]` — merged candidates with `candidate_update` / `llm_review` records applied |
| **What it does** | Reads `candidates_{date}.jsonl` from ledger directory. Merges all `record_type == "candidate"` entries with later `candidate_update` or `llm_review` records (keyed by `candidate_id`). Returns the merged list. Each candidate dict contains `symbol`, `direction`, `catalyst_type`, `confidence`, `price`, `quantity`, `agy_approved`, `llm_approved`, `condition_triggers`, etc. |

#### `execution/direct_executor.py` — `load_processed_ids()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/execution/direct_executor.py` |
| **Line** | 39 |
| **Signature** | `def load_processed_ids(date: str) -> set[str]` |
| **Input** | `date` — ISO date string |
| **Output** | `set[str]` — candidate IDs already processed (executed, blocked, rejected, etc.) |
| **What it does** | Scans JSONL for `candidate_event` records with terminal statuses and collects their `candidate_id` values to skip them on re-runs. |

### 2.5 Pre-Filtering (direct_executor.py lines 447–566)

#### `execution/pipeline.py` — `is_catalyst_enabled()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/execution/pipeline.py` |
| **Line** | 39 |
| **Signature** | `def is_catalyst_enabled(catalyst_type: str | None, params: dict | None = None, direction: str | None = None) -> bool` |
| **Input** | `catalyst_type` (e.g. `"dragon_screener"`, `"limit_up_ladder"`), optional `params`, `direction` |
| **Output** | `bool` — `True` if the catalyst type is enabled (or is a sell signal, which bypasses) |
| **What it does** | Checks `strategy_params.json` for catalyst blacklist and per-catalyst `cooldown_until` dates. Sell signals always pass. Buy signals are blocked if the catalyst is in blacklist or cooldown. Also checks sentiment phase — if phase is `warmup`/`hot`/`euphoria`, all catalysts are enabled. |

#### `execution/direct_executor.py` — `_check_direction_conflict()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/execution/direct_executor.py` |
| **Line** | 225 |
| **Signature** | `def _check_direction_conflict(dm: Any, date: str, symbol: str, direction: str) -> str | None` |
| **Input** | `dm` (DataManager), `date`, `symbol`, `direction` |
| **Output** | `str` (blocking direction) or `None` (pass) |
| **What it does** | T+1 rule: reads JSONL for same-symbol executed events. Blocks same-direction repeat trades. For opposite direction, checks MCP positions — allows sell only if shares are available, allows buy only if no remaining position. Returns the conflicting direction string if blocked. |

#### `execution/direct_executor.py` — sell_only_mode / cooldown / blocked_sector guards

| Lines | Guard | What it does |
|-------|-------|-------------|
| 496–519 | **sell_only_mode** | Reads `strategy_params.json` for `sell_only_mode` flag, also checks `redline_state.json` for tripped redline. If active, strips all buy candidates leaving only sells. |
| 521–565 | **cooldown/ice phase** | When sentiment phase is `cooldown`/`ice` with multiplier <= 0.3, only permits sells and high-confidence (>=0.70) dragon/leader buys. |
| 549–566 | **blocked sectors** | Reads `blocked_sectors` list from strategy params. Strips buy candidates whose `sector` matches. |

### 2.6 Account Snapshot

#### `execution/direct_executor.py` — `get_account_snapshot()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/execution/direct_executor.py` |
| **Line** | 65 |
| **Signature** | `def get_account_snapshot() -> tuple[float, float, float]` |
| **Input** | None (calls MCP exec server port 9003) |
| **Output** | `(total_assets, available_cash, current_market_val)` |
| **What it does** | Calls `client.get_balance()` and `client.get_positions()`. Includes active pending buy orders in market value (BUG-04 fix). Returns a point-in-time snapshot used for position sizing. |

### 2.7 AGY Iron Rule Gate

#### `core/market_regime_check.py` — `iron_rule_gate()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/core/market_regime_check.py` |
| **Line** | 222 |
| **Signature** | `def iron_rule_gate(candidate: dict, now_cst: dt.datetime | None = None) -> tuple[bool, str]` |
| **Input** | `candidate` (enriched with `quote`, `index_quotes`, `market_metrics`), `now_cst` |
| **Output** | `(True, "PASS: ...")` or `(False, "iron_rule_blocked: ...")` |
| **What it does** | **Four gates in one:** |
| | **Gate 1** — `intraday_dynamic_check()` (line 56): Real-time circuit breaker checking limit-down count >= 20, broken-seal rate >= 45%, index crashes (SH <= -2%, CYB <= -3%, STAR <= -2% with broad weakness). Writes regime state to disk on trigger. |
| | **Gate 2** — Consecutive board check (line 244): Blocks >=3-board stocks unless they are true dragons (is_dragon + sector support + score >= 10). |
| | **Gate 3** — `check_strategy()` (line 263): Per-catalyst circuit breaker from `strategy_circuit_breaker.py`. |
| | **Gate 4** — Market state machine (line 268): Reads `market_regime.json`. Blocks on stale data, freezing/panic regimes, fail-closed state. In ebb phases, blocks non-leader chasing. In garbage time (10:00-14:30), blocks non-dragon chasing. |
| | **Sell exemption** (line 231): Sell direction always passes. |
| | Market type isolation: Blocks STAR (科创板) stocks during isolated STAR crash. |

### 2.8 Condition Evaluator (Micro Gate)

#### `condition_evaluator.py` — `evaluate_all()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/condition_evaluator.py` |
| **Line** | 383 |
| **Signature** | `def evaluate_all(cand: dict, quote: dict | None = None, now_time: str | None = None, sentinel_quotes: dict | None = None, ...) -> dict` |
| **Input** | `cand`, `quote`, `now_time`, `sentinel_quotes`, `auction_pct`, `current_pct`, `index_quotes`, `sector_quote` |
| **Output** | `{"pass": bool, "checks": {...}, "first_failure": str | None}` |
| **What it does** | **8-condition micro-gate** with early exit on first failure: |
| | 1. **Index meltdown** (line 395): Checks if 3+ major indices (SH/SZ/CYB/STAR) drop > -1% simultaneously, or SH <= -2%, or CYB <= -3%. |
| | 2. **Sector deviation** (line 434): Blocks stock at limit-up when sector drops > -2%, or stock up > 3% while sector down > -1.5%. |
| | 3. **Speed filter** (line 448): Blocks 3-minute speed > 5%. |
| | 4. **Auction amount** (line 456): Blocks auction amount < 5M CNY. |
| | 5. **Auction condition** (line 463) → `evaluate_auction_condition()`: Validates auction open % against min/max thresholds. Also checks dependency anchor symbols. |
| | 6. **Intraday condition** (line 468) → `evaluate_intraday_condition()`: Checks `max_chase_pct` (chase limit), `must_seal_before` (seal deadline), and `check_broken_and_fake_healing()` for break/repair patterns. |
| | 7. **Chip safety** (line 479) → `evaluate_chip_condition()`: Checks profit-rate ratio, chip distribution safety via `utils/chip.py`. |
| | 8. **Fund flow** (line 485) → `evaluate_fund_flow_condition()`: Checks main net flow safety via `utils/fund_flow.py`. |

### 2.9 Position Sizing

#### `execution/direct_executor.py` — position sizing (lines 662–720)

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/execution/direct_executor.py` |
| **Lines** | 662–720 |
| **What it does** | For buys: `base_pct` (from candidate or default 25%) × `sent_multiplier` (from strategy params) = `adj_pct`. Computes `target_value = total_assets * adj_pct`, clamped by `max_regime_ratio - current_market_val` and `available_cash * 0.95`. Converts to round-lot shares (÷100 × 100). Blocks if < 100 shares. For sells: reads real available quantity from MCP positions, clamps to candidate quantity, blocks if < 100 shares. |

#### `execution/pipeline.py` — `normalize_intent()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/execution/pipeline.py` |
| **Line** | 244 |
| **Signature** | `def normalize_intent(candidate: dict, total_assets=0.0, adjusted_pct=0.0, available_cash=0.0, current_market_val=0.0, max_regime_ratio=1.0) -> dict` |
| **Input** | `candidate` dict + account financials |
| **Output** | `intent` dict with keys: `intent_id`, `candidate_id`, `symbol`, `name`, `direction`, `price`, `quantity`, `confidence`, `thesis`, `entry_rule`, `catalyst_type`, `approval_status`, `llm_approved`, `agy_approved`, `max_position_pct`, `created_at` |
| **What it does** | Wraps a raw candidate dict into a standardized TradeIntent with a unique `intent_id` (prefixed `it-`). For buys: recomputes quantity from financial inputs (redundant with direct_executor sizing). For sells: uses original quantity (min 100). Sets `approval_status = "pending"`. |

### 2.10 Risk Check & Execution

#### `execution/pipeline.py` — `risk_check_and_execute()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/execution/pipeline.py` |
| **Line** | 295 |
| **Signature** | `def risk_check_and_execute(intents: list[dict], dry_run: bool = True) -> dict` |
| **Input** | `intents` list, `dry_run` flag (reads `ASTOCK_DRY_RUN` env var) |
| **Output** | `{"approved": [...], "rejected": [...], "executed": [...], "skipped": [...], "status": str}` |
| **What it does** | **Five phases:** |
| | **Phase 1 — Trading session check** (line 310): Calls `client.get_trading_sessions()`. If not open and no AGY fallback, returns `blocked_outside_trading_session`. |
| | **Phase 2 — Risk batch check** (line 324): Calls `client.batch_check()` (MCP Risk port 9002) with retry (1s/2s/4s backoff). On 4 failures, falls back to AGY approval if candidate was AGY-approved. |
| | **Phase 3 — Snapshot balance** (line 384): Re-reads `client.get_balance()` and `client.get_positions()`. Enforces `max_position_count` (default 5). Re-checks cash sufficiency and sell availability (temporary_insufficient_shares check). |
| | **Phase 4 — Registration** (line 473): For each approved intent where `exec_registered` is not set, calls `client.register_approved_intent()` (MCP Exec port 9003) — registers the intent ID, symbol, direction, and max quantity with the exec server. |
| | **Phase 5 — Order placement** (line 488): Calls `client.place_order()` (MCP Exec port 9003) with symbol, direction, price, quantity, intent_id, and thesis. Sends Feishu notification on success. |

### 2.11 RiskManager (13 Layers)

#### `risk/risk_manager.py` — `RiskManager.batch_check()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/risk/risk_manager.py` |
| **Line** | 461 |
| **Signature** | `def batch_check(self, intents: list[dict]) -> dict` |
| **Input** | `intents` list with `symbol`, `direction`, `quantity`, `price` |
| **Output** | `{"results": [{"approved": bool, "reason": str, "layer": str, ...}], "registered": int}` |
| **What it does** | Iterates each intent through `check_intent()` (13 layers), then auto-registers approved intents to the exec server. |

#### `risk/risk_manager.py` — `check_intent()` (the 13-layer core)

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/risk/risk_manager.py` |
| **Line** | 402 |
| **Signature** | `def check_intent(self, intent: dict) -> dict` |
| **What it does** | Runs 13 sequential risk checks. Early exits on first failure. |

| # | Layer | Method | Line | What it checks |
|---|-------|--------|------|----------------|
| 1 | **symbol** | `_check_symbol()` | 134 | Stock code format: must be 6 digits + `.SH`/`.SZ`/`.BJ` suffix |
| 2 | **weekend** | `_check_weekend()` | 148 | Weekend (weekday >= 5) and non-trading-day (holiday) check |
| 3 | **position_cap** | `_check_position_cap()` | 157 | Single stock position <= 30% of total assets (current + new) |
| 4 | **market_crash** | `_check_market_crash()` | 186 | Market health score from MCP: if < 30, trigger crash circuit breaker |
| 5 | **outflow** | `_check_outflow() ` | 197 | Main net outflow < -800亿 (80B CNY) blocks new buys |
| 6 | **sentiment** | `_check_sentiment()` | 208 | Sentiment phase `ice`/`cooldown` with multiplier <= 0.3 blocks buys |
| 7 | **sector_conc** | `_check_sector_concentration()` | 221 | Sector concentration <= configurable limit (default 40%) |
| 8 | **total_exp** | `_check_total_exposure()` | 268 | Total portfolio exposure <= configurable limit (default 80%) |
| 9 | **t1_rule** | `_check_t1_rule()` | 296 | T+1 direction conflict: reads JSONL for today's executed trades. Blocks same-direction duplicate. Allows opposite-direction only if positions support it |
| 10 | **st_blacklist** | `_check_st_blacklist()` | 353 | ST / *ST / delisting check; also checks MCP blacklist |
| 11 | **avg_down** | `_check_avg_down()` | 362 | Prohibits averaging down: blocks buy if position already held |
| 12 | **tail_chase** | `_check_tail_chase()` | 377 | Blocks chase buys after 14:35 (late session) |
| 13 | **freeze** | `_check_freeze()` | 384 | Cooldown/freeze period check from `freeze_state.json` |

### 2.12 MCP Client (Network Layer)

#### `mcp_client.py` — `MCPClient`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/mcp_client.py` |
| **What it does** | Singleton JSON-RPC client wrapping three MCP microservices on localhost: |
| | **Intel (9001)**: Kline, quotes, wencai search, market health, limit-up ladder, fund flow, chip distribution, news, technical indicators |
| | **Risk (9002)**: `check_intent`, `batch_check`, `get_blacklist`, `daily_pnl` |
| | **Exec (9003)**: `get_balance`, `get_positions`, `get_today_trades`, `get_orders`, `cancel_order`, `register_approved_intent`, `place_order` |

**Key RPC methods for execution:**

| Method | Line | Port | Purpose |
|--------|------|------|---------|
| `get_market_health()` | 84 | 9001 | Fetch market-wide health metrics (limit-down count, broken-seal rate) |
| `query_quotes(symbols)` | 100 | 9001 | Batch quote retrieval for symbols |
| `get_balance()` | 178 | 9003 | Account total assets, available cash |
| `get_positions()` | 181 | 9003 | Current holdings |
| `get_today_trades()` | 187 | 9003 | Today's filled trades |
| `get_orders()` | 193 | 9003 | Active/pending orders |
| `batch_check(intents)` | 166 | 9002 | 13-layer risk batch check |
| `register_approved_intent(...)` | 210 | 9003 | Register approved intent in exec server |
| `place_order(...)` | 200 | 9003 | Place actual trade order |

---

## 3. Discovery Call Chains

### 3.1 Full Market Wide Discovery

#### `discovery/full_market_discovery.py` — `discover_wide_pool()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/discovery/full_market_discovery.py` |
| **Line** | 51 |
| **Signature** | `def discover_wide_pool() -> dict` |
| **Input** | None |
| **Output** | `{"wide_pool": [...], "theme_groups": {...}, "stats": {...}}` |
| **What it does** | Runs 5 parallel wencai searches via `ThreadPoolExecutor(max_workers=5)`, each with 50-result limit: |

| Query | Label | Search Criteria |
|-------|-------|-----------------|
| 1 | 动量突破 | Price breaks above MA20, gain > 3%, volume > 50% avg, cap 5B-30B, no ST/STAR/BJ |
| 2 | N字反包 | Yesterday negative candle, today gain > 5%, above MA5, cap 3B-20B, no ST |
| 3 | 倍量首板 | Limit-up, first board, volume > 2x yesterday, cap < 10B, no ST/STAR, turnover 5-25% |
| 4 | 平台突破 | Sideways > 15 days, today gain > 4%, breaks MA60, cap 5B-30B, no ST/STAR |
| 5 | 龙回头 | Former dragon, pullback > 5 days, today positive gain < 5%, cap 5B-50B, no ST, consecutive board history |

Deduplicates by symbol (first occurrence wins), normalizes fields (`symbol`, `name`, `price`, `change_pct`, `volume_ratio`, `market_cap`, `source`). Returns grouped by strategy label.

### 3.2 Leader Monitor

#### `discovery/leader_monitor.py` — `monitor_leaders()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/discovery/leader_monitor.py` |
| **Line** | 11 |
| **Signature** | `def monitor_leaders() -> dict` |
| **Input** | None |
| **Output** | `{"leaders": [...], "positions": [...], "signals": {...}, "updated_at": "..."}` |
| **What it does** | Fetches limit-up ladder via `client.get_limitup_ladder(min_streak=2)` to find multi-board leaders. Fetches positions via `client.get_positions()`. For each position, runs `check_exit_triggers()` which delegates to `SellRules.evaluate()` from `core/strategy.py`. Aggregates exit signals (trailing_stop, hard_stop_loss, time_exit, hold). |

#### `discovery/leader_monitor.py` — `check_exit_triggers()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/discovery/leader_monitor.py` |
| **Line** | 107 |
| **Signature** | `def check_exit_triggers(position: dict, current_price: float) -> str | None` |
| **Input** | `position` (cost, highest_price, entry_time), `current_price` |
| **Output** | `"trailing_stop"`, `"hard_stop_loss"`, `"breakeven"`, `"time_exit"`, `"weak_exit"`, `"profit_target"`, or `None` (hold) |
| **What it does** | Loads `sell_rules` from `strategy_params.json`, constructs a compat position dict, calls `SellRules.evaluate()`, maps the `why` string to an exit signal name. |

### 3.3 Limit-Up Scanner

#### `discovery/limitup_scanner.py` — `get_ladder()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/discovery/limitup_scanner.py` |
| **Line** | 10 |
| **Signature** | `def get_ladder(min_streak: int = 1) -> list[dict]` |
| **Input** | `min_streak` — minimum consecutive boards |
| **Output** | List of graded ladder entries with `symbol`, `name`, `boards`, `seal_grade`, `order_book_quality`, `score`, `reason` |
| **What it does** | Calls MCP `get_limitup_ladder`, then `grade_seal_strength()` which grades entries into `iron` (>=5 boards), `strong` (2-3 boards), or `weak` (single board). Called by `dragon_screener_engine.py`. |

### 3.4 Morning Master Orchestration

#### `orchestrator/morning_master.py` — `main()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/orchestrator/morning_master.py` |
| **Line** | 124 |
| **Signature** | `def main() -> int` |
| **What it does** | Sequential pre-market orchestration triggered by cron at 09:24:50. Executes phases via `subprocess.run()`: |

| Phase | Time | Script | What it does |
|-------|------|--------|-------------|
| 0 | 09:24:50 | MCP warmup | Pings Intel (9001), Risk (9002), Exec (9003) to ensure connectivity |
| 0.5 | +0s | `strategy_params_init.py` | Initializes sentiment/multiplier/phase from market state |
| 0.75 | +0s | `market_regime.py` | Refreshes market regime state machine |
| 0.8 | +0s | `active_portfolio_cleaner.py` | Cleans stale positions to free slot capacity |
| 0.85 | wait | (sleep) | Waits for 09:25:05 (auction match) |
| 0.9 | 09:25:05 | `auction_kill_switch.py --force` | Circuit breaker for positions at auction open |
| 0.95 | +0s | `position_guard.py` | Hard risk pre-check: if blocked, skips all scan phases |
| 1 | 09:25:05+ | `call_auction_scanner.py` | Scans gap-up high-volume auction candidates |
| 2 | 09:25:20 | `limit_up_scanner.py` | Scans yesterday limit-up weak-to-strong candidates |
| 2.5 | 09:25:35 | `dragon_screener_engine.py` → `direct_executor.py` | Grades dragons and immediately executes |
| 3 | 09:30:00 | (handoff) | Leaves `direct_executor.py` polling loop to handle remaining candidates |

---

## 4. Backtest Call Chain

### 4.1 Entry Point

#### `scripts/backtest_2yr.py` — `run_backtest()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/scripts/backtest_2yr.py` |
| **Line** | 101 |
| **Signature** | `def run_backtest(config_override: dict | None = None, profile: str = "momentum_v5") -> dict` |
| **Input** | Optional config override dict, strategy profile name |
| **Output** | `dict` with keys: `ret`, `annual_ret`, `sharpe`, `wr`, `pf`, `mdd`, `trades`, plus per-strategy and per-industry stats |
| **What it does** | Runs a full 2-year backtest across the entire A-share universe (~4000 stocks, 485 trading days, 2024-10-01 to 2026-10-01). Initial capital: 400,000 CNY. |

### 4.2 Data Loading (lines 144–188)

| Step | Function | What it does |
|------|----------|-------------|
| 1 | `load_cache()` | Checks `data/kline_cache.json` for pre-fetched K-lines |
| 2 | `fetch_klines(sym, 500)` | Fetches 500 daily K-lines per symbol via MCP Intel (9001), with 3 retries. Batch size 50, progress logging. |
| 3 | `save_cache()` | Saves fetched data to file cache for subsequent runs |
| 4 | `fetch_klines("000001.SH", 500)` | Fetches Shanghai index K-lines for regime detection |

### 4.3 Configuration

#### `core/strategy.py` — `load_strategy_config()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/core/strategy.py` |
| **Line** | 79 |
| **Signature** | `def load_strategy_config() -> dict` |
| **Input** | None (reads `config/strategy_params.json` + `_PARAM_OVERRIDES`) |
| **Output** | Merged config dict with `sell_rules`, `score_weights`, `regime_map`, etc. |

#### `core/strategy_profiles.py` — `get_profile()`

| Field | Detail |
|-------|--------|
| **Line** | (imported at backtest_2yr.py line 38) |
| **Signature** | `def get_profile(name: str) -> Profile` |
| **What it does** | Returns a strategy profile containing `score_fn`, `screen_fn`, `sell_rules`, `default_params`. Default profile is `momentum_v5` which uses `score_momentum_core` for scoring and `screen_candidates` for filtering. |

### 4.4 Main Loop (lines 232–483)

#### Regime Detection

| | |
|--|--|
| **Function** | `core/strategy.py` `get_regime()` (line 145) |
| **Input** | Index bars + current date |
| **Output** | One of: `euphoria`, `hot`, `warmup`, `cooldown`, `ice` |
| **Logic** | Based on 5-day index change + MA relationships: >+3% with bullish MA = euphoria; >+1% with above MA20 = hot; >-1.5% with above 0.95*MA20 = warmup; >-3% = cooldown; else = ice |

Regime parameters from `REGIME_MAP` (strategy.py:128):
```
euphoria: (min_score=65, max_positions=2, cap_pct=0.35)
hot:      (70, 1, 0.20)
warmup:   (60, 5, 0.30)
cooldown: (60, 3, 0.28)
ice:      (70, 1, 0.15)
```

#### Sell Rules Engine

#### `core/strategy.py` — `SellRules.evaluate()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/core/strategy.py` |
| **Line** | 419 |
| **Signature** | `def evaluate(self, pos: dict, hi: float, lo: float, cl: float, hold: int) -> tuple[bool, float, str]` |
| **Input** | Position (ep, tp, sp, mp), day's hi/lo/close, hold days |
| **Output** | `(sell: bool, sell_price: float, reason: str)` |
| **What it does** | **6-rule exit engine:** |

| # | Rule | Condition | Returns |
|---|------|-----------|---------|
| 1 | **profit_target** | `cp >= tp` (current return >= target %) | `(True, close, "目标+8%")` |
| 2 | **trailing_stop** | `mp_pct >= trail_trigger` AND `lo <= trail_price` | `(True, trail_price, "回落30%(高12%)")` |
| 3 | **hard_stop** | `cp <= sp` (current return <= stop %) | `(True, close, "止损-3%")` |
| 4 | **breakeven** | `mp_pct >= breakeven_peak AND cp < breakeven_thresh` | `(True, close, "保本(曾12%)")` |
| 5 | **weak_exit** | `hold >= weak_hold AND cp < weak_thresh` | `(True, close, "弱2d")` |
| 6 | **time_exit** | `hold >= max_hold` | `(True, close, "时间5d")` |

Default parameters: `trail_trigger=3.0, trail_high_rate=0.3, trail_low_rate=0.4, trail_high_thresh=5.0, breakeven_peak=3.0, breakeven_thresh=0.5, weak_hold=2, weak_thresh=-0.5, max_hold=5`

#### Buy Signal Generation

#### `core/strategy.py` — `screen_candidates()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/core/strategy.py` |
| **Line** | 186 |
| **Signature** | `def screen_candidates(bars_dict: dict, curr_date: str, min_vr=1.5, min_close=10.0, ma_pct=0.95) -> list[str]` |
| **Input** | All symbol bars + current date |
| **Output** | Filtered symbol list |
| **What it does** | **5 hard filters:** (1) >= 30 bars available, (2) close >= min_close (default 10.0), (3) volume > 0, (4) volume ratio >= min_vr (default 1.5), (5) close >= MA20 * ma_pct (default 0.95) |

#### `core/strategy.py` — `score_momentum_core()`

| Field | Detail |
|-------|--------|
| **File** | `/home/wade/workspace/ai/Astock/core/strategy.py` |
| **Line** | 218 |
| **Signature** | `def score_momentum_core(bars: list[dict], params: dict | None = None) -> dict` |
| **Input** | Bar list for one symbol, scoring params |
| **Output** | `{"score": int (0-100), "grade": "A"|"B"|"C"|"D", "name": str, "target_pct": float, "stop_pct": float, "hold_days": int, "atr_pct": float}` |
| **What it does** | **8-factor momentum scoring:** |

| # | Factor | Weight | Scoring logic |
|---|--------|--------|--------------|
| 1 | **Volume** | 25 | VR > 3.0 → full; > 2.0 → 80%; > 1.5 → 60%; > 1.2 → 40%; > 1.0 → 24%; else 12% |
| 2 | **DH (distance from 10d high)** | 20 | < 1% → full; < 3% → 80%; < 5% → 60%; < 8% → 35%; < 12% → 20% |
| 3 | **MA alignment** | 20 | close>MA5>MA10>MA20 → full + name="trend"; close>MA5>MA20 → 70%; close>MA20 → 50%; else 10% |
| 4 | **RSI** | 15 | 45-65 → full; 65-75 → 67%; 35-45 → 53%; >75 → 27%; else 13% |
| 5 | **Daily change** | 15 | > 7% → full + "ignition"; > 5% → 87%; > 3% → 67%; > 1.5% → 47%; > 0.5% → 27%; else 7% |
| 6 | **Volatility bonus** | 5 | Range > 5% → full; > 3% → 60% |
| 7 | **New high bonus** | 5 | 10d high within 1% of 20d high → full + "breakout" |
| 8 | **Pullback bonus** | 10 | Past 10d had >5% gain day + current VR < 0.9 → full + "pullback" |

Hard filters: VR < min_vr (0.8) or RSI < min_rs (25) or close < MA20 * ma_pct (0.95) → score=0, grade="D".
Score capped at 100. Grades: >=65=A, >=50=B, >=35=C, else D.

#### Multi-Strategy Mode (profile="multi")

When `--profile multi` is used:
- Uses `MultiStrategyAllocator` from `strategy_profiles.py` (line 118)
- Runs all profiles simultaneously via `allocator.screen_all()` and `allocator.score_all()`
- Merges scores by symbol with resonance boost (each additional profile +30% position size)
- Tracks per-profile budget limits

#### Position Sizing in Backtest (lines 409–463)

| Score | Allocation |
|-------|-----------|
| >= 80 | `cap_pct + 0.05` (capped at `max_pos_pct` 0.35) |
| >= 70 | `cap_pct` |
| >= 60 | `cap_pct * 0.8` |
| < 60 | `cap_pct * 0.6` |

Entry on D+1 at open price. Quantity = max(100, floor(amount / price / 100) * 100). Fee = 0.03%.

---

## 5. Key Data Structures

### TradeIntent (pipeline.py normalize_intent output)
```python
{
    "intent_id": "it-<candidate_id>",
    "candidate_id": str,
    "symbol": str,            # e.g. "600519.SH"
    "name": str,
    "direction": "buy"|"sell",
    "price": float,
    "quantity": int,
    "confidence": float,
    "thesis": str,
    "entry_rule": str,
    "catalyst_type": str,
    "approval_status": "pending"|"approved"|"rejected"|"reduced",
    "llm_approved": bool,
    "agy_approved": bool,
    "max_position_pct": float,
    "created_at": str          # ISO 8601 UTC
}
```

### RiskManager.check_intent output
```python
{
    "approved": bool,
    "reason": str,            # Reason if rejected
    "layer": str|None          # Layer name if rejected (e.g. "position_cap")
}
```

### SellRules.evaluate output
```python
(sell: bool, sell_price: float, reason: str)
# reason examples: "目标+8%", "回落30%(高12.3%)", "止损-3%", "保本(曾12.3%)", "弱2d", "时间5d"
```

---

## 6. Summary: Path Comparison

| Aspect | Live Trading | Backtest |
|--------|-------------|----------|
| **Entry** | cron `direct_executor.main()` | `scripts/backtest_2yr.run_backtest()` |
| **Data source** | MCP Intel (9001) real-time quotes | Pre-fetched K-line history (500 bars) |
| **Candidate source** | JSONL ledger (written by scanners) | `screen_candidates()` on bar data |
| **Scoring** | LLM/AGY approval flags | `score_momentum_core()` (8 factors) |
| **Market regime** | `market_regime_check.iron_rule_gate()` | `get_regime()` on index bars |
| **Position sizing** | Account snapshot + sentiment multiplier | Static cap_pct per regime |
| **Risk** | `risk_check_and_execute()` → `RiskManager.batch_check()` (13 layers) | No real-time risk; only position limits |
| **Sell rules** | `leader_monitor.check_exit_triggers()` | `SellRules.evaluate()` (6 rules) |
| **Execution** | `register_approved_intent()` + `place_order()` via MCP Exec (9003) | D+1 open price, simulated fill |
| **Notifications** | Feishu trade notification | Console + file output |
