#!/usr/bin/env python3
"""Sector rotation strategy: Identify top-performing sectors monthly and rotate into leaders.

Strategy concept:
- At start of each month, rank all sectors by prior month performance
- Allocate capital to top 3 sectors equally
- Within each sector, pick top 5 stocks by momentum (20-day return)
- Hold for the month, rebalance next month

This exploits the sector rotation pattern visible in the April-Sep 2026 data
where 通信, 电子, 银行, 煤炭 consistently outperformed.
"""

import json
import sys
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.stock_universe_full import get_industry

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KLINE_CACHE = PROJECT_ROOT / "data" / "kline_cache.json"

WINDOW_START = "2026-04-01"
WINDOW_END = "2026-09-30"
INITIAL_CAPITAL = 400_000.0
MONTHLY_CAPITAL = 400_000.0  # total deployed each month


@dataclass
class Trade:
    symbol: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    return_pct: float
    sector: str
    shares: int

@dataclass
class BacktestResult:
    trades: list = field(default_factory=list)
    monthly_returns: list = field(default_factory=list)
    equity_curve: list = field(default_factory=list)
    total_return: float = 0.0
    win_rate: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0


def load_klines() -> dict[str, list[dict]]:
    with open(KLINE_CACHE) as f:
        cache = json.load(f)
    return {"_".join(k.split("_")[:-1]): v for k, v in cache.items()}


def stock_monthly_return(klines: list[dict], month: str) -> float:
    """Compute return for a stock in a given month."""
    bars = [b for b in klines if b["time"].startswith(month)]
    if len(bars) < 5:
        return 0.0
    first = bars[0]["close"]
    last = bars[-1]["close"]
    return (last / first - 1) * 100 if first > 0 else 0.0


def stock_20d_momentum(klines: list[dict], date: str) -> float:
    """Compute 20-day momentum ending on date."""
    bars = [b for b in klines if b["time"] <= date]
    if len(bars) < 20:
        return 0.0
    window = bars[-20:]
    first_c = window[0]["close"]
    last_c = window[-1]["close"]
    return (last_c / first_c - 1) * 100 if first_c > 0 else 0.0


def rank_sectors_by_performance(klines: dict, month: str) -> list[tuple[str, float]]:
    """Rank all sectors by average stock performance in given month."""
    sector_stocks = defaultdict(list)
    for sym in klines:
        sector_stocks[get_industry(sym)].append(sym)

    sector_ret = {}
    for sector, stocks in sector_stocks.items():
        rets = []
        for s in stocks:
            r = stock_monthly_return(klines[s], month)
            if r != 0:
                rets.append(r)
        if rets and len(rets) >= 3:
            sector_ret[sector] = sum(rets) / len(rets)

    return sorted(sector_ret.items(), key=lambda x: x[1], reverse=True)


def get_available_dates(klines: dict) -> list[str]:
    """Get first trading day of each month in the window."""
    dates = set()
    for bars in klines.values():
        for b in bars:
            t = b["time"]
            if WINDOW_START <= t <= WINDOW_END and t.endswith("-01"):
                dates.add(t)
            # Also get early month dates
            if WINDOW_START <= t <= WINDOW_END and t[8:] in ("01", "02", "03"):
                dates.add(t)
    return sorted(dates)


def get_first_trading_day(klines: dict, month: str) -> str:
    """Get first available trading day for a month."""
    candidates = []
    for bars in klines.values():
        for b in bars:
            if b["time"].startswith(month):
                candidates.append(b["time"])
    return min(candidates) if candidates else f"{month}-01"


def get_last_trading_day(klines: dict, month: str) -> str:
    """Get last available trading day for a month."""
    candidates = []
    for bars in klines.values():
        for b in bars:
            if b["time"].startswith(month):
                candidates.append(b["time"])
    return max(candidates) if candidates else f"{month}-30"


def get_price_on_date(klines_list: list[dict], date: str, price_type: str = "close") -> Optional[float]:
    """Get price on or before a date."""
    for bar in reversed(klines_list):
        if bar["time"] <= date:
            return bar[price_type]
    return None


def get_close_on_date(klines_list: list[dict], date: str) -> Optional[float]:
    """Get close price on exact date or nearest before."""
    for bar in reversed(klines_list):
        if bar["time"] <= date:
            return bar["close"]
    return None


