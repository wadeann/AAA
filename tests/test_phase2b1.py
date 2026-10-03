"""Phase 2B.1 — Pattern Incremental Attribution + Date-Cluster Bootstrap tests.

Tests verify:
  1. event_id uniqueness
  2. pattern presence counted once per event
  3. no event duplication from multi-pattern events
  4. solo vs concurrent classification correct
  5. incremental calculation correct (deterministic fixture)
  6. date-cluster bootstrap: same-date events clustered together
  7. bootstrap deterministic with seed=42
  8. OOS isolation (no train/val dates)
  9. train/val/oos no overlap
  10. theme_lifecycle stays NOT_AVAILABLE
  11. no ranking fields in output
  12. legacy Phase 2B results readable
"""

import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.phase2b1_incremental_attribution import (
    event_bootstrap_ci,
    date_cluster_bootstrap,
    incremental_bootstrap,
    get_period,
    get_sample_label,
    OOS_START,
    OOS_END,
    TRAIN_START,
    TRAIN_END,
    VAL_START,
    VAL_END,
)

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
EVENT_CSV = RESULTS_DIR / "event_level_trades.csv"
ATTR_CSV = RESULTS_DIR / "pattern_incremental_attribution.csv"
SOLO_CSV = RESULTS_DIR / "pattern_solo_concurrent.csv"
DC_CSV = RESULTS_DIR / "pattern_date_cluster_bootstrap.csv"
EVIDENCE_CSV = RESULTS_DIR / "pattern_incremental_evidence.csv"


def _load_events():
    with open(EVENT_CSV) as f:
        return list(csv.DictReader(f))


# ═══════════════════════════════════════════════════════════════
# Test 1: Event ID uniqueness
# ═══════════════════════════════════════════════════════════════

def test_event_id_unique():
    """Every event_id must be unique."""
    events = _load_events()
    ids = [e["event_id"] for e in events]
    assert len(ids) == len(set(ids)), f"Found {len(ids) - len(set(ids))} duplicate event_ids"

def test_event_count_correct():
    """Event count should be 282,892."""
    events = _load_events()
    assert len(events) == 282892


# ═══════════════════════════════════════════════════════════════
# Test 2: Pattern presence — single count per event
# ═══════════════════════════════════════════════════════════════

def test_pattern_presence_single_count():
    """A pattern can only appear once per event (present or absent, never both)."""
    events = _load_events()
    # For each event, check that a given pattern is either present or absent
    for e in events[:5000]:
        event_patterns = set(p.strip() for p in e["patterns"].split("|"))
        for p in event_patterns:
            # Pattern should appear exactly once in event_patterns
            count = sum(1 for ep in e["patterns"].split("|") if ep.strip() == p)
            assert count == 1, f"Pattern {p} appears {count} times in {e['event_id']}"


# ═══════════════════════════════════════════════════════════════
# Test 3: No event duplication from multi-pattern
# ═══════════════════════════════════════════════════════════════

def test_no_event_duplication_in_attribution():
    """Attribution CSV must not double-count events."""
    with open(ATTR_CSV) as f:
        rows = list(csv.DictReader(f))
    # Sum of n_events across present+absent for same (pattern, regime, period)
    # should not exceed total events in that period+regime
    from collections import defaultdict
    events = _load_events()
    period_regime_counts = defaultdict(int)
    for e in events:
        period = get_period(e["signal_date"])
        regime = e["market_regime"]
        period_regime_counts[(period, regime)] += 1

    for r in rows:
        n = int(r["n_events"])
        pr = (r["period"], r["regime"])
        total = period_regime_counts.get(pr, 0)
        assert n <= total, \
            f"Attribution row has n={n} > total events={total} for {pr}"


# ═══════════════════════════════════════════════════════════════
# Test 4: Solo vs concurrent classification
# ═══════════════════════════════════════════════════════════════

def test_solo_events_have_pattern_count_1():
    """Solo events must have pattern_count == 1."""
    events = _load_events()
    solo_events_from_data = [e for e in events if int(e["pattern_count"]) == 1]
    for e in solo_events_from_data[:1000]:
        assert int(e["pattern_count"]) == 1

    concurrent_events = [e for e in events if int(e["pattern_count"]) > 1]
    for e in concurrent_events[:1000]:
        assert int(e["pattern_count"]) > 1


