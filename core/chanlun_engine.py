#!/usr/bin/env python3
"""Deterministic Chan-structure and limit-up leader scoring primitives.

The implementation is intentionally auditable: every derived structure keeps source
bar indexes and numeric evidence. It is a conservative computational model, not a
claim that noisy OHLCV data can remove market uncertainty.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


def num(value: Any) -> float:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0.0


def normalize_bars(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        high = num(row.get("high", row.get("最高价")))
        low = num(row.get("low", row.get("最低价")))
        close = num(row.get("close", row.get("收盘价", row.get("最新价"))))
        open_ = num(row.get("open", row.get("开盘价", close)))
        volume = num(row.get("volume", row.get("成交量")))
        if high <= 0 or low <= 0 or close <= 0 or high < low:
            continue
        result.append({"index": index, "time": row.get("time", row.get("date", "")),
                       "open": open_ or close, "high": high, "low": low,
                       "close": close, "volume": volume})
    return result


def inclusion_process(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge adjacent contained bars; direction follows the last non-contained move."""
    merged: list[dict[str, Any]] = []
    direction = 1
    for bar in bars:
        if not merged:
            merged.append(dict(bar)); continue
        prev = merged[-1]
        contained = (bar["high"] <= prev["high"] and bar["low"] >= prev["low"]) or (prev["high"] <= bar["high"] and prev["low"] >= bar["low"])
        if not contained:
            direction = 1 if bar["high"] > prev["high"] and bar["low"] >= prev["low"] else -1 if bar["low"] < prev["low"] and bar["high"] <= prev["high"] else direction
            merged.append(dict(bar)); continue
        if direction >= 0:
            prev["high"] = max(prev["high"], bar["high"])
            prev["low"] = max(prev["low"], bar["low"])
        else:
            prev["high"] = min(prev["high"], bar["high"])
            prev["low"] = min(prev["low"], bar["low"])
        prev["close"] = bar["close"]
        prev["volume"] += bar["volume"]
        prev["end_index"] = bar["index"]
        prev["time"] = bar["time"]
    return merged


