#!/usr/bin/env python3
"""Test chanlun engine with synthetic data."""
from __future__ import annotations

from core.chanlun_engine import (
    normalize_bars,
    inclusion_process,
    fractals,
    strokes,
    pivots,
    divergence,
    trend_breakout_signal,
    analyze_chanlun,
    leader_score,
)


def _make_bar(
    time: str = "2026-01-01",
    open: float = 10.0,  # noqa: A002
    high: float = 11.0,
    low: float = 9.0,
    close: float = 10.5,
    volume: int = 1_000_000,
    index: int = 0,
) -> dict:
    return {"time": time, "open": open, "high": high, "low": low, "close": close, "volume": volume, "index": index}


def _uptrend_bars(n: int = 30) -> list[dict]:
    """Synthetic data with realistic zigzag for chanlun detection."""
    import math
    bars = []
    for i in range(n):
        # oscillating sine wave on top of gentle uptrend
        cycle = math.sin(i * 0.5) * 2
        base = 10 + i * 0.08 + cycle * 0.3
        bars.append({
            "index": i, "time": f"2026-01-{(i%30)+1:02d}",
            "open": round(base - 0.1, 2), "high": round(base + 0.5, 2),
            "low": round(base - 0.4, 2), "close": round(base + 0.1, 2),
            "volume": 1_000_000 + int(cycle * 100_000),
        })
    return bars


# ── normalize_bars ──


def test_normalize_bars_standard_input() -> None:
    """Standard dict input with English keys."""
    bars = [{"time": "2026-01-01", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100}]
    result = normalize_bars(bars)
    assert len(result) == 1, "Should normalize one bar"
    assert result[0]["high"] == 11
    assert result[0]["close"] == 10.5
    assert result[0]["volume"] == 100


def test_normalize_bars_chinese_keys() -> None:
    """Chinese column names."""
    bars = [{"date": "2026-01-01", "开盘价": 10, "最高价": 11, "最低价": 9, "收盘价": 10.5, "成交量": 200}]
    result = normalize_bars(bars)
    assert len(result) == 1
    assert result[0]["high"] == 11
    assert result[0]["close"] == 10.5
    assert result[0]["volume"] == 200


def test_normalize_bars_invalid_high_low() -> None:
    """Bar with high < low should be skipped."""
    bars = [{"time": "2026-01-01", "open": 10, "high": 8, "low": 9, "close": 8.5, "volume": 100}]
    result = normalize_bars(bars)
    assert len(result) == 0, "Invalid bar should be filtered"


def test_normalize_bars_non_dict_rows() -> None:
    """Iterable with non-dict items should be skipped."""
    bars: list = [{"time": "2026-01-01", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100}, None, "string"]
    result = normalize_bars(bars)
    assert len(result) == 1


# ── inclusion_process ──


def test_inclusion_process_contained_bars() -> None:
    """Mutually contained bars should merge into one."""
    bars = [
        _make_bar(time="day1", high=12, low=8, index=0),
        _make_bar(time="day2", high=11, low=9, index=1),   # contained within day1
        _make_bar(time="day3", high=13, low=7, index=2),   # contains previous merged bar
    ]
    result = inclusion_process(bars)
    # day2 is contained in day1, direction up → expand high/low upward
    # day3 contains merged(day1+day2), direction up → expand high upward
    assert len(result) == 1, "All 3 bars should merge into one"
    assert result[0]["high"] == 13, "Merged high should be max"


def test_inclusion_process_no_containment() -> None:
    """No contained bars should pass through unchanged."""
    bars = [
        _make_bar(time="day1", high=10, low=8, index=0),
        _make_bar(time="day2", high=12, low=9, index=1),
        _make_bar(time="day3", high=14, low=10, index=2),
    ]
    result = inclusion_process(bars)
    assert len(result) == 3


# ── fractals ──


def test_fractals_top_detection() -> None:
    """Detect a top fractal at the middle bar."""
    bars = [
        _make_bar(high=10, low=8, index=0),
        _make_bar(high=15, low=9, index=1),  # top
        _make_bar(high=12, low=9, index=2),
    ]
    points = fractals(bars)
    tops = [p for p in points if p["kind"] == "top"]
    assert len(tops) == 1
    assert tops[0]["price"] == 15


