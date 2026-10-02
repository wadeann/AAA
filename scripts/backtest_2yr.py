#!/usr/bin/env python3
"""
Astock 全市场动量回测 — 2 年回测 (2024-10-01 ~ 2026-10-01)
使用 core.strategy 共享策略模块，支持 --profile 多策略回测。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_client import get_mcp_client
from stock_universe_full import STOCK_UNIVERSE, get_industry, get_universe_size, get_industry_distribution

# ── 共享策略模块 ──
from core.strategy import (
    _sf,
    atr,
    clear_param_overrides,
    get_regime,
    load_strategy_config,
    screen_candidates as shared_screen,
    score_momentum_core,
    set_param_overrides,
    sma,
    REGIME_MAP as SHARED_REGIME_MAP,
)
from core.cost_model import buy_cost, sell_cost
from core.strategy_profiles import get_profile, list_profiles

# ── 回测参数 ──
START_DATE = "2024-10-01"
END_DATE = "2026-10-01"
INITIAL_CAPITAL = 400000.0
KLINE_COUNT = 500
MIN_BARS = 120
CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "kline_cache.json"

# ── MCP 缓存 ──
_MCP_CACHE: dict[str, list[dict]] = {}


def load_cache() -> dict[str, list[dict]]:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: dict[str, list[dict]]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
        print(f"  [Cache] Saved {len(cache)} symbols to {CACHE_FILE}")
    except Exception as e:
        print(f"  [Cache] Save failed: {e}")


def fetch_klines(symbol: str, count: int = KLINE_COUNT, retries: int = 3) -> list[dict]:
    """带重试的 K 线获取."""
    key = f"{symbol}_{count}"
    if key in _MCP_CACHE:
        return _MCP_CACHE[key]

    for attempt in range(retries):
        try:
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
            else:
                print(f"    [FAIL] {symbol} after {retries} retries: {e}")
    _MCP_CACHE[key] = []
    return []


def run_backtest(config_override: dict | None = None, profile: str = "momentum_v5") -> dict:
    """运行 2 年全市场回测. 支持 --profile 选择策略档案。"""
    # ── 配置加载 ──
    if config_override:
        set_param_overrides(config_override)
        cfg = config_override
    else:
        cfg = load_strategy_config()

    # 加载策略档案
    prof = get_profile(profile)
    is_multi = (profile == "multi")

    # 多策略分仓组合
    if is_multi:
        from core.strategy_profiles import get_multi_allocator
        multi_cfg = cfg.get("multi_profiles", None)
        allocator = get_multi_allocator(multi_cfg)
        profile_params = {}
        score_fn = prof.score_fn  # 占位, 实际用 allocator
        screen_fn = prof.screen_fn  # 占位, 实际用 allocator
        # 多策略使用默认 regime_map
        _REGIME_MAP = SHARED_REGIME_MAP
        print(f"  多策略分仓组合: {allocator.describe()}")
    else:
        profile_params = {**prof.default_params, **cfg.get("score_weights", {})}
        score_fn = prof.score_fn
        screen_fn = prof.screen_fn or shared_screen
        _REGIME_MAP = cfg.get("regime_map", {}) or SHARED_REGIME_MAP

    # 卖出规则 (单策略用)
    from core.strategy import SellRules
    sell_rules_obj = SellRules(cfg.get("sell_rules", prof.sell_rules)) if not is_multi else None

    symbols = cfg.get("symbols", STOCK_UNIVERSE)
    total_symbols = len(symbols)
    print(f"{'=' * 100}")
    print(f"  全市场回测  |  策略: {profile}")
    print(f"  股票池: {total_symbols} 只 | 时间: {START_DATE} ~ {END_DATE}")
    print(f"  初始资金: {INITIAL_CAPITAL:,.0f}")
    print(f"  行业覆盖: {len(get_industry_distribution())}")
    print(f"{'=' * 100}")

    # ── 1. 加载缓存 ──
    print(f"\n{'─' * 40} 加载数据 {'─' * 40}")
    file_cache = load_cache()
    if file_cache:
        print(f"  [Cache] Loaded {len(file_cache)} cached symbols")
    else:
        print(f"  [Cache] No cache found, will fetch all data")

    # ── 2. 获取 K 线数据 ──
    all_bars: dict[str, list[dict]] = {}
    batch_size = 50
    loaded_count = 0
    start_load = time.time()

    for i in range(0, total_symbols, batch_size):
        batch = symbols[i : i + batch_size]
        for sym in batch:
            cache_key = f"{sym}_{KLINE_COUNT}"
            # 先检查文件缓存
            if cache_key in file_cache:
                bars = file_cache[cache_key]
                _MCP_CACHE[cache_key] = bars
            else:
                bars = fetch_klines(sym, KLINE_COUNT)
            if len(bars) >= MIN_BARS:
                all_bars[sym] = bars
                loaded_count += 1

        # 进度提示
        pct = min(100, (i + batch_size) / total_symbols * 100)
        elapsed = time.time() - start_load
        rate = (i + batch_size) / elapsed if elapsed > 0 else 0
        print(
            f"  Progress: {min(i + batch_size, total_symbols):>4d}/{total_symbols} "
            f"({pct:.0f}%) | Loaded: {loaded_count} | "
            f"{rate:.1f} stocks/s | Elapsed: {elapsed:.0f}s"
        )

    load_time = time.time() - start_load
    print(f"\n  Data loaded: {len(all_bars)}/{total_symbols} (min {MIN_BARS} bars)")
    print(f"  Load time: {load_time:.0f}s")

    # ── 3. 保存缓存（仅首次需要）──
    if not cfg.get("skip_cache_save"):
        save_cache({f"{s}_{KLINE_COUNT}": _MCP_CACHE.get(f"{s}_{KLINE_COUNT}", []) for s in symbols})

    if len(all_bars) < 100:
        print(f"\n  ERROR: Too few stocks with sufficient data ({len(all_bars)}), aborting.")
        return {}

    # ── 4. 获取指数数据 ──
    index_bars = fetch_klines("000001.SH", KLINE_COUNT)
    if not index_bars:
        print("  ERROR: No index data, aborting.")
        return {}

    # ── 5. 生成交易日期 ──
    dates = sorted(
        {
            str(b.get("time"))
            for b in index_bars
            if START_DATE <= str(b.get("time", "")) <= END_DATE
        }
    )
    if len(dates) < 10:
        print(f"  ERROR: Too few trading days: {len(dates)}")
        return {}

    print(f"\n  Trading days: {len(dates)}")
    print(f"  Universe: {len(all_bars)} stocks")
    print(f"{'=' * 100}\n")

    # ── 6. 回测主循环 ──
    cash = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
    pos: dict[str, dict] = {}
    pos_profile_count: dict[str, int] = {}  # 多策略: 各子策略当前持仓数 {profile_name: count}
    pending_sells: list[dict] = []  # D日卖出信号 → D+1开盘执行
    log: list[dict] = []
    eq: list[dict] = []
    comm = 0.0

    total_days = len(dates)
    last_progress_pct = 0

    # 使用 SellRules 引擎
    sr_obj = sell_rules_obj

    for di, dt_ in enumerate(dates):
        # 进度
        progress_pct = (di + 1) / total_days * 100
        if progress_pct // 10 > last_progress_pct // 10:
            print(f"  Backtest: {di + 1}/{total_days} days ({progress_pct:.0f}%) | "
                  f"Cash: {cash:,.0f} | Positions: {len(pos)}")
            last_progress_pct = progress_pct // 10

        regime = get_regime(index_bars, dt_)
        _rm = _REGIME_MAP
        _rm_entry = _rm[regime]
        if isinstance(_rm_entry, dict):
            ms, mx, cp = _rm_entry.get("0", 60), _rm_entry.get("1", 3), _rm_entry.get("2", 0.25)
        else:
            ms, mx, cp = _rm_entry

        # ── 执行前日卖出信号 (D日信号 → D+1开盘执行) ──
        executed_sells: list[str] = []
        for sell_signal in pending_sells:
            sym = sell_signal["sym"]
            if sym not in pos:
                continue
            p = pos[sym]
            # 用当日开盘价卖出
            td = next(
                (b for b in all_bars.get(sym, []) if str(b.get("time", "")) == dt_),
                None,
            )
            if td:
                exit_price = _sf(td.get("open"))
            else:
                exit_price = sell_signal.get("price", p["ep"])
            if exit_price <= 0:
                exit_price = sell_signal.get("price", p["ep"])

            rev = p["qty"] * exit_price
            fee = sell_cost(rev, sym)
            cash += rev - fee
            comm += fee
            pnl = (rev - fee) - (p["qty"] * p["ep"])
            pnl_pct = pnl / (p["qty"] * p["ep"]) * 100
            log.append({
                "date": dt_,
                "d": "S",
                "sym": sym,
                "p": exit_price,
                "q": p["qty"],
                "pnl": pnl,
                "pp": pnl_pct,
                "hold": sell_signal.get("hold", 0),
                "why": sell_signal["why"],
                "nm": p["nm"],
                "reg": p["reg"],
                "sc": p["sc"],
            })
            if is_multi:
                pname = p.get("profile", "momentum_v5")
                pos_profile_count[pname] = max(0, pos_profile_count.get(pname, 0) - 1)
            executed_sells.append(sym)
        for sym in executed_sells:
            del pos[sym]
        pending_sells = []

        # ── SELL 检测 (D日检测 → 存入 pending_sells, D+1开盘执行) ──
        for sym in list(pos.keys()):
            p = pos[sym]
            td = next(
                (b for b in all_bars.get(sym, []) if str(b.get("time", "")) == dt_),
                None,
            )
            if not td:
                continue
            hi = _sf(td.get("high"))
            lo = _sf(td.get("low"))
            cl = _sf(td.get("close"))
            if hi > p["mp"]:
                p["mp"] = hi
            if p["ed"] == dt_:
                continue
            ep_ = p["ep"]
            hold = (dt.date.fromisoformat(dt_) - dt.date.fromisoformat(p["ed"])).days

            # 选择正确的 SellRules
            if is_multi:
                cur_sr = allocator.get_sell_rules(p.get("profile", "momentum_v5"))
            else:
                cur_sr = sr_obj
            sell, sp_, why = cur_sr.evaluate(p, hi, lo, cl, hold)
            if sell:
                pending_sells.append({
                    "sym": sym,
                    "price": sp_,
                    "why": why,
                    "hold": hold,
                })

        # ── BUY ──
        if len(pos) < mx:
            screen_min_vr = cfg.get("min_vr", 1.5)
            screen_min_close = cfg.get("min_close", 10.0)

            if is_multi:
                # ── 多策略分仓买入 ──
                screen = allocator.screen_all(all_bars, dt_, min_vr=screen_min_vr, min_close=screen_min_close)
                scored = allocator.score_all(screen, all_bars, profile_params, min_score=ms)
                # 按 symbol 聚合: 合并多策略评分结果
                sym_agg: dict[str, dict] = {}
                for sym, r, pname in scored:
                    if sym in pos:
                        continue
                    if sym not in sym_agg:
                        sym_agg[sym] = {
                            "best_r": r, "best_pname": pname, "best_score": r["score"],
                            "profiles": [], "total_weight": 0.0,
                        }
                    agg = sym_agg[sym]
                    agg["profiles"].append(pname)
                    agg["total_weight"] += r.get("weight", 0.2)
                    if r["score"] > agg["best_score"]:
                        agg["best_r"] = r
                        agg["best_pname"] = pname
                        agg["best_score"] = r["score"]

                # 按最佳 score 排序
                sorted_syms = sorted(sym_agg.items(), key=lambda x: -x[1]["best_score"])
                for sym, agg in sorted_syms:
                    if len(pos) >= mx:
                        break
                    _max_pos_pct = cfg.get("max_pos_pct", 0.35)
                    # 多策略共振: 每多一个策略加成 0.3 倍仓位
                    resonance = 1.0 + (len(agg["profiles"]) - 1) * 0.3
                    alloc_pct = allocator.get_alloc_pct(
                        agg["best_pname"], agg["best_score"], cp, _max_pos_pct
                    ) * resonance
                    # 限制单策略预算
                    if agg["best_pname"] in pos_profile_count:
                        budgets = allocator.get_budgets(mx)
                        p_budget = budgets.get(agg["best_pname"], 1)
                        if pos_profile_count.get(agg["best_pname"], 0) >= p_budget:
                            alloc_pct *= 0.5  # 超预算减半

                    r = agg["best_r"]
                    pname = agg["best_pname"]
                    ei = di + 1
                    if ei >= len(dates):
                        continue
                    ed = dates[ei]
                    eb = next(
                        (b for b in all_bars.get(sym, []) if str(b.get("time", "")) == ed),
                        None,
                    )
                    if not eb:
                        continue
                    ep = _sf(eb.get("open"))
                    if ep <= 0:
                        continue
                    amt = min(cash * alloc_pct, INITIAL_CAPITAL * _max_pos_pct)
                    qty = max(100, int(amt / ep / 100) * 100)
                    cost = qty * ep
                    fee = buy_cost(cost, sym)
                    if cash < cost + fee:
                        continue
                    cash -= cost + fee
                    comm += fee
                    pos[sym] = {
                        "sym": sym, "qty": qty, "ep": ep, "ed": ed, "mp": ep,
                        "tp": r.get("target_pct", 8), "sp": r.get("stop_pct", -2.8),
                        "hd": r.get("hold_days", 3), "sc": r["score"],
                        "nm": "multi_" + pname, "reg": regime, "profile": pname,
                        "profiles": agg["profiles"],
                    }
                    pos_profile_count[pname] = pos_profile_count.get(pname, 0) + 1
                    log.append({
                        "date": ed, "d": "B", "sym": sym, "p": ep, "q": qty,
                        "sc": r["score"], "nm": "multi_" + pname, "reg": regime,
                    })
            else:
                # ── 单策略买入 ──
                screen = screen_fn(all_bars, dt_, min_vr=screen_min_vr, min_close=screen_min_close)
                cand = []
                for sym in screen:
                    if sym in pos:
                        continue
                    lb = [b for b in all_bars[sym] if str(b.get("time", "")) <= dt_]
                    if len(lb) < 25:
                        continue
                    r = score_fn(lb, profile_params)
                    if r["grade"] in ("D", "C") or r["score"] < ms:
                        continue
                    cand.append((sym, r))
                cand.sort(key=lambda x: -x[1]["score"])
                for sym, r in cand[: mx - len(pos)]:
                    ei = di + 1
                    if ei >= len(dates):
                        continue
                    ed = dates[ei]
                    eb = next(
                        (b for b in all_bars[sym] if str(b.get("time", "")) == ed),
                        None,
                    )
                    if not eb:
                        continue
                    ep = _sf(eb.get("open"))
                    if ep <= 0:
                        continue
                    sc = r["score"]
                    _max_pos_pct = cfg.get("max_pos_pct", 0.35)
                    if sc >= 80:
                        alloc = min(cp + 0.05, _max_pos_pct)
                    elif sc >= 70:
                        alloc = cp
                    elif sc >= 60:
                        alloc = cp * 0.8
                    else:
                        alloc = cp * 0.6
                    amt = min(cash * alloc, INITIAL_CAPITAL * _max_pos_pct)
                    qty = max(100, int(amt / ep / 100) * 100)
                    cost = qty * ep
                    fee = buy_cost(cost, sym)
                    if cash < cost + fee:
                        continue
                    cash -= cost + fee
                    comm += fee
                    pos[sym] = {
                        "sym": sym, "qty": qty, "ep": ep, "ed": ed, "mp": ep,
                        "tp": r["target_pct"], "sp": r["stop_pct"], "hd": r["hold_days"],
                        "sc": r["score"], "nm": r["name"], "reg": regime,
                    }
                    log.append({
                        "date": ed, "d": "B", "sym": sym, "p": ep, "q": qty,
                        "sc": r["score"], "nm": r["name"], "reg": regime,
                    })

        # ── Equity ──
        pv = sum(
            p["qty"]
            * _sf(
                next(
                    (
                        b
                        for b in all_bars.get(sym, [])
                        if str(b.get("time", "")) == dt_
                    ),
                    {},
                ).get("close", p["ep"])
            )
            for sym, p in pos.items()
        )
        te = cash + pv
        if te > peak:
            peak = te
        eq.append({"date": dt_, "te": round(te, 2), "n": len(pos), "reg": regime})

    # ── 7. 统计计算 ──
    fin = eq[-1]
    net = fin["te"] - INITIAL_CAPITAL
    ret = net / INITIAL_CAPITAL * 100

    # 月数
    start_d = dt.date.fromisoformat(START_DATE)
    end_d = dt.date.fromisoformat(END_DATE)
    total_months = max(1, (end_d.year - start_d.year) * 12 + end_d.month - start_d.month)
    annual_ret = ((1 + ret / 100) ** (12 / total_months) - 1) * 100

    # 月度收益
    monthly_returns: dict[str, float] = {}
    prev_te = INITIAL_CAPITAL
    curr_month = ""
    for e in eq:
        ym = e["date"][:7]
        if ym != curr_month:
            if curr_month and curr_month >= START_DATE[:7]:
                monthly_returns[curr_month] = (prev_te - prev_month_start) / prev_month_start * 100
            curr_month = ym
            prev_month_start = prev_te
        prev_te = e["te"]
    # 最后一个月
    if curr_month and curr_month >= START_DATE[:7]:
        monthly_returns[curr_month] = (prev_te - prev_month_start) / prev_month_start * 100

    monthly_ret_mean = sum(monthly_returns.values()) / len(monthly_returns) if monthly_returns else 0
    monthly_ret_std = (
        (sum((r - monthly_ret_mean) ** 2 for r in monthly_returns.values()) / len(monthly_returns)) ** 0.5
        if monthly_returns
        else 0
    )

    # 交易统计
    closed = [t for t in log if t["d"] == "S"]
    wins = [t for t in closed if t.get("pnl", 0) > 0]
    losses = [t for t in closed if t.get("pnl", 0) <= 0]
    wr = len(wins) / len(closed) * 100 if closed else 0
    aw = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    al = abs(sum(t["pnl"] for t in losses)) / len(losses) if losses else 1
    pf = (sum(t["pnl"] for t in wins) or 0) / (abs(sum(t["pnl"] for t in losses)) or 1)

    # 最大回撤
    peak2 = INITIAL_CAPITAL
    mdd = 0.0
    mdd_start = ""
    mdd_end = ""
    mdd_peak_date = ""
    for e in eq:
        if e["te"] > peak2:
            peak2 = e["te"]
            mdd_peak_date = e["date"]
        dd = (peak2 - e["te"]) / peak2 * 100
        if dd > mdd:
            mdd = dd
            mdd_start = mdd_peak_date
            mdd_end = e["date"]

    # Sharpe (假设无风险利率 2%)
    rf = 2.0
    excess_returns = [r - rf / 12 for r in monthly_returns.values()]
    sharpe = (
        (sum(excess_returns) / len(excess_returns)) / (monthly_ret_std + 0.001) * (12**0.5)
        if monthly_ret_std > 0
        else 0
    )

    # ── 8. 行业分析 ──
    industry_stats: dict[str, dict] = {}
    for t in closed:
        ind = get_industry(t["sym"])
        if ind not in industry_stats:
            industry_stats[ind] = {"trades": 0, "wins": 0, "pnl": 0.0, "pnl_pct": 0.0}
        industry_stats[ind]["trades"] += 1
        industry_stats[ind]["pnl"] += t.get("pnl", 0)
        if t.get("pnl", 0) > 0:
            industry_stats[ind]["wins"] += 1

    # ── 9. 策略统计 ──
    strategy_stats: dict[str, dict] = {}
    for t in closed:
        n = t.get("nm", "?")
        if n not in strategy_stats:
            strategy_stats[n] = {"n": 0, "w": 0, "p": 0.0}
        strategy_stats[n]["n"] += 1
        if t.get("pnl", 0) > 0:
            strategy_stats[n]["w"] += 1
        strategy_stats[n]["p"] += t.get("pnl", 0)

    # ── 10. 输出 ──
    results_text: list[str] = []
    results_text.append("=" * 100)
    results_text.append("  全市场动量回测结果 (v5-ext)")
    results_text.append("=" * 100)
    results_text.append("")

    # 参数
    results_text.append(f"  回测参数:")
    results_text.append(f"    时间范围: {START_DATE} ~ {END_DATE}  ({len(dates)} 个交易日)")
    results_text.append(f"    初始资金: {INITIAL_CAPITAL:,.0f}")
    results_text.append(f"    股票池:   {total_symbols} 只 (有效: {len(all_bars)})")
    results_text.append(f"    行业覆盖: {len(get_industry_distribution())}")
    results_text.append(f"    数据量:   {KLINE_COUNT} 根 K 线/只, 最少 {MIN_BARS} 根")
    results_text.append("")

    # 最终统计
    results_text.append(f"  {'=' * 80}")
    results_text.append(f"  最终统计")
    results_text.append(f"  {'=' * 80}")
    results_text.append(f"    总收益:       {ret:>+10.2f}%")
    results_text.append(f"    年化收益:     {annual_ret:>+10.2f}%")
    results_text.append(f"    最终权益:     {fin['te']:>10,.0f}")
    results_text.append(f"    净利润:       {net:>+10,.0f}")
    results_text.append(f"    月均收益:     {monthly_ret_mean:>+10.2f}%")
    results_text.append(f"    月收益标准差: {monthly_ret_std:>10.2f}%")
    results_text.append(f"    夏普比率:     {sharpe:>10.2f}")
    results_text.append(f"    胜率:         {wr:>10.1f}%")
    results_text.append(f"    盈亏比:       {pf:>10.2f}")
    results_text.append(f"    平均盈利:     {aw:>+10,.0f}")
    results_text.append(f"    平均亏损:     {al:>+10,.0f}")
    results_text.append(f"    最大回撤:     {mdd:>10.2f}%")
    results_text.append(f"    回撤区间:     {mdd_start} ~ {mdd_end}")
    results_text.append(f"    交易次数:     {len(closed):>10}")
    results_text.append(f"    总佣金:       {comm:>10,.0f}")
    results_text.append("")

    # 月度收益表
    results_text.append(f"  {'=' * 80}")
    results_text.append(f"  月度收益汇总")
    results_text.append(f"  {'=' * 80}")
    results_text.append(f"  {'月份':<10} {'月收益':>10} {'累计收益':>10}")
    results_text.append(f"  {'-' * 30}")
    cum_ret = 0
    for ym in sorted(monthly_returns.keys()):
        mr = monthly_returns[ym]
        cum_ret += mr
        sign = "+" if mr >= 0 else ""
        results_text.append(f"  {ym:<10} {sign}{mr:>+9.2f}% {cum_ret:>+9.2f}%")
    results_text.append("")

    # 月度统计
    positive_months = sum(1 for v in monthly_returns.values() if v > 0)
    negative_months = sum(1 for v in monthly_returns.values() if v <= 0)
    if monthly_returns:
        best_month = max(monthly_returns.values())
        worst_month = min(monthly_returns.values())
        results_text.append(f"  盈利月: {positive_months}/{len(monthly_returns)} ({positive_months/len(monthly_returns)*100:.0f}%)")
        results_text.append(f"  最佳月: {best_month:+.2f}%")
        results_text.append(f"  最差月: {worst_month:+.2f}%")
        results_text.append("")

    # 每日交易记录
    results_text.append(f"  {'=' * 80}")
    results_text.append(f"  交易记录")
    results_text.append(f"  {'=' * 80}")
    results_text.append(
        f"  {'Date':<10} {'D':<2} {'Symbol':<10} {'Price':>7} {'Qty':>6} "
        f"{'Strat':<9} {'PnL':>10} {'%':>6} {'Hold':>4} {'Reason'}"
    )
    results_text.append(f"  {'-' * 80}")
    buy_count = 0
    sell_count = 0
    for t in log:
        if t["d"] == "B":
            buy_count += 1
            results_text.append(
                f"  {t['date']:<10} {'B':<2} {t['sym']:10s} {t['p']:>7.2f} {t['q']:>6d} "
                f"{t.get('nm', '?'):<9} {'---':>10} {'---':>6} {'':4} | {t.get('reg', '')}"
            )
        else:
            sell_count += 1
            results_text.append(
                f"  {t['date']:<10} {'S':<2} {t['sym']:10s} {t['p']:>7.2f} {t['q']:>6d} "
                f"{t.get('nm', '?'):<9} {t.get('pnl', 0):>+10.0f} {t.get('pp', 0):>+5.1f}% "
                f"{t.get('hold', 0):>3}d | {t['why']}"
            )
    results_text.append(f"  {'-' * 80}")
    results_text.append(f"  买入: {buy_count}  卖出: {sell_count}  |  总交易: {len(closed)}")
    results_text.append("")

    # 策略统计
    if strategy_stats:
        results_text.append(f"  {'=' * 80}")
        results_text.append(f"  策略维度分析")
        results_text.append(f"  {'=' * 80}")
        results_text.append(f"  {'策略':<12} {'交易':>6} {'胜率':>6} {'总盈亏':>10}")
        results_text.append(f"  {'-' * 40}")
        for n, s in sorted(strategy_stats.items(), key=lambda x: -x[1]["p"]):
            results_text.append(
                f"  {n:<12} {s['n']:>6} {(s['w']/s['n']*100):>5.0f}% {s['p']:>+10,.0f}"
            )
        results_text.append("")

    # 行业分析
    if industry_stats:
        results_text.append(f"  {'=' * 80}")
        results_text.append(f"  行业维度分析")
        results_text.append(f"  {'=' * 80}")
        results_text.append(f"  {'行业':<16} {'交易':>6} {'胜率':>6} {'总盈亏':>10}")
        results_text.append(f"  {'-' * 45}")
        for ind, s in sorted(industry_stats.items(), key=lambda x: -x[1]["pnl"]):
            wr_ind = s["wins"] / s["trades"] * 100 if s["trades"] > 0 else 0
            if s["trades"] >= 2:  # 只显示交易次数>=2的行业
                results_text.append(
                    f"  {ind:<16} {s['trades']:>6} {wr_ind:>5.0f}% {s['pnl']:>+10,.0f}"
                )
        results_text.append("")

    # 权益曲线
    results_text.append(f"  {'=' * 80}")
    results_text.append(f"  权益曲线 (每 20 天采样)")
    results_text.append(f"  {'=' * 80}")
    results_text.append(f"  {'日期':<12} {'权益':>10} {'仓位':>4} {'市况':<10} {'DD%':>6}")
    results_text.append(f"  {'-' * 50}")
    for i, e in enumerate(eq):
        if i % 20 == 0 or i == len(eq) - 1:
            dd = (peak - e["te"]) / peak * 100
            results_text.append(
                f"  {e['date']:<12} {e['te']:>10,.0f} {e['n']:>4} {e['reg']:<10} {dd:>5.1f}%"
            )
    results_text.append("")

    results_text.append("=" * 100)

    # ── 打印与保存 ──
    output = "\n".join(results_text)
    print(output)

    # 保存到文件
    result_file = Path(__file__).resolve().parent.parent / "results" / "backtest_2yr_results.txt"
    result_file.parent.mkdir(parents=True, exist_ok=True)
    with open(result_file, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\n结果已保存至: {result_file}")

    return {
        "ret": ret,
        "annual_ret": annual_ret,
        "monthly_ret_mean": monthly_ret_mean,
        "monthly_ret_std": monthly_ret_std,
        "sharpe": sharpe,
        "wr": wr,
        "pf": pf,
        "mdd": mdd,
        "trades": len(closed),
        "total_symbols": total_symbols,
        "valid_symbols": len(all_bars),
        "total_days": len(dates),
        "comm": comm,
        "best_month": max(monthly_returns.values()) if monthly_returns else 0,
        "worst_month": min(monthly_returns.values()) if monthly_returns else 0,
        "positive_months": positive_months,
        "negative_months": negative_months,
        "total_months": len(monthly_returns),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "avg_win": aw,
        "avg_loss": al,
        "strategy_stats": strategy_stats,
        "industry_stats": industry_stats,
    }
    clear_param_overrides()
    return results


def main():
    parser = argparse.ArgumentParser(description="Astock 全市场回测")
    parser.add_argument("--profile", default="momentum_v5", choices=list_profiles(),
                        help="策略档案 (默认: momentum_v5)")
    parser.add_argument("--use-best", action="store_true",
                        help="使用 results/best_config_{profile}.json 最优参数")
    parser.add_argument("--list-profiles", action="store_true",
                        help="列出所有可用策略档案")
    parser.add_argument("--show-accepted", action="store_true", default=True,
                        help="显示接受的交易记录 (默认: 显示)")
    args = parser.parse_args()

    if args.list_profiles:
        print("可用策略档案:")
        for name in list_profiles():
            prof = get_profile(name)
            print(f"  {name:<20} {prof.description}")
            print(f"                  来源: {prof.source}")
        return

    # 如果指定 --use-best，加载最优参数
    config_override = None
    if args.use_best:
        best_file = Path(__file__).resolve().parent.parent / "results" / f"best_config_{args.profile}.json"
        if best_file.exists():
            with open(best_file) as f:
                best_data = json.load(f)
            # 优先用 config 字段，其次 params 字段
            config_override = best_data.get("config") or best_data.get("params", {})
            print(f"  加载最优参数: {best_file}")
            ret_val = best_data.get('results', {}).get('ret', '?')
            comp_val = best_data.get('results', {}).get('composite', '?')
            print(f"  原结果: ret={ret_val} composite={comp_val}")
        else:
            print(f"  [WARN] 最优参数文件不存在: {best_file}，使用默认参数")

    results = run_backtest(config_override=config_override, profile=args.profile)
    if results:
        print(f"\n{'=' * 40} 概览 ({args.profile}) {'=' * 40}")
        print(f"  股票: {results['valid_symbols']}/{results['total_symbols']} | "
              f"交易日: {results['total_days']}")
        print(f"  收益: {results['ret']:+.2f}% | 年化: {results['annual_ret']:+.2f}% | "
              f"月均: {results['monthly_ret_mean']:+.2f}%")
        print(f"  夏普: {results['sharpe']:.2f} | 胜率: {results['wr']:.0f}% | "
              f"盈亏比: {results['pf']:.2f} | 最大回撤: {results['mdd']:.2f}%")
        print(f"  交易: {results['trades']} | 佣金: {results['comm']:,.0f}")
        print(f"  最佳月: {results['best_month']:+.2f}% | 最差月: {results['worst_month']:+.2f}%")
        print(f"  盈利月: {results['positive_months']}/{results['total_months']} "
              f"({results['positive_months']/results['total_months']*100:.0f}%)")
        print("=" * 90)


if __name__ == "__main__":
    main()
