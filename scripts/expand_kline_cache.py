#!/usr/bin/env python3
"""Expand kline_cache.json with missing stocks fetched via MCP.

Fetches kline data for:
- 920xxx.BJ (北交所) stocks not yet in cache
- Any other missing stocks identified
- Saves to kline_cache.json incrementally
"""

import json
import sys
import time
import os
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KLINE_CACHE_PATH = PROJECT_ROOT / "data" / "kline_cache.json"
MISSING_STOCKS_PATH = Path("/tmp/missing_stocks.json")

MCP_URL = "http://127.0.0.1:9001/mcp"
REQUEST_DELAY = 0.3  # seconds between requests to be polite
BATCH_SIZE = 20
KLINES_COUNT = 500  # get 500 daily bars (~2 years)


def call_mcp(tool: str, arguments: dict, timeout: float = 30.0) -> dict:
    """Call MCP JSON-RPC endpoint."""
    with httpx.Client(timeout=timeout) as c:
        resp = c.post(MCP_URL, json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        })
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"MCP error [{tool}]: {data['error']}")
        content = data.get("result", {}).get("content", [])
        if not content:
            return {}
        text = content[0].get("text", "{}")
        return json.loads(text)


def load_missing_stocks() -> list[str]:
    """Load list of missing stocks or compute from cache vs full_universe_raw."""
    if MISSING_STOCKS_PATH.exists():
        with open(MISSING_STOCKS_PATH) as f:
            return json.load(f)

    # Compute missing stocks
    with open(KLINE_CACHE_PATH) as f:
        kline_cache = json.load(f)

    cached_symbols = set()
    for k in kline_cache:
        symbol = "_".join(k.split("_")[:-1]) if "_" in k else k
        cached_symbols.add(symbol)

    with open(PROJECT_ROOT / "data" / "full_universe_raw.json") as f:
        full_raw = json.load(f)

    missing = set(full_raw.keys()) - cached_symbols
    return sorted(missing)


def fetch_kline(symbol: str) -> list[dict] | None:
    """Fetch kline data for a single stock."""
    try:
        result = call_mcp("fetch_kline", {
            "symbol": symbol,
            "period": "D",
            "count": KLINES_COUNT,
        })
        klines = result.get("klines", [])
        if not klines:
            print(f"  {symbol}: 0 klines returned")
            return None
        print(f"  {symbol}: {len(klines)} klines ({klines[0]['time']} to {klines[-1]['time']})")
        return klines
    except Exception as e:
        print(f"  {symbol}: ERROR - {e}")
        return None


def main():
    print("=== Expanding kline_cache.json ===")

    # Load current cache
    with open(KLINE_CACHE_PATH) as f:
        kline_cache = json.load(f)

    initial_count = len(kline_cache)
    print(f"Current cache size: {initial_count} entries")

    # Load missing stocks
    missing = load_missing_stocks()
    print(f"Missing stocks to fetch: {len(missing)}")
    if not missing:
        print("No missing stocks found!")
        return

    # Show what we're fetching
    from collections import Counter
    pf = Counter(s[:3] for s in missing)
    for p in sorted(pf):
        print(f"  {p}: {pf[p]}")

    # Fetch in batches
    new_entries = 0
    failed = []

    for i, symbol in enumerate(missing):
        if i > 0 and i % BATCH_SIZE == 0:
            print(f"\n  Progress: {i}/{len(missing)} ({new_entries} new). Saving checkpoint...")
            with open(KLINE_CACHE_PATH, "w") as f:
                json.dump(kline_cache, f, ensure_ascii=False)

        klines = fetch_kline(symbol)
        time.sleep(REQUEST_DELAY)

        if klines:
            key = f"{symbol}_{KLINES_COUNT}"
            kline_cache[key] = klines
            new_entries += 1
        else:
            failed.append(symbol)

    # Final save
    final_count = len(kline_cache)
    print(f"\n=== Summary ===")
    print(f"Initial entries: {initial_count}")
    print(f"New entries added: {new_entries}")
    print(f"Failed: {len(failed)}")
    print(f"Final cache size: {final_count}")

    with open(KLINE_CACHE_PATH, "w") as f:
        json.dump(kline_cache, f, ensure_ascii=False)

    if failed:
        print(f"\nFailed stocks: {failed}")
        with open("/tmp/failed_stocks.json", "w") as f:
            json.dump(failed, f)

    print("Done!")


if __name__ == "__main__":
    main()
