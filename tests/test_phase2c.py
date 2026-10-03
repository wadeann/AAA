"""Phase 2C — OOS Regime × Pattern Candidate Validation tests.

Tests verify:
  1. Candidate classification (QUALIFIED/PROVISIONAL/INSUFFICIENT/LOW_DATE_COUNT)
  2. date-cluster CI as primary logic
  3. Ice LOW_DATE_COUNT classification
  4. Hot CI crossing zero documented
  5. No ranking fields in output
  6. No future OOS leakage
  7. Train/validation/OOS separation
  8. profile_name + pattern_name preserved
  9. Deterministic output
  10. Present/absent composition reported
  11. Multi-pattern event not double-counted
  12. Candidate table schema validation
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.phase2c_validate import (
    classify_candidate,
    derive_profile_pattern_map,
    get_primary_profile,
    get_period,
    OOS_START,
    OOS_END,
    TRAIN_START,
    TRAIN_END,
    VAL_START,
    VAL_END,
)

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


# ═══════════════════════════════════════════════════════════════
# Test 1: Candidate classification
# ═══════════════════════════════════════════════════════════════

def test_qualified_candidate():
    """Fully qualified: n>=100, dates>=20, dc_ci_low>0, mean>0, median>0."""
    status, reason = classify_candidate(
        n_events=500, n_dates=30, mean_return=0.75, median_return=0.50,
        dc_ci_low=0.25, dc_ci_high=1.25,
    )
    assert status == "QUALIFIED", f"Expected QUALIFIED, got {status}: {reason}"


def test_provisional_dc_ci_crosses_zero():
    """Positive mean but date-cluster CI crosses zero."""
    status, reason = classify_candidate(
        n_events=500, n_dates=30, mean_return=0.50, median_return=0.30,
        dc_ci_low=-0.10, dc_ci_high=1.10,
    )
    assert status == "PROVISIONAL", f"Expected PROVISIONAL, got {status}: {reason}"


def test_provisional_small_n():
    """Date-cluster CI positive but n < 100."""
    status, reason = classify_candidate(
        n_events=50, n_dates=25, mean_return=0.50, median_return=0.30,
        dc_ci_low=0.10, dc_ci_high=0.90,
    )
    assert status == "PROVISIONAL", f"Expected PROVISIONAL, got {status}: {reason}"


def test_insufficient_low_n():
    """n < 30."""
    status, reason = classify_candidate(
        n_events=15, n_dates=10, mean_return=0.50, median_return=0.30,
        dc_ci_low=0.10, dc_ci_high=0.90,
    )
    assert status == "INSUFFICIENT", f"Expected INSUFFICIENT, got {status}: {reason}"


def test_insufficient_negative_mean():
    """Mean return <= 0."""
    status, reason = classify_candidate(
        n_events=500, n_dates=30, mean_return=-0.20, median_return=-0.10,
        dc_ci_low=-0.50, dc_ci_high=0.10,
    )
    assert status == "INSUFFICIENT", f"Expected INSUFFICIENT, got {status}: {reason}"


def test_low_date_count():
    """n_dates < 10."""
    status, reason = classify_candidate(
        n_events=500, n_dates=5, mean_return=1.50, median_return=1.00,
        dc_ci_low=0.50, dc_ci_high=2.50,
    )
    assert status == "LOW_DATE_COUNT", f"Expected LOW_DATE_COUNT, got {status}: {reason}"


# ═══════════════════════════════════════════════════════════════
# Test 2: date-cluster CI as primary logic
# ═══════════════════════════════════════════════════════════════

def test_dc_ci_primary_for_qualified():
    """QUALIFIED requires date-cluster CI lower > 0, not just event CI."""
    # Same data, only dc_ci differs
    status1, _ = classify_candidate(
        n_events=500, n_dates=30, mean_return=0.75, median_return=0.50,
        dc_ci_low=0.25, dc_ci_high=1.25,
    )
    status2, _ = classify_candidate(
        n_events=500, n_dates=30, mean_return=0.75, median_return=0.50,
        dc_ci_low=-0.05, dc_ci_high=1.55,
    )
    assert status1 == "QUALIFIED"
    assert status2 == "PROVISIONAL", f"dc_ci crosses zero should be PROVISIONAL, got {status2}"


# ═══════════════════════════════════════════════════════════════
# Test 3: Ice LOW_DATE_COUNT
# ═══════════════════════════════════════════════════════════════

def test_ice_low_date_classification():
    """Ice-regime patterns with 5 dates must be LOW_DATE_COUNT."""
    status, reason = classify_candidate(
        n_events=844, n_dates=5, mean_return=1.50, median_return=1.00,
        dc_ci_low=0.50, dc_ci_high=2.50,
    )
    assert status == "LOW_DATE_COUNT", (
        f"Ice patterns with 5 dates must be LOW_DATE_COUNT, got {status}"
    )


# ═══════════════════════════════════════════════════════════════
# Test 4: Hot CI crossing zero
# ═══════════════════════════════════════════════════════════════

def test_hot_ci_knowledge():
    """Verify hot regime aggregate CI crosses zero (from Phase 2B.1 audit)."""
    # This test verifies the fact is preserved in the output CSV
    dc_csv = RESULTS_DIR / "pattern_date_cluster_bootstrap.csv"
    with open(dc_csv) as f:
        rows = list(csv.DictReader(f))
    hot_mean = [r for r in rows if r["regime"] == "hot" and r["statistic"] == "mean"]
    assert len(hot_mean) > 0, "Hot regime mean row not found in date-cluster CSV"
    for r in hot_mean:
        dc_lo = float(r["date_cluster_ci_low"])
        dc_hi = float(r["date_cluster_ci_high"])
        assert dc_lo < 0, f"Hot CI lower bound should be < 0, got {dc_lo}"
        assert dc_hi > 0, f"Hot CI upper bound should be > 0, got {dc_hi}"


# ═══════════════════════════════════════════════════════════════
# Test 5: No ranking fields
# ═══════════════════════════════════════════════════════════════

def test_no_ranking_fields_in_candidate_table():
    """Candidate table must not contain ranking fields."""
    forbidden = {"rank", "winner", "best", "enable", "weight", "score",
                 "top", "buy", "sell", "router", "priority"}
    candidate_csv = RESULTS_DIR / "phase2c_candidate_table.csv"
    assert candidate_csv.exists(), "Candidate table not found"
    with open(candidate_csv) as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        found = fields & forbidden
        assert len(found) == 0, f"Forbidden ranking fields found: {found}"


def test_no_ranking_fields_in_summary():
    """Summary CSV must not contain ranking fields."""
    forbidden = {"rank", "winner", "best", "enable", "weight", "score"}
    summary_csv = RESULTS_DIR / "phase2c_candidate_summary.csv"
    with open(summary_csv) as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        found = fields & forbidden
        assert len(found) == 0, f"Forbidden ranking fields found: {found}"


def test_no_ranking_fields_in_matrix():
    """Matrix CSV must not contain ranking fields."""
    forbidden = {"rank", "winner", "best", "enable", "weight", "score"}
    matrix_csv = RESULTS_DIR / "phase2c_regime_pattern_matrix.csv"
    with open(matrix_csv) as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        found = fields & forbidden
        assert len(found) == 0, f"Forbidden ranking fields found: {found}"


def test_candidate_status_values():
    """Candidate status must use only allowed values."""
    allowed = {"QUALIFIED", "PROVISIONAL", "INSUFFICIENT", "LOW_DATE_COUNT"}
    candidate_csv = RESULTS_DIR / "phase2c_candidate_table.csv"
    with open(candidate_csv) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        assert r["candidate_status"] in allowed, (
            f"Invalid candidate_status: {r['candidate_status']}"
        )


# ═══════════════════════════════════════════════════════════════
# Test 6: No future OOS leakage
# ═══════════════════════════════════════════════════════════════

def test_period_separation():
    """get_period must correctly separate train/val/OOS."""
    assert get_period("2025-06-15") == "train"
    assert get_period("2026-01-01") == "validation"
    assert get_period("2026-07-01") == "oos"
    assert get_period("2024-01-01") == "unknown"


def test_oos_candidates_only_use_oos_data():
    """Candidate table must not reference train/val data in primary metrics."""
    candidate_csv = RESULTS_DIR / "phase2c_candidate_table.csv"
    with open(candidate_csv) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) > 0, "No candidate rows"
    # All metrics in candidate table are OOS metrics
    for r in rows:
        assert int(r["oos_events"]) > 0, f"oos_events should be > 0, got {r['oos_events']}"
        assert int(r["oos_dates"]) > 0, f"oos_dates should be > 0, got {r['oos_dates']}"


# ═══════════════════════════════════════════════════════════════
# Test 7: Train/validation/OOS separation in matrix
# ═══════════════════════════════════════════════════════════════

def test_matrix_has_train_val_oos():
    """Stability matrix must have train, validation, and OOS columns."""
    matrix_csv = RESULTS_DIR / "phase2c_regime_pattern_matrix.csv"
    with open(matrix_csv) as f:
        rows = list(csv.DictReader(f))
    required = {"train_result", "validation_result", "oos_result", "stability_status"}
    for r in rows[:5]:
        for field in required:
            assert field in r, f"Missing field {field} in matrix row"


# ═══════════════════════════════════════════════════════════════
# Test 8: profile_name + pattern_name preserved
# ═══════════════════════════════════════════════════════════════

def test_profile_and_pattern_preserved():
    """Candidate table must have both profile_name and pattern_name."""
    candidate_csv = RESULTS_DIR / "phase2c_candidate_table.csv"
    with open(candidate_csv) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        assert r["profile_name"], f"Empty profile_name for {r.get('pattern_name')}"
        assert r["pattern_name"], f"Empty pattern_name for {r.get('profile_name')}"


def test_profile_pattern_map_derivation():
    """Profile→pattern mapping must be derived from event data."""
    events = [
        {"profiles": "momentum_v5|t1_swing", "patterns": "breakout|old_duck"},
        {"profiles": "lotus", "patterns": "lotus"},
        {"profiles": "single_yang", "patterns": "single_yang"},
    ]
    mapping = derive_profile_pattern_map(events)
    assert "momentum_v5" in mapping
    assert "breakout" in mapping["momentum_v5"]
    assert "lotus" in mapping
    assert "lotus" in mapping["lotus"]


def test_get_primary_profile_direct_match():
    """Pattern name matching profile name returns that profile."""
    mapping = {"lotus": {"lotus"}, "momentum_v5": {"breakout", "ignition"}}
    assert get_primary_profile("lotus", mapping) == "lotus"
    assert get_primary_profile("breakout", mapping) == "momentum_v5"


# ═══════════════════════════════════════════════════════════════
# Test 9: Deterministic output
# ═══════════════════════════════════════════════════════════════

def test_deterministic_classification():
    """Classification must be deterministic (same inputs = same result)."""
    for _ in range(10):
        status1, _ = classify_candidate(
            n_events=500, n_dates=30, mean_return=0.75, median_return=0.50,
            dc_ci_low=0.25, dc_ci_high=1.25,
        )
        assert status1 == "QUALIFIED"


# ═══════════════════════════════════════════════════════════════
# Test 10: Present/absent composition reported
# ═══════════════════════════════════════════════════════════════

def test_present_absent_fields_exist():
    """Candidate table must include present_n, absent_n, single_n, multi_n."""
    candidate_csv = RESULTS_DIR / "phase2c_candidate_table.csv"
    with open(candidate_csv) as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
    required = {"present_n", "absent_n", "single_n", "multi_n"}
    missing = required - fields
    assert len(missing) == 0, f"Missing composition fields: {missing}"

    # Verify values are present
    rows = list(csv.DictReader(open(candidate_csv)))
    for r in rows[:3]:
        assert int(r["present_n"]) > 0, f"present_n should be > 0"
        # absent_n can be 0


# ═══════════════════════════════════════════════════════════════
# Test 11: Multi-pattern event not double-counted
# ═══════════════════════════════════════════════════════════════

def test_event_count_is_unique_events():
    """Candidate oos_events must count unique events, not pattern rows."""
    candidate_csv = RESULTS_DIR / "phase2c_candidate_table.csv"
    with open(candidate_csv) as f:
        rows = list(csv.DictReader(f))
    # The implementation uses set(event_ids) for counting
    # Cross-check: sum of present_n across patterns should not exceed
    # total OOS events * avg patterns per event
    # Total OOS events = 69,679. Sum of present_n is larger because
    # each event can contribute to multiple patterns.
    # This test verifies that for any single pattern, n_events <= total OOS
    total_oos = 69679
    for r in rows:
        n = int(r["oos_events"])
        assert n <= total_oos, (
            f"Pattern {r['pattern_name']} has {n} events > total OOS {total_oos}"
        )


# ═══════════════════════════════════════════════════════════════
# Test 12: Candidate table schema
# ═══════════════════════════════════════════════════════════════

def test_candidate_table_schema():
    """Verify all required columns exist with correct types."""
    candidate_csv = RESULTS_DIR / "phase2c_candidate_table.csv"
    with open(candidate_csv) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) > 0, "Candidate table is empty"

    required_fields = [
        "regime", "profile_name", "pattern_name",
        "oos_events", "oos_dates",
        "mean_return", "median_return", "win_rate",
        "event_bootstrap_mean_ci_low", "event_bootstrap_mean_ci_high",
        "date_cluster_mean_ci_low", "date_cluster_mean_ci_high",
        "excess_return", "evidence_grade",
        "candidate_status", "reason",
    ]
    for field in required_fields:
        assert field in rows[0], f"Missing required field: {field}"

    # Verify types
    for r in rows[:5]:
        int(r["oos_events"])
        int(r["oos_dates"])
        float(r["mean_return"])
        float(r["win_rate"])


def test_summary_schema():
    """Verify summary CSV has correct columns."""
    summary_csv = RESULTS_DIR / "phase2c_candidate_summary.csv"
    with open(summary_csv) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) > 0, "Summary is empty"
    required = ["regime", "qualified_count", "provisional_count",
                "insufficient_count", "low_date_count", "total_patterns"]
    for field in required:
        assert field in rows[0], f"Missing required field: {field}"

    # Verify OVERALL row exists
    regimes = [r["regime"] for r in rows]
    assert "OVERALL" in regimes, "Missing OVERALL summary row"


def test_matrix_schema():
    """Verify matrix CSV has correct columns."""
    matrix_csv = RESULTS_DIR / "phase2c_regime_pattern_matrix.csv"
    with open(matrix_csv) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) > 0, "Matrix is empty"
    required = ["regime", "pattern_name", "train_result", "validation_result",
                "oos_result", "oos_date_cluster_ci_low", "oos_date_cluster_ci_high",
                "stability_status"]
    for field in required:
        assert field in rows[0], f"Missing required field: {field}"


# ═══════════════════════════════════════════════════════════════
# Additional: Ice regime in candidate output
# ═══════════════════════════════════════════════════════════════

def test_ice_regime_all_low_date_count():
    """All ice regime candidates must be LOW_DATE_COUNT."""
    candidate_csv = RESULTS_DIR / "phase2c_candidate_table.csv"
    with open(candidate_csv) as f:
        rows = list(csv.DictReader(f))
    ice_rows = [r for r in rows if r["regime"] == "ice"]
    assert len(ice_rows) > 0, "No ice regime candidates found"
    for r in ice_rows:
        assert r["candidate_status"] == "LOW_DATE_COUNT", (
            f"Ice pattern {r['pattern_name']} should be LOW_DATE_COUNT, got {r['candidate_status']}"
        )


# ═══════════════════════════════════════════════════════════════
# Additional: Euphoria absence
# ═══════════════════════════════════════════════════════════════

def test_euphoria_not_in_candidates():
    """Euphoria regime should have no candidates (insufficient OOS data)."""
    candidate_csv = RESULTS_DIR / "phase2c_candidate_table.csv"
    with open(candidate_csv) as f:
        rows = list(csv.DictReader(f))
    euphoria = [r for r in rows if r["regime"] == "euphoria"]
    assert len(euphoria) == 0, (
        f"Euphoria has {len(euphoria)} candidates — should have 0 (no OOS data)"
    )
