#!/usr/bin/env python3
"""Auction kill switch.

Checks today's auction results for adverse signals:
  - Gap-down: auction open significantly below pre-close
  - Volume reversal: abnormal auction volume with weak open
Generates emergency exit orders for auction-entered positions.

Usage:
  python3 -m execution.auction_kill_switch
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from data import get_data_manager
from mcp_client import get_mcp_client

CST = dt.timezone(dt.timedelta(hours=8))


def fetch_auction_quotes(symbols: list[str]) -> dict[str, dict[str, Any]]:
    """Fetch current quotes for given symbols via MCP intel port."""
    client = get_mcp_client()
    result: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        try:
            raw = client.call("query_data", {"symbol": sym}, port=9001)
            if isinstance(raw, dict) and "tables" in raw:
                tbl = raw["tables"][0]
                cols = tbl["columns"]
                row = tbl["rows"][0]
                result[sym] = dict(zip(cols, row))
            elif isinstance(raw, dict):
                result[sym] = raw
        except Exception:
            pass
    return result


def evaluate_auction_risk(
    symbol: str,
    quote: dict[str, Any],
    pos: dict[str, Any],
) -> dict[str, Any] | None:
    """Evaluate auction adverse signals for a position.

    Returns a sell candidate dict or None.
    """
    cost = float(pos.get("cost_price", 0) or 0)
    qty_raw = pos.get("quantity", pos.get("available_quantity", 0))
    qty = int(float(qty_raw if qty_raw is not None else 0))
    if qty < 100 or cost <= 0:
        return None

    cur_price = float(quote.get("price", quote.get("current", 0)) or 0)
    open_price = float(quote.get("open", 0) or 0)
    pre_close = float(quote.get("pre_close", quote.get("prev_close", 0)) or 0)
    auction_vol = float(quote.get("auction_volume", quote.get("bid_volume", 0)) or 0)
    change_pct = float(quote.get("change_pct", 0) or 0)

    if cur_price <= 0:
        return None

    reasons: list[str] = []

    # Gap-down signal: open significantly below pre-close
    if pre_close > 0 and open_price > 0:
        gap_pct = (open_price - pre_close) / pre_close * 100.0
        if gap_pct <= -2.0:
            reasons.append(f"gap_down: open={gap_pct:.1f}%")

    # Volume reversal: high auction volume but weak open
    if auction_vol > 0 and pre_close > 0 and open_price > 0:
        vol_factor = auction_vol / 10000  # rough volume gauge
        gap = (open_price - pre_close) / pre_close * 100.0
        if vol_factor > 5.0 and gap < 0:
            reasons.append(f"volume_reversal: auction_vol={auction_vol:.0f}, gap={gap:.1f}%")

    # Change pct negative sign of weakness
    if change_pct < -1.0:
        reasons.append(f"weak_open: change={change_pct:.1f}%")

    if not reasons:
        return None

    return {
        "symbol": symbol,
        "direction": "sell",
        "price": cur_price,
        "quantity": qty,
        "confidence": 0.80,
        "reason": "; ".join(reasons),
        "thesis": f"[auction_kill] {'; '.join(reasons)}",
        "catalyst_type": "auction_kill_switch",
        "trigger_tier": "auction_adverse",
    }


def main() -> None:
    client = get_mcp_client()
    dm = get_data_manager()
    today = dt.date.today().isoformat()

    # Fetch positions that were entered via auction
    try:
        positions = client.get_positions()
    except Exception as e:
        print(f"[KILLSWITCH] 无法获取持仓: {e}", flush=True)
        return

    if not positions:
        print("[KILLSWITCH] 无持仓, 跳过", flush=True)
        return

    # Filter for auction-entered positions (buy_date == today or recent)
    auction_positions = []
    for pos in positions:
        if not isinstance(pos, dict):
            continue
        buy_date = str(pos.get("buy_date", ""))[:10]
        if buy_date == today:
            auction_positions.append(pos)

    if not auction_positions:
        print("[KILLSWITCH] 无今日竞价买入持仓, 跳过", flush=True)
        return

    symbols = [str(p.get("symbol", "")) for p in auction_positions if p.get("symbol")]
    quotes = fetch_auction_quotes(symbols)

    candidates: list[dict[str, Any]] = []
    for pos in auction_positions:
        sym = str(pos.get("symbol", ""))
        if not sym or sym not in quotes:
            continue
        result = evaluate_auction_risk(sym, quotes[sym], pos)
        if result is not None:
            candidates.append(result)
            print(
                f"  [KILL] {sym}: {result['reason']}",
                flush=True,
            )

    if not candidates:
        print("[KILLSWITCH] 所有竞价买入标的安全, 无核按钮信号", flush=True)
        return

    for cand in candidates:
        record = {
            "record_type": "candidate",
            "date": today,
            "candidate_id": f"kill-{cand['symbol']}-{dt.datetime.now(CST).strftime('%H%M%S')}",
            "symbol": cand["symbol"],
            "direction": cand["direction"],
            "price": cand["price"],
            "quantity": cand["quantity"],
            "confidence": cand["confidence"],
            "llm_approved": True,
            "agy_approved": True,
            "reviewed_by": "AuctionKillSwitch",
            "reasoning": cand["reason"],
            "thesis": cand["thesis"],
            "catalyst_type": cand["catalyst_type"],
            "entry_rule": "auction_kill_sell",
            "source": "auction_kill_switch",
        }
        dm.append_jsonl(record, date=today)

    print(
        f"[KILLSWITCH] 已生成 {len(candidates)} 条竞价核按钮卖出候选",
        flush=True,
    )


if __name__ == "__main__":
    main()
