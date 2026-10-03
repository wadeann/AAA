"""Phase 2B — Event-Level OOS Validation.

Aggregates Phase 2A trades into unique signal events (symbol + signal_date),
computes OOS statistics at event level, and generates bootstrap confidence
intervals on unique events (not trades).

Key design decisions:
  - event_id = symbol + signal_date (from pattern_overlap_summary.csv)
  - Multi-outcome events handled via 3 aggregation methods (mean/median/consensus)
  - Bootstrap operates on UNIQUE EVENTS, never duplicates multi-pattern events
  - theme_lifecycle = NOT_AVAILABLE (no data source in codebase)
  - context_quality derived from profile_count/pattern_count
  - No "best pattern" rankings — evidence grades only
"""

import csv
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "results"
TRADES_CSV = RESULTS_DIR / "pattern_all_trades.csv"
OVERLAP_CSV = RESULTS_DIR / "pattern_overlap_summary.csv"
BASELINE_CSV = RESULTS_DIR / "baseline_daily.csv"
STABILITY_CSV = RESULTS_DIR / "pattern_stability.csv"
VALIDATION_CSV = RESULTS_DIR / "pattern_regime_validation.csv"

OOS_START = "2026-04-01"
OOS_END = "2026-10-01"
TRAIN_START = "2024-10-01"
TRAIN_END = "2025-09-30"
VAL_START = "2025-10-01"
VAL_END = "2026-03-31"

BOOTSTRAP_ITERATIONS = 1000
BOOTSTRAP_CONFIDENCE = 0.95
BOOTSTRAP_SEED = 42
SMALL_THRESHOLD = 30
MEDIUM_THRESHOLD = 100


# ═══════════════════════════════════════════════════════════════
# Data Loading
# ═══════════════════════════════════════════════════════════════

def load_trades() -> list[dict]:
    """Load all Phase 2A trades."""
    with open(TRADES_CSV) as f:
        return list(csv.DictReader(f))


def load_overlap() -> list[dict]:
    """Load pattern overlap summary (one row per signal event)."""
    with open(OVERLAP_CSV) as f:
        return list(csv.DictReader(f))


def load_baselines() -> dict[str, float]:
    """Load daily baseline returns keyed by entry_date."""
    with open(BASELINE_CSV) as f:
        return {row["entry_date"]: float(row["avg_return"])
                for row in csv.DictReader(f)}


def load_stability() -> dict[tuple[str, str, str], dict]:
    """Load stability data keyed by (profile_name, pattern_name, market_regime)."""
    with open(STABILITY_CSV) as f:
        rows = list(csv.DictReader(f))
    result = {}
    for r in rows:
        key = (r["profile_name"], r["pattern_name"], r["market_regime"])
        result[key] = r
    return result


def load_train_val_returns() -> dict[tuple[str, str, str], dict]:
    """Load train/val avg returns keyed by (profile_name, pattern_name, market_regime)."""
    with open(VALIDATION_CSV) as f:
        rows = list(csv.DictReader(f))
    result = {}
    for r in rows:
        key = (r["profile_name"], r["pattern_name"], r["market_regime"], r["period"])
        result[key] = float(r["avg_return"])
    return result


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def get_period(pattern_date: str) -> str:
    """Map a pattern_date to train/validation/oos/unknown."""
    if TRAIN_START <= pattern_date <= TRAIN_END:
        return "train"
    if VAL_START <= pattern_date <= VAL_END:
        return "validation"
    if OOS_START <= pattern_date <= OOS_END:
        return "oos"
    return "unknown"


def get_sample_label(n: int) -> str:
    if n >= MEDIUM_THRESHOLD:
        return "large"
    if n >= SMALL_THRESHOLD:
        return "medium"
    return "small"


def get_context_quality(profile_count: int, pattern_count: int) -> str:
    """Derive context quality from event complexity."""
    complexity = max(profile_count, pattern_count)
    if complexity <= 1:
        return "SIMPLE"
    if complexity <= 3:
        return "MODERATE"
    return "COMPLEX"


def get_dispersion_flag(return_range: float) -> str:
    if return_range < 2.0:
        return "LOW"
    if return_range < 5.0:
        return "MEDIUM"
    return "HIGH"


def simplify_exit_reason(reason: str) -> str:
    """Strip trailing parameters from exit reason for grouping.
    e.g. '回落25%(高7.1%)' -> '回落25%'"""
    idx = reason.find("(")
    return reason[:idx] if idx > 0 else reason


