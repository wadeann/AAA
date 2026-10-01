Patching existing file with additional fix history.

## Cross-pipeline direction conflict (2026-08-31 fix)

**Problem**: Multiple independent no_agent scripts each run their own Chan analysis and write candidates to the shared `candidates_{date}.jsonl` without any awareness of each other's real-time decisions. This causes opposing buy/sell signals on the same stock on the same trading day.

**Real example** (2026-08-31, 688331.SH 荣昌生物):
- 06:16 UTC: `close_session_scan.py` → range/三卖 + downtrend → **SELL 100股@120.47** ✅
- 06:20 UTC: `intraday_leader_monitor.py` → range/二买 + 量能充沛 → **BUY @121.07** (no shares left)

**Fix — 3-layer defense in `utils_candidate.py`**:

Layer 1 — `check_direction_conflict(path, symbol, direction)` scans today's JSONL for `event=submitted` + `order.detail=executed` records with the same symbol but opposite direction. Returns the conflicting direction or None. Uses a per-filepath cache (`SYMBOL_EVENT_KEYS_CACHE`) to avoid repeated I/O.

Layer 2 — Each script's `append_candidate()`/`write_candidate()`/`write_llm_trigger()` calls `check_direction_conflict(force_refresh=True)` before writing. If conflict found, returns early with a print warning. The `force_refresh=True` ensures the cache picks up any order executed in the same tick.

Layer 3 — `dedup_append_many()` (central dedup function) has the same check as a fallback for any caller that doesn't do its own pre-check. Rejected candidates are recorded as `direction_conflict` events in the JSONL.

**Affected scripts**: `close_session_scan.py`, `intraday_leader_monitor.py` (both `write_candidate` and `write_llm_trigger`), `intraday_scan.py`.

**Detection scope**: `event=submitted`/`submitted_unverified` with `order.detail=executed`. Also scans `record_type=candidate` for direction metadata to detect pending candidates' direction intent.

## thesis prefix — `llm_approved` exemption (2026-08-27 fix)

`is_trade_ready()` also gates BUY candidates on the `[缺口逻辑]` prefix in the thesis string. This was designed for candidate data from the wencai-based researcher pipeline. However, the AGY fast channel (`intraday_leader_monitor.py` → direct AGY call) produces theses that do not include this prefix format.

**Fix (2026-08-27)**: `is_trade_ready()` now exempts candidates with `llm_approved: true` from the thesis prefix check. AGY's natural language thesis is accepted as-is.
