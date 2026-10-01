#!/usr/bin/env python3
"""Dragon screener engine stub.

Scans for dragon-type (high-board) leaders. Not yet ported from myhermes.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from discovery.limitup_scanner import get_ladder


def main() -> None:
    ladder = get_ladder()
    dragons = [d for d in ladder if d.get("board_height", 0) >= 3]
    print(f"[DRAGON] 连板>=3: {len(dragons)} 只")
    for d in dragons:
        print(f"  {d.get('symbol','')} {d.get('name','')} {d.get('board_height',0)}板")


if __name__ == "__main__":
    main()
