#!/usr/bin/env python3
"""筹码分布穿透与持仓成本防御核心组件.

移植至 Astock: urllib MCP 调用替换为 MCPClient.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Optional

from mcp_client import get_mcp_client

logger = logging.getLogger("astock.utils_chip")


class ChipEvaluationResult(tuple):
    """筹码安全评估结果容器: 支持元组解包、属性访问、字典接口."""

    def __new__(cls, is_safe: bool, reason: str, details: Optional[dict[str, Any]] = None):
        return super().__new__(cls, (bool(is_safe), str(reason)))

    def __init__(self, is_safe: bool, reason: str, details: Optional[dict[str, Any]] = None):
        self.is_safe = bool(is_safe)
        self.reason = str(reason)
        self.details: dict[str, Any] = details or {}

    @property
    def chip_profit_rate(self) -> float:
        return float(self.details.get("chipProfitRate", 100.0 if self.is_safe else 0.0))

    @property
    def chip_avg_cost(self) -> float:
        return float(self.details.get("chipAvgCost", 0.0))

    @property
    def chip_concentration(self) -> float:
        return float(self.details.get("chipConcentration70", 10.0))

    @property
    def bias(self) -> float:
        return float(self.details.get("bias", 0.0))

    @property
    def has_divergence(self) -> bool:
        return bool(self.details.get("has_divergence", False))

    @property
    def has_distribution_risk(self) -> bool:
        return bool(self.details.get("has_distribution_risk", False))

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


def get_chip_distribution(symbol: str, timeout: int = 5) -> dict[str, Any]:
    """调用 MCP get_chip_distribution."""
    code = clean_symbol(symbol)
    if not code:
        return {}
    try:
        client = get_mcp_client()
        return client.get_chip_distribution(code)
    except Exception as e:
        logger.warning("获取标的 %s(%s) 筹码分布异常: %s", symbol, code, e)
        return {}


@lru_cache(maxsize=1024)
def get_chip_distribution_cached(symbol: str, timeout: int = 5) -> dict[str, Any]:
    return get_chip_distribution(symbol=symbol, timeout=timeout)


def clear_chip_cache() -> None:
    get_chip_distribution_cached.cache_clear()


def parse_chip_raw(raw_data: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not raw_data or not isinstance(raw_data, dict):
        return {}
    d = raw_data.get("data", raw_data) if isinstance(raw_data.get("data"), dict) else raw_data

    profit_rate: Optional[float] = None
    for k in ("chipProfitRate", "chip_profit_rate", "profit_rate", "获利盘比例", "获利盘"):
        if k in d and d[k] is not None:
            try:
                val = float(d[k])
                if 0.0 < val <= 1.0:
                    val *= 100.0
                profit_rate = round(val, 2)
                break
            except (ValueError, TypeError):
                pass

    avg_cost = 0.0
    for k in ("chipAvgCost", "chip_avg_cost", "avg_cost", "平均成本", "主力成本"):
        if k in d and d[k] is not None:
            try:
                avg_cost = round(float(d[k]), 2)
                break
            except (ValueError, TypeError):
                pass

    conc70 = 0.0
    for k in ("chipConcentration70", "chip_concentration_70", "chip_concentration", "70%集中度", "70集中度"):
        if k in d and d[k] is not None:
            try:
                val = float(d[k])
                if 0.0 < val <= 1.0:
                    val *= 100.0
                conc70 = round(val, 2)
                break
            except (ValueError, TypeError):
                pass

    conc90 = 0.0
    for k in ("chipConcentration90", "chip_concentration_90", "90%集中度", "90集中度"):
        if k in d and d[k] is not None:
            try:
                val = float(d[k])
                if 0.0 < val <= 1.0:
                    val *= 100.0
                conc90 = round(val, 2)
                break
            except (ValueError, TypeError):
                pass

    is_sub_new = bool(d.get("is_sub_new", False))
    days_since_ipo = d.get("days_since_ipo", d.get("ipo_days"))
    if days_since_ipo is not None:
        try:
            if float(days_since_ipo) < 30:
                is_sub_new = True
        except (ValueError, TypeError):
            pass

    return {"chipProfitRate": profit_rate, "chipAvgCost": avg_cost,
            "chipConcentration70": conc70, "chipConcentration90": conc90, "is_sub_new": is_sub_new}


def evaluate_chip_safety(
    symbol: str, current_price: float = 0.0, streak: int = 1,
    is_sub_new: bool = False, chip_data: Optional[dict[str, Any]] = None,
    timeout: int = 5,
) -> ChipEvaluationResult:
    """评估标的筹码分布安全性与高位派发风险."""
    if chip_data is None:
        raw = get_chip_distribution_cached(symbol, timeout=timeout)
    else:
        raw = chip_data

    parsed = parse_chip_raw(raw)

    if not parsed or parsed.get("chipProfitRate") is None:
        return ChipEvaluationResult(True, "筹码数据缺失或超时，容灾降级放行",
                                    details={"chipProfitRate": 100.0, "chipAvgCost": current_price or 0.0,
                                             "chipConcentration70": 10.0, "chipConcentration90": 15.0,
                                             "degraded": True, "has_divergence": False, "has_distribution_risk": False})

    profit_rate = parsed["chipProfitRate"]
    avg_cost = parsed["chipAvgCost"]
    conc70 = parsed["chipConcentration70"]
    sub_new = is_sub_new or parsed.get("is_sub_new", False)

    bias = 0.0
    if current_price > 0 and avg_cost > 0:
        bias = round((current_price - avg_cost) / avg_cost * 100.0, 2)

    has_divergence = conc70 > 25.0
    has_distribution_risk = (bias > 45.0) and has_divergence

    details = {"chipProfitRate": profit_rate, "chipAvgCost": avg_cost, "chipConcentration70": conc70,
               "bias": bias, "is_sub_new": sub_new, "has_divergence": has_divergence,
               "has_distribution_risk": has_distribution_risk, "degraded": False}

    if profit_rate < 15.0 and not sub_new:
        return ChipEvaluationResult(False, "获利盘比例不足15%，上方套牢抛压沉重一票否决", details=details)

    if has_distribution_risk:
        return ChipEvaluationResult(True, f"高位派发风险: 乖离率{bias:.1f}%>45%且筹码发散(70%集中度={conc70:.1f}%)", details=details)

    if has_divergence:
        return ChipEvaluationResult(True, f"筹码集中度发散: 70%集中度{conc70:.1f}%>25.0%", details=details)

    return ChipEvaluationResult(True, f"筹码结构健康: 获利盘{profit_rate:.1f}%, 成本{avg_cost:.2f}元",
                                details=details)