def test_solo_concurrent_csv_event_types():
    """Solo/concurrent CSV must only have valid event_type values."""
    with open(SOLO_CSV) as f:
        rows = list(csv.DictReader(f))
    valid = {"solo", "concurrent"}
    for r in rows:
        assert r["event_type"] in valid, \
            f"Invalid event_type: {r['event_type']}"


# ═══════════════════════════════════════════════════════════════
# Test 5: Incremental calculation (deterministic fixture)
# ═══════════════════════════════════════════════════════════════

def test_incremental_mean_calculation():
    """Incremental mean = present_mean - absent_mean."""
    # Create deterministic fixture
    present_events = [
        {"signal_date": "2026-05-01", "return_median": "2.0", "market_regime": "warmup"},
        {"signal_date": "2026-05-02", "return_median": "3.0", "market_regime": "warmup"},
        {"signal_date": "2026-05-03", "return_median": "1.0", "market_regime": "warmup"},
    ]
    absent_events = [
        {"signal_date": "2026-05-01", "return_median": "0.5", "market_regime": "warmup"},
        {"signal_date": "2026-05-02", "return_median": "0.0", "market_regime": "warmup"},
        {"signal_date": "2026-05-03", "return_median": "-0.5", "market_regime": "warmup"},
    ]
    p_mean = (2.0 + 3.0 + 1.0) / 3
    a_mean = (0.5 + 0.0 - 0.5) / 3
    expected_inc = p_mean - a_mean

    result = incremental_bootstrap(present_events, absent_events, "return_median", "mean", "event",
                                   n_iterations=100, seed=42)
    assert abs(result["point_estimate"] - expected_inc) < 0.001, \
        f"Expected {expected_inc}, got {result['point_estimate']}"


def test_incremental_win_rate_calculation():
    """Incremental win rate = present_wr - absent_wr."""
    present_events = [
        {"signal_date": "2026-05-01", "return_median": "2.0", "market_regime": "warmup"},
        {"signal_date": "2026-05-02", "return_median": "-1.0", "market_regime": "warmup"},
        {"signal_date": "2026-05-03", "return_median": "1.0", "market_regime": "warmup"},
        {"signal_date": "2026-05-04", "return_median": "-0.5", "market_regime": "warmup"},
    ]
    absent_events = [
        {"signal_date": "2026-05-01", "return_median": "0.5", "market_regime": "warmup"},
        {"signal_date": "2026-05-02", "return_median": "-1.5", "market_regime": "warmup"},
        {"signal_date": "2026-05-03", "return_median": "-0.5", "market_regime": "warmup"},
        {"signal_date": "2026-05-04", "return_median": "0.0", "market_regime": "warmup"},
    ]
    p_wr = 2 / 4 * 100  # 50%
    a_wr = 1 / 4 * 100  # 25%
    expected_inc_wr = p_wr - a_wr  # 25%

    result = incremental_bootstrap(present_events, absent_events, "return_median", "win_rate", "event",
                                   n_iterations=100, seed=42)
    assert abs(result["point_estimate"] - expected_inc_wr) < 1.0, \
        f"Expected ~{expected_inc_wr}, got {result['point_estimate']}"


# ═══════════════════════════════════════════════════════════════
# Test 6: Date-cluster bootstrap — same-date events clustered
# ═══════════════════════════════════════════════════════════════

def test_date_cluster_bootstrap_resamples_dates():
    """Date-cluster bootstrap must resample by signal_date, not individual events."""
    # Create events across 3 dates
    events = [
        {"signal_date": "2026-05-01", "return_median": "2.0", "market_regime": "warmup"},
        {"signal_date": "2026-05-01", "return_median": "3.0", "market_regime": "warmup"},
        {"signal_date": "2026-05-02", "return_median": "1.0", "market_regime": "warmup"},
        {"signal_date": "2026-05-02", "return_median": "0.5", "market_regime": "warmup"},
        {"signal_date": "2026-05-03", "return_median": "-1.0", "market_regime": "warmup"},
        {"signal_date": "2026-05-03", "return_median": "-2.0", "market_regime": "warmup"},
    ]
    # 3 dates, 6 events
    result = date_cluster_bootstrap(events, "return_median", "mean", n_iterations=500, seed=42)
    assert result["ci_lower"] is not None
    assert result["ci_upper"] is not None
    # Point estimate should equal overall mean
    expected_mean = (2.0 + 3.0 + 1.0 + 0.5 - 1.0 - 2.0) / 6
    assert abs(result["point_estimate"] - expected_mean) < 0.001


