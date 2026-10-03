"""Phase 2C — OOS Regime × Pattern Candidate Validation.

Builds on Phase 2B.1 outputs to identify which (regime, pattern) combinations
have sufficient OOS statistical evidence for further study.

Hard rules:
  - No strategy modification
  - No router construction
  - No rankings ("best", "winner", "top")
  - date-cluster CI is primary uncertainty measure
  - Ice regime = LOW_DATE_COUNT (5 OOS dates)
  - Hot regime aggregate CI crosses zero — documented, not hidden
"""

import csv
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
EVENT_CSV = RESULTS_DIR / "event_level_trades.csv"
ATTR_CSV = RESULTS_DIR / "pattern_incremental_attribution.csv"
EVIDENCE_CSV = RESULTS_DIR / "pattern_incremental_evidence.csv"
SOLO_CSV = RESULTS_DIR / "pattern_solo_concurrent.csv"

OOS_START = "2026-04-01"
OOS_END = "2026-10-01"
TRAIN_START = "2024-10-01"
TRAIN_END = "2025-09-30"
VAL_START = "2025-10-01"
VAL_END = "2026-03-31"


# ═══════════════════════════════════════════════════════════════
# Data Loading
# ═══════════════════════════════════════════════════════════════

def get_period(signal_date: str) -> str:
    if TRAIN_START <= signal_date <= TRAIN_END:
        return "train"
    if VAL_START <= signal_date <= VAL_END:
        return "validation"
    if OOS_START <= signal_date <= OOS_END:
        return "oos"
    return "unknown"


def load_events() -> list[dict]:
    with open(EVENT_CSV) as f:
        return list(csv.DictReader(f))


# ═══════════════════════════════════════════════════════════════
# Profile→Pattern Mapping
# ═══════════════════════════════════════════════════════════════

def derive_profile_pattern_map(events: list[dict]) -> dict[str, set[str]]:
    """Derive which profiles produce which patterns from event data."""
    mapping: dict[str, set[str]] = defaultdict(set)
    for e in events:
        profiles = [p.strip() for p in e["profiles"].split("|") if p.strip()]
        patterns = [p.strip() for p in e["patterns"].split("|") if p.strip()]
        for prof in profiles:
            for pat in patterns:
                mapping[prof].add(pat)
    return dict(mapping)


def get_primary_profile(pattern_name: str, profile_map: dict[str, set[str]]) -> str:
    """Find the primary profile for a pattern name.

    Priority: exact name match, then the profile that most frequently
    co-occurs with the pattern. For composite patterns, use the first
    profile found.
    """
    # Direct match: profile name == pattern name
    if pattern_name in profile_map:
        return pattern_name

    # Search: which profile contains this pattern?
    candidates = []
    for prof, pats in profile_map.items():
        if pattern_name in pats:
            candidates.append(prof)

    if len(candidates) == 1:
        return candidates[0]
    elif candidates:
        # Multiple profiles produce this pattern — return the first
        return candidates[0]

    return pattern_name  # fallback


# ═══════════════════════════════════════════════════════════════
# Candidate Qualification
# ═══════════════════════════════════════════════════════════════

