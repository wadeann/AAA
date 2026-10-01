"""涨停梯队扫描器 — 获取涨停连板数据并评估封板强度."""

from __future__ import annotations

from typing import Any

from mcp_client import get_mcp_client


def get_ladder(min_streak: int = 1) -> list[dict]:
    """Fetch limit-up ladder from MCP and grade seal strength.

    Args:
        min_streak: minimum consecutive limit-up boards to include.

    Returns:
        List of graded dicts with keys: symbol, name, boards, seal_grade,
        order_book_quality, score, reason.
    """
    client = get_mcp_client()
    raw: Any = client.get_limitup_ladder(min_streak=min_streak)

    ladder: list[dict] = []
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("ladder", raw.get("items", raw.get("data", [])))
    else:
        items = []

    for item in items:
        if isinstance(item, str):
            ladder.append({"symbol": item, "name": "", "boards": 0})
            continue
        symbol = str(item.get("股票代码", item.get("code", item.get("symbol", ""))))
        name = str(item.get("股票简称", item.get("name", "")))
        boards = int(item.get("连板数", item.get("boards", item.get("streak", 0))))
        ladder.append({
            "symbol": symbol,
            "name": name,
            "boards": boards,
            **{k: item[k] for k in item if k not in ("symbol", "name", "boards")},
        })

    return grade_seal_strength(ladder)


def grade_seal_strength(ladder_data: list[dict]) -> list[dict]:
    """Grade seal strength for each ladder entry.

    Grades:
      - iron:    >= 5 boards, or 4 boards with strong order book
      - strong:  2-3 boards with healthy volume and order book
      - weak:    single board, or low order-book quality

    Mutates and returns the same list with added keys:
      seal_grade, order_book_quality, score, reason.
    """
    for entry in ladder_data:
        boards = entry.get("boards", 0)
        order_book_quality = _infer_order_book_quality(entry)
        entry["order_book_quality"] = order_book_quality

        if boards >= 5:
            entry["seal_grade"] = "iron"
            entry["score"] = _iron_score(boards, order_book_quality)
            entry["reason"] = f"{boards}连板, 封单质量{order_book_quality}"
        elif boards == 4 and order_book_quality in ("strong", "fair"):
            entry["seal_grade"] = "iron"
            entry["score"] = 85 + (5 if order_book_quality == "strong" else 0)
            entry["reason"] = f"4连板+{order_book_quality}封单, 晋级铁板"
        elif boards >= 2:
            entry["seal_grade"] = "strong"
            entry["score"] = 60 + boards * 5 + (10 if order_book_quality == "strong" else 0)
            entry["reason"] = f"{boards}连板, 封板强度中等"
        else:
            entry["seal_grade"] = "weak"
            entry["score"] = 30 + (15 if order_book_quality == "strong" else 0)
            entry["reason"] = f"首板, 需观察次日溢价"

    ladder_data.sort(key=lambda x: x.get("score", 0), reverse=True)
    return ladder_data


def _infer_order_book_quality(entry: dict) -> str:
    """Infer order book quality from available fields.

    Looks at: sealing_amount (封单金额), turnover_rate, volume_ratio.
    Returns 'strong', 'fair', or 'weak'.
    """
    sealing_amount = entry.get("封单金额", entry.get("sealing_amount", 0))
    turnover_rate = entry.get("换手率", entry.get("turnover_rate", 100))
    volume_ratio = entry.get("量比", entry.get("volume_ratio", 1))

    try:
        sealing_amount = float(sealing_amount) if sealing_amount else 0
        turnover_rate = float(turnover_rate) if turnover_rate else 100
        volume_ratio = float(volume_ratio) if volume_ratio else 1
    except (ValueError, TypeError):
        sealing_amount, turnover_rate, volume_ratio = 0, 100, 1

    if sealing_amount > 1e8 and turnover_rate < 10:
        return "strong"
    if sealing_amount > 3e7 or turnover_rate < 20:
        return "fair"
    return "weak"


def _iron_score(boards: int, quality: str) -> int:
    base = 80 + min(boards, 10) * 2
    bonus = {"strong": 10, "fair": 5, "weak": 0}
    return base + bonus.get(quality, 0)


if __name__ == "__main__":
    ladder = get_ladder(min_streak=1)
    print(f"Limit-up ladder: {len(ladder)} entries\n")
    for entry in ladder[:15]:
        print(
            f"  {entry['symbol']:>8} {entry['name']:<10} "
            f"{entry['boards']}板 "
            f"grade={entry['seal_grade']:<6} "
            f"order_book={entry['order_book_quality']:<6} "
            f"score={entry['score']}"
        )
