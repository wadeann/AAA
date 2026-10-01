#!/usr/bin/env python3
"""Limit-up scanner — morning master Phase 2 shim.

Delegates to discovery.limitup_scanner.get_ladder().
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from discovery.limitup_scanner import get_ladder, grade_seal_strength


def main() -> None:
    ladder = get_ladder()
    graded = grade_seal_strength(ladder)
    print(f"涨停梯队扫描: {len(ladder)} 只, 已评级 {len(graded)} 只")


if __name__ == "__main__":
    main()
