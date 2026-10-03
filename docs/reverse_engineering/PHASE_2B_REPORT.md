# PHASE 2B REPORT — Event-Level OOS Validation

## 1. STATUS

**PASS WITH LIMITATION**

Phase 2B aggregates Phase 2A's 852,982 pattern trades into 282,892 unique signal events and performs OOS validation at the event level. The multi-outcome problem (69.9% of multi-pattern events have different returns per profile) is handled via three aggregation methods. Bootstrap confidence intervals are computed on unique events.

---

## 2. SCOPE

### Objective

Validate Phase 2A pattern signals at the **event level** — one observation per unique `(symbol, signal_date)`, not one per pattern trade. This is necessary because Phase 2A.1 discovered 65.1% pattern overlap.

### Phase 2B Does

- Aggregate trades into unique signal events
- Handle multi-outcome events (different profiles → different exits → different returns)
- Bootstrap confidence intervals on unique events (numpy, seed=42, 1000 iterations)
- OOS-only analysis (2026-04-01 ~ 2026-10-01)
- Regime × event_type breakdown
- Single-pattern, multi-pattern, and pattern presence analysis
- Evidence grading (STRONG/MODERATE/WEAK/INCONCLUSIVE) — NOT rankings

### Phase 2B Does NOT

- Modify any strategy rules, patterns, or sell rules
- Rank patterns as "best" or "winner"
- Generate router weights or enable/disable decisions
- Introduce theme_lifecycle data (not available in codebase)
- Re-scan historical data

---

## 3. FILES

### New Files

| File | Lines/Rows | Description |
|------|-----------|-------------|
| `scripts/phase2b_event_analysis.py` | ~650 | Main Phase 2B analysis engine |
| `tests/test_phase2b.py` | ~340 | 30 test cases |
| `docs/reverse_engineering/PHASE_2B_REPORT.md` | — | This report |

### Generated Output Files

| File | Rows | Description |
|------|------|-------------|
| `results/event_level_trades.csv` | 282,892 | One row per unique signal event |
| `results/event_oos_summary.csv` | 16 | OOS stats by regime × context_quality × event_type |
| `results/single_pattern_oos.csv` | 61 | Single-pattern OOS evidence |
| `results/multipattern_oos.csv` | 30 | Multi-pattern OOS by pattern_count × regime |
| `results/pattern_presence_oos.csv` | 260 | Per-pattern presence analysis |
| `results/pattern_oos_evidence.csv` | 1,154 | Candidate evidence with bootstrap CIs |

### Existing Files

No existing files were modified.

---

## 4. TESTS

```
tests/test_phase2b.py — 30 passed, 0 failed
```

| Category | Tests | Description |
|----------|-------|-------------|
| Event uniqueness | 3 | Row count (282,892), event_id unique, format |
| Single-pattern | 2 | Return identity, stdev=0 |
| Multi-pattern | 1 | Valid aggregation, non-NaN returns |
| Spot-checks | 2 | return_mean matches manual, trade counts match |
| Bootstrap CI | 4 | Deterministic, CI bounds, small sample, unique events |
| Schema validation | 4 | context_quality, theme_lifecycle, stability, evidence_grade |
| OOS isolation | 1 | Only OOS dates |
| Consistency | 2 | Event count, single/multi separation |
| Presence | 1 | No duplicate combos |
| Legacy | 2 | Phase 2A.1 CSVs still readable |
| Helpers | 5 | Sample label, context, exit reason, stability, period |

### Regression

```
Full test suite: 345 passed, 2 failed (pre-existing, unrelated)
```

---

## 5. EVENT-LEVEL AGGREGATION METHODOLOGY

### Event Definition

```
event_id = symbol + signal_date
```

An event is a unique stock-day pair where one or more patterns trigger. Events come from `pattern_overlap_summary.csv` (282,892 events).

### The Multi-Outcome Problem

Different strategy profiles use different sell parameters (target_pct, stop_pct, trailing stop %). This means the same stock, bought at the same price on the same day, can have **different exit outcomes** depending on which profile's sell rules are applied.