def compute_stability_status(
    train_val_ret: float | None,
    oos_ret: float,
    n_oos: int,
) -> str:
    """Determine stability status comparing train+val vs OOS."""
    if n_oos < 10 or train_val_ret is None:
        return "INSUFFICIENT_DATA"
    oos_sign = oos_ret > 0
    tv_sign = train_val_ret > 0
    if tv_sign == oos_sign:
        return "STABLE_POSITIVE" if oos_sign else "STABLE_NEGATIVE"
    return "SIGN_FLIP"


def compute_evidence_grade(
    n: int,
    stability: str,
    mean_ci_lower: float | None,
    excess_ci_lower: float | None,
) -> str:
    """Assign evidence grade based on sample size, stability, and CI."""
    if n < SMALL_THRESHOLD:
        return "INCONCLUSIVE"
    if stability not in ("STABLE_POSITIVE",):
        return "INCONCLUSIVE"
    if mean_ci_lower is None:
        return "INCONCLUSIVE"
    if mean_ci_lower > 0 and (excess_ci_lower is None or excess_ci_lower > 0):
        if n >= MEDIUM_THRESHOLD:
            return "STRONG"
        return "MODERATE"
    if mean_ci_lower > 0:
        return "MODERATE"
    if mean_ci_lower <= 0:
        return "WEAK"
    return "INCONCLUSIVE"


# ═══════════════════════════════════════════════════════════════
# Bootstrap CI Engine (numpy only)
# ═══════════════════════════════════════════════════════════════

def bootstrap_ci(
    data: np.ndarray,
    statistic: str = "mean",
    n_iterations: int = BOOTSTRAP_ITERATIONS,
    confidence: float = BOOTSTRAP_CONFIDENCE,
    seed: int = BOOTSTRAP_SEED,
) -> dict:
    """Bootstrap confidence intervals for mean, median, or win_rate.

    Operates on EVENT-LEVEL data. Uses numpy.random.RandomState for
    deterministic reproducibility.

    Returns dict with point_estimate, ci_lower, ci_upper, n_bootstrap, n_original.
    """
    n = len(data)
    if n < 2:
        return {
            "point_estimate": float(data[0]) if n == 1 else None,
            "ci_lower": None,
            "ci_upper": None,
            "n_bootstrap": n_iterations,
            "n_original": n,
        }

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
    ci_lower = float(np.percentile(estimates, alpha * 100))
    ci_upper = float(np.percentile(estimates, (1 - alpha) * 100))

    return {
        "point_estimate": round(point, 4),
        "ci_lower": round(ci_lower, 4),
        "ci_upper": round(ci_upper, 4),
        "n_bootstrap": n_iterations,
        "n_original": n,
    }


def compute_group_bootstrap(
    events: list[dict],
    return_key: str = "return_median",
) -> dict:
    """Compute bootstrap CIs for a group of events.

    Returns bootstrap results for mean, median, and win_rate.
    """
    returns = np.array([e[return_key] for e in events], dtype=float)
    excess_key = "baseline_excess_mean"
    excess = np.array([e.get(excess_key, e.get("return_median", 0))
                       for e in events], dtype=float)

    if len(returns) < 2:
        return {
            "mean_ci": {"ci_lower": None, "ci_upper": None},
            "median_ci": {"ci_lower": None, "ci_upper": None},
            "win_rate_ci": {"ci_lower": None, "ci_upper": None},
            "excess_ci": {"ci_lower": None, "ci_upper": None},
        }

    return {
        "mean_ci": bootstrap_ci(returns, "mean"),
        "median_ci": bootstrap_ci(returns, "median"),
        "win_rate_ci": bootstrap_ci(returns, "win_rate"),
        "excess_ci": bootstrap_ci(excess, "mean"),
    }


# ═══════════════════════════════════════════════════════════════
# Event Aggregation
# ═══════════════════════════════════════════════════════════════

