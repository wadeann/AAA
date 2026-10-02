# AUDIT REPORT -- Phase 2A: Risk & Execution Vulnerability Audit

**Date:** 2026-10-02
**Scope:** AGY fail-open, risk architecture gaps, execution pipeline, data quality, cost model
**Status:** COMPLETE -- 4 CRITICAL, 6 HIGH, 5 MEDIUM, 3 LOW findings

---

## EXECUTIVE SUMMARY

**This system CANNOT go to live trading in its current state.** The AGY fail-open risk has been partially mitigated (degraded risk check added), but 2 CRITICAL bypass paths remain through `close_session_defense.py` and the `is_trade_ready` function. Additionally, no复权 factors are present in 2,348 stocks worth of cached K-line data, meaning all backtests are running on unadjusted prices. The minimum commission of 5 RMB per trade and过户费 are not modeled, which inflates backtest returns for small trades.

---

## CRITICAL FINDINGS (Will Cause Real Money Loss)

### CRITICAL-001: close_session_defense hardcodes AGY bypass for all sell candidates
- **File:** `defense/close_session_defense.py:472-473`
- **Reproduction:**
  1. Any trading day at 14:15-14:56 CST
  2. A position held shows a Chanlun sell signal
  3. `close_session_defense.py` creates a candidate with `llm_approved: True, agy_approved: True` hardcoded
  4. This candidate flows through `batch_trade_gate.py` or `direct_executor.py`
  5. With AGY approval flag set, if Risk MCP is down, it bypasses the degraded risk check gate entirely
- **Code:**
  ```python
  # close_session_defense.py:472-473
  "llm_approved": True,
  "agy_approved": True,
  ```
- **Estimated P&L Impact:** In a market crash scenario (Risk MCP down + multiple sell signals), ALL sell orders execute unprotected. In a specific scenario where a stock gaps down -15% intraday and the strategy sells, the 13-layer risk check that would normally detect the market crash and trigger circuit breaker is entirely absent.
- **Recommended Fix:**
  1. Remove hardcoded `llm_approved: True, agy_approved: True` from defense modules
  2. Set `agy_approved: True` only if the AGY review was actually performed
  3. Add a distinct `defense_approved` flag separate from `agy_approved`
  4. Ensure degraded risk check (which is now FAIL-CLOSED) still applies to defense candidates

### CRITICAL-002: is_trade_ready bypasses all risk checks for AGY-approved candidates
- **File:** `execution/pipeline.py:170-241`
- **Reproduction:**
  1. A candidate has `agy_approved: True` or `llm_approved: True` (the `approved` variable)
  2. Line 204: `float(candidate.get("confidence", 0) or 0) >= 0.65 if not approved else True` -- confidence threshold is skipped for approved candidates
  3. Lines 220-237: Complex condition gates are relaxed for approved candidates
  4. Line 239: `if require_risk: required.append(bool(candidate.get("risk_approved")))` -- BUT `require_risk` defaults to True, and `batch_trade_gate.py:275` calls it with `require_risk=False`
- **Blast radius:** The `batch_trade_gate.py` at line 275 explicitly calls `is_trade_ready(candidate, require_risk=False)`. This means AGY-approved candidates entering through the trade gate skip the `risk_approved` field check entirely.
- **Estimated P&L Impact:** A candidate with AGY approval but a confidence score of 0.30 and fundamental_confirmed: False will pass `is_trade_ready` because the `approved` check on line 204 relaxes confidence, and `require_risk=False` skips the final risk gate. This could lead to buying into a fundamentally broken company.
- **Recommended Fix:**
  1. `risk_approved` check should NEVER be optional for buy-side trades
  2. Make `require_risk` always True for buy direction, False only for sell
  3. Remove the confidence bypass for approved candidates (confidence >= 0.65 should be universal)