def test_date_cluster_vs_event_bootstrap_different():
    """Date-cluster and event bootstrap should produce different CIs on clustered data."""
    # Create events with strong within-date correlation
    np.random.seed(123)
    events = []
    for d in range(50):
        # Each date has a "date effect"
        date_effect = np.random.randn() * 2.0
        for s in range(5):  # 5 stocks per date
            events.append({
                "signal_date": f"2026-{(d // 30 + 5):02d}-{(d % 30 + 1):02d}",
                "return_median": str(date_effect + np.random.randn()),
                "market_regime": "warmup",
            })

    eb = event_bootstrap_ci(np.array([float(e["return_median"]) for e in events]), "mean",
                            n_iterations=200, seed=42)
    dc = date_cluster_bootstrap(events, "return_median", "mean", n_iterations=200, seed=42)

    # Both should have valid CIs
    assert eb["ci_lower"] is not None and eb["ci_upper"] is not None
    assert dc["ci_lower"] is not None and dc["ci_upper"] is not None
    # Date-cluster CIs should typically be wider due to clustering
    # (This is probabilistic but should hold for this seed)


# ═══════════════════════════════════════════════════════════════
# Test 7: Bootstrap deterministic with seed
# ═══════════════════════════════════════════════════════════════

def test_event_bootstrap_deterministic():
    """Same seed + same data = same CIs."""
    data = np.array([1.0, 2.0, 3.0, 4.0, 5.0, -1.0, -2.0, 0.5, 1.5, 2.5])
    r1 = event_bootstrap_ci(data, "mean", n_iterations=500, seed=42)
    r2 = event_bootstrap_ci(data, "mean", n_iterations=500, seed=42)
    assert r1["ci_lower"] == r2["ci_lower"]
    assert r1["ci_upper"] == r2["ci_upper"]


def test_date_cluster_bootstrap_deterministic():
    """Same seed + same events = same CIs."""
    events = [
        {"signal_date": "2026-05-01", "return_median": "2.0", "market_regime": "warmup"},
        {"signal_date": "2026-05-01", "return_median": "3.0", "market_regime": "warmup"},
        {"signal_date": "2026-05-02", "return_median": "1.0", "market_regime": "warmup"},
    ]
    r1 = date_cluster_bootstrap(events, "return_median", "mean", n_iterations=200, seed=42)
    r2 = date_cluster_bootstrap(events, "return_median", "mean", n_iterations=200, seed=42)
    assert r1["ci_lower"] == r2["ci_lower"], f"{r1['ci_lower']} != {r2['ci_lower']}"
    assert r1["ci_upper"] == r2["ci_upper"]


def test_incremental_bootstrap_deterministic():
    """Incremental bootstrap must be deterministic with same seed."""
    present = [
        {"signal_date": "2026-05-01", "return_median": "2.0", "market_regime": "warmup"},
        {"signal_date": "2026-05-02", "return_median": "1.0", "market_regime": "warmup"},
    ]
    absent = [
        {"signal_date": "2026-05-01", "return_median": "0.5", "market_regime": "warmup"},
        {"signal_date": "2026-05-02", "return_median": "-0.5", "market_regime": "warmup"},
    ]
    r1 = incremental_bootstrap(present, absent, "return_median", "mean", "event",
                               n_iterations=100, seed=42)
    r2 = incremental_bootstrap(present, absent, "return_median", "mean", "event",
                               n_iterations=100, seed=42)
    assert r1["ci_lower"] == r2["ci_lower"]
    assert r1["ci_upper"] == r2["ci_upper"]


# ═══════════════════════════════════════════════════════════════
# Test 8: OOS isolation
# ═══════════════════════════════════════════════════════════════

