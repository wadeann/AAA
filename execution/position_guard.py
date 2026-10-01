#!/usr/bin/env python3
"""Position guard stub.

Pre-market position guard check. Evaluates current positions for risk.
Not yet fully ported from myhermes — runs basic check.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from mcp_client import get_mcp_client


def main() -> None:
    try:
        positions = get_mcp_client().get_positions()
        open_count = sum(1 for p in positions if int(float(p.get("quantity", 0) or 0)) > 0)
        result = {"blocked": False, "open_positions": open_count}
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        result = {"blocked": False, "error": str(e)}
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
