#!/usr/bin/env python3
"""Active portfolio cleaner.

Evaluates open positions for early-exit candidates.
Checks:
  - Trailing stop: -6% from peak (hard exit)
  - Time exit: held > 20 trading days
  - Generates sell candidates and writes to JSONL ledger.

Usage:
  python3 -m execution.active_portfolio_cleaner
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data import get_data_manager
from mcp_client import get_mcp_client

CST = dt.timezone(dt.timedelta(hours=8))


def compute_high_watermark(symbol: str, cost_price: float) -> dict[str, Any] | None:
    """Fetch daily klines and compute the peak price since entry.

    Returns dict with high_watermark_price, high_watermark_pct or None if unavailable.
    """
    try:
        client = get_mcp_client()
        klines = client.fetch_klines(symbol, period="D", count=60)
        if not klines:
            return None
        highs = [float(k.get("high", 0) or 0) for k in klines if float(k.get("high", 0) or 0) > 0]
        if not highs:
            return None
        peak = max(highs)
        pct = (peak - cost_price) / cost_price * 100.0 if cost_price > 0 else 0.0
        return {"high_watermark_price": peak, "high_watermark_pct": round(pct, 2)}
    except Exception:
        return None


def estimate_hold_days(symbol: str) -> int:
    """Estimate number of trading days since first position record."""
    try:
        dm = get_data_manager()
        today = dt.date.today().isoformat()
        records = dm.read_jsonl(date=today)
        for rec in reversed(records):
            if rec.get("symbol") == symbol and rec.get("event") in ("executed", "submitted"):
                ts = rec.get("timestamp", "")
                if ts:
                    try:
                        d = dt.datetime.fromisoformat(ts)
                        return (dt.datetime.now(CST) - d).days
                    except Exception:
                        pass
        return 999
    except Exception:
        return 999


def evaluate_position(
    pos: dict[str, Any],
) -> dict[str, Any] | None:
    """Evaluate a single position and return a sell candidate dict or None."""
    symbol = str(pos.get("symbol", ""))
    if not symbol:
        return None

    qty_raw = pos.get("quantity", pos.get("available_quantity", 0))
    qty = int(float(qty_raw if qty_raw is not None else 0))
    if qty < 100:
        return None

    cost = float(pos.get("cost_price", 0) or 0)
    cur_price = float(pos.get("current_price", 0) or 0)
    if cost <= 0 or cur_price <= 0:
        return None

    pnl_pct = (cur_price - cost) / cost * 100.0

    # Hard trailing stop: -6% from peak
    wm = compute_high_watermark(symbol, cost)
    if wm and wm["high_watermark_price"] > cost:
        peak_pct = wm["high_watermark_pct"]
        drawdown = peak_pct - pnl_pct
        if drawdown >= 6.0:
            return {
                "symbol": symbol,
                "direction": "sell",
                "price": cur_price,
                "quantity": qty,
                "confidence": 0.80,
                "reason": f"trailing_stop: peak_gain={peak_pct:.1f}%, drawdown={drawdown:.1f}%",
                "thesis": f"[portfolio_cleaner] 移动止损: 高点回撤{drawdown:.1f}%(-6%触发)",
                "catalyst_type": "portfolio_cleaning",
                "trigger_tier": "trailing_stop",
            }

    # Time exit: held > 20 trading days (~4 weeks)
    hold_days = estimate_hold_days(symbol)
    if hold_days > 20:
        reason = f"time_exit: held {hold_days}d, pnl={pnl_pct:.1f}%"
        return {
            "symbol": symbol,
            "direction": "sell",
            "price": cur_price,
            "quantity": qty,
            "confidence": 0.70,
            "reason": reason,
            "thesis": f"[portfolio_cleaner] 持仓超过{hold_days}个交易日触发时间退出",
            "catalyst_type": "portfolio_cleaning",
            "trigger_tier": "time_exit",
        }

    return None


def main() -> None:
    client = get_mcp_client()
    dm = get_data_manager()
    today = dt.date.today().isoformat()

    try:
        positions = client.get_positions()
    except Exception as e:
        print(f"[PORTFOLIO] 无法获取持仓: {e}", flush=True)
        return

    candidates: list[dict[str, Any]] = []
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        result = evaluate_position(pos)
        if result is not None:
            candidates.append(result)
            print(
                f"  [CLEAN] {result['symbol']} {result['trigger_tier']}: "
                f"{result['reason']}",
                flush=True,
            )

    if not candidates:
        print("[PORTFOLIO] 无需要清理的持仓", flush=True)
        return

    for cand in candidates:
        record = {
            "record_type": "candidate",
            "date": today,
            "candidate_id": f"cleaner-{cand['symbol']}-{cand['trigger_tier']}-{dt.datetime.now(CST).strftime('%H%M%S')}",
            "symbol": cand["symbol"],
            "direction": cand["direction"],
            "price": cand["price"],
            "quantity": cand["quantity"],
            "confidence": cand["confidence"],
            "defense_approved": True,
            "reviewed_by": "PortfolioCleaner",
            "reasoning": cand["reason"],
            "thesis": cand["thesis"],
            "catalyst_type": cand["catalyst_type"],
            "entry_rule": "portfolio_cleaner_sell",
            "source": "portfolio_cleaner",
        }
        dm.append_jsonl(record, date=today)

    print(
        f"[PORTFOLIO] 已生成 {len(candidates)} 条清理卖出候选",
        flush=True,
    )


if __name__ == "__main__":
    main()
