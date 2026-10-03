# PHASE 2B.1 REPORT — Pattern Incremental Attribution + Date-Cluster Bootstrap

## 1. STATUS

**PASS**

Phase 2B.1 extends Phase 2B's event-level OOS validation with three new analyses: (1) pattern incremental attribution measuring the marginal contribution of each pattern, (2) solo vs concurrent breakdown distinguishing single-pattern from multi-pattern events, and (3) date-cluster bootstrap accounting for within-day cross-sectional correlation. All 23 tests pass, full regression 400 passed, 0 failed.

---

## 2. OBJECTIVE

Phase 2B established event-level baselines but left three questions unanswered:

1. **Incremental**: Does pattern P add value beyond what other patterns already capture in the same regime/period?
2. **Concurrence**: Does pattern P perform differently when it fires alone vs alongside other patterns?
3. **Clustering**: Are bootstrap CIs too narrow because they treat same-date events as independent?

Phase 2B.1 answers all three.

---

## 3. DATA

| Metric | Value |
|--------|-------|
| Total events | 282,892 |
| OOS events | 69,679 |
| OOS single-pattern | 25,799 (37.0%) |
| OOS multi-pattern | 43,880 (63.0%) |
| Unique OOS dates | 124 |
| Time split | TRAIN: 2024-10-01~2025-09-30, VAL: 2025-10-01~2026-03-31, OOS: 2026-04-01~2026-10-01 |

---

## 4. INCREMENTAL ATTRIBUTION

### Methodology

For each (pattern, regime, period), events are split into **present** (pattern fires) and **absent** (pattern does not fire). The incremental value is `present_mean - absent_mean`, bootstrapped with both event-level and date-cluster methods (1000 iterations, seed=42, 95% CI).

### Evidence Distribution

| Grade | Count | Criteria |
|-------|-------|----------|
| STRONG | 1 | n≥100, STABLE_POSITIVE, both CI types > 0 |
| MODERATE | 12 | n≥30, STABLE_POSITIVE, event CI > 0 |
| WEAK | 57 | n≥30, STABLE_POSITIVE, CI crosses zero |
| INCONCLUSIVE | 2 | n<30 or non-stable |

### STRONG Evidence

| Pattern | Regime | Present N | Inc Mean | Inc Win Rate | Event CI | Date-Cluster CI |
|---------|--------|-----------|----------|--------------|----------|-----------------|
| lu_sniper | hot | 1,054 | +0.90% | +10.2pp | [+0.26, +1.57] | [+0.04, +1.64] |

### MODERATE Evidence (top by incremental mean)

| Pattern | Regime | Present N | Inc Mean | Inc Win Rate |
|---------|--------|-----------|----------|--------------|
| single_yang | hot | 1,141 | +0.94% | +7.0pp |
| lu_sniper | hot | 1,054 | +0.90% | +10.2pp |
| long_yang_seven | hot | 515 | +0.81% | +5.1pp |
| single_yang | warmup | 1,299 | +0.77% | -0.4pp |
| breakout | cooldown | 2,176 | +0.63% | -0.1pp |
| old_duck | ice | 844 | +0.61% | +5.2pp |

### Key Observation

Most patterns show **positive incremental mean** but **negative or near-zero incremental win rate**. Only lu_sniper/hot (+10.2pp), long_yang_seven/hot (+5.1pp), single_yang/hot (+7.0pp), and old_duck/ice (+5.2pp) increase win rate when present. For most patterns, presence improves return magnitude but not directional accuracy — they amplify wins and losses proportionally.

---

## 5. SOLO VS CONCURRENT

### Methodology