def aggregate_events(
    trades: list[dict],
    overlap_rows: list[dict],
    baselines: dict[str, float],
) -> list[dict]:
    """Build event-level dataset from overlap summary + trades.

    For each unique (symbol, signal_date) from overlap_summary:
      - Collect all matching trades from pattern_all_trades.csv
      - Compute return_mean, return_median, return_consensus
      - Derive context_quality, dispersion metrics
      - Match baseline by entry_date
    """
    # Build trade lookup: (symbol, pattern_date) -> list of trades
    trade_lookup: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in trades:
        trade_lookup[(t["symbol"], t["pattern_date"])].append(t)

    events = []
    for row in overlap_rows:
        symbol = row["symbol"]
        signal_date = row["signal_date"]
        key = (symbol, signal_date)
        event_trades = trade_lookup.get(key, [])

        if not event_trades:
            continue

        returns = [float(t["return_pct"]) for t in event_trades]
        exit_reasons_raw = [t["exit_reason"] for t in event_trades]
        holding_days = [int(t["holding_days"]) for t in event_trades]

        n_trades = len(event_trades)

        # Three aggregation methods
        return_mean = round(statistics.mean(returns), 4)
        return_median = round(statistics.median(returns), 4)

        # Consensus: return from most common exit reason
        simplified = [simplify_exit_reason(r) for r in exit_reasons_raw]
        reason_counts: dict[str, int] = {}
        for sr in simplified:
            reason_counts[sr] = reason_counts.get(sr, 0) + 1
        max_count = max(reason_counts.values())
        top_reasons = [sr for sr, c in reason_counts.items() if c == max_count]

        if len(top_reasons) == 1:
            # Single most common reason: median of returns with that reason
            consensus_returns = [
                returns[i] for i, sr in enumerate(simplified)
                if sr == top_reasons[0]
            ]
            return_consensus = round(statistics.median(consensus_returns), 4)
            primary_exit_reason = top_reasons[0]
        else:
            # Tie or all unique: use median of all returns
            return_consensus = return_median
            primary_exit_reason = simplified[0]  # first alphabetically

        # Dispersion
        return_stdev = round(statistics.stdev(returns), 4) if n_trades > 1 else 0.0
        return_range = round(max(returns) - min(returns), 4)

        # Context quality
        profile_count = int(row["profile_count"])
        pattern_count = int(row["pattern_count"])

        # Baselines
        entry_date = event_trades[0]["entry_date"]
        baseline_return = baselines.get(entry_date)
        baseline_excess_mean = (
            round(return_mean - baseline_return, 4)
            if baseline_return is not None else None
        )

        events.append({
            "symbol": symbol,
            "signal_date": signal_date,
            "event_id": f"{symbol}_{signal_date}",
            "entry_date": entry_date,
            "entry_price": float(event_trades[0]["entry_price"]),
            "profile_count": profile_count,
            "pattern_count": pattern_count,
            "profiles": row["profiles"],
            "patterns": row["patterns"],
            "market_regime": event_trades[0]["market_regime"],
            "context_quality": get_context_quality(profile_count, pattern_count),
            "theme_lifecycle": "NOT_AVAILABLE",
            "return_mean": return_mean,
            "return_median": return_median,
            "return_consensus": return_consensus,
            "return_stdev": return_stdev,
            "return_range": return_range,
            "min_holding_days": min(holding_days),
            "max_holding_days": max(holding_days),
            "exit_reasons": "|".join(sorted(set(simplified))),
            "primary_exit_reason": primary_exit_reason,
            "return_dispersion_flag": get_dispersion_flag(return_range),
            "baseline_return": round(baseline_return, 4) if baseline_return is not None else None,
            "baseline_excess_mean": baseline_excess_mean,
        })

    return events


# ═══════════════════════════════════════════════════════════════
# Summary Builders
# ═══════════════════════════════════════════════════════════════

def build_event_oos_summary(
    oos_events: list[dict],
) -> list[dict]:
    """Build OOS event summary by regime × context_quality × event_type."""
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for e in oos_events:
        regime = e["market_regime"] or "unknown"
        cq = e["context_quality"]
        et = "single_pattern" if e["pattern_count"] == 1 else "multi_pattern"
        groups[(regime, cq, et)].append(e)

    rows = []
    for (regime, cq, et), events in sorted(groups.items()):
        n = len(events)
        returns = [e["return_median"] for e in events]
        excess = [e["baseline_excess_mean"] for e in events
                  if e["baseline_excess_mean"] is not None]
        ci = compute_group_bootstrap(events, "return_median")

        rows.append({
            "regime": regime,
            "context_quality": cq,
            "event_type": et,
            "n_events": n,
            "sample_label": get_sample_label(n),
            "mean_return": round(statistics.mean(returns), 4),
            "median_return": round(statistics.median(returns), 4),
            "win_rate": round(sum(1 for r in returns if r > 0) / n * 100, 2),
            "mean_excess": round(statistics.mean(excess), 4) if excess else None,
            "mean_ci_lower": ci["mean_ci"]["ci_lower"],
            "mean_ci_upper": ci["mean_ci"]["ci_upper"],
            "win_rate_ci_lower": ci["win_rate_ci"]["ci_lower"],
            "win_rate_ci_upper": ci["win_rate_ci"]["ci_upper"],
            "excess_ci_lower": ci["excess_ci"]["ci_lower"],
            "excess_ci_upper": ci["excess_ci"]["ci_upper"],
            "stability": "INSUFFICIENT_DATA",  # Filled below
            "theme_lifecycle": "NOT_AVAILABLE",
        })

    return rows


