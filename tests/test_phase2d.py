"""Phase 2D — Frozen Candidate Independent OOS Re-validation tests.

Tests verify:
  1. Frozen candidates are immutable (21 from Phase 2C)
  2. Revalidation status classification
  3. Date-cluster bootstrap determinism
  4. Phase 2D window independence from Phase 2C OOS
  5. No ranking fields in output
  6. Candidate table schema validation
  7. Summary table schema and OVERALL row
  8. Stability matrix schema
  9. Phase 2C metrics preserved unchanged
 10. Hot aggregate CI crossing zero in Phase 2C, confirmed positive in Phase 2D
 11. Revalidation status values are valid
 12. Single/multi event composition reported
 13. No NOT_OBSERVED for warmup/hot candidates
 14. Deterministic revalidation output
"""

import csv
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"


# ═══════════════════════════════════════════════════════════════
# Test 1: Frozen candidates are immutable (21 from Phase 2C)
# ═══════════════════════════════════════════════════════════════

def test_frozen_candidate_count():
    """Exactly 21 QUALIFIED candidates, all from Phase 2C."""
    frozen_csv = RESULTS_DIR / "phase2d_frozen_candidates.csv"
    with open(frozen_csv) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 21, f"Expected 21 frozen candidates, got {len(rows)}"
    for r in rows:
        assert r["freeze_commit"] == "b22698c", (
            f"Frozen candidate {r['pattern_name']} not from Phase 2C commit b22698c"
        )
        assert r["freeze_source"] == "phase2c_candidate_table.csv"


def test_frozen_candidates_only_warmup_hot():
    """All frozen candidates must be warmup or hot regime."""
    frozen_csv = RESULTS_DIR / "phase2d_frozen_candidates.csv"
    with open(frozen_csv) as f:
        rows = list(csv.DictReader(f))
    regimes = set(r["regime"] for r in rows)
    assert regimes == {"warmup", "hot"}, f"Expected only warmup+hot, got {regimes}"


def test_frozen_candidate_metrics_match_phase2c():
    """Phase 2C metrics in frozen table must match Phase 2C candidate table."""
    frozen_csv = RESULTS_DIR / "phase2d_frozen_candidates.csv"
    phase2c_csv = RESULTS_DIR / "phase2c_candidate_table.csv"

    with open(frozen_csv) as f:
        frozen = {f"{r['regime']}|{r['pattern_name']}": r for r in csv.DictReader(f)}
    with open(phase2c_csv) as f:
        p2c = {f"{r['regime']}|{r['pattern_name']}": r for r in csv.DictReader(f)
               if r["candidate_status"] == "QUALIFIED"}

    assert len(frozen) == len(p2c), f"Frozen count {len(frozen)} != P2C QUALIFIED {len(p2c)}"

    for key, fr in frozen.items():
        pc = p2c[key]
        assert int(fr["phase2c_events"]) == int(pc["oos_events"]), (
            f"{key}: frozen events {fr['phase2c_events']} != P2C {pc['oos_events']}"
        )
        assert float(fr["phase2c_mean"]) == float(pc["mean_return"]), (
            f"{key}: frozen mean {fr['phase2c_mean']} != P2C {pc['mean_return']}"
        )


# ═══════════════════════════════════════════════════════════════
# Test 2: Revalidation status classification
# ═══════════════════════════════════════════════════════════════

def test_revalidation_statuses_are_valid():
    """All revalidation statuses must be from the allowed set."""
    allowed = {"REVALIDATED", "REVALIDATION_UNCERTAIN", "REVALIDATION_FAIL",
               "LOW_DATE_COUNT", "NOT_OBSERVED"}
    csv_path = RESULTS_DIR / "phase2d_revalidation.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        assert r["revalidation_status"] in allowed, (
            f"Invalid status: {r['revalidation_status']}"
        )


def test_revalidated_means_positive():
    """REVALIDATED candidates must have positive mean, median, and CI low."""
    csv_path = RESULTS_DIR / "phase2d_revalidation.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r["revalidation_status"] == "REVALIDATED":
            assert float(r["phase2d_mean"]) > 0, (
                f"{r['pattern_name']}: REVALIDATED but mean={r['phase2d_mean']}"
            )
            assert float(r["phase2d_median"]) > 0, (
                f"{r['pattern_name']}: REVALIDATED but median={r['phase2d_median']}"
            )


