#!/usr/bin/env python3
"""Sector capital flow analysis via Antigravity AGY.

Analyzes A-share sector capital flows and generates rotation forecasts.
Replaces agy_sector_flow.py — all MCP via MCPClient, AGY via agy_bridge.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from data import get_data_manager
from intelligence.agy_bridge import ask_antigravity
from mcp_client import get_mcp_client


def main() -> int:
    """Fetch sector flow data, analyze via AGY, print report."""
    client = get_mcp_client()

    # Check trading day
    if not client.is_trading_day():
        print("[SILENT]")
        return 0

    today = dt.date.today().isoformat()

    # Get sector flow data via MCP
    try:
        health = client.get_market_health()
        # health may already contain sector flow info
        datas: list[dict[str, Any]] = []
        if isinstance(health, dict):
            sectors = health.get("sectors", health.get("sector_flow", []))
            if isinstance(sectors, list):
                datas = sectors
    except Exception:
        datas = []

    # Fallback: query via wencai
    if not datas:
        try:
            raw = client.wencai_search(f"{today} 行业板块 资金净流入 涨跌幅 前10", limit=10)
            datas = raw if isinstance(raw, list) else raw.get("datas", []) if isinstance(raw, dict) else []
        except Exception:
            datas = []

    # Disaster recovery: from today's candidate ledger
    if not datas:
        try:
            dm = get_data_manager()
            today_path = dm.ledger_dir / f"candidates_{today}.jsonl"
            if today_path.exists():
                sectors: list[str] = []
                for line in today_path.read_text(encoding="utf-8").splitlines():
                    try:
                        c = json.loads(line)
                        s = c.get("sector") or c.get("primary_sector")
                        if s and len(s) > 1:
                            sectors.append(s)
                    except Exception:
                        pass
                top_sectors = Counter(sectors).most_common(5)
                datas = [{"板块名称": s, "龙头热度频次": count} for s, count in top_sectors]
        except Exception:
            pass

    prompt = (
        f"You are the A-share capital flow and sector rotation chief analyst. "
        f"Based on today's sector capital flow data for deep analysis:\n"
        f"- Today's main force sector data: {json.dumps(datas[:8], ensure_ascii=False)}\n\n"
        f"【Output constraints】: Strictly limited to 4-5 lines:\n"
        f"1. Today's strongest net inflow sectors and leading themes\n"
        f"2. Main force capital withdrawal direction\n"
        f"3. Tomorrow's sector rotation and attack direction forecast"
    )

    res = ask_antigravity(prompt, timeout=120)
    print(f"[Sector Capital Flow | {today}]", flush=True)
    print(res, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