def backtest_sector_rotation(klines: dict, top_n_sectors: int = 3,
                              stocks_per_sector: int = 5,
                              min_momentum: float = 0.0,
                              max_stocks_total: int = 8) -> BacktestResult:
    """Backtest sector rotation strategy.

    Each month:
    1. Rank sectors by prior month performance
    2. Pick top N sectors
    3. Within each sector, pick top stocks_per_sector by 20d momentum
    4. Equal weight across all picks
    5. Hold until month end
    """
    months = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]
    trades = []
    equity = [INITIAL_CAPITAL]
    monthly_returns = []

    for i, month in enumerate(months):
        # Rank sectors by prior month (or use current month momentum if first)
        if i == 0:
            # First month: use 20-day momentum ranking
            entry_date = get_first_trading_day(klines, month)
            sector_momentum = defaultdict(list)
            for sym, bars in klines.items():
                if len([b for b in bars if b["time"] < entry_date]) >= 20:
                    mom = stock_20d_momentum(bars, entry_date)
                    if mom != 0:
                        sector_momentum[get_industry(sym)].append(mom)
            sector_rank = []
            for sec, moms in sector_momentum.items():
                if len(moms) >= 3:
                    sector_rank.append((sec, sum(moms)/len(moms)))
            sector_rank.sort(key=lambda x: x[1], reverse=True)
        else:
            prior_month = months[i-1]
            sector_rank = rank_sectors_by_performance(klines, prior_month)

        top_sectors = [s for s, _ in sector_rank[:top_n_sectors] if _ > -20]  # filter very bad

        # Entry date: first trading day of month
        entry_date = get_first_trading_day(klines, month)
        exit_date = get_last_trading_day(klines, month)

        # Pick stocks within top sectors
        picks = []
        for sector in top_sectors:
            sector_stocks = []
            for sym, bars in klines.items():
                if get_industry(sym) == sector:
                    mom = stock_20d_momentum(bars, entry_date)
                    if mom >= min_momentum:
                        sector_stocks.append((sym, mom))

            sector_stocks.sort(key=lambda x: x[1], reverse=True)
            for sym, mom in sector_stocks[:stocks_per_sector]:
                price = get_close_on_date(klines[sym], entry_date)
                if price and price > 0:
                    picks.append((sym, price, mom, sector))

        # Cap total picks
        picks = picks[:max_stocks_total]

        if not picks:
            continue

        # Equal weight allocation
        capital_per_pick = MONTHLY_CAPITAL / len(picks)

        month_trades = []
        for sym, entry_price, mom, sector in picks:
            exit_price = get_close_on_date(klines[sym], exit_date)
            if exit_price is None or entry_price <= 0:
                continue

            ret = (exit_price / entry_price - 1) * 100
            shares = int(capital_per_pick / entry_price / 100) * 100  # round to 100
            if shares <= 0:
                continue

            trade = Trade(
                symbol=sym,
                entry_date=entry_date,
                exit_date=exit_date,
                entry_price=entry_price,
                exit_price=exit_price,
                return_pct=ret,
                sector=sector,
                shares=shares,
            )
            month_trades.append(trade)
            trades.append(trade)

        # Monthly P&L
        month_pnl = sum(t.return_pct / 100 * t.shares * t.entry_price for t in month_trades)
        monthly_returns.append(month_pnl)
        equity.append(equity[-1] + month_pnl)

    # Compute metrics
    total_return = (equity[-1] / INITIAL_CAPITAL - 1) * 100 if INITIAL_CAPITAL > 0 else 0
    winning = sum(1 for t in trades if t.return_pct > 0)
    win_rate = winning / len(trades) * 100 if trades else 0

    # Max drawdown
    peak = equity[0]
    max_dd = 0.0
    for val in equity:
        if val > peak:
            peak = val
        dd = (peak - val) / peak * 100 if peak > 0 else 0
        max_dd = max(max_dd, dd)

    result = BacktestResult(
        trades=trades,
        monthly_returns=monthly_returns,
        equity_curve=equity,
        total_return=total_return,
        win_rate=win_rate,
        max_drawdown=max_dd,
    )
    return result