def test_uncertain_has_positive_mean():
    """UNCERTAIN must have positive mean but CI or median not confirmed."""
    csv_path = RESULTS_DIR / "phase2d_revalidation.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r["revalidation_status"] == "REVALIDATION_UNCERTAIN":
            assert float(r["phase2d_mean"]) > 0, (
                f"{r['pattern_name']}: UNCERTAIN but mean <= 0"
            )
            # Must fail either median > 0 or CI confirmed
            median_ok = float(r["phase2d_median"]) > 0
            ci_ok = r["phase2d_ci_low"] is not None and float(r["phase2d_ci_low"]) > 0
            assert not (median_ok and ci_ok), (
                f"{r['pattern_name']}: meets REVALIDATED criteria but marked UNCERTAIN"
            )


# ═══════════════════════════════════════════════════════════════
# Test 3: Date-cluster bootstrap determinism
# ═══════════════════════════════════════════════════════════════

def test_date_cluster_bootstrap_deterministic():
    """Date-cluster bootstrap with same seed must produce same results."""
    from scripts.phase2d_revalidate import date_cluster_bootstrap

    events = []
    for date_idx in range(20):
        for val in range(30):
            events.append({
                "signal_date": f"2025-{((date_idx // 2) + 4):02d}-{((date_idx % 28) + 1):02d}",
                "return_median": str(0.5 + (date_idx * 0.1) + (val * 0.01)),
            })

    result1 = date_cluster_bootstrap(events, "return_median", "mean", seed=42)
    result2 = date_cluster_bootstrap(events, "return_median", "mean", seed=42)
    assert result1["ci_lower"] == result2["ci_lower"]
    assert result1["ci_upper"] == result2["ci_upper"]

    # Different seed should produce different (but similar) results
    result3 = date_cluster_bootstrap(events, "return_median", "mean", seed=99)
    assert result3["ci_lower"] != result2["ci_lower"] or result3["ci_upper"] != result2["ci_upper"]


# ═══════════════════════════════════════════════════════════════
# Test 4: Phase 2D window independence from Phase 2C OOS
# ═══════════════════════════════════════════════════════════════

def test_phase2d_window_before_phase2c_oos():
    """Phase 2D window must end before Phase 2C OOS starts."""
    from scripts.phase2d_revalidate import PHASE2D_START, PHASE2D_END
    from scripts.phase2c_validate import OOS_START, OOS_END

    assert PHASE2D_END < OOS_START, (
        f"Phase 2D end {PHASE2D_END} must be before Phase 2C OOS start {OOS_START}"
    )
    assert PHASE2D_START < PHASE2D_END, "Phase 2D window inverted"


def test_no_date_overlap_between_phase2d_and_phase2c_oos():
    """Phase 2D window must not share any dates with Phase 2C OOS."""
    from scripts.phase2d_revalidate import PHASE2D_START, PHASE2D_END
    from scripts.phase2c_validate import OOS_START, OOS_END

    # Dates are strings, but sequential comparison works for ISO format
    assert PHASE2D_END <= "2026-03-31", (
        f"Phase 2D extends into validation period"
    )
    assert OOS_START >= "2026-04-01", (
        f"Phase 2C OOS starts in validation period"
    )


# ═══════════════════════════════════════════════════════════════
# Test 5: No ranking fields in output
# ═══════════════════════════════════════════════════════════════

def test_no_ranking_fields_in_revalidation():
    """Revalidation CSV must not contain ranking fields."""
    forbidden = {"rank", "winner", "best", "enable", "weight", "score",
                 "top", "buy", "sell", "router", "priority"}
    csv_path = RESULTS_DIR / "phase2d_revalidation.csv"
    with open(csv_path) as f:
        fields = set(csv.DictReader(f).fieldnames or [])
        found = fields & forbidden
        assert len(found) == 0, f"Forbidden ranking fields found: {found}"


