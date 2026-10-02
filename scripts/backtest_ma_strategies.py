#!/usr/bin/env python3
"""
MA Strategy Backtest — implements 6 MA-based strategies from the strategy document
and backtests them over a 3-month window.

Strategies:
  1. MA5 Monster Hunting (MA5捉妖战法)
  2. Lotus Rising (出水芙蓉 / 蛟龙出海)
  3. Monkey Explores (灵猴探路)
  4. Lotus Step (步步莲花)
  5. Three Horse Carriage (三驾马车)
  6. Guillotine (断头铡刀) — SELL FILTER ONLY

Usage:
  python3 scripts/backtest_ma_strategies.py
"""

from __future__ import annotations

import datetime as dt
import json
import math
import sys
from pathlib import Path
from typing import Any

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.cost_model import buy_cost, sell_cost


# ═══════════════════════════════════════════════════════════════
# Utility Functions
# ═══════════════════════════════════════════════════════════════

def _sf(v: Any, d: float = 0.0) -> float:
    """Safe float conversion."""
    try:
        return float(v) if v is not None else d
    except (TypeError, ValueError):
        return d


def strip_suffix(sym: str) -> str:
    """Remove _500 suffix from symbol for cost model."""
    return sym.replace("_500", "")


def compute_sma(bars: list[dict], key: str, period: int) -> float:
    """Compute simple moving average for last N bars."""
    vals = [_sf(b[key]) for b in bars[-period:] if _sf(b[key]) > 0]
    return sum(vals) / len(vals) if vals else 0


def compute_ma(bars: list[dict], period: int) -> list[float]:
    """Compute rolling MA series. Returns list same length as bars, NaN for insufficient data."""
    closes = [_sf(b["close"]) for b in bars]
    result = [float('nan')] * len(bars)
    for i in range(period - 1, len(bars)):
        result[i] = sum(closes[i - period + 1:i + 1]) / period
    return result


def is_date_before(a: str, b: str) -> bool:
    """True if date a <= date b."""
    return a <= b


def is_limit_up(bar: dict, prev_close: float | None = None) -> bool:
    """Check if bar is a limit-up (10% for main board, 20% for ChiNext/STAR)."""
    close = _sf(bar["close"])
    high = _sf(bar["high"])
    # Limit up: close == high and ~10% gain from prev close
    if close != high or close <= 0:
        return False
    if prev_close is not None and prev_close > 0:
        chg = (close - prev_close) / prev_close
        # Main board: 9.5%+ (allow for rounding), ChiNext/STAR: 19%+
        # 600/000/001/002/003 are main board, 300/301 are ChiNext, 688 is STAR
        return chg >= 0.095  # Conservative: treat 9.5%+ as limit up
    return False


def is_suspended(bar: dict) -> bool:
    """Check if stock is suspended (zero volume or zero high-low range)."""
    vol = _sf(bar.get("volume"))
    hi = _sf(bar.get("high"))
    lo = _sf(bar.get("low"))
    return vol <= 0 or hi <= lo


# ═══════════════════════════════════════════════════════════════
# Strategy 1: MA5 Monster Hunting (MA5捉妖战法)
# ═══════════════════════════════════════════════════════════════

def detect_ma5_monster(bars_lookback: list[dict], idx: int) -> bool:
    """
    Signal conditions:
    1. Stock must have had 3+ consecutive days closing above MA5, each day
       making a new stage high (close > previous day's close)
    2. Within last 3 days, a bearish candle (close < open) pullback occurred
    3. Current day: open near MA5 (within 1.5% of MA5)

    Returns: True if signal detected at idx (entry on idx+1)
    """
    if idx < 6:
        return False

    # Need enough history for MA5 computation
    closes = [_sf(b["close"]) for b in bars_lookback[:idx + 1]]
    opens = [_sf(b["open"]) for b in bars_lookback[:idx + 1]]

    # Compute MA5 at current bar
    ma5_series = compute_ma(bars_lookback[:idx + 1], 5)
    ma5 = ma5_series[idx]
    if math.isnan(ma5) or ma5 <= 0:
        return False

    curr_close = closes[idx]
    curr_open = opens[idx]

    # Check: 3+ consecutive days above MA5 with new highs BEFORE the current day
    # Look backwards from idx-1 to find the uptrend pattern
    consecutive_above = 0
    # We look for the most recent sequence of 3+ days above MA5 with new highs
    # ending between idx-3 and idx-1 (the uptrend must have been established before the pullback)

    # Find sequence: at least 3 consecutive days where close > MA5 and close > prev close
    found_sequence = False
    sequence_end = -1  # index where the uptrend sequence ends
    for end in range(idx - 1, 3, -1):
        count = 0
        for j in range(end, 0, -1):
            if math.isnan(ma5_series[j]) or ma5_series[j] <= 0:
                break
            if closes[j] > ma5_series[j] and (j == end or closes[j] > closes[j - 1]):
                count += 1
            else:
                break
        if count >= 3:
            found_sequence = True
            sequence_end = end
            break

    if not found_sequence:
        return False

    # Check for bearish candle (pullback) in the last 2 days (idx-1 or idx)
    # The pullback should occur after the uptrend sequence
    pullback_found = False
    for pi in range(max(sequence_end + 1, idx - 2), idx + 1):
        if closes[pi] < opens[pi]:  # bearish candle
            pullback_found = True
            break

    if not pullback_found:
        return False

    # Current bar: open near MA5 (within 1.5%)
    if ma5 > 0:
        dist = abs(curr_open - ma5) / ma5
        if dist <= 0.015:
            return True

    return False