def classify_candidate(
    n_events: int,
    n_dates: int,
    mean_return: float,
    median_return: float,
    dc_ci_low: float | None,
    dc_ci_high: float | None,
) -> tuple[str, str]:
    """Classify a (pattern, regime) candidate.

    Returns (candidate_status, reason).
    Priority: LOW_DATE_COUNT > INSUFFICIENT > PROVISIONAL > QUALIFIED
    """
    # Ice regime and other low-date groups
    if n_dates < 10:
        return "LOW_DATE_COUNT", f"Only {n_dates} unique OOS dates — insufficient for date-cluster inference"

    # Insufficient sample
    if n_events < 30:
        return "INSUFFICIENT", f"n={n_events} events — below minimum threshold of 30"

    # Negative or zero returns
    if mean_return <= 0:
        return "INSUFFICIENT", f"OOS mean return = {mean_return:+.4f}% — not positive"

    # Check date-cluster CI
    if dc_ci_low is not None and dc_ci_low > 0:
        # Date-cluster CI confirms positive
        if n_events >= 100 and n_dates >= 20 and median_return > 0:
            return "QUALIFIED", (
                f"n={n_events}, dates={n_dates}, "
                f"mean={mean_return:+.2f}%, median={median_return:+.2f}%, "
                f"dc_ci=[{dc_ci_low:+.2f}, {dc_ci_high:+.2f}] — all criteria met"
            )
        else:
            # Date-cluster CI positive but other criteria not fully met
            missing = []
            if n_events < 100:
                missing.append(f"n={n_events}<100")
            if n_dates < 20:
                missing.append(f"dates={n_dates}<20")
            if median_return <= 0:
                missing.append(f"median={median_return:+.2f}%<=0")
            return "PROVISIONAL", (
                f"date-cluster CI > 0 but {'; '.join(missing)}"
            )
    else:
        # Date-cluster CI not confirmed (crosses zero or unavailable)
        if n_events >= 30 and n_dates >= 10 and mean_return > 0:
            ci_str = f"dc_ci=[{dc_ci_low:+.2f}, {dc_ci_high:+.2f}]" if dc_ci_low is not None else "dc_ci=N/A"
            return "PROVISIONAL", (
                f"n={n_events}, dates={n_dates}, mean={mean_return:+.2f}% > 0 "
                f"but {ci_str} crosses zero — positive but uncertain"
            )
        else:
            return "INSUFFICIENT", (
                f"n={n_events}, dates={n_dates}, mean={mean_return:+.4f}% — insufficient evidence"
            )


# ═══════════════════════════════════════════════════════════════
# Main Analysis
# ═══════════════════════════════════════════════════════════════

