#!/usr/bin/env python3
"""
Phase 2A — Regime × Pattern Historical Outcome Analyzer.

Strict single-trade analysis: for every historical pattern trigger, simulate
one independent trade (T+1 open entry → existing sell rules exit) and record
the outcome. No portfolio simulation, no position sizing, no cash management.

Outputs:
  --profile MODE:  results/pattern_trades.csv + pattern_summary.json
  --all MODE:      results/pattern_all_trades.csv + pattern_regime_summary.csv

Usage:
    python3 scripts/pattern_analyzer.py --profile momentum_v5
    python3 scripts/pattern_analyzer.py --all
    python3 scripts/pattern_analyzer.py --all --start 2025-01-01 --end 2025-12-31
    python3 scripts/pattern_analyzer.py --profile single_yang --min-score 70
    python3 scripts/pattern_analyzer.py --list-profiles
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.strategy import SellRules, _sf, get_regime, screen_candidates
from core.strategy_profiles import get_profile, list_profiles
from core.trading_calendar import TradingCalendar

# ── Paths ──
CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "kline_cache.json"
RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

# Profiles excluded from --all (multi-strategy composites)
ALL_EXCLUDE = {"ensemble_top3", "notes_ensemble", "multi"}

# MCP index cache
_MCP_CACHE: dict[str, list[dict]] = {}


def fetch_klines(symbol: str, count: int = 500, retries: int = 3) -> list[dict]:
    """Fetch K-line data via MCP client (same as backtest.py)."""
    key = f"{symbol}_{count}"
    if key in _MCP_CACHE:
        return _MCP_CACHE[key]

    for attempt in range(retries):
        try:
            from mcp_client import get_mcp_client
            raw = get_mcp_client().call(
                "fetch_kline",
                {"symbol": symbol, "period": "D", "count": count},
            )
            if isinstance(raw, dict):
                k = raw.get("klines", [])
                if k:
                    _MCP_CACHE[key] = k
                    return k
            if isinstance(raw, list):
                _MCP_CACHE[key] = raw
                return raw
        except Exception as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * 2
                print(f"    [Retry {attempt + 1}/{retries}] {symbol}: {e}, wait {wait}s")
                time.sleep(wait)

    print(f"  WARNING: Failed to fetch {symbol} after {retries} retries")
    return []


# ═══════════════════════════════════════════════════════════════
# Trade record
# ═══════════════════════════════════════════════════════════════

@dataclass
class TradeRecord:
    symbol: str
    pattern_date: str           # T — when pattern triggered
    entry_date: str             # T+1 — actual entry
    entry_price: float
    exit_date: str
    exit_price: float
    holding_days: int
    return_pct: float
    exit_reason: str
    pattern_score: float = 0.0
    pattern_grade: str = ""
    pattern_name: str = ""
    market_regime: str = ""
    profile_name: str = ""      # which StrategyProfile generated this
    no_entry_reason: str = ""   # non-empty if NO_ENTRY

    def is_executed(self) -> bool:
        return self.no_entry_reason == ""


# ═══════════════════════════════════════════════════════════════
# Data loading
# ═══════════════════════════════════════════════════════════════

def load_cache() -> dict[str, list[dict]]:
    if CACHE_FILE.exists():
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def build_calendar(index_bars: list[dict], start_date: str, end_date: str) -> TradingCalendar:
    """Build calendar from ALL available index dates (not filtered to end_date).

    We need dates beyond end_date because T+1 entries near end_date may
    fall outside the analysis window. The scanning loop filters to start_date..end_date.
    """
    dates = sorted({
        str(b.get("time", ""))
        for b in index_bars
        if str(b.get("time", "")) >= start_date  # Only filter lower bound
    })
    return TradingCalendar(dates)


def find_bar(bars: list[dict], date: str) -> dict | None:
    for b in bars:
        if str(b.get("time", "")) == date:
            return b
    return None


# ═══════════════════════════════════════════════════════════════
# Exit simulation (unchanged from v1 — same as backtest)
# ═══════════════════════════════════════════════════════════════

def simulate_exit(
    symbol: str,
    entry_date: str,
    entry_price: float,
    pattern_result: dict,
    sell_rules: SellRules,
    all_bars: dict[str, list[dict]],
    calendar: TradingCalendar,
) -> TradeRecord:
    """Simulate exit for a single position from entry_date forward."""
    bars = all_bars.get(symbol, [])
    future_bars = [b for b in bars if str(b.get("time", "")) >= entry_date]
    if len(future_bars) < 2:
        last_bar = future_bars[-1] if future_bars else {"time": entry_date, "close": entry_price}
        return TradeRecord(
            symbol=symbol, pattern_date="", entry_date=entry_date,
            entry_price=entry_price, exit_date=str(last_bar.get("time", "")),
            exit_price=_sf(last_bar.get("close", entry_price)),
            holding_days=0, return_pct=0.0, exit_reason="END_OF_DATA",
            pattern_score=pattern_result.get("score", 0),
            pattern_grade=pattern_result.get("grade", ""),
            pattern_name=pattern_result.get("name", ""),
        )

    pos = {
        "ep": entry_price,
        "ed": entry_date,
        "mp": entry_price,
        "tp": pattern_result.get("target_pct", 8),
        "sp": pattern_result.get("stop_pct", -2.8),
    }

    for bar in future_bars[1:]:
        bar_date = str(bar.get("time", ""))
        hi = _sf(bar.get("high"))
        lo = _sf(bar.get("low"))
        cl = _sf(bar.get("close"))

        if hi > pos["mp"]:
            pos["mp"] = hi

        hold = calendar.trading_days_between(entry_date, bar_date) - 1
        if hold <= 0:
            continue

        sell, price, reason = sell_rules.evaluate(pos, hi, lo, cl, hold)
        if sell:
            ret = (price / entry_price - 1) * 100
            return TradeRecord(
                symbol=symbol, pattern_date="", entry_date=entry_date,
                entry_price=entry_price, exit_date=bar_date, exit_price=price,
                holding_days=hold, return_pct=round(ret, 2), exit_reason=reason,
                pattern_score=pattern_result.get("score", 0),
                pattern_grade=pattern_result.get("grade", ""),
                pattern_name=pattern_result.get("name", ""),
            )

    last_bar = future_bars[-1]
    last_date = str(last_bar.get("time", ""))
    last_close = _sf(last_bar.get("close"))
    last_hold = calendar.trading_days_between(entry_date, last_date) - 1
    ret = (last_close / entry_price - 1) * 100
    return TradeRecord(
        symbol=symbol, pattern_date="", entry_date=entry_date,
        entry_price=entry_price, exit_date=last_date, exit_price=last_close,
        holding_days=max(0, last_hold), return_pct=round(ret, 2),
        exit_reason="END_OF_DATA",
        pattern_score=pattern_result.get("score", 0),
        pattern_grade=pattern_result.get("grade", ""),
        pattern_name=pattern_result.get("name", ""),
    )


# ═══════════════════════════════════════════════════════════════
# Single-profile analysis
# ═══════════════════════════════════════════════════════════════

def run_analysis(
    profile_name: str = "momentum_v5",
    start_date: str = "2024-10-01",
    end_date: str = "2026-10-01",
    min_score: int = 60,
    min_bars: int = 60,
    all_bars: dict[str, list[dict]] | None = None,
    index_bars: list[dict] | None = None,
    calendar: TradingCalendar | None = None,
    quiet: bool = False,
) -> tuple[list[TradeRecord], dict]:
    """Run pattern historical outcome analysis for a single profile.

    Returns:
        (trades, summary) — trades includes both executed and NO_ENTRY records.
    """
    prof = get_profile(profile_name)
    sell_rules = SellRules(prof.sell_rules)
    profile_params = prof.default_params

    if not quiet:
        print(f"  {profile_name}: {prof.description}")
        print(f"    Date: {start_date} ~ {end_date}  Min score: {min_score}")

    # ── Load data (or use pre-loaded) ──
    if all_bars is None or index_bars is None or calendar is None:
        cache = load_cache()
        if not cache:
            print("ERROR: kline_cache.json not found or empty")
            return [], {}

        all_bars = {}
        for key, bars in cache.items():
            sym = key.rsplit("_", 1)[0] if "_" in key else key
            if len(bars) >= min_bars:
                all_bars[sym] = bars

        # Fetch index data via MCP (same as backtest.py)
        print("  Fetching 000001.SH index data...")
        index_bars = fetch_klines("000001.SH", 500)
        if not index_bars:
            print("ERROR: No 000001.SH index data from MCP")
            return [], {}

        calendar = build_calendar(index_bars, start_date, end_date)

    trading_days = [d for d in calendar.dates if start_date <= d <= end_date]
    if not quiet:
        print(f"    Trading days in range: {len([d for d in trading_days if d >= start_date])}")

    # ── Scan for patterns ──
    trades: list[TradeRecord] = []
    total_signals = 0
    no_entry_count = 0

    screen_fn = prof.screen_fn or screen_candidates
    score_fn = prof.score_fn

    for di, dt_ in enumerate(trading_days):
        # PIT-safe: only bars <= dt_
        regime = get_regime(index_bars, dt_)
        candidates = screen_fn(all_bars, dt_, min_vr=1.2, min_close=8.0)
        T1 = calendar.next_trading_day(dt_)
        if T1 is None:
            continue

        for sym in candidates:
            lb = [b for b in all_bars.get(sym, []) if str(b.get("time", "")) <= dt_]
            if len(lb) < 25:
                continue

            result = score_fn(lb, profile_params)
            if result.get("grade") in ("D", "C") or result.get("score", 0) < min_score:
                continue

            total_signals += 1

            # ── Entry: T+1 open ──
            entry_bar = find_bar(all_bars.get(sym, []), T1)
            if not entry_bar:
                trades.append(TradeRecord(
                    symbol=sym, pattern_date=dt_, entry_date=T1,
                    entry_price=0, exit_date="", exit_price=0,
                    holding_days=0, return_pct=0, exit_reason="",
                    pattern_score=result.get("score", 0),
                    pattern_grade=result.get("grade", ""),
                    pattern_name=result.get("name", ""),
                    market_regime=regime, profile_name=profile_name,
                    no_entry_reason="NO_ENTRY: missing T+1 bar",
                ))
                no_entry_count += 1
                continue

            entry_price = _sf(entry_bar.get("open"))
            entry_vol = _sf(entry_bar.get("volume"))

            if entry_price <= 0:
                trades.append(TradeRecord(
                    symbol=sym, pattern_date=dt_, entry_date=T1,
                    entry_price=0, exit_date="", exit_price=0,
                    holding_days=0, return_pct=0, exit_reason="",
                    pattern_score=result.get("score", 0),
                    pattern_grade=result.get("grade", ""),
                    pattern_name=result.get("name", ""),
                    market_regime=regime, profile_name=profile_name,
                    no_entry_reason="NO_ENTRY: invalid open price",
                ))
                no_entry_count += 1
                continue

            if entry_vol <= 0:
                trades.append(TradeRecord(
                    symbol=sym, pattern_date=dt_, entry_date=T1,
                    entry_price=0, exit_date="", exit_price=0,
                    holding_days=0, return_pct=0, exit_reason="",
                    pattern_score=result.get("score", 0),
                    pattern_grade=result.get("grade", ""),
                    pattern_name=result.get("name", ""),
                    market_regime=regime, profile_name=profile_name,
                    no_entry_reason="NO_ENTRY: suspended (zero volume)",
                ))
                no_entry_count += 1
                continue

            # ── Simulate exit ──
            trade = simulate_exit(sym, T1, entry_price, result, sell_rules, all_bars, calendar)
            trade.pattern_date = dt_
            trade.market_regime = regime
            trade.profile_name = profile_name
            trades.append(trade)

    if not quiet:
        print(f"    {total_signals} signals, {total_signals - no_entry_count} executed, "
              f"{no_entry_count} no_entry")

    # ── Compute summary ──
    executed = [t for t in trades if t.is_executed()]
    wins = [t for t in executed if t.return_pct > 0]
    losses = [t for t in executed if t.return_pct <= 0]

    # By exit reason
    by_reason: dict[str, dict] = {}
    for t in executed:
        reason_key = t.exit_reason.split("(")[0] if "(" in t.exit_reason else t.exit_reason
        reason_key = reason_key.split(":")[0].strip() if ":" in reason_key else reason_key
        if reason_key not in by_reason:
            by_reason[reason_key] = {"count": 0, "wins": 0, "total_return": 0.0}
        by_reason[reason_key]["count"] += 1
        by_reason[reason_key]["total_return"] += t.return_pct
        if t.return_pct > 0:
            by_reason[reason_key]["wins"] += 1
    for k in by_reason:
        by_reason[k]["avg_return"] = round(by_reason[k]["total_return"] / by_reason[k]["count"], 2)
        by_reason[k]["win_rate"] = round(by_reason[k]["wins"] / by_reason[k]["count"] * 100, 1)

    # By regime
    by_regime: dict[str, dict] = {}
    for t in executed:
        reg = t.market_regime or "unknown"
        if reg not in by_regime:
            by_regime[reg] = {"count": 0, "wins": 0, "total_return": 0.0}
        by_regime[reg]["count"] += 1
        by_regime[reg]["total_return"] += t.return_pct
        if t.return_pct > 0:
            by_regime[reg]["wins"] += 1
    for k in by_regime:
        by_regime[k]["avg_return"] = round(by_regime[k]["total_return"] / by_regime[k]["count"], 2)
        by_regime[k]["win_rate"] = round(by_regime[k]["wins"] / by_regime[k]["count"] * 100, 1)

    returns = [t.return_pct for t in executed]
    returns_sorted = sorted(returns)

    summary = {
        "profile": profile_name,
        "date_range": f"{start_date} ~ {end_date}",
        "total_signals": total_signals,
        "executed_trades": len(executed),
        "no_entry": no_entry_count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(executed) * 100, 2) if executed else 0,
        "average_return": round(sum(returns) / len(returns), 2) if returns else 0,
        "median_return": round(returns_sorted[len(returns_sorted) // 2], 2) if returns_sorted else 0,
        "average_win": round(sum(t.return_pct for t in wins) / len(wins), 2) if wins else 0,
        "average_loss": round(sum(t.return_pct for t in losses) / len(losses), 2) if losses else 0,
        "max_win": round(max(returns), 2) if returns else 0,
        "max_loss": round(min(returns), 2) if returns else 0,
        "average_holding_days": round(sum(t.holding_days for t in executed) / len(executed), 1) if executed else 0,
        "median_holding_days": sorted([t.holding_days for t in executed])[len(executed) // 2] if executed else 0,
        "by_exit_reason": by_reason,
        "by_regime": by_regime,
    }

    return trades, summary


# ═══════════════════════════════════════════════════════════════
# All-profiles analysis
# ═══════════════════════════════════════════════════════════════

def run_all_analysis(
    start_date: str = "2024-10-01",
    end_date: str = "2026-10-01",
    min_score: int = 60,
    min_bars: int = 60,
) -> tuple[list[TradeRecord], list[dict]]:
    """Run pattern analysis on ALL non-ensemble profiles.

    Returns:
        (all_trades, profile_summaries)
    """
    profile_names = [p for p in list_profiles() if p not in ALL_EXCLUDE]
    print(f"Phase 2A — Regime × Pattern Historical Analysis")
    print(f"  Profiles: {', '.join(profile_names)}")
    print(f"  Date range: {start_date} ~ {end_date}")
    print(f"  Min score: {min_score}\n")

    # ── Load data once ──
    print("Loading kline_cache.json...")
    cache = load_cache()
    if not cache:
        print("ERROR: kline_cache.json not found or empty")
        return [], []

    all_bars: dict[str, list[dict]] = {}
    for key, bars in cache.items():
        sym = key.rsplit("_", 1)[0] if "_" in key else key
        if len(bars) >= min_bars:
            all_bars[sym] = bars
    print(f"  Loaded {len(all_bars)} symbols with >= {min_bars} bars")

    # ── Fetch index data via MCP ──
    print("Fetching 000001.SH index data via MCP...")
    index_bars = fetch_klines("000001.SH", 500)
    if not index_bars:
        print("ERROR: No 000001.SH index data from MCP")
        return [], []

    calendar = build_calendar(index_bars, start_date, end_date)
    print(f"  Index bars: {len(index_bars)}, in range: {len(calendar.dates)}")

    # ── Run each profile ──
    all_trades: list[TradeRecord] = []
    summaries: list[dict] = []

    for i, pname in enumerate(profile_names):
        print(f"[{i + 1}/{len(profile_names)}] ", end="")
        trades, summary = run_analysis(
            profile_name=pname,
            start_date=start_date,
            end_date=end_date,
            min_score=min_score,
            min_bars=min_bars,
            all_bars=all_bars,
            index_bars=index_bars,
            calendar=calendar,
            quiet=False,
        )
        all_trades.extend(trades)
        summaries.append(summary)

    return all_trades, summaries


# ═══════════════════════════════════════════════════════════════
# Regime × Pattern summary builder
# ═══════════════════════════════════════════════════════════════

def build_regime_pattern_summary(trades: list[TradeRecord]) -> list[dict]:
    """Build Regime × Pattern × Year grouped statistics.

    Returns list of rows suitable for CSV export, sorted by regime, pattern, year.
    """
    executed = [t for t in trades if t.is_executed()]

    # Group by (market_regime, pattern_name, year)
    groups: dict[tuple[str, str, str], list[TradeRecord]] = defaultdict(list)
    # Also track total signals (including no_entry)
    signal_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for t in trades:
        year = t.pattern_date[:4]
        regime = t.market_regime or "unknown"
        pattern = t.pattern_name or "unknown"
        key = (regime, pattern, year)
        groups[key].append(t) if t.is_executed() else None
        signal_counts[key] += 1

    rows = []
    for (regime, pattern, year), etrades in sorted(groups.items()):
        if not etrades:
            continue
        returns = [t.return_pct for t in etrades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]
        holding_days = [t.holding_days for t in etrades]
        n = len(etrades)
        sample_n = signal_counts.get((regime, pattern, year), n)

        rows.append({
            "market_regime": regime,
            "pattern_name": pattern,
            "year": year,
            "sample_count": sample_n,
            "executed_count": n,
            "win_count": len(wins),
            "loss_count": len(losses),
            "win_rate": round(len(wins) / n * 100, 2),
            "average_return": round(statistics.mean(returns), 2),
            "median_return": round(statistics.median(returns), 2),
            "average_win": round(statistics.mean(wins), 2) if wins else 0,
            "average_loss": round(statistics.mean(losses), 2) if losses else 0,
            "average_holding_days": round(statistics.mean(holding_days), 1),
            "median_holding_days": round(statistics.median(holding_days), 1),
        })

    # Sort: regime, pattern, year
    rows.sort(key=lambda r: (r["market_regime"], r["pattern_name"], r["year"]))
    return rows


def print_regime_pattern_table(rows: list[dict]):
    """Print a formatted summary table."""
    # Group by regime
    by_regime: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_regime[r["market_regime"]].append(r)

    regime_order = ["euphoria", "hot", "warmup", "cooldown", "ice", "unknown"]

    print(f"\n{'=' * 110}")
    print("Regime × Pattern Summary")
    print(f"{'=' * 110}")

    for regime in regime_order:
        if regime not in by_regime:
            continue
        entries = by_regime[regime]
        # Aggregate across years per pattern
        by_pattern: dict[str, dict] = {}
        for e in entries:
            p = e["pattern_name"]
            if p not in by_pattern:
                by_pattern[p] = {
                    "sample_count": 0, "executed_count": 0, "win_count": 0,
                    "loss_count": 0, "returns": [], "holding_days": [],
                }
            bp = by_pattern[p]
            bp["sample_count"] += e["sample_count"]
            bp["executed_count"] += e["executed_count"]
            bp["win_count"] += e["win_count"]
            bp["loss_count"] += e["loss_count"]
            bp["returns"].extend([e["average_return"]] * e["executed_count"])
            bp["holding_days"].extend([e["average_holding_days"]] * e["executed_count"])

        print(f"\n  [{regime}]")
        print(f"  {'Pattern':<22} {'Samples':>7} {'Exec':>6} {'WR%':>7} {'AvgR%':>8} "
              f"{'MedR%':>8} {'AvgW%':>8} {'AvgL%':>8} {'AvgHold':>8}")
        print(f"  {'-' * 90}")
        for pname, stats in sorted(by_pattern.items()):
            n = stats["executed_count"]
            rets = stats["returns"]
            holds = stats["holding_days"]
            if n == 0:
                continue
            wins_r = [r for r in rets if r > 0]
            losses_r = [r for r in rets if r <= 0]
            avg_w_str = f"{statistics.mean(wins_r):>+7.2f}%" if wins_r else f"{'+0.00':>8}%"
            avg_l_str = f"{statistics.mean(losses_r):>+7.2f}%" if losses_r else f"{'+0.00':>8}%"
            print(f"  {pname:<22} {stats['sample_count']:>7} {n:>6} "
                  f"{stats['win_count'] / n * 100:>6.1f}% "
                  f"{statistics.mean(rets):>+7.2f}% "
                  f"{statistics.median(rets):>+7.2f}% "
                  f"{avg_w_str} "
                  f"{avg_l_str} "
                  f"{statistics.mean(holds):>7.1f}d")


# ═══════════════════════════════════════════════════════════════
# PIT mutation test
# ═══════════════════════════════════════════════════════════════

def pit_mutation_test(profile_name: str) -> dict:
    """Verify that modifying T+1 data does not change T-day pattern detection."""
    prof = get_profile(profile_name)
    cache = load_cache()

    test_sym = None
    for key in cache:
        sym = key.rsplit("_", 1)[0] if "_" in key else key
        if len(cache[key]) >= 120:
            test_sym = sym
            break

    if not test_sym:
        return {"status": "SKIP", "reason": "No symbol with sufficient data"}

    bars = cache[f"{test_sym}_500"] if f"{test_sym}_500" in cache else cache[test_sym]
    test_date = str(bars[100].get("time", ""))
    bars_up_to_T = [b for b in bars if str(b.get("time", "")) <= test_date]

    result_a = prof.score_fn(bars_up_to_T, prof.default_params)

    bars_mutated = list(bars_up_to_T)
    # Append a fake future bar with same OHLCV as last real bar (only date differs)
    fake_bar = dict(bars_up_to_T[-1])
    fake_bar["time"] = "2999-01-01"
    bars_mutated.append(fake_bar)
    result_b = prof.score_fn(bars_mutated, prof.default_params)

    unchanged = (
        result_a.get("score") == result_b.get("score")
        and result_a.get("grade") == result_b.get("grade")
    )

    return {
        "status": "PASS" if unchanged else "FAIL",
        "symbol": test_sym,
        "test_date": test_date,
        "score_before": result_a.get("score"),
        "score_after": result_b.get("score"),
        "grade_before": result_a.get("grade"),
        "grade_after": result_b.get("grade"),
    }


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Phase 2A — Regime × Pattern Historical Analyzer")
    parser.add_argument("--profile", default=None,
                        help="Single strategy profile to analyze")
    parser.add_argument("--all", action="store_true",
                        help="Run analysis on ALL non-ensemble profiles")
    parser.add_argument("--start", default="2024-10-01",
                        help="Start date (default: 2024-10-01)")
    parser.add_argument("--end", default="2026-10-01",
                        help="End date (default: 2026-10-01)")
    parser.add_argument("--min-score", type=int, default=60,
                        help="Minimum score threshold (default: 60)")
    parser.add_argument("--list-profiles", action="store_true",
                        help="List available profiles")
    parser.add_argument("--pit-test", action="store_true",
                        help="Run PIT mutation test only")
    args = parser.parse_args()

    if args.list_profiles:
        print("Available strategy profiles:")
        for name in list_profiles():
            p = get_profile(name)
            tag = " [MULTI]" if name in ALL_EXCLUDE else ""
            print(f"  {name:<22}{tag} {p.description}")
            print(f"                     source: {p.source}")
        return

    if args.pit_test:
        profile = args.profile or "momentum_v5"
        print("PIT Mutation Test")
        print("=" * 60)
        result = pit_mutation_test(profile)
        for k, v in result.items():
            print(f"  {k}: {v}")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    if args.all:
        # ── Run ALL profiles ──
        all_trades, summaries = run_all_analysis(
            start_date=args.start,
            end_date=args.end,
            min_score=args.min_score,
        )

        if not all_trades:
            print("No trades generated across any profile.")
            return

        executed = [t for t in all_trades if t.is_executed()]

        # ── Save all trades CSV ──
        trades_csv = RESULTS_DIR / "pattern_all_trades.csv"
        with open(trades_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "symbol", "pattern_date", "entry_date", "entry_price",
                "exit_date", "exit_price", "holding_days", "return_pct",
                "exit_reason", "pattern_score", "pattern_grade",
                "pattern_name", "market_regime", "profile_name",
            ])
            for t in executed:
                writer.writerow([
                    t.symbol, t.pattern_date, t.entry_date, t.entry_price,
                    t.exit_date, t.exit_price, t.holding_days, t.return_pct,
                    t.exit_reason, t.pattern_score, t.pattern_grade,
                    t.pattern_name, t.market_regime, t.profile_name,
                ])
        print(f"\nAll trades CSV: {trades_csv} ({len(executed)} executed trades)")

        # ── Save Regime × Pattern summary CSV ──
        summary_rows = build_regime_pattern_summary(all_trades)
        summary_csv = RESULTS_DIR / "pattern_regime_summary.csv"
        with open(summary_csv, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "market_regime", "pattern_name", "year",
                "sample_count", "executed_count", "win_count", "loss_count",
                "win_rate", "average_return", "median_return",
                "average_win", "average_loss",
                "average_holding_days", "median_holding_days",
            ])
            for row in summary_rows:
                writer.writerow([
                    row["market_regime"], row["pattern_name"], row["year"],
                    row["sample_count"], row["executed_count"],
                    row["win_count"], row["loss_count"],
                    row["win_rate"], row["average_return"], row["median_return"],
                    row["average_win"], row["average_loss"],
                    row["average_holding_days"], row["median_holding_days"],
                ])
        print(f"Regime × Pattern summary CSV: {summary_csv} ({len(summary_rows)} rows)")

        # ── Print summary table ──
        print_regime_pattern_table(summary_rows)

        # ── Per-profile summaries ──
        print(f"\n{'=' * 60}")
        print("Per-Profile Summary")
        print(f"{'=' * 60}")
        for s in sorted(summaries, key=lambda s: -s["executed_trades"]):
            print(f"  {s['profile']:<22} signals={s['total_signals']:>5}  "
                  f"exec={s['executed_trades']:>5}  "
                  f"wr={s['win_rate']:>6.1f}%  "
                  f"avg={s['average_return']:>+7.2f}%  "
                  f"med={s['median_return']:>+7.2f}%  "
                  f"hold={s['average_holding_days']:>5.1f}d")

        # ── Save all summaries JSON ──
        json_path = RESULTS_DIR / "pattern_all_summary.json"
        with open(json_path, "w") as f:
            json.dump(summaries, f, indent=2, ensure_ascii=False)
        print(f"\nAll summaries JSON: {json_path}")

    else:
        # ── Single profile mode ──
        profile = args.profile or "momentum_v5"
        trades, summary = run_analysis(
            profile_name=profile,
            start_date=args.start,
            end_date=args.end,
            min_score=args.min_score,
        )

        if not trades:
            print("No trades generated.")
            return

        executed = [t for t in trades if t.is_executed()]

        # ── Save trades CSV ──
        csv_path = RESULTS_DIR / "pattern_trades.csv"
        with open(csv_path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "symbol", "pattern_date", "entry_date", "entry_price",
                "exit_date", "exit_price", "holding_days", "return_pct",
                "exit_reason", "pattern_score", "pattern_grade",
                "pattern_name", "market_regime",
            ])
            for t in executed:
                writer.writerow([
                    t.symbol, t.pattern_date, t.entry_date, t.entry_price,
                    t.exit_date, t.exit_price, t.holding_days, t.return_pct,
                    t.exit_reason, t.pattern_score, t.pattern_grade,
                    t.pattern_name, t.market_regime,
                ])
        print(f"\nTrade CSV: {csv_path} ({len(executed)} executed trades)")

        # ── Save summary JSON ──
        json_path = RESULTS_DIR / "pattern_summary.json"
        with open(json_path, "w") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        print(f"Summary JSON: {json_path}")

        # ── Print summary ──
        print(f"\n{'=' * 60}")
        print(f"Pattern Analysis Summary: {profile}")
        print(f"{'=' * 60}")
        print(f"  Date range:        {summary['date_range']}")
        print(f"  Total signals:     {summary['total_signals']}")
        print(f"  Executed trades:   {summary['executed_trades']}")
        print(f"  No entry:          {summary['no_entry']}")
        print(f"  Win rate:          {summary['win_rate']:.1f}%")
        print(f"  Average return:    {summary['average_return']:+.2f}%")
        print(f"  Median return:     {summary['median_return']:+.2f}%")
        print(f"  Average win:       {summary['average_win']:+.2f}%")
        print(f"  Average loss:      {summary['average_loss']:+.2f}%")
        print(f"  Max win:           {summary['max_win']:+.2f}%")
        print(f"  Max loss:          {summary['max_loss']:+.2f}%")
        print(f"  Avg holding days:  {summary['average_holding_days']:.1f}")
        print(f"  Median hold days:  {summary['median_holding_days']}")
        print(f"\n  By exit reason:")
        for reason, stats in sorted(summary["by_exit_reason"].items(), key=lambda x: -x[1]["count"]):
            print(f"    {reason:<20} n={stats['count']:>5}  wr={stats['win_rate']:>5.1f}%  "
                  f"avg={stats['avg_return']:>+7.2f}%")

        # ── Show Regime × Pattern for single profile ──
        regime_rows = build_regime_pattern_summary(trades)
        if regime_rows:
            print(f"\n  By regime:")
            for r in regime_rows:
                print(f"    {r['market_regime']:<12} {r['pattern_name']:<20} "
                      f"n={r['executed_count']:>4}  wr={r['win_rate']:>5.1f}%  "
                      f"avg={r['average_return']:>+7.2f}%  hold={r['average_holding_days']:>5.1f}d")

        # ── PIT test ──
        print(f"\n{'=' * 60}")
        print("PIT Mutation Test")
        print(f"{'=' * 60}")
        pit_result = pit_mutation_test(profile)
        for k, v in pit_result.items():
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
