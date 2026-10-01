# Cross-pipeline Direction Conflict — 2026-08-31 (四次迭代审计修复, 至今持续迭代)

## The Bug

Two independent no_agent scripts can have **opposing views on the same stock on the same trading day**, producing buy and sell candidates simultaneously. The execution gate (a deterministic consumer) processes both, resulting in the system buying and selling the same stock within minutes — without any awareness of the conflict.

## Concrete Timeline (2026-08-31, 荣昌生物 688331.SH)

| Time (UTC+8) | Script | Analysis | Action |
|:---|:---|:---|---:|
| 14:16 | `close_session_scan.py` | 30min=range/三卖, 60min=downtrend | **SELL 100股@120.47** — executed directly |
| 14:20 | `intraday_leader_monitor.py` | 30min=range/二买, 量能充沛无顶背驰 | **BUY @121.07** — llm_approved, no shares left |

Also on 2026-08-27, the same `intraday_leader_monitor.py` itself flip-flopped on 荣昌生物:
| Time (UTC+8) | Action | Direction |
|:---|:---|:---|
| 10:21 | sell@119.20 (三卖) | **sell** |
| 10:26 | 拦截买入 (否决) | buy (blocked) |
| Next day 09:52 | buy@121.56 (二买) | **buy** |

Note: The 08-27 case was the same script flip-flopping (sell→then block buy). The 08-31 case was **two different scripts** making opposite decisions on the same day. The final fix addresses all patterns via same-direction blocking.

## Root Cause

**Root cause (two distinct problems):**

1. **System design flaw — Independent Chan analysis without cross-awareness**: Both scripts call `analyze_chanlun()` on the same 30-minute bars and can legitimately reach different conclusions — one position-biased (find exits), one entry-biased (find entries). Neither checks the candidates JSONL for today's opposite-direction events.

2. **Chan analysis ambiguity**: The same stock's structure can be decomposed differently depending on analyst bias. `close_session_scan.py` (position-holder → biased to find exits) sees 三卖; `intraday_leader_monitor.py` (entry finder → biased to find buys) sees 二买. The same 30-min bars yield opposite interpretations. **This is not solved by direction conflict detection alone — if the Chan analysis itself is internally inconsistent on the same K-line data, the direction system is treating symptoms, not causes.**

## Final Fix Architecture (三次迭代, 2026-08-31)

### Iteration 1 — AGY audit (initial code changes)

| Issue | Severity | Fix |
|:---|:---|:---|
| `order.get("direction")` 大写 vs candidate 小写不匹配 | P0 | `.lower().strip()` 归一化 |
| typo `"direciton"` in docstring | P0 | Fixed |
| `dedup_append_many()` 中 `check_direction_conflict()` 无 `force_refresh=True` | P1 | Added `force_refresh=True` |
| `_scan_candidate_directions()` 把**未执行候选**当「已执行」事件 → 假阳性 | P1 | 重构函数，只扫 `submitted` event + `order.detail=executed` |
| 双重扫描：`_build_executed_events` 和 `_scan_candidate_directions` 逻辑完全重复 | P2 | 合并为单次扫描 |

### Iteration 2 — Code consolidation

**`_scan_candidate_directions` merged into `_build_executed_events`**: Before fix, the file was scanned twice (once in `_build_executed_events`, once in the now-removed `_scan_candidate_directions`). After fix, a single pass scans all records, using two extraction strategies:

- **方式A**: `event=submitted/submitted_unverified` + `order.detail=executed` → extract direction from `order.direction` (with `.lower().strip()` normalization)
- **方式B (fallback)**: If `order.direction` is empty, look up the `candidate_id` in the same file via `_infer_direction_from_candidates()`

**Deleted ~40 lines of dead code.**

### Iteration 3 — AGY prompt hardening (昊华科技买入案 driven)

The 昊华科技(600378.SH) buy on 2026-08-31 exposed two flaws:
1. **量价背离未被AGY识别**: 当日成交7643万手（昨日5275万的1.45倍），收跌-1.05% — 经典多头陷阱
2. **风控超时(timed out)后仍执行**: risk batch_check 超时标记了 `risk_rejected`，但系统仍买入了

**Fix to AGY buy-review prompt** (in `intraday_leader_monitor.py`):

```python
2. 趋势与量能：是否上升通道？量能是否配合？特别注意：
   - ⛔ 放量下跌/高开低走收阴 → 多头陷阱，直接 REJECT
   - ⛔ 振幅>5%却收跌 → 典型出货形态，直接 REJECT
   - ✅ 缩量回踩支撑不破 + 次日放量企稳 → 真买点
   - ✅ 放量突破 + 缩量回踩确认 → 真买点
```

