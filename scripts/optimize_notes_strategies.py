#!/usr/bin/env python3
"""
Notes Strategy Optimizer — Runs parameter search on top 3 strategies.
Uses direct kline_cache data for speed. 50 iterations per strategy.

Usage: python3 scripts/optimize_notes_strategies.py
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.strategy_profiles import get_profile
from core.strategy import sma, _sf, get_regime, SellRules
from core.cost_model import buy_cost, sell_cost


START_DATE = "2026-04-01"
END_DATE = "2026-09-30"
INITIAL_CAPITAL = 200000.0
MIN_BARS = 80
MAX_POSITIONS = 5
OPTIMIZE_ROUNDS = 30  # Per strategy
CACHE_FILE = PROJECT_ROOT / "data" / "kline_cache.json"


def load_all_bars() -> dict[str, list[dict]]:
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
    dates = set()
    for bars in all_bars.values():
        for b in bars:
            d = str(b.get("time", ""))[:10]
            if START_DATE <= d <= END_DATE:
                dates.add(d)
    return sorted(dates)


def shared_screen(bars_dict: dict[str, list[dict]], date: str, **kwargs) -> list[str]:
    from core.strategy import screen_candidates
    return screen_candidates(bars_dict, date, **kwargs)


def run_profile_backtest_with_params(
    profile_name: str,
    all_bars: dict[str, list[dict]],
    trade_dates: list[str],
    params_override: dict | None = None,
    sell_rules_override: dict | None = None,
    silent: bool = True,
) -> dict[str, Any]:
    """Run backtest with optional parameter overrides."""
    prof = get_profile(profile_name)
    score_fn = prof.score_fn
    screen_fn = prof.screen_fn or shared_screen
    params = {**prof.default_params, **(params_override or {})}

    sell_rules_cfg = dict(prof.sell_rules)
    if sell_rules_override:
        sell_rules_cfg.update(sell_rules_override)
    sell_rules_obj = SellRules(sell_rules_cfg)

    cash = INITIAL_CAPITAL
    positions: dict[str, dict] = {}
    pending_sells: list[dict] = []
    trade_log: list[dict] = []
    total_commissions = 0.0
    cooldowns: dict[str, str] = {}

    # Index bars (PIT-safe)
    index_bars = all_bars.get("000001.SH", [])
    if not index_bars:
        for sym, bars in all_bars.items():
            if sym.endswith(".SH") and sym.startswith("000"):
                index_bars = bars
                break

    for day_idx, curr_date in enumerate(trade_dates):
        for sym in list(cooldowns.keys()):
            if curr_date >= cooldowns[sym]:
                del cooldowns[sym]

        # Execute pending sells (D-day signal, D+1 open)
        for sell_signal in sorted(pending_sells, key=lambda x: x.get("priority", 0)):
            sym = sell_signal["sym"]
            if sym not in positions:
                continue
            p = positions[sym]
            td = next((b for b in all_bars.get(sym, []) if str(b.get("time", ""))[:10] == curr_date), None)
            if not td:
                continue
            if p.get("entry_date") == curr_date:
                continue
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

            trade_log.append({
                "date": curr_date, "direction": "SELL",
                "symbol": sym, "price": exit_price, "qty": p["qty"],
                "pnl": pnl, "pnl_pct": pnl_pct,
                "hold_days": (dt.date.fromisoformat(curr_date) - dt.date.fromisoformat(p["entry_date"])).days,
                "reason": sell_signal.get("why", "?"),
                "entry_date": p["entry_date"], "entry_price": p["ep"],
            })
            cooldowns[sym] = (dt.date.fromisoformat(curr_date) + dt.timedelta(days=5)).isoformat()

        for sym in [s["sym"] for s in pending_sells if s["sym"] in positions]:
            del positions[sym]
        pending_sells = []

        # Sell checks
        for sym in list(positions.keys()):
            p = positions[sym]
            td = next((b for b in all_bars.get(sym, []) if str(b.get("time", ""))[:10] == curr_date), None)
            if not td:
                continue
            if p.get("entry_date") == curr_date:
                continue
            if _sf(td.get("volume")) <= 0:
                continue

            close = _sf(td.get("close"))
            high = _sf(td.get("high"))
            low = _sf(td.get("low"))
            ep = p["ep"]
            if high > p.get("max_price", 0):
                p["max_price"] = high
            max_p = p["max_price"]

            sr_pos = {
                "ep": ep, "tp": params.get("target_pct", 8), "sp": params.get("stop_pct", -2.8),
                "mp": max_p, "ed": p["entry_date"],
            }
            hold = (dt.date.fromisoformat(curr_date) - dt.date.fromisoformat(p["entry_date"])).days
            trigger, exit_price, reason = sell_rules_obj.evaluate(sr_pos, high, low, close, hold)

            if not trigger:
                if low <= max_p * 0.92:
                    trigger, exit_price, reason = True, max_p * 0.92, "Trail -8%"
                elif low <= ep * 0.93:
                    trigger, exit_price, reason = True, ep * 0.93, "Stop -7%"

            if trigger:
                pending_sells.append({"sym": sym, "price": exit_price, "why": reason, "priority": 0})

        # Buy
        if len(positions) < MAX_POSITIONS:
            try:
                candidates = screen_fn(all_bars, curr_date, min_close=5.0, min_vr=0.6, ma_pct=0.92, min_rs=25)
            except Exception:
                candidates = list(all_bars.keys())[:1000]

            scored = []
            for sym in candidates:
                if sym in positions or sym in cooldowns:
                    continue
                bars_upto = [b for b in all_bars.get(sym, []) if str(b.get("time", ""))[:10] <= curr_date]
                if len(bars_upto) < MIN_BARS:
                    continue
                today = bars_upto[-1]
                if _sf(today.get("volume")) <= 0:
                    continue
                prev_close = _sf(bars_upto[-2].get("close")) if len(bars_upto) >= 2 else 0
                if prev_close > 0:
                    if (_sf(today.get("close")) - prev_close) / prev_close * 100 >= 9.5:
                        continue
                try:
                    result = score_fn(bars_upto, params)
                    if result.get("score", 0) >= 50 and result.get("grade") not in ("D",):
                        scored.append((sym, result))
                except Exception:
                    continue

            scored.sort(key=lambda x: -x[1].get("score", 0))

            for sym, result in scored[:MAX_POSITIONS]:
                if len(positions) >= MAX_POSITIONS:
                    break
                if sym in positions or sym in cooldowns:
                    continue

                entry_date_idx = day_idx + 1
                if entry_date_idx >= len(trade_dates):
                    continue
                entry_date = trade_dates[entry_date_idx]
                entry_bar = next((b for b in all_bars.get(sym, []) if str(b.get("time", ""))[:10] == entry_date), None)
                if not entry_bar:
                    continue
                entry_price = _sf(entry_bar.get("open"))
                if entry_price <= 0 or _sf(entry_bar.get("volume")) <= 0:
                    continue

                prev_c = _sf(bars_upto[-1].get("close")) if len(bars_upto) >= 1 else 0
                if prev_c > 0:
                    entry_chg = (_sf(entry_bar.get("close")) - prev_c) / prev_c * 100
                    if entry_chg >= 9.5:
                        continue

                alloc = min(cash * 0.2, cash / max(1, MAX_POSITIONS - len(positions)))
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
                    "sym": sym, "qty": qty, "ep": entry_price,
                    "entry_date": entry_date, "max_price": entry_price,
                    "score": result.get("score", 0),
                }
                trade_log.append({
                    "date": entry_date, "direction": "BUY",
                    "symbol": sym, "price": entry_price, "qty": qty,
                    "reason": f"{profile_name}[{result.get('score', 0)}]",
                })

    # Force close
    final_date = trade_dates[-1] if trade_dates else END_DATE
    for sym in list(positions.keys()):
        p = positions[sym]
        final_bar = next((b for b in all_bars.get(sym, []) if str(b.get("time", ""))[:10] == final_date), None)
        sell_price = _sf(final_bar.get("close")) if final_bar else p["ep"]
        revenue = p["qty"] * sell_price
        fee = sell_cost(revenue, sym)
        cash += revenue - fee
        total_commissions += fee
        entry_cost = p["qty"] * p["ep"]
        pnl = (revenue - fee) - entry_cost
        trade_log.append({
            "date": final_date, "direction": "SELL",
            "symbol": sym, "price": sell_price, "qty": p["qty"],
            "pnl": pnl, "pnl_pct": pnl / entry_cost * 100,
            "hold_days": (dt.date.fromisoformat(final_date) - dt.date.fromisoformat(p["entry_date"])).days,
            "reason": "End close", "entry_date": p["entry_date"], "entry_price": p["ep"],
        })

    # Statistics
    final_equity = cash  # all positions closed
    net = final_equity - INITIAL_CAPITAL
    ret = net / INITIAL_CAPITAL * 100

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

    # Max drawdown (approximate for speed)
    mdd = 5.0  # placeholder

    # Composite score
    composite = (
        ret * 1.0 +  # Return
        (wr - 40) * 0.5 +  # Win rate bonus
        min(pf, 5) * 2 +  # Profit factor
        min(num_trades, 30) * 0.2  # Trade count
    )

    return {
        "profile": profile_name,
        "return_pct": round(ret, 2),
        "win_rate": round(wr, 1),
        "profit_factor": round(pf, 2),
        "num_trades": num_trades,
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "composite": round(composite, 2),
        "params": params_override or {},
        "sell_rules": sell_rules_override or {},
    }


# ── Parameter spaces for each top strategy ──

PARAM_SPACES = {
    "ma5_monster": [
        ("target_pct", 10, [6, 8, 10, 12, 15]),
        ("stop_pct", -5.0, [-3.0, -4.0, -5.0, -6.0, -7.0]),
        ("hold_days", 5, [3, 4, 5, 7]),
        ("consecutive_new_high", 3, [2, 3, 4]),
        ("sell.trail_trigger", 3.0, [2.0, 3.0, 4.0, 5.0]),
        ("sell.trail_high_rate", 0.25, [0.15, 0.20, 0.25, 0.30]),
        ("sell.trail_low_rate", 0.35, [0.25, 0.30, 0.35, 0.40]),
        ("sell.breakeven_peak", 4.0, [2.0, 3.0, 4.0, 5.0]),
        ("sell.max_hold", 5, [3, 4, 5, 7, 10]),
    ],
    "single_yang": [
        ("yang_gain", 5.0, [3.0, 4.0, 5.0, 6.0, 7.0]),
        ("max_consolidation_bars", 9, [5, 7, 9, 12]),
        ("target_pct", 8, [5, 6, 8, 10, 12]),
        ("stop_pct", -2.8, [-2.0, -2.5, -2.8, -3.5, -4.5]),
        ("hold_days", 3, [2, 3, 4, 5]),
        ("sell.trail_trigger", 3.0, [2.0, 3.0, 4.0, 5.0]),
        ("sell.trail_high_rate", 0.25, [0.15, 0.20, 0.25, 0.30]),
        ("sell.max_hold", 5, [3, 5, 7, 10]),
    ],
    "island_reversal": [
        ("target_pct", 12, [8, 10, 12, 15, 18]),
        ("stop_pct", -4.0, [-3.0, -4.0, -5.0, -6.0]),
        ("hold_days", 7, [5, 7, 10, 12]),
        ("sell.trail_trigger", 3.0, [2.0, 3.0, 4.0, 5.0, 6.0]),
        ("sell.trail_high_rate", 0.25, [0.15, 0.20, 0.25, 0.30]),
        ("sell.breakeven_peak", 4.0, [3.0, 4.0, 5.0, 6.0]),
        ("sell.max_hold", 8, [5, 7, 10, 12]),
    ],
}


def optimize_strategy(profile_name: str, all_bars: dict, trade_dates: list[str], rounds: int = OPTIMIZE_ROUNDS):
    """Random search optimization for one strategy."""
    param_space = PARAM_SPACES.get(profile_name, [])
    if not param_space:
        print(f"  No param space for {profile_name}")
        return None

    best_composite = -999
    best_params = {}
    best_sell_rules = {}
    best_result = None
    history = []

    # Baseline
    baseline = run_profile_backtest_with_params(profile_name, all_bars, trade_dates)
    best_composite = baseline["composite"]
    current_params = {}
    current_sell_rules = {}
    print(f"  Baseline: ret={baseline['return_pct']:+.2f}% WR={baseline['win_rate']:.0f}% PF={baseline['profit_factor']:.2f} Composite={baseline['composite']:.2f}")
    history.append({"round": 0, "composite": baseline["composite"], "ret": baseline["return_pct"],
                    "verdict": "BASELINE"})

    for rnd in range(1, rounds + 1):
        # Pick a random parameter to mutate
        pname, default_val, candidates = random.choice(param_space)
        current_val = current_params.get(pname, current_sell_rules.get(pname.replace("sell.", ""), default_val))
        available = [v for v in candidates if v != current_val]
        if not available:
            continue
        new_val = random.choice(available)

        # Build override
        test_params = dict(current_params)
        test_sell_rules = dict(current_sell_rules)

        if pname.startswith("sell."):
            sell_key = pname.replace("sell.", "")
            test_sell_rules[sell_key] = new_val
        else:
            test_params[pname] = new_val

        result = run_profile_backtest_with_params(
            profile_name, all_bars, trade_dates,
            params_override=test_params,
            sell_rules_override=test_sell_rules,
        )

        composite = result["composite"]
        if composite > best_composite * 0.995:
            # Accept
            best_composite = composite
            best_params = dict(test_params)
            best_sell_rules = dict(test_sell_rules)
            current_params = dict(test_params)
            current_sell_rules = dict(test_sell_rules)
            best_result = result
            history.append({"round": rnd, "composite": composite, "ret": result["return_pct"],
                          "param": pname, "old": current_val, "new": new_val, "verdict": "ACCEPT"})
            print(f"  Round {rnd:>3}: ACCEPT {pname}={current_val}→{new_val} | ret={result['return_pct']:+.2f}% | comp={composite:.2f}")
        else:
            history.append({"round": rnd, "composite": composite, "ret": result["return_pct"],
                          "param": pname, "old": current_val, "new": new_val, "verdict": "REJECT"})
            if rnd % 10 == 0:
                print(f"  Round {rnd:>3}: best comp={best_composite:.2f}, ret={best_result['return_pct']:+.2f}%")

    if best_result:
        print(f"  FINAL: ret={best_result['return_pct']:+.2f}% WR={best_result['win_rate']:.0f}% "
              f"PF={best_result['profit_factor']:.2f} Composite={best_composite:.2f}")
        print(f"  Best params: {best_params}")
        print(f"  Best sell rules: {best_sell_rules}")

    return {
        "profile": profile_name,
        "baseline": baseline,
        "best_result": {**best_result, "params": best_params, "sell_rules": best_sell_rules} if best_result else None,
        "history": history,
        "best_composite": best_composite,
    }


def main():
    print("=" * 80)
    print("  NOTES STRATEGY OPTIMIZER")
    print(f"  Window: {START_DATE} ~ {END_DATE}")
    print(f"  Rounds per strategy: {OPTIMIZE_ROUNDS}")
    print("=" * 80)

    # Load data
    print("\nLoading kline data...")
    t0 = time.time()
    all_bars = load_all_bars()
    trade_dates = get_trade_dates(all_bars)
    print(f"  {len(all_bars)} stocks, {len(trade_dates)} trading days")

    # Top 3 strategies to optimize (based on previous backtest)
    top_strategies = ["ma5_monster", "single_yang", "island_reversal"]

    all_results = {}
    for profile_name in top_strategies:
        print(f"\n{'─' * 60}")
        print(f"Optimizing: {profile_name}")
        print(f"{'─' * 60}")
        t1 = time.time()
        result = optimize_strategy(profile_name, all_bars, trade_dates)
        all_results[profile_name] = result
        print(f"  Time: {time.time() - t1:.1f}s")

    # Summary
    print("\n" + "=" * 80)
    print("  OPTIMIZATION RESULTS")
    print("=" * 80)
    for pname, res in all_results.items():
        if res and res.get("best_result"):
            br = res["best_result"]
            bl = res["baseline"]
            print(f"\n  {pname}:")
            print(f"    Baseline: ret={bl['return_pct']:+.2f}% WR={bl['win_rate']:.0f}% PF={bl['profit_factor']:.2f}")
            print(f"    Optimized: ret={br['return_pct']:+.2f}% WR={br['win_rate']:.0f}% PF={br['profit_factor']:.2f}")
            print(f"    Improvement: {br['return_pct'] - bl['return_pct']:+.2f}%")
            print(f"    Params: {br.get('params', {})}")
            print(f"    Sell Rules: {br.get('sell_rules', {})}")

    # Save
    output = PROJECT_ROOT / "data" / "optimization_results.json"
    with open(output, "w") as f:
        # Strip history for compactness
        slim = {}
        for pname, res in all_results.items():
            if res:
                slim[pname] = {
                    "baseline": {k: v for k, v in res["baseline"].items() if k != "history"},
                    "best": res.get("best_result"),
                    "best_composite": res.get("best_composite"),
                }
        json.dump(slim, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nSaved to {output}")

    total_time = time.time() - t0
    print(f"\nTotal time: {total_time:.0f}s")


if __name__ == "__main__":
    main()
