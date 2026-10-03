# PHASE 2C REPORT — OOS Regime × Pattern Candidate Validation

## 1. Executive Summary

Phase 2C evaluates 76 (regime, pattern) combinations in OOS (2026-04-01 ~ 2026-10-01) using Phase 2B.1 date-cluster bootstrap evidence as the primary uncertainty measure. **21 candidates qualify** with date-cluster CI > 0, all in warmup (13) and hot (8) regimes. **30 are provisional** — positive mean returns but date-cluster CIs cross zero. **21 are LOW_DATE_COUNT**, all in ice regime (5 OOS dates). **4 are INSUFFICIENT** (sample or return criteria not met). Cooldown has 0 qualified candidates (all date-cluster CIs cross zero with only 16 OOS dates).

---

## 2. Scope

Phase 2C is **research validation only**. It does not:
- Rank patterns or declare a "best"
- Modify strategies, sell rules, or regime definitions
- Build a router or position allocator
- Enable/disable any pattern for trading
- Generate recommendations for live trading

The sole objective: identify which (regime, pattern) combinations have sufficient OOS statistical evidence to warrant independent re-validation in a future phase (Phase 2D).

---

## 3. Input Data Provenance

| File | Source | Key Fields Used |
|------|--------|----------------|
| `results/event_level_trades.csv` | Phase 2B | event_id, signal_date, market_regime, patterns, profiles, pattern_count, baseline_excess_mean, return_median |
| `results/pattern_incremental_attribution.csv` | Phase 2B.1 | pattern_name, regime, period, n_events, mean_return, median_return, win_rate, date_cluster_ci |
| `results/pattern_incremental_evidence.csv` | Phase 2B.1 | pattern_name, regime, evidence_status, stability |
| `results/pattern_date_cluster_bootstrap.csv` | Phase 2B.1 | Aggregate regime-level date-cluster CIs |

All data is from committed phases. No data was regenerated.

---

## 4. OOS Definition

```
OOS: 2026-04-01 ~ 2026-10-01 (124 unique trading dates)
TRAIN: 2024-10-01 ~ 2025-09-30 (244 dates)
VALIDATION: 2025-10-01 ~ 2026-03-31 (116 dates)
```

OOS boundaries are identical to Phase 2B/2B.1. No modification.

---

## 5. Candidate Qualification Rules

Date-cluster bootstrap CI is the **primary uncertainty measure**. Event bootstrap CI is reported but not used for qualification decisions.

```
QUALIFIED:
  n_events >= 100
  n_dates >= 20
  date_cluster_mean_ci_low > 0
  mean_return > 0
  median_return > 0

PROVISIONAL:
  n_events >= 30
  n_dates >= 10
  mean_return > 0
  BUT date_cluster CI not confirmed positive (crosses zero or n_dates < 20)

INSUFFICIENT:
  n_events < 30
  OR mean_return <= 0

LOW_DATE_COUNT:
  n_dates < 10  (priority over all other rules)
```

Priority: LOW_DATE_COUNT > INSUFFICIENT > PROVISIONAL > QUALIFIED

These thresholds are research qualification rules, not optimized parameters. They reuse Phase 2B.1's n≥100/n≥30 sample size conventions.

---

## 6. Regime × Pattern Results

### Summary

| Regime | QUALIFIED | PROVISIONAL | INSUFFICIENT | LOW_DATE_COUNT | Total |
|--------|-----------|-------------|--------------|----------------|-------|
| warmup | 13 | 5 | 1 | 0 | 19 |
| hot | 8 | 11 | 0 | 0 | 19 |
| cooldown | 0 | 14 | 3 | 2 | 19 |
| ice | 0 | 0 | 0 | 19 | 19 |
| **OVERALL** | **21** | **30** | **4** | **21** | **76** |

Euphoria: 0 candidates (no OOS data meeting minimum thresholds).

### QUALIFIED — By Regime

