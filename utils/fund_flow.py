#!/usr/bin/env python3
"""主力资金真实流向多源交叉核验核心组件.

移植至 Astock: urllib MCP 调用替换为 MCPClient.
"""
from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any, Optional

from mcp_client import get_mcp_client

logger = logging.getLogger("astock.utils_fund_flow")


class FundFlowEvaluationResult(tuple):
    """资金流向安全评估结果容器: 支持布尔判断、元组解包、属性访问、字典接口."""

    def __new__(cls, is_safe: bool, reason: str, details: Optional[dict[str, Any]] = None):
        return super().__new__(cls, (bool(is_safe), str(reason)))

    def __init__(self, is_safe: bool, reason: str, details: Optional[dict[str, Any]] = None):
        self.is_safe = bool(is_safe)
        self.reason = str(reason)
        self.details: dict[str, Any] = details or {}

    def __bool__(self) -> bool:
        return self.is_safe

    @property
    def main_net_flow(self) -> float:
        return float(self.details.get("MainNetFlow", 0.0))

    @property
    def small_net_flow(self) -> float:
        return float(self.details.get("SmallNetFlow", 0.0))

    @property
    def has_retail_divergence(self) -> bool:
        return bool(self.details.get("has_retail_divergence", False))

    @property
    def has_dumping_risk(self) -> bool:
        return bool(self.details.get("has_dumping_risk", False))

    @property
    def has_institution_exit(self) -> bool:
        return bool(self.details.get("has_institution_exit", False))

    @property
    def inst_net_sell(self) -> float:
        return float(self.details.get("inst_net_sell", 0.0))

    @property
    def degraded(self) -> bool:
        return bool(self.details.get("degraded", False))

    def get(self, key: str, default: Any = None) -> Any:
        if key in self.details:
            return self.details[key]
        if key == "is_safe":
            return self.is_safe
        if key == "reason":
            return self.reason
        return default


def clean_symbol(symbol: str) -> str:
    if not symbol:
        return ""
    sym = str(symbol).strip().upper()
    if "." in sym:
        sym = sym.split(".")[0]
    for prefix in ("SH", "SZ", "BJ"):
        if sym.startswith(prefix):
            sym = sym[len(prefix):]
    return sym


def get_fund_flow(symbol: str, timeout: int = 5) -> dict[str, Any]:
    """调用 MCP get_fund_flow."""
    code = clean_symbol(symbol)
    if not code:
        return {}
    try:
        client = get_mcp_client()
        return client.get_fund_flow(code)
    except Exception as e:
        logger.warning("获取标的 %s(%s) 资金流向异常: %s", symbol, code, e)
        return {}


_FUND_FLOW_TTL_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
DEFAULT_CACHE_TTL = 60.0


def get_fund_flow_with_ttl(symbol: str, timeout: int = 5, ttl: float = DEFAULT_CACHE_TTL) -> dict[str, Any]:
    code = clean_symbol(symbol)
    if not code:
        return {}
    now = time.time()
    if code in _FUND_FLOW_TTL_CACHE:
        ts, data = _FUND_FLOW_TTL_CACHE[code]
        if now - ts < ttl and data:
            return data
    fresh_data = get_fund_flow(symbol=code, timeout=timeout)
    if fresh_data:
        _FUND_FLOW_TTL_CACHE[code] = (now, fresh_data)
    return fresh_data


@lru_cache(maxsize=1024)
def get_fund_flow_cached(symbol: str, timeout: int = 5) -> dict[str, Any]:
    return get_fund_flow(symbol=symbol, timeout=timeout)


def clear_fund_flow_cache() -> None:
    get_fund_flow_cached.cache_clear()
    _FUND_FLOW_TTL_CACHE.clear()