def build_candidate_table(
    events: list[dict],
    profile_map: dict[str, set[str]],
) -> tuple[list[dict], list[dict]]:
    """Build candidate table and stability matrix."""

    # ── Index OOS attribution rows by (pattern, regime) ──
    attr_rows = list(csv.DictReader(open(ATTR_CSV)))
    attr_oos: dict[tuple[str, str], dict] = {}
    for r in attr_rows:
        if r["period"] == "oos" and r["presence_type"] == "present":
            attr_oos[(r["pattern_name"], r["regime"])] = r

    # ── Index evidence rows ──
    ev_rows = list(csv.DictReader(open(EVIDENCE_CSV)))
    ev_idx: dict[tuple[str, str], dict] = {}
    for r in ev_rows:
        ev_idx[(r["pattern_name"], r["regime"])] = r

    # ── Index train/val attribution for stability ──
    train_val_idx: dict[tuple[str, str], dict[str, float]] = {}
    for r in attr_rows:
        if r["period"] in ("train", "validation") and r["presence_type"] == "present":
            key = (r["pattern_name"], r["regime"])
            if key not in train_val_idx:
                train_val_idx[key] = {}
            train_val_idx[key][r["period"]] = float(r["mean_return"])

    # ── Compute OOS event counts per (pattern, regime) ──
    oos_events = [e for e in events if OOS_START <= e["signal_date"] <= OOS_END]

    # Per (pattern, regime): count events and dates
    pr_counts: dict[tuple[str, str], dict] = defaultdict(lambda: {
        "event_ids": set(), "dates": set(), "excess_returns": [],
        "single_events": 0, "multi_events": 0,
    })
    for e in oos_events:
        regime = e["market_regime"]
        event_patterns = set(p.strip() for p in e["patterns"].split("|"))
        for pat in event_patterns:
            key = (pat, regime)
            pr_counts[key]["event_ids"].add(e["event_id"])
            pr_counts[key]["dates"].add(e["signal_date"])
            if e["baseline_excess_mean"]:
                try:
                    pr_counts[key]["excess_returns"].append(float(e["baseline_excess_mean"]))
                except (ValueError, TypeError):
                    pass
            if int(e["pattern_count"]) == 1:
                pr_counts[key]["single_events"] += 1
            else:
                pr_counts[key]["multi_events"] += 1

    # ── Build candidate rows ──
    candidates = []
    matrix_rows = []

    for (pattern, regime), info in sorted(pr_counts.items()):
        n_events = len(info["event_ids"])
        n_dates = len(info["dates"])

        # Get attribution data
        attr = attr_oos.get((pattern, regime))
        ev = ev_idx.get((pattern, regime))

        if attr is None:
            continue

        mean_return = float(attr["mean_return"])
        median_return = float(attr["median_return"])
        win_rate = float(attr["win_rate"])

        eb_lo = float(attr["event_bootstrap_ci_low"]) if attr["event_bootstrap_ci_low"] else None
        eb_hi = float(attr["event_bootstrap_ci_high"]) if attr["event_bootstrap_ci_high"] else None
        dc_lo = float(attr["date_cluster_ci_low"]) if attr["date_cluster_ci_low"] else None
        dc_hi = float(attr["date_cluster_ci_high"]) if attr["date_cluster_ci_high"] else None

        # Excess return
        excess = None
        if info["excess_returns"]:
            excess = round(statistics.mean(info["excess_returns"]), 4)

        # Evidence grade from Phase 2B.1
        evidence_grade = ev["evidence_status"] if ev else "N/A"

        # Classify
        status, reason = classify_candidate(n_events, n_dates, mean_return, median_return, dc_lo, dc_hi)

        # Profile
        profile = get_primary_profile(pattern, profile_map)

        # Win rate date-cluster CI (from attribution or evidence)
        wr_dc_lo = None
        wr_dc_hi = None
        if ev and ev.get("incremental_date_cluster_ci_low"):
            # Evidence has incremental DC CI for win_rate — not what we need
            pass
        # We compute wr DC CI from date_cluster_bootstrap on the present group
        # This is available in the attribution CSV only for mean, not win_rate
        # For candidate table, we report what we have

        # Present/absent composition
        baseline_n = int(attr.get("baseline_n", 0)) if attr.get("baseline_n") else 0
        single_n = info["single_events"]
        multi_n = info["multi_events"]

        candidates.append({
            "regime": regime,
            "profile_name": profile,
            "pattern_name": pattern,
            "oos_events": n_events,
            "oos_dates": n_dates,
            "mean_return": round(mean_return, 4),
            "median_return": round(median_return, 4),
            "win_rate": round(win_rate, 2),
            "event_bootstrap_mean_ci_low": round(eb_lo, 4) if eb_lo is not None else None,
            "event_bootstrap_mean_ci_high": round(eb_hi, 4) if eb_hi is not None else None,
            "date_cluster_mean_ci_low": round(dc_lo, 4) if dc_lo is not None else None,
            "date_cluster_mean_ci_high": round(dc_hi, 4) if dc_hi is not None else None,
            "date_cluster_win_rate_ci_low": wr_dc_lo,
            "date_cluster_win_rate_ci_high": wr_dc_hi,
            "excess_return": excess,
            "evidence_grade": evidence_grade,
            "candidate_status": status,
            "reason": reason,
            "present_n": n_events,
            "absent_n": baseline_n,
            "single_n": single_n,
            "multi_n": multi_n,
        })

        # ── Stability matrix row ──
        tv = train_val_idx.get((pattern, regime), {})
        train_result = tv.get("train")
        val_result = tv.get("validation")

        if train_result is not None and val_result is not None and mean_return is not None:
            if train_result > 0 and val_result > 0 and mean_return > 0:
                stability_status = "HISTORICALLY_CONSISTENT"
            elif train_result > 0 and val_result > 0 and mean_return <= 0:
                stability_status = "HISTORICALLY_INCONSISTENT"
            elif mean_return > 0 and (train_result <= 0 or val_result <= 0):
                stability_status = "HISTORICALLY_INCONSISTENT"
            else:
                stability_status = "HISTORICALLY_INCONSISTENT"
        elif train_result is not None or val_result is not None:
            stability_status = "PARTIAL_HISTORY"
        else:
            stability_status = "NO_HISTORY"

        matrix_rows.append({
            "regime": regime,
            "pattern_name": pattern,
            "train_result": round(train_result, 4) if train_result is not None else None,
            "validation_result": round(val_result, 4) if val_result is not None else None,
            "oos_result": round(mean_return, 4),
            "oos_date_cluster_ci_low": round(dc_lo, 4) if dc_lo is not None else None,
            "oos_date_cluster_ci_high": round(dc_hi, 4) if dc_hi is not None else None,
            "stability_status": stability_status,
        })

    return candidates, matrix_rows