def build_single_pattern_oos(
    oos_events: list[dict],
    train_val_returns: dict[tuple[str, str, str], float],
) -> list[dict]:
    """Build single-pattern OOS evidence by profile × pattern × regime."""
    single_events = [e for e in oos_events if e["pattern_count"] == 1]

    groups: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for e in single_events:
        # For single-pattern events: profiles pipe just has one entry
        profile = e["profiles"].split("|")[0] if "|" in e["profiles"] else e["profiles"]
        pattern = e["patterns"].split("|")[0] if "|" in e["patterns"] else e["patterns"]
        regime = e["market_regime"] or "unknown"
        groups[(profile, pattern, regime)].append(e)

    rows = []
    for (profile, pattern, regime), events in sorted(groups.items()):
        n = len(events)
        returns = [e["return_median"] for e in events]
        excess = [e["baseline_excess_mean"] for e in events
                  if e["baseline_excess_mean"] is not None]
        ci = compute_group_bootstrap(events, "return_median")
        avg_dispersion = round(
            statistics.mean([e["return_stdev"] for e in events]), 4)

        # Train+val return
        tv_key = (profile, pattern, regime, "train")
        vv_key = (profile, pattern, regime, "validation")
        train_ret = train_val_returns.get(tv_key)
        val_ret = train_val_returns.get(vv_key)
        tv_avg = None
        if train_ret is not None and val_ret is not None:
            tv_avg = (train_ret + val_ret) / 2
        elif train_ret is not None:
            tv_avg = train_ret
        elif val_ret is not None:
            tv_avg = val_ret

        stability = compute_stability_status(tv_avg, statistics.mean(returns), n)

        rows.append({
            "profile_name": profile,
            "pattern_name": pattern,
            "regime": regime,
            "n_events": n,
            "sample_label": get_sample_label(n),
            "mean_return": round(statistics.mean(returns), 4),
            "median_return": round(statistics.median(returns), 4),
            "win_rate": round(sum(1 for r in returns if r > 0) / n * 100, 2),
            "mean_excess": round(statistics.mean(excess), 4) if excess else None,
            "mean_ci_lower": ci["mean_ci"]["ci_lower"],
            "mean_ci_upper": ci["mean_ci"]["ci_upper"],
            "win_rate_ci_lower": ci["win_rate_ci"]["ci_lower"],
            "win_rate_ci_upper": ci["win_rate_ci"]["ci_upper"],
            "excess_ci_lower": ci["excess_ci"]["ci_lower"],
            "excess_ci_upper": ci["excess_ci"]["ci_upper"],
            "avg_return_stdev": avg_dispersion,
            "stability": stability,
            "theme_lifecycle": "NOT_AVAILABLE",
        })

    return rows


def build_multipattern_oos(
    oos_events: list[dict],
) -> list[dict]:
    """Build multi-pattern OOS evidence by pattern_count × regime."""
    multi_events = [e for e in oos_events if e["pattern_count"] > 1]

    groups: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for e in multi_events:
        pc = e["pattern_count"]
        regime = e["market_regime"] or "unknown"
        groups[(pc, regime)].append(e)

    rows = []
    for (pc, regime), events in sorted(groups.items()):
        n = len(events)
        returns = [e["return_median"] for e in events]
        excess = [e["baseline_excess_mean"] for e in events
                  if e["baseline_excess_mean"] is not None]
        ci = compute_group_bootstrap(events, "return_median")
        avg_dispersion = round(
            statistics.mean([e["return_stdev"] for e in events]), 4)

        rows.append({
            "pattern_count": pc,
            "regime": regime,
            "n_events": n,
            "sample_label": get_sample_label(n),
            "mean_return": round(statistics.mean(returns), 4),
            "median_return": round(statistics.median(returns), 4),
            "win_rate": round(sum(1 for r in returns if r > 0) / n * 100, 2),
            "mean_excess": round(statistics.mean(excess), 4) if excess else None,
            "mean_ci_lower": ci["mean_ci"]["ci_lower"],
            "mean_ci_upper": ci["mean_ci"]["ci_upper"],
            "win_rate_ci_lower": ci["win_rate_ci"]["ci_lower"],
            "win_rate_ci_upper": ci["win_rate_ci"]["ci_upper"],
            "excess_ci_lower": ci["excess_ci"]["ci_lower"],
            "excess_ci_upper": ci["excess_ci"]["ci_upper"],
            "avg_return_stdev": avg_dispersion,
            "stability": "INSUFFICIENT_DATA",
            "theme_lifecycle": "NOT_AVAILABLE",
        })

    return rows


