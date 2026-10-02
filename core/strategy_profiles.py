#!/usr/bin/env python3
"""
Astock 策略档案 — 从 notes/skills 提取的可编码策略模式。

每个 StrategyProfile 封装完整的 score/screen/regime/sell 逻辑，
可作为独立策略单元进行回测验证。

来源: /home/wade/workspace/ai/notes/skills/ (6 个策略文件)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable

from core.strategy import (
    REGIME_MAP,
    _sf,
    atr,
    get_regime,
    rsi,
    screen_candidates,
    sma,
)


# ═══════════════════════════════════════════════════════════════
# StrategyProfile 接口
# ═══════════════════════════════════════════════════════════════

@dataclass
class StrategyProfile:
    """策略档案 — 一个可独立回测的完整策略单元。"""
    name: str
    description: str
    source: str                     # "notes/skills/<file>.md"
    score_fn: Callable              # (bars, params) → {"score", "grade", "name", ...}
    screen_fn: Callable | None = None  # (bars_dict, date, params) → [symbols]
    regime_fn: Callable | None = None  # (index_bars, date) → regime
    sell_rules: dict = field(default_factory=lambda: dict(
        trail_trigger=3.0, trail_high_rate=0.25, trail_low_rate=0.35,
        trail_high_thresh=4.0, breakeven_peak=4.0, breakeven_thresh=0.3,
        weak_hold=2, weak_thresh=0.0, max_hold=5,
    ))
    default_params: dict = field(default_factory=dict)
    weight: float = 1.0             # 多策略组合时的权重


# ── 注册表 ──
_profile_registry: dict[str, StrategyProfile] = {}


def register_profile(profile: StrategyProfile) -> StrategyProfile:
    _profile_registry[profile.name] = profile
    return profile


def get_profile(name: str = "momentum_v5") -> StrategyProfile:
    if name not in _profile_registry:
        raise KeyError(f"Unknown profile '{name}'. Available: {list_profiles()}")
    return _profile_registry[name]


def list_profiles() -> list[str]:
    return list(_profile_registry.keys())


# ═══════════════════════════════════════════════════════════════
# Profile 1: momentum_v5 — 8 因子动量评分 (基线)
# ═══════════════════════════════════════════════════════════════

def _score_momentum_v5(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """基线 8 因子动量评分 (委托给 core.strategy.score_momentum_core)."""
    from core.strategy import score_momentum_core
    return score_momentum_core(bars, params)


register_profile(StrategyProfile(
    name="momentum_v5",
    description="8 因子动量评分: Volume/DH/MA/RSI/Chg/Volatility/NewHigh/Pullback",
    source="scripts/backtest_2yr.py (基线)",
    score_fn=_score_momentum_v5,
    screen_fn=screen_candidates,
    regime_fn=get_regime,
    default_params={
        "volume": 25, "dh": 20, "ma": 20, "rsi": 15, "chg": 15,
        "vol_bonus": 5, "new_high_bonus": 5, "pullback_bonus": 10,
        "target_pct": 8, "stop_pct": -2.8, "hold_days": 3,
        "min_vr": 0.8, "min_rs": 25, "ma_pct": 0.95,
    },
))


# ═══════════════════════════════════════════════════════════════
# Profile 2: single_yang — 单阳不破
# ═══════════════════════════════════════════════════════════════

def _score_single_yang(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """单阳不破: 大阳线后 2-9 天回调不破阳线中位。

    来源: stock-selection-methods.md
    条件:
        1. 最后一根阳线涨幅 >= 5%
        2. 大阳线后至今日未破大阳线实体中位
        3. 缩量回调
        4. MA20 方向向上
    """
    if len(bars) < 30:
        return {"score": 0, "grade": "D"}

    p = params or {}
    yang_gain = p.get("yang_gain", 5.0)
    max_bars = p.get("max_consolidation_bars", 9)
    score_weight = p.get("score_weight", 70)

    # 找到最近的大阳线 (涨幅 >= yang_gain%)
    yang_idx = None
    for i in range(len(bars) - 1, max(0, len(bars) - 30), -1):
        b = bars[i]
        chg = _sf(b.get("change_pct"))
        if chg >= yang_gain:
            yang_idx = i
            break

    if yang_idx is None:
        return {"score": 0, "grade": "D"}

    # 检查距今天数
    bars_since = len(bars) - 1 - yang_idx
    if bars_since > max_bars or bars_since < 1:
        return {"score": 0, "grade": "D"}

    # 大阳线实体中位
    yang_high = _sf(bars[yang_idx].get("close"))
    yang_low = _sf(bars[yang_idx].get("open"))
    if yang_high < yang_low:
        yang_high, yang_low = yang_low, yang_high
    midpoint = (yang_high + yang_low) / 2

    # 检查所有后续 K 线未破中位
    for i in range(yang_idx + 1, len(bars)):
        if _sf(bars[i].get("low")) < midpoint:
            return {"score": 0, "grade": "D"}

    # MA20 方向
    ma20_vals = [sma(bars[:i], "close", 20) for i in range(len(bars) - 10, len(bars))]
    ma20_up = ma20_vals[-1] > ma20_vals[0] if len(ma20_vals) >= 2 else False
    if not ma20_up:
        return {"score": 0, "grade": "D"}

    # 评分: 距离大阳线越近越高
    score = score_weight - (bars_since / max_bars) * 30
    close = _sf(bars[-1].get("close"))
    vol = _sf(bars[-1].get("volume"))
    avg_vol = sma(bars, "volume", 20)
    vr = vol / avg_vol if avg_vol > 0 else 0
    if vr < 0.9:
        score += 10  # 缩量加分

    score = min(score, 100)
    grade = "A" if score >= 65 else "B" if score >= 50 else "C" if score >= 35 else "D"
    return {"score": score, "grade": grade, "name": "single_yang",
            "target_pct": p.get("target_pct", 8), "stop_pct": p.get("stop_pct", -2.8),
            "hold_days": p.get("hold_days", 3), "atr_pct": atr(bars)}


register_profile(StrategyProfile(
    name="single_yang",
    description="单阳不破: 大阳线后 N 日回调不破中位 + MA20 向上",
    source="notes/skills/stock-selection-methods.md",
    score_fn=_score_single_yang,
    regime_fn=get_regime,
    default_params={"yang_gain": 5.0, "max_consolidation_bars": 9, "score_weight": 70},
))


# ═══════════════════════════════════════════════════════════════
# Profile 3: ma5_monster — MA5 捉妖战法
# ═══════════════════════════════════════════════════════════════

def _score_ma5_monster(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """MA5 捉妖: 3 连创新高 + 回踩 MA5 不破 + 缩量。

    来源: ma-system-strategies.md
    条件:
        1. 连续 3 日收盘创阶段新高并站稳 MA5
        2. 当前回踩 MA5 (收盘在 MA5 附近)
        3. 缩量
    """
    if len(bars) < 25:
        return {"score": 0, "grade": "D"}

    p = params or {}
    consecutive = p.get("consecutive_new_high", 3)

    close = _sf(bars[-1].get("close"))
    ma5 = sma(bars, "close", 5)
    ma20 = sma(bars, "close", 20)

    if close < ma5 * 0.98 or close < ma20:
        return {"score": 0, "grade": "D"}

    # 检查连续 N 日创新高
    highs = [_sf(b.get("high")) for b in bars[-consecutive - 5:-1]]
    recent_highs = [_sf(b.get("high")) for b in bars[-consecutive:]]
    for i in range(1, len(recent_highs)):
        if recent_highs[i] <= recent_highs[i - 1]:
            return {"score": 0, "grade": "D"}

    # 回踩 MA5: close 在 MA5 附近 ±2%
    near_ma5 = abs(close - ma5) / ma5 <= 0.02
    if not near_ma5:
        return {"score": 0, "grade": "D"}

    vol = _sf(bars[-1].get("volume"))
    avg_vol = sma(bars, "volume", 20)
    vr = vol / avg_vol if avg_vol > 0 else 0

    score = 60
    if vr < 0.8:
        score += 20
    elif vr < 1.2:
        score += 10

    # MA 多头排列加分
    ma10 = sma(bars, "close", 10)
    if ma5 > ma10 > ma20:
        score += 15

    score = min(score, 100)
    grade = "A" if score >= 65 else "B" if score >= 50 else "C" if score >= 35 else "D"
    return {"score": score, "grade": grade, "name": "ma5_monster",
            "target_pct": p.get("target_pct", 10), "stop_pct": p.get("stop_pct", -5.0),
            "hold_days": p.get("hold_days", 5), "atr_pct": atr(bars)}


register_profile(StrategyProfile(
    name="ma5_monster",
    description="MA5 捉妖: 3 连创新高 + 回踩 MA5 + 缩量",
    source="notes/skills/ma-system-strategies.md",
    score_fn=_score_ma5_monster,
    regime_fn=get_regime,
))


# ═══════════════════════════════════════════════════════════════
# Profile 4: old_duck — 经典老鸭头
# ═══════════════════════════════════════════════════════════════

def _score_old_duck(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """经典老鸭头: MA5 死叉→金叉 + 缩量 + MA30 支撑。

    来源: trend-and-limitup.md
    条件:
        1. MA5 必须先死叉 MA10，再金叉 MA10
        2. 死叉→金叉期间缩量
        3. MA30 未破
    """
    if len(bars) < 40:
        return {"score": 0, "grade": "D"}

    p = params or {}

    close = _sf(bars[-1].get("close"))
    ma5 = sma(bars, "close", 5)
    ma10 = sma(bars, "close", 10)
    ma30 = sma(bars, "close", 30)

    if close < ma30:
        return {"score": 0, "grade": "D"}

    # 搜索最近 30 根 K 线中 MA5 死叉 MA10 后再金叉
    cross_window = 30
    if len(bars) < cross_window:
        return {"score": 0, "grade": "D"}

    ma5_vals = [sma(bars[:i], "close", 5) for i in range(len(bars) - cross_window, len(bars))]
    ma10_vals = [sma(bars[:i], "close", 10) for i in range(len(bars) - cross_window, len(bars))]

    last_cross = None  # 0=unknown, 1=golden, -1=death
    found_death = False
    found_golden = False
    death_idx = None

    for i in range(1, len(ma5_vals)):
        if ma5_vals[i] is None or ma10_vals[i] is None:
            continue
        prev_5 = ma5_vals[i - 1]
        prev_10 = ma10_vals[i - 1]
        if prev_5 is None or prev_10 is None:
            continue
        curr_cross = 1 if ma5_vals[i] > ma10_vals[i] else -1
        if last_cross is not None and curr_cross != last_cross:
            if curr_cross == -1:
                found_death = True
                death_idx = i
            elif curr_cross == 1 and found_death:
                found_golden = True
                break
        last_cross = curr_cross

    if not found_death or not found_golden:
        return {"score": 0, "grade": "D"}

    # 死叉→金叉期间缩量检查
    if death_idx is not None:
        # 比较死叉附近均量和金叉附近均量
        vol_before = sma(bars[len(bars) - cross_window + death_idx - 5:len(bars) - cross_window + death_idx], "volume", 5) if death_idx >= 5 else 0
        vol_now = sma(bars, "volume", 5)
        if vol_before > 0 and vol_now > vol_before * 0.8:
            pass  # 缩量不严格

    score = 75
    score = min(score, 100)
    grade = "A" if score >= 65 else "B"
    return {"score": score, "grade": grade, "name": "old_duck",
            "target_pct": p.get("target_pct", 15), "stop_pct": p.get("stop_pct", -4.0),
            "hold_days": p.get("hold_days", 10), "atr_pct": atr(bars)}


register_profile(StrategyProfile(
    name="old_duck",
    description="经典老鸭头: MA5 死叉→金叉 + 缩量 + MA30 支撑",
    source="notes/skills/trend-and-limitup.md",
    score_fn=_score_old_duck,
    regime_fn=get_regime,
))


# ═══════════════════════════════════════════════════════════════
# Profile 5: fairy_guide — 仙人指路
# ═══════════════════════════════════════════════════════════════

def _score_fairy_guide(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """仙人指路: 长上影试探 + 第三日确认。

    来源: candlestick-patterns.md
    3 根 K 线形态:
        D1: 阳线实体 >= 5%
        D2: 长上影小实体
        D3 (今日): 确认阳线收盘 > D2 最高
    """
    if len(bars) < 5:
        return {"score": 0, "grade": "D"}

    p = params or {}
    d1 = bars[-3] if len(bars) >= 3 else None
    d2 = bars[-2] if len(bars) >= 2 else None
    d3 = bars[-1]

    if not d1 or not d2:
        return {"score": 0, "grade": "D"}

    # D1: 阳线实体 >= 5%
    d1_chg = _sf(d1.get("change_pct"))
    if d1_chg < 5:
        return {"score": 0, "grade": "D"}

    # D2: 长上影 (上影线 >= 实体 2 倍)
    d2_open = _sf(d2.get("open"))
    d2_close = _sf(d2.get("close"))
    d2_high = _sf(d2.get("high"))
    d2_low = _sf(d2.get("low"))
    d2_body = abs(d2_close - d2_open)
    d2_upper = d2_high - max(d2_open, d2_close)
    d2_lower = min(d2_open, d2_close) - d2_low
    if d2_upper < d2_body * 2 or d2_lower > d2_body * 0.5:
        return {"score": 0, "grade": "D"}

    # D3: 确认阳线收盘 > D2 最高
    d3_close = _sf(d3.get("close"))
    if d3_close <= d2_high:
        return {"score": 0, "grade": "D"}

    vol = _sf(d3.get("volume"))
    avg_vol = sma(bars, "volume", 20)
    vr = vol / avg_vol if avg_vol > 0 else 0

    score = 70
    if vr > 1.5:
        score += 15
    elif vr > 1.0:
        score += 5

    score = min(score, 100)
    grade = "A" if score >= 65 else "B"
    return {"score": score, "grade": grade, "name": "fairy_guide",
            "target_pct": p.get("target_pct", 10), "stop_pct": p.get("stop_pct", -3.0),
            "hold_days": p.get("hold_days", 5), "atr_pct": atr(bars)}


register_profile(StrategyProfile(
    name="fairy_guide",
    description="仙人指路: 长上影试探 + 第三日确认突破",
    source="notes/skills/candlestick-patterns.md",
    score_fn=_score_fairy_guide,
    regime_fn=get_regime,
))


# ═══════════════════════════════════════════════════════════════
# Profile 6: massive_volume — 巨量交易
# ═══════════════════════════════════════════════════════════════

def _score_massive_volume(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """巨量交易: 2-3x 均量 + 突破放量日高点。

    来源: volume-price-analysis.md + stock-selection-methods.md
    条件:
        1. 放量日 (2-3x 20日均量)
        2. 当前价格突破放量日最高价
    """
    if len(bars) < 25:
        return {"score": 0, "grade": "D"}

    p = params or {}
    vol_mult = p.get("vol_multiplier", 2.0)

    avg_vol = sma(bars, "volume", 20)
    if avg_vol <= 0:
        return {"score": 0, "grade": "D"}

    close = _sf(bars[-1].get("close"))

    # 找最近 20 根中的放量日
    vol_break_idx = None
    for i in range(len(bars) - 1, max(0, len(bars) - 25), -1):
        b = bars[i]
        v = _sf(b.get("volume"))
        vr = v / avg_vol if avg_vol > 0 else 0
        if vr >= vol_mult:
            vol_break_idx = i
            break

    if vol_break_idx is None:
        return {"score": 0, "grade": "D"}

    # 当前价格突破放量日最高
    break_high = _sf(bars[vol_break_idx].get("high"))
    if close <= break_high:
        return {"score": 0, "grade": "D"}

    vol = _sf(bars[-1].get("volume"))
    vr = vol / avg_vol if avg_vol > 0 else 0
    chg = _sf(bars[-1].get("change_pct"))

    score = 60
    if chg > 3:
        score += 15
    elif chg > 1:
        score += 5
    if vr > 1.2:
        score += 10

    score = min(score, 100)
    grade = "A" if score >= 65 else "B" if score >= 50 else "C"
    return {"score": score, "grade": grade, "name": "massive_vol",
            "target_pct": p.get("target_pct", 8), "stop_pct": p.get("stop_pct", -3.0),
            "hold_days": p.get("hold_days", 3), "atr_pct": atr(bars)}


register_profile(StrategyProfile(
    name="massive_volume",
    description="巨量交易: 2-3x 放量 + 突破放量日高点",
    source="notes/skills/volume-price-analysis.md",
    score_fn=_score_massive_volume,
    regime_fn=get_regime,
))


# ═══════════════════════════════════════════════════════════════
# Profile 7: golden_cross — 三线金叉
# ═══════════════════════════════════════════════════════════════

def _ema(data: list[float], period: int) -> list[float]:
    """Exponential Moving Average."""
    if not data:
        return []
    result = [data[0]]
    k = 2 / (period + 1)
    for v in data[1:]:
        result.append(result[-1] * (1 - k) + v * k)
    return result


def _macd(bars: list[dict]) -> tuple[list[float], list[float], list[float]]:
    """MACD(12,26,9): dif, dea, bar."""
    closes = [_sf(b.get("close")) for b in bars]
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    dif = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    dea = _ema(dif, 9)
    bar = [d - a for d, a in zip(dif, dea)]
    return dif, dea, bar


def _score_golden_cross(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """三线金叉: MA 金叉 + 量 MA 金叉 + MACD 金叉。

    来源: trend-and-limitup.md / candlestick-patterns.md
    """
    if len(bars) < 40:
        return {"score": 0, "grade": "D"}

    p = params or {}
    window = p.get("cross_window", 5)

    # MA 金叉检查: MA5 > MA10
    ma5 = sma(bars, "close", 5)
    ma10 = sma(bars, "close", 10)
    prev_ma5 = sma(bars[:-1], "close", 5)
    prev_ma10 = sma(bars[:-1], "close", 10)

    ma_cross = ma5 > ma10 and prev_ma5 <= prev_ma10

    # 量 MA 金叉
    vma5 = sma(bars, "volume", 5)
    vma10 = sma(bars, "volume", 10)
    prev_vma5 = sma(bars[:-1], "volume", 5) if len(bars) > 5 else 0
    prev_vma10 = sma(bars[:-1], "volume", 10) if len(bars) > 10 else 0

    vol_cross = vma5 > vma10 and prev_vma5 <= prev_vma10

    # MACD 金叉
    dif, dea, _ = _macd(bars)
    macd_cross = dif[-1] > dea[-1] and (len(dif) < 2 or dif[-2] <= dea[-2])

    crosses = sum([ma_cross, vol_cross, macd_cross])

    if crosses < 2:
        return {"score": 0, "grade": "D"}

    score = 40 + crosses * 15
    close = _sf(bars[-1].get("close"))
    ma20 = sma(bars, "close", 20)
    if close > ma20:
        score += 10

    score = min(score, 100)
    grade = "A" if score >= 65 else "B" if score >= 50 else "C"
    return {"score": score, "grade": grade, "name": "golden_cross",
            "target_pct": p.get("target_pct", 10), "stop_pct": p.get("stop_pct", -3.0),
            "hold_days": p.get("hold_days", 5), "atr_pct": atr(bars)}


register_profile(StrategyProfile(
    name="golden_cross",
    description="三线金叉: MA + 量 + MACD 三线金叉共振",
    source="notes/skills/trend-and-limitup.md / candlestick-patterns.md",
    score_fn=_score_golden_cross,
    regime_fn=get_regime,
))


# ═══════════════════════════════════════════════════════════════
# Profile 8: lotus — 出水芙蓉
# ═══════════════════════════════════════════════════════════════

def _score_lotus(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """出水芙蓉: 大阳线穿三线 (MA5/10/20) + 放量。

    来源: ma-system-strategies.md
    条件:
        1. 大阳线 (涨幅 >= 5%)
        2. 收盘价同时上穿 MA5/MA10/MA20
        3. 成交量 >= 2x 均量
    """
    if len(bars) < 25:
        return {"score": 0, "grade": "D"}

    p = params or {}
    min_gain = p.get("min_gain", 5.0)
    vol_mult = p.get("vol_multiplier", 2.0)

    last = bars[-1]
    close = _sf(last.get("close"))
    open_ = _sf(last.get("open"))
    chg = _sf(last.get("change_pct"))
    vol = _sf(last.get("volume"))

    if chg < min_gain or close <= open_:
        return {"score": 0, "grade": "D"}

    ma5 = sma(bars, "close", 5)
    ma10 = sma(bars, "close", 10)
    ma20 = sma(bars, "close", 20)

    # 收盘上穿三线
    if not (close > ma20 and close > ma10 and close > ma5):
        return {"score": 0, "grade": "D"}

    avg_vol = sma(bars, "volume", 20)
    vr = vol / avg_vol if avg_vol > 0 else 0
    if vr < vol_mult:
        return {"score": 0, "grade": "D"}

    score = 70
    if vr > 3:
        score += 15
    elif vr > 2:
        score += 5
    if chg > 7:
        score += 10

    score = min(score, 100)
    grade = "A" if score >= 65 else "B"
    return {"score": score, "grade": grade, "name": "lotus",
            "target_pct": p.get("target_pct", 10), "stop_pct": p.get("stop_pct", -4.0),
            "hold_days": p.get("hold_days", 5), "atr_pct": atr(bars)}


register_profile(StrategyProfile(
    name="lotus",
    description="出水芙蓉: 大阳线穿三线(MA5/10/20) + 放量2x+",
    source="notes/skills/ma-system-strategies.md",
    score_fn=_score_lotus,
    regime_fn=get_regime,
))


# ═══════════════════════════════════════════════════════════════
# Profile 9: momentum_breakout — 放量过顶
# ═══════════════════════════════════════════════════════════════

def _score_momentum_breakout(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """放量过顶: 突破前高 + 放量。

    来源: trend-and-limitup.md
    条件:
        1. 当前价突破 20 日最高价
        2. 放量 (VR >= 1.5)
        3. MA 多头排列
    """
    if len(bars) < 25:
        return {"score": 0, "grade": "D"}

    p = params or {}

    close = _sf(bars[-1].get("close"))
    vol = _sf(bars[-1].get("volume"))

    # 20 日最高价
    h20 = [_sf(b.get("high")) for b in bars[-20:]]
    hi20 = max(h20) if h20 else close

    if close < hi20 * 0.99:
        return {"score": 0, "grade": "D"}

    avg_vol = sma(bars, "volume", 20)
    vr = vol / avg_vol if avg_vol > 0 else 0
    if vr < 1.5:
        return {"score": 0, "grade": "D"}

    ma5 = sma(bars, "close", 5)
    ma10 = sma(bars, "close", 10)
    ma20 = sma(bars, "close", 20)

    score = 60
    if close > ma5 > ma10 > ma20:
        score += 20
    elif close > ma20:
        score += 10
    if vr > 2.5:
        score += 10
    elif vr > 2.0:
        score += 5

    chg = _sf(bars[-1].get("change_pct"))
    if chg > 5:
        score += 5

    score = min(score, 100)
    grade = "A" if score >= 65 else "B" if score >= 50 else "C"
    return {"score": score, "grade": grade, "name": "breakout",
            "target_pct": p.get("target_pct", 10), "stop_pct": p.get("stop_pct", -3.0),
            "hold_days": p.get("hold_days", 5), "atr_pct": atr(bars)}


register_profile(StrategyProfile(
    name="momentum_breakout",
    description="放量过顶: 突破 20 日高点 + 放量 1.5x+",
    source="notes/skills/trend-and-limitup.md",
    score_fn=_score_momentum_breakout,
    regime_fn=get_regime,
))


# ═══════════════════════════════════════════════════════════════
# Profile 10: ensemble_top3 — 多策略集成 (single_yang + lotus + ma5_monster)
# ═══════════════════════════════════════════════════════════════

def _score_ensemble_top3(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """集成 top 3 策略评分: 取最高分 + 多策略共振加分.

    运行 three profiles 各自评分，返回最佳结果.
    若多个 profile 同时选中，加共振分.
    """
    p = params or {}
    sub_scores = []
    sub_results = []

    for scorer in (_score_single_yang, _score_lotus, _score_ma5_monster):
        try:
            result = scorer(bars, p)
            sub_results.append(result)
            sub_scores.append(result.get("score", 0))
        except Exception:
            sub_scores.append(0)

    best_score = max(sub_scores)
    best_idx = sub_scores.index(best_score)
    best_result = sub_results[best_idx] if sub_results else {"score": 0, "grade": "D"}

    # 共振加分: 多个 profile 同时选中 (score >= threshold)
    threshold = p.get("ensemble_min_score", 50)
    confirmed = sum(1 for s in sub_scores if s >= threshold)
    if confirmed >= 2:
        best_result = dict(best_result)
        best_result["score"] = min(100, best_score + 10 * confirmed)
        best_result["grade"] = "A" if best_result["score"] >= 70 else "B"
        best_result["ensemble_confirmed"] = confirmed
        best_result["ensemble_profiles"] = [
            name for name, s in zip(["single_yang", "lotus", "ma5_monster"], sub_scores)
            if s >= threshold
        ]

    best_result["sub_scores"] = sub_scores
    return best_result


def _screen_ensemble_top3(bars_dict: dict, date: str, params: dict | None = None, **kwargs) -> list[str]:
    """集成筛选: 各子 profile 都用默认 screen_candidates，取并集去重.

    single_yang / lotus / ma5_monster 均无自定义 screen_fn，
    统一使用 shared_screen，不存在额外过滤差异，直接返回全量候选.
    """
    from core.strategy import screen_candidates as shared_screen
    return shared_screen(bars_dict, date, **kwargs)

    return sorted(candidates)


register_profile(StrategyProfile(
    name="ensemble_top3",
    description="多策略集成: single_yang + lotus + ma5_monster (共振加分)",
    source="core/strategy_profiles.py (auto-generated)",
    score_fn=_score_ensemble_top3,
    screen_fn=_screen_ensemble_top3,
    regime_fn=get_regime,
    sell_rules=dict(
        trail_trigger=3.0, trail_high_rate=0.25, trail_low_rate=0.35,
        trail_high_thresh=4.0, breakeven_peak=4.0, breakeven_thresh=0.3,
        weak_hold=2, weak_thresh=0.0, max_hold=5,
    ),
    default_params=dict(
        ensemble_min_score=50,
    ),
    weight=1.0,
))
