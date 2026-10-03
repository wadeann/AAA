# PHASE 2B.1 CODE AUDIT

## STATUS

**VERIFIED WITH LIMITATIONS**

The Phase 2B.1 implementation correctly performs all claimed analyses. No material defects found. Six documented limitations affect statistical interpretation but not code correctness.

---

## A. Report vs Implementation

| Claim | Report | Code | Verification |
|---|---|---|---|
| Total events | 282,892 | 282,892 | PASS |
| OOS events | 69,679 | 69,679 | PASS |
| OOS dates | 124 | 124 | PASS |
| Attribution rows | 265 | 265 | PASS |
| Solo/concurrent rows | 474 | 474 | PASS |
| Date-cluster rows | 21 | 21 | PASS |
| Evidence rows | 72 | 72 | PASS |
| STRONG evidence | 1 | 1 (lu_sniper/hot) | PASS |
| MODERATE evidence | 12 | 12 | PASS |
| WEAK evidence | 57 | 57 | PASS |
| INCONCLUSIVE evidence | 2 | 2 | PASS |
| Bootstrap iterations | 1,000 | 1,000 | PASS |
| Bootstrap seed | 42 | 42 | PASS |
| CI confidence | 95% | 95% | PASS |
| Hot regime DC CI | [-0.09, +0.99] | [-0.091, +0.985] | PASS |
| Date-cluster wider | "3-8x" | 4.5–9.0x | **MINOR: actual range is wider** |
| theme_lifecycle | NOT_AVAILABLE | NOT_AVAILABLE | PASS |
| No ranking fields | claimed | verified in all CSVs | PASS |
| Event ID unique | 282,892 unique | 0 duplicates | PASS |
| Multi-pattern % | 65.1% | 65.1% | PASS |
| No period overlap | train/val/OOS | 0 shared dates | PASS |
| Primary metric | return_median | return_median | PASS |

---

## B. Critical Findings

**None.** No material defects found in the implementation.

---

## C. Statistical Findings

### C.1 Event Bootstrap
- Uses `numpy.random.RandomState(42)` — deterministic ✓
- Resamples individual event values (not pattern rows, not profile rows) ✓
- 1,000 iterations, 95% percentile CI ✓
- Handles n<2 gracefully (returns None for CIs) ✓

### C.2 Date-Cluster Bootstrap
- Resamples by `signal_date` with replacement ✓
- ALL events for each sampled date included ✓
- Duplicate sampled dates correctly duplicate all their events ✓
- `RandomState(42)`, deterministic output verified ✓
- Point estimate computed on full population (not bootstrapped) ✓

### C.3 Incremental Bootstrap
- **Event method**: Independently resamples present and absent values, computes `mean(p_sample) - mean(a_sample)` inside each iteration ✓
- **Date-cluster method**: Independently resamples present dates and absent dates, computes `mean(p_vals) - mean(a_vals)` inside each iteration ✓
- Point estimate = `mean(all_present) - mean(all_absent)` ✓
- **Limitation**: Present and absent groups have different date pools. Date-cluster incremental bootstrap resamples from two independent date pools — dates are not matched between groups within each iteration. This is inherent: the same event cannot be both present and absent.

### C.4 Clustering Impact
CI width ratios (date-cluster / event-bootstrap) for mean return:

| Group | Ratio |
|---|---|
| Overall | 8.1x |
| hot regime | 9.0x |
| warmup regime | 6.9x |
| cooldown regime | 4.5x |
| ice regime | 4.8x |
| single_pattern | 5.3x |
| multi_pattern | 6.2x |

Range: **4.5x to 9.0x** (report says "3-8x" — actual range is slightly wider at the upper bound)

### C.5 Events Per Date Distribution (OOS)
- mean=562, median=520, p95=1,053, max=1,325, min=100
- Some dates have 2.5x more events than the median
- Five ice-regime dates carry 1,702 events — very concentrated

---

## D. Implementation Trace