def exit_ma5_monster(bars_upto: list[dict], entry_idx: int, current_idx: int, entry_price: float) -> tuple[bool, float, str]:
    """
    Exit rule: close below MA5.
    """
    ma5 = compute_sma(bars_upto[:current_idx + 1], "close", 5)
    close = _sf(bars_upto[current_idx]["close"])
    if close < ma5:
        return (True, close, "Close < MA5")
    return (False, close, "")


# ═══════════════════════════════════════════════════════════════
# Strategy 2: Lotus Rising / Dragon Emerging (出水芙蓉)
# ═══════════════════════════════════════════════════════════════

def detect_lotus_rising(bars_lookback: list[dict], idx: int) -> bool:
    """
    Conditions:
    1. MA5, MA10, MA20 converging from different directions into narrow range
       - max(ma5,ma10,ma20) / min(ma5,ma10,ma20) - 1 < 1.5% (very tight convergence)
       - Check convergence at idx-1 (yesterday)
    2. Current day (idx): high-volume long bullish candle
       - close > open (bullish)
       - body > 3% (long candle)
       - volume > 1.5x 20-day average
       - close > ma5 AND close > ma10 AND close > ma20 (breaks above all 3 MAs)
       - low < min(ma5, ma10, ma20) (pierced through from below, or close enough)
    """
    if idx < 20:
        return False

    lookback = bars_lookback[:idx + 1]
    closes = [_sf(b["close"]) for b in lookback]
    opens = [_sf(b["open"]) for b in lookback]
    highs = [_sf(b["high"]) for b in lookback]
    lows = [_sf(b["low"]) for b in lookback]
    vols = [_sf(b["volume"]) for b in lookback]

    # MA convergence at idx-1
    ma5_prev = compute_sma(bars_lookback[:idx], "close", 5)
    ma10_prev = compute_sma(bars_lookback[:idx], "close", 10)
    ma20_prev = compute_sma(bars_lookback[:idx], "close", 20)

    if ma5_prev <= 0 or ma10_prev <= 0 or ma20_prev <= 0:
        return False

    ma_max_prev = max(ma5_prev, ma10_prev, ma20_prev)
    ma_min_prev = min(ma5_prev, ma10_prev, ma20_prev)
    convergence = (ma_max_prev / ma_min_prev - 1) * 100

    if convergence > 1.5:  # Must be tightly converged
        return False

    # Check MAs come from different directions
    # MA5 should not be monotonically above/below MA10 (check slope differences)
    ma5_5d_ago = compute_sma(bars_lookback[:idx - 4], "close", 5) if idx >= 5 else 0
    ma10_5d_ago = compute_sma(bars_lookback[:idx - 4], "close", 10) if idx >= 5 else 0
    ma20_5d_ago = compute_sma(bars_lookback[:idx - 4], "close", 20) if idx >= 5 else 0

    ma5_slope = ma5_prev - ma5_5d_ago if ma5_5d_ago > 0 else 0
    ma10_slope = ma10_prev - ma10_5d_ago if ma10_5d_ago > 0 else 0
    ma20_slope = ma20_prev - ma20_5d_ago if ma20_5d_ago > 0 else 0

    # At least one MA must have positive slope and one negative (converging from different directions)
    slopes = [ma5_slope, ma10_slope, ma20_slope]
    has_pos = any(s > 0.001 for s in slopes)
    has_neg = any(s < -0.001 for s in slopes)
    if not (has_pos and has_neg):
        return False

    # Current bar: high-volume long bullish candle breaking above all 3 MAs
    bar = lookback[-1]
    curr_close = closes[-1]
    curr_open = opens[-1]
    curr_vol = vols[-1]

    # Bullish candle
    if curr_close <= curr_open:
        return False

    # Long body (> 3%)
    body_pct = (curr_close - curr_open) / curr_open * 100
    if body_pct < 3.0:
        return False

    # High volume (> 1.5x 20-day avg)
    avg_vol = sum(vols[-21:-1]) / 20 if len(vols) >= 21 else sum(vols[:-1]) / max(len(vols) - 1, 1)
    if avg_vol <= 0 or curr_vol < avg_vol * 1.5:
        return False

    # Breaks above all 3 MAs (close above all, low is below at least the min MA)
    curr_ma5 = compute_sma(lookback, "close", 5)
    curr_ma10 = compute_sma(lookback, "close", 10)
    curr_ma20 = compute_sma(lookback, "close", 20)

    if not (curr_close > curr_ma5 and curr_close > curr_ma10 and curr_close > curr_ma20):
        return False

    # Must have pierced from below: low < min(all MAs at idx-1)
    curr_low = lows[-1]
    if curr_low > ma_min_prev:
        return False

    return True


def exit_lotus_rising(bars_upto: list[dict], entry_idx: int, current_idx: int, entry_price: float) -> tuple[bool, float, str]:
    """
    Exit: close below MA20 or trailing stop (trail 20% from peak).
    """
    close = _sf(bars_upto[current_idx]["close"])
    ma20 = compute_sma(bars_upto[:current_idx + 1], "close", 20)

    if close < ma20:
        return (True, close, "Close < MA20")

    return (False, close, "")


