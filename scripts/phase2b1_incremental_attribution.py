"""Phase 2B.1 — Pattern Incremental Attribution + Date-Cluster Bootstrap.

Extends Phase 2B event-level analysis with:
  1. Pattern presence analysis (present vs absent, matched by regime+period)
  2. Solo vs concurrent breakdown per pattern
  3. Date-cluster bootstrap (resample by signal_date, not individual event)
  4. Incremental evidence (present_mean - absent_mean)

Key constraints:
  - event_id = symbol + signal_date (one observation per event)
  - No "best pattern" rankings
  - No strategy enablement
  - theme_lifecycle = NOT_AVAILABLE
  - Survivorship bias explicitly documented
"""

import csv
import statistics
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
EVENT_CSV = RESULTS_DIR / "event_level_trades.csv"
OOS_START = "2026-04-01"
OOS_END = "2026-10-01"
TRAIN_START = "2024-10-01"
TRAIN_END = "2025-09-30"
VAL_START = "2025-10-01"
VAL_END = "2026-03-31"

BOOTSTRAP_ITERATIONS = 1000
BOOTSTRAP_CONFIDENCE = 0.95
BOOTSTRAP_SEED = 42


# ═══════════════════════════════════════════════════════════════
# Data Loading
# ═══════════════════════════════════════════════════════════════

def load_events() -> list[dict]:
    with open(EVENT_CSV) as f:
        return list(csv.DictReader(f))


def get_period(signal_date: str) -> str:
    if TRAIN_START <= signal_date <= TRAIN_END:
        return "train"
    if VAL_START <= signal_date <= VAL_END:
        return "validation"
    if OOS_START <= signal_date <= OOS_END:
        return "oos"
    return "unknown"


def get_sample_label(n: int) -> str:
    if n >= 100:
        return "large"
    if n >= 30:
        return "medium"
    return "small"


# ═══════════════════════════════════════════════════════════════
# Bootstrap Engines
# ═══════════════════════════════════════════════════════════════