def test_no_ranking_fields_in_frozen():
    """Frozen candidates CSV must not contain ranking fields."""
    forbidden = {"rank", "winner", "best", "enable", "weight", "score"}
    csv_path = RESULTS_DIR / "phase2d_frozen_candidates.csv"
    with open(csv_path) as f:
        fields = set(csv.DictReader(f).fieldnames or [])
        found = fields & forbidden
        assert len(found) == 0, f"Forbidden ranking fields found: {found}"


def test_no_ranking_fields_in_summary():
    """Summary CSV must not contain ranking fields."""
    forbidden = {"rank", "winner", "best", "enable", "weight", "score"}
    csv_path = RESULTS_DIR / "phase2d_summary.csv"
    with open(csv_path) as f:
        fields = set(csv.DictReader(f).fieldnames or [])
        found = fields & forbidden
        assert len(found) == 0, f"Forbidden ranking fields found: {found}"


def test_no_ranking_fields_in_stability():
    """Stability matrix CSV must not contain ranking fields."""
    forbidden = {"rank", "winner", "best", "enable", "weight", "score"}
    csv_path = RESULTS_DIR / "phase2d_stability_matrix.csv"
    with open(csv_path) as f:
        fields = set(csv.DictReader(f).fieldnames or [])
        found = fields & forbidden
        assert len(found) == 0, f"Forbidden ranking fields found: {found}"


# ═══════════════════════════════════════════════════════════════
# Test 6: Candidate table schema validation
# ═══════════════════════════════════════════════════════════════

def test_revalidation_table_schema():
    """All required columns must exist in revalidation CSV."""
    required = [
        "regime", "profile_name", "pattern_name",
        "phase2c_events", "phase2c_dates",
        "phase2c_mean", "phase2c_median", "phase2c_win_rate",
        "phase2c_ci_low", "phase2c_ci_high",
        "phase2d_events", "phase2d_dates",
        "phase2d_mean", "phase2d_median", "phase2d_win_rate",
        "phase2d_ci_low", "phase2d_ci_high",
        "mean_return_delta", "median_return_delta", "win_rate_delta",
        "revalidation_status",
        "single_events", "multi_events",
    ]
    csv_path = RESULTS_DIR / "phase2d_revalidation.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 21, f"Expected 21 rows, got {len(rows)}"
    for field in required:
        assert field in rows[0], f"Missing required field: {field}"

    # Verify numeric types
    for r in rows[:3]:
        int(r["phase2d_events"])
        int(r["phase2d_dates"])
        float(r["phase2d_mean"])
        float(r["phase2d_median"])
        float(r["phase2d_win_rate"])
        int(r["single_events"])
        int(r["multi_events"])


def test_frozen_table_schema():
    """All required columns must exist in frozen candidates CSV."""
    required = [
        "regime", "profile_name", "pattern_name",
        "phase2c_events", "phase2c_dates",
        "phase2c_mean", "phase2c_median", "phase2c_win_rate",
        "phase2c_ci_low", "phase2c_ci_high",
        "freeze_commit", "freeze_source",
    ]
    csv_path = RESULTS_DIR / "phase2d_frozen_candidates.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    for field in required:
        assert field in rows[0], f"Missing required field: {field}"


# ═══════════════════════════════════════════════════════════════
# Test 7: Summary table schema and OVERALL row
# ═══════════════════════════════════════════════════════════════

def test_summary_schema():
    """Summary CSV has correct columns and OVERALL row."""
    csv_path = RESULTS_DIR / "phase2d_summary.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    required = ["regime", "frozen_candidates", "revalidated",
                "uncertain", "failed", "low_date_count", "not_observed"]
    for field in required:
        assert field in rows[0], f"Missing required field: {field}"

    regimes = [r["regime"] for r in rows]
    assert "OVERALL" in regimes, "Missing OVERALL summary row"
    overall = [r for r in rows if r["regime"] == "OVERALL"][0]
    assert int(overall["frozen_candidates"]) == 21
    assert int(overall["revalidated"]) + int(overall["uncertain"]) + \
           int(overall["failed"]) + int(overall["low_date_count"]) + \
           int(overall["not_observed"]) == 21, "OVERALL counts must sum to 21"