# ═══════════════════════════════════════════════════════════════
# Strategy 3: Monkey Explores (灵猴探路)
# ═══════════════════════════════════════════════════════════════

def detect_monkey_explores(bars_lookback: list[dict], idx: int) -> bool:
    """
    Conditions:
    1. MA5 crossed above MA30 or MA60 (golden cross) in last 10 days, with increasing volume
    2. Price then pulled back to the medium-term MA on decreasing volume
    3. Current bar: pullback confirms support (price near medium MA, decreasing vol), right-side signal

    We use MA30 for this (MA60 is also valid but we need more data).
    """
    if idx < 35:
        return False

    lookback = bars_lookback[:idx + 1]
    closes = [_sf(b["close"]) for b in lookback]
    vols = [_sf(b["volume"]) for b in lookback]

    # Compute MA series
    ma5_series = compute_ma(lookback, 5)
    ma30_series = compute_ma(lookback, 30)

    # Find golden cross (MA5 crossing above MA30) in last 10 days
    golden_cross_idx = -1
    for j in range(idx - 10, idx - 1):
        if j < 30 or j >= len(ma5_series) - 1:
            continue
        # Cross: MA5 was below MA30 at j-1, above at j
        if (not math.isnan(ma5_series[j - 1])) and (not math.isnan(ma30_series[j - 1])):
            if ma5_series[j - 1] <= ma30_series[j - 1] and ma5_series[j] > ma30_series[j]:
                golden_cross_idx = j
                break

    if golden_cross_idx < 0:
        return False

    # Golden cross must have increasing volume
    vol_at_cross = vols[golden_cross_idx]
    vol_5d_before = sum(vols[golden_cross_idx - 5:golden_cross_idx]) / 5 if golden_cross_idx >= 5 else 0
    if vol_5d_before > 0 and vol_at_cross < vol_5d_before * 1.2:
        return False  # Volume not increasing enough

    # After golden cross, price must pull back toward MA30 on decreasing volume
    # Find peak price after golden cross
    peak_idx = golden_cross_idx
    peak_close = closes[golden_cross_idx]
    for j in range(golden_cross_idx + 1, idx + 1):
        if closes[j] > peak_close:
            peak_idx = j
            peak_close = closes[j]

    # Pullback: price has declined from peak toward MA30
    if peak_close <= ma30_series[idx]:
        # Price already at or below MA30, pullback happened
        pass
    elif peak_idx >= idx - 3:
        # Still near peak, no meaningful pullback
        return False

    pullback_from_peak = (peak_close - closes[idx]) / peak_close * 100 if peak_close > 0 else 0
    if pullback_from_peak < 2:  # Must have pulled back at least 2%
        return False

    # Decreasing volume during pullback (current volume < average volume during golden cross period)
    current_vol = vols[idx]
    avg_vol_cross_period = sum(vols[golden_cross_idx - 2:golden_cross_idx + 3]) / 5
    if avg_vol_cross_period > 0 and current_vol > avg_vol_cross_period * 0.8:
        return False  # Volume not decreasing enough

    # Current price near MA30 (within 3%)
    if ma30_series[idx] > 0:
        dist = abs(closes[idx] - ma30_series[idx]) / ma30_series[idx]
        if dist <= 0.03:  # Within 3% of MA30 = support confirmed
            # Right-side confirmation: today close > open (bullish) or close > yesterday close
            if closes[idx] > _sf(lookback[-1]["open"]) or closes[idx] > closes[idx - 1]:
                return True

    return False


def exit_monkey_explores(bars_upto: list[dict], entry_idx: int, current_idx: int, entry_price: float) -> tuple[bool, float, str]:
    """
    Exit: below MA20 (defense line).
    """
    close = _sf(bars_upto[current_idx]["close"])
    ma20 = compute_sma(bars_upto[:current_idx + 1], "close", 20)
    if close < ma20:
        return (True, close, "Close < MA20")
    return (False, close, "")


# ═══════════════════════════════════════════════════════════════
# Strategy 4: Lotus Step (步步莲花)
# ═══════════════════════════════════════════════════════════════

