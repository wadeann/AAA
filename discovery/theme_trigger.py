"""题材起爆引擎 — 消费 discovery 快照，排序题材，筛选种子股做深度筛查."""

from __future__ import annotations

import concurrent.futures
from typing import Any

from mcp_client import get_mcp_client

# ── 题材衍生搜索模板 ──

_THEME_DEEP_QUERIES: dict[str, str] = {
    "涨停梯队": "涨停 {theme} 连板 非ST",
    "竞价异动": "集合竞价 高开 {theme} 放量",
    "资金流入": "{theme} 主力资金净流入 大单 涨幅小于7%",
    "平台突破": "{theme} 横盘突破 均线多头排列 非ST",
    "低位首板": "{theme} 首板 低位 流通市值小于100亿",
}


def trigger_themes(discovery_result: dict) -> list[dict]:
    """Consume a discovery snapshot, rank themes, return top seeds.

    Args:
        discovery_result: output of full_market_discovery.discover_wide_pool().

    Returns:
        List of theme dicts, each containing:
          theme_name, score, rank, seed_count, seeds (list of candidate dicts).
    """
    raw_themes: dict[str, list[str]] = discovery_result.get("theme_groups", {})
    theme_details = rank_themes_by_momentum(raw_themes)

    top_themes = theme_details[:8]

    # Deep-screen each top theme with parallel queries
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_map = {
            executor.submit(_deep_screen_theme, t["theme_name"]): t
            for t in top_themes
        }
        for future in concurrent.futures.as_completed(future_map):
            theme = future_map[future]
            try:
                theme["seeds"] = future.result()
                theme["seed_count"] = len(theme["seeds"])
            except Exception as exc:
                print(f"[WARN] Deep screen for '{theme['theme_name']}' failed: {exc}")
                theme["seeds"] = []
                theme["seed_count"] = 0

    return top_themes


def rank_themes_by_momentum(themes: dict) -> list[dict]:
    """Rank themes by inferred momentum. Returns descending list of theme dicts.

    Scoring factors:
      - Group size (more stocks = higher attention)
      - Label priority (动量突破 > N字反包 > 倍量首板 > 平台突破 > 龙回头)
    """
    priority = {
        "动量突破": 5,
        "N字反包": 4,
        "倍量首板": 3,
        "平台突破": 2,
        "龙回头": 1,
    }
    scored: list[dict] = []
    for theme_name, symbols in themes.items():
        size = len(symbols)
        base = priority.get(theme_name, 0)
        score = base * 10 + min(size, 20) * 2
        scored.append({
            "theme_name": theme_name,
            "score": score,
            "symbol_count": size,
            "symbols": symbols[:20],
            "seeds": [],
            "seed_count": 0,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)
    for i, t in enumerate(scored):
        t["rank"] = i + 1
    return scored


def _deep_screen_theme(theme_name: str) -> list[dict]:
    """Run multiple deep-queries for a theme, merge up to 8 unique seeds."""
    client = get_mcp_client()
    seen: set[str] = set()
    seeds: list[dict] = []

    for label, template in _THEME_DEEP_QUERIES.items():
        if len(seeds) >= 8:
            break
        query = template.format(theme=theme_name)
        try:
            rows = client.wencai_search(query, limit=10)
        except Exception:
            continue
        for row in rows:
            if len(seeds) >= 8:
                break
            symbol = str(row.get("股票代码", row.get("code", row.get("symbol", "")))).strip()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)
            seeds.append({
                "symbol": symbol,
                "name": str(row.get("股票简称", row.get("name", ""))),
                "price": _safe_float(row, ("最新价", "price", "close")),
                "change_pct": _safe_float(row, ("涨幅", "change_pct")),
                "source_query": label,
            })

    return seeds[:8]


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
    # Standalone demo: build a minimal discovery_result to test
    dummy_discovery = {
        "theme_groups": {
            "动量突破": ["000001", "000002", "000003", "600000", "600001"],
            "N字反包": ["000004", "000005", "600002"],
            "倍量首板": ["000006", "000007", "000008", "000009"],
            "平台突破": ["000010", "600003"],
            "龙回头": ["000011", "000012", "000013", "000014", "000015", "600004"],
        },
    }

    ranked_themes = trigger_themes(dummy_discovery)
    print(f"Themes triggered: {len(ranked_themes)}\n")
    for t in ranked_themes:
        print(
            f"  #{t['rank']} {t['theme_name']:<10} "
            f"score={t['score']} "
            f"symbols={t['symbol_count']} "
            f"seeds={t['seed_count']}"
        )
        for s in t.get("seeds", [])[:4]:
            print(f"       {s['symbol']} {s['name']} [{s['source_query']}]")
