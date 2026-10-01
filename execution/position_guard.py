#!/usr/bin/env python3
"""Position guard.

Pre-market position guard check. Evaluates current positions for:
  - Hard stop: current price < cost * 0.94 (-6% from cost)
  - Trailing stop: -6% drawdown from peak
  - Time exit: held > 20 trading days
Generates sell candidates and writes to JSONL ledger.

Usage:
  python3 -m execution.position_guard
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

HARD_STOP_PCT = -6.0       # -6% from cost
TRAILING_STOP_PCT = -6.0   # -6% from peak
TIME_EXIT_DAYS = 20        # > 20 trading days


def compute_peak(symbol: str) -> dict[str, Any] | None:
    """Fetch daily klines and compute the peak price since entry.

    Returns dict with high_watermark_price, high_watermark_pct or None.
    """
    try:
        client = get_mcp_client()
        klines = client.fetch_klines(symbol, period="D", count=60)
        if not klines:
            return None
        highs = [float(k.get("high", 0) or 0) for k in klines if float(k.get("high", 0) or 0) > 0]
        if not highs:
            return None
        return {"high_watermark_price": max(highs)}
    except Exception:
        return None


def estimate_hold_days(symbol: str) -> int:
    """Estimate hold days by scanning ledger records."""
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


def evaluate_position(pos: dict[str, Any]) -> dict[str, Any] | None:
    """Evaluate a single position and return a sell candidate or None."""
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

    # 1. Hard stop: -6% from cost
    if pnl_pct <= HARD_STOP_PCT:
        return {
            "symbol": symbol,
            "direction": "sell",
            "price": cur_price,
            "quantity": qty,
            "confidence": 0.90,
            "reason": f"hard_stop: pnl={pnl_pct:.1f}% (threshold={HARD_STOP_PCT:.0f}%)",
            "thesis": f"[position_guard] 硬止损触发: 盈亏{pnl_pct:.1f}%",
            "catalyst_type": "position_guard",
            "trigger_tier": "hard_stop",
        }

    # 2. Trailing stop: -6% from peak
    peak = compute_peak(symbol)
    if peak and peak.get("high_watermark_price", 0) > cost:
        peak_price = peak["high_watermark_price"]
        peak_pnl = (peak_price - cost) / cost * 100.0
        drawdown = peak_pnl - pnl_pct
        if drawdown >= abs(TRAILING_STOP_PCT):
            return {
                "symbol": symbol,
                "direction": "sell",
                "price": cur_price,
                "quantity": qty,
                "confidence": 0.80,
                "reason": f"trailing_stop: peak_gain={peak_pnl:.1f}%, drawdown={drawdown:.1f}%",
                "thesis": f"[position_guard] 移动止损: 高点回撤{drawdown:.1f}%",
                "catalyst_type": "position_guard",
                "trigger_tier": "trailing_stop",
            }

    # 3. Time exit: held > 20 trading days
    hold_days = estimate_hold_days(symbol)
    if hold_days > TIME_EXIT_DAYS:
        return {
            "symbol": symbol,
            "direction": "sell",
            "price": cur_price,
            "quantity": qty,
            "confidence": 0.70,
            "reason": f"time_exit: held {hold_days}d, pnl={pnl_pct:.1f}%",
            "thesis": f"[position_guard] 持仓超过{hold_days}天触发时间退出",
            "catalyst_type": "position_guard",
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
        result = {"blocked": False, "error": str(e)}
        print(json.dumps(result, ensure_ascii=False))
        return

    candidates: list[dict[str, Any]] = []
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        result = evaluate_position(pos)
        if result is not None:
            candidates.append(result)
            print(
                f"  [GUARD] {result['symbol']} {result['trigger_tier']}: "
                f"{result['reason']}",
                flush=True,
            )

    if not candidates:
        print(json.dumps({"blocked": False, "open_positions": len(positions)}, ensure_ascii=False))
        return

    for cand in candidates:
        record = {
            "record_type": "candidate",
            "date": today,
            "candidate_id": f"guard-{cand['symbol']}-{cand['trigger_tier']}-{dt.datetime.now(CST).strftime('%H%M%S')}",
            "symbol": cand["symbol"],
            "direction": cand["direction"],
            "price": cand["price"],
            "quantity": cand["quantity"],
            "confidence": cand["confidence"],
            "llm_approved": True,
            "agy_approved": True,
            "reviewed_by": "PositionGuard",
            "reasoning": cand["reason"],
            "thesis": cand["thesis"],
            "catalyst_type": cand["catalyst_type"],
            "entry_rule": "position_guard_sell",
            "source": "position_guard",
        }
        dm.append_jsonl(record, date=today)

    result = {
        "blocked": False,
        "open_positions": len(positions),
        "sell_candidates": len(candidates),
    }
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