**Warmup (13):**
| Pattern | N | Dates | Mean | WR | DC CI |
|---------|---|-------|------|-----|-------|
| gap_proof | 22,278 | 66 | +0.51% | 57.1% | [+0.06, +0.92] |
| t1_swing | 15,896 | 66 | +0.58% | 56.1% | [+0.13, +0.98] |
| old_duck | 12,223 | 66 | +0.75% | 54.2% | [+0.22, +1.30] |
| breakout | 10,423 | 66 | +0.77% | 54.6% | [+0.25, +1.29] |
| three_horse | 4,543 | 66 | +0.64% | 52.4% | [+0.09, +1.16] |
| lu_sniper | 2,323 | 66 | +0.62% | 59.2% | [+0.00, +1.23] |
| lotus | 1,632 | 66 | +1.01% | 57.3% | [+0.28, +1.69] |
| massive_vol | 1,404 | 66 | +0.72% | 52.9% | [+0.13, +1.28] |
| fake_yin | 1,364 | 66 | +0.68% | 53.5% | [+0.12, +1.21] |
| single_yang | 1,299 | 65 | +1.34% | 56.4% | [+0.59, +2.10] |
| ma5_monster | 1,112 | 66 | +0.85% | 51.5% | [+0.28, +1.41] |
| momentum | 1,054 | 66 | +0.66% | 56.4% | [+0.02, +1.27] |
| trend | 135 | 47 | +1.20% | 54.8% | [+0.35, +2.12] |

**Hot (8):**
| Pattern | N | Dates | Mean | WR | DC CI |
|---------|---|-------|------|-----|-------|
| old_duck | 10,023 | 37 | +0.73% | 51.6% | [+0.16, +1.24] |
| breakout | 9,234 | 37 | +0.68% | 51.6% | [+0.08, +1.23] |
| three_horse | 4,225 | 37 | +0.71% | 51.3% | [+0.16, +1.26] |
| lotus | 1,252 | 37 | +0.83% | 53.6% | [+0.15, +1.41] |
| single_yang | 1,141 | 37 | +1.38% | 59.6% | [+0.59, +2.16] |
| lu_sniper | 1,054 | 37 | +1.35% | 62.6% | [+0.62, +1.98] |
| ignition | 839 | 37 | +1.26% | 60.3% | [+0.39, +2.10] |
| long_yang_seven | 515 | 37 | +1.27% | 57.9% | [+0.42, +2.03] |

---

## 7. Date-Cluster Uncertainty

The date-cluster bootstrap is the primary uncertainty measure. Key findings:

- **Cooldown (0 QUALIFIED)**: Only 16 OOS dates. All 14 PROVISIONAL patterns have date-cluster CIs crossing zero despite positive mean returns. Example: breakout/cooldown mean=+0.77% but dc_ci=[-0.19, +1.74].
- **Hot (8 QUALIFIED)**: Aggregate CI crosses zero [-0.091, +0.985] but individual pattern CIs are positive. This suggests within-regime pattern differentiation is meaningful even though aggregate regime evidence is uncertain.
- **Warmup (13 QUALIFIED)**: 66 OOS dates provide sufficient clustering resolution. Mean CIs are narrower than hot/cooldown.

Qualification inherently favors regimes with more OOS dates — this is intentional, as date-cluster bootstrap reliability scales with number of unique dates.

---

## 8. Pattern Identity

Profile+pattern identity is preserved from event-level data. Key mappings:

| Profile | Patterns |
|---------|----------|
| momentum_v5 | breakout, ignition, momentum, trend |
| limitup_pullback | lu_sniper |
| gap_proof, gap_proof_v2 | gap_proof |
| lotus | lotus |
| old_duck | old_duck |
| single_yang | single_yang |
| three_horse | three_horse |
| t1_swing | t1_swing |
| ma5_monster | ma5_monster |
| fake_yin | fake_yin |
| long_yang_seven | long_yang_seven |
| golden_cross | golden_cross |
| massive_volume | massive_vol |
| divine_explorer | divine_explorer |
| fairy_guide | fairy_guide |
| island_reversal | island_rev |