### CRITICAL-003: No复权 (adjustment factor) in 2,348 stocks' K-line data
- **File:** `data/kline_cache.json` (264 MB, 2,348 keys)
- **Reproduction:**
  1. Examine any bar in the cache: fields are `['time', 'open', 'close', 'high', 'low', 'volume', 'amount', 'change', 'change_pct', 'amplitude']`
  2. No `factor`, `adj_factor`, `fq_factor`, or `复权因子` field exists
  3. When a stock has a 10-to-10 stock split, the price suddenly drops 50% in the raw data
  4. Indicators (SMA, RSI, ATR) all compute on price-doubled data across the split date
- **Estimated P&L Impact:** For a stock that had a 10-to-10 bonus issue, the MA20 would show a false 50% drop, triggering both false Chanlun buy/sell signals and false momentum scores. Over 500 bars of history, this is likely to affect 5-15% of stocks. The Chanlun pivots (中枢, 买卖点) would be computed on discontinuous data.
- **Recommended Fix:**
  1. Download 前复权 (forward-adjusted) or 后复权 (backward-adjusted) K-line data
  2. Add adjustment factor field to each bar
  3. Apply adjustment before any technical indicator computation
  4. If TDX data source is used, the `tdx_kline` function may already support `fq` parameter -- verify

### CRITICAL-004: Minimum commission (最低5元) and过户费 not modeled in ANY engine
- **Files:** All backtest engines + all live execution paths
- **Reproduction:**
  1. Backtest buys 100 shares at 10.00 = 1,000 RMB trade
  2. Commission charged: 1,000 * 0.0003 = 0.30 RMB
  3. Actual commission: max(1,000 * 0.0003, 5.00) = 5.00 RMB + 过户费 0.02 RMB
  4. Difference: 5.02 - 0.30 = 4.72 RMB per small trade
- **Rates used in code:**
  - Buy: 0.03% (0.0003) -- correct broker commission rate
  - Sell: 0.13% (0.0013) -- 0.08% broker + 0.05% stamp duty, BUT missing 0.002%过户费
  - Missing: min(commission, 5.00) floor for both buy and sell
  - Missing: 过户费 (0.002% of trade amount for Shanghai stocks)
- **Estimated P&L Impact:**
  - For a 1,000 RMB trade: 4.72 RMB excess profit in backtest
  - For a strategy doing 200 trades/year, average 5,000 RMB/trade: ~500-800 RMB/year in phantom returns
  - For small accounts (< 100K): ~1-2% annual return inflation
  - For Shanghai stocks specifically: 0.002% per trade missing (过户费)
- **Recommended Fix:**
  1. Implement `calculate_commission(amount, market='SH')` function
  2. Buy commission: max(amount * 0.0003, 5.0)
  3. Sell commission: max(amount * 0.0003, 5.0) + amount * 0.0005 (stamp) + (amount * 0.00002 if SH else 0) (过户)
  4. Apply to ALL backtest engines and ALL live execution paths

---

## HIGH FINDINGS (Significant Impact on Backtest Reliability)

### HIGH-001: Three different T+1 enforcement implementations with subtle differences
- **Files:**
  - `risk/risk_manager.py:296-351` (`_check_t1_rule`)
  - `execution/direct_executor.py:225-296` (`_check_direction_conflict`)
  - `execution/batch_trade_gate.py:65-123` (`_check_direction_conflict`)
  - `execution/pipeline.py:416-420` (degraded T+1 check)
- **Issue:** Three separate implementations of the same T+1 logic exist. The risk_manager version checks `available_quantity` for sell availability, while the direct_executor version also checks `today_buys` via `client.get_today_trades()`. The batch_trade_gate version does NOT check today_trades for the sell direction check. These divergences mean a sell could be blocked by one path but approved by another.
- **Specific divergence:**
  - `risk_manager.py:328`: `av_raw = p.get("available_quantity")` -- simple
  - `direct_executor.py:263-264`: Also fetches `available_quantity` but adds `client.get_positions()` fallback
  - `batch_trade_gate.py:99-100`: Same pattern but missing the `today_trades` deduction from `direct_executor.py:440-445`
  - `pipeline.py:468-474`: Also checks `available_quantity` but no `today_trades` deduction in degraded path
