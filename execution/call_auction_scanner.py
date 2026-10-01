#!/usr/bin/env python3
"""Call auction scanner — morning master Phase 1 shim.

Delegates to discovery.auction_scanner.scan_auction().
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from discovery.auction_scanner import scan_auction


def main() -> None:
    results = scan_auction()
    print(f"竞价扫描完成: {len(results)} 个标的")


if __name__ == "__main__":
    main()