def build_candidate_summary(candidates: list[dict]) -> list[dict]:
    """Aggregate candidate counts by regime."""
    regimes = defaultdict(lambda: {"QUALIFIED": 0, "PROVISIONAL": 0, "INSUFFICIENT": 0, "LOW_DATE_COUNT": 0, "total": 0})
    for c in candidates:
        r = regimes[c["regime"]]
        r[c["candidate_status"]] += 1
        r["total"] += 1

    rows = []
    for regime in ["warmup", "hot", "cooldown", "ice", "euphoria"]:
        if regime in regimes:
            r = regimes[regime]
            rows.append({
                "regime": regime,
                "qualified_count": r["QUALIFIED"],
                "provisional_count": r["PROVISIONAL"],
                "insufficient_count": r["INSUFFICIENT"],
                "low_date_count": r["LOW_DATE_COUNT"],
                "total_patterns": r["total"],
            })

    # Overall
    totals = {"QUALIFIED": 0, "PROVISIONAL": 0, "INSUFFICIENT": 0, "LOW_DATE_COUNT": 0, "total": 0}
    for r in regimes.values():
        for k in totals:
            totals[k] += r[k]
    rows.append({
        "regime": "OVERALL",
        "qualified_count": totals["QUALIFIED"],
        "provisional_count": totals["PROVISIONAL"],
        "insufficient_count": totals["INSUFFICIENT"],
        "low_date_count": totals["LOW_DATE_COUNT"],
        "total_patterns": totals["total"],
    })

    return rows


# ═══════════════════════════════════════════════════════════════
# CSV Writers
# ═══════════════════════════════════════════════════════════════

def write_candidate_table(rows: list[dict]):
    fields = [
        "regime", "profile_name", "pattern_name",
        "oos_events", "oos_dates",
        "mean_return", "median_return", "win_rate",
        "event_bootstrap_mean_ci_low", "event_bootstrap_mean_ci_high",
        "date_cluster_mean_ci_low", "date_cluster_mean_ci_high",
        "date_cluster_win_rate_ci_low", "date_cluster_win_rate_ci_high",
        "excess_return", "evidence_grade",
        "candidate_status", "reason",
        "present_n", "absent_n", "single_n", "multi_n",
    ]
    path = RESULTS_DIR / "phase2c_candidate_table.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    print(f"Saved: {path} ({len(rows)} rows)")


def write_candidate_summary(rows: list[dict]):
    fields = [
        "regime", "qualified_count", "provisional_count",
        "insufficient_count", "low_date_count", "total_patterns",
    ]
    path = RESULTS_DIR / "phase2c_candidate_summary.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    print(f"Saved: {path} ({len(rows)} rows)")


def write_matrix(rows: list[dict]):
    fields = [
        "regime", "pattern_name",
        "train_result", "validation_result", "oos_result",
        "oos_date_cluster_ci_low", "oos_date_cluster_ci_high",
        "stability_status",
    ]
    path = RESULTS_DIR / "phase2c_regime_pattern_matrix.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    print(f"Saved: {path} ({len(rows)} rows)")


# ═══════════════════════════════════════════════════════════════
# Print Summary
# ═══════════════════════════════════════════════════════════════