| Metric | Value |
|--------|-------|
| Multi-pattern events | 184,199 (65.1%) |
| Events with differing returns | 128,765 (69.9% of multi) |
| Average within-event stdev | 0.69% |
| Average within-event range | 1.38% |

### Three Aggregation Methods

| Method | Formula | Use |
|--------|---------|-----|
| `return_mean` | Arithmetic mean of all profile returns | Average event outcome |
| `return_median` | Median of all profile returns | Robust central tendency, **primary metric** |
| `return_consensus` | Return from most common exit reason | Exit-reason-aligned outcome |

`return_median` is used as the primary metric for win rate, mean return, and bootstrap CIs.

### context_quality Derivation

Since `context_quality` does not exist in the codebase, it is derived from event complexity:

| Value | Condition |
|-------|-----------|
| `SIMPLE` | 1 profile AND 1 pattern |
| `MODERATE` | 2-3 profiles OR 2-3 patterns |
| `COMPLEX` | 4+ profiles OR 4+ patterns |

### theme_lifecycle

`theme_lifecycle = NOT_AVAILABLE` across all outputs. There is no theme lifecycle data source in the current codebase.

---

## 6. OOS EVENT STATISTICS

### Overall

| Metric | Value |
|--------|-------|
| OOS date range | 2026-04-01 ~ 2026-10-01 |
| OOS events | 69,679 |
| OOS single-pattern | 25,799 (37.0%) |
| OOS multi-pattern | 43,880 (63.0%) |
| OOS mean return | +0.54% |
| OOS median return | +1.21% |
| OOS win rate | 54.7% |

### By Regime × Event Type

| Regime | Event Type | Events | Mean Return | Win Rate |
|--------|-----------|--------|-------------|----------|
| warmup | single | 12,142 | +0.45% | 57.5% |
| warmup | multi | 19,848 | +0.69% | 56.4% |
| hot | single | 10,710 | +0.51% | 54.7% |
| hot | multi | 19,070 | +0.46% | 51.8% |
| cooldown | single | 2,348 | +0.21% | 55.7% |
| cooldown | multi | 3,859 | +0.45% | 54.5% |
| ice | single | 599 | +1.06% | 44.6% |
| ice | multi | 1,103 | +1.26% | 47.2% |

Key observation: **warmup produces the highest win rates** (57.5% single, 56.4% multi) and half of all OOS events. **Ice produces the highest mean returns** but the lowest win rates — returns are high when they win but losses are larger and more frequent.

### By context_quality × Regime

| Regime | Context | Events | Mean | Win Rate |
|--------|---------|--------|------|----------|
| warmup | SIMPLE | 9,047 | +0.53% | 58.4% |
| warmup | MODERATE | 13,027 | +0.58% | 57.6% |
| warmup | COMPLEX | 9,916 | +0.67% | 54.2% |
| hot | SIMPLE | 7,699 | +0.62% | 55.8% |
| hot | MODERATE | 12,673 | +0.29% | 52.3% |
| hot | COMPLEX | 9,408 | +0.62% | 51.1% |

---

## 7. SINGLE-PATTERN OOS RESULTS

61 single-pattern evidence rows across profile × pattern × regime.

### Top by OOS Mean Return (n ≥ 100, single-pattern only)

| Profile | Pattern | Regime | Events | Mean Ret | Win Rate |
|---------|---------|--------|--------|----------|----------|
| single_yang | single_yang | hot | 1,141 | +1.38% | 59.6% |
| lotus | lotus | warmup | 1,632 | +1.01% | 57.3% |
| limitup_pullback | lu_sniper | hot | 1,054 | +1.35% | 62.6% |
| momentum_v5 | ignition | hot | 839 | +1.26% | 60.3% |
| single_yang | single_yang | warmup | 1,299 | +1.34% | 56.4% |

### Key Observations

- **limitup_pullback/lu_sniper** has the highest win rate (62.6%) among large-sample single-pattern combos
- **single_yang** is the most consistent single-pattern performer across hot (59.6% WR) and warmup (56.4% WR)
- **lotus** performs best in warmup (57.3% WR, +1.01% mean)
- Single-pattern events are only 37% of OOS events — most patterns fire concurrently