def fractals(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    points = []
    for i in range(1, len(bars) - 1):
        left, cur, right = bars[i - 1], bars[i], bars[i + 1]
        if cur["high"] >= left["high"] and cur["high"] >= right["high"] and (cur["high"] > left["high"] or cur["high"] > right["high"]):
            points.append({"kind": "top", "index": i, "price": cur["high"], "time": cur["time"]})
        elif cur["low"] <= left["low"] and cur["low"] <= right["low"] and (cur["low"] < left["low"] or cur["low"] < right["low"]):
            points.append({"kind": "bottom", "index": i, "price": cur["low"], "time": cur["time"]})
    return points


def strokes(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for point in points:
        if result and point["kind"] == result[-1]["kind"]:
            better = point["price"] > result[-1]["price"] if point["kind"] == "top" else point["price"] < result[-1]["price"]
            if better: result[-1] = point
            continue
        if result and point["index"] - result[-1]["index"] < 2:
            continue
        result.append(point)
    return [{"from": a["index"], "to": b["index"], "direction": "up" if b["price"] > a["price"] else "down", "start_price": a["price"], "end_price": b["price"]} for a, b in zip(result, result[1:])]


def segments(stroke_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for i in range(2, len(stroke_list)):
        group = stroke_list[i - 2:i + 1]
        direction = "up" if group[0]["start_price"] < group[-1]["end_price"] else "down"
        if sum(1 for s in group if s["direction"] == direction) >= 2:
            result.append({"from": group[0]["from"], "to": group[-1]["to"], "direction": direction,
                           "high": max(s["start_price"] for s in group) if direction == "down" else max(s["end_price"] for s in group),
                           "low": min(s["end_price"] for s in group) if direction == "up" else min(s["start_price"] for s in group)})
    return result


def pivots(stroke_list: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for i in range(len(stroke_list) - 2):
        group = stroke_list[i:i + 3]
        lows = [min(s["start_price"], s["end_price"]) for s in group]
        highs = [max(s["start_price"], s["end_price"]) for s in group]
        zd, zg = max(lows), min(highs)
        if zd < zg:
            result.append({"from": group[0]["from"], "to": group[-1]["to"], "zd": zd, "zg": zg,
                           "axis": (zd + zg) / 2, "width": zg - zd})
    return result


def ema(values: list[float], period: int) -> list[float]:
    if not values: return []
    alpha = 2 / (period + 1); result = [values[0]]
    for value in values[1:]: result.append(alpha * value + (1 - alpha) * result[-1])
    return result


def macd_strength(bars: list[dict[str, Any]]) -> list[float]:
    closes = [b["close"] for b in bars]
    fast, slow = ema(closes, 12), ema(closes, 26)
    dif = [a - b for a, b in zip(fast, slow)]
    dea = ema(dif, 9)
    return [(d - e) * 2 for d, e in zip(dif, dea)]


def divergence(bars: list[dict[str, Any]], points: list[dict[str, Any]]) -> dict[str, Any]:
    hist = macd_strength(bars)
    for kind, label in (("top", "top_divergence"), ("bottom", "bottom_divergence")):
        same = [p for p in points if p["kind"] == kind]
        if len(same) < 2: continue
        a, b = same[-2:]
        ha = sum(abs(x) for x in hist[a["index"]:b["index"] + 1])
        hb = sum(abs(x) for x in hist[b["index"]:])
        price_new = b["price"] > a["price"] if kind == "top" else b["price"] < a["price"]
        if price_new and hb < ha * 0.8:
            return {"status": "confirmed", "type": label, "first_index": a["index"], "second_index": b["index"], "prior_strength": ha, "latest_strength": hb}
    return {"status": "none", "type": "none"}


def trend_breakout_signal(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Detect a breakout/retest setup when limit-up compression hides pivots."""
    if len(bars) < 8:
        return {"status": "insufficient", "buy_point": None}
    closes = [b["close"] for b in bars]
    volumes = [b["volume"] for b in bars]
    alert = None
    for end in range(len(bars) - 1, 5, -1):
        start = max(0, end - 8)
        base = bars[start:end]
        if len(base) < 5:
            continue
        base_high = max(b["high"] for b in base)
        base_low = min(b["low"] for b in base)
        width = (base_high - base_low) / base_low if base_low else 1
        if width > 0.12:
            continue
        breakout = bars[end]
        avg_volume = sum(b["volume"] for b in base) / len(base)
        if breakout["close"] <= base_high or breakout["volume"] < avg_volume * 1.25:
            continue
        alert = {"status": "alert", "buy_point": None, "base_from": start, "base_to": end - 1,
                 "base_high": base_high, "base_low": base_low, "breakout_index": end,
                 "alert_price": breakout["close"], "breakout_volume": breakout["volume"]}
        retest = bars[end + 1:]
        if not retest:
            continue
        lowest = min(b["low"] for b in retest)
        latest = bars[-1]["close"]
        if lowest < base_high * 0.985 or latest <= base_high:
            continue
        return {"status": "confirmed", "buy_point": "二买", "base_from": start,
                "base_to": end - 1, "base_high": base_high, "base_low": base_low,
                "breakout_index": end, "confirmation_index": end + 1,
                "signal_age_bars": len(bars) - 1 - (end + 1),
                "breakout_price": breakout["close"],
                "breakout_alert": True, "alert_price": breakout["open"],
                "breakout_volume": breakout["volume"], "base_average_volume": avg_volume,
                "retest_low": lowest, "latest_close": latest}
    return alert or {"status": "none", "buy_point": None}


def analyze_chanlun(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    raw = normalize_bars(rows)
    merged = inclusion_process(raw)
    points = fractals(merged)
    stroke_list = strokes(points)
    segment_list = segments(stroke_list)
    pivot_list = pivots(stroke_list)
    div = divergence(merged, points)
    breakout = trend_breakout_signal(raw)
    last = merged[-1]["close"] if merged else 0
    current = "undetermined"
    buy = None; sell = None
    if pivot_list and len(stroke_list) >= 4:
        p = pivot_list[-1]
        prior = pivot_list[-2] if len(pivot_list) > 1 else None
        if last > p["zg"] and prior and last > prior["zg"]:
            current = "uptrend"
            if stroke_list[-1]["direction"] == "up" and len(merged) >= 5 and merged[-1]["low"] > p["zg"]:
                buy = "三买"
        elif last < p["zd"]:
            current = "downtrend"
            if div["type"] == "bottom_divergence": buy = "一买"
        else:
            current = "range"
            if div["type"] == "bottom_divergence": buy = "一买"
        if div["type"] == "top_divergence": sell = "一卖"
        if current == "downtrend" and prior and last < prior["zd"]: sell = "三卖"
    if buy is None and len(points) >= 3 and points[-1]["kind"] == "bottom":
        bottoms = [p for p in points if p["kind"] == "bottom"]
        if len(bottoms) >= 2 and bottoms[-1]["price"] > bottoms[-2]["price"] and current in {"uptrend", "range"}:
            buy = "二买"
    return {"bar_count": len(raw), "merged_bar_count": len(merged), "fractal_count": len(points),
            "stroke_count": len(stroke_list), "segment_count": len(segment_list), "pivot_count": len(pivot_list),
            "bars": merged, "fractals": points, "strokes": stroke_list, "segments": segment_list,
            "pivots": pivot_list, "divergence": div, "breakout_signal": breakout, "trend_type": current,
            "buy_point": buy or breakout.get("buy_point"), "sell_point": sell,
            "first_confirmed_breakout": breakout if breakout.get("status") == "confirmed" else None,
            "confirmed": bool(buy or sell or breakout.get("buy_point")) and bool(pivot_list or breakout.get("status") == "confirmed"),
            "evidence": {"last_close": last, "last_pivot": pivot_list[-1] if pivot_list else None,
                         "breakout": breakout}}


def leader_score(row: dict[str, Any], sector_count: int = 0, sector_rank: int = 99, continuity_days: int = 0) -> dict[str, Any]:
    """Score a limit-up row from 0-100; no score is a buy signal."""
    streak = max(0, num(row.get("limit_up_days", row.get("streak"))))
    amount = num(row.get("amount"))
    turnover = num(row.get("turnover"))
    score = min(30, streak * 10) + min(20, amount / 50_000_000 * 4) + min(15, sector_count * 3)
    score += 15 if sector_rank <= 3 else 8 if sector_rank <= 10 else 0
    score += min(10, continuity_days * 3) + (10 if 3 <= turnover <= 18 else 4 if turnover > 0 else 0)
    risk = []
    if turnover > 25: score -= 12; risk.append("excessive_turnover")
    if streak == 1 and sector_count < 3: score -= 10; risk.append("one_day_isolated")
    if amount < 50_000_000: score -= 10; risk.append("low_liquidity")
    score = max(0, min(100, round(score, 2)))
    classification = "main_uptrend_leader" if score >= 70 else "strong_watch" if score >= 55 else "observation_only"
    return {"leader_score": score, "leader_class": classification, "score_components": {"streak": min(30, streak * 10), "amount": min(20, amount / 50_000_000 * 4), "breadth": min(15, sector_count * 3), "sector_rank": 15 if sector_rank <= 3 else 8 if sector_rank <= 10 else 0, "continuity": min(10, continuity_days * 3), "turnover_quality": 10 if 3 <= turnover <= 18 else 4 if turnover > 0 else 0}, "leader_risks": risk}


def analyze_from_mcp(symbol: str, period: str = "D", count: int = 200) -> dict[str, Any]:
    """Fetch klines from MCP and run full chanlun analysis."""
    from mcp_client import get_mcp_client
    client = get_mcp_client()
    klines = client.fetch_klines(symbol, period, count)
    return analyze_chanlun(klines)


if __name__ == "__main__":
    # Test with synthetic data
    test_bars = [
        {"time": f"2026-01-{d:02d}", "open": 10 + i * 0.1, "high": 11 + i * 0.2,
         "low": 9 + i * 0.05, "close": 10.5 + i * 0.15, "volume": 1000000 + i * 10000}
        for i, d in enumerate(range(1, 31), 1)
    ]
    result = analyze_chanlun(test_bars)
    print(f"Chanlun analysis: {result['bar_count']} bars → {result['pivot_count']} pivots")
    print(f"Trend: {result['trend_type']}, Buy: {result['buy_point']}, Sell: {result['sell_point']}")
    print(f"Confirmed: {result['confirmed']}")