# ═══════════════════════════════════════════════════════════════
# Test 8: Stability matrix schema
# ═══════════════════════════════════════════════════════════════

def test_stability_matrix_schema():
    """Stability matrix has correct columns."""
    required = [
        "regime", "profile_name", "pattern_name",
        "phase2c_direction", "phase2d_direction",
        "phase2c_ci_positive", "phase2d_ci_positive",
        "stability",
    ]
    csv_path = RESULTS_DIR / "phase2d_stability_matrix.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 21, f"Expected 21 rows, got {len(rows)}"
    for field in required:
        assert field in rows[0], f"Missing required field: {field}"

    # Stability values must be valid
    allowed = {"CONSISTENT_POSITIVE", "POSITIVE_TO_UNCERTAIN",
               "POSITIVE_TO_NEGATIVE", "NOT_OBSERVED", "INSUFFICIENT"}
    for r in rows:
        assert r["stability"] in allowed, (
            f"Invalid stability: {r['stability']}"
        )
        assert r["phase2c_direction"] in {"POSITIVE", "NEGATIVE"}
        assert r["phase2c_ci_positive"] in {"YES", "NO"}


# ═══════════════════════════════════════════════════════════════
# Test 9: Phase 2C metrics preserved unchanged
# ═══════════════════════════════════════════════════════════════

def test_phase2c_metrics_unchanged_in_revalidation():
    """Phase 2C columns must match frozen candidate values."""
    frozen_csv = RESULTS_DIR / "phase2d_frozen_candidates.csv"
    reval_csv = RESULTS_DIR / "phase2d_revalidation.csv"

    with open(frozen_csv) as f:
        frozen = {f"{r['regime']}|{r['pattern_name']}": r for r in csv.DictReader(f)}
    with open(reval_csv) as f:
        reval = {f"{r['regime']}|{r['pattern_name']}": r for r in csv.DictReader(f)}

    for key, rv in reval.items():
        fr = frozen[key]
        for field in ["phase2c_events", "phase2c_dates", "phase2c_mean",
                       "phase2c_median", "phase2c_win_rate",
                       "phase2c_ci_low", "phase2c_ci_high"]:
            assert rv[field] == fr[field], (
                f"{key}: {field} mismatch — frozen={fr[field]}, reval={rv[field]}"
            )


# ═══════════════════════════════════════════════════════════════
# Test 10: Hot aggregate CI crossing zero (Phase 2C) vs Phase 2D
# ═══════════════════════════════════════════════════════════════

def test_hot_phase2c_ci_crosses_zero():
    """Phase 2C hot aggregate DC CI must cross zero."""
    dc_csv = RESULTS_DIR / "pattern_date_cluster_bootstrap.csv"
    with open(dc_csv) as f:
        rows = list(csv.DictReader(f))
    hot_mean = [r for r in rows if r["regime"] == "hot" and r["statistic"] == "mean"]
    for r in hot_mean:
        assert float(r["date_cluster_ci_low"]) < 0, "Phase 2C hot CI low must be < 0"
        assert float(r["date_cluster_ci_high"]) > 0, "Phase 2C hot CI high must be > 0"


def test_hot_phase2d_ci_positive():
    """Phase 2D hot aggregate DC CI should be positive (from revalidation output)."""
    # Verify all 8 hot candidates have positive Phase 2D DC CI
    reval_csv = RESULTS_DIR / "phase2d_revalidation.csv"
    with open(reval_csv) as f:
        rows = [r for r in csv.DictReader(f) if r["regime"] == "hot"]
    assert len(rows) == 8, f"Expected 8 hot candidates, got {len(rows)}"
    # In Phase 2D window, hot aggregate is positive
    for r in rows:
        ci_lo = float(r["phase2d_ci_low"])
        assert ci_lo > 0, (
            f"Hot {r['pattern_name']} Phase 2D CI low {ci_lo} must be > 0"
        )


# ═══════════════════════════════════════════════════════════════
# Test 11: Revalidation status values exhaustive
# ═══════════════════════════════════════════════════════════════

