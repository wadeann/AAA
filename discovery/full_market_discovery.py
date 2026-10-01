"""全A盘中宽发现器 — 从 5 个不同切入点并发问财搜索，合并去重."""

from __future__ import annotations

import concurrent.futures
from typing import Any

from mcp_client import get_mcp_client


# ── 5 条差异化搜索语句 ──

_QUERIES: list[tuple[str, str]] = [
    (
        "动量突破",
        "股价突破20日均线 涨幅大于3% 成交量放大50%以上 "
        "流通市值50亿到300亿 非ST 非科创板 非北交所",
    ),
    (
        "N字反包",
        "昨日收阴线 今日涨幅大于5% 股价站上5日均线 "
        "流通市值30亿到200亿 非ST",
    ),
    (
        "倍量首板",
        "涨停 首板 成交量是昨日2倍以上 流通市值100亿以下 "
        "非ST 非科创板 换手率5%到25%",
    ),
    (
        "平台突破",
        "横盘15天以上 今日涨幅大于4% 突破60日均线 "
        "流通市值50亿到300亿 非ST 非科创板",
    ),
    (
        "龙回头",
        "前期龙头 回调5日以上 今日翻红 涨幅小于5% "
        "流通市值50亿到500亿 非ST 连板股",
    ),
]


def _search_one(label: str, query: str, limit: int) -> list[dict]:
    """Single wencai search, tagged with the strategy label."""
    client = get_mcp_client()
    rows = client.wencai_search(query, limit=limit)
    for r in rows:
        r["_source_query"] = label
    return rows


def discover_wide_pool() -> dict:
    """Run 5 parallel wencai queries and merge results.

    Returns:
        dict with keys:
          wide_pool: deduplicated list of candidate dicts
          theme_groups: dict mapping strategy label -> list of symbols
          stats: metadata about the scan
    """
    pool_size = 5
    limit_per_query = 50

    with concurrent.futures.ThreadPoolExecutor(max_workers=pool_size) as executor:
        future_map = {
            executor.submit(_search_one, label, q, limit_per_query): label
            for label, q in _QUERIES
        }
        all_results: list[dict] = []
        for future in concurrent.futures.as_completed(future_map):
            try:
                all_results.extend(future.result())
            except Exception as exc:
                label = future_map[future]
                print(f"[WARN] Query '{label}' failed: {exc}")

    # Dedup by symbol, keep first occurrence (most relevant)
    seen: set[str] = set()
    wide_pool: list[dict] = []
    theme_groups: dict[str, list[str]] = {label: [] for label, _ in _QUERIES}

    for row in all_results:
        symbol = _symbol(row)
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)

        # Normalise fields
        normalized = {
            "symbol": symbol,
            "name": str(row.get("股票简称", row.get("name", ""))),
            "price": _safe_float(row, ("最新价", "price", "close")),
            "change_pct": _safe_float(row, ("涨幅", "change_pct", "pct_chg")),
            "volume_ratio": _safe_float(row, ("量比", "volume_ratio", "vol_ratio")),
            "market_cap": _safe_float(row, ("流通市值", "market_cap")),
            "source": str(row.get("_source_query", "")),
        }
        wide_pool.append(normalized)

        src = row.get("_source_query", "unknown")
        if src in theme_groups:
            theme_groups[src].append(symbol)
        else:
            theme_groups.setdefault(src, []).append(symbol)

    return {
        "wide_pool": wide_pool,
        "theme_groups": theme_groups,
        "stats": {
            "total_raw": len(all_results),
            "deduped": len(wide_pool),
            "strategies": len(_QUERIES),
        },
    }


def _symbol(row: dict) -> str:
    for k in ("股票代码", "code", "symbol"):
        v = row.get(k)
        if v:
            return str(v).strip()
    return ""


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
    result = discover_wide_pool()
    pool = result["wide_pool"]
    stats = result["stats"]
    groups = result["theme_groups"]

    print(f"Full market discovery: {stats}")
    print(f"\nWide pool: {len(pool)} candidates\n")

    for r in pool[:15]:
        print(
            f"  {r['symbol']:>8} {r['name']:<10} "
            f"chg={r['change_pct']:+.2f}% vol_ratio={r['volume_ratio']:.2f} "
            f"[{r['source']}]"
        )

    print("\nTheme group counts:")
    for label, symbols in groups.items():
        print(f"  {label}: {len(symbols)} stocks")
