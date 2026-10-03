#!/usr/bin/env python3
"""Sector performance analysis for 2026 Apr-Sep window.

Analyzes which sectors performed best in the 6-month test window
and identifies sector rotation patterns.
"""

import json
import sys
from pathlib import Path
from collections import Counter, defaultdict
from typing import TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.stock_universe_full import STOCK_INDUSTRY, get_industry

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KLINE_CACHE = PROJECT_ROOT / "data" / "kline_cache.json"

WINDOW_START = "2026-04-01"
WINDOW_END = "2026-09-30"


def load_klines() -> dict[str, list[dict]]:
    with open(KLINE_CACHE) as f:
        cache = json.load(f)
    result = {}
    for k, v in cache.items():
        sym = "_".join(k.split("_")[:-1])
        result[sym] = v
    return result


def calc_returns(klines: list[dict], start: str, end: str) -> tuple[float, float]:
    """Returns (total_return_pct, positive_days_pct) for a stock in date range."""
    window_bars = [bar for bar in klines if start <= bar["time"] <= end]
    if len(window_bars) < 20:
        return 0.0, 0.0

    # Find first and last close in window
    first_close = window_bars[0]["close"]
    last_close = window_bars[-1]["close"]
    if first_close <= 0:
        return 0.0, 0.0

    total_ret = (last_close / first_close - 1) * 100

    # Positive days
    up_days = sum(1 for bar in window_bars if bar["close"] > bar["open"])
    positive_pct = up_days / len(window_bars) * 100 if window_bars else 0

    return total_ret, positive_pct


def monthly_returns(klines: list[dict]) -> dict[str, float]:
    """Compute monthly returns for each month in the window."""
    months = defaultdict(list)
    for bar in klines:
        if WINDOW_START <= bar["time"] <= WINDOW_END:
            month = bar["time"][:7]  # "2026-04"
            months[month].append(bar)

    result = {}
    for month, bars in sorted(months.items()):
        if len(bars) >= 5:
            first = bars[0]["close"]
            last = bars[-1]["close"]
            if first > 0:
                result[month] = (last / first - 1) * 100
    return result


