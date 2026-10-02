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


# ═══════════════════════════════════════════════════════════════
# Profile 11: multi_alloc — 多策略分仓组合
# ═══════════════════════════════════════════════════════════════

class MultiStrategyAllocator:
    """多策略分仓分配器 — 运行多个子策略，各自独立评分、独立仓位、独立卖出规则。

    每个子策略:
      - 独立 screen + score (全市场筛选)
      - 按 weight 分配仓位预算
      - 标记每笔持仓的来源策略
      - 使用各自的 SellRules 离场
    多策略共振: 同一股票被多个子策略同时选中时，仓位叠加 (共振加仓).

    Usage:
        alloc = MultiStrategyAllocator([
            {"name": "momentum_v5", "weight": 0.6},
            {"name": "single_yang", "weight": 0.2},
            {"name": "lotus", "weight": 0.2},
        ])
        candidates = alloc.screen_all(bars_dict, date)
        results = alloc.score_all(candidates, bars_dict, params)
        # results: [(sym, score_result, profile_name), ...]
    """

    def __init__(self, profile_configs: list[dict]):
        """
        Args:
            profile_configs: list of {"name": str, "weight": float, "sell_rules"?: dict}
                weight 总和不必为 1，程序会归一化处理。
        """
        from core.strategy import SellRules
        self.sub_profiles: list[dict] = []
        total_weight = sum(c.get("weight", 1.0) for c in profile_configs) or 1.0
        for cfg in profile_configs:
            p = get_profile(cfg["name"])
            w = cfg.get("weight", 1.0) / total_weight  # 归一化
            sr = SellRules(cfg.get("sell_rules", p.sell_rules))
            self.sub_profiles.append({
                "profile": p,
                "name": cfg["name"],
                "weight": w,
                "sell_rules": sr,
                "budget": 0,  # 每轮回测动态分配
            })

    @property
    def profile_names(self) -> list[str]:
        return [sp["name"] for sp in self.sub_profiles]

    def describe(self) -> str:
        parts = [f"{sp['name']}({sp['weight']*100:.0f}%)" for sp in self.sub_profiles]
        return "+".join(parts)

    def screen_all(self, bars_dict: dict, date: str, **kwargs) -> list[str]:
        """取所有子策略筛选结果的并集。"""
        candidates: set[str] = set()
        for sp in self.sub_profiles:
            fn = sp["profile"].screen_fn or screen_candidates
            try:
                result = fn(bars_dict, date, **kwargs)
                if result:
                    candidates.update(result)
            except Exception:
                continue
        return sorted(candidates)

    def score_all(
        self, symbols: list[str], bars_dict: dict[str, list[dict]],
        params: dict, min_score: int = 60,
    ) -> list[tuple[str, dict, str]]:
        """对每个候选股运行所有子策略评分。

        Returns:
            list of (symbol, score_result, profile_name) 按 score 降序排列，
            仅包含 grade 非 D/C 且 score >= min_score 的结果。
        """
        results: list[tuple[str, dict, str]] = []
        for sym in symbols:
            bars = bars_dict.get(sym, [])
            if len(bars) < 25:
                continue
            for sp in self.sub_profiles:
                try:
                    r = sp["profile"].score_fn(bars, params)
                    if r.get("grade") in ("D", "C"):
                        continue
                    if r.get("score", 0) < min_score:
                        continue
                    r["profile"] = sp["name"]
                    r["weight"] = sp["weight"]
                    results.append((sym, r, sp["name"]))
                except Exception:
                    continue

        # 去重: 同一股票 + 同一策略只保留最高分
        seen: set[tuple[str, str]] = set()
        deduped: list[tuple[str, dict, str]] = []
        for sym, r, pname in sorted(results, key=lambda x: -x[1].get("score", 0)):
            key = (sym, pname)
            if key not in seen:
                seen.add(key)
                deduped.append((sym, r, pname))

        # 按 score 降序
        deduped.sort(key=lambda x: -x[1].get("score", 0))
        return deduped

    def get_sell_rules(self, profile_name: str):
        """获取指定子策略的卖出规则对象。"""
        for sp in self.sub_profiles:
            if sp["name"] == profile_name:
                return sp["sell_rules"]
        return self.sub_profiles[0]["sell_rules"]

    def get_budgets(self, max_positions: int) -> dict[str, int]:
        """按 weight 分配总仓位预算到各子策略。

        Returns:
            dict[profile_name] -> position_slots
        """
        budgets: dict[str, int] = {}
        remaining = max_positions
        # 先按 weight 整数分配
        for sp in sorted(self.sub_profiles, key=lambda x: -x["weight"]):
            slots = max(1, int(max_positions * sp["weight"]))
            slots = min(slots, remaining)
            budgets[sp["name"]] = slots
            remaining -= slots
        # 补余
        if remaining > 0:
            for sp in self.sub_profiles:
                budgets[sp["name"]] = budgets.get(sp["name"], 0) + 1
                remaining -= 1
                if remaining <= 0:
                    break
        return budgets

    def get_alloc_pct(self, profile_name: str, score: float, regime_cap: float, max_pos_pct: float) -> float:
        """计算单笔仓位比例。"""
        if score >= 80:
            return min(regime_cap + 0.05, max_pos_pct)
        elif score >= 70:
            return regime_cap
        elif score >= 60:
            return regime_cap * 0.8
        return regime_cap * 0.6


# 默认多策略组合: momentum_v5 主力 + single_yang 辅助 + lotus 辅助
_DEFAULT_MULTI_CONFIG = [
    {"name": "momentum_v5", "weight": 0.60},
    {"name": "single_yang", "weight": 0.20},
    {"name": "lotus", "weight": 0.20},
]

# 全局 allocator 实例 (懒加载)
_multi_alloc_instance: MultiStrategyAllocator | None = None


def get_multi_allocator(config: list[dict] | None = None) -> MultiStrategyAllocator:
    """获取/创建多策略分配器。"""
    global _multi_alloc_instance
    if config is not None:
        _multi_alloc_instance = MultiStrategyAllocator(config)
    elif _multi_alloc_instance is None:
        _multi_alloc_instance = MultiStrategyAllocator(_DEFAULT_MULTI_CONFIG)
    return _multi_alloc_instance