def parse_fund_flow_raw(raw_data: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not raw_data or not isinstance(raw_data, dict):
        return {}
    d = raw_data.get("data", raw_data) if isinstance(raw_data.get("data"), dict) else raw_data

    def _extract(keys: tuple[str, ...], default: Optional[float] = None) -> Optional[float]:
        for k in keys:
            if k in d and d[k] is not None:
                try:
                    return float(d[k])
                except (ValueError, TypeError):
                    pass
        return default

    jumbo = _extract(("JumboNetFlow", "jumbo_net_flow", "超大单净额", "超大单净流入", "超大单净买入"))
    block = _extract(("BlockNetFlow", "block_net_flow", "大单净额", "大单净流入", "大单净买入"))
    mid = _extract(("MidNetFlow", "mid_net_flow", "中单净额", "中单净流入", "中单净买入"), 0.0) or 0.0
    small = _extract(("SmallNetFlow", "small_net_flow", "小单净额", "小单净流入", "散户净买入"))

    main_flow = _extract(("MainNetFlow", "main_net_flow", "主力净额", "主力净流入", "主力资金净额"))
    if main_flow is None:
        if jumbo is not None and block is not None:
            main_flow = jumbo + block
        elif jumbo is not None:
            main_flow = jumbo
        elif block is not None:
            main_flow = block

    main_5d = _extract(("MainNetFlow5D", "main_net_flow_5d", "5日主力净额", "5日主力净流入"), 0.0) or 0.0
    main_10d = _extract(("MainNetFlow10D", "main_net_flow_10d", "10日主力净额", "10日主力净流入"), 0.0) or 0.0

    lhb_infos = d.get("LhbInfos") or d.get("lhb_infos") or d.get("龙虎榜") or []
    lhb_details = d.get("LhbTradingDetails") or d.get("lhb_trading_details") or []

    inst_net_sell = 0.0
    explicit_inst_sell = _extract(("inst_net_sell", "institution_net_sell", "机构净卖出", "机构净卖出额"))
    if explicit_inst_sell is not None:
        inst_net_sell = max(0.0, explicit_inst_sell)
    else:
        explicit_inst_buy = _extract(("inst_net_buy", "institution_net_buy", "机构净买入", "机构席位净买入"))
        if explicit_inst_buy is not None and explicit_inst_buy < 0:
            inst_net_sell = abs(explicit_inst_buy)

    all_lhb: list[dict[str, Any]] = []
    if isinstance(lhb_infos, list):
        all_lhb.extend(x for x in lhb_infos if isinstance(x, dict))
    elif isinstance(lhb_infos, dict):
        all_lhb.append(lhb_infos)
    if isinstance(lhb_details, list):
        all_lhb.extend(x for x in lhb_details if isinstance(x, dict))
    elif isinstance(lhb_details, dict):
        all_lhb.append(lhb_details)

    if all_lhb:
        calc_inst_buy = 0.0
        found = False
        for item in all_lhb:
            seat_name = str(item.get("seat_name", item.get("name", item.get("营业部名称", ""))))
            seat_type = str(item.get("type", item.get("seat_type", "")))
            if "机构" in seat_name or "机构专用" in seat_name or "institution" in seat_type.lower():
                found = True
                net_val = _extract_float(item, ("net_amount", "net_buy", "买卖净额", "净买入"))
                if net_val is not None:
                    calc_inst_buy += net_val
                else:
                    b = float(item.get("buy_amount", item.get("买入金额", 0.0)) or 0.0)
                    s = float(item.get("sell_amount", item.get("卖出金额", 0.0)) or 0.0)
                    calc_inst_buy += (b - s)
        if found and calc_inst_buy < 0:
            inst_net_sell = max(inst_net_sell, abs(calc_inst_buy))

    turnover_amt = _extract(("turnover_amount", "amount", "成交额", "成交金额"), 0.0) or 0.0
    if 0.0 < turnover_amt < 1000.0:
        turnover_amt *= 1e8

    return {"JumboNetFlow": jumbo if jumbo is not None else 0.0, "BlockNetFlow": block if block is not None else 0.0,
            "MidNetFlow": mid, "SmallNetFlow": small if small is not None else 0.0,
            "MainNetFlow": main_flow, "MainNetFlow5D": main_5d, "MainNetFlow10D": main_10d,
            "inst_net_sell": inst_net_sell, "turnover_amount": turnover_amt}


def _extract_float(d: dict[str, Any], keys: tuple[str, ...]) -> Optional[float]:
    for k in keys:
        if k in d and d[k] is not None:
            try:
                return float(d[k])
            except (ValueError, TypeError):
                pass
    return None


def evaluate_fund_flow_safety(
    symbol: str, current_price: float = 0.0, turnover_amount: float = 0.0,
    fund_data: Optional[dict[str, Any]] = None, timeout: int = 5,
) -> FundFlowEvaluationResult:
    """主力资金真实流向与对倒诱多综合安全评估."""
    if fund_data is None:
        raw = get_fund_flow_cached(symbol, timeout=timeout)
    else:
        raw = fund_data

    parsed = parse_fund_flow_raw(raw)

    amt = float(turnover_amount or 0.0)
    if 0.0 < amt < 1000.0:
        amt *= 1e8
    if amt <= 0.0:
        amt = float(parsed.get("turnover_amount", 0.0) or 0.0)

    if not parsed or parsed.get("MainNetFlow") is None:
        return FundFlowEvaluationResult(True, "资金流向数据缺失或超时，容灾降级放行",
                                        details={"MainNetFlow": 0.0, "SmallNetFlow": 0.0, "turnover_amount": amt,
                                                 "main_flow_ratio": 0.0, "has_retail_divergence": False,
                                                 "has_dumping_risk": False, "has_institution_exit": False,
                                                 "inst_net_sell": 0.0, "degraded": True})

    main_net_flow = float(parsed["MainNetFlow"])
    small_net_flow = float(parsed["SmallNetFlow"])
    inst_net_sell = float(parsed["inst_net_sell"])

    main_flow_ratio = (main_net_flow / amt) if amt > 0 else 0.0

    has_retail_divergence = (main_net_flow < -30_000_000.0) and (small_net_flow > 20_000_000.0)
    has_dumping_risk = (amt > 10_000_000.0) and (main_flow_ratio < -0.10)
    has_institution_exit = inst_net_sell > 30_000_000.0

    details = {"MainNetFlow": main_net_flow, "SmallNetFlow": small_net_flow,
               "turnover_amount": amt, "main_flow_ratio": round(main_flow_ratio, 4),
               "has_retail_divergence": has_retail_divergence, "has_dumping_risk": has_dumping_risk,
               "has_institution_exit": has_institution_exit, "inst_net_sell": inst_net_sell, "degraded": False}

    if has_retail_divergence:
        return FundFlowEvaluationResult(False, "主力出货散户接盘背离一票否决", details=details)
    if has_dumping_risk:
        return FundFlowEvaluationResult(False, "主力对倒出货/资金净流出占比超标一票否决", details=details)
    if has_institution_exit:
        return FundFlowEvaluationResult(True, f"龙虎榜机构出逃: 机构净卖出{inst_net_sell/1e4:.0f}万", details=details)

    return FundFlowEvaluationResult(True, f"主力资金健康: 主力净额{main_net_flow/1e4:.0f}万", details=details)
