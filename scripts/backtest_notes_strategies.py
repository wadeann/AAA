#!/usr/bin/env python3
"""
Notes Strategy Mining Backtest — Tests ALL strategies from notes/skills/ against 6-month data.
Ranks by return, Sharpe, win rate, and profit factor.

Usage: python3 scripts/backtest_notes_strategies.py [--profile NAME] [--all]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════════
# Direct backtest using kline_cache (independent of MCP)
# ═══════════════════════════════════════════════════════════════

from core.strategy_profiles import get_profile, list_profiles
from core.strategy import sma, rsi, atr, _sf, get_regime, SellRules
from core.cost_model import buy_cost, sell_cost


START_DATE = "2026-04-01"
END_DATE = "2026-09-30"
INITIAL_CAPITAL = 200000.0
MIN_BARS = 80
MAX_POSITIONS = 5
CACHE_FILE = PROJECT_ROOT / "data" / "kline_cache.json"


def load_all_bars() -> dict[str, list[dict]]:
    """Load kline data from cache, filter sufficient data."""
    with open(CACHE_FILE) as f:
        raw = json.load(f)

    qualified = {}
    for sym, bars in raw.items():
        if not bars or not isinstance(bars, list):
            continue
        bars_before = [b for b in bars if str(b.get("time", ""))[:10] < START_DATE]
        if len(bars_before) >= MIN_BARS:
            qualified[sym] = bars
    return qualified


def get_trade_dates(all_bars: dict) -> list[str]:
    """Get sorted trade dates in backtest window."""
    dates = set()
    for sym, bars in all_bars.items():
        for b in bars:
            d = str(b.get("time", ""))[:10]
            if START_DATE <= d <= END_DATE:
                dates.add(d)
    return sorted(dates)


def run_profile_backtest(
    profile_name: str,
    all_bars: dict[str, list[dict]],
    trade_dates: list[str],
    initial_capital: float = INITIAL_CAPITAL,
    max_positions: int = MAX_POSITIONS,
) -> dict[str, Any]:
    """Run backtest for a single strategy profile.

    Uses the profile's score_fn + screen_fn with the backtest_2yr sell logic.
    """
    prof = get_profile(profile_name)
    score_fn = prof.score_fn
    screen_fn = prof.screen_fn or shared_screen
    sell_rules_obj = SellRules(prof.sell_rules)
    params = prof.default_params

    cash = initial_capital
    peak = initial_capital
    positions: dict[str, dict] = {}
    pending_sells: list[dict] = []
    trade_log: list[dict] = []
    daily_equity: list[dict] = []
    total_commissions = 0.0
    cooldowns: dict[str, str] = {}

    # Get index bars for regime detection (use any major index)
    index_bars = all_bars.get("000001.SH", [])
    if not index_bars:
        # Find any available index
        for sym, bars in all_bars.items():
            if sym.endswith(".SH") and sym.startswith("000"):
                index_bars = bars
                break

    for day_idx, curr_date in enumerate(trade_dates):
        # Clean expired cooldowns
        for sym in list(cooldowns.keys()):
            if curr_date >= cooldowns[sym]:
                del cooldowns[sym]

        # Market regime (PIT-safe)
        regime = get_regime(index_bars, curr_date) if index_bars else "warmup"

        # ── Execute pending sells (D-day signal → D+1 open execution) ──
        executed_sells = []
        for sell_signal in sorted(pending_sells, key=lambda x: x.get("priority", 0)):
            sym = sell_signal["sym"]
            if sym not in positions:
                continue
            p = positions[sym]
            # Get today's bar for this stock
            td = None
            for b in all_bars.get(sym, []):
                if str(b.get("time", ""))[:10] == curr_date:
                    td = b
                    break
            if not td:
                continue
            # T+1: cannot sell same day as buy
            if p.get("entry_date") == curr_date:
                continue
            # Suspension check
            if _sf(td.get("volume")) <= 0 or _sf(td.get("high")) <= _sf(td.get("low")):
                continue

            exit_price = _sf(td.get("open"))
            if exit_price <= 0:
                exit_price = sell_signal.get("price", p["ep"])

            revenue = p["qty"] * exit_price
            fee = sell_cost(revenue, sym)
            cash += revenue - fee
            total_commissions += fee
            entry_cost = p["qty"] * p["ep"]
            pnl = (revenue - fee) - entry_cost
            pnl_pct = pnl / entry_cost * 100

            entry_d = dt.date.fromisoformat(p["entry_date"])
            exit_d = dt.date.fromisoformat(curr_date)
            hold = (exit_d - entry_d).days

            trade_log.append({
                "date": curr_date, "direction": "SELL",
                "symbol": sym, "price": exit_price, "qty": p["qty"],
                "pnl": pnl, "pnl_pct": pnl_pct, "hold_days": hold,
                "reason": sell_signal.get("why", "?"),
                "entry_date": p["entry_date"], "entry_price": p["ep"],
            })
            cooldowns[sym] = (exit_d + dt.timedelta(days=5)).isoformat()
            executed_sells.append(sym)

        for sym in executed_sells:
            del positions[sym]
        pending_sells = []

        # ── Check sell rules for existing positions ──
        for sym in list(positions.keys()):
            p = positions[sym]
            # Find today's bar
            td = None
            for b in all_bars.get(sym, []):
                if str(b.get("time", ""))[:10] == curr_date:
                    td = b
                    break
            if not td:
                continue
            if p.get("entry_date") == curr_date:
                continue
            if _sf(td.get("volume")) <= 0:
                continue

            close = _sf(td.get("close"))
            high = _sf(td.get("high"))
            low = _sf(td.get("low"))
            today_open = _sf(td.get("open"))

            if high > p.get("max_price", 0):
                p["max_price"] = high

            ep = p["ep"]
            max_p = p.get("max_price", ep)
            profit_pct = (close - ep) / ep * 100
            max_profit_pct = (max_p - ep) / ep * 100

            # Use SellRules.evaluate
            sr_pos = {
                "ep": ep, "tp": result.get("target_pct", 8), "sp": result.get("stop_pct", -2.8),
                "mp": max_p, "ed": p["entry_date"],
            }
            hold_d = (dt.date.fromisoformat(curr_date) - dt.date.fromisoformat(p["entry_date"])).days
            trigger, exit_price, reason = sell_rules_obj.evaluate(sr_pos, high, low, close, hold_d)

            # Fallback: hard stop -7%, trail -8%
            if not trigger:
                trail_price = max_p * 0.92
                if low <= trail_price:
                    trigger, exit_price, reason = True, trail_price, "Trail -8%"
                elif low <= ep * 0.93:
                    trigger, exit_price, reason = True, ep * 0.93, "Stop -7%"

            if trigger:
                # Queue for next day execution
                pending_sells.append({
                    "sym": sym, "price": exit_price, "why": reason,
                    "priority": 0,
                })

        # ── Buy / Entry ──
        if len(positions) < max_positions:
            # Screen candidates
            try:
                candidates = screen_fn(all_bars, curr_date, min_close=5.0, min_vr=0.6,
                                      ma_pct=0.92, min_rs=25)
            except Exception:
                candidates = list(all_bars.keys())[:1000]

            # Score and rank
            scored = []
            for sym in candidates:
                if sym in positions or sym in cooldowns:
                    continue
                bars = [b for b in all_bars.get(sym, []) if str(b.get("time", ""))[:10] <= curr_date]
                if len(bars) < MIN_BARS:
                    continue

                # Check today valid (not suspended, not limit up)
                today = bars[-1]
                if _sf(today.get("volume")) <= 0:
                    continue
                prev_close = _sf(bars[-2].get("close")) if len(bars) >= 2 else 0
                if prev_close > 0:
                    chg = (_sf(today.get("close")) - prev_close) / prev_close * 100
                    if chg >= 9.5:
                        continue  # Limit up today, can't buy

                try:
                    result = score_fn(bars, params)
                    if result.get("score", 0) >= 50 and result.get("grade") not in ("D",):
                        scored.append((sym, result))
                except Exception:
                    continue

            scored.sort(key=lambda x: -x[1].get("score", 0))

            for sym, result in scored[:max_positions]:
                if len(positions) >= max_positions:
                    break
                if sym in positions or sym in cooldowns:
                    continue

                # T+1: execute on next day's open
                entry_date_idx = day_idx + 1
                if entry_date_idx >= len(trade_dates):
                    continue
                entry_date = trade_dates[entry_date_idx]

                entry_bar = None
                for b in all_bars.get(sym, []):
                    if str(b.get("time", ""))[:10] == entry_date:
                        entry_bar = b
                        break
                if not entry_bar:
                    continue

                entry_price = _sf(entry_bar.get("open"))
                if entry_price <= 0:
                    continue
                if _sf(entry_bar.get("volume")) <= 0:
                    continue

                # Skip if entry bar is limit up
                prev_c = _sf(bars[-1].get("close")) if len(bars) >= 1 else 0
                if prev_c > 0:
                    entry_chg = (_sf(entry_bar.get("close")) - prev_c) / prev_c * 100
                    if entry_chg >= 9.5:
                        continue

                # Position sizing: equal allocation
                alloc = min(cash * 0.2, cash / max(1, max_positions - len(positions)))
                qty = int(alloc / entry_price / 100) * 100
                if qty < 100:
                    continue

                cost = qty * entry_price
                commission = buy_cost(cost, sym)
                if cash < cost + commission:
                    qty = int((cash * 0.8) / entry_price / 100) * 100
                    if qty < 100:
                        continue
                    cost = qty * entry_price
                    commission = buy_cost(cost, sym)
                    if cash < cost + commission:
                        continue

                cash -= (cost + commission)
                total_commissions += commission

                positions[sym] = {
                    "sym": sym, "qty": qty,
                    "ep": entry_price, "entry_date": entry_date,
                    "max_price": entry_price,
                    "score": result.get("score", 0),
                    "grade": result.get("grade", "C"),
                }

                trade_log.append({
                    "date": entry_date, "direction": "BUY",
                    "symbol": sym, "price": entry_price, "qty": qty,
                    "reason": f"{profile_name}[{result.get('score', 0)}]",
                })

        # ── Daily settlement ──
        pos_val = 0.0
        for sym, p in positions.items():
            cb = None
            for b in all_bars.get(sym, []):
                if str(b.get("time", ""))[:10] == curr_date:
                    cb = b
                    break
            cp = _sf(cb.get("close")) if cb else p["ep"]
            pos_val += p["qty"] * cp

        daily_equity.append({
            "date": curr_date,
            "cash": round(cash, 2),
            "pos_val": round(pos_val, 2),
            "total": round(cash + pos_val, 2),
            "holdings": len(positions),
        })

    # ── Force close ──
    final_date = trade_dates[-1] if trade_dates else END_DATE
    for sym in list(positions.keys()):
        p = positions[sym]
        final_bar = None
        for b in all_bars.get(sym, []):
            if str(b.get("time", ""))[:10] == final_date:
                final_bar = b
                break
        sell_price = _sf(final_bar.get("close")) if final_bar else p["ep"]

        revenue = p["qty"] * sell_price
        fee = sell_cost(revenue, sym)
        cash += revenue - fee
        total_commissions += fee
        entry_cost = p["qty"] * p["ep"]
        pnl = (revenue - fee) - entry_cost
        pnl_pct = pnl / entry_cost * 100

        entry_d = dt.date.fromisoformat(p["entry_date"])
        exit_d = dt.date.fromisoformat(final_date)
        hold = (exit_d - entry_d).days

        trade_log.append({
            "date": final_date, "direction": "SELL",
            "symbol": sym, "price": sell_price, "qty": p["qty"],
            "pnl": pnl, "pnl_pct": pnl_pct, "hold_days": hold,
            "reason": "End forced close",
            "entry_date": p["entry_date"], "entry_price": p["ep"],
        })
        del positions[sym]

    # ── Statistics ──
    final_equity = daily_equity[-1]["total"] if daily_equity else initial_capital
    net = final_equity - initial_capital
    ret = net / initial_capital * 100

    closed = [t for t in trade_log if t["direction"] == "SELL"]
    wins = [t for t in closed if t.get("pnl", 0) > 0]
    losses = [t for t in closed if t.get("pnl", 0) <= 0]
    num_trades = len(closed)
    wr = len(wins) / num_trades * 100 if num_trades else 0

    tp = sum(t["pnl"] for t in wins) or 0
    tl = abs(sum(t["pnl"] for t in losses)) or 1
    pf = tp / tl

    avg_win = tp / len(wins) if wins else 0
    avg_loss = -tl / len(losses) if losses else 0

    # Max drawdown
    peak_eq = initial_capital
    mdd = 0.0
    for eq in daily_equity:
        if eq["total"] > peak_eq:
            peak_eq = eq["total"]
        dd = (peak_eq - eq["total"]) / peak_eq * 100
        if dd > mdd:
            mdd = dd

    # Sharpe ratio
    if len(daily_equity) > 1:
        daily_returns = []
        for i in range(1, len(daily_equity)):
            prev = daily_equity[i - 1]["total"]
            curr = daily_equity[i]["total"]
            if prev > 0:
                daily_returns.append((curr - prev) / prev)
        if daily_returns and len(daily_returns) > 1:
            avg_dr = sum(daily_returns) / len(daily_returns)
            variance = sum((r - avg_dr) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
            std_dr = variance ** 0.5
            sharpe = (avg_dr / std_dr * (252 ** 0.5)) if std_dr > 0 else 0
        else:
            sharpe = 0
    else:
        sharpe = 0

    avg_hold = sum(t.get("hold_days", 0) for t in closed) / num_trades if num_trades else 0

    return {
        "profile": profile_name,
        "description": prof.description,
        "source": prof.source,
        "initial_capital": initial_capital,
        "final_equity": round(final_equity, 2),
        "net_pnl": round(net, 2),
        "return_pct": round(ret, 2),
        "num_trades": num_trades,
        "num_wins": len(wins),
        "num_losses": len(losses),
        "win_rate": round(wr, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "max_drawdown": round(mdd, 2),
        "sharpe": round(sharpe, 2),
        "profit_factor": round(pf, 2),
        "avg_hold_days": round(avg_hold, 1),
        "total_commissions": round(total_commissions, 2),
        "trade_log": trade_log,
    }


def shared_screen(bars_dict: dict[str, list[dict]], date: str, **kwargs) -> list[str]:
    """Shared stock screening (delegated to core.strategy)."""
    from core.strategy import screen_candidates
    return screen_candidates(bars_dict, date, **kwargs)


def main():
    parser = argparse.ArgumentParser(description="Notes Strategy Mining Backtest")
    parser.add_argument("--profile", default=None, help="Run single profile only")
    parser.add_argument("--all", action="store_true", help="Run all profiles")
    parser.add_argument("--skip-baseline", action="store_true", help="Skip momentum_v5 baseline")
    args = parser.parse_args()

    # Determine which profiles to test
    if args.profile:
        profiles_to_test = [args.profile]
    elif args.all:
        profiles_to_test = [p for p in list_profiles() if p not in ("multi", "ensemble_top3")]
    else:
        # Default: test notes-derived strategies
        profiles_to_test = [p for p in list_profiles() if p != "multi"]

    print("=" * 100)
    print("  NOTES STRATEGY MINING BACKTEST")
    print(f"  Window: {START_DATE} ~ {END_DATE}")
    print(f"  Profiles to test: {len(profiles_to_test)}")
    print(f"  Capital: {INITIAL_CAPITAL:,.0f}")
    print("=" * 100)

    # Load data
    print("\n[1/3] Loading kline data...")
    t0 = time.time()
    all_bars = load_all_bars()
    print(f"  Loaded {len(all_bars)} stocks with >= {MIN_BARS} bars before window")
    trade_dates = get_trade_dates(all_bars)
    print(f"  Trading days: {len(trade_dates)} ({trade_dates[0]} to {trade_dates[-1]})")

    # Run backtests
    print(f"\n[2/3] Running backtests for {len(profiles_to_test)} profiles...")
    results = []
    for i, pname in enumerate(profiles_to_test):
        t1 = time.time()
        try:
            result = run_profile_backtest(pname, all_bars, trade_dates)
            results.append(result)
            elapsed = time.time() - t1
            emoji = "P" if result["return_pct"] > 0 else "N"
            print(f"  [{i+1:>2}/{len(profiles_to_test)}] {pname:<20} | "
                  f"Ret: {result['return_pct']:>+7.2f}% | "
                  f"WR: {result['win_rate']:>5.1f}% | "
                  f"PF: {result['profit_factor']:>5.2f} | "
                  f"Sharpe: {result['sharpe']:>5.2f} | "
                  f"Trades: {result['num_trades']:>3} | "
                  f"MDD: {result['max_drawdown']:>5.1f}% | "
                  f"{elapsed:.1f}s")
        except Exception as e:
            import traceback
            print(f"  [{i+1:>2}] {pname}: FAILED - {e}")
            # Print traceback for debugging
            traceback.print_exc()

    # Rank and save
    print(f"\n[3/3] Ranking results...")
    results.sort(key=lambda r: r["return_pct"], reverse=True)

    # Composite score ranking
    for r in results:
        r["composite"] = round(
            (r["return_pct"] * 1.0 if r["return_pct"] > 0 else r["return_pct"] * 0.5)
            + r["sharpe"] * 5.0
            + (r["win_rate"] - 40) * 0.5
            + min(r["profit_factor"], 5)
            - r["max_drawdown"] * 0.3
            + min(r["num_trades"], 30) * 0.2,
            2
        )

    # Print ranking
    print("\n" + "=" * 120)
    print("  FINAL RANKING (by return %)")
    print("=" * 120)
    print(f"{'Rank':<5} {'Profile':<22} {'Return%':>8} {'Sharpe':>7} {'WR%':>6} {'PF':>6} {'MDD%':>7} {'Trades':>6} {'Composite':>9}  Description")
    print("-" * 120)
    for i, r in enumerate(results):
        status = "GREEN" if r["return_pct"] > 0 else "RED"
        print(f"  {i+1:>3}. {r['profile']:<22} {r['return_pct']:>+7.2f}% {r['sharpe']:>6.2f} {r['win_rate']:>5.1f}% {r['profit_factor']:>5.2f} {r['max_drawdown']:>6.1f}% {r['num_trades']:>5}  {r['composite']:>+8.2f}  {r['description'][:50]}")

    # Composite ranking
    print(f"\n{'Rank':<5} {'Profile':<22} {'Composite':>9} {'Return%':>8} {'Sharpe':>7} {'WR%':>6} {'PF':>6} {'MDD%':>7} {'Trades':>6}")
    print("-" * 100)
    for i, r in enumerate(sorted(results, key=lambda x: -x["composite"])):
        print(f"  {i+1:>3}. {r['profile']:<22} {r['composite']:>+8.2f} {r['return_pct']:>+7.2f}% {r['sharpe']:>6.2f} {r['win_rate']:>5.1f}% {r['profit_factor']:>5.2f} {r['max_drawdown']:>6.1f}% {r['num_trades']:>5}")

    # Save results
    output_path = PROJECT_ROOT / "data" / "notes_mining_results.json"
    with open(output_path, "w") as f:
        # Strip trade logs for compact JSON
        slim = []
        for r in results:
            sr = {k: v for k, v in r.items() if k != "trade_log"}
            slim.append(sr)
        json.dump(slim, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nResults saved to {output_path}")

    # Top 5 summary
    print("\n" + "=" * 80)
    print("  TOP 5 PROFITABLE STRATEGIES")
    print("=" * 80)
    profitable = [r for r in results if r["return_pct"] > 0]
    for i, r in enumerate(profitable[:5]):
        print(f"  {i+1}. {r['profile']}: {r['return_pct']:+.2f}% | "
              f"Sharpe:{r['sharpe']:.2f} | WR:{r['win_rate']:.0f}% | "
              f"PF:{r['profit_factor']:.2f} | Trades:{r['num_trades']}")
        print(f"     {r['description']}")

    total_time = time.time() - t0
    print(f"\nTotal time: {total_time:.1f}s")


if __name__ == "__main__":
    main()