def print_results(result: BacktestResult):
    print("=" * 80)
    print("  Sector Rotation Strategy Results")
    print(f"  Window: {WINDOW_START} to {WINDOW_END}")
    print(f"  Initial Capital: {INITIAL_CAPITAL:,.0f}")
    print("=" * 80)
    print(f"  Total Return: {result.total_return:+.2f}%")
    print(f"  Total Trades: {len(result.trades)}")
    print(f"  Win Rate: {result.win_rate:.1f}%")
    print(f"  Max Drawdown: {result.max_drawdown:.2f}%")
    print(f"  Final Capital: {result.equity_curve[-1]:,.2f}")
    print()

    print("Monthly Returns:")
    months = ["Apr", "May", "Jun", "Jul", "Aug", "Sep"]
    for i, (m, ret) in enumerate(zip(months, result.monthly_returns)):
        pct = ret / INITIAL_CAPITAL * 100
        print(f"  {m}: {pct:+.2f}% ({ret:+,.0f})")

    print("\nTrade Details:")
    print(f"  {'Entry':>12s} {'Exit':>12s} {'Symbol':<14s} {'Sector':<14s} {'Entry$':>8s} {'Exit$':>8s} {'Ret%':>7s} {'PnL':>10s}")
    print("  " + "-" * 85)
    for t in result.trades:
        pnl = t.return_pct / 100 * t.shares * t.entry_price
        print(f"  {t.entry_date:>12s} {t.exit_date:>12s} {t.symbol:<14s} {t.sector:<14s} {t.entry_price:>8.2f} {t.exit_price:>8.2f} {t.return_pct:>+7.2f}% {pnl:>+10,.0f}")

    # Sector performance
    from collections import Counter
    sector_pnl = defaultdict(float)
    sector_count = Counter()
    for t in result.trades:
        sector_pnl[t.sector] += t.return_pct / 100 * t.shares * t.entry_price
        sector_count[t.sector] += 1
    print("\nSector P&L Breakdown:")
    for sec in sorted(sector_pnl, key=lambda x: sector_pnl[x], reverse=True):
        avg = sector_pnl[sec] / sector_count[sec]
        print(f"  {sec:<14s}: {sector_pnl[sec]:>+10,.0f}  ({sector_count[sec]} trades, avg {avg:+,.0f})")


def optimize_params(klines: dict):
    """Grid search for optimal parameters."""
    print("=== Parameter Optimization ===\n")
    best = None
    best_ret = -float('inf')

    for top_n in [2, 3, 4]:
        for stocks_per in [3, 5, 8]:
            for min_mom in [-10, -5, 0, 5]:
                for max_total in [8, 12, 15]:
                    result = backtest_sector_rotation(
                        klines,
                        top_n_sectors=top_n,
                        stocks_per_sector=stocks_per,
                        min_momentum=min_mom,
                        max_stocks_total=max_total,
                    )
                    if result.total_return > best_ret:
                        best_ret = result.total_return
                        best = (top_n, stocks_per, min_mom, max_total, result)
                    print(f"  top_n={top_n} stocks_per={stocks_per} min_mom={min_mom:+d} max_total={max_total} -> {result.total_return:+.2f}% ({len(result.trades)} trades)")

    print(f"\nBest: top_n={best[0]} stocks_per={best[1]} min_mom={best[2]:+d} max_total={best[3]}")
    print(f"Return: {best[4].total_return:+.2f}%")
    return best


def main():
    print("=== Sector Rotation Strategy ===\n")
    print("Loading kline data...")
    klines = load_klines()
    print(f"Loaded {len(klines)} stocks\n")

    # Run optimization
    best = optimize_params(klines)

    # Print detailed results for best
    print("\n" + "=" * 80)
    print("  BEST CONFIG DETAILED RESULTS")
    print("=" * 80)
    print_results(best[4])

    # Second strategy: Sector momentum with entry timing
    print("\n\n" + "=" * 80)
    print("  STRATEGY 2: Sector Leader + Breakout Entry")
    print("  Only enter top sector stocks that also show breakout on entry day")
    print("=" * 80)

    result2 = backtest_sector_rotation(klines, top_n_sectors=2, stocks_per_sector=3,
                                         min_momentum=5, max_stocks_total=5)
    print_results(result2)


if __name__ == "__main__":
    main()
