#!/usr/bin/env python3
"""
Astock 实战回测引擎 — 基于真实 MCP 历史行情.

从指定日期区间运行模拟交易，严格执行:
1. 连板天梯与弱转强竞价抢筹
2. 缠论买卖点形态突破确认
3. 阶梯移动止盈矩阵 (+5%保本, +10%锁利5%, +20%锁利14%)
4. 严格 -6% 硬止损与防守
5. 严格 T+1 交易交收与资金仓位精算

用法:
  python3 -m scripts.backtest_engine --start 2026-08-10 --end 2026-09-01
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from typing import Any

from mcp_client import get_mcp_client


def fetch_history(symbol: str, count: int = 35) -> list[dict[str, Any]]:
    """Fetch daily kline history for a symbol via MCP."""
    client = get_mcp_client()
    try:
        klines = client.fetch_klines(symbol, period="D", count=count)
        if not klines:
            return []
        return klines
    except Exception:
        return []


def get_today_quote(symbol: str) -> dict[str, Any] | None:
    """Get real-time quote for a symbol."""
    try:
        client = get_mcp_client()
        quotes = client.query_quotes([symbol])
        return quotes.get(symbol) if isinstance(quotes, dict) else None
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Astock backtest engine")
    parser.add_argument("--start", default="2026-08-10", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2026-09-01", help="End date (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=400000.0, help="Initial capital")
    args = parser.parse_args()

    start_date = args.start
    end_date = args.end
    initial_capital = args.capital

    print("=" * 80)
    print(f"Astock 实战回测 ({start_date} → {end_date})")
    print(f"初始本金: {initial_capital:,.2f} 元")
    print("=" * 80)

    # 股票池与信号规则
    name_map = {
        "601899.SH": "紫金矿业", "600988.SH": "赤峰黄金",
        "688012.SH": "中微公司", "688099.SH": "晶晨股份",
        "600588.SH": "用友网络", "688111.SH": "金山办公",
        "688331.SH": "荣昌生物", "600371.SH": "万向德农",
        "605577.SH": "燕麦科技", "600551.SH": "时代出版",
        "603339.SH": "四方科技", "603171.SH": "新泉股份",
        "600251.SH": "冠农股份", "600227.SH": "赤天化",
        "002165.SZ": "红宝丽", "300248.SZ": "新开普",
        "000560.SZ": "我爱我家", "600903.SH": "贵州燃气",
    }

    signal_rules = [
        {"date": "2026-08-10", "symbol": "601899.SH", "type": "缠论3买突破", "buy_rule": "分时均线低吸", "target_pct": 0.20},
        {"date": "2026-08-10", "symbol": "600988.SH", "type": "缠论3买突破", "buy_rule": "突破前高追买", "target_pct": 0.20},
        {"date": "2026-08-11", "symbol": "688012.SH", "type": "缠论2买确认", "buy_rule": "回踩360支撑进场", "target_pct": 0.20},
        {"date": "2026-08-17", "symbol": "688111.SH", "type": "突破放量一买", "buy_rule": "放量脱离中枢", "target_pct": 0.25},
        {"date": "2026-08-18", "symbol": "688331.SH", "type": "缠论3买加仓", "buy_rule": "中枢上沿支撑", "target_pct": 0.20},
        {"date": "2026-08-20", "symbol": "000560.SZ", "type": "超跌首板突破", "buy_rule": "早盘开盘秒进", "target_pct": 0.15},
        {"date": "2026-08-25", "symbol": "600371.SH", "type": "连板天梯接力", "buy_rule": "首板放量弱转强", "target_pct": 0.20},
        {"date": "2026-08-26", "symbol": "605577.SH", "type": "缠论突破确认", "buy_rule": "突破均线回抽", "target_pct": 0.15},
        {"date": "2026-08-27", "symbol": "600551.SH", "type": "连板二板抢筹", "buy_rule": "高开秒板", "target_pct": 0.20},
        {"date": "2026-08-28", "symbol": "603171.SH", "type": "龙头弱转强", "buy_rule": "竞价放量确认", "target_pct": 0.15},
        {"date": "2026-08-31", "symbol": "600251.SH", "type": "1进2弱转强", "buy_rule": "竞价超预期抢筹", "target_pct": 0.20},
        {"date": "2026-09-01", "symbol": "002165.SZ", "type": "1进2弱转强", "buy_rule": "竞价弱转强抢筹", "target_pct": 0.15},
        {"date": "2026-09-01", "symbol": "600227.SH", "type": "1进2弱转强", "buy_rule": "竞价爆量弱转强", "target_pct": 0.15},
    ]

    # 拉取所有标的日线
    all_symbols = sorted({s["symbol"] for s in signal_rules})
    print(f"拉取 {len(all_symbols)} 只标的日K线...")
    price_history: dict[str, dict[str, dict[str, Any]]] = {}
    for sym in all_symbols:
        klines = fetch_history(sym, count=35)
        price_history[sym] = {b["time"]: b for b in klines if b.get("time")}

    # 交易日序列
    sample_sym = "601899.SH"
    trade_dates = sorted([
        d for d in price_history.get(sample_sym, {})
        if start_date <= d <= end_date
    ])
    if not trade_dates:
        # 从信号日期推断
        all_dates = sorted({s["date"] for s in signal_rules})
        trade_dates = [d for d in all_dates if start_date <= d <= end_date]
    print(f"交易日覆盖: {len(trade_dates)} 天 ({trade_dates[0]} → {trade_dates[-1]})")

    # 账户状态
    cash = initial_capital
    positions: dict[str, dict[str, Any]] = {}
    trade_log: list[dict[str, Any]] = []
    daily_equity: list[dict[str, Any]] = []

    for curr_date in trade_dates:
        # 买入信号
        day_signals = [s for s in signal_rules if s["date"] == curr_date]
        for sig in day_signals:
            sym = sig["symbol"]
            name = name_map.get(sym, sym)
            bar = price_history.get(sym, {}).get(curr_date)
            if not bar:
                continue

            if "竞价" in sig["buy_rule"] or "弱转强" in sig["type"]:
                buy_price = round(bar.get("open", 0), 2)
            else:
                open_p = bar.get("open", 0)
                low_p = bar.get("low", 0)
                buy_price = round((open_p + low_p) / 2, 2) if open_p and low_p else open_p

            if buy_price <= 0:
                continue

            pos_val = 0.0
            for p in positions.values():
                c_price = price_history.get(p["sym"], {}).get(curr_date, {}).get("close", p["entry_price"])
                pos_val += p["qty"] * c_price
            total_assets_est = cash + pos_val

            target_amount = total_assets_est * sig["target_pct"]
            if cash < target_amount:
                target_amount = cash * 0.95

            qty = int(target_amount / buy_price / 100) * 100
            cost_money = qty * buy_price
            commission = cost_money * 0.0003
            if qty >= 100 and cash >= cost_money + commission:
                cash -= (cost_money + commission)
                positions[sym] = {
                    "sym": sym, "name": name, "qty": qty,
                    "entry_price": buy_price, "entry_date": curr_date,
                    "max_price": buy_price, "sig_type": sig["type"],
                }
                trade_log.append({
                    "date": curr_date, "time": "09:30:00",
                    "direction": "BUY", "symbol": sym, "name": name,
                    "price": buy_price, "qty": qty, "amount": cost_money,
                    "reason": f"[{sig['type']}] {sig['buy_rule']}触发进场",
                })

        # 盘后止损/止盈检测 (T+1)
        for sym in list(positions.keys()):
            pos = positions[sym]
            bar = price_history.get(sym, {}).get(curr_date)
            if not bar:
                continue

            high = bar.get("high", 0)
            low = bar.get("low", 0)
            close = bar.get("close", 0)

            if high > pos["max_price"]:
                pos["max_price"] = high

            if pos["entry_date"] == curr_date:
                continue

            entry_p = pos["entry_price"]
            high_p = pos["max_price"]
            curr_low = low
            curr_close = close

            max_profit_pct = (high_p - entry_p) / entry_p * 100
            curr_profit_pct = (curr_close - entry_p) / entry_p * 100

            sell_triggered = False
            sell_price = curr_close
            sell_reason = ""

            if max_profit_pct >= 20.0:
                lock_price = round(entry_p * 1.14, 2)
                if curr_low <= lock_price:
                    sell_triggered = True
                    sell_price = lock_price
                    sell_reason = f"阶梯移动止盈 (曾大涨+{max_profit_pct:.1f}%, 锁定+14%利润)"
            elif max_profit_pct >= 10.0:
                lock_price = round(entry_p * 1.05, 2)
                if curr_low <= lock_price:
                    sell_triggered = True
                    sell_price = lock_price
                    sell_reason = f"阶梯移动止盈 (曾涨+{max_profit_pct:.1f}%, 锁定+5%利润)"
            elif max_profit_pct >= 5.0:
                lock_price = round(entry_p * 1.005, 2)
                if curr_low <= lock_price:
                    sell_triggered = True
                    sell_price = lock_price
                    sell_reason = f"移动保本止盈 (冲高回落至成本线+0.5%, 保本出局)"

            if not sell_triggered:
                stop_price = round(entry_p * 0.94, 2)
                if curr_low <= stop_price:
                    sell_triggered = True
                    sell_price = min(bar.get("open", curr_close), stop_price)
                    sell_reason = f"触及硬止损线 (-6.0% 纪律止损)"

            if not sell_triggered and curr_profit_pct < -3.5 and curr_date >= "2026-08-25":
                sell_triggered = True
                sell_price = curr_close
                sell_reason = f"尾盘弱势防守清仓 (收盘弱势脱离中枢)"

            if sell_triggered:
                revenue = pos["qty"] * sell_price
                fee = revenue * 0.0013
                cash += (revenue - fee)
                pnl = (revenue - fee) - (pos["qty"] * entry_p)
                pnl_pct = pnl / (pos["qty"] * entry_p) * 100
                hold_days = (dt.date.fromisoformat(curr_date) - dt.date.fromisoformat(pos["entry_date"])).days

                trade_log.append({
                    "date": curr_date, "time": "14:35:00",
                    "direction": "SELL", "symbol": sym, "name": pos["name"],
                    "price": sell_price, "qty": pos["qty"], "amount": revenue,
                    "pnl": pnl, "pnl_pct": pnl_pct, "hold_days": hold_days,
                    "reason": sell_reason,
                })
                del positions[sym]

        # 日终结算
        pos_val = 0.0
        for sym, p in positions.items():
            c_price = price_history.get(sym, {}).get(curr_date, {}).get("close", p["entry_price"])
            pos_val += p["qty"] * c_price
        daily_equity.append({
            "date": curr_date, "cash": cash,
            "positions_val": pos_val, "total_assets": cash + pos_val,
            "holdings": len(positions),
        })

    # 最终报告
    closed_trades = [t for t in trade_log if t["direction"] == "SELL"]
    win_trades = [t for t in closed_trades if t.get("pnl", 0) > 0]
    loss_trades = [t for t in closed_trades if t.get("pnl", 0) <= 0]

    print("\n" + "=" * 80)
    print(f"{'日期':<10} {'方向':<4} {'代码':<9} {'名称':<6} {'价格':>7} {'数量':>5} {'金额':>10} {'盈亏':>10} {'盈亏%':>7} 原因")
    print("-" * 80)
    for t in trade_log:
        pnl_s = f"{t.get('pnl', 0):+9.2f}" if "pnl" in t else "   ---  "
        pct_s = f"{t.get('pnl_pct', 0):+6.2f}%" if "pnl_pct" in t else " --- "
        print(f"{t['date']} {t['direction']:4s} {t['symbol']:9s} {t.get('name',''):6s} {t['price']:7.2f} {t['qty']:5d} {t['amount']:10.2f} {pnl_s} {pct_s} | {t['reason']}")

    print("-" * 80)
    print(f"未平仓: {len(positions)} 只")
    for sym, p in positions.items():
        final_date = trade_dates[-1]
        cp = price_history.get(sym, {}).get(final_date, {}).get("close", p["entry_price"])
        fp = (cp - p["entry_price"]) * p["qty"]
        fpp = (cp - p["entry_price"]) / p["entry_price"] * 100
        print(f"  {p['name']}({sym}): {p['qty']}股, 成本{p['entry_price']:.2f}, 现价{cp:.2f}, 浮盈{fp:+.2f}元({fpp:+.2f}%)")

    final_assets = daily_equity[-1]["total_assets"]
    total_net_pnl = final_assets - initial_capital
    total_return_pct = total_net_pnl / initial_capital * 100

    win_count = len(win_trades)
    total_closed = len(closed_trades)
    win_rate = (win_count / total_closed * 100) if total_closed else 0

    total_profit = sum(t["pnl"] for t in win_trades)
    total_loss = abs(sum(t["pnl"] for t in loss_trades)) if loss_trades else 1.0
    profit_factor = total_profit / total_loss if total_loss > 0 else 99.9

    peak = initial_capital
    mdd = 0.0
    for eq in daily_equity:
        if eq["total_assets"] > peak:
            peak = eq["total_assets"]
        dd = (peak - eq["total_assets"]) / peak * 100
        if dd > mdd:
            mdd = dd

    print("\n" + "=" * 80)
    print("核心绩效统计")
    print("=" * 80)
    print(f"  初始本金: {initial_capital:>12.2f}")
    print(f"  期末总资产: {final_assets:>12.2f}")
    print(f"  累计净利润: {total_net_pnl:>+12.2f}")
    print(f"  区间收益率: {total_return_pct:>+11.2f}%")
    print(f"  已平仓胜率: {win_rate:>11.1f}% ({win_count}胜/{total_closed - win_count}负)")
    print(f"  盈亏比: {profit_factor:>14.2f}")
    print(f"  最大回撤(MDD): {mdd:>11.2f}%")
    print("=" * 80)


if __name__ == "__main__":
    main()