- **Recommended Fix:** Extract T+1 check to a single shared function in `execution/pipeline.py` or a new utility module. All callers should use the same implementation.

### HIGH-002: Position sizing formulas diverge between live and backtest
- **Files:**
  - `execution/direct_executor.py:698-720` (live trading position sizing)
  - `execution/pipeline.py:244-292` (`normalize_intent` position sizing)
  - `scripts/backtest_2yr.py:437-453` (backtest position sizing)
  - `scripts/backtest_engine.py:552-576` (backtest_engine position sizing)
- **Key differences:**
  - Live (`direct_executor`): `adj_pct = base_pct * sent_multiplier` where `base_pct` comes from `max_position_pct` or `risk_adjusted_pct` field, multiplied by sentiment multiplier
  - Live (`normalize_intent`): `target_value = total_assets * adjusted_pct`, then clamped by `max_regime_ratio` and `available_cash * 0.95`
  - `backtest_2yr.py`: `alloc = cp * 0.6-1.0` depending on score, `amt = min(cash * alloc, INITIAL_CAPITAL * _max_pos_pct)`
  - `backtest_engine.py`: `base_allocation = cash * sent_mult * pos_factor / remaining`
  - These produce DIFFERENT position sizes for the same signal. A backtest showing 2% monthly returns might correspond to 0.5% in live.
- **Recommended Fix:** Consolidate position sizing into a single function `compute_position_size(signal_score, regime, cash, total_assets, ...)` used by both engines.

### HIGH-003: Field format inconsistency in kline_cache.json
- **File:** `data/kline_cache.json`
- **Issue:** The `time` field is stored as a plain date string `"2024-09-06"` with NO timezone information. Meanwhile, `scripts/backtest_engine.py:58-59` converts times to `dt.datetime` objects in normalize_bars, and `core/strategy.py:150` does string comparison on `time`. This works because both sides use string comparison, but any future code that calls `dt.datetime.fromisoformat("2024-09-06")` will get a naive datetime -- which in UTC context means 00:00 UTC = 08:00 CST, potentially selecting wrong bars.
- **Risk:** If bars are ever fetched from a live MCP source that returns ISO 8601 with timezone, the mix of tz-aware and tz-naive datetimes would cause comparison failures.
- **Recommended Fix:** Standardize on ISO 8601 date strings with explicit CST offset: `"2024-09-06T00:00:00+08:00"` or use `datetime.date` objects consistently.

### HIGH-004: degraded_risk_check is FAIL-CLOSED but ships without market crash / sentiment / sector / outflow checks
- **File:** `execution/pipeline.py:300-495`
- **Issue:** The degraded risk check function properly applies FAIL-CLOSED semantics (no auto-approve), but it SKIPS 5 of the 13 risk layers when Risk MCP is down:
  - Market crash detection (Layer 4)
  - Sentiment check (Layer 6)
  - Sector concentration (Layer 7)
  - Outflow detection (Layer 5)
  - Tail chase prohibition (Layer 12)
  - Weekend check (Layer 2, partially)
- **Scenario:** Risk MCP is down at 14:35. A buy candidate for a ST stock in a crashing sector, with massive outflow, gets through degraded check because: (1) ST check passes if name doesn't contain "ST", (2) price sanity passes, (3) T+1 passes. The 5 missing layers are exactly the ones that catch market-level catastrophic conditions.
- **Estimated Impact:** In a flash crash (Risk MCP overwhelmed by real-time data), degraded mode would approve buys that the full risk engine would reject.
- **Recommended Fix:**
  1. Cache the latest market health score, sentiment phase, and outflow data locally every 5 minutes in `data/state/`
  2. Use cached values in degraded mode with a staleness check (reject if cache > 10 min old)
  3. For tail chase: time is available locally (14:35 check)
  4. For weekend: day-of-week is available locally

