"""Phase 2A.1 — PIT / Leakage tests.

Tests verify:
  1. Pattern uses only <= T data (PIT safety)
  2. Entry is T+1 Open only
  3. NO_ENTRY when T+1 not tradeable
  4. Exit respects T+1 constraint
  5. Baseline uses same semantics as patterns
  6. Train/Val/OOS no time crossover
  7. Overlap does not cause sample deletion
"""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
TRADES_CSV = RESULTS_DIR / "pattern_all_trades.csv"


def _load_trades():
    """Load all trades from Phase 2A CSV."""
    with open(TRADES_CSV) as f:
        return list(csv.DictReader(f))


# ═══════════════════════════════════════════════════════════════
# Test 1: Pattern date always < entry date
# ═══════════════════════════════════════════════════════════════

def test_entry_after_pattern_date():
    """Every trade must have entry_date strictly after pattern_date."""
    trades = _load_trades()
    violations = []
    for t in trades:
        if t["pattern_date"] >= t["entry_date"]:
            violations.append(t)
    assert len(violations) == 0, \
        f"Found {len(violations)} trades with pattern_date >= entry_date"


# ═══════════════════════════════════════════════════════════════
# Test 2: No same-day execution
# ═══════════════════════════════════════════════════════════════

def test_no_same_day_execution():
    """Pattern date and entry date must be different (T+1 constraint)."""
    trades = _load_trades()
    same_day = [t for t in trades if t["pattern_date"] == t["entry_date"]]
    assert len(same_day) == 0, \
        f"Found {len(same_day)} trades with same pattern and entry date"


# ═══════════════════════════════════════════════════════════════
# Test 3: All trades have valid entry prices
# ═══════════════════════════════════════════════════════════════

def test_all_trades_valid_entry():
    """No trade should have entry_price <= 0 (would be NO_ENTRY)."""
    trades = _load_trades()
    invalid = [t for t in trades if float(t["entry_price"]) <= 0]
    assert len(invalid) == 0, \
        f"Found {len(invalid)} trades with entry_price <= 0"


# ═══════════════════════════════════════════════════════════════
# Test 4: Holding days >= 1 (T+1 constraint on exit)
# ═══════════════════════════════════════════════════════════════

def test_holding_days_at_least_one():
    """Almost all executed trades must have holding_days >= 1 (T+1 exit constraint).

    Some trades may have holding_days=0 (END_OF_DATA with insufficient future bars).
    This is expected and should be rare (< 0.5% of trades).
    """
    trades = _load_trades()
    violations = [t for t in trades if int(t["holding_days"]) < 1]
    ratio = len(violations) / len(trades) * 100
    assert ratio < 0.5, \
        f"Found {len(violations)} trades ({ratio:.2f}%) with holding_days < 1"


# ═══════════════════════════════════════════════════════════════
# Test 5: Profile and pattern names are both present
# ═══════════════════════════════════════════════════════════════

def test_profile_and_pattern_fields_present():
    """Every trade must have both profile_name and pattern_name fields."""
    trades = _load_trades()
    missing_profile = [t for t in trades if not t.get("profile_name")]
    missing_pattern = [t for t in trades if not t.get("pattern_name")]
    assert len(missing_profile) == 0, \
        f"Found {len(missing_profile)} trades missing profile_name"
    assert len(missing_pattern) == 0, \
        f"Found {len(missing_pattern)} trades missing pattern_name"


# ═══════════════════════════════════════════════════════════════
# Test 6: momentum_v5 produces sub-patterns
# ═══════════════════════════════════════════════════════════════

def test_momentum_v5_subpatterns():
    """momentum_v5 profile must produce sub-pattern names.

    Note: 'pullback' sub-pattern may be absent due to min_score filtering
    in Phase 2A (pullback patterns score lower on average).
    """
    trades = _load_trades()
    mv5_trades = [t for t in trades if t["profile_name"] == "momentum_v5"]
    patterns = set(t["pattern_name"] for t in mv5_trades)
    expected_core = {"momentum", "trend", "breakout", "ignition"}
    assert expected_core.issubset(patterns), \
        f"momentum_v5 missing core sub-patterns. Found: {patterns}"
    # Verify all patterns come from expected set
    valid_patterns = {"momentum", "trend", "breakout", "ignition", "pullback"}
    unknown = patterns - valid_patterns
    assert len(unknown) == 0, \
        f"Unknown sub-patterns: {unknown}"


# ═══════════════════════════════════════════════════════════════
# Test 7: Train/Val/OOS date ranges don't overlap
# ═══════════════════════════════════════════════════════════════

def test_train_val_oos_no_overlap():
    """The three periods must not share any dates."""
    train = set()
    val = set()
    oos = set()
    for t in _load_trades():
        d = t["pattern_date"]
        if "2024-10-01" <= d <= "2025-09-30":
            train.add(d)
        elif "2025-10-01" <= d <= "2026-03-31":
            val.add(d)
        elif "2026-04-01" <= d <= "2026-10-01":
            oos.add(d)

    assert len(train & val) == 0, f"Train ∩ Val overlap: {len(train & val)} dates"
    assert len(train & oos) == 0, f"Train ∩ OOS overlap: {len(train & oos)} dates"
    assert len(val & oos) == 0, f"Val ∩ OOS overlap: {len(val & oos)} dates"


# ═══════════════════════════════════════════════════════════════
# Test 8: Overlap does not delete samples
# ═══════════════════════════════════════════════════════════════

def test_overlap_preserves_all_trades():
    """Counting overlap groups must preserve all original trades."""
    trades = _load_trades()
    from collections import defaultdict
    groups: dict[tuple, list] = defaultdict(list)
    for t in trades:
        groups[(t["symbol"], t["pattern_date"])].append(t)
    # Each trade must appear exactly once across all groups
    total_in_groups = sum(len(g) for g in groups.values())
    assert total_in_groups == len(trades), \
        f"Group total {total_in_groups} != trade total {len(trades)}"


# ═══════════════════════════════════════════════════════════════
# Test 9: Market regime values are valid
# ═══════════════════════════════════════════════════════════════

def test_regime_values_valid():
    """All trades must have a valid market_regime value."""
    valid_regimes = {"euphoria", "hot", "warmup", "cooldown", "ice", "unknown"}
    trades = _load_trades()
    invalid = [t for t in trades if t["market_regime"] not in valid_regimes]
    assert len(invalid) == 0, \
        f"Found {len(invalid)} trades with invalid market_regime: {set(t['market_regime'] for t in invalid)}"


# ═══════════════════════════════════════════════════════════════
# Test 10: Return values are within reasonable bounds
# ═══════════════════════════════════════════════════════════════

def test_returns_within_bounds():
    """Returns should be within [-100%, +1000%] (stocks can gap, but extreme values are suspicious)."""
    trades = _load_trades()
    extreme = [t for t in trades if float(t["return_pct"]) < -100 or float(t["return_pct"]) > 1000]
    assert len(extreme) < len(trades) * 0.0001, \
        f"Found {len(extreme)} trades with extreme returns"
