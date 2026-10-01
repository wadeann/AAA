#!/usr/bin/env python3
"""
Astock 全市场动量回测 — 2 年回测 (2024-10-01 ~ 2026-10-01)
基于 v5 引擎，扩展至 800+ 全市场股票，添加行业分析。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp_client import get_mcp_client
from stock_universe_full import STOCK_UNIVERSE, get_industry, get_universe_size, get_industry_distribution

# ── 回测参数 ──
START_DATE = "2024-10-01"
END_DATE = "2026-10-01"
INITIAL_CAPITAL = 400000.0
KLINE_COUNT = 500       # 2年需要更多数据
MIN_BARS = 120          # 最少 K 线数
CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "kline_cache.json"

# ── 参数覆盖（用于自动迭代）──
_PARAM_OVERRIDES: dict = {}

# ── 工具函数 ──
_MCP_CACHE: dict[str, list[dict]] = {}


def _sf(v: Any, d: float = 0.0) -> float:
    try:
        return float(v) if v is not None else d
    except (TypeError, ValueError):
        return d


def load_cache() -> dict[str, list[dict]]:
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_cache(cache: dict[str, list[dict]]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
        print(f"  [Cache] Saved {len(cache)} symbols to {CACHE_FILE}")
    except Exception as e:
        print(f"  [Cache] Save failed: {e}")


def fetch_klines(symbol: str, count: int = KLINE_COUNT, retries: int = 3) -> list[dict]:
    """带重试的 K 线获取."""
    key = f"{symbol}_{count}"
    if key in _MCP_CACHE:
        return _MCP_CACHE[key]

    for attempt in range(retries):
        try:
            raw = get_mcp_client().call(
                "fetch_kline",
                {"symbol": symbol, "period": "D", "count": count},
            )
            if isinstance(raw, dict):
                k = raw.get("klines", [])
                if k:
                    _MCP_CACHE[key] = k
                    return k
            if isinstance(raw, list):
                _MCP_CACHE[key] = raw
                return raw
        except Exception as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * 2
                print(f"    [Retry {attempt + 1}/{retries}] {symbol}: {e}, wait {wait}s")
                time.sleep(wait)
            else:
                print(f"    [FAIL] {symbol} after {retries} retries: {e}")
    _MCP_CACHE[key] = []
    return []


def sma(bars: list[dict], key: str = "close", period: int = 5) -> float:
    vals = [_sf(b.get(key)) for b in bars[-period:] if _sf(b.get(key)) > 0]
    return sum(vals) / len(vals) if vals else 0


def rsi(bars: list[dict], period: int = 14) -> float:
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


def get_regime(index_bars: list[dict], curr_date: str) -> str:
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


REGIME_MAP = {
    "euphoria": (65, 2, 0.35),
    "hot": (70, 1, 0.20),
    "warmup": (60, 5, 0.30),
    "cooldown": (60, 3, 0.28),
    "ice": (70, 1, 0.15),
}


def screen_candidates(
    bars_dict: dict[str, list[dict]], curr_date: str,
    min_vr: float = 1.5, min_close: float = 10.0,
) -> list[str]:
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
        if close < sma(lb, "close", 20) * 0.95:
            continue
        cand.append(sym)
    return cand


def score_stock(bars: list[dict]) -> dict[str, Any]:
    """统一动量评分 (与 v5 完全相同)."""
    if len(bars) < 25:
        return {"score": 0, "grade": "D"}

    # 配置覆盖
    sw = _PARAM_OVERRIDES.get("score_weights", {})
    _vol_w = sw.get("volume", 25)
    _dh_w = sw.get("dh", 20)
    _ma_w = sw.get("ma", 20)
    _rsi_w = sw.get("rsi", 15)
    _chg_w = sw.get("chg", 15)
    _vol_bonus_w = sw.get("vol_bonus", 5)
    _new_high_bonus = sw.get("new_high_bonus", 5)
    _pullback_bonus = sw.get("pullback_bonus", 10)
    _target_pct = sw.get("target_pct", 8)
    _stop_pct = sw.get("stop_pct", -2.8)
    _hold_days = sw.get("hold_days", 3)

    # 硬过滤阈值
    hf = _PARAM_OVERRIDES.get("hard_filters", {})
    _min_vr = hf.get("min_vr", 0.8)
    _min_rs = hf.get("min_rs", 25)
    _ma_pct = hf.get("ma_pct", 0.95)
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
    # 1. Volume (0-25)
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


def run_backtest(config_override: dict | None = None) -> dict:
    """运行 2 年全市场回测."""
    # ── 配置覆盖（用于自动迭代）──
    global _PARAM_OVERRIDES
    _PARAM_OVERRIDES = config_override or {}
    cfg = _PARAM_OVERRIDES
    _REGIME_MAP = cfg.get("regime_map", REGIME_MAP)
    _MIN_CLOSE = cfg.get("min_close", 10.0)
    _MIN_VR = cfg.get("min_vr", 1.5)
    _TARGET_PCT = cfg.get("target_pct", 8)
    _STOP_PCT = cfg.get("stop_pct", -2.8)
    _HOLD_DAYS = cfg.get("hold_days", 3)
    _SCORE_WEIGHTS = cfg.get("score_weights", {})
    _SELL_RULES = cfg.get("sell_rules", {})
    _HARD_FILTERS = cfg.get("hard_filters", {})

    symbols = cfg.get("symbols", STOCK_UNIVERSE)
    total_symbols = len(symbols)
    print(f"{'=' * 100}")
    print(f"  全市场动量回测  v5-ext")
    print(f"  股票池: {total_symbols} 只 | 时间: {START_DATE} ~ {END_DATE}")
    print(f"  初始资金: {INITIAL_CAPITAL:,.0f}")
    print(f"  行业覆盖: {len(get_industry_distribution())}")
    print(f"{'=' * 100}")

    # ── 1. 加载缓存 ──
    print(f"\n{'─' * 40} 加载数据 {'─' * 40}")
    file_cache = load_cache()
    if file_cache:
        print(f"  [Cache] Loaded {len(file_cache)} cached symbols")
    else:
        print(f"  [Cache] No cache found, will fetch all data")

    # ── 2. 获取 K 线数据 ──
    all_bars: dict[str, list[dict]] = {}
    batch_size = 50
    loaded_count = 0
    start_load = time.time()

    for i in range(0, total_symbols, batch_size):
        batch = symbols[i : i + batch_size]
        for sym in batch:
            cache_key = f"{sym}_{KLINE_COUNT}"
            # 先检查文件缓存
            if cache_key in file_cache:
                bars = file_cache[cache_key]
                _MCP_CACHE[cache_key] = bars
            else:
                bars = fetch_klines(sym, KLINE_COUNT)
            if len(bars) >= MIN_BARS:
                all_bars[sym] = bars
                loaded_count += 1

        # 进度提示
        pct = min(100, (i + batch_size) / total_symbols * 100)
        elapsed = time.time() - start_load
        rate = (i + batch_size) / elapsed if elapsed > 0 else 0
        print(
            f"  Progress: {min(i + batch_size, total_symbols):>4d}/{total_symbols} "
            f"({pct:.0f}%) | Loaded: {loaded_count} | "
            f"{rate:.1f} stocks/s | Elapsed: {elapsed:.0f}s"
        )

    load_time = time.time() - start_load
    print(f"\n  Data loaded: {len(all_bars)}/{total_symbols} (min {MIN_BARS} bars)")
    print(f"  Load time: {load_time:.0f}s")

    # ── 3. 保存缓存（仅首次需要）──
    if not cfg.get("skip_cache_save"):
        save_cache({f"{s}_{KLINE_COUNT}": _MCP_CACHE.get(f"{s}_{KLINE_COUNT}", []) for s in symbols})

    if len(all_bars) < 100:
        print(f"\n  ERROR: Too few stocks with sufficient data ({len(all_bars)}), aborting.")
        return {}

    # ── 4. 获取指数数据 ──
    index_bars = fetch_klines("000001.SH", KLINE_COUNT)
    if not index_bars:
        print("  ERROR: No index data, aborting.")
        return {}

    # ── 5. 生成交易日期 ──
    dates = sorted(
        {
            str(b.get("time"))
            for b in index_bars
            if START_DATE <= str(b.get("time", "")) <= END_DATE
        }
    )
    if len(dates) < 10:
        print(f"  ERROR: Too few trading days: {len(dates)}")
        return {}

    print(f"\n  Trading days: {len(dates)}")
    print(f"  Universe: {len(all_bars)} stocks")
    print(f"{'=' * 100}\n")

    # ── 6. 回测主循环 ──
    cash = INITIAL_CAPITAL
    peak = INITIAL_CAPITAL
    pos: dict[str, dict] = {}
    log: list[dict] = []
    eq: list[dict] = []
    comm = 0.0

    total_days = len(dates)
    last_progress_pct = 0

    # 从覆盖参数中提取 sell rules
    sr = _SELL_RULES
    _trail_trigger = sr.get("trail_trigger", 3.0)
    _trail_high = sr.get("trail_high_rate", 0.3)
    _trail_low = sr.get("trail_low_rate", 0.4)
    _trail_high_thresh = sr.get("trail_high_thresh", 5.0)
    _breakeven_peak = sr.get("breakeven_peak", 3.0)
    _breakeven_thresh = sr.get("breakeven_thresh", 0.5)
    _weak_hold = sr.get("weak_hold", 2)
    _weak_thresh = sr.get("weak_thresh", -0.5)
    _max_hold = sr.get("max_hold", 5)

    for di, dt_ in enumerate(dates):
        # 进度
        progress_pct = (di + 1) / total_days * 100
        if progress_pct // 10 > last_progress_pct // 10:
            print(f"  Backtest: {di + 1}/{total_days} days ({progress_pct:.0f}%) | "
                  f"Cash: {cash:,.0f} | Positions: {len(pos)}")
            last_progress_pct = progress_pct // 10

        regime = get_regime(index_bars, dt_)
        _rm = cfg.get("regime_map", REGIME_MAP)
        _rm_entry = _rm[regime]
        if isinstance(_rm_entry, dict):
            ms, mx, cp = _rm_entry.get("0", 60), _rm_entry.get("1", 3), _rm_entry.get("2", 0.25)
        else:
            ms, mx, cp = _rm_entry

        # ── BUY ──
        if len(pos) < mx:
            screen_min_vr = cfg.get("min_vr", 1.5)
            screen_min_close = cfg.get("min_close", 10.0)
            screen = screen_candidates(all_bars, dt_, min_vr=screen_min_vr, min_close=screen_min_close)
            cand = []
            for sym in screen:
                if sym in pos:
                    continue
                lb = [b for b in all_bars[sym] if str(b.get("time", "")) <= dt_]
                if len(lb) < 25:
                    continue
                r = score_stock(lb)
                if r["grade"] in ("D", "C") or r["score"] < ms:
                    continue
                cand.append((sym, r))
            cand.sort(key=lambda x: -x[1]["score"])
            for sym, r in cand[: mx - len(pos)]:
                ei = di + 1
                if ei >= len(dates):
                    continue
                ed = dates[ei]
                eb = next(
                    (b for b in all_bars[sym] if str(b.get("time", "")) == ed),
                    None,
                )
                if not eb:
                    continue
                ep = _sf(eb.get("open"))
                if ep <= 0:
                    continue
                sc = r["score"]
                _max_pos_pct = cfg.get("max_pos_pct", 0.35)
                if sc >= 80:
                    alloc = min(cp + 0.05, _max_pos_pct)
                elif sc >= 70:
                    alloc = cp
                elif sc >= 60:
                    alloc = cp * 0.8
                else:
                    alloc = cp * 0.6
                amt = min(cash * alloc, INITIAL_CAPITAL * _max_pos_pct)
                qty = max(100, int(amt / ep / 100) * 100)
                cost = qty * ep
                fee = cost * 0.0003
                if cash < cost + fee:
                    continue
                cash -= cost + fee
                comm += fee
                pos[sym] = {
                    "sym": sym,
                    "qty": qty,
                    "ep": ep,
                    "ed": ed,
                    "mp": ep,
                    "tp": r["target_pct"],
                    "sp": r["stop_pct"],
                    "hd": r["hold_days"],
                    "sc": r["score"],
                    "nm": r["name"],
                    "reg": regime,
                }
                log.append({
                    "date": ed,
                    "d": "B",
                    "sym": sym,
                    "p": ep,
                    "q": qty,
                    "sc": r["score"],
                    "nm": r["name"],
                    "reg": regime,
                })

        # ── SELL ──
        for sym in list(pos.keys()):
            p = pos[sym]
            td = next(
                (b for b in all_bars.get(sym, []) if str(b.get("time", "")) == dt_),
                None,
            )
            if not td:
                continue
            hi = _sf(td.get("high"))
            lo = _sf(td.get("low"))
            cl = _sf(td.get("close"))
            if hi > p["mp"]:
                p["mp"] = hi
            if p["ed"] == dt_:
                continue
            ep_ = p["ep"]
            cp_ = (cl - ep_) / ep_ * 100
            mp_ = (p["mp"] - ep_) / ep_ * 100
            hold = (dt.date.fromisoformat(dt_) - dt.date.fromisoformat(p["ed"])).days
            sell = False
            sp_ = cl
            why = ""
            if cp_ >= p["tp"]:
                sell = True
                why = f"目标+{p['tp']:.0f}%"
            elif mp_ >= _trail_trigger:
                tr = _trail_high if mp_ >= _trail_high_thresh else _trail_low
                tp = ep_ * (1 + mp_ * (1 - tr) / 100)
                if lo <= tp:
                    sell = True
                    sp_ = tp
                    why = f"回落{tr*100:.0f}%(高{mp_:.1f}%)"
            elif cp_ <= p["sp"]:
                sell = True
                why = f"止损{p['sp']:.0f}%"
            elif mp_ >= _breakeven_peak and cp_ < _breakeven_thresh:
                sell = True
                why = f"保本(曾{mp_:.1f}%)"
            elif hold >= _weak_hold and cp_ < _weak_thresh:
                sell = True
                why = f"弱{hold}d"
            elif hold >= _max_hold:
                sell = True
                why = f"时间{hold}d"
            if sell:
                rev = p["qty"] * sp_
                fee = rev * 0.0013
                cash += rev - fee
                comm += fee
                pnl = (rev - fee) - (p["qty"] * ep_)
                pnl_pct = pnl / (p["qty"] * ep_) * 100
                log.append({
                    "date": dt_,
                    "d": "S",
                    "sym": sym,
                    "p": sp_,
                    "q": p["qty"],
                    "pnl": pnl,
                    "pp": pnl_pct,
                    "hold": hold,
                    "why": why,
                    "nm": p["nm"],
                    "reg": p["reg"],
                    "sc": p["sc"],
                })
                del pos[sym]

        # ── Equity ──
        pv = sum(
            p["qty"]
            * _sf(
                next(
                    (
                        b
                        for b in all_bars.get(sym, [])
                        if str(b.get("time", "")) == dt_
                    ),
                    {},
                ).get("close", p["ep"])
            )
            for sym, p in pos.items()
        )
        te = cash + pv
        if te > peak:
            peak = te
        eq.append({"date": dt_, "te": round(te, 2), "n": len(pos), "reg": regime})

    # ── 7. 统计计算 ──
    fin = eq[-1]
    net = fin["te"] - INITIAL_CAPITAL
    ret = net / INITIAL_CAPITAL * 100

    # 月数
    start_d = dt.date.fromisoformat(START_DATE)
    end_d = dt.date.fromisoformat(END_DATE)
    total_months = max(1, (end_d.year - start_d.year) * 12 + end_d.month - start_d.month)
    annual_ret = ((1 + ret / 100) ** (12 / total_months) - 1) * 100

    # 月度收益
    monthly_returns: dict[str, float] = {}
    prev_te = INITIAL_CAPITAL
    curr_month = ""
    for e in eq:
        ym = e["date"][:7]
        if ym != curr_month:
            if curr_month and curr_month >= START_DATE[:7]:
                monthly_returns[curr_month] = (prev_te - prev_month_start) / prev_month_start * 100
            curr_month = ym
            prev_month_start = prev_te
        prev_te = e["te"]
    # 最后一个月
    if curr_month and curr_month >= START_DATE[:7]:
        monthly_returns[curr_month] = (prev_te - prev_month_start) / prev_month_start * 100

    monthly_ret_mean = sum(monthly_returns.values()) / len(monthly_returns) if monthly_returns else 0
    monthly_ret_std = (
        (sum((r - monthly_ret_mean) ** 2 for r in monthly_returns.values()) / len(monthly_returns)) ** 0.5
        if monthly_returns
        else 0
    )

    # 交易统计
    closed = [t for t in log if t["d"] == "S"]
    wins = [t for t in closed if t.get("pnl", 0) > 0]
    losses = [t for t in closed if t.get("pnl", 0) <= 0]
    wr = len(wins) / len(closed) * 100 if closed else 0
    aw = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    al = abs(sum(t["pnl"] for t in losses)) / len(losses) if losses else 1
    pf = (sum(t["pnl"] for t in wins) or 0) / (abs(sum(t["pnl"] for t in losses)) or 1)

    # 最大回撤
    peak2 = INITIAL_CAPITAL
    mdd = 0.0
    mdd_start = ""
    mdd_end = ""
    mdd_peak_date = ""
    for e in eq:
        if e["te"] > peak2:
            peak2 = e["te"]
            mdd_peak_date = e["date"]
        dd = (peak2 - e["te"]) / peak2 * 100
        if dd > mdd:
            mdd = dd
            mdd_start = mdd_peak_date
            mdd_end = e["date"]

    # Sharpe (假设无风险利率 2%)
    rf = 2.0
    excess_returns = [r - rf / 12 for r in monthly_returns.values()]
    sharpe = (
        (sum(excess_returns) / len(excess_returns)) / (monthly_ret_std + 0.001) * (12**0.5)
        if monthly_ret_std > 0
        else 0
    )

    # ── 8. 行业分析 ──
    industry_stats: dict[str, dict] = {}
    for t in closed:
        ind = get_industry(t["sym"])
        if ind not in industry_stats:
            industry_stats[ind] = {"trades": 0, "wins": 0, "pnl": 0.0, "pnl_pct": 0.0}
        industry_stats[ind]["trades"] += 1
        industry_stats[ind]["pnl"] += t.get("pnl", 0)
        if t.get("pnl", 0) > 0:
            industry_stats[ind]["wins"] += 1

    # ── 9. 策略统计 ──
    strategy_stats: dict[str, dict] = {}
    for t in closed:
        n = t.get("nm", "?")
        if n not in strategy_stats:
            strategy_stats[n] = {"n": 0, "w": 0, "p": 0.0}
        strategy_stats[n]["n"] += 1
        if t.get("pnl", 0) > 0:
            strategy_stats[n]["w"] += 1
        strategy_stats[n]["p"] += t.get("pnl", 0)

    # ── 10. 输出 ──
    results_text: list[str] = []
    results_text.append("=" * 100)
    results_text.append("  全市场动量回测结果 (v5-ext)")
    results_text.append("=" * 100)
    results_text.append("")

    # 参数
    results_text.append(f"  回测参数:")
    results_text.append(f"    时间范围: {START_DATE} ~ {END_DATE}  ({len(dates)} 个交易日)")
    results_text.append(f"    初始资金: {INITIAL_CAPITAL:,.0f}")
    results_text.append(f"    股票池:   {total_symbols} 只 (有效: {len(all_bars)})")
    results_text.append(f"    行业覆盖: {len(get_industry_distribution())}")
    results_text.append(f"    数据量:   {KLINE_COUNT} 根 K 线/只, 最少 {MIN_BARS} 根")
    results_text.append("")

    # 最终统计
    results_text.append(f"  {'=' * 80}")
    results_text.append(f"  最终统计")
    results_text.append(f"  {'=' * 80}")
    results_text.append(f"    总收益:       {ret:>+10.2f}%")
    results_text.append(f"    年化收益:     {annual_ret:>+10.2f}%")
    results_text.append(f"    最终权益:     {fin['te']:>10,.0f}")
    results_text.append(f"    净利润:       {net:>+10,.0f}")
    results_text.append(f"    月均收益:     {monthly_ret_mean:>+10.2f}%")
    results_text.append(f"    月收益标准差: {monthly_ret_std:>10.2f}%")
    results_text.append(f"    夏普比率:     {sharpe:>10.2f}")
    results_text.append(f"    胜率:         {wr:>10.1f}%")
    results_text.append(f"    盈亏比:       {pf:>10.2f}")
    results_text.append(f"    平均盈利:     {aw:>+10,.0f}")
    results_text.append(f"    平均亏损:     {al:>+10,.0f}")
    results_text.append(f"    最大回撤:     {mdd:>10.2f}%")
    results_text.append(f"    回撤区间:     {mdd_start} ~ {mdd_end}")
    results_text.append(f"    交易次数:     {len(closed):>10}")
    results_text.append(f"    总佣金:       {comm:>10,.0f}")
    results_text.append("")

    # 月度收益表
    results_text.append(f"  {'=' * 80}")
    results_text.append(f"  月度收益汇总")
    results_text.append(f"  {'=' * 80}")
    results_text.append(f"  {'月份':<10} {'月收益':>10} {'累计收益':>10}")
    results_text.append(f"  {'-' * 30}")
    cum_ret = 0
    for ym in sorted(monthly_returns.keys()):
        mr = monthly_returns[ym]
        cum_ret += mr
        sign = "+" if mr >= 0 else ""
        results_text.append(f"  {ym:<10} {sign}{mr:>+9.2f}% {cum_ret:>+9.2f}%")
    results_text.append("")

    # 月度统计
    positive_months = sum(1 for v in monthly_returns.values() if v > 0)
    negative_months = sum(1 for v in monthly_returns.values() if v <= 0)
    if monthly_returns:
        best_month = max(monthly_returns.values())
        worst_month = min(monthly_returns.values())
        results_text.append(f"  盈利月: {positive_months}/{len(monthly_returns)} ({positive_months/len(monthly_returns)*100:.0f}%)")
        results_text.append(f"  最佳月: {best_month:+.2f}%")
        results_text.append(f"  最差月: {worst_month:+.2f}%")
        results_text.append("")

    # 每日交易记录
    results_text.append(f"  {'=' * 80}")
    results_text.append(f"  交易记录")
    results_text.append(f"  {'=' * 80}")
    results_text.append(
        f"  {'Date':<10} {'D':<2} {'Symbol':<10} {'Price':>7} {'Qty':>6} "
        f"{'Strat':<9} {'PnL':>10} {'%':>6} {'Hold':>4} {'Reason'}"
    )
    results_text.append(f"  {'-' * 80}")
    buy_count = 0
    sell_count = 0
    for t in log:
        if t["d"] == "B":
            buy_count += 1
            results_text.append(
                f"  {t['date']:<10} {'B':<2} {t['sym']:10s} {t['p']:>7.2f} {t['q']:>6d} "
                f"{t.get('nm', '?'):<9} {'---':>10} {'---':>6} {'':4} | {t.get('reg', '')}"
            )
        else:
            sell_count += 1
            results_text.append(
                f"  {t['date']:<10} {'S':<2} {t['sym']:10s} {t['p']:>7.2f} {t['q']:>6d} "
                f"{t.get('nm', '?'):<9} {t.get('pnl', 0):>+10.0f} {t.get('pp', 0):>+5.1f}% "
                f"{t.get('hold', 0):>3}d | {t['why']}"
            )
    results_text.append(f"  {'-' * 80}")
    results_text.append(f"  买入: {buy_count}  卖出: {sell_count}  |  总交易: {len(closed)}")
    results_text.append("")

    # 策略统计
    if strategy_stats:
        results_text.append(f"  {'=' * 80}")
        results_text.append(f"  策略维度分析")
        results_text.append(f"  {'=' * 80}")
        results_text.append(f"  {'策略':<12} {'交易':>6} {'胜率':>6} {'总盈亏':>10}")
        results_text.append(f"  {'-' * 40}")
        for n, s in sorted(strategy_stats.items(), key=lambda x: -x[1]["p"]):
            results_text.append(
                f"  {n:<12} {s['n']:>6} {(s['w']/s['n']*100):>5.0f}% {s['p']:>+10,.0f}"
            )
        results_text.append("")

    # 行业分析
    if industry_stats:
        results_text.append(f"  {'=' * 80}")
        results_text.append(f"  行业维度分析")
        results_text.append(f"  {'=' * 80}")
        results_text.append(f"  {'行业':<16} {'交易':>6} {'胜率':>6} {'总盈亏':>10}")
        results_text.append(f"  {'-' * 45}")
        for ind, s in sorted(industry_stats.items(), key=lambda x: -x[1]["pnl"]):
            wr_ind = s["wins"] / s["trades"] * 100 if s["trades"] > 0 else 0
            if s["trades"] >= 2:  # 只显示交易次数>=2的行业
                results_text.append(
                    f"  {ind:<16} {s['trades']:>6} {wr_ind:>5.0f}% {s['pnl']:>+10,.0f}"
                )
        results_text.append("")

    # 权益曲线
    results_text.append(f"  {'=' * 80}")
    results_text.append(f"  权益曲线 (每 20 天采样)")
    results_text.append(f"  {'=' * 80}")
    results_text.append(f"  {'日期':<12} {'权益':>10} {'仓位':>4} {'市况':<10} {'DD%':>6}")
    results_text.append(f"  {'-' * 50}")
    for i, e in enumerate(eq):
        if i % 20 == 0 or i == len(eq) - 1:
            dd = (peak - e["te"]) / peak * 100
            results_text.append(
                f"  {e['date']:<12} {e['te']:>10,.0f} {e['n']:>4} {e['reg']:<10} {dd:>5.1f}%"
            )
    results_text.append("")

    results_text.append("=" * 100)

    # ── 打印与保存 ──
    output = "\n".join(results_text)
    print(output)

    # 保存到文件
    result_file = Path(__file__).resolve().parent.parent / "results" / "backtest_2yr_results.txt"
    result_file.parent.mkdir(parents=True, exist_ok=True)
    with open(result_file, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\n结果已保存至: {result_file}")

    return {
        "ret": ret,
        "annual_ret": annual_ret,
        "monthly_ret_mean": monthly_ret_mean,
        "monthly_ret_std": monthly_ret_std,
        "sharpe": sharpe,
        "wr": wr,
        "pf": pf,
        "mdd": mdd,
        "trades": len(closed),
        "total_symbols": total_symbols,
        "valid_symbols": len(all_bars),
        "total_days": len(dates),
        "comm": comm,
        "best_month": max(monthly_returns.values()) if monthly_returns else 0,
        "worst_month": min(monthly_returns.values()) if monthly_returns else 0,
        "positive_months": positive_months,
        "negative_months": negative_months,
        "total_months": len(monthly_returns),
        "n_wins": len(wins),
        "n_losses": len(losses),
        "avg_win": aw,
        "avg_loss": al,
        "strategy_stats": strategy_stats,
        "industry_stats": industry_stats,
    }
    _PARAM_OVERRIDES.clear()
    return results


def main():
    results = run_backtest()
    if results:
        print(f"\n{'=' * 40} 概览 {'=' * 40}")
        print(f"  股票: {results['valid_symbols']}/{results['total_symbols']} | "
              f"交易日: {results['total_days']}")
        print(f"  收益: {results['ret']:+.2f}% | 年化: {results['annual_ret']:+.2f}% | "
              f"月均: {results['monthly_ret_mean']:+.2f}%")
        print(f"  夏普: {results['sharpe']:.2f} | 胜率: {results['wr']:.0f}% | "
              f"盈亏比: {results['pf']:.2f} | 最大回撤: {results['mdd']:.2f}%")
        print(f"  交易: {results['trades']} | 佣金: {results['comm']:,.0f}")
        print(f"  最佳月: {results['best_month']:+.2f}% | 最差月: {results['worst_month']:+.2f}%")
        print(f"  盈利月: {results['positive_months']}/{results['total_months']} "
              f"({results['positive_months']/results['total_months']*100:.0f}%)")
        print("=" * 90)


if __name__ == "__main__":
    main()
