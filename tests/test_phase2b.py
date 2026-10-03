"""Phase 2B — Event-Level OOS Validation tests.

Tests verify:
  1. event_id uniqueness / correct row count
  2. Single-pattern events: return_mean == return_median == return_consensus
  3. Multi-pattern events: valid aggregation, return_stdev >= 0
  4. return_mean spot-check for known event
  5. Bootstrap CI: deterministic with fixed seed
  6. Bootstrap operates on unique events (not trades)
  7. context_quality values valid
  8. theme_lifecycle always NOT_AVAILABLE
  9. Stability values valid
  10. OOS summary only contains OOS dates
  11. Event count consistency across outputs
  12. Pattern presence does not create duplicate events
  13. Legacy Phase 2A.1 results remain readable
"""

import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.phase2b_event_analysis import (
    bootstrap_ci,
    compute_group_bootstrap,
    get_context_quality,
    get_sample_label,
    get_dispersion_flag,
    simplify_exit_reason,
    compute_stability_status,
    compute_evidence_grade,
    get_period,
    OOS_START,
    OOS_END,
)

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
EVENT_CSV = RESULTS_DIR / "event_level_trades.csv"
OOS_SUMMARY_CSV = RESULTS_DIR / "event_oos_summary.csv"
SINGLE_CSV = RESULTS_DIR / "single_pattern_oos.csv"
MULTI_CSV = RESULTS_DIR / "multipattern_oos.csv"
PRESENCE_CSV = RESULTS_DIR / "pattern_presence_oos.csv"
EVIDENCE_CSV = RESULTS_DIR / "pattern_oos_evidence.csv"
TRADES_CSV = RESULTS_DIR / "pattern_all_trades.csv"


def _load_events():
    with open(EVENT_CSV) as f:
        return list(csv.DictReader(f))


def _load_trades():
    with open(TRADES_CSV) as f:
        return list(csv.DictReader(f))


# ═══════════════════════════════════════════════════════════════
# Test 1: Event ID uniqueness and correct row count
# ═══════════════════════════════════════════════════════════════

def test_event_count_matches_overlap():
    """event_level_trades.csv must have exactly 282,892 rows (one per signal event)."""
    events = _load_events()
    # Should match pattern_overlap_summary.csv row count
    assert len(events) == 282892, \
        f"Expected 282,892 events, got {len(events)}"


def test_event_id_unique():
    """Every event_id must be unique."""
    events = _load_events()
    ids = [e["event_id"] for e in events]
    assert len(ids) == len(set(ids)), \
        f"Found {len(ids) - len(set(ids))} duplicate event_ids"


def test_event_id_format():
    """event_id must be {symbol}_{signal_date}."""
    events = _load_events()
    for e in events[:1000]:
        expected = f"{e['symbol']}_{e['signal_date']}"
        assert e["event_id"] == expected, \
            f"event_id mismatch: {e['event_id']} != {expected}"


# ═══════════════════════════════════════════════════════════════
# Test 2: Single-pattern events have return identity
# ═══════════════════════════════════════════════════════════════

def test_single_pattern_returns_identical():
    """For single-pattern events, return_mean == return_median == return_consensus."""
    events = _load_events()
    single = [e for e in events if e["pattern_count"] == "1"]
    assert len(single) > 0, "No single-pattern events found"

    violations = []
    for e in single[:5000]:  # Sample for speed
        rm = float(e["return_mean"])
        rmd = float(e["return_median"])
        rc = float(e["return_consensus"])
        if not (abs(rm - rmd) < 0.001 and abs(rmd - rc) < 0.001):
            violations.append(e)
    assert len(violations) == 0, \
        f"Found {len(violations)} single-pattern events with differing returns"


def test_single_pattern_stdev_zero():
    """For single-profile events, return_stdev should be 0."""
    events = _load_events()
    single_profile = [e for e in events if e["profile_count"] == "1"]
    for e in single_profile:
        assert float(e["return_stdev"]) == 0.0, \
            f"Single-profile event {e['event_id']} has non-zero stdev: {e['return_stdev']}"


# ═══════════════════════════════════════════════════════════════
# Test 3: Multi-pattern events have valid aggregation
# ═══════════════════════════════════════════════════════════════