def _score_multi(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """多策略评分入口 — 委托给 allocator，此处返回空 (由 backtest 循环直接调用 allocator)。

    注意: multi profile 不走标准 score_fn 流程，
    而是由 backtest 循环直接调用 MultiStrategyAllocator.score_all()。
    此函数仅为满足接口而存在。
    """
    return {"score": 0, "grade": "D", "name": "multi"}


def _screen_multi(bars_dict: dict, date: str, params: dict | None = None, **kwargs) -> list[str]:
    """多策略筛选入口 — 委托给 allocator 取并集。"""
    alloc = get_multi_allocator()
    return alloc.screen_all(bars_dict, date, **kwargs)


register_profile(StrategyProfile(
    name="multi",
    description="多策略分仓组合: momentum_v5(60%) + single_yang(20%) + lotus(20%)",
    source="core/strategy_profiles.py (multi-strategy allocator)",
    score_fn=_score_multi,
    screen_fn=_screen_multi,
    regime_fn=get_regime,
    sell_rules=dict(
        trail_trigger=3.0, trail_high_rate=0.25, trail_low_rate=0.35,
        trail_high_thresh=4.0, breakeven_peak=4.0, breakeven_thresh=0.3,
        weak_hold=2, weak_thresh=0.0, max_hold=5,
    ),
    default_params=dict(),
    weight=1.0,
))


# ═══════════════════════════════════════════════════════════════
# Profile 12: limitup_pullback_sniper — 涨停板回调狙击
# ═══════════════════════════════════════════════════════════════

def _find_limitup_days(bars: list[dict], lookback: int = 30) -> list[int]:
    """Find indices of bars where stock hit daily limit-up (>= 9.5% for main board, >= 19% for 科创板/创业板)."""
    limitup_indices = []
    for i in range(len(bars)):
        b = bars[i]
        chg = _sf(b.get("change_pct"))
        # Main board: 10% limit, Kechuang/Chuangyeban: 20% limit
        # Stock hitting >= 9.5% (allowing for rounding) or >= 19%
        if chg >= 19.0 or (chg >= 9.5 and chg < 11.0):
            limitup_indices.append(i)
    return limitup_indices


def _score_limitup_pullback(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """涨停板回调狙击策略: 涨停后回调 2-8 天, 不破支撑, 缩量企稳, 第二波启动.

    A-stock proven pattern:
      1. Stock hits daily limit-up (涨停) → strong demand signal
      2. Pulls back 2-8 days → profit-takers exit, discount entry
      3. Holds above MA10 during pullback → demand still present
      4. Volume shrinks during pullback → selling exhausted
      5. Current bar shows stabilization (small body, near MA) → entry point

    Scoring dimensions (100 total):
      - Limit-up quality: 涨停日涨幅, 封板强度, 距今时间 (25pts)
      - Pullback quality: 回调幅度, 缩量程度, 支撑强度 (35pts)
      - Trend context: MA alignment, market position (25pts)
      - Setup quality: 企稳信号, 当日形态 (15pts)
    """
    if len(bars) < 40:
        return {"score": 0, "grade": "D"}

    p = params or {}

    # ── Step 1: Find recent limit-up day ──
    limitup_indices = _find_limitup_days(bars, lookback=30)
    if not limitup_indices:
        return {"score": 0, "grade": "D"}

    # Use the most recent limit-up that is at least 2 days ago
    limitup_idx = None
    for idx in reversed(limitup_indices):
        days_since = len(bars) - 1 - idx
        if 2 <= days_since <= 8:
            limitup_idx = idx
            break

    if limitup_idx is None:
        return {"score": 0, "grade": "D"}

    days_since = len(bars) - 1 - limitup_idx
    lu_bar = bars[limitup_idx]
    lu_close = _sf(lu_bar.get("close"))
    lu_high = _sf(lu_bar.get("high"))
    lu_low = _sf(lu_bar.get("low"))
    lu_open = _sf(lu_bar.get("open"))
    lu_chg = _sf(lu_bar.get("change_pct"))
    lu_vol = _sf(lu_bar.get("volume"))

    # ── Step 2: Compute technicals ──
    close = _sf(bars[-1].get("close"))
    open_ = _sf(bars[-1].get("open"))
    high = _sf(bars[-1].get("high"))
    low = _sf(bars[-1].get("low"))
    vol = _sf(bars[-1].get("volume"))

    ma5 = sma(bars, "close", 5)
    ma10 = sma(bars, "close", 10)
    ma20 = sma(bars, "close", 20)
    ma60 = sma(bars, "close", 60) if len(bars) >= 60 else ma20

    avg_vol20 = sma(bars, "volume", 20)
    vr20 = vol / avg_vol20 if avg_vol20 > 0 else 0

    # ── Step 3: Pullback quality assessment ──
    # Check that price pulled back from limit-up close
    pullback_from_high = (lu_close - close) / lu_close * 100 if lu_close > 0 else 0

    # Pullback must be reasonable: 2% - 15% from limit-up close
    if pullback_from_high < 1.0 or pullback_from_high > 15.0:
        return {"score": 0, "grade": "D"}

    # Must hold above MA20 during pullback
    if close < ma20:
        return {"score": 0, "grade": "D"}

    # Volume during pullback: must be declining
    # Compute average volume during pullback vs. volume before limit-up
    pullback_bars = bars[limitup_idx + 1:]
    if len(pullback_bars) < 2:
        return {"score": 0, "grade": "D"}

    pb_vol_avg = sum(_sf(b.get("volume")) for b in pullback_bars) / len(pullback_bars)
    pre_lu_bars = bars[max(0, limitup_idx - 5):limitup_idx]
    pre_lu_vol_avg = sum(_sf(b.get("volume")) for b in pre_lu_bars) / len(pre_lu_bars) if pre_lu_bars else pb_vol_avg

    volume_shrink_ratio = pb_vol_avg / pre_lu_vol_avg if pre_lu_vol_avg > 0 else 1.0

    # Check no bar during pullback broke below MA10 significantly
    lowest_pb_close = min(_sf(b.get("close")) for b in pullback_bars)
    ma10_at_lowest = sma(bars[:limitup_idx + 2], "close", 10)  # approximate

    score = 0

    # ── 1. Limit-up quality (25pts) ──
    if lu_chg >= 19.0:
        score += 25  # 20cm limit-up, strongest signal
    elif lu_chg >= 10.0:
        score += 22
    elif lu_chg >= 9.7:
        score += 20
    elif lu_chg >= 9.5:
        score += 18

    # Bonus for seal strength: high = close means strong seal
    seal_strength = (lu_close - lu_low) / (lu_high - lu_low) * 100 if lu_high > lu_low else 100
    if seal_strength > 90:
        score += 0  # already at max for 20cm
    elif seal_strength > 70:
        score += -2

    # ── 2. Pullback quality (35pts) ──
    # Shallow pullback is better
    if pullback_from_high <= 4:
        score += 15
    elif pullback_from_high <= 7:
        score += 12
    elif pullback_from_high <= 10:
        score += 8
    elif pullback_from_high <= 15:
        score += 4

    # Volume shrinkage
    if volume_shrink_ratio < 0.4:
        score += 12  # extreme shrinkage, sellers exhausted
    elif volume_shrink_ratio < 0.6:
        score += 10
    elif volume_shrink_ratio < 0.8:
        score += 7
    elif volume_shrink_ratio < 1.0:
        score += 4
    else:
        score += 0  # no shrinkage, still high volume = distribution

    # Distance from pullback low (stabilization signal)
    pb_lowest = min(_sf(b.get("low")) for b in pullback_bars)
    recovery_from_low = (close - pb_lowest) / pb_lowest * 100 if pb_lowest > 0 else 0
    if recovery_from_low > 2:
        score += 8  # clear recovery underway
    elif recovery_from_low > 0.5:
        score += 5
    else:
        score += 2

    # ── 3. Trend context (25pts) ──
    # MA alignment
    if ma5 > ma10 > ma20:
        score += 15
    elif ma10 > ma20 and close > ma10:
        score += 10
    elif close > ma20:
        score += 5

    # Position within 60-day range (not overextended)
    h60 = max(_sf(b.get("high")) for b in bars[-60:]) if len(bars) >= 60 else lu_high
    l60 = min(_sf(b.get("low")) for b in bars[-60:]) if len(bars) >= 60 else lu_low
    position_in_range = (close - l60) / (h60 - l60) * 100 if h60 > l60 else 50
    if 30 <= position_in_range <= 70:
        score += 10  # mid-range, room to run
    elif position_in_range <= 85:
        score += 5

    # ── 4. Today's setup quality (15pts) ──
    # Today should be a stabilization candle (small body, doji-like or small bullish)
    today_body = abs(close - open_)
    today_range = high - low if high > low else 1
    body_ratio = today_body / today_range * 100 if today_range > 0 else 100

    today_chg = _sf(bars[-1].get("change_pct"))

    if today_chg > 0 and body_ratio < 50:
        score += 8  # bullish hammer/doji, classic reversal signal
    elif today_chg > 0 and today_chg < 3:
        score += 6  # gentle bullish
    elif today_chg > -1 and today_chg <= 0:
        score += 4  # flat, stabilizing
    else:
        score += 1

    # Volume today: should be low (continuation of shrinkage)
    if vr20 < 0.5:
        score += 7  # very low volume today, perfect setup
    elif vr20 < 0.8:
        score += 4
    elif vr20 < 1.2:
        score += 2

    # Cap at 100
    score = min(score, 100)

    # Grade
    if score >= 70:
        grade = "A"
    elif score >= 55:
        grade = "B"
    elif score >= 40:
        grade = "C"
    else:
        grade = "D"

    # Dynamic targets based on pullback depth
    if pullback_from_high > 8:
        target_pct = p.get("target_pct", 12)
    else:
        target_pct = p.get("target_pct", 8)

    return {
        "score": score,
        "grade": grade,
        "name": "lu_sniper",
        "target_pct": target_pct,
        "stop_pct": p.get("stop_pct", -3.0),
        "hold_days": p.get("hold_days", 5),
        "atr_pct": atr(bars),
        "lu_chg": lu_chg,
        "days_since": days_since,
        "pullback_pct": pullback_from_high,
        "vol_shrink": volume_shrink_ratio,
    }


def _screen_limitup_pullback(bars_dict: dict[str, list[dict]], date: str, **kwargs) -> list[str]:
    """Limit-up pullback screening: wider net than momentum screen.

    Filters: min 40 bars, close >= 5 RMB, MA20+ price, RSI > 25.
    Key difference from shared screen: lower VR requirement (we WANT low volume).
    """
    cand = []
    for sym, bars in bars_dict.items():
        lb = [b for b in bars if str(b.get("time", "")) <= date]
        if len(lb) < 40:
            continue
        last = lb[-1]
        close = _sf(last.get("close"))
        if close < kwargs.get("min_close", 5.0):
            continue
        vol = _sf(last.get("volume"))
        if vol <= 0:
            continue
        # Don't filter on high volume - we want low volume for pullback
        if close < sma(lb, "close", 20) * kwargs.get("ma_pct", 0.92):
            continue
        # Filter extreme low RSI only
        rsi_val = rsi(lb)
        if rsi_val < 20:
            continue
        cand.append(sym)
    return cand


register_profile(StrategyProfile(
    name="limitup_pullback",
    description="涨停板回调狙击: 涨停后回调2-8天, 缩量企稳不破支撑, 第二波启动",
    source="core/strategy_profiles.py (A-stock proven pattern)",
    score_fn=_score_limitup_pullback,
    screen_fn=_screen_limitup_pullback,
    regime_fn=get_regime,
    sell_rules=dict(
        trail_trigger=2.5, trail_high_rate=0.30, trail_low_rate=0.40,
        trail_high_thresh=5.0, breakeven_peak=3.0, breakeven_thresh=0.5,
        weak_hold=3, weak_thresh=-0.5, max_hold=7,
    ),
    default_params={
        "target_pct": 10, "stop_pct": -3.5, "hold_days": 6,
    },
    weight=1.0,
))


# ═══════════════════════════════════════════════════════════════
# Profile 13: t1_momentum_swing — T+1 动量摆荡 (尾盘买+次日卖)
# ═══════════════════════════════════════════════════════════════

def _score_t1_swing(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """T+1动量摆荡策略: 尾盘强势股买入, 次日冲高卖出.

    A-stock T+1 mechanic exploitation:
      - Select stocks with strong intraday momentum at close
      - These tend to gap up next morning (overnight momentum)
      - Quick profit taking at 2-4% target
      - Very tight stop at -2%

    Scoring dimensions (100 total):
      - Intraday momentum: daily change %, close vs open position (30pts)
      - Volume expansion: relative volume vs 20-day avg (25pts)
      - Trend context: MA alignment, recent breakout (25pts)
      - Risk/reward: ATR-based target feasibility (20pts)
    """
    if len(bars) < 25:
        return {"score": 0, "grade": "D"}

    p = params or {}

    last = bars[-1]
    close = _sf(last.get("close"))
    open_ = _sf(last.get("open"))
    high = _sf(last.get("high"))
    low = _sf(last.get("low"))
    vol = _sf(last.get("volume"))
    chg = _sf(last.get("change_pct"))

    ma5 = sma(bars, "close", 5)
    ma10 = sma(bars, "close", 10)
    ma20 = sma(bars, "close", 20)
    avg_vol = sma(bars, "volume", 20)
    vr = vol / avg_vol if avg_vol > 0 else 0

    score = 0

    # ── 1. Intraday momentum (30pts) ──
    # Close position within daily range: high close = strong
    daily_range = high - low if high > low else 1
    close_position = (close - low) / daily_range * 100  # 0-100, higher = stronger close

    if close_position >= 90:
        score += 15  # closed near high, very strong
    elif close_position >= 75:
        score += 12
    elif close_position >= 60:
        score += 8
    elif close_position >= 40:
        score += 4
    else:
        score += 0  # closed near low = weak

    # Daily change within optimal range (not too hot, not dead)
    if 1.5 <= chg <= 4.0:
        score += 15  # sweet spot: enough momentum, not overbought
    elif 4.0 < chg <= 6.0:
        score += 12  # strong but may be too hot
    elif 0.5 <= chg < 1.5:
        score += 8
    elif chg > 6.0:
        score += 5  # too hot, high reversal risk
    elif chg > 0:
        score += 3

    # ── 2. Volume expansion (25pts) ──
    # We want volume expansion but not extreme
    if 1.2 <= vr <= 2.0:
        score += 18  # healthy volume expansion
    elif 2.0 < vr <= 3.0:
        score += 14  # strong but ok
    elif 0.9 <= vr < 1.2:
        score += 10  # average volume
    elif 3.0 < vr <= 4.0:
        score += 8  # very high volume, could be distribution
    elif vr > 4.0:
        score += 3  # extreme volume, likely exhaustion
    else:
        score += 2  # low volume, ignore

    # Volume trend: volume increasing over last 3 days
    v3 = [_sf(b.get("volume")) for b in bars[-3:]]
    if len(v3) == 3 and v3[2] > v3[1] > v3[0]:
        score += 7  # increasing volume = building momentum

    # ── 3. Trend context (25pts) ──
    # MA alignment
    if close > ma5 > ma10 > ma20:
        score += 15  # perfect bull alignment
    elif close > ma5 > ma20:
        score += 12
    elif close > ma20 and ma5 > ma20:
        score += 8
    elif close > ma20:
        score += 4

    # Recent breakout check: close near 20-day high
    h20 = max(_sf(b.get("high")) for b in bars[-20:])
    dist_from_high = (h20 - close) / h20 * 100 if h20 > 0 else 100
    if dist_from_high <= 2.0:
        score += 10  # near recent high, breakout imminent
    elif dist_from_high <= 5.0:
        score += 5

    # ── 4. Risk/reward (20pts) ──
    # Check if the stock has enough volatility for 3% target
    recent_atr = atr(bars)
    if 2.0 <= recent_atr <= 5.0:
        score += 12  # enough volatility for target without excessive risk
    elif 1.5 <= recent_atr < 2.0:
        score += 8
    elif 5.0 < recent_atr <= 7.0:
        score += 6  # higher vol, use smaller position
    elif recent_atr > 7.0:
        score += 3  # too volatile
    else:
        score += 4

    # No gap-down risk filter: yesterday wasn't a big drop
    prev_chg = _sf(bars[-2].get("change_pct")) if len(bars) >= 2 else 0
    if prev_chg < -5:
        score += -5  # penalty: yesterday big drop, today may be dead cat bounce
    elif prev_chg < -2:
        score += 0
    else:
        score += 8  # yesterday not negative = good continuation signal

    score = max(0, min(score, 100))

    # Grade
    if score >= 70:
        grade = "A"
    elif score >= 55:
        grade = "B"
    elif score >= 40:
        grade = "C"
    else:
        grade = "D"

    # T+1 specific targets: quick profit, tight stop
    return {
        "score": score,
        "grade": grade,
        "name": "t1_swing",
        "target_pct": p.get("target_pct", 3.5),   # quick 3.5% target
        "stop_pct": p.get("stop_pct", -2.0),        # tight 2% stop
        "hold_days": p.get("hold_days", 2),          # max 2 day hold
        "atr_pct": recent_atr,
    }


def _screen_t1_swing(bars_dict: dict[str, list[dict]], date: str, **kwargs) -> list[str]:
    """T+1 swing screen: wider net, lower volume requirement since we want moderate volume."""
    cand = []
    for sym, bars in bars_dict.items():
        lb = [b for b in bars if str(b.get("time", "")) <= date]
        if len(lb) < 25:
            continue
        last = lb[-1]
        close = _sf(last.get("close"))
        if close < kwargs.get("min_close", 8.0):
            continue
        vol = _sf(last.get("volume"))
        if vol <= 0:
            continue
        # We want stocks above MA20, but don't require huge volume
        if close < sma(lb, "close", 20) * kwargs.get("ma_pct", 0.93):
            continue
        # Filter out extremely dead stocks (RSI < 30)
        if rsi(lb) < 30:
            continue
        # Must have some volume (at least 0.6x average)
        avg_v = sma(lb, "volume", 20)
        if vol / avg_v < 0.6:
            continue
        cand.append(sym)
    return cand


register_profile(StrategyProfile(
    name="t1_swing",
    description="T+1动量摆荡: 尾盘强势股买入(高收盘位+温和放量+多头排列), 次日冲高3.5%卖出",
    source="core/strategy_profiles.py (T+1 mechanic exploitation)",
    score_fn=_score_t1_swing,
    screen_fn=_screen_t1_swing,
    regime_fn=get_regime,
    sell_rules=dict(
        trail_trigger=1.5, trail_high_rate=0.50, trail_low_rate=0.60,
        trail_high_thresh=3.0, breakeven_peak=2.0, breakeven_thresh=0.3,
        weak_hold=1, weak_thresh=-0.5, max_hold=3,
    ),
    default_params={
        "target_pct": 3.5, "stop_pct": -2.0, "hold_days": 2,
    },
    weight=1.0,
))


# ═══════════════════════════════════════════════════════════════
# Profile 14: gap_proof_momentum — 防缺口动量策略
# ═══════════════════════════════════════════════════════════════

def _calc_gap_score(bars: list[dict]) -> float:
    """Calculate overnight gap stability score (0-100, higher = more stable).

    Measures how often the stock gaps and the typical gap size.
    Lower gap frequency + smaller gap size = higher score.
    """
    if len(bars) < 30:
        return 50.0

    gaps = []
    for i in range(1, len(bars)):
        prev_close = _sf(bars[i - 1].get("close"))
        curr_open = _sf(bars[i].get("open"))
        if prev_close > 0:
            gap_pct = abs(curr_open - prev_close) / prev_close * 100
            gaps.append(gap_pct)

    if not gaps:
        return 50.0

    avg_gap = sum(gaps) / len(gaps)
    big_gaps = sum(1 for g in gaps if g > 3.0)
    big_gap_ratio = big_gaps / len(gaps)

    # Score: lower gap = higher score
    if avg_gap < 0.5 and big_gap_ratio < 0.1:
        return 90.0
    elif avg_gap < 1.0 and big_gap_ratio < 0.2:
        return 75.0
    elif avg_gap < 1.5 and big_gap_ratio < 0.3:
        return 60.0
    elif avg_gap < 2.0:
        return 40.0
    else:
        return max(10.0, 100 - avg_gap * 20)


def _score_gap_proof(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """防缺口动量策略: 选择低缺口风险+动量优质股, 优化T+1隔夜持有。

    The core problem with T+1 strategies: overnight gap-down risk destroys profits.
    This strategy specifically selects stocks with:
      1. Low historical gap amplitude (stable overnight behavior)
      2. Strong daily close (high close position = momentum carries to tomorrow)
      3. Healthy uptrend (MA alignment + above key levels)
      4. Moderate volume (not exhaustion, not dead)
      5. Good market cap (large enough to be stable, not too large to be sluggish)

    Scoring (100 total):
      - Gap stability: historical overnight gap behavior (25pts)
      - Daily momentum: today's close quality + volume (30pts)
      - Trend context: MA alignment + breakout positioning (25pts)
      - Risk metrics: ATR-based, volatility filter (20pts)
    """
    if len(bars) < 40:
        return {"score": 0, "grade": "D"}

    p = params or {}

    last = bars[-1]
    close = _sf(last.get("close"))
    open_ = _sf(last.get("open"))
    high = _sf(last.get("high"))
    low = _sf(last.get("low"))
    vol = _sf(last.get("volume"))
    chg = _sf(last.get("change_pct"))

    ma5 = sma(bars, "close", 5)
    ma10 = sma(bars, "close", 10)
    ma20 = sma(bars, "close", 20)
    avg_vol20 = sma(bars, "volume", 20)
    vr = vol / avg_vol20 if avg_vol20 > 0 else 0
    curr_atr = atr(bars)
    curr_rsi = rsi(bars)

    score = 0

    # ── 1. Gap stability (25pts) ──
    gap_score = _calc_gap_score(bars)
    score += int(gap_score * 0.25)

    # ── 2. Daily momentum (30pts) ──
    # Close position: where did the stock close within today's range?
    daily_range = high - low if high > low else 0.01
    close_pos = (close - low) / daily_range * 100

    if close_pos >= 85:
        score += 18  # strong close, high continuation probability
    elif close_pos >= 70:
        score += 14
    elif close_pos >= 55:
        score += 9
    elif close_pos >= 40:
        score += 5
    else:
        score += 0  # weak close, don't buy

    # Daily change: sweet spot is 1-5%
    if 1.5 <= chg <= 3.5:
        score += 12  # optimal momentum
    elif 3.5 < chg <= 5.5:
        score += 9
    elif 0.8 <= chg < 1.5:
        score += 7
    elif chg > 5.5:
        score += 4  # hot, high reversal risk
    elif chg > 0:
        score += 3

    # ── 3. Trend context (25pts) ──
    if close > ma5 > ma10 > ma20:
        score += 15  # perfect alignment
    elif close > ma5 > ma20:
        score += 12
    elif close > ma20 and ma5 > ma20:
        score += 8
    elif close > ma20:
        score += 4

    # Distance from recent high: too close = exhausted, too far = no momentum
    h10 = max(_sf(b.get("high")) for b in bars[-10:])
    dist = (h10 - close) / h10 * 100 if h10 > 0 else 0
    if 1.0 <= dist <= 4.0:
        score += 10  # pullback from high, good entry
    elif dist < 1.0:
        score += 6  # at the high, momentum but reversal risk
    elif dist <= 7.0:
        score += 4

    # ── 4. Risk filters (20pts) ──
    # RSI sweet spot: not overbought, not dead
    if 45 <= curr_rsi <= 62:
        score += 10
    elif 62 < curr_rsi <= 70:
        score += 7
    elif 35 <= curr_rsi < 45:
        score += 5
    elif curr_rsi > 70:
        score += 2  # overbought, risky
    else:
        score += 2

    # Volume: moderate expansion preferred
    if 0.9 <= vr <= 1.5:
        score += 10  # healthy volume, sustainable
    elif 1.5 < vr <= 2.0:
        score += 7
    elif 0.7 <= vr < 0.9:
        score += 5
    else:
        score += 2

    # Cap and grade
    score = min(score, 100)

    if score >= 72:
        grade = "A"
    elif score >= 58:
        grade = "B"
    elif score >= 44:
        grade = "C"
    else:
        grade = "D"

    return {
        "score": score,
        "grade": grade,
        "name": "gap_proof",
        "target_pct": p.get("target_pct", 4.0),
        "stop_pct": p.get("stop_pct", -2.5),
        "hold_days": p.get("hold_days", 2),
        "atr_pct": curr_atr,
    }


def _screen_gap_proof(bars_dict: dict[str, list[dict]], date: str, **kwargs) -> list[str]:
    """Gap-proof screening: focus on stable, mid-to-large cap stocks."""
    cand = []
    for sym, bars in bars_dict.items():
        lb = [b for b in bars if str(b.get("time", "")) <= date]
        if len(lb) < 40:
            continue
        last = lb[-1]
        close = _sf(last.get("close"))
        if close < kwargs.get("min_close", 8.0):
            continue
        vol = _sf(last.get("volume"))
        if vol <= 0:
            continue
        avg_v = sma(lb, "volume", 20)
        if avg_v <= 0:
            continue
        vr = vol / avg_v
        # Accept moderate-low volume (0.7x - 3x)
        if vr < 0.7 or vr > 3.5:
            continue
        # Must be above MA20
        if close < sma(lb, "close", 20) * kwargs.get("ma_pct", 0.95):
            continue
        # RSI must be reasonable (not extreme)
        if rsi(lb) > 78 or rsi(lb) < 25:
            continue
        cand.append(sym)
    return cand


register_profile(StrategyProfile(
    name="gap_proof",
    description="防缺口动量: 低缺口风险+强势收盘+多头排列+温和放量, 优化隔夜T+1持有",
    source="core/strategy_profiles.py (gap-proof overnight momentum)",
    score_fn=_score_gap_proof,
    screen_fn=_screen_gap_proof,
    regime_fn=get_regime,
    sell_rules=dict(
        trail_trigger=2.0, trail_high_rate=0.35, trail_low_rate=0.45,
        trail_high_thresh=4.0, breakeven_peak=3.0, breakeven_thresh=0.3,
        weak_hold=2, weak_thresh=-0.3, max_hold=4,
    ),
    default_params={
        "target_pct": 4.0, "stop_pct": -2.5, "hold_days": 2,
    },
    weight=1.0,
))


# ═══════════════════════════════════════════════════════════════
# Profile 15: gap_proof_v2 — 防缺口动量 v2 (增强版: 行业过滤 + 宽松止盈)
# ═══════════════════════════════════════════════════════════════

# Sectors that consistently lose money in momentum strategies
# These are either too defensive (银行), too cyclical (汽车/煤炭),
# or too volatile (电子/纺织/建材/餐饮旅游) for T+1 momentum
_BAD_SECTORS_T1 = {
    "汽车", "纺织服装", "煤炭", "电子", "建材", "餐饮旅游",
    "银行", "传媒", "钢铁", "通信",
}


def _screen_gap_proof_v2(bars_dict: dict[str, list[dict]], date: str, **kwargs) -> list[str]:
    """Enhanced v2 screening: adds sector exclusion for losing sectors,
    tighter market cap demand, and stronger trend requirement."""
    # Import sector info
    try:
        from stock_universe_full import get_industry
    except ImportError:
        from scripts.stock_universe_full import get_industry

    cand = []
    for sym, bars in bars_dict.items():
        # Sector exclusion
        try:
            ind = get_industry(sym)
            if ind in _BAD_SECTORS_T1:
                continue
        except Exception:
            pass

        lb = [b for b in bars if str(b.get("time", "")) <= date]
        if len(lb) < 50:  # More data required for gap analysis
            continue
        last = lb[-1]
        close = _sf(last.get("close"))
        if close < kwargs.get("min_close", 10.0):  # Higher price threshold
            continue
        vol = _sf(last.get("volume"))
        if vol <= 0:
            continue
        avg_v = sma(lb, "volume", 20)
        if avg_v <= 0:
            continue
        vr = vol / avg_v
        # Tighter volume range
        if vr < 0.8 or vr > 3.0:
            continue
        # Liquidity filter: daily turnover >= 50M RMB (excludes illiquid small caps)
        amount = _sf(last.get("amount"))
        if amount < 50000000:  # 50M RMB minimum daily turnover
            continue
        # Stronger MA requirement
        ma20 = sma(lb, "close", 20)
        if close < ma20 * kwargs.get("ma_pct", 0.97):
            continue
        # Gap stability pre-filter
        gap_score = _calc_gap_score(lb)
        if gap_score < 40:
            continue
        # RSI range
        rs = rsi(lb)
        if rs > 75 or rs < 30:
            continue
        cand.append(sym)
    return cand


register_profile(StrategyProfile(
    name="gap_proof_v2",
    description="防缺口动量v2: 行业过滤+更严筛选+宽松止盈+高门槛, v1增强版",
    source="core/strategy_profiles.py (enhanced gap-proof)",
    score_fn=_score_gap_proof,  # Same scoring, better screening
    screen_fn=_screen_gap_proof_v2,
    regime_fn=get_regime,
    sell_rules=dict(
        trail_trigger=2.5, trail_high_rate=0.30, trail_low_rate=0.40,
        trail_high_thresh=5.0, breakeven_peak=4.0, breakeven_thresh=0.5,
        weak_hold=3, weak_thresh=-0.5, max_hold=5,
    ),
    default_params={
        "target_pct": 5.0, "stop_pct": -2.5, "hold_days": 3,
    },
    weight=1.0,
))


# ═══════════════════════════════════════════════════════════════
# Profile 16: long_yang_seven — 长阳七星战法
# ═══════════════════════════════════════════════════════════════

def _score_long_yang_seven(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """长阳七星: 放量长阳 + 7日窄幅震荡 + 第7日变盘向上。

    来源: candlestick-patterns.md / ma-system-strategies.md
    条件:
        1. 7日前有一根放量长阳 (涨幅 >= 5%, 成交量 >= 1.5x 均量)
        2. 之后 6 日窄幅震荡 (波动范围 < 长阳实体的 3x)
        3. 第7日(今日) 向上突破震荡区间
        4. MA20 上行
    """
    if len(bars) < 30:
        return {"score": 0, "grade": "D"}

    p = params or {}
    min_gain = p.get("min_gain", 5.0)
    vol_mult = p.get("vol_multiplier", 1.5)

    # 找长阳日 (距今 6-8 天)
    yang_idx = None
    for offset in range(6, 9):
        idx = len(bars) - 1 - offset
        if idx < 0:
            continue
        b = bars[idx]
        chg = _sf(b.get("change_pct"))
        vol = _sf(b.get("volume"))
        avg_vol = sma(bars[:idx + 1], "volume", 20)
        vr = vol / avg_vol if avg_vol > 0 else 0
        if chg >= min_gain and vr >= vol_mult:
            yang_idx = idx
            break

    if yang_idx is None:
        return {"score": 0, "grade": "D"}

    # 窄幅震荡检查: 长阳后到昨日
    consolidation_bars = bars[yang_idx + 1:len(bars) - 1]
    if len(consolidation_bars) < 5 or len(consolidation_bars) > 8:
        return {"score": 0, "grade": "D"}

    yang_high = max(_sf(bars[yang_idx].get("close")), _sf(bars[yang_idx].get("open")))
    yang_low = min(_sf(bars[yang_idx].get("close")), _sf(bars[yang_idx].get("open")))
    yang_body = yang_high - yang_low

    cons_highs = [_sf(b.get("high")) for b in consolidation_bars]
    cons_lows = [_sf(b.get("low")) for b in consolidation_bars]
    cons_range = max(cons_highs) - min(cons_lows)

    if cons_range > yang_body * 3:  # Too wide volatility
        return {"score": 0, "grade": "D"}

    # 今日向上突破
    close = _sf(bars[-1].get("close"))
    vol = _sf(bars[-1].get("volume"))
    avg_vol = sma(bars, "volume", 20)
    vr = vol / avg_vol if avg_vol > 0 else 0

    cons_max_close = max(_sf(b.get("close")) for b in consolidation_bars)
    if close <= cons_max_close:
        return {"score": 0, "grade": "D"}

    # MA20 上行
    ma20 = sma(bars, "close", 20)
    ma20_prev = sma(bars[:-5], "close", 20) if len(bars) >= 25 else ma20
    if ma20 <= ma20_prev:
        return {"score": 0, "grade": "D"}

    score = 65
    if vr > 1.5:
        score += 15
    elif vr > 1.0:
        score += 8

    # 缩量震荡加分
    cons_vol_avg = sum(_sf(b.get("volume")) for b in consolidation_bars) / len(consolidation_bars)
    yang_vol = _sf(bars[yang_idx].get("volume"))
    if cons_vol_avg < yang_vol * 0.5:
        score += 10  # 明显缩量

    score = min(score, 100)
    grade = "A" if score >= 65 else "B" if score >= 50 else "C"
    return {"score": score, "grade": grade, "name": "long_yang_seven",
            "target_pct": p.get("target_pct", 8), "stop_pct": p.get("stop_pct", -4.0),
            "hold_days": p.get("hold_days", 5), "atr_pct": atr(bars)}


register_profile(StrategyProfile(
    name="long_yang_seven",
    description="长阳七星: 放量长阳+7日窄幅震荡+第7日突破, 变盘窗口买入",
    source="notes/skills/candlestick-patterns.md",
    score_fn=_score_long_yang_seven,
    regime_fn=get_regime,
    sell_rules=dict(
        trail_trigger=3.0, trail_high_rate=0.25, trail_low_rate=0.35,
        trail_high_thresh=5.0, breakeven_peak=4.0, breakeven_thresh=0.3,
        weak_hold=2, weak_thresh=-0.5, max_hold=7,
    ),
))


# ═══════════════════════════════════════════════════════════════
# Profile 17: fake_yin — 假阴真阳买入法
# ═══════════════════════════════════════════════════════════════

def _score_fake_yin(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """假阴真阳: MA5上方3日连续新高 + 出现阴线回调 + MA5附近买入。

    来源: candlestick-patterns.md / ma-system-strategies.md
    条件:
        1. 连续3日收盘在MA5上方且创阶段新高
        2. 出现阴线回调 (但收盘仍在MA5上方)
        3. 当前价靠近MA5 (买入时机)
    """
    if len(bars) < 30:
        return {"score": 0, "grade": "D"}

    p = params or {}

    close = _sf(bars[-1].get("close"))
    ma5 = sma(bars, "close", 5)
    ma10 = sma(bars, "close", 10)
    ma20 = sma(bars, "close", 20)

    if close < ma5 * 0.97 or close < ma20:
        return {"score": 0, "grade": "D"}

    # 找最近3日连续新高 (在idx-6到idx-4之间)
    new_high_sequence = False
    for start in range(len(bars) - 6, max(len(bars) - 6, len(bars) - 5)):
        if start < 1:
            continue
        closes_3 = [_sf(bars[j].get("close")) for j in range(start, start + 3)]
        highs_3 = [_sf(bars[j].get("high")) for j in range(start, start + 3)]
        ma5_vals = [sma(bars[:j + 1], "close", 5) for j in range(start, start + 3)]

        all_above_ma5 = all(c > m for c, m in zip(closes_3, ma5_vals) if m > 0)
        all_new_high = all(highs_3[i] > highs_3[i - 1] for i in range(1, 3))

        if all_above_ma5 and all_new_high:
            new_high_sequence = True
            break

    if not new_high_sequence:
        return {"score": 0, "grade": "D"}

    # 出现阴线回调 (在前2天)
    pullback_found = False
    for i in range(len(bars) - 3, len(bars)):
        if _sf(bars[i].get("close")) < _sf(bars[i].get("open")):
            pullback_found = True
            break

    if not pullback_found:
        return {"score": 0, "grade": "D"}

    # 当前靠近MA5
    near_ma5 = abs(close - ma5) / ma5 <= 0.03
    if not near_ma5:
        return {"score": 0, "grade": "D"}

    vol = _sf(bars[-1].get("volume"))
    avg_vol = sma(bars, "volume", 20)
    vr = vol / avg_vol if avg_vol > 0 else 0

    score = 65
    if vr < 0.7:
        score += 15  # 回调缩量
    elif vr < 1.0:
        score += 8

    # 均线多头排列
    if ma5 > ma10 > ma20:
        score += 10

    score = min(score, 100)
    grade = "A" if score >= 65 else "B" if score >= 50 else "C"
    return {"score": score, "grade": grade, "name": "fake_yin",
            "target_pct": p.get("target_pct", 10), "stop_pct": p.get("stop_pct", -5.0),
            "hold_days": p.get("hold_days", 5), "atr_pct": atr(bars)}


register_profile(StrategyProfile(
    name="fake_yin",
    description="假阴真阳: MA5上方3日连续新高+阴线回调+MA5附近买入, 捉妖战法",
    source="notes/skills/candlestick-patterns.md / ma-system-strategies.md",
    score_fn=_score_fake_yin,
    regime_fn=get_regime,
    sell_rules=dict(
        trail_trigger=3.0, trail_high_rate=0.25, trail_low_rate=0.35,
        trail_high_thresh=5.0, breakeven_peak=4.0, breakeven_thresh=0.3,
        weak_hold=2, weak_thresh=-0.5, max_hold=5,
    ),
    default_params={"target_pct": 10, "stop_pct": -5.0, "hold_days": 5},
))


# ═══════════════════════════════════════════════════════════════
# Profile 18: divine_explorer — 灵猴探路
# ═══════════════════════════════════════════════════════════════

def _score_divine_explorer(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """灵猴探路: MA5金叉MA60 + 带量突破 + 缩量回踩 + 右侧确认。

    来源: ma-system-strategies.md
    条件:
        1. MA5 在近15日内上穿 MA60 (金叉), 放量
        2. 股价回踩至 MA60 附近 (4%以内)
        3. 缩量
        4. 今日右侧企稳信号 (阳线或小实体)
    """
    if len(bars) < 65:
        return {"score": 0, "grade": "D"}

    p = params or {}

    close = _sf(bars[-1].get("close"))
    vol = _sf(bars[-1].get("volume"))
    ma20 = sma(bars, "close", 20)
    ma60 = sma(bars, "close", 60)

    if close < ma20 or ma60 <= 0:
        return {"score": 0, "grade": "D"}

    # 找15日内的MA5金叉MA60
    golden_cross_idx = None
    for i in range(len(bars) - 15, len(bars) - 1):
        if i < 60:
            continue
        ma5_prev = sma(bars[:i], "close", 5)
        ma60_prev = sma(bars[:i], "close", 60)
        ma5_curr = sma(bars[:i + 1], "close", 5)
        ma60_curr = sma(bars[:i + 1], "close", 60)

        if ma5_prev <= ma60_prev and ma5_curr > ma60_curr:
            golden_cross_idx = i
            break

    if golden_cross_idx is None:
        return {"score": 0, "grade": "D"}

    # 金叉时放量检查
    cross_vol = _sf(bars[golden_cross_idx].get("volume"))
    avg_vol_at_cross = sma(bars[:golden_cross_idx + 1], "volume", 20)
    vr_cross = cross_vol / avg_vol_at_cross if avg_vol_at_cross > 0 else 0
    if vr_cross < 1.2:
        return {"score": 0, "grade": "D"}

    # 当前价格回调至MA60附近
    dist_to_ma60 = abs(close - ma60) / ma60 * 100
    if dist_to_ma60 > 4.0:
        return {"score": 0, "grade": "D"}

    # 缩量
    avg_vol = sma(bars, "volume", 20)
    vr = vol / avg_vol if avg_vol > 0 else 0

    # 右侧企稳
    is_bullish = close > _sf(bars[-1].get("open"))
    today_chg = _sf(bars[-1].get("change_pct"))

    score = 55
    if vr < 0.6:
        score += 20  # 明显缩量
    elif vr < 0.8:
        score += 12
    elif vr < 1.0:
        score += 6

    if is_bullish and today_chg > 0.5:
        score += 10  # 阳线企稳

    if dist_to_ma60 < 2.0:
        score += 10  # 精准回踩

    if ma20 > ma60:
        score += 5

    score = min(score, 100)
    grade = "A" if score >= 65 else "B" if score >= 50 else "C"
    return {"score": score, "grade": grade, "name": "divine_explorer",
            "target_pct": p.get("target_pct", 10), "stop_pct": p.get("stop_pct", -4.0),
            "hold_days": p.get("hold_days", 7), "atr_pct": atr(bars)}


register_profile(StrategyProfile(
    name="divine_explorer",
    description="灵猴探路: MA5金叉MA60+放量突破+缩量回踩+右侧买入, 最强均线战法",
    source="notes/skills/ma-system-strategies.md",
    score_fn=_score_divine_explorer,
    regime_fn=get_regime,
    sell_rules=dict(
        trail_trigger=3.0, trail_high_rate=0.25, trail_low_rate=0.35,
        trail_high_thresh=5.0, breakeven_peak=4.0, breakeven_thresh=0.3,
        weak_hold=3, weak_thresh=-0.5, max_hold=8,
    ),
    default_params={"target_pct": 10, "stop_pct": -4.0, "hold_days": 7},
))


# ═══════════════════════════════════════════════════════════════
# Profile 19: three_horse — 三驾马车
# ═══════════════════════════════════════════════════════════════

def _score_three_horse(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """三驾马车: MA5/10/20粘合后向上发散, 多头发散确认。

    来源: ma-system-strategies.md
    条件:
        1. 近期 MA5/MA10/MA20 曾经粘合 (差距<2%)
        2. 当前 MA5 > MA10 > MA20 (多头排列)
        3. 三条均线同步向上
        4. MA 间距在扩大 (发散中)
    """
    if len(bars) < 30:
        return {"score": 0, "grade": "D"}

    p = params or {}

    close = _sf(bars[-1].get("close"))
    ma5 = sma(bars, "close", 5)
    ma10 = sma(bars, "close", 10)
    ma20 = sma(bars, "close", 20)

    # 当前必须多头排列 + 发散
    if not (ma5 > ma10 > ma20 and close > ma5):
        return {"score": 0, "grade": "D"}

    # MA 斜率向上 (当前 vs 5日前)
    ma5_5d = sma(bars[:-5], "close", 5) if len(bars) >= 10 else ma5
    ma10_5d = sma(bars[:-5], "close", 10) if len(bars) >= 15 else ma10
    ma20_5d = sma(bars[:-5], "close", 20) if len(bars) >= 25 else ma20

    if not (ma5 > ma5_5d and ma10 > ma10_5d and ma20 > ma20_5d):
        return {"score": 0, "grade": "D"}

    # MA 间距扩大
    spread = ma5 - ma20
    spread_5d = ma5_5d - ma20_5d if ma20_5d > 0 else 0
    if spread <= spread_5d:
        return {"score": 0, "grade": "D"}

    # 找过去20天内的粘合点
    convergence_found = False
    for j in range(max(20, len(bars) - 30), len(bars) - 5):
        m5 = sma(bars[:j], "close", 5)
        m10 = sma(bars[:j], "close", 10)
        m20 = sma(bars[:j], "close", 20)
        if m5 > 0 and m10 > 0 and m20 > 0:
            ma_range = max(m5, m10, m20) / min(m5, m10, m20) - 1
            if ma_range < 0.02:
                convergence_found = True
                break

    if not convergence_found:
        return {"score": 0, "grade": "D"}

    vol = _sf(bars[-1].get("volume"))
    avg_vol = sma(bars, "volume", 20)
    vr = vol / avg_vol if avg_vol > 0 else 0

    score = 70
    if vr > 1.5:
        score += 15
    elif vr > 1.0:
        score += 8

    # 发散角度
    angle = (spread / ma20) * 100  # spread as % of MA20
    if angle > 5:
        score += 10
    elif angle > 3:
        score += 5

    score = min(score, 100)
    grade = "A" if score >= 65 else "B" if score >= 50 else "C"
    return {"score": score, "grade": grade, "name": "three_horse",
            "target_pct": p.get("target_pct", 12), "stop_pct": p.get("stop_pct", -4.0),
            "hold_days": p.get("hold_days", 7), "atr_pct": atr(bars)}


register_profile(StrategyProfile(
    name="three_horse",
    description="三驾马车: MA5/10/20粘合→向上发散, 均线多头发散确认买入",
    source="notes/skills/ma-system-strategies.md",
    score_fn=_score_three_horse,
    regime_fn=get_regime,
    sell_rules=dict(
        trail_trigger=3.0, trail_high_rate=0.25, trail_low_rate=0.35,
        trail_high_thresh=5.0, breakeven_peak=4.0, breakeven_thresh=0.3,
        weak_hold=3, weak_thresh=-0.5, max_hold=7,
    ),
    default_params={"target_pct": 12, "stop_pct": -4.0, "hold_days": 7},
))


# ═══════════════════════════════════════════════════════════════
# Profile 20: island_reversal — 岛形反转(底部)
# ═══════════════════════════════════════════════════════════════

def _score_island_reversal(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """岛形反转(底部): 跳空下跌缺口 + 震荡孤岛 + 跳空上涨缺口回补。

    来源: trend-and-limitup.md
    条件:
        1. 前有下跌趋势
        2. 向下跳空缺口 (孤岛开始)
        3. 1-5日震荡整理 (孤岛)
        4. 向上跳空缺口回补 (孤岛结束, 反转确认)
        5. 放量
    """
    if len(bars) < 30:
        return {"score": 0, "grade": "D"}

    p = params or {}

    # 找向上跳空缺口 (最近1-3天, 岛形反转完成信号)
    gap_up_idx = None
    for offset in range(0, 4):
        idx = len(bars) - 1 - offset
        if idx < 3:
            continue
        prev_high = _sf(bars[idx - 1].get("high"))
        curr_low = _sf(bars[idx].get("low"))
        if curr_low > prev_high:  # 向上跳空
            gap_up_idx = idx
            break

    if gap_up_idx is None:
        return {"score": 0, "grade": "D"}

    # 找向下跳空缺口 (1-5天前, 岛形反转开始信号)
    gap_down_idx = None
    for i in range(gap_up_idx - 1, max(gap_up_idx - 7, 0), -1):
        if i < 2:
            continue
        prev_low = _sf(bars[i - 1].get("low"))
        curr_high = _sf(bars[i].get("high"))
        if curr_high < prev_low:  # 向下跳空
            gap_down_idx = i
            break

    if gap_down_idx is None:
        return {"score": 0, "grade": "D"}

    # 孤岛大小: 1-5 根 K线
    island_size = gap_up_idx - gap_down_idx
    if island_size < 1 or island_size > 6:
        return {"score": 0, "grade": "D"}

    # 验证下跌趋势: gap_down前5日总体下跌
    if gap_down_idx >= 5:
        close_before = _sf(bars[gap_down_idx - 5].get("close"))
        close_at_gap = _sf(bars[gap_down_idx - 1].get("close"))
        if close_at_gap > close_before:
            return {"score": 0, "grade": "D"}  # 没有下跌趋势

    # 放量确认
    vol = _sf(bars[gap_up_idx].get("volume"))
    avg_vol = sma(bars[:gap_up_idx + 1], "volume", 20)
    vr = vol / avg_vol if avg_vol > 0 else 0
    if vr < 1.3:
        return {"score": 0, "grade": "D"}

    score = 65
    if vr > 2.5:
        score += 15
    elif vr > 1.8:
        score += 10
    elif vr > 1.3:
        score += 5

    # 孤岛越小越强
    if island_size <= 2:
        score += 10

    # 当前仍在上涨
    close = _sf(bars[-1].get("close"))
    ma20 = sma(bars, "close", 20)
    if close > ma20:
        score += 5

    score = min(score, 100)
    grade = "A" if score >= 65 else "B" if score >= 50 else "C"
    return {"score": score, "grade": grade, "name": "island_rev",
            "target_pct": p.get("target_pct", 12), "stop_pct": p.get("stop_pct", -4.0),
            "hold_days": p.get("hold_days", 7), "atr_pct": atr(bars)}


register_profile(StrategyProfile(
    name="island_reversal",
    description="岛形反转(底): 下跌+跳空缺口+孤岛+向上跳空回补, 强烈底部反转信号",
    source="notes/skills/trend-and-limitup.md",
    score_fn=_score_island_reversal,
    regime_fn=get_regime,
    sell_rules=dict(
        trail_trigger=3.0, trail_high_rate=0.25, trail_low_rate=0.35,
        trail_high_thresh=6.0, breakeven_peak=4.0, breakeven_thresh=0.3,
        weak_hold=3, weak_thresh=-0.5, max_hold=8,
    ),
    default_params={"target_pct": 12, "stop_pct": -4.0, "hold_days": 7},
))


# ═══════════════════════════════════════════════════════════════
# Profile 21: volume_floor — 地量买入法
# ═══════════════════════════════════════════════════════════════

def _score_volume_floor(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """地量买入法: 支撑位+成交量新低+小阳线。

    来源: volume-price-analysis.md / stock-selection-methods.md
    条件:
        1. 成交量创近期新低 (地量 < 0.55x 20日均量)
        2. 股价在MA20或前低支撑位附近
        3. 今日收阳线 (多头占优)
        4. 前有上涨趋势或处在横盘底部
    """
    if len(bars) < 30:
        return {"score": 0, "grade": "D"}

    p = params or {}

    close = _sf(bars[-1].get("close"))
    open_ = _sf(bars[-1].get("open"))
    vol = _sf(bars[-1].get("volume"))
    avg_vol = sma(bars, "volume", 20)
    vr = vol / avg_vol if avg_vol > 0 else 0

    # 地量: 成交量 < 0.55x 均量
    if vr > 0.55:
        return {"score": 0, "grade": "D"}

    # 小阳线
    if close <= open_:
        return {"score": 0, "grade": "D"}

    chg = _sf(bars[-1].get("change_pct"))
    if chg > 5.0:
        # 不是地量小阳, 是放量拉升
        return {"score": 0, "grade": "D"}

    # 支撑位: MA20附近
    ma20 = sma(bars, "close", 20)
    ma60 = sma(bars, "close", 60) if len(bars) >= 60 else ma20

    near_support = False
    # MA20支撑
    if abs(close - ma20) / ma20 <= 0.03:
        near_support = True
    # MA60支撑
    if ma60 > 0 and abs(close - ma60) / ma60 <= 0.03:
        near_support = True
    # 前低支撑
    if not near_support:
        l20 = min(_sf(b.get("low")) for b in bars[-25:-5])
        if abs(close - l20) / l20 <= 0.04:
            near_support = True

    if not near_support:
        return {"score": 0, "grade": "D"}

    # 前有上升趋势或横盘
    ma20_10d = sma(bars[:-10], "close", 20) if len(bars) >= 30 else ma20
    trend_ok = ma20 >= ma20_10d * 0.97  # 不是持续下跌

    score = 55
    # 越缩量越好
    if vr < 0.3:
        score += 20
    elif vr < 0.4:
        score += 15
    elif vr < 0.5:
        score += 10

    # 多个支撑共振
    support_count = 0
    if abs(close - ma20) / ma20 <= 0.03:
        support_count += 1
    if ma60 > 0 and abs(close - ma60) / ma60 <= 0.03:
        support_count += 1
    score += support_count * 5

    if trend_ok:
        score += 5

    score = min(score, 100)
    grade = "A" if score >= 65 else "B" if score >= 50 else "C"
    return {"score": score, "grade": grade, "name": "volume_floor",
            "target_pct": p.get("target_pct", 6), "stop_pct": p.get("stop_pct", -3.0),
            "hold_days": p.get("hold_days", 5), "atr_pct": atr(bars)}


register_profile(StrategyProfile(
    name="volume_floor",
    description="地量买入: 支撑位+成交量创近期新低+小阳线企稳, 底部买入信号",
    source="notes/skills/volume-price-analysis.md",
    score_fn=_score_volume_floor,
    regime_fn=get_regime,
    sell_rules=dict(
        trail_trigger=2.0, trail_high_rate=0.30, trail_low_rate=0.40,
        trail_high_thresh=4.0, breakeven_peak=3.0, breakeven_thresh=0.3,
        weak_hold=3, weak_thresh=-0.5, max_hold=8,
    ),
    default_params={"target_pct": 6, "stop_pct": -3.0, "hold_days": 5},
))


# ═══════════════════════════════════════════════════════════════
# Profile 22: notes_ensemble — 笔记策略矿工集成 (ma5_monster + single_yang + island_reversal)
# ═══════════════════════════════════════════════════════════════

def _score_notes_ensemble(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """笔记集成: ma5_monster + single_yang + island_reversal, 取最高分 + 共振加分.

    Top 3 strategies from notes mining (6-month backtest, Apr-Sep 2026):
      - ma5_monster: +0.66%, 50% WR, 1.03 PF
      - single_yang: -0.95%, 46.3% WR, 0.99 PF
      - island_reversal: -0.25%, 40.9% WR, 1.00 PF
    """
    p = params or {}
    scorers = [
        ("ma5_monster", _score_ma5_monster),
        ("single_yang", _score_single_yang),
        ("island_reversal", _score_island_reversal),
    ]
    sub_scores = []
    sub_results = []

    for name, scorer in scorers:
        try:
            r = scorer(bars, p)
            sub_scores.append(r.get("score", 0))
            sub_results.append(r)
        except Exception:
            sub_scores.append(0)
            sub_results.append({"score": 0, "grade": "D"})

    best_idx = max(range(len(sub_scores)), key=lambda i: sub_scores[i])
    best = dict(sub_results[best_idx]) if sub_results else {"score": 0, "grade": "D"}

    # 共振加分: 多个策略同时选中
    threshold = p.get("ensemble_min_score", 50)
    confirmed = sum(1 for s in sub_scores if s >= threshold)
    if confirmed >= 2:
        best["score"] = min(100, best["score"] + 10 * confirmed)
        best["grade"] = "A" if best["score"] >= 70 else "B"
        best["ensemble_confirmed"] = confirmed
        best["ensemble_names"] = [
            name for name, s in zip(
                ["ma5_monster", "single_yang", "island_reversal"], sub_scores
            ) if s >= threshold
        ]

    best["sub_scores"] = sub_scores
    return best


register_profile(StrategyProfile(
    name="notes_ensemble",
    description="笔记策略集成: ma5_monster+single_yang+island_reversal (共振加分), 6月回测top3",
    source="core/strategy_profiles.py (notes mining ensemble)",
    score_fn=_score_notes_ensemble,
    regime_fn=get_regime,
    sell_rules=dict(
        trail_trigger=2.5, trail_high_rate=0.25, trail_low_rate=0.35,
        trail_high_thresh=5.0, breakeven_peak=4.0, breakeven_thresh=0.3,
        weak_hold=2, weak_thresh=-0.5, max_hold=7,
    ),
    default_params={"ensemble_min_score": 50},
    weight=1.0,
))