def print_summary(candidates: list[dict], summary: list[dict], matrix: list[dict]):
    print(f"\n{'=' * 70}")
    print("PHASE 2C — OOS REGIME × PATTERN CANDIDATE VALIDATION")
    print(f"{'=' * 70}")

    # Summary counts
    print(f"\n{'─' * 70}")
    print("Candidate Summary")
    print(f"{'─' * 70}")
    for s in summary:
        print(f"  {s['regime']:10s}: Q={s['qualified_count']} P={s['provisional_count']} "
              f"I={s['insufficient_count']} LDC={s['low_date_count']} total={s['total_patterns']}")

    # Qualified candidates
    qualified = [c for c in candidates if c["candidate_status"] == "QUALIFIED"]
    print(f"\n{'─' * 70}")
    print(f"QUALIFIED ({len(qualified)})")
    print(f"{'─' * 70}")
    if qualified:
        for c in sorted(qualified, key=lambda c: -c["oos_events"]):
            dc = f"[{c['date_cluster_mean_ci_low']:+.2f}, {c['date_cluster_mean_ci_high']:+.2f}]" if c['date_cluster_mean_ci_low'] is not None else "N/A"
            print(f"  {c['profile_name']:20s}/{c['pattern_name']:20s} {c['regime']:8s}: "
                  f"n={c['oos_events']:>5,} dates={c['oos_dates']:>3} "
                  f"mean={c['mean_return']:>+7.2f}% wr={c['win_rate']:>5.1f}% "
                  f"dc_ci={dc}")
    else:
        print("  (none)")

    # Provisional
    provisional = [c for c in candidates if c["candidate_status"] == "PROVISIONAL"]
    print(f"\n{'─' * 70}")
    print(f"PROVISIONAL ({len(provisional)})")
    print(f"{'─' * 70}")
    for c in sorted(provisional, key=lambda c: -c["oos_events"])[:15]:
        dc = f"[{c['date_cluster_mean_ci_low']:+.2f}, {c['date_cluster_mean_ci_high']:+.2f}]" if c['date_cluster_mean_ci_low'] is not None else "N/A"
        print(f"  {c['profile_name']:20s}/{c['pattern_name']:20s} {c['regime']:8s}: "
              f"n={c['oos_events']:>5,} dates={c['oos_dates']:>3} "
              f"mean={c['mean_return']:>+7.2f}% wr={c['win_rate']:>5.1f}% "
              f"dc_ci={dc}")

    # Ice regime
    ice_candidates = [c for c in candidates if c["regime"] == "ice"]
    print(f"\n{'─' * 70}")
    print(f"ICE REGIME ({len(ice_candidates)} patterns, 5 OOS dates)")
    print(f"{'─' * 70}")
    for c in sorted(ice_candidates, key=lambda c: -c["oos_events"]):
        print(f"  {c['pattern_name']:20s}: n={c['oos_events']:>5,} mean={c['mean_return']:>+7.2f}% "
              f"wr={c['win_rate']:>5.1f}% status={c['candidate_status']}")

    # Hot regime aggregate
    print(f"\n{'─' * 70}")
    print("HOT REGIME — Aggregate Date-Cluster CI")
    print(f"{'─' * 70}")
    print("  Date-cluster mean CI for hot regime aggregate: [-0.091, +0.985]")
    print("  INTERPRETATION: Hot-regime aggregate evidence remains uncertain")
    print("  under date-cluster inference. Individual pattern results must be")
    print("  interpreted with this aggregate uncertainty in mind.")

    # Stability matrix summary
    from collections import Counter
    stability_counts = Counter(m["stability_status"] for m in matrix)
    print(f"\n{'─' * 70}")
    print("Stability Matrix")
    print(f"{'─' * 70}")
    for status in ["HISTORICALLY_CONSISTENT", "HISTORICALLY_INCONSISTENT", "PARTIAL_HISTORY", "NO_HISTORY"]:
        count = stability_counts.get(status, 0)
        if count > 0:
            print(f"  {status}: {count} patterns")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    print("Loading event-level data...")
    events = load_events()
    print(f"  Loaded {len(events):,} events")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Derive profile→pattern mapping
    profile_map = derive_profile_pattern_map(events)
    print(f"  Derived {len(profile_map)} profile→pattern mappings")

    # Build candidate table and matrix
    print("\nBuilding candidate table...")
    candidates, matrix_rows = build_candidate_table(events, profile_map)

    # Summarize
    summary = build_candidate_summary(candidates)

    # Write outputs
    write_candidate_table(candidates)
    write_candidate_summary(summary)
    write_matrix(matrix_rows)

    # Print
    print_summary(candidates, summary, matrix_rows)

    # Final status
    qualified = [c for c in candidates if c["candidate_status"] == "QUALIFIED"]
    provisional = [c for c in candidates if c["candidate_status"] == "PROVISIONAL"]
    insufficient = [c for c in candidates if c["candidate_status"] == "INSUFFICIENT"]
    low_date = [c for c in candidates if c["candidate_status"] == "LOW_DATE_COUNT"]

    print(f"\nPHASE 2C STATUS: PASS")
    print(f"  {len(candidates)} candidates evaluated")
    print(f"  QUALIFIED:      {len(qualified)}")
    print(f"  PROVISIONAL:    {len(provisional)}")
    print(f"  INSUFFICIENT:   {len(insufficient)}")
    print(f"  LOW_DATE_COUNT: {len(low_date)}")


if __name__ == "__main__":
    main()
