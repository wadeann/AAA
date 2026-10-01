"""09:25 集合竞价扫描器 — 抓取跳空高开 3%-7.5% 且伴随成交量放大的标的."""

from __future__ import annotations

import datetime as dt
from typing import Any

from mcp_client import get_mcp_client


def scan_auction() -> list[dict]:
    """Scan stocks that gap up 3-7.5% at 09:25 auction with volume explosion.

    Uses wencai_search to find candidates, then scores each one.
    Returns list of dicts with keys: symbol, name, auction_price,
    volume_ratio, confidence, score.
    """
    client = get_mcp_client()
    query = (
        "集合竞价 涨幅3%到7.5% 成交量放大 首板 流通市值50亿到200亿 "
        "现价不高于20元 竞价量大于昨日总成交量5%"
    )
    raw = client.wencai_search(query, limit=50)

    candidates: list[dict] = []
    for row in raw:
        symbol = str(row.get("股票代码", row.get("code", row.get("symbol", ""))))
        name = str(row.get("股票简称", row.get("name", "")))
        gap_pct = _safe_float(row, ("竞价涨幅", "涨幅", "gap_pct", "change_pct"))
        volume_ratio = _safe_float(
            row, ("竞价量比", "量比", "volume_ratio", "vol_ratio")
        )
        auction_price = _safe_float(row, ("竞价价格", "竞价格", "price", "auction_price"))
        market_cap = _safe_float(
            row, ("流通市值", "market_cap", "circulating_market_cap")
        )

        if not symbol:
            continue

        score = score_auction_candidate({
            "gap_pct": gap_pct,
            "volume_ratio": volume_ratio,
            "market_cap": market_cap,
        })

        candidates.append({
            "symbol": symbol,
            "name": name,
            "auction_price": auction_price,
            "gap_pct": gap_pct,
            "volume_ratio": volume_ratio,
            "market_cap": market_cap,
            "confidence": min(1.0, max(0.0, score / 100.0)),
            "score": round(score, 1),
            # Pipeline compatibility fields
            "direction": "buy",
            "price": auction_price,
            "quantity": 0,
            "candidate_id": f"auction-{symbol}-{dt.date.today().isoformat()}",
            "thesis": f"[集合竞价] {name}({symbol}) 跳空{gap_pct:.1f}% 量比{volume_ratio:.1f}",
            "entry_rule": "auction_gap_up",
            "catalyst_type": "call_auction",
            "llm_approved": False,
            "agy_approved": False,
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


def score_auction_candidate(row: dict) -> float:
    """Score from 0-100 based on gap %, volume ratio, market cap.

    Weight distribution:
      - Gap % (40 pts): 3% = 0, 5.25% = 40, 7.5% = 20 (inverted V)
      - Volume ratio (35 pts): >= 3 = 35, linear down to 0
      - Market cap (25 pts): 50-100B = 25, 100-150B = 18, 150-200B = 10
    """
    gap_pct = row.get("gap_pct", 0.0) or 0.0
    volume_ratio = row.get("volume_ratio", 0.0) or 0.0
    market_cap = row.get("market_cap", 0.0) or 0.0

    # Gap score: inverted-V centered at ~5.25%
    if gap_pct < 3.0 or gap_pct > 7.5:
        gap_score = 0.0
    elif gap_pct <= 5.25:
        gap_score = 40.0 * (gap_pct - 3.0) / 2.25
    else:
        gap_score = 40.0 * (7.5 - gap_pct) / 2.25

    # Volume ratio score
    if volume_ratio >= 3.0:
        vol_score = 35.0
    elif volume_ratio >= 1.0:
        vol_score = 35.0 * (volume_ratio - 1.0) / 2.0
    else:
        vol_score = 0.0

    # Market cap score
    if 50 <= market_cap <= 100:
        cap_score = 25.0
    elif 100 < market_cap <= 150:
        cap_score = 18.0
    elif 150 < market_cap <= 200:
        cap_score = 10.0
    else:
        cap_score = 0.0

    return gap_score + vol_score + cap_score


def _confidence_label(score: float) -> str:
    if score >= 80:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def _safe_float(row: dict, keys: tuple[str, ...]) -> float:
    for k in keys:
        v = row.get(k)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
    return 0.0


if __name__ == "__main__":
    results = scan_auction()
    print(f"Auction scanner found {len(results)} candidates:\n")
    for r in results[:10]:
        print(
            f"  {r['symbol']:>8} {r['name']:<10} "
            f"gap={r['gap_pct']:.2f}% vol_ratio={r['volume_ratio']:.2f} "
            f"score={r['score']:.1f} confidence={r['confidence']}"
        )