def main():
    print("=== Sector Performance Analysis: 2026-04-01 to 2026-09-30 ===\n")

    klines = load_klines()

    # Build industry -> stocks mapping
    industry_stocks = defaultdict(list)
    for sym in klines:
        ind = get_industry(sym)
        industry_stocks[ind].append(sym)

    # Compute per-stock returns
    stock_returns: dict[str, tuple[float, float]] = {}
    for sym, bars in klines.items():
        ret, pos_pct = calc_returns(bars, WINDOW_START, WINDOW_END)
        stock_returns[sym] = (ret, pos_pct)

    # Compute per-industry averages
    industry_returns = {}
    industry_details = {}

    for ind, stocks in industry_stocks.items():
        rets = []
        for s in stocks:
            r, pp = stock_returns.get(s, (0, 0))
            if r != 0:
                rets.append(r)

        if rets:
            avg_ret = sum(rets) / len(rets)
            med_ret = sorted(rets)[len(rets)//2]
            top5_avg = sum(sorted(rets, reverse=True)[:max(5, len(rets)//10)]) / max(5, len(rets)//10)
            bot5_avg = sum(sorted(rets)[:max(5, len(rets)//10)]) / max(5, len(rets)//10)
            up_ratio = sum(1 for r in rets if r > 0) / len(rets) * 100

            industry_returns[ind] = (avg_ret, med_ret, len(stocks), len(rets), up_ratio, top5_avg, bot5_avg)
            industry_details[ind] = sorted([(s, stock_returns.get(s, (0,0))[0])
                                            for s in stocks], key=lambda x: x[1], reverse=True)

    # Sort by average return
    sorted_industries = sorted(industry_returns.items(), key=lambda x: x[1][0], reverse=True)

    print(f"{'Industry':<16s} {'AvgRet%':>8s} {'MedRet%':>8s} {'Stocks':>7s} {'WinRate%':>9s} {'Top5Avg%':>9s} {'Bot5Avg%':>9s}")
    print("-" * 80)

    for ind, (avg, med, n_stocks, n_valid, up, top5, bot5) in sorted_industries:
        print(f"{ind:<16s} {avg:>+8.2f} {med:>+8.2f} {n_valid:>5d}/{n_stocks:<3d} {up:>8.1f}% {top5:>+8.2f} {bot5:>+8.2f}")

    # Monthly rotation analysis
    print(f"\n\n=== Monthly Sector Returns ===\n")

    # For each industry, compute monthly returns
    ind_monthly = defaultdict(lambda: defaultdict(list))
    for sym, bars in klines.items():
        ind = get_industry(sym)
        month_rets = monthly_returns(bars)
        for month, ret in month_rets.items():
            ind_monthly[month][ind].append(ret)

    # Average per month per industry
    months = sorted(ind_monthly.keys())
    print(f"{'Industry':<16s}", end="")
    for m in months:
        print(f" {m:>8s}", end="")
    print()
    print("-" * (16 + 11 * len(months)))

    for ind, _ in sorted_industries[:10]:  # top 10
        print(f"{ind:<16s}", end="")
        for m in months:
            rets = ind_monthly[m].get(ind, [])
            avg = sum(rets)/len(rets) if rets else 0
            print(f" {avg:>+8.2f}", end="")
        print()

    # Sector rotation: which industries had the biggest month-to-month swings
    print(f"\n\n=== Sector Rotation Analysis ===\n")
    # For each industry, compute monthly return sequence
    rotations = {}
    for ind in industry_returns:
        monthly_seq = []
        for m in months:
            rets = ind_monthly[m].get(ind, [0])
            monthly_seq.append(sum(rets)/len(rets) if rets else 0)
        if monthly_seq:
            # Volatility of monthly returns = rotation potential
            import statistics
            std_dev = statistics.stdev(monthly_seq) if len(monthly_seq) > 1 else 0
            min_m = min(monthly_seq)
            max_m = max(monthly_seq)
            spread = max_m - min_m
            rotations[ind] = (std_dev, spread, monthly_seq)

    sorted_rotations = sorted(rotations.items(), key=lambda x: x[1][0], reverse=True)
    print(f"{'Industry':<16s} {'StdDev%':>8s} {'Spread%':>8s} Monthly Pattern")
    print("-" * 80)
    for ind, (std, spread, seq) in sorted_rotations:
        seq_str = " -> ".join(f"{v:+5.1f}%" for v in seq)
        print(f"{ind:<16s} {std:>8.2f} {spread:>8.2f} {seq_str}")

    # Top individual stocks
    print(f"\n\n=== Top 20 Individual Stocks (Apr-Sep 2026) ===\n")
    all_stock_rets = [(s, stock_returns[s][0]) for s in stock_returns if stock_returns[s][0] != 0]
    top20 = sorted(all_stock_rets, key=lambda x: x[1], reverse=True)[:20]
    bot20 = sorted(all_stock_rets, key=lambda x: x[1])[:20]

    print(f"{'Stock':<16s} {'Industry':<16s} {'Return%':>8s}")
    print("-" * 44)
    for s, r in top20:
        print(f"{s:<16s} {get_industry(s):<16s} {r:>+8.2f}")

    print(f"\n=== Bottom 20 Individual Stocks ===\n")
    print(f"{'Stock':<16s} {'Industry':<16s} {'Return%':>8s}")
    print("-" * 44)
    for s, r in bot20:
        print(f"{s:<16s} {get_industry(s):<16s} {r:>+8.2f}")

    # BJ sector separate analysis
    print(f"\n\n=== 北交所 (BJ) Sector Analysis ===\n")
    bj_stocks = [s for s in klines if s.endswith('.BJ')]
    bj_returns = []
    for s in bj_stocks:
        r, pp = calc_returns(klines[s], WINDOW_START, WINDOW_END)
        if r != 0:
            bj_returns.append((s, r, pp))

    if bj_returns:
        avg_bj = sum(r for _, r, _ in bj_returns) / len(bj_returns)
        med_bj = sorted(bj_returns, key=lambda x: x[1])[len(bj_returns)//2][1]
        up_pct = sum(1 for _, r, _ in bj_returns if r > 0) / len(bj_returns) * 100
        print(f"BJ stocks with valid data: {len(bj_returns)}")
        print(f"BJ average return: {avg_bj:+.2f}%")
        print(f"BJ median return: {med_bj:+.2f}%")
        print(f"BJ win rate: {up_pct:.1f}%")

        top_bj = sorted(bj_returns, key=lambda x: x[1], reverse=True)[:10]
        print(f"\nTop 10 BJ stocks:")
        for s, r, pp in top_bj:
            print(f"  {s:<16s} {r:>+8.2f}% ({pp:.0f}% up days)")

    # Save results for later use
    results = {
        "industry_returns": {ind: {"avg": avg, "median": med, "stocks": stocks,
                                    "valid": valid, "win_rate": up, "top5_avg": top5, "bot5_avg": bot5}
                           for ind, (avg, med, stocks, valid, up, top5, bot5) in industry_returns.items()},
        "top20_stocks": [(s, r) for s, r in top20],
        "bottom20_stocks": [(s, r) for s, r in bot20],
        "monthly_industry": {m: {ind: sum(rets)/len(rets) for ind, rets in data.items()}
                            for m, data in ind_monthly.items()},
        "bj_analysis": {
            "count": len(bj_returns),
            "avg_return": sum(r for _, r, _ in bj_returns) / len(bj_returns) if bj_returns else 0,
            "top10": [(s, r) for s, r, _ in top_bj] if bj_returns else [],
        }
    }

    out_path = PROJECT_ROOT / "data" / "sector_analysis.json"
    with open(out_path, "w") as f:
        json.dump(results, f, ensure_ascii=False)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
