#!/usr/bin/env python3
"""A股市场板块规则库与涨跌幅/连板身位计算工具.

移植至 Astock: urllib MCP 调用替换为 MCPClient.
"""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Optional

from mcp_client import get_mcp_client


def clean_stock_code(symbol: str) -> str:
    if not symbol:
        return ""
    digits = re.sub(r"\D", "", str(symbol).strip())
    if len(digits) >= 6:
        return digits[-6:]
    return digits


def normalize_stock_symbol(symbol: str) -> str:
    code = clean_stock_code(symbol)
    if not code:
        return str(symbol).strip().upper()
    mkt = get_stock_market_type(symbol)
    if mkt == "STAR":
        return f"{code}.SH"
    elif mkt == "CHINEXT":
        return f"{code}.SZ"
    elif mkt == "BSE":
        return f"{code}.BJ"
    elif mkt == "MAIN":
        if code.startswith(("60", "68")):
            return f"{code}.SH"
        return f"{code}.SZ"
    return f"{code}.SH"


def get_stock_market_type(symbol: str) -> str:
    """沪深主板 MAIN / 创业板 CHINEXT / 科创板 STAR / 北交所 BSE."""
    if not symbol:
        return "MAIN"
    raw = str(symbol).strip().upper()
    if raw.endswith(".BJ") or raw.startswith("BJ"):
        return "BSE"
    code = clean_stock_code(raw)
    if not code:
        return "MAIN"
    if code.startswith(("300", "301")):
        return "CHINEXT"
    elif code.startswith(("688", "689")):
        return "STAR"
    elif code.startswith("920") or code.startswith(("82", "83", "87", "88", "43", "40")):
        return "BSE"
    elif code.startswith(("600", "601", "603", "605", "000", "001", "002", "003")):
        return "MAIN"
    if raw.endswith(".SH"):
        return "STAR" if code.startswith(("688", "689")) else "MAIN"
    elif raw.endswith(".SZ"):
        return "CHINEXT" if code.startswith(("300", "301")) else "MAIN"
    return "MAIN"


def get_board_limit_ratio(symbol: str, name: str = "") -> float:
    """板块涨跌幅限制比例: 主板10%/ST5%, 双创20%, 北交所30%."""
    mkt = get_stock_market_type(symbol)
    name_upper = (name or "").strip().upper()
    is_st = "ST" in name_upper
    if mkt == "MAIN":
        return 0.05 if is_st else 0.10
    elif mkt in ("CHINEXT", "STAR"):
        return 0.20
    elif mkt == "BSE":
        return 0.30
    return 0.10


def calc_limit_up_price(pre_close: float, ratio: float) -> float:
    """交易所四舍五入规则精确计算涨停价."""
    if pre_close <= 0:
        return 0.0
    p = Decimal(str(round(pre_close, 4)))
    r = Decimal(str(ratio))
    target = p * (Decimal("1") + r)
    return float(target.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def is_limit_up_price(close: float, pre_close: float, symbol: str, name: str = "", tolerance: float = 0.01) -> bool:
    if close <= 0 or pre_close <= 0:
        return False
    ratio = get_board_limit_ratio(symbol, name)
    limit_price = calc_limit_up_price(pre_close, ratio)
    return close >= (limit_price - tolerance)


def get_board_min_limit_pct(symbol: str, name: str = "") -> float:
    """涨停判定经验最小涨幅阈值(%): 主板9.5%, 主板ST4.8%, 双创19.2%, 北交所28.5%."""
    ratio = get_board_limit_ratio(symbol, name)
    if ratio <= 0.05:
        return 4.8
    elif ratio <= 0.10:
        return 9.5
    elif ratio <= 0.20:
        return 19.2
    else:
        return 28.5


def get_real_board_count(
    symbol: str, name: str = "", klines: Optional[list[dict[str, Any]]] = None,
    skip_unclosed_today: bool = True, force_skip_last: bool = False,
) -> int:
    """核验连板身位，跳过今日未收盘K线."""
    bars: list[dict[str, Any]] = []
    if klines is not None:
        bars = list(klines)
    else:
        try:
            client = get_mcp_client()
            res = client.fetch_klines(symbol, period="D", count=20)
            bars = res if isinstance(res, list) else []
        except Exception:
            bars = []

    if not bars:
        return 0

    today_dash = dt.date.today().strftime("%Y-%m-%d")
    today_nodash = dt.date.today().strftime("%Y%m%d")

    valid_bars = list(bars)
    if force_skip_last and len(valid_bars) > 0:
        valid_bars = valid_bars[:-1]
    elif skip_unclosed_today and len(valid_bars) > 0:
        last_bar = valid_bars[-1]
        last_t = str(last_bar.get("time", last_bar.get("date", "")))
        is_today = (today_dash in last_t) or (today_nodash in last_t)
        is_unclosed = (last_bar.get("unclosed") is True) or (last_bar.get("is_closed") is False)
        if is_today or is_unclosed:
            valid_bars = valid_bars[:-1]

    if not valid_bars:
        return 0

    streak = 0
    for i in range(len(valid_bars) - 1, -1, -1):
        k = valid_bars[i]
        close = float(k.get("close", 0) or 0)
        pre_close = float(k.get("pre_close", k.get("preclose", 0)) or 0)
        if pre_close <= 0 and i > 0:
            pre_close = float(valid_bars[i - 1].get("close", 0) or 0)
        is_zt = False
        if close > 0 and pre_close > 0:
            is_zt = is_limit_up_price(close, pre_close, symbol, name)
        else:
            chg = float(k.get("change_pct", k.get("pct_chg", k.get("涨跌幅", 0))) or 0)
            min_thresh = get_board_min_limit_pct(symbol, name)
            is_zt = (chg >= min_thresh)
        if is_zt:
            streak += 1
        else:
            break
    return streak