Pattern taxonomy is NOT redefined in Phase 2C. It is derived directly from the profiles/patterns columns in event_level_trades.csv.

---

## 9. Multi-Pattern Events

65.1% of events are multi-pattern. Phase 2C uses the event as the unit of analysis — each event is counted once per pattern presence check, not once per pattern. Multi-pattern event outcomes use `return_median` (Phase 2B's primary metric), which is an aggregation construct, not an independent counterfactual ground truth.

The candidate table reports `single_n` and `multi_n` for each candidate, showing the composition of present-group events.

---

## 10. Present vs Absent Confounding

As identified in the Phase 2B.1 audit, present vs absent groups differ in pattern_count composition. Present groups tend to have more multi-pattern events. Phase 2C candidates are based on **present-group absolute performance** (not incremental), which avoids the compositional confound in the incremental metric. However, present-group performance may still be influenced by the pattern_count distribution — patterns that fire more frequently in multi-pattern contexts inherit the characteristics of those contexts.

---

## 11. Solo vs Concurrent

Not explicitly re-analyzed in Phase 2C (deferred to Phase 2B.1 solo/concurrent CSV). The Phase 2B.1 audit finding stands: solo does not universally outperform concurrent at the individual pattern level. Candidate qualification does not distinguish solo from concurrent events.

---

## 12. Train / Validation / OOS Stability

| Status | Count | Description |
|--------|-------|-------------|
| HISTORICALLY_CONSISTENT | 61 | Train>0, Val>0, OOS>0 |
| HISTORICALLY_INCONSISTENT | 14 | Sign mismatch between train/val and OOS |
| PARTIAL_HISTORY | 1 | Only one of train/val available |

The high proportion of HISTORICALLY_CONSISTENT (80%) suggests the patterns that work in OOS also worked in train+val — but this is observational, not causal. Train and validation data are from the same market regime classification system.

---

## 13. Hot Regime

**Aggregate date-cluster CI: [-0.091, +0.985]** — crosses zero.

Despite the aggregate uncertainty, 8 individual patterns achieve QUALIFIED status in hot regime with positive date-cluster CIs. This indicates that **within-regime pattern differentiation is meaningful** even when the regime-level aggregate is uncertain. The hot regime has 37 OOS dates — sufficient for pattern-level inference but insufficient for regime-level aggregate certainty.

---

## 14. Ice Regime

**5 OOS dates, 19 patterns, all LOW_DATE_COUNT.**

Ice regime has the highest mean returns (many >+1.0%) but only 5 unique trading dates. Date-cluster bootstrap on 5 dates is unreliable — the CI width is dominated by which specific 5 dates are sampled. No ice pattern can be qualified regardless of its mean return. This is a hard constraint from the date-cluster methodology, not a judgment about the patterns.

---

## 15. Baseline / Excess Return

Excess return is computed from `baseline_excess_mean` in event_level_trades.csv (Phase 2B). This is the difference between the event's return_median and the same-date sampled baseline return. The baseline is a **descriptive comparison**, not a strict matched counterfactual. Phase 2C reports it as `excess_return` in the candidate table — interpret as observational, not causal alpha.

---

## 16. PIT / Survivorship Status

- **PIT**: Phase 2C reads event_level_trades.csv (Phase 2B), which reads pattern_overlap_summary.csv (Phase 2A.1), which reads pattern_all_trades.csv (Phase 2A). The Phase 2A analysis used `backtest.py` with PIT-safe data provider. However, the exact PIT properties of the full pipeline have not been re-verified in Phase 2C.
- **Survivorship**: The stock universe (~2,500 stocks) contains only stocks that survived to the present. Survivorship bias remains unresolved at the data source level.

---

## 17. Costs / Slippage

Returns are **gross**. Transaction costs, stamp duty (0.1%), commission (~0.025%), and slippage are NOT included. This applies uniformly to all candidates and does not differentially affect qualification.

---

## 18. Statistical Limitations

1. **Date-cluster bootstrap requires sufficient unique dates**: Cooldown (16 dates) and ice (5 dates) have insufficient date samples for reliable clustering inference.

2. **Present-group performance ≠ causal effect**: Pattern presence is correlated with event complexity (pattern_count). Qualified candidates may benefit from the types of events they appear in, not just the pattern itself.

3. **6-month OOS is minimal**: 124 dates, of which only 37 are hot and 16 are cooldown. Regime-specific inference degrades with fewer dates.

4. **Multi-outcome aggregation**: return_median is an aggregation of potentially different profile outcomes. The median masks within-event dispersion.

5. **No sector/industry controls**: All analysis is market-wide. Sector concentration could confound results.

6. **Gross returns**: No transaction costs included.

---

## 19. Candidate Table

Full table: `results/phase2c_candidate_table.csv` (76 rows).

Columns: regime, profile_name, pattern_name, oos_events, oos_dates, mean_return, median_return, win_rate, event_bootstrap_mean_ci_low, event_bootstrap_mean_ci_high, date_cluster_mean_ci_low, date_cluster_mean_ci_high, date_cluster_win_rate_ci_low, date_cluster_win_rate_ci_high, excess_return, evidence_grade, candidate_status, reason, present_n, absent_n, single_n, multi_n.

---

## 20. What We Can Conclude

- 21 (regime, pattern) combinations have QUALIFIED OOS evidence under date-cluster inference
- All QUALIFIED candidates are in warmup (13) and hot (8) — regimes with sufficient OOS dates
- Warmup has the most robust evidence (66 dates, narrowest date-cluster CIs)
- Hot regime has positive individual pattern CIs despite aggregate uncertainty
- Cooldown and ice cannot be evaluated reliably with current OOS date counts
- 80% of patterns are HISTORICALLY_CONSISTENT across train/val/OOS

---

## 21. What We Cannot Conclude

- We cannot say any pattern is "the best"
- We cannot say any regime "should" use specific patterns
- We cannot say pattern X causes higher returns
- We cannot say any pattern is ready for live trading
- We cannot say any pattern should be enabled
- We cannot say any pattern has alpha
- Ice regime results are exploratory only (LOW_DATE_COUNT)
- Cooldown results lack date-cluster confirmation

---

## 22. Phase 2D Readiness

**READY WITH CONDITIONS.**

Phase 2C has identified 21 QUALIFIED candidates with date-cluster-confirmed OOS evidence. These candidates should proceed to Phase 2D (Independent Re-validation) where they are tested on a new, non-overlapping time window with frozen qualification rules, patterns, regimes, and sell rules.

Conditions for Phase 2D:
1. Freeze all 21 QUALIFIED candidates as the validation set
2. Extend OOS window as new data becomes available
3. Re-run date-cluster bootstrap with additional dates
4. Do not add new candidates based on Phase 2C results alone
5. Do not construct a router or position allocator until Phase 2D confirms results

---

## 23. Files

| File | Rows/Lines | Description |
|------|-----------|-------------|
| `scripts/phase2c_validate.py` | ~380 | Main Phase 2C engine |
| `tests/test_phase2c.py` | ~315 | 27 test cases |
| `results/phase2c_candidate_table.csv` | 76 | Regime × Pattern candidates |
| `results/phase2c_candidate_summary.csv` | 5 | Summary by regime |
| `results/phase2c_regime_pattern_matrix.csv` | 76 | Train/Val/OOS stability matrix |
| `docs/reverse_engineering/PHASE_2C_REPORT.md` | — | This report |

**No existing files modified.**

---

## 24. CI Status

```
tests/test_phase2c.py — 27 passed, 0 failed
Full regression       — 427 passed, 0 failed
```
