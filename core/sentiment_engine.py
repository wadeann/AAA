#!/usr/bin/env python3
"""情绪周期引擎 — 根据市场情绪自动调节仓位倍数和策略门限。"""

from __future__ import annotations

import datetime as dt
from typing import Any


def compute_sentiment() -> dict[str, Any]:
    """获取市场情绪阶段。

    优先拉取四大指数实时涨跌判断情绪相位。
    防御性 market_regime 是唯一优先真理源。
    返回: {phase, multiplier, description, cand_count, updated_at}
    """
    from mcp_client import get_mcp_client
    from data import get_data_manager

    dm = get_data_manager()
    client = get_mcp_client()

    # 检查 market_regime 防御状态
    regime = dm.load_state("market_regime.json")
    standard = str(regime.get("standard_regime") or "")
    defensive = (
        regime.get("sell_only_mode") is True
        or regime.get("fail_closed") is True
        or standard in {"freezing", "panic_ebb"}
        or float(regime.get("regime_multiplier", 1.0) or 0.0) == 0.0
    )
    if defensive and regime:
        return {
            "phase": "ice" if standard == "freezing" or regime.get("regime") == "极寒" else "cooldown",
            "multiplier": 0.0,
            "description": str(regime.get("description") or "市场状态机防御熔断，只卖不买"),
            "cand_count": 0,
            "updated_at": str(regime.get("updated_at") or dt.datetime.now(dt.timezone.utc).isoformat()),
        }

    # 统计今日候选数
    today = dt.date.today().isoformat()
    candidates = dm.load_candidates(today)
    cand_count = len(candidates)

    # 拉取四大指数实时涨跌
    indices_chg: list[float] = []
    try:
        quotes = client.query_quotes(["000001.SH", "399001.SZ", "399006.SZ", "000688.SH"])
        for s in ["000001.SH", "399001.SZ", "399006.SZ", "000688.SH"]:
            if s in quotes and isinstance(quotes[s], dict):
                chg = quotes[s].get("change_pct")
                if chg is not None:
                    indices_chg.append(float(chg))
    except Exception:
        pass

    if indices_chg:
        avg_chg = sum(indices_chg) / len(indices_chg)
        if avg_chg > 1.2:
            phase = "euphoria"
            multiplier = 0.85
            desc = f"高潮狂热期 (指数均涨{avg_chg:+.2f}%), 适度控仓防退潮分歧"
        elif avg_chg >= 0.4:
            phase = "hot"
            multiplier = 0.75
            desc = f"主升走强期 (指数均涨{avg_chg:+.2f}%), 顺势做多主线龙头"
        elif avg_chg >= -0.3:
            phase = "warmup"
            multiplier = 0.45
            desc = f"震荡启动期 (指数均涨{avg_chg:+.2f}%), 中等仓位聚焦核心"
        elif avg_chg >= -1.2:
            phase = "cooldown"
            multiplier = 0.25
            desc = f"退潮分歧期 (指数均涨{avg_chg:+.2f}%), 低仓防守严格止损"
        else:
            phase = "ice"
            multiplier = 0.15
            desc = f"冰点恐慌期 (指数均涨{avg_chg:+.2f}%), 防守保命等待企稳"
    else:
        if cand_count > 30:
            phase, multiplier, desc = "hot", 0.70, f"盘中活跃 (候选数:{cand_count}), 加大仓位"
        elif cand_count > 5:
            phase, multiplier, desc = "warmup", 0.40, f"启动阶段 (候选数:{cand_count}), 中等仓位"
        else:
            phase, multiplier, desc = "warmup", 0.30, "盘前默认: 启动期保守底仓"

    result = {
        "phase": phase,
        "multiplier": multiplier,
        "description": desc,
        "cand_count": cand_count,
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    dm.save_state("sentiment.json", result)
    return result


def get_strategy_blacklist(feedback_content: str = "") -> list[str]:
    """从策略反馈内容读取低胜率策略，自动加入黑名单。"""
    import re
    stop_list: list[str] = []

    if not feedback_content:
        return stop_list

    # 匹配标准统计行: technical_breakout：8笔，2盈6亏，胜率 25.0%
    for m in re.finditer(r'[-*]?\s*([a-zA-Z0-9_]+)[：:]\s*(\d+)笔[，,].*?胜率\s*([\d.]+)%', feedback_content):
        strategy = m.group(1).strip()
        sample = int(m.group(2))
        win_rate = float(m.group(3))
        if sample >= 5 and win_rate < 40 and strategy not in stop_list:
            stop_list.append(strategy)

    # 匹配表格形式
    for m in re.finditer(r'\|\s*([a-zA-Z0-9_]+)\s*\|\s*(\d+)\s*\|\s*([\d.]+)%', feedback_content):
        strategy = m.group(1).strip()
        sample = int(m.group(2))
        win_rate = float(m.group(3))
        if sample >= 5 and win_rate < 40 and strategy not in stop_list:
            stop_list.append(strategy)

    # 强制加入低胜率策略
    for forced in ["technical_breakout"]:
        if forced not in stop_list:
            stop_list.append(forced)

    return stop_list


if __name__ == "__main__":
    sent = compute_sentiment()
    print(f"情绪: {sent['phase']}, 乘数: {sent['multiplier']}")
    print(f"描述: {sent['description']}")
