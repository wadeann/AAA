#!/usr/bin/env python3
"""炸板最高价防守与防假企稳铁律核心防护组件 (AGENTS.md §2).

移植至 Astock: urllib MCP 调用替换为 MCPClient, ~/.hermes 路径替换为 STATE_DIR.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Callable, Optional

from config import STATE_DIR
from mcp_client import get_mcp_client


class BrokenGuardResult(dict):
    """质检结果容器：支持元组解包 (ok, reason)、布尔判断、字典访问."""

    def __init__(self, passed: bool, reason: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self["pass"] = bool(passed)
        self["ok"] = bool(passed)
        self["reason"] = str(reason)

    def __iter__(self):
        return iter((self["pass"], self["reason"]))

    def __bool__(self) -> bool:
        return bool(self["pass"])

    def __getitem__(self, item: Any) -> Any:
        if item == 0:
            return self["pass"]
        if item == 1:
            return self["reason"]
        return super().__getitem__(item)


_BLACKLIST_DIR = STATE_DIR / "broken_blacklist"


def _ensure_blacklist_dir() -> None:
    _BLACKLIST_DIR.mkdir(parents=True, exist_ok=True)


def get_blacklist_file(date_str: Optional[str] = None) -> Path:
    date_str = date_str or dt.date.today().isoformat()
    base_dir = Path(os.getenv("ASTOCK_BLACKLIST_DIR", str(_BLACKLIST_DIR)))
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir / f"broken_blacklist_{date_str}.json"


def load_broken_blacklist(date_str: Optional[str] = None) -> dict[str, dict[str, Any]]:
    path = get_blacklist_file(date_str)
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_broken_blacklist(blacklist: dict[str, dict[str, Any]], date_str: Optional[str] = None) -> None:
    path = get_blacklist_file(date_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(blacklist, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def add_to_broken_blacklist(
    symbol: str, reason: str, metadata: Optional[dict[str, Any]] = None,
    date_str: Optional[str] = None,
) -> bool:
    if not symbol:
        return False
    norm_sym = symbol.strip().upper()
    bl = load_broken_blacklist(date_str)
    rec: dict[str, Any] = {
        "symbol": norm_sym, "reason": reason,
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "permanently_frozen": bool(metadata.get("permanently_frozen", False)) if metadata else False,
    }
    if metadata:
        rec.update(metadata)
    bl[norm_sym] = rec
    save_broken_blacklist(bl, date_str)
    return True


def remove_from_broken_blacklist(symbol: str, date_str: Optional[str] = None) -> bool:
    if not symbol:
        return False
    norm_sym = symbol.strip().upper()
    bl = load_broken_blacklist(date_str)
    if norm_sym in bl:
        if bl[norm_sym].get("permanently_frozen", False):
            return False
        del bl[norm_sym]
        save_broken_blacklist(bl, date_str)
        return True
    return False


def is_broken_blacklisted(symbol: str, date_str: Optional[str] = None) -> bool:
    if not symbol:
        return False
    norm_sym = symbol.strip().upper()
    bl = load_broken_blacklist(date_str)
    return norm_sym in bl


def clear_broken_blacklist(date_str: Optional[str] = None) -> None:
    path = get_blacklist_file(date_str)
    if path.exists():
        try:
            path.unlink()
        except Exception:
            pass


def compute_limit_pct(symbol: str, pre_close: float = 0.0) -> float:
    """获取标的板块涨跌幅限制比例(%)."""
    norm = symbol.strip().upper()
    if "ST" in norm:
        return 5.0
    if norm.endswith(".BJ") or norm.startswith(("8", "4", "92")):
        return 30.0
    if norm.startswith(("30", "68")) or (norm.endswith(".SZ") and norm.startswith("30")) or (norm.endswith(".SH") and norm.startswith("688")):
        return 20.0
    return 10.0


def compute_limit_up_price(symbol: str, pre_close: float) -> float:
    if pre_close <= 0:
        return 0.0
    pct = compute_limit_pct(symbol, pre_close)
    return round(pre_close * (1.0 + pct / 100.0) + 1e-6, 2)


def cancel_pending_orders_for_broken_symbol(
    symbol: str,
    mcp_caller: Optional[Callable[[int, str, dict[str, Any]], Any]] = None,
    max_retries: int = 3,
) -> int:
    """一旦标的炸板破位，毫秒级取消 Exec MCP 上所有在途活动买单."""
    if not symbol:
        return 0
    norm_sym = symbol.strip().upper()
    client = get_mcp_client()
    try:
        orders = client.get_orders()
        active_statuses = ("PENDING", "SUBMITTED", "PARTIALLY_FILLED", "PARTIAL_FILLED")
        cancelled_count = 0
        raw_code = norm_sym.split(".")[0]
        for o in orders:
            if not isinstance(o, dict):
                continue
            status = str(o.get("status", "")).upper()
            if status not in active_statuses:
                continue
            direction = str(o.get("direction", o.get("side", ""))).upper()
            o_sym = str(o.get("symbol", "")).upper()
            if direction == "BUY" and (o_sym == norm_sym or o_sym.split(".")[0] == raw_code):
                oid = o.get("order_id") or o.get("id")
                if oid:
                    import time
                    for attempt in range(1, max_retries + 1):
                        try:
                            res = client.call("cancel_order", {"order_id": oid}, port=9003)
                        except Exception:
                            res = {}
                        if res and (res.get("success") or res.get("status") in ("cancelled", "canceled", "ok") or not res.get("error")):
                            cancelled_count += 1
                            break
                        if attempt < max_retries:
                            time.sleep(0.05 * (2 ** (attempt - 1)))
        return cancelled_count
    except Exception:
        return 0


def check_broken_and_fake_healing(
    symbol: str, cur_price: float, high_price: float, low_price: float,
    pre_close: float, was_limit_up_today: Optional[bool] = None,
    date_str: Optional[str] = None,
) -> BrokenGuardResult:
    """AGENTS.md §2 炸板最高价防守与防假企稳铁律质检."""
    if cur_price <= 0 or pre_close <= 0:
        return BrokenGuardResult(True, "行情数据不全，跳过破位核验")

    norm_sym = symbol.strip().upper()
    high_price = max(high_price, cur_price)
    low_price = min(low_price, cur_price) if low_price > 0 else cur_price

    cur_pct = round((cur_price - pre_close) / pre_close * 100.0, 4)
    high_pct = round((high_price - pre_close) / pre_close * 100.0, 4)
    low_pct = round((low_price - pre_close) / pre_close * 100.0, 4)
    drawdown = round(high_pct - cur_pct, 4)

    limit_pct = compute_limit_pct(norm_sym, pre_close)
    limit_p = compute_limit_up_price(norm_sym, pre_close)

    touched_limit = False
    if was_limit_up_today is True:
        touched_limit = True
    elif high_pct >= (limit_pct - 0.5):
        touched_limit = True
    elif limit_p > 0 and high_price >= (limit_p - 0.01):
        touched_limit = True

    bl = load_broken_blacklist(date_str)
    is_in_bl = norm_sym in bl
    is_permanently_frozen = bl.get(norm_sym, {}).get("permanently_frozen", False)

    # 水下恶劣破位检测
    if (touched_limit or is_in_bl) and (cur_pct < 0.0 or low_pct < 0.0):
        add_to_broken_blacklist(
            norm_sym,
            reason=f"曾触板且水下恶劣出货破位 (cur={cur_pct:.2f}%, low={low_pct:.2f}%)",
            metadata={"cur_pct": cur_pct, "high_pct": high_pct, "low_pct": low_pct, "permanently_frozen": True},
            date_str=date_str,
        )
        cancel_pending_orders_for_broken_symbol(norm_sym)
        return BrokenGuardResult(False, f"曾触板且水下恶劣出货破位 (low={low_pct:.2f}%, cur={cur_pct:.2f}%)，永久冻结严禁买入",
                                 cur_pct=cur_pct, high_pct=high_pct, low_pct=low_pct, drawdown=drawdown, permanently_frozen=True)

    if is_permanently_frozen:
        return BrokenGuardResult(False, "标的日内曾跌入绿盘水下，永久冻结严禁自愈买入",
                                 cur_pct=cur_pct, high_pct=high_pct, low_pct=low_pct, drawdown=drawdown, permanently_frozen=True)

    if touched_limit or is_in_bl:
        if drawdown > 4.0:
            add_to_broken_blacklist(norm_sym, reason=f"日内距最高点回撤 {drawdown:.2f}% 超过 4.0% 破位",
                                    metadata={"cur_pct": cur_pct, "high_pct": high_pct, "low_pct": low_pct, "drawdown": drawdown},
                                    date_str=date_str)
            cancel_pending_orders_for_broken_symbol(norm_sym)
            return BrokenGuardResult(False, f"曾触及涨停({high_pct:.2f}%)日内回撤 {drawdown:.2f}% 超过4.0%",
                                     cur_pct=cur_pct, high_pct=high_pct, low_pct=low_pct, drawdown=drawdown)

        if cur_pct < 5.5:
            add_to_broken_blacklist(norm_sym, reason=f"当前涨幅 {cur_pct:.2f}% 未达自愈门槛 (+5.5%)",
                                    metadata={"cur_pct": cur_pct, "high_pct": high_pct, "low_pct": low_pct, "drawdown": drawdown},
                                    date_str=date_str)
            cancel_pending_orders_for_broken_symbol(norm_sym)
            return BrokenGuardResult(False, f"涨幅 {cur_pct:.2f}% 未达到自愈门槛 (+5.5%)",
                                     cur_pct=cur_pct, high_pct=high_pct, low_pct=low_pct, drawdown=drawdown)

        if is_in_bl:
            remove_from_broken_blacklist(norm_sym, date_str=date_str)
        return BrokenGuardResult(True, f"自愈解冻达标: cur={cur_pct:.2f}%, drawdown={drawdown:.2f}%, low={low_pct:.2f}%",
                                 cur_pct=cur_pct, high_pct=high_pct, low_pct=low_pct, drawdown=drawdown)

    return BrokenGuardResult(True, "正常标的放行", cur_pct=cur_pct, high_pct=high_pct, low_pct=low_pct, drawdown=drawdown)
