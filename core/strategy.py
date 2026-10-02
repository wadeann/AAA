#!/usr/bin/env python3
"""
Astock 共享策略模块 — 回测与实盘共用。

提取自 scripts/backtest_2yr.py，包含：
- 技术指标工具 (sma/rsi/atr)
- 8 因子动量评分 (score_momentum_core)
- 候选过滤 (screen_candidates)
- 市场体制检测 (get_regime / REGIME_MAP)
- 参数化卖出规则 (SellRules)
- 配置加载 (从 config/strategy_params.json 加载，支持 _PARAM_OVERRIDES 覆盖)
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_FILE = _PROJECT_ROOT / "config" / "strategy_params.json"

# ── 全局参数覆盖（用于 auto_iterate 注入）──
_PARAM_OVERRIDES: dict[str, Any] = {}


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _sf(v: Any, d: float = 0.0) -> float:
    """Safe float conversion."""
    try:
        return float(v) if v is not None else d
    except (TypeError, ValueError):
        return d


def sma(bars: list[dict], key: str = "close", period: int = 5) -> float:
    """Simple moving average."""
    vals = [_sf(b.get(key)) for b in bars[-period:] if _sf(b.get(key)) > 0]
    return sum(vals) / len(vals) if vals else 0


def rsi(bars: list[dict], period: int = 14) -> float:
    """Relative Strength Index."""
    closes = [_sf(b.get("close")) for b in bars if _sf(b.get("close")) > 0]
    if len(closes) < period + 1:
        return 50.0
    g = l = 0.0
    for i in range(-period, 0):
        c = closes[i] - closes[i - 1]
        g += max(c, 0)
        l += max(-c, 0)
    a, b = g / period, l / period or 0.01
    return 100 - 100 / (1 + a / b)


def atr(bars: list[dict], period: int = 14) -> float:
    """Average True Range as % of close."""
    trs = []
    for i in range(-period, 0):
        if abs(i) > len(bars):
            continue
        hi = _sf(bars[i].get("high"))
        lo = _sf(bars[i].get("low"))
        pc = _sf(bars[i - 1].get("close")) if i > -len(bars) else hi
        trs.append(max(hi - lo, abs(hi - pc), abs(lo - pc)))
    avg_tr = sum(trs) / len(trs) if trs else 0
    cp = _sf(bars[-1].get("close"))
    return avg_tr / cp * 100 if cp > 0 else 0


# ═══════════════════════════════════════════════════════════════
# 配置加载
# ═══════════════════════════════════════════════════════════════

def load_strategy_config() -> dict[str, Any]:
    """从 config/strategy_params.json 加载策略配置。

    优先级: _PARAM_OVERRIDES > 文件配置 > 默认值
    """
    cfg: dict[str, Any] = {}

    # 1. 从文件加载
    if _CONFIG_FILE.exists():
        try:
            with open(_CONFIG_FILE) as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, OSError):
            cfg = {}

    # 2. _PARAM_OVERRIDES 覆盖（auto_iterate 注入路径）
    if _PARAM_OVERRIDES:
        merged = deepcopy(cfg)
        _deep_merge(merged, _PARAM_OVERRIDES)
        cfg = merged

    return cfg


def _deep_merge(base: dict, override: dict) -> None:
    """递归合并 override 到 base（原地修改）。"""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = deepcopy(v)


def set_param_overrides(overrides: dict) -> None:
    """设置全局参数覆盖（auto_iterate 入口）。"""
    global _PARAM_OVERRIDES
    _PARAM_OVERRIDES = overrides


def clear_param_overrides() -> None:
    """清除全局参数覆盖。"""
    global _PARAM_OVERRIDES
    _PARAM_OVERRIDES = {}


# ═══════════════════════════════════════════════════════════════
# 市场体制检测
# ═══════════════════════════════════════════════════════════════

REGIME_MAP: dict[str, tuple[int, int, float]] = {
    "euphoria": (65, 2, 0.35),
    "hot":      (70, 1, 0.20),
    "warmup":   (60, 5, 0.30),
    "cooldown": (60, 3, 0.28),
    "ice":      (70, 1, 0.15),
}

REGIME_NAMES_CN: dict[str, str] = {
    "euphoria": "高潮",
    "hot":      "走强",
    "warmup":   "震荡",
    "cooldown": "退潮",
    "ice":      "极寒",
}


def get_regime(index_bars: list[dict], curr_date: str) -> str:
    """基于 5 日指数变动 + MA 关系的体制检测。

    返回: euphoria / hot / warmup / cooldown / ice
    """
    bars = [b for b in index_bars if str(b.get("time", "")) <= curr_date]
    if len(bars) < 10:
        return "warmup"
    c5 = [_sf(b.get("close")) for b in bars[-5:]]
    chg5 = (c5[-1] - c5[0]) / c5[0] * 100 if c5[0] > 0 else 0
    ma10 = sma(bars, "close", 10)
    ma20 = sma(bars, "close", 20)
    lc = _sf(bars[-1].get("close"))
    if chg5 > 3 and lc > ma10 > ma20:
        return "euphoria"
    if chg5 > 1 and lc > ma20:
        return "hot"
    if chg5 > -1.5 and lc > ma20 * 0.95:
        return "warmup"
    if chg5 > -3:
        return "cooldown"
    return "ice"


def get_regime_params(regime: str, regime_map_override: dict | None = None) -> tuple[int, int, float]:
    """获取体制参数: (min_score, max_positions, cap_pct)。"""
    rm = regime_map_override or REGIME_MAP
    entry = rm.get(regime, (60, 3, 0.25))
    if isinstance(entry, dict):
        return (
            int(entry.get("0", 60)),
            int(entry.get("1", 3)),
            float(entry.get("2", 0.25)),
        )
    return entry


# ═══════════════════════════════════════════════════════════════
# 候选过滤
# ═══════════════════════════════════════════════════════════════

def screen_candidates(
    bars_dict: dict[str, list[dict]], curr_date: str,
    min_vr: float = 1.5, min_close: float = 10.0,
    ma_pct: float = 0.95,
) -> list[str]:
    """5 重硬过滤: 最少 K 线 → 最低价 → 最低量 → 量比 → MA 位置。"""
    cand = []
    for sym, bars in bars_dict.items():
        lb = [b for b in bars if str(b.get("time", "")) <= curr_date]
        if len(lb) < 30:
            continue
        last = lb[-1]
        close = _sf(last.get("close"))
        if close < min_close:
            continue
        vol = _sf(last.get("volume"))
        if vol <= 0:
            continue
        avg_v = sma(lb, "volume", 20)
        vr = vol / avg_v if avg_v > 0 else 0
        if vr < min_vr:
            continue
        if close < sma(lb, "close", 20) * ma_pct:
            continue
        cand.append(sym)
    return cand


# ═══════════════════════════════════════════════════════════════
# 8 因子动量评分
# ═══════════════════════════════════════════════════════════════

def score_momentum_core(bars: list[dict], params: dict | None = None) -> dict[str, Any]:
    """8 因子统一动量评分 (原 score_stock)。

    params 支持字段:
        volume, dh, ma, rsi, chg, vol_bonus, new_high_bonus, pullback_bonus  (权重)
        target_pct, stop_pct, hold_days                          (交易参数)
        min_vr, min_rs, ma_pct                                   (硬过滤)
    """
    if len(bars) < 25:
        return {"score": 0, "grade": "D"}

    p = params or {}

    # 权重
    _vol_w = p.get("volume", 25)
    _dh_w = p.get("dh", 20)
    _ma_w = p.get("ma", 20)
    _rsi_w = p.get("rsi", 15)
    _chg_w = p.get("chg", 15)
    _vol_bonus_w = p.get("vol_bonus", 5)
    _new_high_bonus = p.get("new_high_bonus", 5)
    _pullback_bonus = p.get("pullback_bonus", 10)

    # 交易参数
    _target_pct = p.get("target_pct", 8)
    _stop_pct = p.get("stop_pct", -2.8)
    _hold_days = p.get("hold_days", 3)

    # 硬过滤阈值
    _min_vr = p.get("min_vr", 0.8)
    _min_rs = p.get("min_rs", 25)
    _ma_pct = p.get("ma_pct", 0.95)

    last = bars[-1]
    close = _sf(last.get("close"))
    vol = _sf(last.get("volume"))
    chg = _sf(last.get("change_pct"))
    avg_vol = sma(bars, "volume", 20)
    vr = vol / avg_vol if avg_vol > 0 else 0
    ma5 = sma(bars, "close", 5)
    ma10 = sma(bars, "close", 10)
    ma20 = sma(bars, "close", 20)
    rs = rsi(bars)
    h10 = [_sf(b.get("high")) for b in bars[-10:]]
    h20 = [_sf(b.get("high")) for b in bars[-20:]]
    hi10 = max(h10) if h10 else close
    hi20 = max(h20) if h20 else close
    dh10 = (hi10 - close) / hi10 * 100
    atr_pct = atr(bars)

    # Hard filters
    if vr < _min_vr or rs < _min_rs:
        return {"score": 0, "grade": "D"}
    if close < ma20 * _ma_pct:
        return {"score": 0, "grade": "D"}

    score = 0
    name = "momentum"

    # 1. Volume (0-_vol_w)
    if vr > 3.0:
        score += _vol_w
    elif vr > 2.0:
        score += int(_vol_w * 0.8)
    elif vr > 1.5:
        score += int(_vol_w * 0.6)
    elif vr > 1.2:
        score += int(_vol_w * 0.4)
    elif vr > 1.0:
        score += int(_vol_w * 0.24)
    else:
        score += int(_vol_w * 0.12)

    # 2. Distance from 10d high (0-_dh_w)
    if dh10 < 1:
        score += _dh_w
    elif dh10 < 3:
        score += int(_dh_w * 0.8)
    elif dh10 < 5:
        score += int(_dh_w * 0.6)
    elif dh10 < 8:
        score += int(_dh_w * 0.35)
    elif dh10 < 12:
        score += int(_dh_w * 0.2)

    # 3. MA alignment (0-_ma_w)
    if close > ma5 > ma10 > ma20:
        score += _ma_w
        name = "trend"
    elif close > ma5 > ma20:
        score += int(_ma_w * 0.7)
    elif close > ma20:
        score += int(_ma_w * 0.5)
    else:
        score += int(_ma_w * 0.1)

    # 4. RSI (0-_rsi_w)
    if 45 <= rs <= 65:
        score += _rsi_w
    elif 65 < rs <= 75:
        score += int(_rsi_w * 0.67)
    elif 35 <= rs < 45:
        score += int(_rsi_w * 0.53)
    elif rs > 75:
        score += int(_rsi_w * 0.27)
    else:
        score += int(_rsi_w * 0.13)

    # 5. Daily change (0-_chg_w)
    if chg > 7:
        score += _chg_w
        name = "ignition"
    elif chg > 5:
        score += int(_chg_w * 0.87)
        name = "ignition"
    elif chg > 3:
        score += int(_chg_w * 0.67)
    elif chg > 1.5:
        score += int(_chg_w * 0.47)
    elif chg > 0.5:
        score += int(_chg_w * 0.27)
    else:
        score += int(_chg_w * 0.07)

    # 6. Volatility bonus (0-_vol_bonus_w)
    rng = (
        (_sf(last.get("high")) - _sf(last.get("low"))) / _sf(last.get("low")) * 100
        if _sf(last.get("low")) > 0
        else 0
    )
    if rng > 5:
        score += _vol_bonus_w
    elif rng > 3:
        score += int(_vol_bonus_w * 0.6)

    # 7. 20d new high bonus
    if hi10 >= hi20 * 0.99:
        score += _new_high_bonus
        name = "breakout"

    # 8. Pullback bonus (0-_pullback_bonus)
    chgs = [
        (cc - o) / o * 100
        for b in bars[-10:-1]
        if (o := _sf(b.get("open", 0))) > 0
        for cc in [_sf(b.get("close", 0))]
    ]
    if chgs and max(chgs) > 5 and vr < 0.9:
        score += _pullback_bonus
        name = "pullback"

    score = min(score, 100)

    if score >= 65:
        grade = "A"
    elif score >= 50:
        grade = "B"
    elif score >= 35:
        grade = "C"
    else:
        grade = "D"

    return {
        "score": score,
        "grade": grade,
        "name": name,
        "target_pct": _target_pct,
        "stop_pct": _stop_pct,
        "hold_days": _hold_days,
        "atr_pct": atr_pct,
    }


# ═══════════════════════════════════════════════════════════════
# 卖出规则引擎
# ═══════════════════════════════════════════════════════════════

class SellRules:
    """参数化卖出规则引擎。

    6 条规则，每条独立可组合:
        1. profit_target  — 达到目标收益即卖
        2. trailing_stop  — 从高点回撤一定比例卖
        3. hard_stop      — 固定止损位卖
        4. breakeven      — 曾达保本峰后回落至阈值卖
        5. weak_exit      — 持仓 X 日且收益低于阈值卖
        6. time_exit      — 超过最大持仓天数卖
    """

    def __init__(self, rules: dict | None = None):
        r = rules or {}
        self.trail_trigger = r.get("trail_trigger", 3.0)
        self.trail_high_rate = r.get("trail_high_rate", 0.3)
        self.trail_low_rate = r.get("trail_low_rate", 0.4)
        self.trail_high_thresh = r.get("trail_high_thresh", 5.0)
        self.breakeven_peak = r.get("breakeven_peak", 3.0)
        self.breakeven_thresh = r.get("breakeven_thresh", 0.5)
        self.weak_hold = r.get("weak_hold", 2)
        self.weak_thresh = r.get("weak_thresh", -0.5)
        self.max_hold = r.get("max_hold", 5)

    def evaluate(self, pos: dict, hi: float, lo: float, cl: float, hold: int) -> tuple[bool, float, str]:
        """评估卖出条件。

        Args:
            pos: 持仓字典 (含 ep/ed/tp/sp/mp 等字段)
            hi: 当日最高价
            lo: 当日最低价
            cl: 当日收盘价
            hold: 持仓天数

        Returns:
            (卖出?, 卖出价, 原因)
        """
        ep = pos.get("ep", 0)
        tp = pos.get("tp", 8)
        sp = pos.get("sp", -2.8)
        mp = pos.get("mp", ep)  # 持仓期间最高价

        cp = (cl - ep) / ep * 100  # 当前收益率
        mp_pct = (mp - ep) / ep * 100  # 最高收益率

        # 1. Profit target
        if cp >= tp:
            return (True, cl, f"目标+{tp:.0f}%")

        # 2. Trailing stop
        if mp_pct >= self.trail_trigger:
            tr = self.trail_high_rate if mp_pct >= self.trail_high_thresh else self.trail_low_rate
            tp_ = ep * (1 + mp_pct * (1 - tr) / 100)
            if lo <= tp_:
                return (True, tp_, f"回落{tr*100:.0f}%(高{mp_pct:.1f}%)")

        # 3. Hard stop
        if cp <= sp:
            return (True, cl, f"止损{sp:.0f}%")

        # 4. Breakeven
        if mp_pct >= self.breakeven_peak and cp < self.breakeven_thresh:
            return (True, cl, f"保本(曾{mp_pct:.1f}%)")

        # 5. Weak exit
        if hold >= self.weak_hold and cp < self.weak_thresh:
            return (True, cl, f"弱{hold}d")

        # 6. Time exit
        if hold >= self.max_hold:
            return (True, cl, f"时间{hold}d")

        return (False, cl, "")

    def to_dict(self) -> dict:
        return {
            "trail_trigger": self.trail_trigger,
            "trail_high_rate": self.trail_high_rate,
            "trail_low_rate": self.trail_low_rate,
            "trail_high_thresh": self.trail_high_thresh,
            "breakeven_peak": self.breakeven_peak,
            "breakeven_thresh": self.breakeven_thresh,
            "weak_hold": self.weak_hold,
            "weak_thresh": self.weak_thresh,
            "max_hold": self.max_hold,
        }
