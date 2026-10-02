#!/usr/bin/env python3
"""
Astock 近 3 月回测学习报告 v2 — 修正 T+1 / 先卖后买 / 次日执行.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.strategy import (
    SellRules, _sf, get_regime, load_strategy_config, rsi,
    screen_candidates as shared_screen, score_momentum_core,
    set_param_overrides, sma,
    REGIME_MAP as SHARED_REGIME_MAP,
)

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
    dates: set[str] = set()
    for sym, bars in bars_dict.items():
        for b in bars:
            t = str(b.get("time", ""))
            if START_DATE <= t <= END_DATE:
                dates.add(t)
    return sorted(dates)


def find_next_date(dates: list[str], curr: str) -> str | None:
    """找到下一个交易日."""
    idx = dates.index(curr) if curr in dates else -1
    if 0 <= idx < len(dates) - 1:
        return dates[idx + 1]
    return None


def get_open_for_date(bars: list[dict], target_date: str) -> float:
    """获取目标日期的开盘价."""
    for b in bars:
        if str(b.get("time", "")) == target_date:
            return _sf(b.get("open"))
    return 0.0


def estimate_market_breadth_regime(bars_dict: dict, date: str) -> tuple[str, float]:
    """用市场宽度估计体制."""
    above_ma20 = 0
    total = 0
    for sym in list(bars_dict.keys())[:200]:
        lb = [b for b in bars_dict[sym] if str(b.get("time", "")) <= date]
        if len(lb) >= 20:
            total += 1
            if _sf(lb[-1].get("close")) > sma(lb, "close", 20):
                above_ma20 += 1
    breadth = above_ma20 / total if total > 0 else 0.5

    if breadth > 0.70:
        return "euphoria", breadth
    elif breadth > 0.55:
        return "hot", breadth
    elif breadth > 0.40:
        return "warmup", breadth
    elif breadth > 0.25:
        return "cooldown", breadth
    return "ice", breadth


def run_backtest_v2() -> dict:
    print(f"{'='*80}")
    print(f"  Astock 近 3 月回测 — v2 (修正版)")
    print(f"  修正: T+1约束 / 先卖后买 / 次日开盘执行")
    print(f"  策略: momentum_v5 (最佳 composite 41.63)")
    print(f"  时间: {START_DATE} ~ {END_DATE}")
    print(f"  初始资金: {INITIAL_CAPITAL:,.0f}")
    print(f"{'='*80}")

    # 1. 加载参数
    with open(BEST_CONFIG_FILE) as f:
        best = json.load(f)
    params = best.get("config", best.get("params", {}))
    set_param_overrides(params)

    sw = params.get("score_weights", {})
    sr = params.get("sell_rules", {})
    hf = params.get("hard_filters", {})
    regime_map_override = params.get("regime_map", SHARED_REGIME_MAP)

    rm = {}
    for k, v in regime_map_override.items():
        if isinstance(v, dict):
            rm[k] = (int(v.get("0", 60)), int(v.get("1", 3)), float(v.get("2", 0.25)))
        elif isinstance(v, list):
            rm[k] = (int(v[0]), int(v[1]) if len(v) > 1 else 3, float(v[2]) if len(v) > 2 else 0.25)
        else:
            rm[k] = v
    regime_map = rm

    min_close = params.get("min_close", 10)
    max_pos_pct = params.get("max_pos_pct", 0.35)

    # 2. 加载数据
    print(f"\n[数据] 加载缓存...")
    bars_dict = load_cache()
    print(f"  股票池: {len(bars_dict)} 只")

    dates = trading_dates(bars_dict)
    dates = [d for d in dates if d <= END_DATE]
    print(f"  交易日: {len(dates)} 天 ({dates[0]} ~ {dates[-1]})")

    # 3. 回测状态
    capital = INITIAL_CAPITAL
    cash = capital
    positions: dict[str, dict] = {}  # symbol -> position
    trades: list[dict] = []
    daily_balance: list[dict] = []

    win_trades = 0
    loss_trades = 0
    max_drawdown = 0.0
    peak_balance = capital
    monthly_pnl: dict[str, list[float]] = defaultdict(list)
    regime_history: list[str] = []

    # 信号队列: 在 D 日生成信号, D+1 日开盘执行
    pending_buys: list[dict] = []  # D 日筛选出的买入候选
    pending_sells: list[dict] = []  # D 日触发的卖出信号

    for di, curr_date in enumerate(dates):
        if di < 15:
            continue

        # --- 体制检测 ---
        regime, _ = estimate_market_breadth_regime(bars_dict, curr_date)
        regime_history.append(regime)
        rp = regime_map.get(regime, (60, 3, 0.25))
        min_score = rp[0] if len(rp) > 0 else 60
        max_pos = rp[1] if len(rp) > 1 else 3
        regime_cap = rp[2] if len(rp) > 2 else 0.25

        next_date = find_next_date(dates, curr_date)
        if not next_date:
            continue

        # =====================================================
        # 第一步: 执行昨日积累的卖出信号 (D 日信号, D+1 开盘执行)
        # =====================================================
        for sell_signal in pending_sells:
            sym = sell_signal["symbol"]
            if sym not in positions:
                continue
            pos = positions[sym]

            # 用 D+1 开盘价卖出
            bars = bars_dict.get(sym, [])
            exit_price = get_open_for_date(bars, curr_date)
            if exit_price <= 0:
                # 如果 D+1 无数据, 用信号日的 close 估算
                exit_price = sell_signal.get("price", pos["entry_price"])

            pnl = (exit_price - pos["entry_price"]) / pos["entry_price"] * 100
            pnl_value = (exit_price - pos["entry_price"]) * pos["shares"]
            cash += pos["shares"] * exit_price

            is_win = pnl > 0
            trades.append({
                "id": len(trades) + 1,
                "symbol": sym,
                "entry_date": pos["entry_date"],
                "exit_date": curr_date,
                "entry_price": round(pos["entry_price"], 2),
                "exit_price": round(exit_price, 2),
                "pnl_pct": round(pnl, 2),
                "pnl_value": round(pnl_value, 2),
                "hold_days": pos["hold"] + 1,
                "exit_reason": sell_signal["reason"],
                "score": pos["score"],
                "grade": pos["grade"],
                "type": pos["type"],
            })
            if is_win:
                win_trades += 1
            else:
                loss_trades += 1
            month_key = curr_date[:7]
            monthly_pnl[month_key].append(pnl)
            del positions[sym]

        pending_sells = []

        # =====================================================
        # 第二步: 检测持仓是否触发卖出信号 (用 curr_date 数据)
        #         但信号存入队列, 下个交易日开盘执行
        # =====================================================
        sell_rules = SellRules(sr)
        for sym, pos in list(positions.items()):
            pos["hold"] += 1
            bars = bars_dict.get(sym, [])
            lb = [b for b in bars if str(b.get("time", "")) <= curr_date]
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
                "tp": pos.get("target_pct", 8),
                "sp": pos.get("stop_pct", -2.8),
            }
            should_sell, sell_price, reason = sell_rules.evaluate(sell_obj, hi, lo, cl, pos["hold"])
            if should_sell:
                pending_sells.append({
                    "symbol": sym,
                    "price": sell_price,
                    "reason": reason,
                })

        # =====================================================
        # 第三步: 用 curr_date 数据筛选候选 (买入信号)
        #         存入队列, D+1 开盘执行
        # =====================================================
        # 先算出可用仓位: 当日卖出后剩余持仓
        sold_symbols_today = {s["symbol"] for s in pending_sells}
        effective_positions = {k: v for k, v in positions.items() if k not in sold_symbols_today}
        available_slots = max_pos - len(effective_positions)

        if available_slots > 0 and cash > 0:
            # 筛选
            candidates = shared_screen(
                bars_dict, curr_date,
                min_vr=hf.get("min_vr", 0.5),
                min_close=min_close,
                ma_pct=hf.get("ma_pct", 0.95),
            )

            # 评分 (排除已持仓和即将卖出的)
            scored = []
            exclude = set(positions.keys())
            for sym in candidates:
                if sym in exclude:
                    continue
                lb = [b for b in bars_dict.get(sym, []) if str(b.get("time", "")) <= curr_date]
                if len(lb) < MIN_BARS:
                    continue
                result = score_momentum_core(lb, sw)
                if result["grade"] in ("A", "B") and result["score"] >= min_score:
                    scored.append((sym, result))
            scored.sort(key=lambda x: -x[1]["score"])

            pending_buys = []
            for sym, result in scored[:available_slots]:
                lb = [b for b in bars_dict[sym] if str(b.get("time", "")) <= curr_date]
                close = _sf(lb[-1].get("close")) if lb else 0
                if close <= 0:
                    continue

                pos_pct = regime_cap
                if result["score"] >= 80:
                    pos_pct = min(regime_cap + 0.05, max_pos_pct)
                elif result["score"] >= 70:
                    pos_pct = regime_cap

                pos_value = cash * pos_pct
                shares = max(1, int(pos_value / close / 100) * 100)
                if shares * close > cash:
                    continue

                pending_buys.append({
                    "symbol": sym,
                    "shares": shares,
                    "entry_price_est": close,  # 估算价格, 实际用 D+1 open
                    "score": result["score"],
                    "grade": result["grade"],
                    "type": result.get("name", ""),
                    "target_pct": result.get("target_pct", 8),
                    "stop_pct": result.get("stop_pct", -2.8),
                })
        else:
            pending_buys = []

        # =====================================================
        # 第四步: 执行昨日积累的买入信号 (D 日信号, D+1 开盘执行)
        # =====================================================
        if pending_buys:
            for buy in pending_buys:
                sym = buy["symbol"]
                bars = bars_dict.get(sym, [])
                entry_price = get_open_for_date(bars, curr_date)
                if entry_price <= 0:
                    continue  # 无开盘数据则放弃

                shares = buy["shares"]
                cost = shares * entry_price
                if cost > cash:
                    # 重新计算可买数量
                    shares = max(1, int(cash / entry_price / 100) * 100)
                    cost = shares * entry_price
                    if cost <= 0:
                        continue

                cash -= cost
                positions[sym] = {
                    "symbol": sym,
                    "entry_date": curr_date,
                    "entry_price": entry_price,
                    "shares": shares,
                    "cost": cost,
                    "highest": entry_price,
                    "highest_pct": 0.0,
                    "hold": 0,  # 从 0 开始, 明天开始计数
                    "score": buy["score"],
                    "grade": buy["grade"],
                    "type": buy["type"],
                    "target_pct": buy["target_pct"],
                    "stop_pct": buy["stop_pct"],
                }
        pending_buys = []

        # --- 日终市值 ---
        pos_value = 0
        for sym, pos in positions.items():
            bars = bars_dict.get(sym, [])
            lb = [b for b in bars if str(b.get("time", "")) <= curr_date]
            if lb:
                pos_value += _sf(lb[-1].get("close")) * pos["shares"]
            else:
                pos_value += pos["cost"]

        total_balance = cash + pos_value
        if total_balance > peak_balance:
            peak_balance = total_balance
        dd = (peak_balance - total_balance) / peak_balance * 100
        if dd > max_drawdown:
            max_drawdown = dd

        if di % 10 == 0:
            print(f"  {curr_date}: balance={total_balance:,.0f} cash={cash:,.0f} "
                  f"pos={len(positions)} regime={regime} dd={dd:.2f}%")

    # --- 期末平仓 ---
    for sym, pos in list(positions.items()):
        bars = bars_dict.get(sym, [])
        lb = [b for b in bars if str(b.get("time", "")) <= END_DATE]
        if lb:
            cl = _sf(lb[-1].get("close"))
        else:
            cl = pos["entry_price"]
        pnl = (cl - pos["entry_price"]) / pos["entry_price"] * 100
        pnl_value = (cl - pos["entry_price"]) * pos["shares"]
        cash += pos["shares"] * cl
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
        if pnl > 0:
            win_trades += 1
        else:
            loss_trades += 1

    positions = {}
    total_return = (cash - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

    # ── 输出报告 ──
    print(f"\n{'='*80}")
    print(f"  回测结果 (修正版)")
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
        total = sum(pnls)
        print(f"  {m}: {len(pnls)}笔 胜{wins}负{losses} "
              f"平均{avg_pnl:+.2f}% 合计{total:+.2f}%")

    # 退出原因统计
    reason_stats = defaultdict(lambda: {"total": 0, "win": 0})
    for t in trades:
        r = t["exit_reason"]
        # 简化为大类
        if "回落40%" in r:
            cat = "回落止盈(40%)"
        elif "回落30%" in r:
            cat = "回落止盈(30%)"
        elif "目标" in r:
            cat = "目标止盈"
        elif "止损" in r:
            cat = "硬止损"
        elif "弱" in r:
            cat = "弱持仓卖出"
        elif "时间" in r:
            cat = "时间卖出"
        elif "保本" in r:
            cat = "保本卖出"
        else:
            cat = r
        reason_stats[cat]["total"] += 1
        if t["pnl_pct"] > 0:
            reason_stats[cat]["win"] += 1

    print(f"\n{'='*80}")
    print(f"  退出原因分析")
    print(f"{'='*80}")
    for r, stats in sorted(reason_stats.items(), key=lambda x: -x[1]["total"]):
        wr = stats["win"] / stats["total"] * 100
        print(f"  {r:<16}: {stats['total']:>4}笔 胜{stats['win']}负{stats['total']-stats['win']} 胜率{wr:>5.1f}%")

    # 评分区间统计
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

    print(f"\n{'='*80}")
    print(f"  评分区间胜率")
    print(f"{'='*80}")
    for bracket, pnls in score_brackets.items():
        if pnls:
            wr = sum(1 for p in pnls if p > 0) / len(pnls) * 100
            avg = sum(pnls) / len(pnls)
            print(f"  {bracket:<8}: {len(pnls):>3}笔 胜率{wr:>5.1f}% 平均{avg:+.2f}% 合计{sum(pnls):+.2f}%")

    # 交易分析
    win_pnls = [t["pnl_pct"] for t in trades if t["pnl_pct"] > 0]
    loss_pnls = [t["pnl_pct"] for t in trades if t["pnl_pct"] <= 0]
    hold_days_list = [t["hold_days"] for t in trades]
    print(f"\n{'='*80}")
    print(f"  综合分析")
    print(f"{'='*80}")
    print(f"  平均盈利:    {sum(win_pnls)/max(len(win_pnls),1):+.2f}%")
    print(f"  平均亏损:    {sum(loss_pnls)/max(len(loss_pnls),1):+.2f}%")
    print(f"  盈亏比:      {abs((sum(win_pnls)/max(len(win_pnls),1))/(sum(loss_pnls)/max(len(loss_pnls),1))):.2f}" if loss_pnls else "  盈亏比:      INF")
    print(f"  最大盈利:    {max(win_pnls):+.2f}%" if win_pnls else "  最大盈利:    N/A")
    print(f"  最大亏损:    {min(loss_pnls):+.2f}%" if loss_pnls else "  最大亏损:    N/A")
    print(f"  平均持仓:    {sum(hold_days_list)/len(hold_days_list):.1f}天")

    # 体制分布
    regime_counts = defaultdict(int)
    for r in regime_history:
        regime_counts[r] += 1
    print(f"\n{'='*80}")
    print(f"  市场体制分布")
    print(f"{'='*80}")
    total_days = len(regime_history)
    names = {"euphoria": "高潮", "hot": "走强", "warmup": "震荡", "cooldown": "退潮", "ice": "极寒"}
    for r in ["euphoria", "hot", "warmup", "cooldown", "ice"]:
        cnt = regime_counts.get(r, 0)
        print(f"  {names.get(r,r):<6} ({r:<10}): {cnt:>3}天 ({cnt/total_days*100:>5.1f}%)")

    # ── 逐笔交易明细 ──
    print(f"\n{'='*80}")
    print(f"  逐笔交易明细 ({len(trades)} 笔)")
    print(f"{'='*80}")
    print(f"  {'#':>3} {'代码':<12} {'入场':<10} {'出场':<10} {'入场价':>7} {'出场价':>7} "
          f"{'盈亏%':>7} {'盈亏额':>9} {'持有':>3} {'二级原因':<20} {'评分':>3}")
    print(f"  {'-'*105}")

    for t in trades[:80]:
        # 简化退出原因显示
        r = t["exit_reason"]
        print(f"  {t['id']:>3} {t['symbol']:<12} {t['entry_date']:<10} {t['exit_date']:<10} "
              f"{t['entry_price']:>7.2f} {t['exit_price']:>7.2f} "
              f"{t['pnl_pct']:>+7.2f} {t['pnl_value']:>+9.0f} {t['hold_days']:>3} "
              f"{r:<20} {t['score']:>3}")

    if len(trades) > 80:
        print(f"  ... 还有 {len(trades) - 80} 笔, 详见完整报告文件")

    print(f"\n{'='*80}")
    print(f"  v2 修正要点:")
    print(f"  1. T+1: 买入后至少 hold=1 才能卖出 (无当天买卖)")
    print(f"  2. 先卖后买: 每日先处理卖出信号, 再处理买入")
    print(f"  3. 次日开盘执行: D日信号 → D+1日开盘价执行")
    print(f"  4. 仓位: 按体制分配 + 单票比例 +可用现金")
    print(f"{'='*80}")

    return {"total_return": total_return, "trades": len(trades)}


if __name__ == "__main__":
    run_backtest_v2()
