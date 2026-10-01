#!/usr/bin/env python3
"""龙头精选池过滤器 (Leader Universe Filter).

移植至 Astock: urllib MCP 调用替换为 MCPClient, ~/.hermes 路径替换为 STATE_DIR.
"""
from __future__ import annotations

import collections
import datetime as dt
import json
from typing import Any, Optional

from config import STATE_DIR
from mcp_client import get_mcp_client

LEADER_FILE = STATE_DIR / "leader_universe.json"
CST = dt.timezone(dt.timedelta(hours=8))


def get_5d_avg_turnover_yi(symbol: str, quote_amount: float = 0.0, verbose: bool = False) -> float:
    """获取标的前5日日均成交额(亿元)."""
    try:
        client = get_mcp_client()
        bars = client.fetch_klines(symbol, period="D", count=6)
        if bars and len(bars) > 0:
            amounts = []
            for b in bars:
                raw = b.get("amount", 0.0) or 0.0
                amounts.append(float(raw))
            if amounts:
                recent_5 = amounts[-5:] if len(amounts) >= 5 else amounts
                avg_amount = sum(recent_5) / len(recent_5)
                avg_yi = avg_amount / 1e8
                if verbose:
                    print(f"  [K线量能] {symbol}: 5日均成交额={avg_yi:.2f}亿", flush=True)
                return round(avg_yi, 2)
    except Exception:
        pass

    try:
        datas = get_mcp_client().wencai_search(f"{symbol} 5日日均成交额")
        if datas and isinstance(datas[0], dict):
            for row in datas:
                row_name = str(row.get("名称", row.get("code", "")))
                if row_name and symbol not in row_name:
                    continue
                for k, v in row.items():
                    if "成交额" in k or "平均值" in k:
                        avg_yi = float(v) / 1e8
                        return round(avg_yi, 2)
            for k, v in datas[0].items():
                if "成交额" in k or "平均值" in k:
                    avg_yi = float(v) / 1e8
                    return round(avg_yi, 2)
    except Exception:
        pass

    if quote_amount > 0:
        return round(quote_amount / 1e8, 2)
    return 0.0


def get_10d_limitup_count(symbol: str, verbose: bool = False) -> int:
    """获取标的10日内涨停次数."""
    try:
        datas = get_mcp_client().wencai_search(f"{symbol} 10日内涨停次数")
        if datas and isinstance(datas[0], dict):
            for k, v in datas[0].items():
                if "涨停次数" == k.strip() or ("涨停" in k and "非" not in k and "无" not in k and "跌" not in k):
                    val = int(float(v)) if v else 0
                    return val
    except Exception:
        pass
    return 0


def get_leader_universe(force_refresh: bool = False, output_only: bool = False,
                        verbose: bool = False) -> list[dict[str, Any]]:
    """返回当前全市场符合条件的龙头池."""
    if output_only and not force_refresh:
        if LEADER_FILE.exists():
            try:
                data = json.loads(LEADER_FILE.read_text(encoding="utf-8"))
                leaders = data.get("leaders", [])
                if verbose:
                    print(f"读取已保存龙头池: {len(leaders)} 只", flush=True)
                return leaders
            except Exception:
                pass

    if verbose:
        print("扫描全市场连板梯队...", flush=True)

    client = get_mcp_client()
    ladder_data = client.get_limitup_ladder(min_streak=1)
    ladder = ladder_data.get("ladder", {}) if isinstance(ladder_data, dict) else ladder_data
    if not ladder:
        if verbose:
            print("未获取到连板梯队数据", flush=True)
        return []

    all_candidates: list[dict[str, Any]] = []
    industry_height_map: dict[str, list[int]] = collections.defaultdict(list)

    if isinstance(ladder, dict):
        for height_str, items in ladder.items():
            try:
                h = int(height_str)
            except ValueError:
                continue
            for it in items:
                if isinstance(it, dict):
                    it["board_height"] = h
                    ind = it.get("industry", "").strip() or "综合"
                    industry_height_map[ind].append(h)
                    all_candidates.append(it)

    tier1_candidates: list[dict[str, Any]] = []
    for cand in all_candidates:
        sym = cand.get("symbol", "")
        nm = cand.get("name", "")
        h = cand.get("board_height", 0)
        ind = cand.get("industry", "").strip() or "综合"
        heights_in_ind = industry_height_map.get(ind, [])
        max_h_in_ind = max(heights_in_ind) if heights_in_ind else 0
        tie_count = sum(1 for x in heights_in_ind if x == max_h_in_ind)
        is_sector_unique_first = (h == max_h_in_ind) and (tie_count == 1) and (h >= 2)
        if is_sector_unique_first:
            tier1_candidates.append(cand)
        elif verbose and h >= 2:
            print(f"  排除 {sym} {nm} ({ind} {h}板 最高{max_h_in_ind}板 并列{tie_count})", flush=True)

    symbols = [c["symbol"] for c in tier1_candidates]
    quotes = {}
    if symbols:
        try:
            q_res = client.query_quotes(symbols)
            quotes = q_res if isinstance(q_res, dict) else {}
        except Exception:
            pass

    qualified_leaders: list[dict[str, Any]] = []
    now_cst = dt.datetime.now(CST)

    for cand in tier1_candidates:
        sym = cand["symbol"]
        nm = cand.get("name", "")
        h = cand.get("board_height", 2)
        ind = cand.get("industry", "主线").strip() or "综合"
        q = quotes.get(sym, {}) if isinstance(quotes, dict) else {}
        today_amount = float(q.get("amount", 0.0) or 0.0)
        cur_price = float(q.get("price", cand.get("price", 0.0)) or 0.0)
        cur_pct = float(q.get("change_pct", cand.get("change_pct", 0.0)) or 0.0)

        avg_5d_yi = get_5d_avg_turnover_yi(sym, quote_amount=today_amount, verbose=verbose)
        if avg_5d_yi < 8.0:
            if verbose:
                print(f"  容量门禁: {sym} {nm} 5日均额{avg_5d_yi:.2f}亿<8亿", flush=True)
            continue

        limitup_10d = get_10d_limitup_count(sym, verbose=verbose)
        if limitup_10d < 2:
            if verbose:
                print(f"  涨停频次: {sym} {nm} 10日涨停{limitup_10d}<2次", flush=True)
            continue

        qualified_leaders.append({
            "symbol": sym, "name": nm, "industry": ind, "board_height": h,
            "price": cur_price, "change_pct": cur_pct,
            "avg_turnover_5d_yi": avg_5d_yi, "limitup_count_10d": limitup_10d,
            "is_sector_leader": True, "filtered_at": now_cst.isoformat(),
        })

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    out_data = {"updated_at": now_cst.isoformat(), "count": len(qualified_leaders), "leaders": qualified_leaders}
    tmp_file = LEADER_FILE.with_suffix(".tmp")
    tmp_file.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_file.replace(LEADER_FILE)

    return qualified_leaders