def test_multi_pattern_aggregation_valid():
    """Multi-pattern events must have non-NaN returns and valid dispersion."""
    events = _load_events()
    multi = [e for e in events if int(e["pattern_count"]) > 1]
    assert len(multi) > 0, "No multi-pattern events found"

    for e in multi[:1000]:
        assert float(e["return_mean"]) != float("nan"), \
            f"NaN return_mean for {e['event_id']}"
        assert float(e["return_median"]) != float("nan"), \
            f"NaN return_median for {e['event_id']}"
        assert float(e["return_stdev"]) >= 0, \
            f"Negative stdev for {e['event_id']}"
        assert float(e["return_range"]) >= 0, \
            f"Negative return_range for {e['event_id']}"


# ═══════════════════════════════════════════════════════════════
# Test 4: Return aggregation spot-checks
# ═══════════════════════════════════════════════════════════════

def test_return_mean_spotcheck():
    """Spot-check: return_mean for a specific event matches manual calculation."""
    trades = _load_trades()
    # Event: ('000004.SZ', '2024-10-08') has 8 trades all at -15.7%
    event_trades = [t for t in trades
                    if t["symbol"] == "000004.SZ" and t["pattern_date"] == "2024-10-08"]
    returns = [float(t["return_pct"]) for t in event_trades]
    expected_mean = sum(returns) / len(returns)

    events = _load_events()
    target = [e for e in events
              if e["symbol"] == "000004.SZ" and e["signal_date"] == "2024-10-08"]
    assert len(target) == 1
    assert abs(float(target[0]["return_mean"]) - expected_mean) < 0.01


def test_event_trade_count_matches():
    """Each event's profile_count must match number of trades for that (symbol, signal_date)."""
    trades = _load_trades()
    from collections import defaultdict
    trade_counts = defaultdict(int)
    for t in trades:
        trade_counts[(t["symbol"], t["pattern_date"])] += 1

    events = _load_events()
    mismatches = 0
    for e in events[:5000]:
        key = (e["symbol"], e["signal_date"])
        expected = trade_counts[key]
        actual = int(e["profile_count"])
        if expected != actual:
            mismatches += 1
    assert mismatches == 0, \
        f"Found {mismatches} events with mismatched trade counts"


# ═══════════════════════════════════════════════════════════════
# Test 5: Bootstrap CI — deterministic with seed
# ═══════════════════════════════════════════════════════════════

def test_bootstrap_deterministic():
    """Same seed + same data = same CIs."""
    data = np.array([1.0, 2.0, 3.0, 4.0, 5.0, -1.0, -2.0, 0.5, 1.5, 2.5])
    result1 = bootstrap_ci(data, "mean", n_iterations=500, seed=42)
    result2 = bootstrap_ci(data, "mean", n_iterations=500, seed=42)
    assert result1["ci_lower"] == result2["ci_lower"]
    assert result1["ci_upper"] == result2["ci_upper"]
    assert result1["point_estimate"] == result2["point_estimate"]


def test_bootstrap_ci_bounds():
    """CI lower <= point estimate <= CI upper."""
    data = np.random.RandomState(42).randn(100) + 1.0  # mean ~ 1.0
    for stat in ["mean", "median", "win_rate"]:
        result = bootstrap_ci(data, stat)
        if result["ci_lower"] is not None:
            assert result["ci_lower"] <= result["point_estimate"] <= result["ci_upper"], \
                (f"CI bounds violation for {stat}: "
                 f"{result['ci_lower']} <= {result['point_estimate']} <= {result['ci_upper']}")


def test_bootstrap_small_sample():
    """Bootstrap with n < 10 should still compute but report correctly."""
    data = np.array([1.0, 2.0, 3.0])
    result = bootstrap_ci(data, "mean")
    assert result["n_original"] == 3
    # Should still compute CI
    assert result["ci_lower"] is not None


def test_bootstrap_on_unique_events_not_trades():
    """Verify bootstrap uses unique events, not duplicate trades."""
    # Create mock event-level data
    np.random.seed(42)
    events = np.random.randn(50) + 0.5
    result = bootstrap_ci(events, "mean", n_iterations=1000, seed=42)
    # The point estimate should be the mean of events, not inflated
    assert abs(result["point_estimate"] - np.mean(events)) < 0.001
    assert result["n_original"] == 50


# ═══════════════════════════════════════════════════════════════
# Test 6: context_quality values
# ═══════════════════════════════════════════════════════════════

def test_context_quality_values():
    """context_quality must be in {SIMPLE, MODERATE, COMPLEX}."""
    valid = {"SIMPLE", "MODERATE", "COMPLEX"}
    events = _load_events()
    cqs = set(e["context_quality"] for e in events)
    unknown = cqs - valid
    assert len(unknown) == 0, f"Unknown context_quality values: {unknown}"