def detect_lotus_step(bars_lookback: list[dict], idx: int) -> bool:
    """
    Conditions:
    1. Day idx-2 (or earlier): limit-up day (~10% gain, close == high)
    2. Day idx-1 (yesterday): gap up open, forms small bullish candle (the "lotus")
       - open > prev close (gap up)
       - body small: (close-open) / open < 3%
       - bullish: close > open
       - lotus body <= 50% of limit-up day body
    3. Day idx (today): gaps down below lotus body
       - open < yesterday's close (gaps down)
       - open is below or near lotus body low

    Entry: next day open (idx+1)
    """
    if idx < 2:
        return False

    lookback = bars_lookback[:idx + 1]
    closes = [_sf(b["close"]) for b in lookback]
    opens = [_sf(b["open"]) for b in lookback]
    highs = [_sf(b["high"]) for b in lookback]
    lows = [_sf(b["low"]) for b in lookback]

    # Find the most recent limit-up day (look back up to 5 days before yesterday)
    limit_up_idx = -1
    for j in range(idx - 1, max(idx - 5, 0), -1):
        prev_c = closes[j - 1] if j > 0 else 0
        if is_limit_up(lookback[j], prev_c):
            limit_up_idx = j
            break

    if limit_up_idx < 0:
        return False

    # Must have at least 1 day between limit-up and yesterday
    if limit_up_idx >= idx - 1:
        return False  # Yesterday wasn't a separate lotus day

    # Yesterday (idx-1): the lotus day
    lotus_open = opens[idx - 1]
    lotus_close = closes[idx - 1]
    lotus_high = highs[idx - 1]
    lotus_low = lows[idx - 1]

    # Gap up: open > prev close
    prev_close = closes[idx - 2] if idx >= 2 else 0
    if lotus_open <= prev_close:
        return False

    # Small bullish candle
    if lotus_close <= lotus_open:
        return False

    lotus_body = lotus_close - lotus_open
    lotus_body_pct = lotus_body / lotus_open * 100
    if lotus_body_pct >= 3.0:
        return False  # Not small enough

    # Lotus body <= 50% of limit-up body
    limit_up_bar = lookback[limit_up_idx]
    limit_body = _sf(limit_up_bar["close"]) - _sf(limit_up_bar["open"])
    if limit_body <= 0:
        return False
    if lotus_body > limit_body * 0.5:
        return False

    # Today (idx): gaps down below lotus body
    today_open = opens[idx]
    if today_open >= lotus_close:  # Must gap down below lotus close/body
        return False

    # Today opens below or near lotus body
    if today_open > lotus_close:  # Still above lotus body
        return False

    # Today must gap down below lotus body low (or at least within the lotus range)
    # "大幅低开莲花实体以下，是绝佳买入时机"
    if today_open >= lotus_low * 0.995:  # Must open below or very near lotus low
        return False

    return True


def exit_lotus_step(bars_upto: list[dict], entry_idx: int, current_idx: int, entry_price: float) -> tuple[bool, float, str]:
    """
    Exit: fixed 5-7% profit OR below MA5.
    """
    close = _sf(bars_upto[current_idx]["close"])
    profit = (close - entry_price) / entry_price * 100

    if profit >= 5.0:
        return (True, close, f"Target +{profit:.1f}%")

    ma5 = compute_sma(bars_upto[:current_idx + 1], "close", 5)
    if close < ma5:
        return (True, close, "Close < MA5")

    return (False, close, "")


# ═══════════════════════════════════════════════════════════════
# Strategy 5: Three Horse Carriage (三驾马车)
# ═══════════════════════════════════════════════════════════════

def detect_three_horse(bars_lookback: list[dict], idx: int) -> bool:
    """
    Conditions:
    1. MA5, MA10, MA20 were converging (tight range) at some point in last 10 days
    2. Now all 3 MAs are diverging upward
       - MA5 > MA10 > MA20 (all in order)
       - Each MA slope is positive
       - MA spread (ma5 - ma20) is expanding (larger than 5 days ago)
    """
    if idx < 25:
        return False

    lookback = bars_lookback[:idx + 1]
    closes = [_sf(b["close"]) for b in lookback]

    # Current MAs
    curr_ma5 = compute_sma(lookback, "close", 5)
    curr_ma10 = compute_sma(lookback, "close", 10)
    curr_ma20 = compute_sma(lookback, "close", 20)

    if curr_ma5 <= 0 or curr_ma10 <= 0 or curr_ma20 <= 0:
        return False

    # Must be in order: MA5 > MA10 > MA20
    if not (curr_ma5 > curr_ma10 > curr_ma20):
        return False

    # All slopes must be positive (current vs 5 days ago)
    prev_ma5 = compute_sma(bars_lookback[:idx], "close", 5) if idx >= 5 else 0
    prev_ma10 = compute_sma(bars_lookback[:idx], "close", 10) if idx >= 5 else 0
    prev_ma20 = compute_sma(bars_lookback[:idx], "close", 20) if idx >= 5 else 0

    # Use 3-day slope
    ma5_3d = compute_sma(bars_lookback[:idx - 2], "close", 5) if idx >= 7 else 0
    ma10_3d = compute_sma(bars_lookback[:idx - 2], "close", 10) if idx >= 7 else 0
    ma20_3d = compute_sma(bars_lookback[:idx - 2], "close", 20) if idx >= 7 else 0

    if ma5_3d <= 0 or ma10_3d <= 0 or ma20_3d <= 0:
        return False

    # All MAs must be rising
    if not (curr_ma5 > ma5_3d and curr_ma10 > ma10_3d and curr_ma20 > ma20_3d):
        return False

    # MA spread expanding: current spread > spread 5 days ago
    curr_spread = curr_ma5 - curr_ma20
    ma5_5d = compute_sma(bars_lookback[:idx - 4], "close", 5) if idx >= 9 else 0
    ma20_5d = compute_sma(bars_lookback[:idx - 4], "close", 20) if idx >= 9 else 0
    if ma5_5d > 0 and ma20_5d > 0:
        prev_spread = ma5_5d - ma20_5d
        if curr_spread <= prev_spread:
            return False  # Spread not expanding

    # Check convergence occurred in last 10 days (MAs were tight)
    # Look back for a period where max(ma5,ma10,ma20)/min(ma5,ma10,ma20)-1 < 2%
    convergence_found = False
    for j in range(max(idx - 10, 20), idx - 2):
        m5 = compute_sma(bars_lookback[:j + 1], "close", 5)
        m10 = compute_sma(bars_lookback[:j + 1], "close", 10)
        m20 = compute_sma(bars_lookback[:j + 1], "close", 20)
        if m5 > 0 and m10 > 0 and m20 > 0:
            ma_max = max(m5, m10, m20)
            ma_min = min(m5, m10, m20)
            if (ma_max / ma_min - 1) * 100 < 2.0:
                convergence_found = True
                break

    if not convergence_found:
        return False

    return True