## Architecture (current)

```
utils_candidate.py (central utility)
├── check_direction_conflict(path, symbol, direction, force_refresh=False)
│   ├── Builds set of "symbol:direction" from today's JSONL executed events
│   ├── Cache: SYMBOL_EVENT_KEYS_CACHE[filepath] (per-filepath)
│   ├── force_refresh=True clears cache before re-read
│   └── Returns: None=no conflict, "buy"/"sell"=conflicting direction
├── clear_conflict_cache()  — for daily reset / testing
├── dedup_append(path, record)
│   └── calls dedup_append_many()
├── dedup_append_many(path, records)
│   ├── Reads file, builds dedup index by candidate_id
│   ├── For new records: check_direction_conflict(force_refresh=True)
│   │   ├── None conflict → append
│   │   └── Conflict found → skip, write direction_conflict event record
│   └── Rewrites entire file after dedup
└── dedup_file(path) — standalone dedup for batch repair

Each script (close_session_scan, intraday_leader_monitor, intraday_scan):
├── write_candidate() / write_llm_trigger() / append_candidate()
│   ├── check_direction_conflict(force_refresh=True) — pre-write check
│   ├── Conflict → early return, print warning
│   └── No conflict → dedup_append / dedup_append_many
```

### Detection scope

Only checks **executed orders** (`event=submitted/submitted_unverified` + `order.detail=executed`), NOT unexecuted candidates. This avoids false positives where:
- A buy candidate was written but not yet approved → should NOT block a sell
- A sell candidate is pending review → should NOT block a buy from LLM review

### Cache behavior

- `SYMBOL_EVENT_KEYS_CACHE` is per-filepath, process-level global
- `force_refresh=True` in `dedup_append_many` and each script's pre-write check ensures the cache picks up orders executed in the same tick
- `clear_conflict_cache()` exported for cross-day reset
- Cache does NOT expire automatically across days — scripts must call `clear_conflict_cache()` or use `force_refresh=True`

### Two-phase scan ordering bug (2026-08-31 round 2 fix)

**Bug**: `_build_executed_events` built the `candidate_id→direction` index and detected executed events in a **single file scan**. Since JSONL records are written in chronological order, a `candidate_event` (which has no `direction` field in `order`) could appear **before** its corresponding `shadow_candidate` record (which does have `direction`). The fallback logic that looked up `candidate_id` in the index found nothing because the shadow record hadn't been seen yet.

**Example**: `close_session_scan.py` writes:
1. `candidate_event` with `event=submitted, order.detail=executed, order.direction=MISSING`
2. `shadow_candidate` with `direction=sell` (later in file)

When processing the `candidate_event` first, the index doesn't yet contain `shadow-close-...` → direction fallback returns empty → event is skipped → `check_direction_conflict` never sees the executed sell → buy passes through.

**Fix**: Split into two sequential file scans:
- Phase 1: Build candidate_id→direction map from all `candidate` and `shadow_candidate` records
- Phase 2: Scan for `event==submitted` + `order.detail==executed`, using pre-built index

**Also fixed**:
- Index scope expanded from `record_type=="candidate"` only to also include `"shadow_candidate"`
- CID format bridging: `candidate_event` cid format is `"close-*"` (no shadow- prefix) while `shadow_candidate` cid is `"shadow-close-*"`. Fallback now tries both direct lookup and `f"shadow-{cid}"`.

### ⚠️ Design evolution: same-direction blocking (final — 2026-08-31 round 3)

**Final logic**: `check_direction_conflict` blocks **same-direction repeats** (`buy` blocks another `buy`, `sell` blocks another `sell`), NOT opposite directions. This evolved through 3 user-driven iterations:

| Iteration | Logic | Why changed |
|:---|:---|:---|
| 1 | Opposite-direction blocking (buy blocks sell, sell blocks buy) | User complained "为什么又买又卖荣昌" — but opposite-direction blocking isn't the right tool for the root problem |
| 2 | Opposite + fallback shadow indexing | Still didn't fix the real issue |
| 3 (final) | **Same-direction blocking** (buy blocks buy, sell blocks sell, T+1 rule) | The real problem is **T+1**: if you sell a stock today, you can't sell it again. If you buy, you can't buy more. But **you CAN buy after selling (做T纠错)** or sell after buying (倒T纠错). Only same-direction repeats violate T+1. |

**Implementation** (`utils_candidate.py`):
```python
same_dir_key = f"{symbol}:{direction}"  # "688331.SH:buy" or "688331.SH:sell"
if same_dir_key in events:
    return direction  # conflict: same stock, same direction, already executed today
return None
```