### HIGH-005: close_session_defense write-then-execute race condition
- **File:** `defense/close_session_defense.py:486-587`
- **Reproduction:**
  1. 14:15 scan finds a sell signal for symbol 600519
  2. `append_candidate(dm, record)` writes candidate to JSONL (line 486)
  3. `run_trade_gate()` is called on line 587, which calls `batch_trade_gate.py`
  4. `batch_trade_gate.py` reads candidates from JSONL (line 144)
  5. If cron triggers `direct_executor.py` between steps 2 and 3, the same candidate could be processed TWICE
- **Flaw:** The `fctl.flock` in `data/__init__.py:32` provides inter-process file locking for writes, but `run_trade_gate()` spawns a subprocess that reads the same file. The flock is released immediately after each append. Between append and `run_trade_gate()`, another process could read and process the same candidate.
- **Recommended Fix:** Use a `processed_ids` check in `batch_trade_gate.py` that covers ALL events (not just a subset), or use a centralized dedup key per candidate_id.

### HIGH-006: backtest_engine.py scores on data that live can never access
- **File:** `scripts/backtest_engine.py:151-267` (`compute_signal_score`)
- **Issue:** The backtest engine computes signal scores using: weekly trend from weekly bars, daily trend from chanlun analysis, RSI, volume ratio, and sentiment multiplier. In live trading, the corresponding AGY-routed path (`direct_executor.py`) does NOT compute a comprehensive signal score. It uses `candidate.get("confidence")` from whatever discovery module created the candidate. These confidence values are filled by `close_session_defense.py` (0.78 for sell), `discovery` modules, etc., and range from 0.62-0.78, with no standardized scoring.
- **Impact:** Backtest selects the top-N candidates by score. Live selects candidates by whatever order they were discovered and whether they have AGY approval. The selection bias is different.
- **Recommended Fix:** Standardize scoring in a shared module used by both engines. The `score_momentum_core` in `core/strategy.py` is a good start but is NOT used by any discovery or execution module in live trading.

---

## MEDIUM FINDINGS (Edge Cases)

### MEDIUM-001: normalize_intent mirrors llm_approved to agy_approved and vice versa
- **File:** `execution/pipeline.py:286-287`
- **Code:**
  ```python
  "llm_approved": bool(candidate.get("llm_approved") or candidate.get("agy_approved")),
  "agy_approved": bool(candidate.get("agy_approved") or candidate.get("llm_approved")),
  ```
- **Issue:** This MUTUAL mirroring means if either flag is set, both appear set. This makes it impossible to trace which approval path was actually used. If `llm_approved=True` but `agy_approved` was never checked, the intent still carries `agy_approved=True`. This is an audit trail problem -- you cannot determine if a losing trade was approved by LLM or AGY.
- **Recommended Fix:** Keep them separate. Only set `agy_approved` if AGY actually returned approval. Only set `llm_approved` if LLM actually returned approval.

### MEDIUM-002: Error handlers that silently return empty data are indistinguishable from genuine empty states
- **Files:** `risk/risk_manager.py:111-115`, `execution/direct_executor.py:56-62`, `execution/pipeline.py:384-391`
- **Pattern:**
  ```python
  try:
      return self._client.get_positions()
  except Exception:
      return []
  ```
- **Issue:** When `get_positions()` fails (network error, MCP crash), it returns `[]`. The calling code then sees "no positions" and proceeds to open new positions, potentially exceeding the position cap of 5. Meanwhile, the real account has 4 positions -- so the strategy could open up to 9 total positions.
- **Recommended Fix:** On MCP failure, return a sentinel value (e.g., `None`) or raise a specific exception. The calling code should treat "cannot determine positions" as a FAIL-CLOSED condition for buy-side trades.

