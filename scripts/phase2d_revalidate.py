"""Phase 2D — Frozen Candidate Independent OOS Re-validation.

Re-validates Phase 2C's 21 QUALIFIED candidates on a new independent time window
(2025-04-01 ~ 2025-10-01) that did not participate in Phase 2C candidate selection.

Hard freeze:
  - 21 candidates from Phase 2C: frozen, no modification
  - Pattern logic, Regime logic, SellRules: frozen
  - Date-cluster bootstrap: same methodology (RandomState(42), 1000 iter, 95% CI)
  - No re-ranking, no re-qualification, no candidate replacement
"""

import csv
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
EVENT_CSV = RESULTS_DIR / "event_level_trades.csv"
CANDIDATE_CSV = RESULTS_DIR / "phase2c_candidate_table.csv"

# Phase 2D validation window — independent from Phase 2C OOS (2026-04-01~2026-10-01)
PHASE2D_START = "2025-04-01"
PHASE2D_END = "2025-10-01"

BOOTSTRAP_ITERATIONS = 1000
BOOTSTRAP_CONFIDENCE = 0.95
BOOTSTRAP_SEED = 42


# ═══════════════════════════════════════════════════════════════
# Bootstrap (same methodology as Phase 2B.1/2C)
# ═══════════════════════════════════════════════════════════════