**Rationale**:
- **T+1 compliance**: Only same-direction repeats violate T+1. Buy-after-sell (做T) and sell-after-buy (倒T) are legitimate correction trades.
- **User's real complaint**: The user said "为什么又买又卖荣昌" — the problem was contradictory signals from independent scripts, not direction conflict. The same-direction block prevents double-trading without blocking legitimate T-trading.
- **MCP-based detection**: `_build_executed_events` detects `event==submitted` + `order.detail==executed` from the exec MCP, not from candidate records — ensuring only actually-executed orders block.

```python
def check_direction_conflict(path, symbol, direction, force_refresh=False):
    opp = {"buy": "sell", "sell": "buy"}.get(direction)
    conflict_key = f"{symbol}:{opp}"
    if conflict_key in events:
        return opp
    return None
```

### ⚠️ Known Gap: candidate_update bypasses direction conflict detection

**Discovered 2026-09-01 audit**: In `utils_candidate.py` `dedup_append_many()`, the code at ~L312 includes this shortcut:

```python
if rt not in ("candidate", "shadow_candidate") or not symbol or not direction:
    new_records.append(rec)  # candidate_update passes through without conflict check
```

**Consequence**: A `candidate_update` record (written by AGY LLM review script `agy_price_trigger_review.py` to set `llm_approved=True`) bypasses direction conflict detection entirely. The `candidate_update` is silently appended even when there's an existing same-day opposite-direction execution.

**Actual risk**: If a buy candidate's direction-conflict rejection blocks the `candidate` record from being written, but the AGY LLM review later writes a `candidate_update` for the same `candidate_id`, that update:
1. Passes direction conflict check (because `record_type != "candidate"/"shadow_candidate"`)
2. Gets merged into `load_candidates()` results (because the original `candidate` has a matching `candidate_id`)
3. BUT the merged candidate has `direction` from the update but no `price/quantity` from the blocked original → `is_trade_ready()` rejects it for incomplete fields

**Current status**: Low actual risk because the merged candidate lacks price/quantity, so `is_trade_ready()` rejects it. But this is a fragile defense. **Consider adding direction conflict check for `candidate_update` records before the shortcut.**

### Round 6 Fix: Dual-Layer Defense (2026-09-01, commit 87d84f2)

**Trigger**: User reported 荣昌生物 688331.SH as "why both buy and sell" — cross-pipeline contradiction between `close_session_scan.py` (三卖→sell) and `intraday_leader_monitor.py` (二买→buy) on the same day.

**Diagnostic Method** (proven effective — save for future use):

1. **Pull raw evidence first** (do NOT start reasoning):
   ```bash
   python3 -c "
   from scripts.utils_candidate import _build_executed_events
   events = _build_executed_events('trading/feedback/candidates_2026-08-31.jsonl')
   print(events)  # => {'688331.SH:sell', '600378.SH:buy', '600420.SH:buy'}
   "
   ```

2. **Check dedup_append return value**: Verify `write_candidate()` actually passes through `dedup_append`'s return:
   ```bash
   grep -n 'write_candidate\|dedup_append' scripts/intraday_leader_monitor.py
   ```

3. **Check cron output timeline**: Each cron's output is in separate dirs under `cron/output/`:
   ```
   cron/output/7f5916e3340f/2026-08-31/06-16-20.md  # close_session sell@120.47 ✅
   cron/output/intraday-leader-monitor/2026-08-31/06-20-36.md  # AGY放行 荣昌
   cron/output/autonomous-trade-gate/2026-08-31/06-55-24.md  # 买入执行
   ```

**Root cause discovered**: `intraday_leader_monitor.py`'s `write_candidate()` **ignores the return value** of `dedup_append()`. Even when `dedup_append` internally calls `check_direction_conflict()` and returns `False` (conflict detected, nothing written), the script's `write_candidate()` only checks `if result:` — but the actual conflict response comes back as a record, not a boolean. The candidate was written anyway.

**Additional contributing factors**:
- `_build_executed_events` uses `SYMBOL_EVENT_KEYS_CACHE` with mtime-based validation; cross-process writes can have stale mtime → cached empty result
- `dedup_append_many` only sets `force_refresh=True` for the **first** record in a batch
- `close_session_scan.py` and `intraday_leader_monitor.py` are independent cron jobs with **no coordination mechanism**

**Fix (dual-layer)**:

| Layer | File | Location | What it does |
|:---|:---|:---|---:|
| 1 | `intraday_leader_monitor.py` | ~L540-570 (pre-AGY) | Calls `check_direction_conflict(force_refresh=True)` before AGY review; on conflict, skips AGY entirely, writes `direction_conflict` event, returns early — saves AGY API costs |
| 2 | `run_autonomous_trades.py` | ~L161-180 (gate-level) | After `is_trade_ready()` passes but before calling `risk_check`, does one more `check_direction_conflict(force_refresh=True)`; on conflict, marks candidate `risk_rejected` with reason `direction_conflict` and skips |

**Verification**: Both files pass syntax check. However, full integration test requires a live trading day because `intraday_leader_monitor.py` creates real MCP connections and AGY calls — cannot dry-run without MCP services.

**Debugging test** (works offline — only needs utils_candidate):
```bash
python3 -c "
from scripts.utils_candidate import check_direction_conflict, clear_conflict_cache
import json, tempfile, os

# Create test JSONL with an executed sell
tf = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
record = {
    'event': 'submitted', 'symbol': '688331.SH', 'direction': 'sell',
    'order': {'detail': 'executed'}
}
tf.write(json.dumps(record, ensure_ascii=False) + '\n')
tf.close()

# Same direction sell → blocked
r = check_direction_conflict(tf.name, '688331.SH', 'sell', force_refresh=True)
assert r == 'sell', f'Expected sell blocked, got {r}'

# Opposite direction buy → ALLOWED (做T纠错, T+1合规)
r = check_direction_conflict(tf.name, '688331.SH', 'buy', force_refresh=True)
assert r is None, f'Expected buy allowed, got {r}'

os.unlink(tf.name)
clear_conflict_cache()
print('✅ Same-direction blocks, opposite allows — T+1 compliance verified')
print('✅ Dual-layer fix: AGY saves on conflict + gate-level backstop active')
"
```

### 🔴 User-Found Bug Response Protocol (2026-09-01)

When a user reports a system inconsistency like "你为什么又买又卖荣昌，让我很茫然":

**Step 1 — Pull real data immediately**: Do NOT start reasoning about fixes. First collect:
- Today's trade records (`mcp_exec_get_today_trades`)
- Today's orders (`mcp_exec_get_orders`)
- Today's JSONL candidates (`candidates_{date}.jsonl`)
- Cron job output from relevant tasks (under `cron/output/<job_id>/<date>/`)
- Test `_build_executed_events` on the actual JSONL to confirm if the executed events are detectable

**Step 2 — Audit before fix**: 
- When user says "让AGY审计审查" do exactly that — initiate independent audit via delegate_task or AGY CLI
- If subagent audit times out (600s limit), break audit into smaller rounds (one concern per round, 10-20 calls)
- Do NOT self-audit and fix in one step then claim "fixed" — user explicitly rejected this pattern
- But if user says "你自己查" — do self-diagnosis with data, then report findings

**Step 3 — Data-driven diagnosis**: Write concrete Python test commands to prove each hypothesized bug exists before fixing. Show actual test output to the user.

**Step 4 — Fix + independent verification**: After fixing, run the same test commands to prove the fix works. Show before/after evidence.

**Step 5 — Track the `write_candidate` return value**: This is the most common failure pattern — `dedup_append` correctly returns `False` for conflict, but caller ignores it. When debugging direction conflicts, the first check should always be: does `write_candidate` inspect and propagate the return value of `dedup_append`/`dedup_append_many`?

## Chan Analysis Ambiguity — The Deeper Problem

AGY-approved `shadow_candidate` records with `llm_approved=True` (e.g., 海鸥股份 +10.01%, 易点天下 +7.28%, 英维克 +5.78% on 2026-08-31) are written to JSONL but **never consumed by `run_autonomous_trades.py`** — the gate only processes `record_type=="candidate"`. Not yet fixed.

## Reusable pattern: two-phase scan for ordering-sensitive JSONL

This pattern solves a general problem: when a JSONL file has records written in chronological order, and a later record is needed to interpret an earlier one (e.g., a `shadow_candidate` provides the `direction` field missing from its preceding `candidate_event` record).

**When to use this pattern**:
- Multiple no_agent scripts write to the same JSONL file
- Records within a single script's write batch have dependency (e.g., candidate_event → shadow_candidate)
- A summary record written after the main record needs to be available during indexing