def build_pattern_presence_oos(
    oos_events: list[dict],
) -> list[dict]:
    """Build per-pattern presence analysis: solo vs concurrent."""
    # For each pattern, find events where it's present
    all_patterns: set[str] = set()
    for e in oos_events:
        for p in e["patterns"].split("|"):
            p = p.strip()
            if p:
                all_patterns.add(p)

    rows = []
    for pattern in sorted(all_patterns):
        # Categorize events by how this pattern appears
        solo_events = []
        concurrent_2 = []
        concurrent_3 = []
        concurrent_4plus = []
        concurrent_any = []

        for e in oos_events:
            event_patterns = [p.strip() for p in e["patterns"].split("|")]
            if pattern not in event_patterns:
                continue
            concurrent_any.append(e)
            pc = e["pattern_count"]
            if pc == 1:
                solo_events.append(e)
            elif pc == 2:
                concurrent_2.append(e)
            elif pc == 3:
                concurrent_3.append(e)
            else:
                concurrent_4plus.append(e)

        for presence_type, events in [
            ("solo", solo_events),
            ("concurrent_any", concurrent_any),
            ("concurrent_2", concurrent_2),
            ("concurrent_3_4plus", concurrent_3 + concurrent_4plus),
        ]:
            if not events:
                continue
            n = len(events)
            returns = [e["return_median"] for e in events]
            excess = [e["baseline_excess_mean"] for e in events
                      if e["baseline_excess_mean"] is not None]
            ci = compute_group_bootstrap(events, "return_median")

            # Get regimes present
            regimes = sorted(set(e["market_regime"] for e in events))
            for regime in regimes:
                regime_events = [e for e in events if e["market_regime"] == regime]
                if len(regime_events) < 5:
                    continue  # Too few for regime-specific
                rn = len(regime_events)
                rreturns = [e["return_median"] for e in regime_events]
                rexcess = [e["baseline_excess_mean"] for e in regime_events
                           if e["baseline_excess_mean"] is not None]
                rci = compute_group_bootstrap(regime_events, "return_median")

                rows.append({
                    "pattern_name": pattern,
                    "presence_type": presence_type,
                    "regime": regime,
                    "n_events": rn,
                    "sample_label": get_sample_label(rn),
                    "mean_return": round(statistics.mean(rreturns), 4),
                    "median_return": round(statistics.median(rreturns), 4),
                    "win_rate": round(sum(1 for r in rreturns if r > 0) / rn * 100, 2),
                    "mean_excess": round(statistics.mean(rexcess), 4) if rexcess else None,
                    "mean_ci_lower": rci["mean_ci"]["ci_lower"],
                    "mean_ci_upper": rci["mean_ci"]["ci_upper"],
                    "win_rate_ci_lower": rci["win_rate_ci"]["ci_lower"],
                    "win_rate_ci_upper": rci["win_rate_ci"]["ci_upper"],
                    "excess_ci_lower": rci["excess_ci"]["ci_lower"],
                    "excess_ci_upper": rci["excess_ci"]["ci_upper"],
                    "theme_lifecycle": "NOT_AVAILABLE",
                })

    return rows