### MEDIUM-003: DT.datetime comparison inconsistency across the codebase
- **Files:** Multiple
- **Issue:**
  - `risk/risk_manager.py:98`: `dt.datetime.now(CST)` -- timezone-aware (CST = UTC+8)
  - `execution/direct_executor.py:19`: `dt.datetime.now(cst)` -- timezone-aware (cst = UTC+8)
  - `execution/pipeline.py:101`: `dt.datetime.now(dt.timezone.utc)` -- UTC
  - `data/__init__.py:42`: `dt.date.today().isoformat()` -- naive date
  - `condition_evaluator.py:12`: No timezone handling, relies on caller
  - The `dt.date.today()` call uses system timezone (which may not be CST)
  - If system timezone is UTC, `dt.date.today()` returns UTC date -- which at 09:00 CST is the PREVIOUS DAY in UTC (01:00 UTC)
- **Recommended Fix:** Centralize on a single timezone constant (`CST = dt.timezone(dt.timedelta(hours=8))`) and use `dt.datetime.now(CST).date()` everywhere.

### MEDIUM-004: is_trade_ready confidence bypass logic is error-prone
- **File:** `execution/pipeline.py:204`
- **Code:** `float(candidate.get("confidence", 0) or 0) >= 0.65 if not approved else True`
- **Issue:** This ternary is logically complex and the intent is unclear. If `approved=True` (AGY or LLM approved), confidence check returns `True` unconditionally. This means a candidate with `confidence: 0.01` and `agy_approved: True` passes. The assumption is that AGY would never approve such a candidate, but there is no enforcement.
- **Recommended Fix:** Change to `confidence >= 0.50` (lower threshold, not zero) for approved candidates. Or remove the bypass entirely.

### MEDIUM-005: Scheduled cron jobs have no inter-job coordination
- **File:** `scripts/scheduler.py`
- **Issue:** The scheduler runs `direct_executor`, `full_market_discovery`, `market_regime`, and `leader_monitor` ALL at the same cron tick (every 5 minutes at the same minute). They all access `data/ledger/candidates_{date}.jsonl` simultaneously. The `fcntl.flock` on writes prevents corruption, but reads are not locked. A `direct_executor` read while `leader_monitor` is writing (or vice versa) could return partial data.
- **Impact:** A candidate could be partially read (first half of the line flushed, second half not) and appear corrupted, causing `json.JSONDecodeError` which is silently caught by `read_jsonl` (line 53).
- **Recommended Fix:** Add read-side locking with `fcntl.LOCK_SH` in `read_jsonl`, or stagger cron times by 30 seconds to avoid contention.

---

## LOW FINDINGS (Cosmetic/Documentation)

### LOW-001: Risk layer numbering in docstring is now misleading
- **File:** `risk/risk_manager.py:7-21`
- **Issue:** The docstring claims "13 risk layers" but the actual order in `check_intent` (lines 424-445) differs from the documented order. The doc lists `weekend` as layer 2 but in code it runs 2nd. The new degraded risk check in `pipeline.py` has a different order and different checks entirely. The docstring is stale documentation.

### LOW-002: strategy_params.json has no cost configuration
- **File:** `config/strategy_params.json`
- **Issue:** Commission rates (0.03%, 0.13%) are hardcoded in 5+ places across the codebase with no configurable override. If commission rates change (e.g., stamp duty reduction from 0.05% to 0.03%), the fix requires code changes in every engine.

### LOW-003: Variable name collision in backtest_engine.py
- **File:** `scripts/backtest_engine.py:504`
- **Code:** `bp_type = cand_bp if locals().get('cand_bp') else bp`
- **Issue:** The variable `cand_bp` is never defined in the enclosing scope. This `locals().get('cand_bp')` will always return None, making `bp_type = bp`. The `bp_type` variable is then never used anywhere. This is dead code.

---

## AGY FAIL-OPEN ANALYSIS (RISK-001)

### Current State

The `pipeline.py:risk_check_and_execute` function now uses FAIL-CLOSED semantics when Risk MCP is unavailable:

1. **Risk MCP available** (normal path): All 13 layers checked via `client.batch_check()` at Risk MCP port 9002.
2. **Risk MCP unavailable** (degraded path): Falls through to `degraded_risk_check()` which applies 9 of 13 layers using local data only. AGY approval status is NOT considered -- ALL intents go through degraded check equally. NO auto-approval for AGY candidates.

### But two bypass paths remain CRITICAL:

**Bypass Path 1: close_session_defense.py** (CRITICAL-001)
- Sells are directly created as candidates with `llm_approved=True, agy_approved=True`
- These enter through `batch_trade_gate.py:275` with `require_risk=False`
- The degraded check in `pipeline.py` is bypassed because `is_trade_ready` returns True without `risk_approved`

**Bypass Path 2: direct_executor.py entry**
- `direct_executor.py:451-455` lines skip candidates with `agy_approved is False` or `llm_approved is False`
- But `close_session_defense` candidates have both set to True
- If Risk MCP is down, `pipeline.py:517` blocks outside-session trades UNLESS `agy_approved` or `llm_approved` is True
- Wait -- actually line 514 checks `agy_fallback = any(i.get("llm_approved") or i.get("agy_approved") for i in intents)` and if true, SKIPS the session block. This means AGY-approved intents can trade outside session hours when Risk MCP is down. This is the AGY fail-open that RISK-001 warned about.

### Blast Radius

If Risk MCP (port 9002) is down for **1 hour** during trading:

- **Scheduler fires** `direct_executor` every 5 minutes = 12 times/hour
- **Each fire** processes up to BATCH_SIZE=2 candidates = max 24 trades/hour
- **close_session_defense** fires at 14:15, 14:30, 14:45 = up to 3 batches of sell candidates
- **batch_trade_gate** fires at 10:55 and 14:55 = 2 batches
- **Worst case:** 24 + 6 + 4 = 34 trades through degraded risk check in 1 hour

With degraded risk check (FAIL-CLOSED), only 9 of 13 layers apply. The missing 4 layers (market crash, sentiment, sector concentration, outflow) are the ONES THAT MATTER MOST during a market crash -- which is exactly when Risk MCP is most likely to fail.

### Bottom Line on AGY Fail-Open

The `degraded_risk_check` function (FAIL-CLOSED) is a good mitigation, but the bypass through `close_session_defense` hardcoded approvals and the `require_risk=False` parameter in `batch_trade_gate.py:275` means trades CAN AND WILL execute with only partial risk coverage when Risk MCP is unavailable during market turmoil.

---

## RISK ARCHITECTURE COMPARISON

| Layer | risk_manager.py | backtest_engine.py | backtest_2yr.py | direct_executor (live) | batch_trade_gate |
|-------|-----------------|---------------------|-----------------|----------------------|-------------------|
| 1. Symbol validation | YES | NO | NO | NO (via normalize_intent) | NO |
| 2. Weekend check | YES | NO (via trade_dates) | NO (via trade_dates) | YES (in_trading_session) | NO (via session check in risk_check) |
| 3. Position cap (30%) | YES | NO | NO (different formula) | YES (implicit via max_regime_ratio) | YES (in degraded check) |
| 4. Market crash | YES (MCP) | NO | NO | YES (iron_rule_gate) | YES (intraday_dynamic_check) |
| 5. Outflow (-800B) | YES (MCP) | NO | NO | NO | NO |
| 6. Sentiment cooldown | YES | YES (sent_mult) | YES (regime_map) | YES (R37 cooldown) | NO |
| 7. Sector concentration | YES (MCP) | NO | NO | NO | NO |
| 8. Total exposure (80%) | YES | NO | IMPLICIT (pos count < mx) | IMPLICIT (max_regime_ratio) | IMPLICIT (max_regime_ratio) |
| 9. T+1 conflict | YES | YES (implicit, cant sell same day) | YES (implicit, cant sell same day) | YES (_check_direction_conflict) | YES (_check_direction_conflict) |
| 10. ST blacklist | YES | NO | NO | NO | YES (in degraded check) |
| 11. Avg-down prohibition | YES | NO (position check) | NO (position check) | NO | YES (in degraded check) |
| 12. Tail chase (14:35) | YES | NO | NO | NO | NO |
| 13. Freeze list | YES | NO | NO | NO | YES (in degraded check) |
| **AGY Iron Rule Gate** | NO | NO | NO | YES (iron_rule_gate) | NO |
| **Condition Evaluator** | NO | NO | NO | YES (cond_eval) | NO |
| **Sell-only mode** | NO | NO | NO | YES | YES |
| **Broken board guard** | NO | NO | NO | YES (via cond_eval) | NO |