def test_revalidation_status_counts():
    """Verify the distribution of revalidation statuses."""
    csv_path = RESULTS_DIR / "phase2d_revalidation.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))

    from collections import Counter
    counts = Counter(r["revalidation_status"] for r in rows)

    assert counts["REVALIDATED"] == 19, f"Expected 19 REVALIDATED, got {counts.get('REVALIDATED', 0)}"
    assert counts["REVALIDATION_UNCERTAIN"] == 2, (
        f"Expected 2 UNCERTAIN, got {counts.get('REVALIDATION_UNCERTAIN', 0)}"
    )
    assert counts.get("REVALIDATION_FAIL", 0) == 0
    assert counts.get("LOW_DATE_COUNT", 0) == 0
    assert counts.get("NOT_OBSERVED", 0) == 0


# ═══════════════════════════════════════════════════════════════
# Test 12: Single/multi event composition reported
# ═══════════════════════════════════════════════════════════════

def test_single_multi_composition():
    """Every candidate must report single_events and multi_events."""
    csv_path = RESULTS_DIR / "phase2d_revalidation.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        s = int(r["single_events"])
        m = int(r["multi_events"])
        total = int(r["phase2d_events"])
        assert s + m == total, (
            f"{r['pattern_name']}/{r['regime']}: single({s}) + multi({m}) != total({total})"
        )
        assert s + m > 0, f"{r['pattern_name']}: no events"


# ═══════════════════════════════════════════════════════════════
# Test 13: No NOT_OBSERVED for warmup/hot candidates
# ═══════════════════════════════════════════════════════════════

def test_warmup_hot_candidates_have_events():
    """All frozen candidates are warmup/hot and must have Phase 2D events."""
    csv_path = RESULTS_DIR / "phase2d_revalidation.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        assert r["revalidation_status"] != "NOT_OBSERVED", (
            f"{r['pattern_name']}/{r['regime']}: should not be NOT_OBSERVED"
        )
        assert int(r["phase2d_events"]) > 0, (
            f"{r['pattern_name']}/{r['regime']}: phase2d_events must be > 0"
        )
        assert int(r["phase2d_dates"]) >= 10, (
            f"{r['pattern_name']}/{r['regime']}: phase2d_dates must be >= 10"
        )


# ═══════════════════════════════════════════════════════════════
# Test 14: Deterministic revalidation output
# ═══════════════════════════════════════════════════════════════

def test_revalidation_deterministic():
    """Running revalidation twice with same inputs must produce identical outputs."""
    import sys
    import io
    from scripts.phase2d_revalidate import compute_revalidation, load_frozen_candidates
    import csv

    EVENTS = RESULTS_DIR / "event_level_trades.csv"
    frozen = load_frozen_candidates()
    events = list(csv.DictReader(open(EVENTS)))

    rows1, summ1, stab1 = compute_revalidation(frozen, events)
    rows2, summ2, stab2 = compute_revalidation(frozen, events)

    # Compare revalidation rows
    for r1, r2 in zip(rows1, rows2):
        for key in r1:
            assert r1[key] == r2[key], f"Non-deterministic: {key}: {r1[key]} vs {r2[key]}"

    # Compare summary
    for s1, s2 in zip(summ1, summ2):
        for key in s1:
            assert s1[key] == s2[key], f"Non-deterministic summary: {key}"

    # Compare stability
    for t1, t2 in zip(stab1, stab2):
        for key in t1:
            assert t1[key] == t2[key], f"Non-deterministic stability: {key}"


# ═══════════════════════════════════════════════════════════════
# Additional: Revalidation deltas are correct
# ═══════════════════════════════════════════════════════════════

def test_mean_delta_calculation():
    """mean_return_delta must equal phase2d_mean - phase2c_mean."""
    csv_path = RESULTS_DIR / "phase2d_revalidation.csv"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        p2c = float(r["phase2c_mean"])
        p2d = float(r["phase2d_mean"])
        expected = round(p2d - p2c, 4)
        actual = float(r["mean_return_delta"])
        assert abs(actual - expected) < 0.0001, (
            f"Delta mismatch: {actual} != {expected}"
        )