**Pattern**:
```python
def _build_executed_events(filepath):
    """Two-phase scan for ordering-safe direction detection."""
    # Phase 1: Build lookup index from ALL records (candidate + shadow_candidate)
    cid_to_direction = {}
    all_records = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            all_records.append(rec)
            # Phase 1: Build direction index from candidate + shadow_candidate
            rt = rec.get("record_type") or rec.get("type", "")
            if rt in ("candidate", "shadow_candidate"):
                # Try order.direction first, then rec.direction
                direction = (rec.get("order") or {}).get("direction", "")
                if not direction:
                    direction = rec.get("direction", "")
                cid = rec.get("candidate_id", "")
                if cid and direction:
                    cid_to_direction[cid] = direction.lower().strip()
                    # Also register shadow-{cid} variant for bridged lookups
                    if rt == "shadow_candidate" and not cid.startswith("shadow-"):
                        cid_to_direction[f"shadow-{cid}"] = direction.lower().strip()

    # Phase 2: Scan for executed events using pre-built index
    events = set()
    for rec in all_records:
        event = rec.get("event", "")
        if event in ("submitted", "submitted_unverified"):
            order = rec.get("order") or {}
            if order.get("detail") == "executed":
                # Direct direction from order
                d = (order.get("direction") or "").lower().strip()
                # Fallback: look up candidate_id in index
                if not d:
                    cid = rec.get("candidate_id", "")
                    d = cid_to_direction.get(cid, "") or cid_to_direction.get(f"shadow-{cid}", "")
                if d:
                    events.add(f"{rec.get('symbol','')}:{d}")
    return events
```

**Key insight**: Phase 1 builds a complete index from the entire file first, then Phase 2 uses it. This is equivalent to sorting by record type before processing — but without actually sorting (since the file is append-only with interleaved record types).

```bash
# Quick test
python3 -c "
from scripts.utils_candidate import check_direction_conflict, clear_conflict_cache
# No cache → empty path → returns None
assert check_direction_conflict('/tmp/nonexistent.jsonl', '600378.SH', 'buy') is None
clear_conflict_cache()
print('✅ check_direction_conflict works')
"

# Full integration test (verify same-direction blocking)
python3 -c "
from scripts.utils_candidate import (
    check_direction_conflict, clear_conflict_cache, 
    _build_executed_events, DEDUP_DIR
)
import os, json, tempfile

# Create test JSONL with an executed sell event
tf = tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False)
record = {
    'event': 'submitted', 'symbol': '688331.SH', 'direction': 'sell',
    'order': {'detail': 'executed'}
}
tf.write(json.dumps(record, ensure_ascii=False) + '\n')
tf.close()

# Same direction sell → should be blocked
result = check_direction_conflict(tf.name, '688331.SH', 'sell', force_refresh=True)
assert result == 'sell', f'Expected sell blocked, got {result}'

# Opposite direction buy → should be ALLOWED (做T纠错)
result = check_direction_conflict(tf.name, '688331.SH', 'buy', force_refresh=True)
assert result is None, f'Expected buy allowed, got {result}'

os.unlink(tf.name)
clear_conflict_cache()
print('✅ Same-direction blocks, opposite-direction allows — T+1 compliance verified')
"
```

## Chan Analysis Ambiguity — The Deeper Problem

**What actually happened with 荣昌生物 on 2026-08-31:**

- `close_session_scan.py` analyzed 30-min bars → saw **range-bound consolidation, potential 三卖** → generated SELL
- `intraday_leader_monitor.py` analyzed 30-min bars → saw **range-bound consolidation, potential 二买** → generated BUY
- **Same 30-min bars, opposite conclusions**

**Why this happens:** Chan theory has inherent ambiguity at the stroke/segment decomposition level. Two analysts (or two scripts) can look at the same K-line data and draw different strokes if they bias toward exit-finding vs entry-finding. The direction conflict detection (same-direction blocking) prevents the *execution* of contradictory signals, but it doesn't fix the *analysis quality* that produces them.

**Detection:** If a user reports contradictory signals for the same stock on the same day, and both scripts used the same period K-line data, the root cause is **Chan analysis inconsistency**, not just direction conflict detection. Audit must include comparing the two scripts' stroke decomposition and hub identification.

**Mitigation (not solved yet as of 2026-09-01):**
1. Both scripts should share a common `chanlun_engine.py` module with deterministic stroke decomposition — not independent `analyze_chanlun()` implementations
2. Or a single script should produce both buy and sell recommendations from the same analysis pass, rather than two scripts independently re-analyzing
3. Short-term: the direction conflict system prevents actual harm (no execution of contradictory orders), but the quality issue remains

This is documented here rather than creating a separate skill because it's the same class of problem (direction consistency) with a deeper root cause.

Any new no_agent script that writes trading candidates must:

1. Always import `check_direction_conflict` from `utils_candidate`
2. Before writing any candidate via `dedup_append`/`dedup_append_many`, call `check_direction_conflict(path, symbol, direction, force_refresh=True)`
3. Always set `awaiting_llm_review: True` — never write directly-executable candidates
