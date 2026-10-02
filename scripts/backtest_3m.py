#!/usr/bin/env python3
"""
Astock 近 3 月回测学习报告 — 逐笔交易明细 + 统计分析.
使用 momentum_v5 策略 (最佳 composite 41.63) 参数.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.strategy import (
    SellRules, _sf, atr, clear_param_overrides, get_regime,
    load_strategy_config, rsi, screen_candidates as shared_screen,
    score_momentum_core, set_param_overrides, sma,
    REGIME_MAP as SHARED_REGIME_MAP,
)

# ── 参数 ──
START_DATE = "2026-07-01"
END_DATE = "2026-10-01"
INITIAL_CAPITAL = 400000.0
MIN_BARS = 60
CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "kline_cache.json"
BEST_CONFIG_FILE = Path(__file__).resolve().parent.parent / "results" / "best_config_momentum_v5.json"


def load_cache() -> dict[str, list[dict]]:
    with open(CACHE_FILE) as f:
        return json.load(f)


def trading_dates(bars_dict: dict) -> list[str]:
    """从数据中提取所有交易日并排序."""
    dates: set[str] = set()
    for sym, bars in bars_dict.items():
        for b in bars:
            t = str(b.get("time", ""))
            if START_DATE <= t <= END_DATE:
                dates.add(t)
    return sorted(dates)


def run_backtest_3m() -> dict:
    print(f"{'='*80}")
    print(f"  Astock 近 3 月回测学习报告")
    print(f"  策略: momentum_v5 (最佳参数)")
    print(f"  时间: {START_DATE} ~ {END_DATE}")
    print(f"  初始资金: {INITIAL_CAPITAL:,.0f}")
    print(f"{'='*80}")

    # 1. 加载最优参数
    with open(BEST_CONFIG_FILE) as f:
        best = json.load(f)
    params = best.get("config", best.get("params", {}))
    set_param_overrides(params)
    print(f"\n[参数] 加载自 {BEST_CONFIG_FILE.name}")
    print(f"  score_weights: {params.get('score_weights', {})}")
    print(f"  sell_rules: {params.get('sell_rules', {})}")
    print(f"  hard_filters: {params.get('hard_filters', {})}")
    print(f"  regime_map: {params.get('regime_map', {})}")
    print(f"  min_close: {params.get('min_close', 10)}")
    print(f"  max_pos_pct: {params.get('max_pos_pct', 0.35)}")
    print(f"  target_pct: {params.get('target_pct', 8)}")
    print(f"  stop_pct: {params.get('stop_pct', -2.8)}")

    # 2. 加载数据
    print(f"\n[数据] 加载缓存...")
    bars_dict = load_cache()
    print(f"  股票池: {len(bars_dict)} 只")

    dates = trading_dates(bars_dict)
    print(f"  交易日: {len(dates)} 天 ({dates[0]} ~ {dates[-1]})")

    if END_DATE in dates:
        dates = [d for d in dates if d <= END_DATE]

    # 3. 提取 regime 参数
    regime_map_override = params.get("regime_map", SHARED_REGIME_MAP)
    # convert list-style regime params to tuple
    rm = {}
    for k, v in regime_map_override.items():
        if isinstance(v, dict):
            rm[k] = (int(v.get("0", 60)), int(v.get("1", 3)), float(v.get("2", 0.25)))
        elif isinstance(v, list):
            rm[k] = (int(v[0]), int(v[1]) if len(v) > 1 else 3, float(v[2]) if len(v) > 2 else 0.25)
        else:
            rm[k] = v
    regime_map = rm
    sw = params.get("score_weights", {})
    sr = params.get("sell_rules", {})
    hf = params.get("hard_filters", {})
    min_close = params.get("min_close", 10)
    max_pos_pct = params.get("max_pos_pct", 0.35)
    target_pct = params.get("target_pct", 8)
    stop_pct = params.get("stop_pct", -2.8)
    hold_days = params.get("hold_days", 3)

    # 4. 逐日回测循环
    capital = INITIAL_CAPITAL
    cash = capital
    positions: dict[str, dict] = {}  # symbol -> position info
    trades: list[dict] = []
    daily_balance: list[dict] = []
    total_sold_pnl = 0.0

    # 统计
    win_trades = 0
    loss_trades = 0
    max_drawdown = 0.0
    peak_balance = capital
    monthly_pnl: dict[str, list[float]] = defaultdict(list)

    regime_history: list[str] = []

    trade_id = 0

    for di, curr_date in enumerate(dates):
        if di < 10:
            continue  # 跳过前几个日期让指标预热

        # --- 检测体制 ---
        # 用大盘股组合代替指数检测
        # 取 MA20 上/下比例作为市场宽度
        above_ma20 = 0
        total_check = 0
        for sym in list(bars_dict.keys())[:100]:  # 取样 100 只
            lb = [b for b in bars_dict[sym] if str(b.get("time", "")) <= curr_date]
            if len(lb) >= 20:
                total_check += 1
                if _sf(lb[-1].get("close")) > sma(lb, "close", 20):
                    above_ma20 += 1
        breadth = above_ma20 / total_check if total_check > 0 else 0.5

        if breadth > 0.7:
            regime = "euphoria"
        elif breadth > 0.55:
            regime = "hot"
        elif breadth > 0.40:
            regime = "warmup"
        elif breadth > 0.25:
            regime = "cooldown"
        else:
            regime = "ice"
        regime_history.append(regime)

        rp = regime_map.get(regime, (60, 3, 0.25))
        min_score = rp[0] if len(rp) > 0 else 60
        max_pos = rp[1] if len(rp) > 1 else 3
        regime_cap = rp[2] if len(rp) > 2 else 0.25

        # --- 筛选 ---
        candidates = shared_screen(
            bars_dict, curr_date,
            min_vr=hf.get("min_vr", 0.7),
            min_close=min_close,
            ma_pct=hf.get("ma_pct", 0.95),
        )

        # --- 评分排序 ---
        scored = []
        for sym in candidates:
            if sym in positions:
                continue
            bars = bars_dict.get(sym, [])
            lb = [b for b in bars if str(b.get("time", "")) <= curr_date]
            if len(lb) < MIN_BARS:
                continue
            result = score_momentum_core(lb, sw)
            if result["grade"] in ("A", "B") and result["score"] >= min_score:
                scored.append((sym, result))

        scored.sort(key=lambda x: -x[1]["score"])

        # --- 买入 ---
        open_slots = max_pos - len(positions)
        for sym, result in scored[:open_slots]:
            lb = [b for b in bars_dict[sym] if str(b.get("time", "")) <= curr_date]
            if not lb:
                continue
            close = _sf(lb[-1].get("close"))
            if close <= 0:
                continue

            pos_pct = regime_cap
            if result["score"] >= 80:
                pos_pct = min(regime_cap + 0.05, max_pos_pct)
            elif result["score"] >= 70:
                pos_pct = regime_cap
            elif result["score"] >= 60:
                pos_pct = regime_cap * 0.8

            pos_value = cash * pos_pct
            shares = max(1, int(pos_value / close / 100) * 100)
            cost = shares * close
            if cost > cash or cost <= 0:
                continue

            cash -= cost
            positions[sym] = {
                "symbol": sym,
                "entry_date": curr_date,
                "entry_price": close,
                "shares": shares,
                "cost": cost,
                "highest": close,
                "highest_pct": 0.0,
                "score": result["score"],
                "grade": result["grade"],
                "type": result.get("name", ""),
                "hold": 0,
                "target_pct": result.get("target_pct", target_pct),
                "stop_pct": result.get("stop_pct", stop_pct),
                "profile": "momentum_v5",
            }
            trade_id += 1

        # --- 卖出 ---
        sold_symbols = []
        for sym, pos in positions.items():
            pos["hold"] += 1
            lb = [b for b in bars_dict.get(sym, []) if str(b.get("time", "")) <= curr_date]
            if not lb:
                continue
            bar = lb[-1]
            hi = _sf(bar.get("high"))
            lo = _sf(bar.get("low"))
            cl = _sf(bar.get("close"))
            if hi <= 0 or cl <= 0:
                continue

            if hi > pos["highest"]:
                pos["highest"] = hi
                pos["highest_pct"] = (hi - pos["entry_price"]) / pos["entry_price"] * 100

            sell_obj = {
                "ep": pos["entry_price"],
                "mp": pos["highest"],
                "tp": pos["target_pct"],
                "sp": pos["stop_pct"],
            }
            sell_rules = SellRules(sr)
            should_sell, sell_price, reason = sell_rules.evaluate(
                sell_obj, hi, lo, cl, pos["hold"]
            )

            if should_sell:
                pnl = (sell_price - pos["entry_price"]) / pos["entry_price"] * 100
                pnl_value = (sell_price - pos["entry_price"]) * pos["shares"]
                cash += pos["shares"] * sell_price

                is_win = pnl > 0
                trades.append({
                    "id": len(trades) + 1,
                    "symbol": sym,
                    "entry_date": pos["entry_date"],
                    "exit_date": curr_date,
                    "entry_price": round(pos["entry_price"], 2),
                    "exit_price": round(sell_price, 2),
                    "pnl_pct": round(pnl, 2),
                    "pnl_value": round(pnl_value, 2),
                    "hold_days": pos["hold"],
                    "exit_reason": reason,
                    "score": pos["score"],
                    "grade": pos["grade"],
                    "type": pos["type"],
                })
                if is_win:
                    win_trades += 1
                else:
                    loss_trades += 1
                total_sold_pnl += pnl_value
                month_key = curr_date[:7]
                monthly_pnl[month_key].append(pnl)
                sold_symbols.append(sym)

        for sym in sold_symbols:
            del positions[sym]

        # --- 日终市值 ---
        pos_value = sum(
            _sf([b for b in bars_dict.get(p["symbol"], [])
                 if str(b.get("time", "")) <= curr_date][-1].get("close"))
            * p["shares"]
            if [b for b in bars_dict.get(p["symbol"], [])
                if str(b.get("time", "")) <= curr_date]
            else p["cost"]
            for p in positions.values()
        )
        total_balance = cash + pos_value
        if total_balance > peak_balance:
            peak_balance = total_balance
        dd = (peak_balance - total_balance) / peak_balance * 100
        if dd > max_drawdown:
            max_drawdown = dd

        daily_balance.append({
            "date": curr_date,
            "balance": round(total_balance, 2),
            "cash": round(cash, 2),
            "positions": len(positions),
            "regime": regime,
            "drawdown": round(dd, 2),
        })

    # 平所有剩余仓位
    for sym, pos in list(positions.items()):
        lb = [b for b in bars_dict.get(sym, []) if str(b.get("time", "")) <= END_DATE]
        if lb:
            cl = _sf(lb[-1].get("close"))
            pnl = (cl - pos["entry_price"]) / pos["entry_price"] * 100
            pnl_value = (cl - pos["entry_price"]) * pos["shares"]
            cash += pos["shares"] * cl
            is_win = pnl > 0
            trades.append({
                "id": len(trades) + 1,
                "symbol": sym,
                "entry_date": pos["entry_date"],
                "exit_date": END_DATE,
                "entry_price": round(pos["entry_price"], 2),
                "exit_price": round(cl, 2),
                "pnl_pct": round(pnl, 2),
                "pnl_value": round(pnl_value, 2),
                "hold_days": pos["hold"],
                "exit_reason": "期末平仓",
                "score": pos["score"],
                "grade": pos["grade"],
                "type": pos["type"],
            })
            if is_win:
                win_trades += 1
            else:
                loss_trades += 1
        positions = {}

    total_return = (cash - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    # ── 5. 输出报告 ──
    print(f"\n{'='*80}")
    print(f"  回测结果总览")
    print(f"{'='*80}")
    print(f"  总收益率:        {total_return:>+8.2f}%")
    print(f"  总交易次数:      {len(trades)}")
    print(f"  胜率:            {win_trades}/{len(trades)} ({win_trades/max(len(trades),1)*100:.1f}%)")
    print(f"  最大回撤:        {max_drawdown:.2f}%")
    print(f"  最终资金:        {cash:>12,.2f}")
    print(f"  净利润:          {cash - INITIAL_CAPITAL:>+12,.2f}")

    # 月度统计
    print(f"\n{'='*80}")
    print(f"  月度统计")
    print(f"{'='*80}")
    months = sorted(monthly_pnl.keys())
    for m in months:
        pnls = monthly_pnl[m]
        wins = sum(1 for p in pnls if p > 0)
        losses = sum(1 for p in pnls if p <= 0)
        avg_pnl = sum(pnls) / len(pnls) if pnls else 0
        print(f"  {m}: {len(pnls)}笔 胜{wins}负{losses} "
              f"平均{avg_pnl:+.2f}% 合计{sum(pnls):+.2f}%")

    # 体制分布
    regime_counts = defaultdict(int)
    for r in regime_history:
        regime_counts[r] += 1
    print(f"\n{'='*80}")
    print(f"  市场体制分布")
    print(f"{'='*80}")
    total_days = len(regime_history)
    for r in ["euphoria", "hot", "warmup", "cooldown", "ice"]:
        cnt = regime_counts.get(r, 0)
        names = {"euphoria": "高潮", "hot": "走强", "warmup": "震荡", "cooldown": "退潮", "ice": "极寒"}
        print(f"  {names.get(r,r):<6} ({r:<10}): {cnt:>3}天 ({cnt/total_days*100:>5.1f}%)")

    # ── 6. 逐笔交易明细 ──
    print(f"\n{'='*80}")
    print(f"  逐笔交易明细 ({len(trades)} 笔)")
    print(f"{'='*80}")
    print(f"  {'#':>3} {'代码':<12} {'入场':<10} {'出场':<10} {'入场价':>7} {'出场价':>7} "
          f"{'盈亏%':>7} {'盈亏额':>9} {'持有':>3} {'原因':<16} {'评分':>3}")
    print(f"  {'-'*95}")

    win_total = 0
    loss_total = 0
    max_win = 0.0
    max_loss = 0.0
    hold_stats: list[int] = []

    for t in trades:
        pnl = t["pnl_pct"]
        print(f"  {t['id']:>3} {t['symbol']:<12} {t['entry_date']:<10} {t['exit_date']:<10} "
              f"{t['entry_price']:>7.2f} {t['exit_price']:>7.2f} "
              f"{pnl:>+7.2f} {t['pnl_value']:>+9.0f} {t['hold_days']:>3} "
              f"{t['exit_reason']:<16} {t['score']:>3}")
        if pnl > 0:
            win_total += pnl
            max_win = max(max_win, pnl)
        else:
            loss_total += pnl
            max_loss = min(max_loss, pnl)
        hold_stats.append(t["hold_days"])

    # 7. 综合分析
    print(f"\n{'='*80}")
    print(f"  交易分析")
    print(f"{'='*80}")
    avg_win = win_total / max(win_trades, 1)
    avg_loss = loss_total / max(loss_trades, 1)
    avg_hold = sum(hold_stats) / len(hold_stats) if hold_stats else 0
    print(f"  平均盈利:    {avg_win:+.2f}%")
    print(f"  平均亏损:    {avg_loss:+.2f}%")
    print(f"  盈亏比:      {abs(avg_win/avg_loss):.2f}" if avg_loss != 0 else "  盈亏比:      INF")
    print(f"  最大单笔盈利:{max_win:+.2f}%")
    print(f"  最大单笔亏损:{max_loss:+.2f}%")
    print(f"  平均持仓天数:{avg_hold:.1f}天")

    # 按退出原因统计
    reason_stats = defaultdict(lambda: {"total": 0, "win": 0})
    for t in trades:
        r = t["exit_reason"]
        reason_stats[r]["total"] += 1
        if t["pnl_pct"] > 0:
            reason_stats[r]["win"] += 1
    print(f"\n  退出原因统计:")
    for r, stats in sorted(reason_stats.items(), key=lambda x: -x[1]["total"]):
        wr = stats["win"] / stats["total"] * 100
        print(f"    {r:<20}: {stats['total']:>3}笔 胜{stats['win']}负{stats['total']-stats['win']} 胜率{wr:>5.1f}%")

    # 按评分区间统计
    score_brackets = {"<60": [], "60-69": [], "70-79": [], "80-89": [], "90+": []}
    for t in trades:
        s = t["score"]
        if s >= 90:
            score_brackets["90+"].append(t["pnl_pct"])
        elif s >= 80:
            score_brackets["80-89"].append(t["pnl_pct"])
        elif s >= 70:
            score_brackets["70-79"].append(t["pnl_pct"])
        elif s >= 60:
            score_brackets["60-69"].append(t["pnl_pct"])
        else:
            score_brackets["<60"].append(t["pnl_pct"])
    print(f"\n  评分区间胜率:")
    for bracket, pnls in score_brackets.items():
        if pnls:
            wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
            avg = sum(pnls) / len(pnls)
            print(f"    {bracket:<8}: {len(pnls):>3}笔 胜率{wr:>5.1f}% 平均{avg:+.2f}%")

    return {
        "total_return": total_return,
        "trades": len(trades),
        "win_rate": win_trades / max(len(trades), 1) * 100,
        "max_drawdown": max_drawdown,
        "win_trades": win_trades,
        "loss_trades": loss_trades,
        "monthly_pnl": {k: sum(v) for k, v in monthly_pnl.items()},
        "trade_details": trades[:50],  # 前 50 笔
    }


if __name__ == "__main__":
    result = run_backtest_3m()