| Step | Function | File:Line |
|---|---|---|
| Load events | `load_events()` | phase2b1:43-45 |
| Period classification | `get_period()` | phase2b1:48-55 |
| Event bootstrap | `event_bootstrap_ci()` | phase2b1:70-106 |
| Date-cluster bootstrap | `date_cluster_bootstrap()` | phase2b1:109-180 |
| Incremental bootstrap | `incremental_bootstrap()` | phase2b1:183-278 |
| Pattern presence | `compute_pattern_presence()` | phase2b1:285-367 |
| Solo/concurrent | `compute_solo_concurrent()` | phase2b1:374-427 |
| Date-cluster summary | `compute_date_cluster_summary()` | phase2b1:434-502 |
| Evidence grading | `compute_incremental_evidence()` | phase2b1:509-590 |
| Attribution CSV | `write_attribution_csv()` | phase2b1:597-615 |
| Solo/concurrent CSV | `write_solo_concurrent_csv()` | phase2b1:618-632 |
| Date-cluster CSV | `write_date_cluster_csv()` | phase2b1:635-649 |
| Evidence CSV | `write_evidence_csv()` | phase2b1:652-668 |

**Event identity**: `event_id = symbol + signal_date` (pre-computed in Phase 2B's `event_level_trades.csv`). Phase 2B.1 reads this CSV directly — no re-aggregation.

**Primary outcome metric**: `return_median` — the median of all profile returns within an event. Same metric reused for all patterns present in that event.

**Pattern presence**: For each pattern P, an event is "present" if P appears in the event's `patterns` field (pipe-separated). "Absent" if it does not. Each event counted exactly once per (pattern, regime, period).

**Solo/concurrent**: `pattern_count == 1` → solo; `pattern_count > 1` → concurrent. `pattern_count` is from the pre-computed Phase 2B field, verified to match actual unique pattern count (0 mismatches in 282,892 events).

**Incremental formula**: `mean(present_returns) - mean(absent_returns)`, matched by (regime, period). Both groups filtered to same regime AND same period.

---

## E. Evidence Grading Logic

Exact conditions from `compute_incremental_evidence()` (lines 556-568):

```python
if n < 30 or stability == INSUFFICIENT_DATA:
    INCONCLUSIVE
elif stability == SIGN_FLIP:
    WEAK
elif incremental_event_ci_low > 0:
    if incremental_date_cluster_ci_low > 0:
        STRONG
    else:
        MODERATE
elif incremental_event_ci_low <= 0:
    WEAK
else:
    INCONCLUSIVE
```

Stability (lines 546-553):
```python
if train_val_avg > 0 and oos_inc > 0:   STABLE_POSITIVE
elif train_val_avg < 0 and oos_inc < 0:  STABLE_NEGATIVE
else:                                     SIGN_FLIP
```

Key observations:
- STRONG requires BOTH event CI and date-cluster CI > 0 (very strict)
- MODERATE requires event CI > 0 but date-cluster CI may cross zero
- Evidence grade uses OOS outcomes (incremental mean and CIs) — this is correct because evidence is computed on OOS data
- Stability uses train+val average vs OOS — train/val incremental was computed from train/val data only, no leakage
- No OOS data used to define thresholds

---

## F. Confounding Assessment

For the only STRONG evidence (lu_sniper/hot):
- Present: 1,054 events, 526 single (49.9%) / 528 multi (50.1%)
- Absent: 28,726 events, 10,184 single (35.5%) / 18,542 multi (64.5%)

The absent group has proportionally more multi-pattern events. Since multi-pattern events have different return characteristics, this compositional difference could confound the incremental estimate. Regime+period matching controls for time and market regime but not for event complexity (pattern_count distribution).

This is a **statistical limitation**, not a code defect. The matching conditions on (regime, period) as specified.

---

## G. Look-Ahead Audit

**PASS** — No future data leakage detected.

- `compute_pattern_presence()`: Filters events by period BEFORE computing present/absent (line 302: `period_events = [e for e in events if get_period(e["signal_date"]) == period]`)
- `compute_incremental_evidence()`: Only processes OOS rows (line 513: `if r["period"] != "oos": continue`). Train/val incremental means pulled from pre-computed attribution rows.
- `compute_date_cluster_summary()`: Only uses OOS events (line 439: `oos_events = [e for e in events if get_period(e["signal_date"]) == "oos"]`)
- No sorting, rolling, grouping, or matching operations span period boundaries
- Full dataset loaded at start — this is fine; filtering happens before computation

---

## H. Baseline

Phase 2B.1 does **not** use the Phase 2A.1 sampled baseline (`baseline_return` / `baseline_excess_mean`). The `baseline_n` field in output CSVs refers to the count of absent events (the within-dataset comparison group), not the external baseline.

Incremental attribution = `present_mean - absent_mean`, where absent = all events in same (regime, period) that do NOT contain the pattern. This is a **within-population comparison**, not an external benchmark.

---

## I. Test Quality Assessment

23 tests in `test_phase2b1.py`:

| Coverage Area | Tests | Quality |
|---|---|---|
| Event uniqueness | test_event_id_unique, test_event_count_correct | PASS — direct CSV verification |
| Pattern presence | test_pattern_presence_single_count | PASS — checks 5,000 events |
| No duplication | test_no_event_duplication_in_attribution | PASS — cross-references event CSV |
| Solo/concurrent | test_solo_events_have_pattern_count_1, test_solo_concurrent_csv_event_types | PASS — data-based checks |
| Incremental calc | test_incremental_mean_calculation, test_incremental_win_rate_calculation | **PASS — independent deterministic fixtures with hand-computed expected values** |
| Date-cluster bootstrap | test_date_cluster_bootstrap_resamples_dates, test_date_cluster_vs_event_bootstrap_different | PASS — synthetic data with known properties |
| Determinism | test_event_bootstrap_deterministic, test_date_cluster_bootstrap_deterministic, test_incremental_bootstrap_deterministic | PASS — same seed = same output |
| OOS isolation | test_oos_isolation, test_train_val_oos_no_date_overlap | PASS — date boundary checks |
| theme_lifecycle | test_event_csv_theme_lifecycle | PASS — checks 500 events |
| No ranking | test_no_ranking_fields_in_evidence, test_no_ranking_fields_in_attribution | PASS — forbidden field check |
| Legacy | test_phase2b_event_csv_readable, test_phase2b_evidence_csv_readable | PASS — Phase 2B files still readable |
| Helpers | test_get_period, test_get_sample_label | PASS — basic unit tests |
| Edge cases | test_bootstrap_small_sample | PASS — n=2 graceful handling |

**Not tested**: Evidence grading logic (STRONG/MODERATE/WEAK/INCONCLUSIVE) has no test with deterministic fixtures. Stability computation has no direct test. These are tested indirectly via CSV output assertions.

No test merely asserts output against itself. Incremental calculation tests use hand-computed expected values from deterministic fixtures.

---

## J. Phase 2C Readiness

**READY WITH CONDITIONS**

Phase 2B.1 is methodologically sound and correctly implemented. The following should be considered before Phase 2C:

1. **Date-cluster CI width**: CIs are 4.5–9.0x wider than event bootstrap. For hot regime, the mean date-cluster CI crosses zero. This means statistical confidence at the regime level is lower than event-bootstrap alone suggests. Phase 2C should use date-cluster CIs as the primary uncertainty measure.

2. **Confounding in absent groups**: Present vs absent groups differ in pattern_count composition. Phase 2C should consider matching on event complexity (pattern_count) in addition to regime+period, or at minimum document this as a known confound.

3. **Evidence grading is conservative**: Requiring both event CI AND date-cluster CI > 0 for STRONG is strict — only 1 pattern passes. This is appropriate for avoiding false positives but means most evidence is WEAK (57/72).

4. **Solo sample sizes**: Many solo breakdowns have n<100. Solo vs concurrent comparisons should be interpreted cautiously for low-n patterns.

5. **Ice regime**: Only 5 unique OOS dates with 1,702 events. Date-cluster bootstrap on ice is unreliable. Any Phase 2C ice-regime decisions should acknowledge this.

6. **6-month OOS**: 124 dates is the minimum for date-cluster bootstrap. As more data accumulates, CIs will narrow.

---

## K. Artifacts Verified

| File | Type | Status |
|---|---|---|
| `scripts/phase2b1_incremental_attribution.py` (796 lines) | Implementation | VERIFIED |
| `tests/test_phase2b1.py` (415 lines) | Tests | VERIFIED |
| `docs/reverse_engineering/PHASE_2B1_REPORT.md` | Report | VERIFIED (minor: CI width claim) |
| `results/pattern_incremental_attribution.csv` (265 rows) | Output | VERIFIED |
| `results/pattern_solo_concurrent.csv` (474 rows) | Output | VERIFIED |
| `results/pattern_date_cluster_bootstrap.csv` (21 rows) | Output | VERIFIED |
| `results/pattern_incremental_evidence.csv` (72 rows) | Output | VERIFIED |

**No existing files were modified.** Confirmed via `git show --stat 034a36a`.

---

## L. Regression

```
tests/test_phase2b1.py — 23 passed, 0 failed
Full test suite       — 400 passed, 0 failed
```

All tests executed on current HEAD (034a36a).