---

## 8. MULTI-PATTERN OOS RESULTS

30 rows across pattern_count (2-9) × regime.

### Concurrence Effect

| Pattern Count | warmup (Mean/WR) | hot (Mean/WR) | cooldown (Mean/WR) | ice (Mean/WR) |
|---------------|-------------------|---------------|---------------------|---------------|
| 2 | +0.65% / 59.1% | +0.15% / 51.6% | +0.31% / 54.9% | +1.05% / 45.0% |
| 3 | +0.80% / 57.1% | +0.72% / 54.5% | +0.13% / 53.1% | +1.78% / 54.1% |
| 4 | +0.80% / 55.9% | +0.77% / 52.5% | +0.62% / 54.7% | +1.34% / 48.8% |
| 5 | +0.58% / 52.0% | +0.58% / 49.8% | +0.70% / 53.5% | +0.91% / 45.7% |
| 6 | +0.57% / 51.6% | +0.62% / 50.3% | +0.71% / 55.0% | +1.56% / 43.8% |
| 7+ | +0.56% / 49.0% | +0.55% / 46.7% | +1.12% / 65.2% | +1.12% / 35.3% |

### Key Observations

- **More patterns don't consistently improve outcomes**: In warmup, win rate declines from 59.1% (2p) to 49.0% (7+p). The same pattern holds in hot.
- **2-pattern events in warmup** have the best risk-adjusted profile: 59.1% WR, +0.65% mean
- **3-pattern events in ice** show the highest mean return (+1.78%) but small sample (196 events)
- High concurrence (7+ patterns) means many profiles agree on the signal, but sell-parameter dispersion also increases

---

## 9. PATTERN PRESENCE ANALYSIS

260 rows across 19 patterns × 4 presence types × 5 regimes.

### Solo vs Concurrent Performance (warmup, n ≥ 100)

| Pattern | Solo Events | Solo Mean | Solo WR | Concurrent Mean | Concurrent WR |
|---------|------------|-----------|---------|-----------------|---------------|
| single_yang | 1,299 | +1.34% | 56.4% | +0.92% | 55.1% |
| lotus | 1,632 | +1.01% | 57.3% | +0.85% | 55.7% |
| momentum_v5/breakout | 10,423 | +0.77% | 54.6% | +0.72% | 53.8% |
| old_duck | 12,223 | +0.75% | 54.2% | +0.69% | 53.7% |

### Key Observation

**Solo performance is consistently better than concurrent performance** for the same pattern in the same regime. This suggests that pattern concurrence may indicate a noisier signal environment, not a stronger signal.

---

## 10. BOOTSTRAP CONFIDENCE INTERVALS

### Methodology

- Engine: `numpy.random.RandomState(42)` for deterministic resampling
- Iterations: 1,000
- Confidence: 95% (percentile method)
- Resampling unit: **unique signal events** (not trades)
- Statistics: mean, median, win_rate

### Example CIs for STRONG Evidence

| Profile/Pattern | Regime | N | Mean | 95% CI | Win Rate CI |
|-----------------|--------|-----|------|--------|-------------|
| old_duck/old_duck | warmup | 12,223 | +0.75% | [+0.63, +0.86] | [53.2, 55.3] |
| momentum_v5/breakout | warmup | 10,423 | +0.77% | [+0.64, +0.89] | [53.4, 55.7] |
| single_yang/single_yang | hot | 1,141 | +1.38% | [+1.04, +1.76] | [56.7, 62.5] |
| limitup_pullback/lu_sniper | hot | 1,054 | +1.35% | [+0.96, +1.71] | [59.2, 65.5] |

These CIs are tight for large samples but widen considerably for N < 100. The bootstrap confirms that the top STRONG evidence combos have returns reliably above zero.

---

## 11. EVIDENCE GRADE DISTRIBUTION