def test_fractals_bottom_detection() -> None:
    """Detect a bottom fractal at the middle bar."""
    bars = [
        _make_bar(high=10, low=8, index=0),
        _make_bar(high=9, low=5, index=1),   # bottom
        _make_bar(high=10, low=7, index=2),
    ]
    points = fractals(bars)
    bottoms = [p for p in points if p["kind"] == "bottom"]
    assert len(bottoms) == 1
    assert bottoms[0]["price"] == 5


def test_fractals_insufficient_bars() -> None:
    """Less than 3 bars returns no fractals."""
    bars = [_make_bar(index=0), _make_bar(index=1)]
    points = fractals(bars)
    assert len(points) == 0


# ── strokes ──


def test_strokes_direction_up() -> None:
    """Upward stroke detection."""
    points = [
        {"kind": "bottom", "index": 0, "price": 10},
        {"kind": "top", "index": 5, "price": 15},
    ]
    stroke_list = strokes(points)
    assert len(stroke_list) == 1
    assert stroke_list[0]["direction"] == "up"


def test_strokes_direction_down() -> None:
    """Downward stroke detection."""
    points = [
        {"kind": "top", "index": 0, "price": 15},
        {"kind": "bottom", "index": 5, "price": 10},
    ]
    stroke_list = strokes(points)
    assert len(stroke_list) == 1
    assert stroke_list[0]["direction"] == "down"


# ── analyze_chanlun ──


def test_analyze_chanlun_full_pipeline() -> None:
    """Full pipeline returns expected structure."""
    bars = _uptrend_bars(30)
    result = analyze_chanlun(bars)
    assert isinstance(result, dict)
    assert result["bar_count"] == 30
    assert result["merged_bar_count"] >= 20
    assert result["fractal_count"] >= 2
    assert result["stroke_count"] >= 1
    assert "pivots" in result
    assert "divergence" in result
    assert "breakout_signal" in result
    assert result["trend_type"] in {"uptrend", "downtrend", "range", "undetermined"}
    assert "confirmed" in result


def test_analyze_chanlun_empty_input() -> None:
    """Empty input returns minimal structure."""
    result = analyze_chanlun([])
    assert result["bar_count"] == 0
    assert result["trend_type"] == "undetermined"
    assert result["confirmed"] is False


# ── leader_score ──


def test_leader_score_boundaries() -> None:
    """Score is clamped to [0, 100]."""
    row = {"limit_up_days": 10, "amount": 1_000_000_000, "turnover": 5}
    score = leader_score(row, sector_count=20, sector_rank=1, continuity_days=10)
    assert 0 <= score["leader_score"] <= 100
    assert score["leader_class"] in {"main_uptrend_leader", "strong_watch", "observation_only"}


def test_leader_score_minimum() -> None:
    """Very weak stock scores near 0."""
    row = {"limit_up_days": 0, "amount": 10_000_000, "turnover": 40}
    score = leader_score(row)
    assert score["leader_score"] == 0
    assert score["leader_class"] == "observation_only"


def test_leader_score_high_streak() -> None:
    """High streak contributes to score."""
    row = {"limit_up_days": 7, "amount": 500_000_000, "turnover": 10}
    score = leader_score(row, sector_count=10, sector_rank=1, continuity_days=5)
    assert score["leader_score"] >= 50
    assert score["leader_risks"] == []


def test_leader_score_risk_detection() -> None:
    """Risk flags are populated for excessive turnover."""
    row = {"limit_up_days": 1, "amount": 30_000_000, "turnover": 30}
    score = leader_score(row, sector_count=1, sector_rank=20)
    assert "excessive_turnover" in score["leader_risks"]


# ── divergence ──


def test_divergence_no_points() -> None:
    """No divergence with fewer than 2 same-kind points."""
    bars = _uptrend_bars(10)
    div = divergence(bars, [])
    assert div["status"] == "none"
    assert div["type"] == "none"


# ── trend_breakout_signal ──


def test_trend_breakout_insufficient_bars() -> None:
    """Fewer than 8 bars returns insufficient."""
    bars = [_make_bar(index=i) for i in range(5)]
    signal = trend_breakout_signal(bars)
    assert signal["status"] == "insufficient"