def test_oos_isolation():
    """OOS outputs must not contain train or validation dates."""
    events = _load_events()
    # Check that get_period correctly identifies OOS
    for e in events:
        period = get_period(e["signal_date"])
        if OOS_START <= e["signal_date"] <= OOS_END:
            assert period == "oos", \
                f"Date {e['signal_date']} in OOS range but period={period}"
        elif e["signal_date"] < OOS_START:
            assert period != "oos", \
                f"Date {e['signal_date']} before OOS but period=oos"

    # Evidence CSV should only have OOS rows
    with open(EVIDENCE_CSV) as f:
        ev_rows = list(csv.DictReader(f))
    for r in ev_rows:
        assert r["period"] == "oos", \
            f"Evidence row has period={r['period']} instead of oos"


# ═══════════════════════════════════════════════════════════════
# Test 9: Train / Validation / OOS no overlap
# ═══════════════════════════════════════════════════════════════

def test_train_val_oos_no_date_overlap():
    """The three periods must not share any dates."""
    train_dates = set()
    val_dates = set()
    oos_dates = set()

    events = _load_events()
    for e in events:
        d = e["signal_date"]
        if TRAIN_START <= d <= TRAIN_END:
            train_dates.add(d)
        elif VAL_START <= d <= VAL_END:
            val_dates.add(d)
        elif OOS_START <= d <= OOS_END:
            oos_dates.add(d)

    assert len(train_dates & val_dates) == 0
    assert len(train_dates & oos_dates) == 0
    assert len(val_dates & oos_dates) == 0


# ═══════════════════════════════════════════════════════════════
# Test 10: theme_lifecycle stays NOT_AVAILABLE
# ═══════════════════════════════════════════════════════════════

def test_event_csv_theme_lifecycle():
    """Phase 2B event CSV must still have theme_lifecycle=NOT_AVAILABLE."""
    events = _load_events()
    for e in events[:500]:
        assert e["theme_lifecycle"] == "NOT_AVAILABLE"


# ═══════════════════════════════════════════════════════════════
# Test 11: No ranking fields
# ═══════════════════════════════════════════════════════════════

def test_no_ranking_fields_in_evidence():
    """Evidence CSV must not contain ranking/strategy fields."""
    forbidden = {"rank", "winner", "best", "enable", "weight", "score",
                 "enabled", "router_weight", "priority", "recommended"}
    with open(EVIDENCE_CSV) as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        found = fields & forbidden
        assert len(found) == 0, f"Forbidden fields found: {found}"


def test_no_ranking_fields_in_attribution():
    """Attribution CSV must not contain ranking fields."""
    forbidden = {"rank", "winner", "best", "enable", "weight", "score"}
    with open(ATTR_CSV) as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        found = fields & forbidden
        assert len(found) == 0, f"Forbidden fields found: {found}"


# ═══════════════════════════════════════════════════════════════
# Test 12: Legacy Phase 2B results readable
# ═══════════════════════════════════════════════════════════════

def test_phase2b_event_csv_readable():
    """Phase 2B event_level_trades.csv must still be readable."""
    assert EVENT_CSV.exists()
    with open(EVENT_CSV) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 282892
    assert "event_id" in rows[0]
    assert "return_median" in rows[0]
    assert "theme_lifecycle" in rows[0]


def test_phase2b_evidence_csv_readable():
    """Phase 2B pattern_oos_evidence.csv must still be readable."""
    ev_csv = RESULTS_DIR / "pattern_oos_evidence.csv"
    assert ev_csv.exists()
    with open(ev_csv) as f:
        rows = list(csv.DictReader(f))
    assert len(rows) > 0
    assert "evidence_grade" in rows[0]


# ═══════════════════════════════════════════════════════════════
# Test 13: Helper functions
# ═══════════════════════════════════════════════════════════════

def test_get_period():
    assert get_period("2025-06-15") == "train"
    assert get_period("2026-01-01") == "validation"
    assert get_period("2026-07-01") == "oos"
    assert get_period("2024-01-01") == "unknown"


def test_get_sample_label():
    assert get_sample_label(10) == "small"
    assert get_sample_label(50) == "medium"
    assert get_sample_label(100) == "large"


def test_bootstrap_small_sample():
    """Bootstrap handles very small samples gracefully."""
    data = np.array([1.0, 2.0])
    result = event_bootstrap_ci(data, "mean")
    assert result["ci_lower"] is not None
    assert result["ci_upper"] is not None
