#!/usr/bin/env python3
"""盘口微观时空条件求值引擎 (R36).

移植至 Astock: 路径导入替换为 astock 模块导入.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

from utils.broken_guard import check_broken_and_fake_healing


class ConditionResult(dict):
    """兼容字典访问 res['pass'] 与元组解包 ok, msg = res 的结果容器."""

    def __init__(self, passed: bool, reason: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self["pass"] = bool(passed)
        self["reason"] = str(reason)

    def __iter__(self):
        return iter((self["pass"], self["reason"]))

    def __bool__(self) -> bool:
        return bool(self["pass"])


def extract_quote_metrics(quote: dict[str, Any]) -> dict[str, Any]:
    """从多源quote字典中提取标准量化指标."""
    open_p = float(quote.get("open", quote.get("open_price", 0)) or 0)
    pre_close = float(quote.get("pre_close", quote.get("last_close", quote.get("prev_close", 0))) or 0)
    curr_p = float(quote.get("price", quote.get("current", quote.get("close", 0))) or 0)

    if "open_pct" in quote:
        open_pct = float(quote["open_pct"])
    elif pre_close > 0 and open_p > 0:
        open_pct = round((open_p - pre_close) / pre_close * 100, 2)
    elif "change_pct" in quote:
        open_pct = float(quote["change_pct"])
    else:
        open_pct = 0.0

    if "change_pct" in quote:
        current_pct = float(quote["change_pct"])
    elif pre_close > 0 and curr_p > 0:
        current_pct = round((curr_p - pre_close) / pre_close * 100, 2)
    else:
        current_pct = open_pct

    is_sealed = bool(quote.get("is_sealed", False))
    if not is_sealed and current_pct >= 9.8:
        ask1_val = quote.get("ask1_volume", quote.get("ask_vol1"))
        if ask1_val is not None:
            ask1_vol = float(ask1_val)
            if ask1_vol == 0 or quote.get("seal_amount", 0) > 0:
                is_sealed = True

    high_p = float(quote.get("high", quote.get("high_price", curr_p)) or curr_p)
    low_p = float(quote.get("low", quote.get("low_price", curr_p)) or curr_p)
    if pre_close > 0 and high_p > 0:
        high_pct = round((high_p - pre_close) / pre_close * 100, 2)
    else:
        high_pct = current_pct
    if pre_close > 0 and low_p > 0:
        low_pct = round((low_p - pre_close) / pre_close * 100, 2)
    else:
        low_pct = current_pct

    auction_volume = float(quote.get("auction_volume", quote.get("bid_volume", 0)) or 0)
    auction_amount = float(quote.get("auction_amount", quote.get("bid_amount", 0)) or 0)

    return {
        "open_price": open_p, "pre_close": pre_close, "current_price": curr_p,
        "high_price": high_p, "low_price": low_p,
        "open_pct": open_pct, "current_pct": current_pct, "high_pct": high_pct, "low_pct": low_pct,
        "is_sealed": is_sealed, "exploded": bool(quote.get("exploded", quote.get("is_exploded", False))),
        "auction_volume": auction_volume, "auction_amount": auction_amount,
        "speed_pct_3min": float(quote.get("speed_pct_3min", 0) or 0),
    }


def evaluate_auction_condition(
    cand: dict[str, Any], quote: Optional[dict[str, Any]] = None,
    auction_pct: Optional[float] = None,
) -> ConditionResult:
    """核验竞价涨幅是否在条件范围内."""
    direction = cand.get("direction", "buy")
    if direction != "buy":
        return ConditionResult(True, "sell_no_auction_check")

    triggers = cand.get("condition_triggers") or {}
    min_pct = triggers.get("auction_open_min_pct") if triggers else cand.get("auction_open_min_pct")
    max_pct = triggers.get("auction_open_max_pct") if triggers else cand.get("auction_open_max_pct")

    if auction_pct is not None:
        pct = float(auction_pct)
    elif quote:
        metrics = extract_quote_metrics(quote)
        pct = metrics["open_pct"]
    else:
        if min_pct is None and max_pct is None:
            return ConditionResult(True, "竞价条件默认放行")
        return ConditionResult(False, "missing_quote_and_pct")

    if min_pct is not None and pct < float(min_pct):
        return ConditionResult(False, f"竞价高开 {pct:.2f}% < 门槛 {float(min_pct):.2f}%")
    if max_pct is not None and pct > float(max_pct):
        return ConditionResult(False, f"竞价高开 {pct:.2f}% > 上限 {float(max_pct):.2f}%")

    anchor = triggers.get("dependency_anchor") or cand.get("dependency_anchor")
    if anchor and isinstance(anchor, dict) and quote:
        anchor_sym = anchor.get("symbol")
        anchors_data = quote.get("anchors", {})
        if anchor_sym and anchor_sym in anchors_data:
            a_metrics = extract_quote_metrics(anchors_data[anchor_sym])
            min_a = anchor.get("min_auction_open_pct")
            if min_a is not None and a_metrics["open_pct"] < float(min_a):
                return ConditionResult(False, f"锚定 {anchor_sym} 竞价 {a_metrics['open_pct']:.2f}% < {float(min_a):.2f}%")
            if anchor.get("must_not_explode") and a_metrics["exploded"]:
                return ConditionResult(False, f"锚定 {anchor_sym} 炸板破位")

    return ConditionResult(True, f"竞价达标 (open={pct:.2f}%)")


def evaluate_intraday_condition(
    cand: dict[str, Any], quote: Optional[dict[str, Any]] = None,
    now_time: Optional[str] = None, current_pct: Optional[float] = None,
) -> ConditionResult:
    """盘中条件核验: 追高阈值、封板时效."""
    direction = cand.get("direction", "buy")
    if direction != "buy":
        return ConditionResult(True, "sell_no_intraday_check")

    if quote or current_pct is not None:
        sym = cand.get("symbol") or (quote.get("symbol") if quote else "")
        if quote:
            metrics = extract_quote_metrics(quote)
            cur_p = metrics["current_price"]
            high_p = metrics["high_price"]
            low_p = metrics["low_price"]
            pre_close = metrics["pre_close"]
            was_limit = quote.get("was_limit_up_today", cand.get("was_limit_up_today"))
        else:
            cur_p = float(cand.get("price", cand.get("current_price", 0)) or 0)
            high_p = float(cand.get("high", cand.get("high_price", cur_p)) or cur_p)
            low_p = float(cand.get("low", cand.get("low_price", cur_p)) or cur_p)
            pre_close = float(cand.get("pre_close", 0) or 0)
            was_limit = cand.get("was_limit_up_today")

        if cur_p > 0 and pre_close > 0:
            ok, reason = check_broken_and_fake_healing(
                symbol=sym, cur_price=cur_p, high_price=high_p, low_price=low_p,
                pre_close=pre_close, was_limit_up_today=was_limit,
            )
            if not ok:
                return ConditionResult(False, "炸板破位/假自愈一票否决")

    triggers = cand.get("condition_triggers") or {}
    max_chase = triggers.get("max_chase_pct") if triggers else cand.get("max_chase_pct")
    must_seal_before = triggers.get("must_seal_before") if triggers else cand.get("must_seal_before")

    if current_pct is not None:
        pct = float(current_pct)
        is_sealed = pct >= 9.8
    elif quote:
        metrics = extract_quote_metrics(quote)
        pct = metrics["current_pct"]
        is_sealed = metrics["is_sealed"]
    else:
        pct = 0.0
        is_sealed = False

    if max_chase is not None and pct > float(max_chase):
        return ConditionResult(False, f"当前涨幅 {pct:.2f}% > 最高追高门槛 {float(max_chase):.2f}%")

    if must_seal_before:
        check_time = now_time or dt.datetime.now(dt.timezone.utc).strftime("%H:%M")
        if check_time[:5] > str(must_seal_before)[:5] and not is_sealed:
            return ConditionResult(False, f"未在 {must_seal_before} 前封板 ({check_time})")

    return ConditionResult(True, f"盘中达标 (current={pct:.2f}%)")


def evaluate_dependency(
    cand: dict[str, Any], sentinel_quotes: dict[str, dict[str, Any]],
) -> ConditionResult:
    """核验依赖标的."""
    triggers = cand.get("condition_triggers") or {}
    dep = triggers.get("dependency_anchor") or cand.get("dependency_anchor")
    if not dep or not isinstance(dep, dict):
        return ConditionResult(True, "no_dependency")
    dep_sym = dep.get("symbol")
    if not dep_sym:
        return ConditionResult(True, "no_dependency_symbol")
    dep_quote = sentinel_quotes.get(dep_sym)
    if not dep_quote:
        return ConditionResult(False, f"dependency {dep_sym} quote unavailable")
    dep_metrics = extract_quote_metrics(dep_quote)
    min_pct = dep.get("min_auction_open_pct")
    if min_pct is not None and dep_metrics["open_pct"] < float(min_pct):
        return ConditionResult(False, f"锚定 {dep_sym} 竞价 {dep_metrics['open_pct']:.2f}% < {float(min_pct):.2f}%")
    if dep.get("must_not_explode") and dep_metrics["exploded"]:
        return ConditionResult(False, f"锚定 {dep_sym} 炸板破位")
    return ConditionResult(True, "dependency_ok")


def evaluate_chip_condition(
    quote: dict[str, Any], condition: Optional[dict[str, Any]] = None,
) -> ConditionResult:
    """核验筹码分布安全性."""
    condition = condition or {}

    direction = condition.get("direction", quote.get("direction", "buy"))
    if direction != "buy":
        return ConditionResult(True, "sell_no_chip_check")

    sym = str(quote.get("symbol", condition.get("symbol", "")))
    price = float(quote.get("price", quote.get("current", quote.get("close", condition.get("price", 0.0)))) or 0.0)
    streak = int(condition.get("streak", quote.get("streak", 1)) or 1)
    is_sub_new = bool(condition.get("is_sub_new", quote.get("is_sub_new", False)))

    chip_data = quote.get("chip_data") or condition.get("chip_data")
    if chip_data is None:
        direct_chip = {}
        for k in ("chipProfitRate", "chip_profit_rate", "profit_rate", "获利盘比例"):
            if k in quote and quote[k] is not None:
                direct_chip["chipProfitRate"] = quote[k]; break
            elif k in condition and condition[k] is not None:
                direct_chip["chipProfitRate"] = condition[k]; break
        for k in ("chipAvgCost", "chip_avg_cost", "avg_cost", "平均成本"):
            if k in quote and quote[k] is not None:
                direct_chip["chipAvgCost"] = quote[k]; break
            elif k in condition and condition[k] is not None:
                direct_chip["chipAvgCost"] = condition[k]; break
        if direct_chip:
            chip_data = direct_chip

    try:
        from utils.chip import evaluate_chip_safety
        chip_res = evaluate_chip_safety(symbol=sym, current_price=price, streak=streak,
                                        is_sub_new=is_sub_new, chip_data=chip_data)
        if not chip_res.is_safe:
            return ConditionResult(False, chip_res.reason, chip_safe=False, chip_details=chip_res.details)

        min_profit = condition.get("min_chip_profit_rate") or condition.get("condition_triggers", {}).get("min_chip_profit_rate")
        if min_profit is not None and not is_sub_new and chip_res.chip_profit_rate < float(min_profit):
            return ConditionResult(False, f"获利盘比例 {chip_res.chip_profit_rate:.1f}% < {float(min_profit):.1f}%",
                                   chip_safe=False, chip_details=chip_res.details)
        return ConditionResult(True, chip_res.reason, chip_safe=True, chip_details=chip_res.details)
    except Exception as e:
        return ConditionResult(True, f"筹码评估异常降级放行: {e}", chip_safe=True)


def evaluate_fund_flow_condition(
    quote: dict[str, Any], condition: Optional[dict[str, Any]] = None,
) -> ConditionResult:
    """核验主力资金真实流向."""
    condition = condition or {}

    direction = condition.get("direction", quote.get("direction", "buy"))
    if direction != "buy":
        return ConditionResult(True, "sell_no_fund_flow_check")

    sym = str(quote.get("symbol", condition.get("symbol", "")))
    price = float(quote.get("price", quote.get("current", quote.get("close", condition.get("price", 0.0)))) or 0.0)
    turnover_amt = float(quote.get("amount", quote.get("turnover_amount", condition.get("amount", 0.0))) or 0.0)

    fund_data = quote.get("fund_data") or condition.get("fund_data")
    if fund_data is None:
        direct_fund = {}
        for k in ("MainNetFlow", "main_net_flow", "主力净额", "主力净流入"):
            if k in quote and quote[k] is not None:
                direct_fund["MainNetFlow"] = quote[k]; break
            elif k in condition and condition[k] is not None:
                direct_fund["MainNetFlow"] = condition[k]; break
        if direct_fund:
            fund_data = direct_fund

    try:
        from utils.fund_flow import evaluate_fund_flow_safety
        fund_res = evaluate_fund_flow_safety(symbol=sym, current_price=price,
                                             turnover_amount=turnover_amt, fund_data=fund_data)
        if not fund_res.is_safe:
            return ConditionResult(False, fund_res.reason, fund_flow_safe=False, fund_flow_details=fund_res.details)

        min_main = condition.get("min_main_net_flow") or condition.get("condition_triggers", {}).get("min_main_net_flow")
        if min_main is not None and fund_res.main_net_flow < float(min_main):
            return ConditionResult(False, f"主力净额 {fund_res.main_net_flow/1e4:.0f}万 < {float(min_main)/1e4:.0f}万",
                                   fund_flow_safe=False, fund_flow_details=fund_res.details)
        return ConditionResult(True, fund_res.reason, fund_flow_safe=True, fund_flow_details=fund_res.details)
    except Exception as e:
        return ConditionResult(True, f"资金流向评估异常降级放行: {e}", fund_flow_safe=True)


def evaluate_trailing_profit_condition(
    pos: dict[str, Any], quote: Optional[dict[str, Any]] = None,
    watermark: Optional[dict[str, Any]] = None, tighten_stops: bool = False,
) -> ConditionResult:
    """卖出端: 阶梯动态追踪止盈与保本锁."""
    quote = quote or {}
    cost = float(pos.get("cost_price", 0.0) or 0.0)
    cur_p = float(quote.get("price", quote.get("close", pos.get("current_price", cost))) or cost)
    high_p = float(quote.get("high", cur_p) or cur_p)
    pre_close = float(quote.get("pre_close", quote.get("prev_close", 0.0)) or 0.0)
    sym = str(pos.get("symbol", quote.get("symbol", "")))

    if cost <= 0.0 or cur_p <= 0.0:
        return ConditionResult(False, "成本价或现价无效")

    wm_dict = watermark if isinstance(watermark, dict) else {}
    high_wm_p = float(wm_dict.get("high_watermark_price", max(high_p, cur_p)) or max(high_p, cur_p))
    high_wm_pct = float(wm_dict.get("high_watermark_pct", (high_wm_p - cost) / cost * 100.0))

    pnl_pct = (cur_p - cost) / cost * 100.0
    drawdown_from_wm = high_wm_pct - pnl_pct

    tier0_wm_thresh = 2.0 if tighten_stops else 3.0
    tier0_breakeven_line = cost * 1.001 if tighten_stops else cost * 1.002
    tier2_wm_thresh = 7.0 if tighten_stops else 9.0
    tier2_drawdown_thresh = 2.0 if tighten_stops else 3.0
    tier2_min_pnl = 4.0 if tighten_stops else 6.0

    # 触板破位铁律
    if pre_close > 0.0 and high_p > 0.0:
        try:
            from utils.broken_guard import compute_limit_pct
            limit_pct = compute_limit_pct(sym, pre_close)
        except Exception:
            limit_pct = 9.9
        high_gain_pct = (high_p - pre_close) / pre_close * 100.0
        cur_gain_pct = (cur_p - pre_close) / pre_close * 100.0
        dd = high_gain_pct - cur_gain_pct
        touched = (high_gain_pct >= limit_pct - 0.5) or bool(quote.get("was_limit_up_today", False))
        if touched and (dd > 4.0 or cur_gain_pct < 0.0):
            return ConditionResult(True, f"触板破位: 曾触涨停回撤{dd:.1f}%或翻绿({cur_gain_pct:+.1f}%)",
                                   action="sell_all", trigger_tier="broken_limit", drawdown_pct=dd)

    # Tier 2 核心锁利
    if high_wm_pct >= tier2_wm_thresh:
        if drawdown_from_wm >= tier2_drawdown_thresh or pnl_pct < tier2_min_pnl:
            return ConditionResult(True, f"Tier 2核心锁利: 最高浮盈+{high_wm_pct:.2f}%回撤{drawdown_from_wm:.2f}%",
                                   action="sell_all", trigger_tier="tier2",
                                   high_wm_pct=high_wm_pct, drawdown_pct=drawdown_from_wm)

    # Tier 0 保本锁
    if high_wm_pct >= tier0_wm_thresh and cur_p <= tier0_breakeven_line:
        return ConditionResult(True, f"Tier 0保本锁: 最高浮盈+{high_wm_pct:.2f}%跌破成本价",
                               action="sell_all", trigger_tier="tier0", high_wm_pct=high_wm_pct)

    return ConditionResult(False, "未触及止盈条件", high_wm_pct=high_wm_pct, pnl_pct=pnl_pct)


def evaluate_scale_out_condition(
    pos: dict[str, Any], quote: Optional[dict[str, Any]] = None,
    watermark: Optional[dict[str, Any]] = None, tighten_stops: bool = False,
) -> ConditionResult:
    """第一级动态止盈与分批锁利 (50% scale-out)."""
    quote = quote or {}
    cost = float(pos.get("cost_price", 0.0) or 0.0)
    cur_p = float(quote.get("price", quote.get("close", pos.get("current_price", cost))) or cost)
    high_p = float(quote.get("high", cur_p) or cur_p)
    if cost <= 0.0 or cur_p <= 0.0:
        return ConditionResult(False, "成本价或现价无效")
    wm_dict = watermark if isinstance(watermark, dict) else {}
    if wm_dict.get("scale_out_executed", False):
        return ConditionResult(False, "Tier 1分批止盈已执行过", scale_out_executed=True)
    high_wm_p = float(wm_dict.get("high_watermark_price", max(high_p, cur_p)) or max(high_p, cur_p))
    high_wm_pct = float(wm_dict.get("high_watermark_pct", (high_wm_p - cost) / cost * 100.0))
    pnl_pct = (cur_p - cost) / cost * 100.0
    drawdown_from_wm = high_wm_pct - pnl_pct
    tier1_wm_thresh = 4.5 if tighten_stops else 6.0
    tier1_drawdown_thresh = 1.8 if tighten_stops else 2.5
    tier1_min_pnl = 2.0 if tighten_stops else 3.0
    if high_wm_pct >= tier1_wm_thresh:
        if drawdown_from_wm >= tier1_drawdown_thresh or pnl_pct <= tier1_min_pnl:
            return ConditionResult(True, f"Tier 1分批止盈: 最高浮盈+{high_wm_pct:.2f}%回撤{drawdown_from_wm:.2f}%",
                                   action="scale_out_50", scale_ratio=0.5,
                                   high_wm_pct=high_wm_pct, drawdown_pct=drawdown_from_wm)
    return ConditionResult(False, "未触及分批止盈条件", high_wm_pct=high_wm_pct, pnl_pct=pnl_pct)


def evaluate_all(
    cand: dict[str, Any], quote: Optional[dict[str, Any]] = None,
    now_time: Optional[str] = None,
    sentinel_quotes: Optional[dict[str, dict[str, Any]]] = None,
    auction_pct: Optional[float] = None, current_pct: Optional[float] = None,
    index_quotes: Optional[dict[str, dict[str, Any]]] = None,
    sector_quote: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """全量核验: 竞价+盘中+依赖+大盘熔断+板块偏离+涨速+竞价金额."""
    result: dict[str, Any] = {"pass": True, "checks": {}, "first_failure": None}

    # 大盘指数熔断校验
    if index_quotes and cand.get("direction", "buy") == "buy":
        major_keys = ["000001", "399001", "399006", "000688"]
        matched_drops = []
        for m_key in major_keys:
            for idx_sym, idx_q in index_quotes.items():
                if m_key in idx_sym:
                    m_pct = extract_quote_metrics(idx_q)["current_pct"]
                    matched_drops.append((m_key, m_pct))
                    break
        if len(matched_drops) >= 3 and all(pct <= -1.0 for _, pct in matched_drops):
            drops = ", ".join(f"{k}:{p:.2f}%" for k, p in matched_drops)
            result["checks"]["index_meltdown"] = ConditionResult(False, f"四指数同时跌超-1% ({drops})")
            result["pass"] = False
            result["first_failure"] = "四大指数同时跌超-1%熔断"
            return result

        for idx_sym, idx_q in index_quotes.items():
            idx_metrics = extract_quote_metrics(idx_q)
            idx_pct = idx_metrics["current_pct"]
            if "000001" in idx_sym or "SH" in idx_sym:
                if idx_pct <= -2.0:
                    result["checks"]["index_meltdown"] = ConditionResult(False, f"上证 {idx_pct:.2f}% 跌超-2%")
                    result["pass"] = False; result["first_failure"] = f"上证熔断({idx_pct:.2f}%)"
                    break
        if not result["pass"]:
            return result

        for idx_sym, idx_q in index_quotes.items():
            idx_metrics = extract_quote_metrics(idx_q)
            idx_pct = idx_metrics["current_pct"]
            if "399006" in idx_sym or "CYB" in idx_sym:
                if idx_pct <= -3.0:
                    result["checks"]["index_meltdown"] = ConditionResult(False, f"创业板 {idx_pct:.2f}% 跌超-3%")
                    result["pass"] = False; result["first_failure"] = f"创业板熔断({idx_pct:.2f}%)"
                    break
        if not result["pass"]:
            return result

    # 板块偏离度
    if sector_quote and quote and cand.get("direction", "buy") == "buy":
        stock_pct = extract_quote_metrics(quote)["current_pct"]
        sector_pct = extract_quote_metrics(sector_quote)["current_pct"]
        deviation = stock_pct - sector_pct
        if stock_pct >= 9.8 and sector_pct <= -2.0:
            result["checks"]["sector_deviation"] = ConditionResult(False, f"涨停但板块跌{sector_pct:.1f}%")
            result["pass"] = False; result["first_failure"] = f"板块偏离({deviation:.1f}pt)"
            return result
        if sector_pct <= -1.5 and stock_pct >= 3.0:
            result["checks"]["sector_deviation"] = ConditionResult(False, f"板块跌{sector_pct:.1f}%标的涨{stock_pct:.1f}%")
            result["pass"] = False; result["first_failure"] = f"弱势板块伪强({deviation:.1f}pt)"
            return result

    # 涨速过滤
    if quote and cand.get("direction", "buy") == "buy":
        speed = extract_quote_metrics(quote).get("speed_pct_3min", 0)
        if speed > 5.0:
            result["checks"]["speed_filter"] = ConditionResult(False, f"3分钟涨速 {speed:.1f}% > 5%")
            result["pass"] = False; result["first_failure"] = f"涨速过滤({speed:.1f}%)"
            return result

    # 竞价金额过滤
    if quote and cand.get("direction", "buy") == "buy":
        auction_amt = extract_quote_metrics(quote).get("auction_amount", 0)
        if auction_amt > 0 and auction_amt < 5_000_000:
            result["checks"]["auction_amount"] = ConditionResult(False, f"竞价金额 {auction_amt/10000:.0f}万 < 500万")
            result["pass"] = False; result["first_failure"] = f"竞价金额不足({auction_amt/10000:.0f}万)"
            return result

    au = evaluate_auction_condition(cand, quote, auction_pct=auction_pct)
    result["checks"]["auction"] = au
    if not au["pass"]:
        result["pass"] = False; result["first_failure"] = au["reason"]

    intra = evaluate_intraday_condition(cand, quote, now_time=now_time, current_pct=current_pct)
    result["checks"]["intraday"] = intra
    if result["pass"] and not intra["pass"]:
        result["pass"] = False; result["first_failure"] = intra["reason"]

    if sentinel_quotes:
        dep = evaluate_dependency(cand, sentinel_quotes)
        result["checks"]["dependency"] = dep
        if result["pass"] and not dep["pass"]:
            result["pass"] = False; result["first_failure"] = dep["reason"]

    if cand.get("direction", "buy") == "buy":
        chip_eval = evaluate_chip_condition(quote or cand, cand)
        result["checks"]["chip_safety"] = chip_eval
        if result["pass"] and not chip_eval["pass"]:
            result["pass"] = False; result["first_failure"] = chip_eval["reason"]

    if cand.get("direction", "buy") == "buy":
        fund_eval = evaluate_fund_flow_condition(quote or cand, cand)
        result["checks"]["fund_flow_safety"] = fund_eval
        if result["pass"] and not fund_eval["pass"]:
            result["pass"] = False; result["first_failure"] = fund_eval["reason"]

    if cand.get("direction") == "sell":
        pos = cand.get("position") or cand.get("pos") or cand
        wm = cand.get("watermark") or (pos.get("watermark") if isinstance(pos, dict) else None)
        result["checks"]["trailing_profit"] = evaluate_trailing_profit_condition(pos, quote, watermark=wm)
        result["checks"]["scale_out"] = evaluate_scale_out_condition(pos, quote, watermark=wm)

    return result