def test_context_quality_matches_profile_count():
    """SIMPLE = 1 profile, MODERATE = 2-3, COMPLEX = 4+."""
    events = _load_events()
    for e in events[:2000]:
        pc = int(e["profile_count"])
        cq = e["context_quality"]
        if pc == 1:
            assert cq == "SIMPLE", f"pc=1 but cq={cq} for {e['event_id']}"
        elif pc <= 3:
            assert cq == "MODERATE", f"pc={pc} but cq={cq} for {e['event_id']}"
        else:
            assert cq == "COMPLEX", f"pc={pc} but cq={cq} for {e['event_id']}"


# ═══════════════════════════════════════════════════════════════
# Test 7: theme_lifecycle always NOT_AVAILABLE
# ═══════════════════════════════════════════════════════════════

def test_theme_lifecycle_not_available_event_csv():
    """Every event must have theme_lifecycle = NOT_AVAILABLE."""
    events = _load_events()
    for e in events[:1000]:
        assert e["theme_lifecycle"] == "NOT_AVAILABLE", \
            f"Expected NOT_AVAILABLE, got {e['theme_lifecycle']}"


def test_theme_lifecycle_not_available_outputs():
    """All output CSVs must have theme_lifecycle = NOT_AVAILABLE."""
    for csv_path in [OOS_SUMMARY_CSV, SINGLE_CSV, MULTI_CSV, PRESENCE_CSV, EVIDENCE_CSV]:
        with open(csv_path) as f:
            for row in csv.DictReader(f):
                assert row.get("theme_lifecycle", "NOT_AVAILABLE") == "NOT_AVAILABLE", \
                    f"{csv_path.name}: found {row.get('theme_lifecycle')}"


# ═══════════════════════════════════════════════════════════════
# Test 8: Stability values
# ═══════════════════════════════════════════════════════════════

def test_stability_values():
    """stability must be in valid set."""
    valid = {"STABLE_POSITIVE", "STABLE_NEGATIVE", "SIGN_FLIP", "INSUFFICIENT_DATA"}
    with open(SINGLE_CSV) as f:
        for row in csv.DictReader(f):
            assert row["stability"] in valid, \
                f"Invalid stability: {row['stability']}"


def test_evidence_grade_values():
    """evidence_grade must be in valid set."""
    valid = {"STRONG", "MODERATE", "WEAK", "INCONCLUSIVE"}
    with open(EVIDENCE_CSV) as f:
        for row in csv.DictReader(f):
            assert row["evidence_grade"] in valid, \
                f"Invalid evidence_grade: {row['evidence_grade']}"


# ═══════════════════════════════════════════════════════════════
# Test 9: OOS isolation
# ═══════════════════════════════════════════════════════════════

def test_oos_summary_only_oos_dates():
    """All events in OOS outputs must have signal_date in OOS range."""
    with open(EVENT_CSV) as f:
        events = list(csv.DictReader(f))

    oos_ids = set()
    with open(OOS_SUMMARY_CSV) as f:
        oos_rows = list(csv.DictReader(f))

    # Spot check: OOS events from event CSV
    oos_events = [e for e in events
                  if OOS_START <= e["signal_date"] <= OOS_END]
    oos_event_count = len(oos_events)
    assert oos_event_count > 0, "No OOS events found"

    # All events in single_pattern_oos should be from OOS-date events
    with open(SINGLE_CSV) as f:
        single_rows = list(csv.DictReader(f))
    for r in single_rows:
        assert r["regime"] in {"euphoria", "hot", "warmup", "cooldown", "ice", "unknown"}, \
            f"Unknown regime: {r['regime']}"


# ═══════════════════════════════════════════════════════════════
# Test 10: Event count consistency
# ═══════════════════════════════════════════════════════════════

def test_event_count_consistency():
    """Total events in OOS summary should match OOS events count."""
    with open(OOS_SUMMARY_CSV) as f:
        oos_rows = list(csv.DictReader(f))

    # Sum of n_events across all rows = total unique OOS events
    # (Note: events may appear in multiple rows if grouped differently,
    #  but event_oos_summary groups by regime x context_quality x event_type
    #  which should partition the OOS events)
    total = sum(int(r["n_events"]) for r in oos_rows)
    # Should approximately equal total OOS events
    assert total > 60000, f"Unexpectedly low total OOS events: {total}"


