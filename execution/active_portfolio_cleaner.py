#!/usr/bin/env python3
"""Active portfolio cleaner stub.

Evaluates open positions for early-exit candidates pre-market.
Not yet fully ported from myhermes — runs as no-op placeholder.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp_client import get_mcp_client


def main() -> None:
    try:
        positions = get_mcp_client().get_positions()
        for p in positions:
            sym = p.get("symbol", "")
            qty = int(float(p.get("quantity", p.get("available_quantity", 0)) or 0))
            if qty > 0:
                print(f"[持仓] {sym} {qty}股")
    except Exception as e:
        print(f"[PORTFOLIO] 无法获取持仓: {e}")


if __name__ == "__main__":
    main()