def exit_three_horse(bars_upto: list[dict], entry_idx: int, current_idx: int, entry_price: float) -> tuple[bool, float, str]:
    """
    Exit: any MA begins to flatten or descend.
    Check MA slope: current MA vs 3 days ago.
    """
    ma5 = compute_sma(bars_upto[:current_idx + 1], "close", 5)
    ma10 = compute_sma(bars_upto[:current_idx + 1], "close", 10)
    ma20 = compute_sma(bars_upto[:current_idx + 1], "close", 20)

    # 3-day ago MAs
    if current_idx - entry_idx >= 3 and current_idx >= 23:
        ma5_prev = compute_sma(bars_upto[:current_idx - 2], "close", 5)
        ma10_prev = compute_sma(bars_upto[:current_idx - 2], "close", 10)
        ma20_prev = compute_sma(bars_upto[:current_idx - 2], "close", 20)

        if ma5_prev > 0 and ma10_prev > 0 and ma20_prev > 0:
            if ma5 <= ma5_prev or ma10 <= ma10_prev or ma20 <= ma20_prev:
                close = _sf(bars_upto[current_idx]["close"])
                return (True, close, "MA flattening")

    close = _sf(bars_upto[current_idx]["close"])
    return (False, close, "")


# ═══════════════════════════════════════════════════════════════
# Strategy 6: Guillotine (断头铡刀) — SELL FILTER
# ═══════════════════════════════════════════════════════════════

def detect_guillotine(bars_lookback: list[dict], idx: int) -> bool:
    """
    A long bearish candle breaks below multiple MAs (MA5, MA10, MA20, MA60).
    Used as an exit filter.

    Conditions at bar idx:
    - Bearish candle (close < open), body > 3%
    - High > MA5 and Low < min(MA5, MA10, MA20) (pierces through from above)
    """
    if idx < 60:
        return False

    lookback = bars_lookback[:idx + 1]
    bar = lookback[-1]

    close = _sf(bar["close"])
    open_p = _sf(bar["open"])
    high = _sf(bar["high"])
    low = _sf(bar["low"])

    # Bearish candle with significant body
    if close >= open_p:
        return False
    body_pct = (open_p - close) / open_p * 100
    if body_pct < 3.0:
        return False

    # Compute MAs
    ma5 = compute_sma(lookback, "close", 5)
    ma10 = compute_sma(lookback, "close", 10)
    ma20 = compute_sma(lookback, "close", 20)
    ma60 = compute_sma(lookback, "close", 60)

    if ma5 <= 0:
        return False

    ma_min = min(ma5, ma10, ma20)
    if ma60 > 0:
        ma_min = min(ma_min, ma60)

    # Pierces: high above top MA, low below bottom MA, close below all
    if high > max(ma5, ma10, ma20) and low < ma_min and close < ma_min:
        return True

    return False


# ═══════════════════════════════════════════════════════════════
# Backtest Engine
# ═══════════════════════════════════════════════════════════════