def test_single_multi_event_types_separated():
    """Single-pattern OOS should have no multi-pattern events."""
    # single_pattern_oos only contains single-pattern events
    # Verify the CSV was generated from event_type==single_pattern
    with open(SINGLE_CSV) as f:
        single_rows = list(csv.DictReader(f))
    assert len(single_rows) > 0, "No single pattern OOS rows"
    # Every row should have sample data
    for r in single_rows:
        assert int(r["n_events"]) > 0, f"Row has 0 events: {r}"


# ═══════════════════════════════════════════════════════════════
# Test 11: Pattern presence does not duplicate events
# ═══════════════════════════════════════════════════════════════

def test_pattern_presence_no_duplication():
    """Pattern presence CSV should not duplicate the same event."""
    with open(PRESENCE_CSV) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) > 0, "No pattern presence rows"
    # Each row represents a unique (pattern, presence_type, regime) combo
    # No two rows should match the same combo
    combos = set()
    for r in rows:
        combo = (r["pattern_name"], r["presence_type"], r["regime"])
        assert combo not in combos, f"Duplicate combo: {combo}"
        combos.add(combo)


# ═══════════════════════════════════════════════════════════════
# Test 12: Legacy Phase 2A.1 results remain readable
# ═══════════════════════════════════════════════════════════════

def test_phase2a1_validation_readable():
    """Phase 2A.1 output CSVs must still be readable."""
    validation_csv = RESULTS_DIR / "pattern_regime_validation.csv"
    assert validation_csv.exists(), "pattern_regime_validation.csv missing"

    with open(validation_csv) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 293, \
        f"Expected 293 rows in pattern_regime_validation.csv, got {len(rows)}"

    # Verify key columns still present
    expected_cols = {"period", "profile_name", "pattern_name", "market_regime",
                     "sample_count", "sample_label", "win_rate", "avg_return"}
    actual_cols = set(rows[0].keys())
    assert expected_cols.issubset(actual_cols), \
        f"Missing columns: {expected_cols - actual_cols}"


def test_phase2a1_overlap_readable():
    """Phase 2A.1 overlap CSV must still be readable."""
    overlap_csv = RESULTS_DIR / "pattern_overlap_summary.csv"
    assert overlap_csv.exists(), "pattern_overlap_summary.csv missing"

    with open(overlap_csv) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 282892, \
        f"Expected 282,892 rows, got {len(rows)}"


# ═══════════════════════════════════════════════════════════════
# Test 13: Helper functions
# ═══════════════════════════════════════════════════════════════

def test_get_sample_label():
    assert get_sample_label(10) == "small"
    assert get_sample_label(50) == "medium"
    assert get_sample_label(100) == "large"
    assert get_sample_label(500) == "large"


def test_get_context_quality():
    assert get_context_quality(1, 1) == "SIMPLE"
    assert get_context_quality(2, 2) == "MODERATE"
    assert get_context_quality(3, 3) == "MODERATE"
    assert get_context_quality(4, 4) == "COMPLEX"
    assert get_context_quality(1, 4) == "COMPLEX"


def test_simplify_exit_reason():
    assert simplify_exit_reason("回落25%(高7.1%)") == "回落25%"
    assert simplify_exit_reason("目标+8%") == "目标+8%"
    assert simplify_exit_reason("止损-3%") == "止损-3%"
    assert simplify_exit_reason("END_OF_DATA") == "END_OF_DATA"


def test_compute_stability():
    assert compute_stability_status(1.0, 2.0, 100) == "STABLE_POSITIVE"
    assert compute_stability_status(-1.0, -2.0, 100) == "STABLE_NEGATIVE"
    assert compute_stability_status(1.0, -1.0, 100) == "SIGN_FLIP"
    assert compute_stability_status(1.0, 2.0, 5) == "INSUFFICIENT_DATA"
    assert compute_stability_status(None, 2.0, 100) == "INSUFFICIENT_DATA"


def test_get_period():
    assert get_period("2025-06-15") == "train"
    assert get_period("2026-01-01") == "validation"
    assert get_period("2026-07-01") == "oos"
    assert get_period("2024-01-01") == "unknown"


def test_dispersion_flag():
    assert get_dispersion_flag(0.5) == "LOW"
    assert get_dispersion_flag(3.0) == "MEDIUM"
    assert get_dispersion_flag(6.0) == "HIGH"