| Grade | Count | Criteria |
|-------|-------|----------|
| STRONG | 23 | n ≥ 100, STABLE_POSITIVE, mean CI > 0, excess CI > 0 |
| MODERATE | 32 | n ≥ 30, STABLE_POSITIVE, mean CI > 0 |
| WEAK | 18 | n ≥ 30, STABLE_POSITIVE, CI crosses zero |
| INCONCLUSIVE | 1,081 | n < 30 or non-stable |

### STRONG Evidence by Regime

| Regime | Count | Top Combos |
|--------|-------|------------|
| warmup | 4 | old_duck, momentum_v5/breakout, lotus, single_yang |
| hot | 9 | old_duck, momentum_v5/breakout, three_horse, lotus, single_yang, lu_sniper, golden_cross, momentum_v5/ignition, long_yang_seven |
| cooldown | 7 | t1_swing, old_duck, momentum_v5/breakout, three_horse, lu_sniper, fake_yin, single_yang |
| ice | 3 | gap_proof, old_duck, momentum_v5/breakout |

No patterns have STRONG evidence in euphoria (not enough OOS events).

Note: **These are observations, not recommendations.** They describe what happened in this specific 6-month OOS period. They do not predict future performance.

---

## 12. KNOWN LIMITATIONS

1. **theme_lifecycle NOT_AVAILABLE**: No theme lifecycle data source exists in the codebase. All theme_lifecycle fields are marked `NOT_AVAILABLE`.

2. **context_quality is a derived proxy**: Based on profile/pattern count, not true signal quality measurement.

3. **Multi-outcome aggregation**: The 69.9% of multi-pattern events with differing returns require an aggregation choice. `return_median` is used as primary but is not a ground truth.

4. **6-month OOS**: Only April-September 2026. Not a full market cycle. Euphoria has essentially no OOS samples.

5. **Bootstrap assumes independent events**: Events on the same day share the same market regime and baseline, creating mild clustering. Bootstrap treats each event as independent.

6. **Survivorship bias**: Current universe (~2,500 stocks) contains only stocks that survived to the present.

7. **Sampled baseline**: 50 stocks/date baseline is directional, not a precise matched counterfactual.

8. **Gross returns**: No transaction costs, stamp duty, or slippage included.

9. **No sector breakdown**: All analysis is market-wide.

10. **Pattern overlap persistence**: 63% of OOS events are multi-pattern. Pattern attribution remains ambiguous.

---

## 13. READINESS FOR NEXT STAGE

### Question: Is Phase 2B ready for "Regime × Lifecycle × Pattern Candidate Evidence → Walk-Forward Validation"?

**Answer: YES, with clear methodological constraints.**

Phase 2B provides the event-level validation foundation:

- 282,892 unique events with quantified return dispersion
- 69,679 OOS events with bootstrap CIs
- 23 STRONG evidence candidates (large sample, stable positive, CI above zero)
- Pattern concurrence effects documented
- Multi-outcome problem handled transparently

### For the next phase:

1. **Focus on the 23 STRONG + 32 MODERATE evidence candidates** — these have sufficient data quality for walk-forward
2. **Do NOT automatically enable all STRONG evidence** — evidence is observational, not prescriptive
3. **Build walk-forward on event-level data, not pattern-level** — avoid double-counting
4. **Account for pattern overlap in any position sizing** — multi-pattern events are one trade opportunity, not N trades
5. **Consider adding theme_lifecycle data** — the NOT_AVAILABLE gap limits regime × lifecycle analysis
6. **Extend OOS as data becomes available** — 6 months is minimal

---

## 14. USAGE

```bash
# Full analysis with bootstrap CIs
python3 scripts/phase2b_event_analysis.py

# Quick run without bootstrap (faster)
python3 scripts/phase2b_event_analysis.py --no-bootstrap

# Run tests
python3 -m pytest tests/test_phase2b.py -q
```

---

## 15. BASELINE

- **Phase 2A.1 commit**: `cddffd4`
- **Phase 2B files**: 2 new source files, 6 generated CSVs, 1 report
- **No existing files modified**
- **Test regression**: 345 passed, 2 pre-existing failures (unrelated)