def build_pattern_oos_evidence(
    oos_events: list[dict],
    train_val_returns: dict[tuple[str, str, str], float],
) -> list[dict]:
    """Build candidate evidence table with bootstrap CIs and evidence grades."""
    # Group by profile+pattern+regime across all event types
    groups: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    for e in oos_events:
        profiles = [p.strip() for p in e["profiles"].split("|")]
        patterns = [p.strip() for p in e["patterns"].split("|")]
        regime = e["market_regime"] or "unknown"
        for profile in set(profiles):
            for pattern in set(patterns):
                # Only include this event if profile+pattern are both present
                if profile in profiles and pattern in patterns:
                    groups[(profile, pattern, regime)].append(e)

    rows = []
    for (profile, pattern, regime), events in sorted(groups.items()):
        n = len(events)
        returns = [e["return_median"] for e in events]
        excess = [e["baseline_excess_mean"] for e in events
                  if e["baseline_excess_mean"] is not None]
        ci = compute_group_bootstrap(events, "return_median")

        # Train+val return
        tv_key_train = (profile, pattern, regime, "train")
        tv_key_val = (profile, pattern, regime, "validation")
        train_ret = train_val_returns.get(tv_key_train)
        val_ret = train_val_returns.get(tv_key_val)
        tv_avg = None
        if train_ret is not None and val_ret is not None:
            tv_avg = (train_ret + val_ret) / 2
        elif train_ret is not None:
            tv_avg = train_ret
        elif val_ret is not None:
            tv_avg = val_ret

        mean_ret = round(statistics.mean(returns), 4)
        stability = compute_stability_status(tv_avg, mean_ret, n)
        grade = compute_evidence_grade(
            n, stability,
            ci["mean_ci"]["ci_lower"],
            ci["excess_ci"]["ci_lower"],
        )

        # Predominant context quality
        cq_counts = defaultdict(int)
        for e in events:
            cq_counts[e["context_quality"]] += 1
        predominant_cq = max(cq_counts, key=cq_counts.get)

        rows.append({
            "evidence_id": f"{profile}|{pattern}|{regime}",
            "profile_name": profile,
            "pattern_name": pattern,
            "regime": regime,
            "n_oos_events": n,
            "sample_label": get_sample_label(n),
            "oos_mean_return": mean_ret,
            "oos_median_return": round(statistics.median(returns), 4),
            "oos_win_rate": round(sum(1 for r in returns if r > 0) / n * 100, 2),
            "oos_mean_excess": round(statistics.mean(excess), 4) if excess else None,
            "mean_ci_lower": ci["mean_ci"]["ci_lower"],
            "mean_ci_upper": ci["mean_ci"]["ci_upper"],
            "win_rate_ci_lower": ci["win_rate_ci"]["ci_lower"],
            "win_rate_ci_upper": ci["win_rate_ci"]["ci_upper"],
            "excess_ci_lower": ci["excess_ci"]["ci_lower"],
            "excess_ci_upper": ci["excess_ci"]["ci_upper"],
            "stability": stability,
            "train_mean_return": train_ret,
            "val_mean_return": val_ret,
            "evidence_grade": grade,
            "theme_lifecycle": "NOT_AVAILABLE",
            "context_quality": predominant_cq,
        })

    return rows


# ═══════════════════════════════════════════════════════════════
# CSV Writers
# ═══════════════════════════════════════════════════════════════

def write_event_csv(events: list[dict]):
    fields = [
        "symbol", "signal_date", "event_id", "entry_date", "entry_price",
        "profile_count", "pattern_count", "profiles", "patterns",
        "market_regime", "context_quality", "theme_lifecycle",
        "return_mean", "return_median", "return_consensus",
        "return_stdev", "return_range",
        "min_holding_days", "max_holding_days",
        "exit_reasons", "primary_exit_reason", "return_dispersion_flag",
        "baseline_return", "baseline_excess_mean",
    ]
    path = RESULTS_DIR / "event_level_trades.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for e in events:
            w.writerow({k: e[k] for k in fields})
    print(f"Saved: {path} ({len(events):,} events)")


def write_oos_summary_csv(rows: list[dict]):
    fields = [
        "regime", "context_quality", "event_type",
        "n_events", "sample_label",
        "mean_return", "median_return", "win_rate", "mean_excess",
        "mean_ci_lower", "mean_ci_upper",
        "win_rate_ci_lower", "win_rate_ci_upper",
        "excess_ci_lower", "excess_ci_upper",
        "stability", "theme_lifecycle",
    ]
    path = RESULTS_DIR / "event_oos_summary.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    print(f"Saved: {path} ({len(rows)} rows)")


def write_single_pattern_oos_csv(rows: list[dict]):
    fields = [
        "profile_name", "pattern_name", "regime",
        "n_events", "sample_label",
        "mean_return", "median_return", "win_rate", "mean_excess",
        "mean_ci_lower", "mean_ci_upper",
        "win_rate_ci_lower", "win_rate_ci_upper",
        "excess_ci_lower", "excess_ci_upper",
        "avg_return_stdev", "stability", "theme_lifecycle",
    ]
    path = RESULTS_DIR / "single_pattern_oos.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    print(f"Saved: {path} ({len(rows)} rows)")


def write_multipattern_oos_csv(rows: list[dict]):
    fields = [
        "pattern_count", "regime",
        "n_events", "sample_label",
        "mean_return", "median_return", "win_rate", "mean_excess",
        "mean_ci_lower", "mean_ci_upper",
        "win_rate_ci_lower", "win_rate_ci_upper",
        "excess_ci_lower", "excess_ci_upper",
        "avg_return_stdev", "stability", "theme_lifecycle",
    ]
    path = RESULTS_DIR / "multipattern_oos.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    print(f"Saved: {path} ({len(rows)} rows)")


def write_pattern_presence_oos_csv(rows: list[dict]):
    fields = [
        "pattern_name", "presence_type", "regime",
        "n_events", "sample_label",
        "mean_return", "median_return", "win_rate", "mean_excess",
        "mean_ci_lower", "mean_ci_upper",
        "win_rate_ci_lower", "win_rate_ci_upper",
        "excess_ci_lower", "excess_ci_upper",
        "theme_lifecycle",
    ]
    path = RESULTS_DIR / "pattern_presence_oos.csv"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in fields})
    print(f"Saved: {path} ({len(rows)} rows)")