def date_cluster_bootstrap(
    events: list[dict],
    value_key: str = "return_median",
    statistic: str = "mean",
    n_iterations: int = BOOTSTRAP_ITERATIONS,
    confidence: float = BOOTSTRAP_CONFIDENCE,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """Date-cluster bootstrap: resample by signal_date."""
    date_groups: dict[str, list[float]] = defaultdict(list)
    for e in events:
        date_groups[e["signal_date"]].append(float(e[value_key]))

    unique_dates = sorted(date_groups.keys())
    n_dates = len(unique_dates)
    if n_dates < 2:
        all_values = np.array([float(e[value_key]) for e in events])
        if len(all_values) < 2:
            return {"ci_lower": None, "ci_upper": None,
                    "point_estimate": float(np.mean(all_values)) if len(all_values) > 0 else None}
        # Fall back to event bootstrap for single-date case
        rng = np.random.RandomState(seed)
        estimates = np.empty(n_iterations)
        for i in range(n_iterations):
            estimates[i] = np.mean(rng.choice(all_values, size=len(all_values), replace=True))
        alpha = (1 - confidence) / 2
        return {
            "ci_lower": round(float(np.percentile(estimates, alpha * 100)), 4),
            "ci_upper": round(float(np.percentile(estimates, (1 - alpha) * 100)), 4),
            "point_estimate": round(float(np.mean(all_values)), 4),
        }

    rng = np.random.RandomState(seed)
    estimates = np.empty(n_iterations)

    if statistic == "mean":
        for i in range(n_iterations):
            sampled_dates = rng.choice(unique_dates, size=n_dates, replace=True)
            sampled_values = []
            for d in sampled_dates:
                sampled_values.extend(date_groups[d])
            estimates[i] = np.mean(sampled_values)
    elif statistic == "win_rate":
        for i in range(n_iterations):
            sampled_dates = rng.choice(unique_dates, size=n_dates, replace=True)
            sampled_values = []
            for d in sampled_dates:
                sampled_values.extend(date_groups[d])
            estimates[i] = np.mean(np.array(sampled_values) > 0) * 100
    elif statistic == "median":
        for i in range(n_iterations):
            sampled_dates = rng.choice(unique_dates, size=n_dates, replace=True)
            sampled_values = []
            for d in sampled_dates:
                sampled_values.extend(date_groups[d])
            estimates[i] = np.median(sampled_values)
    else:
        raise ValueError(f"Unknown statistic: {statistic}")

    alpha = (1 - confidence) / 2
    all_values = np.array([float(e[value_key]) for e in events])
    if statistic == "mean":
        point = float(np.mean(all_values))
    elif statistic == "median":
        point = float(np.median(all_values))
    elif statistic == "win_rate":
        point = float(np.mean(all_values > 0) * 100)
    else:
        point = None

    return {
        "ci_lower": round(float(np.percentile(estimates, alpha * 100)), 4),
        "ci_upper": round(float(np.percentile(estimates, (1 - alpha) * 100)), 4),
        "point_estimate": round(point, 4) if point is not None else None,
    }


# ═══════════════════════════════════════════════════════════════
# Frozen Candidate Loading
# ═══════════════════════════════════════════════════════════════

def load_frozen_candidates() -> list[dict]:
    """Load the 21 QUALIFIED candidates from Phase 2C."""
    with open(CANDIDATE_CSV) as f:
        rows = list(csv.DictReader(f))
    frozen = [r for r in rows if r["candidate_status"] == "QUALIFIED"]
    return frozen


# ═══════════════════════════════════════════════════════════════
# Re-validation
# ═══════════════════════════════════════════════════════════════

def compute_revalidation(
    frozen: list[dict],
    events: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Re-validate each frozen candidate on the Phase 2D window."""

    # Filter events to Phase 2D window
    window_events = [e for e in events
                     if PHASE2D_START <= e["signal_date"] <= PHASE2D_END]

    reval_rows = []
    stability_rows = []
    regime_summary: dict[str, dict] = defaultdict(lambda: {
        "frozen": 0, "revalidated": 0, "uncertain": 0,
        "failed": 0, "low_date_count": 0, "not_observed": 0,
    })

    for c in frozen:
        pat = c["pattern_name"]
        reg = c["regime"]
        prof = c["profile_name"]

        # Phase 2C metrics
        p2c_n = int(c["oos_events"])
        p2c_dates = int(c["oos_dates"])
        p2c_mean = float(c["mean_return"])
        p2c_median = float(c["median_return"])
        p2c_wr = float(c["win_rate"])
        p2c_ci_lo = float(c["date_cluster_mean_ci_low"]) if c["date_cluster_mean_ci_low"] else None
        p2c_ci_hi = float(c["date_cluster_mean_ci_high"]) if c["date_cluster_mean_ci_high"] else None

        # Find events in Phase 2D window for this (pattern, regime)
        regime_events = [e for e in window_events if e["market_regime"] == reg]
        present = []
        for e in regime_events:
            event_pats = set(p.strip() for p in e["patterns"].split("|"))
            if pat in event_pats:
                present.append(e)

        p2d_n = len(present)
        p2d_dates = len(set(e["signal_date"] for e in present))

        regime_summary[reg]["frozen"] += 1

        if p2d_n == 0:
            # NOT_OBSERVED
            status = "NOT_OBSERVED"
            regime_summary[reg]["not_observed"] += 1
            reval_rows.append({
                "regime": reg, "profile_name": prof, "pattern_name": pat,
                "phase2c_events": p2c_n, "phase2c_dates": p2c_dates,
                "phase2c_mean": round(p2c_mean, 4),
                "phase2c_median": round(p2c_median, 4),
                "phase2c_win_rate": round(p2c_wr, 2),
                "phase2c_ci_low": p2c_ci_lo, "phase2c_ci_high": p2c_ci_hi,
                "phase2d_events": 0, "phase2d_dates": 0,
                "phase2d_mean": None, "phase2d_median": None,
                "phase2d_win_rate": None,
                "phase2d_ci_low": None, "phase2d_ci_high": None,
                "mean_return_delta": None, "median_return_delta": None,
                "win_rate_delta": None,
                "revalidation_status": status,
                "single_events": 0, "multi_events": 0,
            })
            stability_rows.append({
                "regime": reg, "profile_name": prof, "pattern_name": pat,
                "phase2c_direction": "POSITIVE" if p2c_mean > 0 else "NEGATIVE",
                "phase2d_direction": "NOT_OBSERVED",
                "phase2c_ci_positive": "YES" if (p2c_ci_lo and p2c_ci_lo > 0) else "NO",
                "phase2d_ci_positive": "NOT_OBSERVED",
                "stability": "NOT_OBSERVED",
            })
            continue

        # Compute Phase 2D metrics
        rets = [float(e["return_median"]) for e in present]
        p2d_mean = statistics.mean(rets)
        p2d_median = statistics.median(rets)
        p2d_wr = sum(1 for r in rets if r > 0) / len(rets) * 100

        # Date-cluster bootstrap
        dc_mean = date_cluster_bootstrap(present, "return_median", "mean")
        p2d_ci_lo = dc_mean["ci_lower"]
        p2d_ci_hi = dc_mean["ci_upper"]

        # Single vs multi composition
        single_n = sum(1 for e in present if int(e["pattern_count"]) == 1)
        multi_n = sum(1 for e in present if int(e["pattern_count"]) > 1)

        # Determine revalidation status
        if p2d_dates < 10:
            status = "LOW_DATE_COUNT"
            regime_summary[reg]["low_date_count"] += 1
        elif p2d_mean > 0 and p2d_median > 0 and p2d_ci_lo is not None and p2d_ci_lo > 0:
            status = "REVALIDATED"
            regime_summary[reg]["revalidated"] += 1
        elif p2d_mean > 0:
            status = "REVALIDATION_UNCERTAIN"
            regime_summary[reg]["uncertain"] += 1
        else:
            status = "REVALIDATION_FAIL"
            regime_summary[reg]["failed"] += 1

        # Deltas
        mean_delta = round(p2d_mean - p2c_mean, 4)
        median_delta = round(p2d_median - p2c_median, 4)
        wr_delta = round(p2d_wr - p2c_wr, 2)

        reval_rows.append({
            "regime": reg, "profile_name": prof, "pattern_name": pat,
            "phase2c_events": p2c_n, "phase2c_dates": p2c_dates,
            "phase2c_mean": round(p2c_mean, 4),
            "phase2c_median": round(p2c_median, 4),
            "phase2c_win_rate": round(p2c_wr, 2),
            "phase2c_ci_low": p2c_ci_lo, "phase2c_ci_high": p2c_ci_hi,
            "phase2d_events": p2d_n, "phase2d_dates": p2d_dates,
            "phase2d_mean": round(p2d_mean, 4),
            "phase2d_median": round(p2d_median, 4),
            "phase2d_win_rate": round(p2d_wr, 2),
            "phase2d_ci_low": p2d_ci_lo, "phase2d_ci_high": p2d_ci_hi,
            "mean_return_delta": mean_delta,
            "median_return_delta": median_delta,
            "win_rate_delta": wr_delta,
            "revalidation_status": status,
            "single_events": single_n, "multi_events": multi_n,
        })

        # Stability row
        p2c_dir = "POSITIVE" if p2c_mean > 0 else "NEGATIVE"
        p2d_dir = "POSITIVE" if p2d_mean > 0 else "NEGATIVE"
        p2c_ci_pos = "YES" if (p2c_ci_lo is not None and p2c_ci_lo > 0) else "NO"
        p2d_ci_pos = "YES" if (p2d_ci_lo is not None and p2d_ci_lo > 0) else "NO"

        if p2c_dir == "POSITIVE" and p2d_dir == "POSITIVE" and p2c_ci_pos == "YES" and p2d_ci_pos == "YES":
            stability = "CONSISTENT_POSITIVE"
        elif p2c_dir == "POSITIVE" and p2d_dir == "POSITIVE":
            stability = "POSITIVE_TO_UNCERTAIN"
        elif p2c_dir == "POSITIVE" and p2d_dir == "NEGATIVE":
            stability = "POSITIVE_TO_NEGATIVE"
        else:
            stability = "INSUFFICIENT"

        stability_rows.append({
            "regime": reg, "profile_name": prof, "pattern_name": pat,
            "phase2c_direction": p2c_dir,
            "phase2d_direction": p2d_dir,
            "phase2c_ci_positive": p2c_ci_pos,
            "phase2d_ci_positive": p2d_ci_pos,
            "stability": stability,
        })

    # Build regime summary
    summary_rows = []
    for regime in ["warmup", "hot", "cooldown", "ice", "euphoria"]:
        if regime in regime_summary:
            s = regime_summary[regime]
            summary_rows.append({
                "regime": regime,
                "frozen_candidates": s["frozen"],
                "revalidated": s["revalidated"],
                "uncertain": s["uncertain"],
                "failed": s["failed"],
                "low_date_count": s["low_date_count"],
                "not_observed": s["not_observed"],
            })

    # OVERALL
    totals = {k: sum(s[k] for s in regime_summary.values())
              for k in ["frozen", "revalidated", "uncertain", "failed", "low_date_count", "not_observed"]}
    summary_rows.append({"regime": "OVERALL", **{f"{k}_candidates" if k == "frozen" else k: v
                         for k, v in totals.items()}})
    # Fix key name
    summary_rows[-1] = {
        "regime": "OVERALL",
        "frozen_candidates": totals["frozen"],
        "revalidated": totals["revalidated"],
        "uncertain": totals["uncertain"],
        "failed": totals["failed"],
        "low_date_count": totals["low_date_count"],
        "not_observed": totals["not_observed"],
    }

    return reval_rows, summary_rows, stability_rows


# ═══════════════════════════════════════════════════════════════
# Frozen Candidate Export
# ═══════════════════════════════════════════════════════════════

def write_frozen_candidates(frozen: list[dict]):
    fields = [
        "regime", "profile_name", "pattern_name",
        "phase2c_events", "phase2c_dates",
        "phase2c_mean", "phase2c_median", "phase2c_win_rate",
        "phase2c_ci_low", "phase2c_ci_high",
        "freeze_commit", "freeze_source",
    ]
    path = RESULTS_DIR / "phase2d_frozen_candidates.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for c in frozen:
            row = {k: c.get(k.replace("phase2c_", "").replace("_ci_", "_date_cluster_mean_ci_"), c.get(k))
                   for k in fields}
            # Remap from Phase 2C column names
            row["phase2c_events"] = c["oos_events"]
            row["phase2c_dates"] = c["oos_dates"]
            row["phase2c_mean"] = c["mean_return"]
            row["phase2c_median"] = c["median_return"]
            row["phase2c_win_rate"] = c["win_rate"]
            row["phase2c_ci_low"] = c["date_cluster_mean_ci_low"]
            row["phase2c_ci_high"] = c["date_cluster_mean_ci_high"]
            row["freeze_commit"] = "b22698c"
            row["freeze_source"] = "phase2c_candidate_table.csv"
            w.writerow(row)
    print(f"Saved: {path} ({len(frozen)} rows)")


# ═══════════════════════════════════════════════════════════════
# CSV Writers
# ═══════════════════════════════════════════════════════════════

def write_revalidation(rows: list[dict]):
    fields = [
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
    path = RESULTS_DIR / "phase2d_revalidation.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    print(f"Saved: {path} ({len(rows)} rows)")


def write_summary(rows: list[dict]):
    fields = [
        "regime", "frozen_candidates", "revalidated",
        "uncertain", "failed", "low_date_count", "not_observed",
    ]
    path = RESULTS_DIR / "phase2d_summary.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    print(f"Saved: {path} ({len(rows)} rows)")


def write_stability(rows: list[dict]):
    fields = [
        "regime", "profile_name", "pattern_name",
        "phase2c_direction", "phase2d_direction",
        "phase2c_ci_positive", "phase2d_ci_positive",
        "stability",
    ]
    path = RESULTS_DIR / "phase2d_stability_matrix.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    print(f"Saved: {path} ({len(rows)} rows)")


# ═══════════════════════════════════════════════════════════════
# Print Summary
# ═══════════════════════════════════════════════════════════════

def print_summary(reval_rows, summary_rows, stability_rows, window_dates):
    from collections import Counter

    print(f"\n{'=' * 70}")
    print("PHASE 2D — FROZEN CANDIDATE INDEPENDENT OOS RE-VALIDATION")
    print(f"{'=' * 70}")

    print(f"\n  Validation window: {PHASE2D_START} ~ {PHASE2D_END}")
    print(f"  Unique dates: {len(window_dates)}")
    print(f"  Frozen candidates: 21 (from Phase 2C commit b22698c)")

    # Summary
    print(f"\n{'─' * 70}")
    print("Revalidation Summary")
    print(f"{'─' * 70}")
    for s in summary_rows:
        print(f"  {s['regime']:10s}: frozen={s['frozen_candidates']} "
              f"REVALIDATED={s['revalidated']} UNCERTAIN={s['uncertain']} "
              f"FAIL={s['failed']} LDC={s['low_date_count']} NOBS={s['not_observed']}")

    # Revalidated
    rev = [r for r in reval_rows if r["revalidation_status"] == "REVALIDATED"]
    print(f"\n{'─' * 70}")
    print(f"REVALIDATED ({len(rev)})")
    print(f"{'─' * 70}")
    if rev:
        for r in sorted(rev, key=lambda r: -r["phase2d_events"]):
            dc = f"[{r['phase2d_ci_low']:+.2f}, {r['phase2d_ci_high']:+.2f}]" if r['phase2d_ci_low'] is not None else "N/A"
            p2c_dc = f"[{r['phase2c_ci_low']:+.2f}, {r['phase2c_ci_high']:+.2f}]" if r['phase2c_ci_low'] is not None else "N/A"
            print(f"  {r['profile_name']:20s}/{r['pattern_name']:20s} {r['regime']:8s}")
            print(f"    P2C: n={r['phase2c_events']:>6,} mean={r['phase2c_mean']:>+7.2f}% wr={r['phase2c_win_rate']:>5.1f}% dc={p2c_dc}")
            print(f"    P2D: n={r['phase2d_events']:>6,} mean={r['phase2d_mean']:>+7.2f}% wr={r['phase2d_win_rate']:>5.1f}% dc={dc}")
    else:
        print("  (none)")

    # Uncertain
    unc = [r for r in reval_rows if r["revalidation_status"] == "REVALIDATION_UNCERTAIN"]
    print(f"\n{'─' * 70}")
    print(f"REVALIDATION_UNCERTAIN ({len(unc)})")
    print(f"{'─' * 70}")
    for r in sorted(unc, key=lambda r: -r["phase2d_events"]):
        dc = f"[{r['phase2d_ci_low']:+.2f}, {r['phase2d_ci_high']:+.2f}]" if r['phase2d_ci_low'] is not None else "N/A"
        print(f"  {r['profile_name']:20s}/{r['pattern_name']:20s} {r['regime']:8s}: "
              f"mean={r['phase2d_mean']:>+7.2f}% dc={dc}")

    # Failed
    fail = [r for r in reval_rows if r["revalidation_status"] == "REVALIDATION_FAIL"]
    print(f"\n{'─' * 70}")
    print(f"REVALIDATION_FAIL ({len(fail)})")
    print(f"{'─' * 70}")
    for r in sorted(fail, key=lambda r: -r["phase2d_events"]):
        print(f"  {r['profile_name']:20s}/{r['pattern_name']:20s} {r['regime']:8s}: "
              f"mean={r['phase2d_mean']:>+7.2f}%")

    # Stability
    stab_counts = Counter(s["stability"] for s in stability_rows)
    print(f"\n{'─' * 70}")
    print("Stability Matrix")
    print(f"{'─' * 70}")
    for status in ["CONSISTENT_POSITIVE", "POSITIVE_TO_UNCERTAIN", "POSITIVE_TO_NEGATIVE",
                    "NOT_OBSERVED", "INSUFFICIENT"]:
        count = stab_counts.get(status, 0)
        if count > 0:
            print(f"  {status}: {count}")

    # Hot regime aggregate
    print(f"\n{'─' * 70}")
    print("Hot Regime Aggregate")
    print(f"{'─' * 70}")
    hot_rows = [r for r in reval_rows if r["regime"] == "hot"]
    hot_rev = [r for r in hot_rows if r["revalidation_status"] == "REVALIDATED"]
    with open(EVENT_CSV) as f:
        all_events = list(csv.DictReader(f))
    hot_win = [e for e in all_events
               if PHASE2D_START <= e["signal_date"] <= PHASE2D_END
               and e["market_regime"] == "hot"]
    if hot_win:
        hot_dc = date_cluster_bootstrap(hot_win, "return_median", "mean")
        print(f"  Phase 2C hot aggregate: dc_ci=[-0.091, +0.985]")
        print(f"  Phase 2D hot aggregate: dc_ci=[{hot_dc['ci_lower']:+.4f}, {hot_dc['ci_upper']:+.4f}]")
        print(f"  Hot REVALIDATED: {len(hot_rev)}/{len(hot_rows)}")

    # Ice regime
    print(f"\n{'─' * 70}")
    print("Ice Regime")
    print(f"{'─' * 70}")
    print("  No ice candidates were QUALIFIED in Phase 2C (all LOW_DATE_COUNT)")
    ice_win = [e for e in all_events
               if PHASE2D_START <= e["signal_date"] <= PHASE2D_END
               and e["market_regime"] == "ice"]
    ice_dates = len(set(e["signal_date"] for e in ice_win))
    print(f"  Phase 2D ice: {len(ice_win)} events, {ice_dates} dates")
    print(f"  Ice remains LOW_DATE_COUNT — insufficient for validation")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    print("Loading frozen candidates from Phase 2C...")
    frozen = load_frozen_candidates()
    print(f"  Loaded {len(frozen)} QUALIFIED candidates")

    write_frozen_candidates(frozen)

    print("\nLoading event-level data...")
    events = list(csv.DictReader(open(EVENT_CSV)))
    print(f"  Loaded {len(events):,} events")

    # Filter to Phase 2D window
    window = [e for e in events if PHASE2D_START <= e["signal_date"] <= PHASE2D_END]
    window_dates = sorted(set(e["signal_date"] for e in window))
    print(f"  Phase 2D window: {len(window):,} events, {len(window_dates)} dates")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print("\nComputing revalidation...")
    reval_rows, summary_rows, stability_rows = compute_revalidation(frozen, events)

    write_revalidation(reval_rows)
    write_summary(summary_rows)
    write_stability(stability_rows)

    print_summary(reval_rows, summary_rows, stability_rows, window_dates)

    # Final status
    status_counts = {}
    for r in reval_rows:
        s = r["revalidation_status"]
        status_counts[s] = status_counts.get(s, 0) + 1

    print(f"\nPHASE 2D STATUS: PASS")
    print(f"  REVALIDATED:          {status_counts.get('REVALIDATED', 0)}")
    print(f"  REVALIDATION_UNCERTAIN: {status_counts.get('REVALIDATION_UNCERTAIN', 0)}")
    print(f"  REVALIDATION_FAIL:    {status_counts.get('REVALIDATION_FAIL', 0)}")
    print(f"  LOW_DATE_COUNT:       {status_counts.get('LOW_DATE_COUNT', 0)}")
    print(f"  NOT_OBSERVED:         {status_counts.get('NOT_OBSERVED', 0)}")


if __name__ == "__main__":
    main()