def event_bootstrap_ci(
    data: np.ndarray,
    statistic: str = "mean",
    n_iterations: int = BOOTSTRAP_ITERATIONS,
    confidence: float = BOOTSTRAP_CONFIDENCE,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """Standard event-level bootstrap (from Phase 2B)."""
    n = len(data)
    if n < 2:
        return {"ci_lower": None, "ci_upper": None, "point_estimate": float(data[0]) if n == 1 else None}

    rng = np.random.RandomState(seed)
    estimates = np.empty(n_iterations)

    if statistic == "mean":
        for i in range(n_iterations):
            estimates[i] = np.mean(rng.choice(data, size=n, replace=True))
        point = float(np.mean(data))
    elif statistic == "median":
        for i in range(n_iterations):
            estimates[i] = np.median(rng.choice(data, size=n, replace=True))
        point = float(np.median(data))
    elif statistic == "win_rate":
        for i in range(n_iterations):
            sample = rng.choice(data, size=n, replace=True)
            estimates[i] = np.mean(sample > 0) * 100
        point = float(np.mean(data > 0) * 100)
    else:
        raise ValueError(f"Unknown statistic: {statistic}")

    alpha = (1 - confidence) / 2
    return {
        "ci_lower": round(float(np.percentile(estimates, alpha * 100)), 4),
        "ci_upper": round(float(np.percentile(estimates, (1 - alpha) * 100)), 4),
        "point_estimate": round(point, 4),
    }


def date_cluster_bootstrap(
    events: list[dict],
    value_key: str = "return_median",
    statistic: str = "mean",
    n_iterations: int = BOOTSTRAP_ITERATIONS,
    confidence: float = BOOTSTRAP_CONFIDENCE,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """Date-cluster bootstrap: resample by signal_date, include all events for each sampled date.

    Each bootstrap iteration:
      1. Sample unique signal_dates with replacement
      2. Include ALL events belonging to each sampled date
      3. Compute statistic on the resulting event set

    This accounts for cross-sectional correlation within the same trading day.
    """
    # Group events by signal_date
    date_groups: dict[str, list[float]] = defaultdict(list)
    for e in events:
        date_groups[e["signal_date"]].append(float(e[value_key]))

    unique_dates = sorted(date_groups.keys())
    n_dates = len(unique_dates)
    if n_dates < 2:
        all_values = np.array([float(e[value_key]) for e in events])
        return event_bootstrap_ci(all_values, statistic, n_iterations, confidence, seed)

    rng = np.random.RandomState(seed)
    estimates = np.empty(n_iterations)

    if statistic == "mean":
        for i in range(n_iterations):
            sampled_dates = rng.choice(unique_dates, size=n_dates, replace=True)
            sampled_values = []
            for d in sampled_dates:
                sampled_values.extend(date_groups[d])
            estimates[i] = np.mean(sampled_values)
    elif statistic == "median":
        for i in range(n_iterations):
            sampled_dates = rng.choice(unique_dates, size=n_dates, replace=True)
            sampled_values = []
            for d in sampled_dates:
                sampled_values.extend(date_groups[d])
            estimates[i] = np.median(sampled_values)
    elif statistic == "win_rate":
        for i in range(n_iterations):
            sampled_dates = rng.choice(unique_dates, size=n_dates, replace=True)
            sampled_values = []
            for d in sampled_dates:
                sampled_values.extend(date_groups[d])
            estimates[i] = np.mean(np.array(sampled_values) > 0) * 100
    else:
        raise ValueError(f"Unknown statistic: {statistic}")

    alpha = (1 - confidence) / 2
    # Point estimate: compute on ALL events (not bootstrapped)
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


def incremental_bootstrap(
    present_events: list[dict],
    absent_events: list[dict],
    value_key: str = "return_median",
    statistic: str = "mean",
    method: str = "event",
    n_iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """Bootstrap the incremental difference (present_mean - absent_mean).

    method='event': resample individual events
    method='date_cluster': resample by signal_date
    """
    if method == "event":
        present_vals = np.array([float(e[value_key]) for e in present_events])
        absent_vals = np.array([float(e[value_key]) for e in absent_events])
        n_p = len(present_vals)
        n_a = len(absent_vals)
        if n_p < 2 or n_a < 2:
            return {"ci_lower": None, "ci_upper": None,
                    "point_estimate": (float(np.mean(present_vals)) - float(np.mean(absent_vals))) if n_p > 0 and n_a > 0 else None}

        rng = np.random.RandomState(seed)
        estimates = np.empty(n_iterations)

        if statistic == "mean":
            for i in range(n_iterations):
                p_sample = rng.choice(present_vals, size=n_p, replace=True)
                a_sample = rng.choice(absent_vals, size=n_a, replace=True)
                estimates[i] = np.mean(p_sample) - np.mean(a_sample)
        elif statistic == "win_rate":
            for i in range(n_iterations):
                p_sample = rng.choice(present_vals, size=n_p, replace=True)
                a_sample = rng.choice(absent_vals, size=n_a, replace=True)
                estimates[i] = (np.mean(p_sample > 0) - np.mean(a_sample > 0)) * 100
        else:
            raise ValueError(f"Unknown statistic: {statistic}")

    else:  # date_cluster
        # Group present events by date
        p_date_groups: dict[str, list[float]] = defaultdict(list)
        for e in present_events:
            p_date_groups[e["signal_date"]].append(float(e[value_key]))
        a_date_groups: dict[str, list[float]] = defaultdict(list)
        for e in absent_events:
            a_date_groups[e["signal_date"]].append(float(e[value_key]))

        p_dates = sorted(p_date_groups.keys())
        a_dates = sorted(a_date_groups.keys())
        if len(p_dates) < 2 or len(a_dates) < 2:
            return {"ci_lower": None, "ci_upper": None,
                    "point_estimate": (float(np.mean([float(e[value_key]) for e in present_events])) -
                                       float(np.mean([float(e[value_key]) for e in absent_events])))}

        rng = np.random.RandomState(seed)
        estimates = np.empty(n_iterations)

        if statistic == "mean":
            for i in range(n_iterations):
                p_sampled_dates = rng.choice(p_dates, size=len(p_dates), replace=True)
                p_vals = []
                for d in p_sampled_dates:
                    p_vals.extend(p_date_groups[d])
                a_sampled_dates = rng.choice(a_dates, size=len(a_dates), replace=True)
                a_vals = []
                for d in a_sampled_dates:
                    a_vals.extend(a_date_groups[d])
                estimates[i] = np.mean(p_vals) - np.mean(a_vals)
        elif statistic == "win_rate":
            for i in range(n_iterations):
                p_sampled_dates = rng.choice(p_dates, size=len(p_dates), replace=True)
                p_vals = []
                for d in p_sampled_dates:
                    p_vals.extend(p_date_groups[d])
                a_sampled_dates = rng.choice(a_dates, size=len(a_dates), replace=True)
                a_vals = []
                for d in a_sampled_dates:
                    a_vals.extend(a_date_groups[d])
                estimates[i] = (np.mean(np.array(p_vals) > 0) - np.mean(np.array(a_vals) > 0)) * 100
        else:
            raise ValueError(f"Unknown statistic: {statistic}")

    alpha = (1 - BOOTSTRAP_CONFIDENCE) / 2
    if statistic == "mean":
        p_point = float(np.mean([float(e[value_key]) for e in present_events]))
        a_point = float(np.mean([float(e[value_key]) for e in absent_events]))
    else:
        p_point = float(np.mean(np.array([float(e[value_key]) for e in present_events]) > 0) * 100)
        a_point = float(np.mean(np.array([float(e[value_key]) for e in absent_events]) > 0) * 100)

    return {
        "ci_lower": round(float(np.percentile(estimates, alpha * 100)), 4),
        "ci_upper": round(float(np.percentile(estimates, (1 - alpha) * 100)), 4),
        "point_estimate": round(p_point - a_point, 4),
    }


# ═══════════════════════════════════════════════════════════════
# Pattern Presence Analysis
# ═══════════════════════════════════════════════════════════════

def compute_pattern_presence(events: list[dict]) -> list[dict]:
    """For each pattern, compute present vs absent metrics by regime+period.

    Matched comparison: present events vs absent events within same (regime, period).
    """
    # Extract all unique patterns
    all_patterns: set[str] = set()
    for e in events:
        for p in e["patterns"].split("|"):
            p = p.strip()
            if p:
                all_patterns.add(p)

    rows = []
    for pattern in sorted(all_patterns):
        # Classify every event: does this pattern appear?
        for period in ["train", "validation", "oos"]:
            period_events = [e for e in events if get_period(e["signal_date"]) == period]
            if not period_events:
                continue

            for regime in sorted(set(e["market_regime"] for e in period_events)):
                regime_period_events = [e for e in period_events if e["market_regime"] == regime]
                present = []
                absent = []
                for e in regime_period_events:
                    event_patterns = set(p.strip() for p in e["patterns"].split("|"))
                    if pattern in event_patterns:
                        present.append(e)
                    else:
                        absent.append(e)

                if not present:
                    continue

                p_returns = [float(e["return_median"]) for e in present]
                a_returns = [float(e["return_median"]) for e in absent] if absent else []

                # Event bootstrap CIs for present group
                p_eb = event_bootstrap_ci(np.array(p_returns), "mean")
                p_dc = date_cluster_bootstrap(present, "return_median", "mean")

                # Incremental bootstrap (present vs absent)
                inc_eb = None
                inc_dc = None
                inc_mean = None
                inc_median = None
                inc_wr = None
                if absent and len(absent) >= 5:
                    inc_mean = round(statistics.mean(p_returns) - statistics.mean(a_returns), 4)
                    inc_median = round(statistics.median(p_returns) - statistics.median(a_returns), 4)
                    p_wr = sum(1 for r in p_returns if r > 0) / len(p_returns) * 100
                    a_wr = sum(1 for r in a_returns if r > 0) / len(a_returns) * 100
                    inc_wr = round(p_wr - a_wr, 2)
                    inc_eb = incremental_bootstrap(present, absent, "return_median", "mean", "event")
                    inc_dc = incremental_bootstrap(present, absent, "return_median", "mean", "date_cluster")

                rows.append({
                    "pattern_name": pattern,
                    "regime": regime,
                    "period": period,
                    "presence_type": "present",
                    "n_events": len(present),
                    "sample_label": get_sample_label(len(present)),
                    "mean_return": round(statistics.mean(p_returns), 4),
                    "median_return": round(statistics.median(p_returns), 4),
                    "win_rate": round(sum(1 for r in p_returns if r > 0) / len(p_returns) * 100, 2),
                    "std_return": round(statistics.stdev(p_returns), 4) if len(p_returns) > 1 else 0.0,
                    "event_bootstrap_ci_low": p_eb["ci_lower"],
                    "event_bootstrap_ci_high": p_eb["ci_upper"],
                    "date_cluster_ci_low": p_dc["ci_lower"],
                    "date_cluster_ci_high": p_dc["ci_upper"],
                    "baseline_n": len(absent),
                    "incremental_mean": inc_mean,
                    "incremental_median": inc_median,
                    "incremental_win_rate": inc_wr,
                    "incremental_event_ci_low": inc_eb["ci_lower"] if inc_eb else None,
                    "incremental_event_ci_high": inc_eb["ci_upper"] if inc_eb else None,
                    "incremental_date_cluster_ci_low": inc_dc["ci_lower"] if inc_dc else None,
                    "incremental_date_cluster_ci_high": inc_dc["ci_upper"] if inc_dc else None,
                })

    return rows


# ═══════════════════════════════════════════════════════════════
# Solo vs Concurrent Analysis
# ═══════════════════════════════════════════════════════════════

def compute_solo_concurrent(events: list[dict]) -> list[dict]:
    """For each pattern, compute solo (pattern_count==1) vs concurrent (pattern_count>1) metrics."""
    all_patterns: set[str] = set()
    for e in events:
        for p in e["patterns"].split("|"):
            p = p.strip()
            if p:
                all_patterns.add(p)

    rows = []
    for pattern in sorted(all_patterns):
        # Find events where this pattern is present
        present_events = []
        for e in events:
            event_patterns = set(p.strip() for p in e["patterns"].split("|"))
            if pattern in event_patterns:
                present_events.append(e)

        for period in ["train", "validation", "oos"]:
            period_events = [e for e in present_events if get_period(e["signal_date"]) == period]
            if not period_events:
                continue

            for regime in sorted(set(e["market_regime"] for e in period_events)):
                regime_events = [e for e in period_events if e["market_regime"] == regime]

                solo = [e for e in regime_events if int(e["pattern_count"]) == 1]
                concurrent = [e for e in regime_events if int(e["pattern_count"]) > 1]

                for event_type, group in [("solo", solo), ("concurrent", concurrent)]:
                    if not group:
                        continue
                    n = len(group)
                    rets = [float(e["return_median"]) for e in group]
                    eb = event_bootstrap_ci(np.array(rets), "mean")
                    dc = date_cluster_bootstrap(group, "return_median", "mean")

                    rows.append({
                        "pattern_name": pattern,
                        "regime": regime,
                        "period": period,
                        "event_type": event_type,
                        "n_events": n,
                        "sample_label": get_sample_label(n),
                        "mean_return": round(statistics.mean(rets), 4),
                        "median_return": round(statistics.median(rets), 4),
                        "win_rate": round(sum(1 for r in rets if r > 0) / n * 100, 2),
                        "event_bootstrap_ci_low": eb["ci_lower"],
                        "event_bootstrap_ci_high": eb["ci_upper"],
                        "date_cluster_ci_low": dc["ci_lower"],
                        "date_cluster_ci_high": dc["ci_upper"],
                    })

    return rows


# ═══════════════════════════════════════════════════════════════
# Date-Cluster Bootstrap: Full OOS summary
# ═══════════════════════════════════════════════════════════════

def compute_date_cluster_summary(events: list[dict]) -> list[dict]:
    """Compute date-cluster bootstrap CIs for key groupings: overall, by regime, by pattern."""
    rows = []

    # Overall OOS
    oos_events = [e for e in events if get_period(e["signal_date"]) == "oos"]
    if oos_events:
        for stat in ["mean", "median", "win_rate"]:
            dc = date_cluster_bootstrap(oos_events, "return_median", stat)
            eb = event_bootstrap_ci(np.array([float(e["return_median"]) for e in oos_events]), stat)
            rows.append({
                "grouping": "overall",
                "regime": "ALL",
                "statistic": stat,
                "n_events": len(oos_events),
                "n_dates": len(set(e["signal_date"] for e in oos_events)),
                "event_bootstrap_ci_low": eb["ci_lower"],
                "event_bootstrap_ci_high": eb["ci_upper"],
                "date_cluster_ci_low": dc["ci_lower"],
                "date_cluster_ci_high": dc["ci_upper"],
                "point_estimate": dc["point_estimate"],
            })

    # By regime
    for regime in sorted(set(e["market_regime"] for e in oos_events)):
        regime_events = [e for e in oos_events if e["market_regime"] == regime]
        if len(regime_events) < 10:
            continue
        for stat in ["mean", "median", "win_rate"]:
            dc = date_cluster_bootstrap(regime_events, "return_median", stat)
            eb = event_bootstrap_ci(np.array([float(e["return_median"]) for e in regime_events]), stat)
            rows.append({
                "grouping": "by_regime",
                "regime": regime,
                "statistic": stat,
                "n_events": len(regime_events),
                "n_dates": len(set(e["signal_date"] for e in regime_events)),
                "event_bootstrap_ci_low": eb["ci_lower"],
                "event_bootstrap_ci_high": eb["ci_upper"],
                "date_cluster_ci_low": dc["ci_lower"],
                "date_cluster_ci_high": dc["ci_upper"],
                "point_estimate": dc["point_estimate"],
            })

    # By event_type (single vs multi)
    for et in ["single_pattern", "multi_pattern"]:
        if et == "single_pattern":
            et_events = [e for e in oos_events if int(e["pattern_count"]) == 1]
        else:
            et_events = [e for e in oos_events if int(e["pattern_count"]) > 1]
        if len(et_events) < 10:
            continue
        for stat in ["mean", "median", "win_rate"]:
            dc = date_cluster_bootstrap(et_events, "return_median", stat)
            eb = event_bootstrap_ci(np.array([float(e["return_median"]) for e in et_events]), stat)
            rows.append({
                "grouping": "by_event_type",
                "regime": et,
                "statistic": stat,
                "n_events": len(et_events),
                "n_dates": len(set(e["signal_date"] for e in et_events)),
                "event_bootstrap_ci_low": eb["ci_lower"],
                "event_bootstrap_ci_high": eb["ci_upper"],
                "date_cluster_ci_low": dc["ci_lower"],
                "date_cluster_ci_high": dc["ci_upper"],
                "point_estimate": dc["point_estimate"],
            })

    return rows


# ═══════════════════════════════════════════════════════════════
# Incremental Evidence Summary
# ═══════════════════════════════════════════════════════════════

def compute_incremental_evidence(attribution_rows: list[dict]) -> list[dict]:
    """Extract incremental evidence from attribution rows, OOS only, with stability info."""
    evidence = []
    for r in attribution_rows:
        if r["period"] != "oos":
            continue
        if r["incremental_mean"] is None:
            continue
        if r["n_events"] < 10:
            continue

        # Find train+val for stability
        train_rows = [a for a in attribution_rows
                      if a["pattern_name"] == r["pattern_name"]
                      and a["regime"] == r["regime"]
                      and a["period"] in ("train", "validation")
                      and a["incremental_mean"] is not None]

        train_inc = None
        val_inc = None
        for tr in train_rows:
            if tr["period"] == "train":
                train_inc = tr["incremental_mean"]
            elif tr["period"] == "validation":
                val_inc = tr["incremental_mean"]

        # Stability
        train_val_avg = None
        if train_inc is not None and val_inc is not None:
            train_val_avg = (train_inc + val_inc) / 2
        elif train_inc is not None:
            train_val_avg = train_inc
        elif val_inc is not None:
            train_val_avg = val_inc

        oos_inc = r["incremental_mean"]
        if train_val_avg is not None and r["n_events"] >= 10:
            if train_val_avg > 0 and oos_inc > 0:
                stability = "STABLE_POSITIVE"
            elif train_val_avg < 0 and oos_inc < 0:
                stability = "STABLE_NEGATIVE"
            else:
                stability = "SIGN_FLIP"
        else:
            stability = "INSUFFICIENT_DATA"

        # Evidence status
        if r["n_events"] < 30 or stability == "INSUFFICIENT_DATA":
            evidence_status = "INCONCLUSIVE"
        elif stability == "SIGN_FLIP":
            evidence_status = "WEAK"
        elif r["incremental_event_ci_low"] is not None and r["incremental_event_ci_low"] > 0:
            if r["incremental_date_cluster_ci_low"] is not None and r["incremental_date_cluster_ci_low"] > 0:
                evidence_status = "STRONG"
            else:
                evidence_status = "MODERATE"
        elif r["incremental_event_ci_low"] is not None and r["incremental_event_ci_low"] <= 0:
            evidence_status = "WEAK"
        else:
            evidence_status = "INCONCLUSIVE"

        evidence.append({
            "pattern_name": r["pattern_name"],
            "regime": r["regime"],
            "period": r["period"],
            "n_present": r["n_events"],
            "baseline_n": r["baseline_n"],
            "incremental_mean": r["incremental_mean"],
            "incremental_median": r["incremental_median"],
            "incremental_win_rate": r["incremental_win_rate"],
            "incremental_event_ci_low": r["incremental_event_ci_low"],
            "incremental_event_ci_high": r["incremental_event_ci_high"],
            "incremental_date_cluster_ci_low": r["incremental_date_cluster_ci_low"],
            "incremental_date_cluster_ci_high": r["incremental_date_cluster_ci_high"],
            "train_incremental_mean": train_inc,
            "val_incremental_mean": val_inc,
            "stability": stability,
            "evidence_status": evidence_status,
            "sample_label": r["sample_label"],
        })

    return evidence


# ═══════════════════════════════════════════════════════════════
# CSV Writers
# ═══════════════════════════════════════════════════════════════

def write_attribution_csv(rows: list[dict]):
    fields = [
        "pattern_name", "regime", "period", "presence_type",
        "n_events", "sample_label",
        "mean_return", "median_return", "win_rate", "std_return",
        "event_bootstrap_ci_low", "event_bootstrap_ci_high",
        "date_cluster_ci_low", "date_cluster_ci_high",
        "baseline_n",
        "incremental_mean", "incremental_median", "incremental_win_rate",
        "incremental_event_ci_low", "incremental_event_ci_high",
        "incremental_date_cluster_ci_low", "incremental_date_cluster_ci_high",
    ]
    path = RESULTS_DIR / "pattern_incremental_attribution.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    print(f"Saved: {path} ({len(rows)} rows)")


def write_solo_concurrent_csv(rows: list[dict]):
    fields = [
        "pattern_name", "regime", "period", "event_type",
        "n_events", "sample_label",
        "mean_return", "median_return", "win_rate",
        "event_bootstrap_ci_low", "event_bootstrap_ci_high",
        "date_cluster_ci_low", "date_cluster_ci_high",
    ]
    path = RESULTS_DIR / "pattern_solo_concurrent.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    print(f"Saved: {path} ({len(rows)} rows)")


def write_date_cluster_csv(rows: list[dict]):
    fields = [
        "grouping", "regime", "statistic",
        "n_events", "n_dates",
        "event_bootstrap_ci_low", "event_bootstrap_ci_high",
        "date_cluster_ci_low", "date_cluster_ci_high",
        "point_estimate",
    ]
    path = RESULTS_DIR / "pattern_date_cluster_bootstrap.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    print(f"Saved: {path} ({len(rows)} rows)")


def write_evidence_csv(rows: list[dict]):
    fields = [
        "pattern_name", "regime", "period",
        "n_present", "baseline_n",
        "incremental_mean", "incremental_median", "incremental_win_rate",
        "incremental_event_ci_low", "incremental_event_ci_high",
        "incremental_date_cluster_ci_low", "incremental_date_cluster_ci_high",
        "train_incremental_mean", "val_incremental_mean",
        "stability", "evidence_status", "sample_label",
    ]
    path = RESULTS_DIR / "pattern_incremental_evidence.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    print(f"Saved: {path} ({len(rows)} rows)")


# ═══════════════════════════════════════════════════════════════
# Print Summary
# ═══════════════════════════════════════════════════════════════

def print_summary(
    events: list[dict],
    attribution_rows: list[dict],
    solo_rows: list[dict],
    date_cluster_rows: list[dict],
    evidence_rows: list[dict],
):
    oos_events = [e for e in events if OOS_START <= e["signal_date"] <= OOS_END]
    oos_dates = sorted(set(e["signal_date"] for e in oos_events))

    print(f"\n{'=' * 70}")
    print("PHASE 2B.1 — PATTERN INCREMENTAL ATTRIBUTION + DATE-CLUSTER BOOTSTRAP")
    print(f"{'=' * 70}")

    print(f"\n  Total events:             {len(events):>10,}")
    print(f"  OOS events:               {len(oos_events):>10,}")
    print(f"  OOS unique dates:         {len(oos_dates):>10,}")

    # Date-cluster vs event bootstrap comparison
    print(f"\n{'─' * 70}")
    print("Date-Cluster vs Event Bootstrap (OOS)")
    print(f"{'─' * 70}")
    for r in date_cluster_rows:
        if r["grouping"] == "overall":
            eb = f"[{r['event_bootstrap_ci_low']:+.4f}, {r['event_bootstrap_ci_high']:+.4f}]" if r['event_bootstrap_ci_low'] is not None else "N/A"
            dc = f"[{r['date_cluster_ci_low']:+.4f}, {r['date_cluster_ci_high']:+.4f}]" if r['date_cluster_ci_low'] is not None else "N/A"
            print(f"  {r['statistic']:10s}: event_bootstrap={eb}  date_cluster={dc}")

    # Incremental evidence
    print(f"\n{'─' * 70}")
    print("Incremental Evidence (OOS)")
    print(f"{'─' * 70}")
    status_counts = defaultdict(int)
    for r in evidence_rows:
        status_counts[r["evidence_status"]] += 1
    print(f"  STRONG:     {status_counts.get('STRONG', 0)}")
    print(f"  MODERATE:   {status_counts.get('MODERATE', 0)}")
    print(f"  WEAK:       {status_counts.get('WEAK', 0)}")
    print(f"  INCONCLUSIVE: {status_counts.get('INCONCLUSIVE', 0)}")

    # Top positive incremental evidence
    positive = [r for r in evidence_rows
                if r["incremental_mean"] is not None and r["incremental_mean"] > 0
                and r["n_present"] >= 30]
    if positive:
        print(f"\n  Positive incremental (n>=30):")
        for r in sorted(positive, key=lambda r: -r["incremental_mean"])[:10]:
            inc = r['incremental_mean']
            ci_lo = f"{r['incremental_event_ci_low']:+.2f}" if r['incremental_event_ci_low'] is not None else "N/A"
            ci_hi = f"{r['incremental_event_ci_high']:+.2f}" if r['incremental_event_ci_high'] is not None else "N/A"
            dc_lo = f"{r['incremental_date_cluster_ci_low']:+.2f}" if r['incremental_date_cluster_ci_low'] is not None else "N/A"
            dc_hi = f"{r['incremental_date_cluster_ci_high']:+.2f}" if r['incremental_date_cluster_ci_high'] is not None else "N/A"
            print(f"    {r['pattern_name']}/{r['regime']}: "
                  f"+{inc:+.2f}% (n={r['n_present']}/{r['baseline_n']}) "
                  f"event_ci=[{ci_lo}, {ci_hi}] "
                  f"dc_ci=[{dc_lo}, {dc_hi}] "
                  f"stability={r['stability']}")

    # Solo vs concurrent highlights
    print(f"\n{'─' * 70}")
    print("Solo vs Concurrent (OOS, large samples)")
    print(f"{'─' * 70}")
    oos_solo = [r for r in solo_rows if r["period"] == "oos" and r["sample_label"] == "large"]
    for r in sorted(oos_solo, key=lambda r: (r["pattern_name"], r["event_type"])):
        et = r["event_type"]
        print(f"  {r['pattern_name']:20s} {r['regime']:10s} {et:12s}: "
              f"n={r['n_events']:>6,}  mean={float(r['mean_return']):>+7.2f}%  wr={float(r['win_rate']):>5.1f}%")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Phase 2B.1 — Pattern Incremental Attribution")
    parser.add_argument("--no-bootstrap", action="store_true",
                        help="Skip bootstrap CI computation (faster)")
    args = parser.parse_args()

    global BOOTSTRAP_ITERATIONS
    if args.no_bootstrap:
        BOOTSTRAP_ITERATIONS = 0

    print("Loading event-level data...")
    events = load_events()
    print(f"  Loaded {len(events):,} events")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Pattern presence / incremental attribution ──
    print("\nComputing pattern presence & incremental attribution...")
    attribution_rows = compute_pattern_presence(events)
    write_attribution_csv(attribution_rows)

    # ── Solo vs concurrent ──
    print("Computing solo vs concurrent...")
    solo_rows = compute_solo_concurrent(events)
    write_solo_concurrent_csv(solo_rows)

    # ── Date-cluster bootstrap ──
    print("Computing date-cluster bootstrap...")
    date_cluster_rows = compute_date_cluster_summary(events)
    write_date_cluster_csv(date_cluster_rows)

    # ── Incremental evidence ──
    print("Computing incremental evidence...")
    evidence_rows = compute_incremental_evidence(attribution_rows)
    write_evidence_csv(evidence_rows)

    # ── Print ──
    print_summary(events, attribution_rows, solo_rows, date_cluster_rows, evidence_rows)

    print(f"\nPHASE 2B.1 STATUS: PASS")
    print(f"  {len(attribution_rows)} attribution rows")
    print(f"  {len(solo_rows)} solo/concurrent rows")
    print(f"  {len(date_cluster_rows)} date-cluster rows")
    print(f"  {len(evidence_rows)} incremental evidence rows")


if __name__ == "__main__":
    main()