def write_pattern_oos_evidence_csv(rows: list[dict]):
    fields = [
        "evidence_id", "profile_name", "pattern_name", "regime",
        "n_oos_events", "sample_label",
        "oos_mean_return", "oos_median_return", "oos_win_rate", "oos_mean_excess",
        "mean_ci_lower", "mean_ci_upper",
        "win_rate_ci_lower", "win_rate_ci_upper",
        "excess_ci_lower", "excess_ci_upper",
        "stability", "train_mean_return", "val_mean_return",
        "evidence_grade", "theme_lifecycle", "context_quality",
    ]
    path = RESULTS_DIR / "pattern_oos_evidence.csv"
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
    oos_events: list[dict],
    oos_summary: list[dict],
    single_rows: list[dict],
    multi_rows: list[dict],
    evidence_rows: list[dict],
):
    """Print Phase 2B results summary."""
    print(f"\n{'=' * 70}")
    print("PHASE 2B — EVENT-LEVEL OOS VALIDATION")
    print(f"{'=' * 70}")

    # Event counts
    total = len(events)
    single = sum(1 for e in events if e["pattern_count"] == 1)
    multi = sum(1 for e in events if e["pattern_count"] > 1)
    overlap_pct = multi / total * 100
    print(f"\n  Total unique events:     {total:>10,}")
    print(f"  Single-pattern events:   {single:>10,} ({single/total*100:.1f}%)")
    print(f"  Multi-pattern events:    {multi:>10,} ({overlap_pct:.1f}%)")

    # Return dispersion
    multi_events = [e for e in events if e["pattern_count"] > 1]
    if multi_events:
        avg_stdev = statistics.mean([e["return_stdev"] for e in multi_events])
        avg_range = statistics.mean([e["return_range"] for e in multi_events])
        diff_events = sum(1 for e in multi_events if e["return_range"] > 0.01)
        print(f"\n  Multi-event avg stdev:  {avg_stdev:>10.2f}%")
        print(f"  Multi-event avg range:  {avg_range:>10.2f}%")
        print(f"  Events w/ diff returns: {diff_events:>10,} ({diff_events/multi*100:.1f}%)")

    # OOS
    n_oos = len(oos_events)
    oos_single = sum(1 for e in oos_events if e["pattern_count"] == 1)
    oos_multi = sum(1 for e in oos_events if e["pattern_count"] > 1)
    oos_returns = [e["return_median"] for e in oos_events]
    print(f"\n{'─' * 70}")
    print("OOS Events ({OOS_START} ~ {OOS_END})".format(OOS_START=OOS_START, OOS_END=OOS_END))
    print(f"{'─' * 70}")
    print(f"  OOS events:              {n_oos:>10,}")
    print(f"  OOS single-pattern:      {oos_single:>10,}")
    print(f"  OOS multi-pattern:       {oos_multi:>10,}")
    print(f"  OOS mean return:         {statistics.mean(oos_returns):>+10.4f}%")
    print(f"  OOS median return:       {statistics.median(oos_returns):>+10.4f}%")
    print(f"  OOS win rate:            {sum(1 for r in oos_returns if r>0)/n_oos*100:>9.2f}%")

    # Regime × event_type breakdown
    print(f"\n{'─' * 70}")
    print("OOS by Regime × Event Type")
    print(f"{'─' * 70}")
    regime_groups = defaultdict(lambda: {"single": [], "multi": []})
    for e in oos_events:
        et = "single" if e["pattern_count"] == 1 else "multi"
        regime_groups[e["market_regime"]][et].append(e["return_median"])
    for regime in sorted(regime_groups):
        g = regime_groups[regime]
        for et in ["single", "multi"]:
            rets = g[et]
            if rets:
                print(f"  {regime:10s} {et:8s}: n={len(rets):>6,}  "
                      f"mean={statistics.mean(rets):>+7.2f}%  "
                      f"wr={sum(1 for r in rets if r>0)/len(rets)*100:>5.1f}%")

    # Evidence grade distribution
    grades = defaultdict(int)
    for r in evidence_rows:
        grades[r["evidence_grade"]] += 1
    print(f"\n{'─' * 70}")
    print("Evidence Grade Distribution")
    print(f"{'─' * 70}")
    for grade in ["STRONG", "MODERATE", "WEAK", "INCONCLUSIVE"]:
        print(f"  {grade:15s}: {grades.get(grade, 0):>5}")

    # Top STRONG evidence (if any)
    strong = [r for r in evidence_rows if r["evidence_grade"] == "STRONG"]
    if strong:
        print(f"\n  STRONG evidence candidates ({len(strong)}):")
        for r in sorted(strong, key=lambda r: -r["n_oos_events"])[:10]:
            ci_lo = f"{r['mean_ci_lower']:+.2f}" if r['mean_ci_lower'] is not None else "N/A"
            ci_hi = f"{r['mean_ci_upper']:+.2f}" if r['mean_ci_upper'] is not None else "N/A"
            print(f"    {r['profile_name']}/{r['pattern_name']}/{r['regime']}: "
                  f"n={r['n_oos_events']} "
                  f"oos_ret={r['oos_mean_return']:+.2f}% "
                  f"ci=[{ci_lo}, {ci_hi}] "
                  f"stability={r['stability']}")

    # Multi-pattern concurrence effect
    print(f"\n{'─' * 70}")
    print("Multi-Pattern Concurrence Effect")
    print(f"{'─' * 70}")
    for r in sorted(multi_rows, key=lambda r: (r["pattern_count"], r.get("regime", ""))):
        ci_lo = f"{r['mean_ci_lower']:>+6.2f}" if r['mean_ci_lower'] is not None else "    N/A"
        ci_hi = f"{r['mean_ci_upper']:>+6.2f}" if r['mean_ci_upper'] is not None else "    N/A"
        print(f"  {r['pattern_count']}p {r.get('regime','?'):10s}: n={r['n_events']:>6,}  "
              f"mean_ret={r['mean_return']:>+7.2f}%  "
              f"wr={r['win_rate']:>5.1f}%  "
              f"ci=[{ci_lo}, {ci_hi}]")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Phase 2B — Event-Level OOS Validation")
    parser.add_argument("--no-bootstrap", action="store_true",
                        help="Skip bootstrap CI computation (faster)")
    args = parser.parse_args()

    global BOOTSTRAP_ITERATIONS
    if args.no_bootstrap:
        BOOTSTRAP_ITERATIONS = 0

    print("Loading trade data...")
    trades = load_trades()
    print(f"  Loaded {len(trades):,} trades")

    print("Loading overlap summary...")
    overlap_rows = load_overlap()
    print(f"  Loaded {len(overlap_rows):,} signal events")

    print("Loading baselines...")
    baselines = load_baselines()
    print(f"  Loaded {len(baselines)} baseline dates")

    print("Loading train/val returns...")
    train_val_returns = load_train_val_returns()
    print(f"  Loaded {len(train_val_returns)} train/val return entries")

    # ── Event aggregation ──
    print("\nAggregating events...")
    events = aggregate_events(trades, overlap_rows, baselines)
    print(f"  Aggregated {len(events):,} unique events")

    # Write event_level_trades.csv
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    write_event_csv(events)

    # ── Filter to OOS ──
    oos_events = [e for e in events if OOS_START <= e["signal_date"] <= OOS_END]
    print(f"\n  OOS events: {len(oos_events):,}")

    # ── Build summaries ──
    print("\nBuilding OOS summaries...")

    print("  event_oos_summary...")
    oos_summary = build_event_oos_summary(oos_events)
    write_oos_summary_csv(oos_summary)

    print("  single_pattern_oos...")
    single_rows = build_single_pattern_oos(oos_events, train_val_returns)
    write_single_pattern_oos_csv(single_rows)

    print("  multipattern_oos...")
    multi_rows = build_multipattern_oos(oos_events)
    write_multipattern_oos_csv(multi_rows)

    print("  pattern_presence_oos...")
    presence_rows = build_pattern_presence_oos(oos_events)
    write_pattern_presence_oos_csv(presence_rows)

    print("  pattern_oos_evidence...")
    evidence_rows = build_pattern_oos_evidence(oos_events, train_val_returns)
    write_pattern_oos_evidence_csv(evidence_rows)

    # ── Print summary ──
    print_summary(events, oos_events, oos_summary, single_rows, multi_rows, evidence_rows)

    print(f"\nPHASE 2B STATUS: PASS")
    print(f"  {len(events):,} events aggregated")
    print(f"  {len(oos_events):,} OOS events analyzed")
    print(f"  {len(evidence_rows)} evidence candidates")
    strong = sum(1 for r in evidence_rows if r["evidence_grade"] == "STRONG")
    moderate = sum(1 for r in evidence_rows if r["evidence_grade"] == "MODERATE")
    print(f"  STRONG={strong} MODERATE={moderate}")


if __name__ == "__main__":
    main()
