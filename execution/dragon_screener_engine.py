#!/usr/bin/env python3
"""Dragon screener engine.

Grades limit-up ladder entries into dragon tiers:
  - iron_dragon:   >= 5 boards or 4 boards with strong order book
  - dragon:        2-3 boards with good volume/order book
  - candidate:     single board with strong fundamentals
  - watch:         everything else

Returns graded list with scores. Importable by morning_master.

Usage:
  python3 -m execution.dragon_screener_engine
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from discovery.limitup_scanner import get_ladder


# Dragon tier thresholds
IRON_MIN_BOARDS = 5
IRON_4_QUALITY = "strong"
DRAGON_MIN_BOARDS = 2
CANDIDATE_MIN_BOARDS = 1
CANDIDATE_MIN_SCORE = 40


def grade_dragon_tier(entry: dict[str, Any]) -> dict[str, Any]:
    """Grade a ladder entry into a dragon tier.

    Mutates and returns the entry with added keys: dragon_tier, dragon_score.
    """
    boards = entry.get("boards", 0)
    seal_grade = entry.get("seal_grade", "weak")
    order_book = entry.get("order_book_quality", "weak")
    score = entry.get("score", 0)

    # Iron dragon: high-board leaders
    if boards >= IRON_MIN_BOARDS or (boards >= 4 and order_book == IRON_4_QUALITY):
        dragon_score = min(100, score + 10)
        entry["dragon_tier"] = "iron_dragon"
        entry["dragon_score"] = dragon_score
        entry["dragon_reason"] = f"{boards}连板, 封板{seal_grade}, 封单{order_book}"
    # Dragon: multi-board with quality
    elif boards >= DRAGON_MIN_BOARDS and seal_grade in ("strong", "iron"):
        dragon_score = min(90, score + 5)
        entry["dragon_tier"] = "dragon"
        entry["dragon_score"] = dragon_score
        entry["dragon_reason"] = f"{boards}连板, 封板{seal_grade}"
    # Candidate: single board promising
    elif boards >= CANDIDATE_MIN_BOARDS and score >= CANDIDATE_MIN_SCORE:
        dragon_score = score
        entry["dragon_tier"] = "candidate"
        entry["dragon_score"] = dragon_score
        entry["dragon_reason"] = f"首板, 评分{score}"
    # Watch: everything else
    else:
        entry["dragon_tier"] = "watch"
        entry["dragon_score"] = max(0, score - 20)
        entry["dragon_reason"] = f"观察, 评分{score}"

    return entry


def screen_dragons(min_streak: int = 1) -> list[dict[str, Any]]:
    """Fetch ladder and grade each entry into dragon tiers.

    Returns sorted list with dragon tier metadata.
    """
    ladder = get_ladder(min_streak=min_streak)
    for entry in ladder:
        grade_dragon_tier(entry)

    # Sort by dragon_score descending, then by boards descending
    ladder.sort(key=lambda x: (x.get("dragon_score", 0), x.get("boards", 0)), reverse=True)
    return ladder


def get_dragon_tier_summary(dragons: list[dict[str, Any]]) -> dict[str, int]:
    """Return count per tier."""
    summary: dict[str, int] = {}
    for d in dragons:
        tier = d.get("dragon_tier", "watch")
        summary[tier] = summary.get(tier, 0) + 1
    return summary


def main() -> None:
    dragons = screen_dragons(min_streak=1)
    summary = get_dragon_tier_summary(dragons)
    print(f"[DRAGON] 涨停梯队扫描: {len(dragons)} 只")
    print(f"  Tier分布: {summary}")

    for entry in dragons:
        tier = entry.get("dragon_tier", "?")
        if tier in ("iron_dragon", "dragon"):
            print(
                f"  [{tier.upper():<14}] {entry.get('symbol',''):>8} "
                f"{entry.get('name',''):<10} {entry.get('boards',0)}板 "
                f"score={entry.get('dragon_score',0)}",
                flush=True,
            )


if __name__ == "__main__":
    main()
