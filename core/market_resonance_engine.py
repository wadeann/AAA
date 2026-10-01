#!/usr/bin/env python3
"""Market resonance engine.

Analyzes sector resonance for a given symbol by querying MCP intel (port 9001).
Checks if the symbol's sector is currently active/leading in the market.
Returns a dict with:
  - role: "primary_attack", "secondary_attack", "rotation", "lagging", "unknown"
  - sector: sector name string
  - resonance_score: 0-100 float

Used by close-session defense for sector-level protection.
"""
from __future__ import annotations

from typing import Any

from mcp_client import get_mcp_client


def analyze_sector_resonance(symbol: str) -> dict:
    """Analyze sector resonance for a given symbol.

    Fetches sector info from MCP intel (port 9001),
    checks mainline lanes for active/leading sectors.
    Returns dict with role, sector, resonance_score.
    """
    client = get_mcp_client()

    # Fetch sector info for the symbol
    sector_name = ""
    sector_change = 0.0
    try:
        raw = client.call("query_data", {"symbol": symbol}, port=9001)
        if isinstance(raw, dict) and "tables" in raw:
            tbl = raw["tables"][0]
            cols = tbl["columns"]
            row = tbl["rows"][0]
            data = dict(zip(cols, row))
        elif isinstance(raw, dict):
            data = raw
        else:
            data = {}

        # Try to extract sector info
        sector_name = str(data.get("行业", data.get("sector", data.get("板块", ""))))
        sector_change = float(data.get("sector_change_pct", data.get("板块涨幅", 0.0)) or 0.0)

        # If no sector directly, try to infer from industry
        if not sector_name:
            industry = str(data.get("industry", data.get("industry_name", data.get("所属行业", ""))))
            if industry:
                sector_name = industry
    except Exception:
        pass

    if not sector_name:
        return {"role": "unknown", "sector": "", "resonance_score": 0}

    # Fetch mainline lanes to check if sector is active/leading
    mainline_sectors: list[str] = []
    try:
        lanes = client.get_mainline_lanes(top_n=5)
        if isinstance(lanes, list):
            for lane in lanes:
                if isinstance(lane, dict):
                    name = str(lane.get("name", lane.get("sector", lane.get("板块", ""))))
                    if name:
                        mainline_sectors.append(name)
        elif isinstance(lanes, dict):
            items = lanes.get("lanes", lanes.get("mainline", lanes.get("data", [])))
            for item in items:
                if isinstance(item, dict):
                    name = str(item.get("name", item.get("sector", item.get("板块", ""))))
                    if name:
                        mainline_sectors.append(name)
    except Exception:
        pass

    # Determine role and score based on sector positioning
    is_primary = any(
        sector_name in ms or ms in sector_name
        for ms in mainline_sectors[:2]
    )
    is_secondary = any(
        sector_name in ms or ms in sector_name
        for ms in mainline_sectors[2:]
    )

    if is_primary and sector_change >= 1.0:
        role = "primary_attack"
        resonance_score = min(100, 70 + int(sector_change * 3))
    elif is_primary:
        role = "primary_attack"
        resonance_score = 60
    elif is_secondary and sector_change >= 0.5:
        role = "secondary_attack"
        resonance_score = 45
    elif is_secondary:
        role = "rotation"
        resonance_score = 30
    elif sector_change >= 1.0:
        role = "secondary_attack"
        resonance_score = 35
    elif sector_change >= -0.5:
        role = "rotation"
        resonance_score = 20
    else:
        role = "lagging"
        resonance_score = 10

    return {
        "role": role,
        "sector": sector_name,
        "resonance_score": resonance_score,
        "sector_change_pct": sector_change,
        "mainline_sectors": mainline_sectors,
    }