def run_strategy_backtest(
    strategy_name: str,
    detect_fn,
    exit_fn,
    all_bars: dict[str, list[dict]],
    trade_dates: list[str],
    initial_capital: float = 100000.0,
    max_positions: int = 5,
    use_guillotine_filter: bool = False,
) -> dict[str, Any]:
    """
    Run a single strategy through all dates.

    Args:
        strategy_name: Name of the strategy
        detect_fn: Function(bars_lookback, idx) -> bool (signal detected at idx)
        exit_fn: Function(bars_upto, entry_idx, current_idx, entry_price) -> (sell_triggered, sell_price, reason)
        all_bars: dict of symbol -> list of bar dicts
        trade_dates: sorted list of date strings
        initial_capital: starting capital
        max_positions: max concurrent positions
        use_guillotine_filter: if True, skip entry if guillotine detected, and exit positions on guillotine

    Returns:
        dict with backtest statistics
    """
    cash = initial_capital
    positions: dict[str, dict] = {}
    trade_log: list[dict] = []
    daily_equity: list[dict] = []
    total_commissions = 0.0
    cooldowns: dict[str, str] = {}

    # Convert trade_dates to list with date objects for hold calculation
    date_to_idx = {d: i for i, d in enumerate(trade_dates)}

    for day_idx, curr_date in enumerate(trade_dates):
        # Clean expired cooldowns
        for sym in list(cooldowns.keys()):
            if curr_date >= cooldowns[sym]:
                del cooldowns[sym]

        # ── SELL / EXIT ──
        for sym in list(positions.keys()):
            pos = positions[sym]
            bars_sym = all_bars.get(sym, [])

            # Find current day's bar for this stock
            today_bar = next((b for b in bars_sym if b["time"] == curr_date), None)
            if not today_bar:
                continue

            # T+1: cannot sell same day as buy
            if pos["entry_date"] == curr_date:
                continue

            # Suspension check
            if is_suspended(today_bar):
                continue

            # Get bars up to current date
            bars_upto = [b for b in bars_sym if is_date_before(b["time"], curr_date)]

            entry_idx_in_bars = pos.get("entry_idx", 0)
            current_idx_in_bars = len(bars_upto) - 1

            sell_triggered = False
            sell_price = _sf(today_bar["close"])
            sell_reason = ""

            # Check strategy-specific exit
            triggered, exit_p, reason = exit_fn(bars_upto, entry_idx_in_bars, current_idx_in_bars, pos["entry_price"])
            if triggered:
                sell_triggered = True
                sell_price = exit_p
                sell_reason = reason

            # Guillotine filter for exit
            if not sell_triggered and use_guillotine_filter:
                if detect_guillotine(bars_upto, current_idx_in_bars):
                    sell_triggered = True
                    sell_price = _sf(today_bar["close"])
                    sell_reason = "Guillotine"

            # Trailing stop: 8% from peak (standard for all strategies)
            if not sell_triggered:
                max_p = pos.get("max_price", pos["entry_price"])
                trail_price = max_p * 0.92  # 8% trailing stop from peak
                if _sf(today_bar["low"]) <= trail_price:
                    sell_triggered = True
                    sell_price = trail_price
                    sell_reason = f"Trail -8%"

            # Hard stop: -7%
            if not sell_triggered:
                stop_price = pos["entry_price"] * 0.93
                if _sf(today_bar["low"]) <= stop_price:
                    sell_triggered = True
                    # Conservative: gap through uses open
                    if _sf(today_bar["open"]) <= stop_price:
                        sell_price = _sf(today_bar["open"])
                        sell_reason = "Stop -7%(gap)"
                    else:
                        sell_price = stop_price
                        sell_reason = "Stop -7%"

            # Update max price
            today_high = _sf(today_bar["high"])
            if today_high > pos.get("max_price", 0):
                pos["max_price"] = today_high

            if sell_triggered:
                raw_sym = strip_suffix(sym)
                revenue = pos["qty"] * sell_price
                fee = sell_cost(revenue, raw_sym)
                cash += (revenue - fee)
                total_commissions += fee
                entry_cost = pos["qty"] * pos["entry_price"]
                pnl = (revenue - fee) - entry_cost
                pnl_pct = pnl / entry_cost * 100

                entry_d = dt.date.fromisoformat(pos["entry_date"])
                exit_d = dt.date.fromisoformat(curr_date)
                hold_days = (exit_d - entry_d).days

                trade_log.append({
                    "date": curr_date, "direction": "SELL",
                    "symbol": sym, "price": sell_price, "qty": pos["qty"],
                    "pnl": pnl, "pnl_pct": pnl_pct,
                    "hold_days": hold_days, "reason": sell_reason,
                    "entry_date": pos["entry_date"],
                    "entry_price": pos["entry_price"],
                })
                cooldowns[sym] = (exit_d + dt.timedelta(days=5)).isoformat()
                del positions[sym]

        # ── BUY / ENTRY ──
        if len(positions) >= max_positions:
            continue

        for sym, bars in all_bars.items():
            if len(positions) >= max_positions:
                break
            if sym in positions:
                continue
            if sym in cooldowns:
                continue

            # Get bars up to current date
            bars_upto = [b for b in bars if is_date_before(b["time"], curr_date)]
            if len(bars_upto) < 30:
                continue

            current_idx = len(bars_upto) - 1
            today_bar = bars_upto[-1]
            today_close = _sf(today_bar["close"])

            # Skip if today's bar is invalid
            if is_suspended(today_bar):
                continue

            # Skip if today is limit up (can't buy)
            prev_close = _sf(bars_upto[-2]["close"]) if len(bars_upto) >= 2 else 0
            if is_limit_up(today_bar, prev_close):
                continue

            # Guillotine filter: skip if guillotine detected today
            if use_guillotine_filter and detect_guillotine(bars_upto, current_idx):
                continue

            # Detect signal
            if not detect_fn(bars_upto, current_idx):
                continue

            # T+1: execute on next day's open
            entry_date_idx = day_idx + 1
            if entry_date_idx >= len(trade_dates):
                continue
            entry_date = trade_dates[entry_date_idx]

            entry_bar = next((b for b in bars if b["time"] == entry_date), None)
            if not entry_bar:
                continue
            entry_price = _sf(entry_bar["open"])
            if entry_price <= 0:
                continue

            # Skip if entry bar is suspended or limit up
            if is_suspended(entry_bar):
                continue
            if is_limit_up(entry_bar):
                continue

            # Position sizing: equal allocation
            allocation_per_position = min(cash * 0.2, cash / max(1, max_positions - len(positions)))
            qty = int(allocation_per_position / entry_price / 100) * 100
            if qty < 100:
                continue

            cost = qty * entry_price
            raw_sym = strip_suffix(sym)
            commission = buy_cost(cost, raw_sym)
            if cash < cost + commission:
                # Try smaller position
                qty = int((cash * 0.8) / entry_price / 100) * 100
                if qty < 100:
                    continue
                cost = qty * entry_price
                commission = buy_cost(cost, raw_sym)
                if cash < cost + commission:
                    continue

            cash -= (cost + commission)
            total_commissions += commission

            # Find idx of entry bar in the full bar series
            entry_idx_full = next((i for i, b in enumerate(bars) if b["time"] == entry_date), current_idx)

            positions[sym] = {
                "sym": sym,
                "qty": qty,
                "entry_price": entry_price,
                "entry_date": entry_date,
                "entry_idx": entry_idx_full,
                "max_price": entry_price,
            }

            trade_log.append({
                "date": entry_date, "direction": "BUY",
                "symbol": sym, "price": entry_price, "qty": qty,
                "reason": strategy_name,
            })

        # ── Daily settlement ──
        pos_val = 0.0
        for sym, p in positions.items():
            cb = next((b for b in all_bars.get(sym, []) if b["time"] == curr_date), None)
            cp = _sf(cb["close"]) if cb else p["entry_price"]
            pos_val += p["qty"] * cp

        daily_equity.append({
            "date": curr_date,
            "cash": round(cash, 2),
            "pos_val": round(pos_val, 2),
            "total": round(cash + pos_val, 2),
            "holdings": len(positions),
        })

    # ── Force close remaining positions at end ──
    final_date = trade_dates[-1] if trade_dates else "2026-09-30"
    for sym in list(positions.keys()):
        pos = positions[sym]
        bars_sym = all_bars.get(sym, [])
        final_bar = next((b for b in bars_sym if b["time"] == final_date), None)
        sell_price = _sf(final_bar["close"]) if final_bar else pos["entry_price"]

        raw_sym = strip_suffix(sym)
        revenue = pos["qty"] * sell_price
        fee = sell_cost(revenue, raw_sym)
        cash += (revenue - fee)
        total_commissions += fee
        entry_cost = pos["qty"] * pos["entry_price"]
        pnl = (revenue - fee) - entry_cost
        pnl_pct = pnl / entry_cost * 100

        entry_d = dt.date.fromisoformat(pos["entry_date"])
        exit_d = dt.date.fromisoformat(final_date)
        hold_days = (exit_d - entry_d).days

        trade_log.append({
            "date": final_date, "direction": "SELL",
            "symbol": sym, "price": sell_price, "qty": pos["qty"],
            "pnl": pnl, "pnl_pct": pnl_pct,
            "hold_days": hold_days, "reason": "End forced close",
            "entry_date": pos["entry_date"],
            "entry_price": pos["entry_price"],
        })
        del positions[sym]

    # ── Statistics ──
    final_equity = daily_equity[-1]["total"] if daily_equity else initial_capital
    net = final_equity - initial_capital
    ret = net / initial_capital * 100

    closed = [t for t in trade_log if t["direction"] == "SELL"]
    wins = [t for t in closed if t.get("pnl", 0) > 0]
    losses = [t for t in closed if t.get("pnl", 0) <= 0]
    wr = len(wins) / len(closed) * 100 if closed else 0

    tp = sum(t["pnl"] for t in wins) or 0
    tl = abs(sum(t["pnl"] for t in losses)) or 1
    pf = tp / tl

    avg_win = tp / len(wins) if wins else 0
    avg_loss = -tl / len(losses) if losses else 0

    # Max drawdown
    peak = initial_capital
    mdd = 0.0
    for eq in daily_equity:
        if eq["total"] > peak:
            peak = eq["total"]
        dd = (peak - eq["total"]) / peak * 100
        if dd > mdd:
            mdd = dd

    # Sharpe ratio (approximate)
    if len(daily_equity) > 1:
        daily_returns = []
        for i in range(1, len(daily_equity)):
            prev = daily_equity[i - 1]["total"]
            curr = daily_equity[i]["total"]
            if prev > 0:
                daily_returns.append((curr - prev) / prev)
        avg_daily_ret = sum(daily_returns) / len(daily_returns) if daily_returns else 0
        if len(daily_returns) > 1:
            variance = sum((r - avg_daily_ret) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
            daily_std = variance ** 0.5
            sharpe = (avg_daily_ret / daily_std * (252 ** 0.5)) if daily_std > 0 else 0
        else:
            sharpe = 0
    else:
        sharpe = 0

    avg_hold = sum(t.get("hold_days", 0) for t in closed) / len(closed) if closed else 0

    return {
        "strategy": strategy_name,
        "initial_capital": initial_capital,
        "final_equity": final_equity,
        "net_pnl": net,
        "return_pct": ret,
        "num_trades": len(closed),
        "win_rate": wr,
        "num_wins": len(wins),
        "num_losses": len(losses),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "max_drawdown": mdd,
        "sharpe": sharpe,
        "profit_factor": pf,
        "avg_hold_days": avg_hold,
        "total_commissions": total_commissions,
        "trade_log": trade_log,
        "daily_equity": daily_equity,
    }


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    import time
    start_time = time.time()

    # Load kline data
    print("Loading kline cache...")
    with open(PROJECT_ROOT / "data" / "kline_cache.json") as f:
        raw_data = json.load(f)
    print(f"Loaded {len(raw_data)} stocks from cache")

    # Determine date range: use most recent 3 months with complete data
    # Check last date
    last_dates = set()
    for sym, bars in raw_data.items():
        if bars:
            last_dates.add(bars[-1]["time"][:10])
    max_last_date = max(last_dates)
    print(f"Max last date in data: {max_last_date}")

    # Use 2026-07-01 to 2026-09-30 as the 3-month window
    start_date = "2026-07-01"
    end_date = "2026-09-30"

    # Get all trade dates from index (use any stock with full data)
    all_trade_dates = set()
    for sym, bars in raw_data.items():
        for b in bars:
            d = b["time"][:10]
            if start_date <= d <= end_date:
                all_trade_dates.add(d)
    trade_dates = sorted(all_trade_dates)
    print(f"Trading days in window: {len(trade_dates)} ({trade_dates[0]} to {trade_dates[-1]})")

    # Pre-filter stocks: need at least 60 bars before start_date for MA60 computation
    qualified_stocks = {}
    for sym, bars in raw_data.items():
        bars_before_window = [b for b in bars if b["time"][:10] < start_date]
        bars_in_window = [b for b in bars if start_date <= b["time"][:10] <= end_date]
        if len(bars_before_window) >= 80 and len(bars_in_window) >= 10:
            qualified_stocks[sym] = bars
    print(f"Qualified stocks (>=80 bars before window): {len(qualified_stocks)}")

    # Define strategies
    strategies = [
        ("MA5捉妖战法", detect_ma5_monster, exit_ma5_monster, False),
        ("出水芙蓉", detect_lotus_rising, exit_lotus_rising, True),
        ("灵猴探路", detect_monkey_explores, exit_monkey_explores, True),
        ("步步莲花", detect_lotus_step, exit_lotus_step, True),
        ("三驾马车", detect_three_horse, exit_three_horse, True),
    ]

    results = []
    for strategy_name, detect_fn, exit_fn, use_guillotine in strategies:
        print(f"\n{'='*80}")
        print(f"Running: {strategy_name}")
        print(f"{'='*80}")

        result = run_strategy_backtest(
            strategy_name=strategy_name,
            detect_fn=detect_fn,
            exit_fn=exit_fn,
            all_bars=qualified_stocks,
            trade_dates=trade_dates,
            initial_capital=100000.0,
            max_positions=5,
            use_guillotine_filter=use_guillotine,
        )
        results.append(result)

        # Print summary
        print(f"  Return: {result['return_pct']:+.2f}%")
        print(f"  Trades: {result['num_trades']}")
        print(f"  Win Rate: {result['win_rate']:.1f}% ({result['num_wins']}W / {result['num_losses']}L)")
        print(f"  Avg Win: {result['avg_win']:+.2f}  Avg Loss: {result['avg_loss']:+.2f}")
        print(f"  Max DD: {result['max_drawdown']:.2f}%  Sharpe: {result['sharpe']:.2f}")
        print(f"  Profit Factor: {result['profit_factor']:.2f}")
        print(f"  Avg Hold: {result['avg_hold_days']:.1f} days")
        print(f"  Commissions: {result['total_commissions']:.2f}")

    # Rank by return
    results.sort(key=lambda r: r["return_pct"], reverse=True)

    elapsed = time.time() - start_time
    print(f"\n{'='*80}")
    print(f"RANKING (by return):")
    print(f"{'='*80}")
    for i, r in enumerate(results):
        emoji = "✅" if r["return_pct"] > 0 else "❌"
        print(f"  {i+1}. {emoji} {r['strategy']}: {r['return_pct']:+.2f}% | WR:{r['win_rate']:.0f}% | Trades:{r['num_trades']} | PF:{r['profit_factor']:.2f} | Sharpe:{r['sharpe']:.2f}")

    print(f"\nTotal time: {elapsed:.1f}s")

    # Save results to JSON for report generation
    # Strip trade logs to avoid huge JSON
    results_for_json = []
    for r in results:
        r_copy = {k: v for k, v in r.items() if k not in ("trade_log", "daily_equity")}
        results_for_json.append(r_copy)

    # Also save the best strategy's trade log (first 5 trades)
    best = results[0]
    results_for_json[0]["sample_trades"] = [t for t in best["trade_log"] if t["direction"] == "SELL"][:5]

    output_path = PROJECT_ROOT / "data" / "ma_strategy_results.json"
    with open(output_path, "w") as f:
        json.dump(results_for_json, f, ensure_ascii=False, indent=2, default=str)
    print(f"Results saved to {output_path}")

    # Also print full trade log of best strategy
    print(f"\n{'='*80}")
    print(f"BEST STRATEGY: {best['strategy']} — Trade Log")
    print(f"{'='*80}")
    print(f"{'Entry':<12} {'Exit':<12} {'Symbol':<14} {'Entry$':>8} {'Exit$':>8} {'Pnl':>8} {'Pnl%':>7} {'Hold':>5}  Reason")
    print("-" * 100)
    sell_trades = [t for t in best["trade_log"] if t["direction"] == "SELL"]
    for t in sell_trades:
        print(f"{t.get('entry_date','?'):<12} {t['date']:<12} {t['symbol']:<14} {t.get('entry_price',0):>8.2f} {t['price']:>8.2f} {t['pnl']:>+8.2f} {t['pnl_pct']:>+6.2f}% {t['hold_days']:>4}d  {t['reason']}")


if __name__ == "__main__":
    main()