Each event is classified by `pattern_count`: 1 → solo, >1 → concurrent. For each pattern, metrics are computed separately for solo events (where it's the only pattern) and concurrent events (where it fires alongside others).

### Selected Results (OOS, warmup, n≥100)

| Pattern | Solo N | Solo Mean | Solo WR | Concurrent N | Concurrent Mean | Concurrent WR |
|---------|--------|-----------|---------|-------------|-----------------|---------------|
| gap_proof | 8,046 | +0.43% | 58.1% | 14,232 | +0.55% | 56.6% |
| t1_swing | 1,045 | +0.05% | 56.0% | 14,851 | +0.62% | 56.2% |
| lu_sniper | 1,241 | +0.55% | 59.9% | 1,082 | +0.72% | 58.4% |
| old_duck | 1,144 | +0.71% | 53.0% | 11,079 | +0.75% | 54.4% |
| breakout | 198 | +1.24% | 58.6% | 10,225 | +0.76% | 54.5% |

### Key Observation

Contrary to Phase 2B's aggregate finding, **solo does not universally outperform concurrent** when broken down by pattern. Some patterns (lu_sniper, gap_proof, t1_swing) actually show **higher returns in concurrent** settings — likely because concurrence confirms the signal. Others (breakout) show much higher solo returns but on tiny sample sizes. Win rates are mixed: lu_sniper solo has 59.9% WR vs 58.4% concurrent, but old_duck solo is 53.0% vs 54.4% concurrent.

---

## 6. DATE-CLUSTER BOOTSTRAP

### Methodology

Standard bootstrap treats each event as independent. But events on the same date share market conditions — the day's overall return, sector moves, macro news. Date-cluster bootstrap resamples by `signal_date` with replacement, including ALL events for each sampled date. This produces wider CIs than event bootstrap.

### Overall OOS Comparison (n=69,679, 124 dates)

| Statistic | Event Bootstrap CI | Date-Cluster CI | Width Ratio |
|-----------|-------------------|-----------------|-------------|
| Mean return | [+0.50, +0.58] | [+0.19, +0.86] | 8.4x |
| Median return | [+1.18, +1.25] | [+0.88, +1.44] | 7.6x |
| Win rate | [54.3, 55.1] | [51.9, 57.6] | 7.1x |

### By Regime (mean return)

| Regime | N Events | N Dates | Event CI | Date-Cluster CI |
|--------|----------|---------|----------|-----------------|
| warmup | 31,990 | 66 | [+0.53, +0.66] | [+0.16, +1.04] |
| hot | 29,780 | 37 | [+0.42, +0.54] | [-0.09, +0.99] |
| cooldown | 6,207 | 16 | [+0.19, +0.52] | [-0.36, +1.15] |
| ice | 1,702 | 5 | [+0.97, +1.40] | [+0.40, +2.48] |

### Key Observation

Date-cluster CIs are consistently **3-8x wider** than event-bootstrap CIs. The hot regime's date-cluster mean CI crosses zero [-0.09, +0.99], meaning we cannot reject the null at 95% confidence when accounting for within-day clustering — even though event bootstrap is tight and positive. Ice has only 5 unique dates, making its CI extremely wide. This confirms that within-day correlation is economically meaningful and cannot be ignored.

---

## 7. STABILITY

Stability compares OOS incremental performance against train+val incremental performance:

| Grade | Count | Rule |
|-------|-------|------|
| STABLE_POSITIVE | 70 | train+val inc > 0 AND OOS inc > 0 |
| STABLE_NEGATIVE | 0 | train+val inc < 0 AND OOS inc < 0 |
| SIGN_FLIP | 0 | train+val sign != OOS sign |
| INSUFFICIENT_DATA | 2 | train+val unavailable |

All 70 meaningful candidates are STABLE_POSITIVE — the incremental effects observed in OOS are consistent with the direction seen in train+val. No pattern's incremental contribution flips sign between in-sample and out-of-sample.

---

## 8. LIMITATIONS

1. **Date-cluster bootstrap assumes within-date independence**: Resampling dates accounts for date-level clustering but assumes stocks within a date are IID beyond the shared date effect. Industry or factor clustering within a date is not modeled.

2. **Incremental attribution is regime-matched, not causal**: Present vs absent comparison controls for regime and period but cannot control for all confounding variables. A pattern may appear "incremental" because it triggers on higher-quality setups, not because the pattern itself adds value.

3. **Solo sample sizes are small**: Most solo breakdowns have n<500, making solo vs concurrent comparisons noisy.

4. **6-month OOS**: Only 124 unique OOS dates. Date-cluster bootstrap is limited by the number of unique dates, not the number of events.

5. **No transaction costs**: All returns are gross. Incremental win rate improvements may not survive real-world costs.

6. **theme_lifecycle NOT_AVAILABLE**: No lifecycle data source exists in the codebase.

7. **Survivorship bias**: Current universe contains only stocks that survived to the present.

---

## 9. CONCLUSION

Phase 2B.1 provides three key methodological extensions:

- **Incremental attribution** reveals that lu_sniper in hot regimes is the only pattern with STRONG incremental evidence (mean return +0.90% and win rate +10.2pp above absent baseline). 12 patterns have MODERATE incremental evidence. Most patterns improve return magnitude but not directional accuracy.

- **Solo vs concurrent** analysis shows the relationship is more nuanced than Phase 2B's aggregate finding suggested — solo does not universally outperform concurrent at the individual pattern level.

- **Date-cluster bootstrap** demonstrates that within-day correlation is economically meaningful: CIs widen by 3-8x. The hot regime's date-cluster mean CI crosses zero, and ice regime has only 5 unique dates making inference unreliable. Any downstream use of bootstrap CIs must account for date clustering.

---

## 10. FILES

### New Files

| File | Lines/Rows | Description |
|------|-----------|-------------|
| `scripts/phase2b1_incremental_attribution.py` | 796 | Main Phase 2B.1 engine |
| `tests/test_phase2b1.py` | 415 | 23 test cases |
| `docs/reverse_engineering/PHASE_2B1_REPORT.md` | — | This report |

### Generated Output Files

| File | Rows | Description |
|------|------|-------------|
| `results/pattern_incremental_attribution.csv` | 265 | Pattern presence with both bootstrap CIs + incremental metrics |
| `results/pattern_solo_concurrent.csv` | 474 | Solo vs concurrent breakdown per pattern |
| `results/pattern_date_cluster_bootstrap.csv` | 21 | Overall/regime/event_type date-cluster vs event bootstrap |
| `results/pattern_incremental_evidence.csv` | 72 | OOS incremental evidence with stability and evidence_status |

**No existing files modified.**

---

## 11. CI STATUS

```
tests/test_phase2b1.py — 23 passed, 0 failed
Full regression      — 400 passed, 0 failed
```