**Analysis:** The live trading path (`direct_executor.py`) has MORE risk layers than any backtest engine, but they are distributed across different modules (iron_rule_gate, condition_evaluator, risk_check_and_execute) rather than centralized. The backtest engines have essentially NO explicit risk checks beyond T+1 and sentiment multiplier -- they rely on the score/regime system instead.

---

## DATA QUALITY SUMMARY

| Item | Status | Detail |
|------|--------|--------|
| K-line fields | OK | open/high/low/close/volume/amount/change_pct/amplitude present |
| Time field format | WARNING | Plain date string `"YYYY-MM-DD"` without timezone |
| Adjustment factors | CRITICAL MISSING | No复权 in any bar across 2,348 stocks |
| Data gaps | OK | Only Chinese holiday gaps (Spring Festival, National Day) |
| MA pre-computation | PARTIAL | MA5/MA10/MA20 present on SOME bars but not all |
| Volume zero handling | OK | Backtest engines check for volume > 0 as suspension indicator |

---

## COST MODEL SUMMARY

| Component | Backtest Rate | Live Rate | Correct Rate | Missing |
|-----------|--------------|-----------|-------------|---------|
| Buy commission | 0.03% | Not modeled | 0.03% | Min 5 RMB |
| Sell commission | 0.03% (in 0.13%) | Not modeled | 0.03% | Min 5 RMB |
| Stamp duty (sell only) | 0.10% (in 0.13%) | Not modeled | 0.05% | Backtest overcharges by 0.05% |
| 过户费 (SH only) | Not modeled | Not modeled | 0.002% | Missing entirely |
| Total buy cost | 0.03% | N/A | 0.03% + min 5 RMB | Min 5 RMB |
| Total sell cost | 0.13% | N/A | 0.08% + min 5 RMB + 0.002% (SH) | Misrated by 0.05% |
| Cost configurable | NO | NO | N/A | Hardcoded |

**Note on sell rate:** The backtest charges 0.13% for sell (0.03% commission + 0.10% stamp). Actual A-share stamp duty is 0.05% (halved from 0.10% in August 2023). The sell rate should be 0.03% + 0.05% = 0.08%, plus 0.002% 过户费 for Shanghai stocks. The backtest is **overcharging by 0.05% on every sell**, which means real-world returns would be HIGHER than backtest for sells -- but the missing minimum commission on buys means small-trade returns are inflated.

---

## RECOMMENDED FIX PRIORITY

1. **P0 (BLOCKING LIVE):** Fix CRITICAL-001 (close_session_defense AGY bypass)
2. **P0 (BLOCKING LIVE):** Fix CRITICAL-002 (is_trade_ready require_risk bypass)
3. **P0 (BLOCKING BACKTEST):** Download复权 K-line data (CRITICAL-003)
4. **P0 (BLOCKING BOTH):** Implement minimum commission + 过户费 (CRITICAL-004)
5. **P1:** Consolidate T+1 enforcement (HIGH-001)
6. **P1:** Add local caching of market health/sentiment/outflow for degraded mode (HIGH-004)
7. **P1:** Consolidate position sizing formula (HIGH-002)
8. **P1:** Fix close_session race condition (HIGH-005)
9. **P2:** Fix normalize_intent approval flag mirroring (MEDIUM-001)
10. **P2:** Fix error handling for empty position lists (MEDIUM-002)
