#!/usr/bin/env python3
"""
Astock 缠论策略回测引擎 v3 — 多周期 + 信号评分 + 市场状态融合.

相较 v2 的改进:
  1. 多周期确认: 周线趋势过滤 (只有周线 uptrend/range 才接受日线买点)
  2. 信号强度评分 (0-100): 融合趋势共振/买点类型/成交量/RSI/情绪相位
  3. 市场状态融合: 从 market_regime.json 读取标准市况, 动态调节仓位
  4. 差异化仓位: 强信号重仓, 弱信号轻仓
  5. 全面统计: 按信号类型、趋势类型统计胜率/盈亏比
  6. 持仓天数统计

用法:
  python3 -m scripts.backtest_engine --pool 20 --capital 400000
  python3 -m scripts.backtest_engine --symbols 000001.SH,600519.SH --start 2026-06-01 --end 2026-09-01
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from mcp_client import get_mcp_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.chanlun_engine import analyze_chanlun, normalize_bars
from data import get_data_manager

CST = dt.timezone(dt.timedelta(hours=8))

# ── 默认股票池: 沪深300核心成分（各行业龙头）──
DEFAULT_POOL = [
    "600519.SH", "000858.SZ", "601899.SH", "600036.SH",
    "002594.SZ", "300750.SZ", "688981.SH", "000333.SZ",
    "601318.SH", "600900.SH", "002415.SZ", "600276.SH",
    "000568.SZ", "002714.SZ", "601012.SH", "600309.SH",
    "000725.SZ", "601166.SH", "002475.SZ", "600585.SH",
]


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def fetch_klines(symbol: str, period: str = "D", count: int = 200) -> list[dict[str, Any]]:
    try:
        raw = get_mcp_client().fetch_klines(symbol, period=period, count=count)
        if not raw:
            return []
        bars = normalize_bars(raw)
        for b in bars:
            if isinstance(b, dict) and isinstance(b.get("time"), dt.datetime):
                b["time"] = b["time"].strftime("%Y-%m-%d")
        return bars
    except Exception:
        return []


def sma(bars: list[dict[str, Any]], key: str = "volume", period: int = 20) -> float:
    vals = [float(b.get(key, 0) or 0) for b in bars[-period:] if b.get(key)]
    return sum(vals) / len(vals) if vals else 0


def compute_rsi(bars: list[dict], period: int = 14) -> float:
    closes = [float(b.get("close", 0) or 0) for b in bars if b.get("close")]
    if len(closes) < period + 1:
        return 50.0
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        chg = closes[i] - closes[i - 1]
        gains += max(chg, 0)
        losses += max(-chg, 0)
    avg_g = gains / period
    avg_l = losses / period or 0.01
    return 100 - 100 / (1 + avg_g / avg_l)


def compute_ma_trend(bars: list[dict]) -> str:
    """Calculate MA trend direction from last 20 bars using multi-MA alignment."""
    closes = [b.get("close", 0) for b in bars if b.get("close")]
    if len(closes) < 20:
        return "unknown"
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10
    ma20 = sum(closes[-20:]) / 20
    close = closes[-1]
    if close > ma5 > ma10 > ma20:
        return "strong_up"
    elif close > ma5 > ma10:
        return "up"
    elif close < ma5 < ma10 and close < ma20:
        return "down"
    elif close < ma5 < ma10 < ma20:
        return "strong_down"
    else:
        return "range"


def compute_vol_ratio(bars: list[dict]) -> float:
    """Current volume / 20-day average volume."""
    if len(bars) < 21:
        return 1.0
    current_vol = _safe_float(bars[-1].get("volume"))
    avg_vol = sma(bars[:-1], "volume", 20) if len(bars) > 21 else sma(bars, "volume", 20)
    return current_vol / avg_vol if avg_vol > 0 else 1.0


def buy_signal_from_chanlun(analysis: dict[str, Any]) -> str | None:
    bp = analysis.get("buy_point")
    if bp:
        return bp
    bo = analysis.get("breakout_signal", {})
    if isinstance(bo, dict) and bo.get("buy_point"):
        return bo["buy_point"]
    return None


def load_market_regime() -> dict[str, Any]:
    """Load market regime with defensive defaults."""
    default = {
        "standard_regime": "warmup",
        "regime_multiplier": 0.45,
        "sell_only_mode": False,
        "fail_closed": False,
    }
    try:
        dm = get_data_manager()
        regime = dm.load_state("market_regime.json")
        if regime:
            rm = float(regime.get("regime_multiplier", 0.45))
            standard = str(regime.get("standard_regime", "warmup"))
            return {
                "standard_regime": standard,
                "regime_multiplier": rm,
                "sell_only_mode": regime.get("sell_only_mode") is True,
                "fail_closed": regime.get("fail_closed") is True,
                "description": regime.get("description", ""),
                "blocked_market_types": regime.get("blocked_market_types", []),
            }
    except Exception:
        pass
    return default


def compute_signal_score(
    buy_point: str | None,
    weekly_trend: str,
    daily_trend: str,
    vol_ratio: float,
    rsi: float,
    sentiment_mult: float,
) -> dict[str, Any]:
    """Score a signal 0-100 based on confluence factors.

    Scoring breakdown:
      - Trend alignment (30 pts): weekly+daily trend match
      - Buy point quality (25 pts): 三买=25, 二买=18, 一买=10, breakout=15
      - Volume confirmation (15 pts): vol ratio tiers
      - RSI zone (15 pts): ideal zone bonus
      - Sentiment phase (15 pts): market sentiment multiplier scaled
    """
    scores = {}
    reasons = []

    # 1. Trend alignment (30 pts)
    weekly_ok = weekly_trend in ("uptrend", "range")
    daily_ok = daily_trend in ("uptrend", "range")
    if weekly_trend == "uptrend" and daily_trend == "uptrend":
        trend_pts = 30
        reasons.append("周线+日线双多头")
    elif weekly_trend == "uptrend" and daily_trend == "range":
        trend_pts = 24
        reasons.append("周线多头+日线震荡")
    elif weekly_trend == "range" and daily_trend == "uptrend":
        trend_pts = 22
        reasons.append("周线震荡+日线多头")
    elif weekly_trend == "range" and daily_trend == "range":
        trend_pts = 18
        reasons.append("双震荡")
    elif weekly_ok and not daily_ok:
        trend_pts = 10
        reasons.append("周线可+日线下行")
    elif not weekly_ok and daily_ok:
        trend_pts = 6
        reasons.append("周线下行+日线可(逆势)")
    else:
        trend_pts = 2
        reasons.append("双下行(规避)")
    scores["trend_alignment"] = trend_pts

    # 2. Buy point quality (25 pts)
    # Calibrated weights: 一买 (divergence bottom) outperforms 二买 (range retrace)
    bp_map = {"三买": 25, "一买": 18, "二买": 14}
    bp_pts = bp_map.get(buy_point, 8)
    if buy_point:
        reasons.append(f"{buy_point}={bp_pts}分")
    scores["buy_point_quality"] = bp_pts

    # 3. Volume confirmation (15 pts)
    if vol_ratio >= 2.0:
        vol_pts = 15
        reasons.append(f"放量{vol_ratio:.1f}x")
    elif vol_ratio >= 1.5:
        vol_pts = 12
        reasons.append(f"放量{vol_ratio:.1f}x")
    elif vol_ratio >= 1.0:
        vol_pts = 8
        reasons.append(f"平量{vol_ratio:.1f}x")
    elif vol_ratio >= 0.7:
        vol_pts = 5
        reasons.append(f"缩量{vol_ratio:.1f}x")
    else:
        vol_pts = 2
        reasons.append(f"地量{vol_ratio:.1f}x")
    scores["volume"] = vol_pts

    # 4. RSI zone (15 pts)
    if 30 <= rsi <= 45:
        rsi_pts = 15
        reasons.append(f"RSI{rsi:.0f}理想")
    elif 45 < rsi <= 55:
        rsi_pts = 12
        reasons.append(f"RSI{rsi:.0f}中性")
    elif 20 <= rsi < 30:
        rsi_pts = 10
        reasons.append(f"RSI{rsi:.0f}超卖边缘")
    elif 55 < rsi <= 65:
        rsi_pts = 8
        reasons.append(f"RSI{rsi:.0f}偏高")
    elif rsi < 20:
        rsi_pts = 5
        reasons.append(f"RSI{rsi:.0f}深度超卖")
    else:
        rsi_pts = 2
        reasons.append(f"RSI{rsi:.0f}超买")
    scores["rsi"] = rsi_pts

    # 5. Sentiment phase (15 pts) — map sentiment multiplier to score
    if sentiment_mult >= 0.7:
        sent_pts = 15
    elif sentiment_mult >= 0.4:
        sent_pts = 10
    elif sentiment_mult >= 0.2:
        sent_pts = 5
    else:
        sent_pts = 1
    scores["sentiment"] = sent_pts

    total = sum(scores.values())
    grade = (
        "A" if total >= 75 else
        "B" if total >= 55 else
        "C" if total >= 35 else
        "D"
    )
    return {
        "total": total,
        "grade": grade,
        "components": scores,
        "reasons": reasons,
    }


def compute_regime_sentiment(
    index_bars: list[dict],
    curr_date: str,
    regime: dict[str, Any],
) -> tuple[str, float]:
    """Enhanced sentiment that combines regime state and index multi-day trend.

    Returns (phase, multiplier).
    """
    # If market regime says sell-only or fail-closed, force ice
    if regime.get("sell_only_mode") or regime.get("fail_closed"):
        return "ice", 0.0

    # Get regime multiplier from state
    reg_mult = regime.get("regime_multiplier", 0.45)

    # Compute multi-day index trend (last 5 days)
    idx_bars_til = [b for b in index_bars if str(b.get("time", "")) <= curr_date]
    if len(idx_bars_til) >= 5:
        recent = idx_bars_til[-5:]
        chgs = []
        for b in recent:
            o = _safe_float(b.get("open"))
            c = _safe_float(b.get("close"))
            if o > 0:
                chgs.append((c - o) / o * 100)
        avg_5d_chg = sum(chgs) / len(chgs) if chgs else 0
        # 3-day momentum
        if len(recent) >= 3:
            mom = (recent[-1]["close"] - recent[-3]["close"]) / recent[-3]["close"] * 100
        else:
            mom = 0
    else:
        avg_5d_chg = 0
        mom = 0

    # Single-day change
    idx_bar = next((b for b in index_bars if str(b.get("time", "")) == curr_date), None)
    if idx_bar:
        o = _safe_float(idx_bar.get("open"))
        c = _safe_float(idx_bar.get("close"))
        chg = (c - o) / max(o, 0.01) * 100 if o > 0 else 0
    else:
        chg = 0

    # Blend: combine single-day change with 5-day avg and regime multiplier
    blended = chg * 0.4 + avg_5d_chg * 0.3 + mom * 0.3

    if blended > 1.0:
        phase, mult = "euphoria", min(0.85, reg_mult * 1.3)
    elif blended >= 0.3:
        phase, mult = "hot", min(0.75, reg_mult * 1.2)
    elif blended >= -0.3:
        phase, mult = "warmup", min(0.60, reg_mult)
    elif blended >= -1.0:
        phase, mult = "cooldown", min(0.35, reg_mult * 0.7)
    else:
        phase, mult = "ice", min(0.15, reg_mult * 0.3)

    return phase, round(mult, 3)


def run_backtest(
    symbols: list[str],
    start_date: str,
    end_date: str,
    initial_capital: float = 400000.0,
) -> dict[str, Any]:
    # ── 0. 加载市场状态 ──
    regime = load_market_regime()
    print(f"市场状态: {regime['standard_regime']} | 乘数: {regime['regime_multiplier']}")
    if regime.get("sell_only_mode") or regime.get("fail_closed"):
        print("!!! 市场处于防御模式 (sell_only/fail_closed) !!!")
    print()

    # ── 1. 数据准备 ──
    all_bars: dict[str, list[dict[str, Any]]] = {}
    weekly_bars: dict[str, list[dict[str, Any]]] = {}
    weekly_trends: dict[str, str] = {}
    for sym in symbols:
        bars = fetch_klines(sym, period="D", count=200)
        if len(bars) >= 80:
            all_bars[sym] = bars
        else:
            print(f"  {sym}: 日线不足 ({len(bars)}), 跳过")
            continue
        w_bars = fetch_klines(sym, period="W", count=100)
        if len(w_bars) >= 20:
            weekly_bars[sym] = w_bars
        else:
            # Fall back to daily for weekly trend
            weekly_bars[sym] = bars
        # Pre-compute weekly trend from latest available data
        w_analysis = analyze_chanlun(w_bars) if len(w_bars) >= 20 else analyze_chanlun(bars)
        weekly_trends[sym] = w_analysis.get("trend_type", "range")

    if not all_bars:
        print("无足够K线")
        return {}

    # ── 市场健康度检查: 多少股票周线多头? ──
    weekly_uptrend_count = sum(1 for t in weekly_trends.values() if t in ("uptrend", "range"))
    weekly_uptrend_pct = weekly_uptrend_count / len(weekly_trends) * 100 if weekly_trends else 0
    print(f"市场健康度: {weekly_uptrend_pct:.0f}% 标的周线处于多头/震荡 ({weekly_uptrend_count}/{len(weekly_trends)})")
    if weekly_uptrend_pct < 25:
        print("!!! 警告: 不足25%标的周线多头, 市场整体弱势, 大幅收紧交易条件 !!!")
    print()

    index_bars = fetch_klines("000001.SH", count=200)
    trade_dates = sorted({
        str(b["time"]) for b in index_bars
        if start_date <= str(b["time"]) <= end_date
    })
    if len(trade_dates) < 10:
        print(f"交易日不足 ({len(trade_dates)})")
        return {}

    print(f"股票池: {len(all_bars)} 只 | 交易日: {len(trade_dates)} ({trade_dates[0]} ~ {trade_dates[-1]})")
    print(f"初始资金: {initial_capital:,.2f}")
    print("=" * 100)

    # ── 2. 账户状态 ──
    cash = initial_capital
    positions: dict[str, dict[str, Any]] = {}
    trade_log: list[dict[str, Any]] = []
    daily_equity: list[dict[str, Any]] = []
    cooldowns: dict[str, str] = {}
    total_commissions = 0.0
    max_positions = 5
    cooldown_days = 10
    min_score_threshold = 55  # Minimum signal score to consider

    # ── 动态仓位上限: 弱势市场降仓位 ──
    effective_max_positions = max_positions
    if weekly_uptrend_pct < 25:
        effective_max_positions = min(max_positions, 3)
        min_score_threshold = max(min_score_threshold, 55)
    elif weekly_uptrend_pct < 35:
        effective_max_positions = min(max_positions, 4)
        min_score_threshold = max(min_score_threshold, 50)

    # Stats by signal type
    stats_by_signal: dict[str, dict] = {}
    stats_by_grade: dict[str, dict] = {}

    for day_idx, curr_date in enumerate(trade_dates):
        # ── 清理过期冷却 ──
        for sym in list(cooldowns.keys()):
            if curr_date >= cooldowns[sym]:
                del cooldowns[sym]

        # ── 增强情绪相位 (多日趋势 + 市场状态) ──
        sent_phase, sent_mult = compute_regime_sentiment(index_bars, curr_date, regime)

        # ── 3. 买入信号 (带评分) ──
        if sent_mult > 0.15 and len(positions) < effective_max_positions:
            # Re-score candidate signals, sort by score
            candidates = []
            for sym in all_bars:
                if sym in positions:
                    continue
                if sym in cooldowns and curr_date < cooldowns[sym]:
                    continue
                if len(positions) >= effective_max_positions:
                    break

                bars = all_bars[sym]
                lookback = [b for b in bars if str(b.get("time", "")) <= curr_date]
                if len(lookback) < 60:
                    continue

                # Daily analysis
                analysis = analyze_chanlun(lookback)
                bp = buy_signal_from_chanlun(analysis)
                if not bp:
                    continue
                daily_trend = analysis.get("trend_type", "range")

                # 一买只在 downtrend 末尾或 range 中接受
                if bp == "一买" and daily_trend not in ("downtrend", "range"):
                    continue
                # 二买需要 uptrend 或 range
                if bp == "二买" and daily_trend not in ("uptrend", "range"):
                    continue

                # Weekly trend analysis
                w_bars_all = weekly_bars.get(sym, bars)
                w_lookback = [b for b in w_bars_all if str(b.get("time", "")) <= curr_date]
                if len(w_lookback) >= 20:
                    w_analysis = analyze_chanlun(w_lookback)
                    weekly_trend = w_analysis.get("trend_type", "range")
                else:
                    weekly_trend = daily_trend  # fallback

                # Strict weekly trend filter: skip ALL weekly downtrend stocks
                # In a bear market, even oversold bounces fail
                if weekly_trend == "downtrend":
                    continue

                # MA trend filter: price should not be too far below MA20
                # (avoids catching falling knives unless deeply oversold)
                closes_ma = [b.get("close", 0) for b in lookback if b.get("close")]
                ma20 = sum(closes_ma[-20:]) / 20 if len(closes_ma) >= 20 else 0
                last_close = closes_ma[-1] if closes_ma else 0
                if ma20 > 0 and last_close < ma20 * 0.92 and rsi > 25:
                    # Price more than 8% below MA20 and not deeply oversold = skip
                    continue

                # Volume confirmation
                vol = _safe_float(lookback[-1].get("volume"))
                avg_vol = sma(lookback, "volume", 20)
                has_volume = vol >= avg_vol * 0.8 if avg_vol > 0 else True
                if not has_volume:
                    continue
                vol_ratio = vol / avg_vol if avg_vol > 0 else 1.0

                # RSI filter
                rsi = compute_rsi(lookback)
                if rsi > 68:
                    continue  # Skip overbought

                # Compute signal score
                score_result = compute_signal_score(
                    buy_point=bp,
                    weekly_trend=weekly_trend,
                    daily_trend=daily_trend,
                    vol_ratio=vol_ratio,
                    rsi=rsi,
                    sentiment_mult=sent_mult,
                )

                # 二买 requires higher minimum score (weakest signal in this regime)
                bp_type = cand_bp if locals().get('cand_bp') else bp
                if bp == "二买" and score_result["total"] < max(min_score_threshold, 65):
                    continue
                if score_result["total"] < min_score_threshold:
                    continue

                candidates.append({
                    "sym": sym,
                    "bp": bp,
                    "daily_trend": daily_trend,
                    "weekly_trend": weekly_trend,
                    "score": score_result["total"],
                    "grade": score_result["grade"],
                    "vol_ratio": vol_ratio,
                    "rsi": rsi,
                    "score_result": score_result,
                })

            # Sort candidates by score descending, take best
            candidates.sort(key=lambda c: c["score"], reverse=True)
            for cand in candidates:
                if len(positions) >= effective_max_positions:
                    break
                if cand["sym"] in positions:
                    continue
                if cand["sym"] in cooldowns and curr_date < cooldowns[cand["sym"]]:
                    continue

                sym = cand["sym"]
                bars = all_bars[sym]
                lookback = [b for b in bars if str(b.get("time", "")) <= curr_date]

                entry_date_idx = day_idx + 1
                if entry_date_idx >= len(trade_dates):
                    continue
                entry_date = trade_dates[entry_date_idx]
                entry_bar = next((b for b in bars if str(b.get("time", "")) == entry_date), None)
                if not entry_bar:
                    continue
                entry_price = _safe_float(entry_bar.get("open"))
                if entry_price <= 0:
                    continue

                # ── 差异化仓位: 根据评分调节 ──
                score = cand["score"]
                remaining = effective_max_positions - len(positions)

                # Position size factor: score 0-100 → factor 0.3-1.0
                if score >= 75:
                    pos_factor = 1.0
                elif score >= 55:
                    pos_factor = 0.8
                elif score >= 40:
                    pos_factor = 0.6
                else:
                    pos_factor = 0.4

                base_allocation = cash * sent_mult * pos_factor
                target_amount = base_allocation / max(remaining, 1)

                # Minimum meaningful position
                min_amount = 20000
                if target_amount < min_amount:
                    target_amount = min_amount

                qty = int(target_amount / entry_price / 100) * 100
                if qty < 100:
                    continue
                cost = qty * entry_price
                commission = cost * 0.0003
                if cash < cost + commission:
                    continue

                cash -= (cost + commission)
                total_commissions += commission
                positions[sym] = {
                    "sym": sym, "qty": qty,
                    "entry_price": entry_price, "entry_date": entry_date,
                    "max_price": entry_price, "buy_point": cand["bp"],
                    "daily_trend": cand["daily_trend"],
                    "weekly_trend": cand["weekly_trend"],
                    "signal_score": score,
                    "signal_grade": cand["grade"],
                    "rsi": cand["rsi"],
                    "_breakeven_set": False,
                }
                trade_log.append({
                    "date": entry_date, "direction": "BUY",
                    "symbol": sym, "price": entry_price, "qty": qty,
                    "amount": cost,
                    "reason": (f"[{cand['bp']}] 评分{score} {cand['grade']} "
                               f"W:{cand['weekly_trend']} D:{cand['daily_trend']} "
                               f"RSI{cand['rsi']:.0f} {sent_phase}"),
                })

                # Track stats by signal
                if cand["bp"] not in stats_by_signal:
                    stats_by_signal[cand["bp"]] = {"buys": 0, "wins": 0, "losses": 0,
                                                   "total_pnl": 0.0, "total_hold": 0}
                stats_by_signal[cand["bp"]]["buys"] += 1

                grade = cand["grade"]
                if grade not in stats_by_grade:
                    stats_by_grade[grade] = {"buys": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}
                stats_by_grade[grade]["buys"] += 1

        # ── 4. 卖出检查 ──
        for sym in list(positions.keys()):
            pos = positions[sym]
            today_bars = [b for b in all_bars.get(sym, []) if str(b.get("time", "")) == curr_date]
            if not today_bars:
                continue
            bar = today_bars[0]
            high = _safe_float(bar.get("high"))
            low = _safe_float(bar.get("low"))
            close = _safe_float(bar.get("close"))

            if high > pos["max_price"]:
                pos["max_price"] = high

            # T+1: cannot sell same day
            if pos["entry_date"] == curr_date:
                continue

            entry_p = pos["entry_price"]
            max_p = pos["max_price"]
            max_profit_pct = (max_p - entry_p) / entry_p * 100
            curr_profit_pct = (close - entry_p) / entry_p * 100

            sell_triggered = False
            sell_price = close
            sell_reason = ""

            # Dynamic stop-loss based on signal grade
            grade = pos.get("signal_grade", "C")
            buy_point = pos.get("buy_point", "")
            if grade == "A":
                stop_loss_pct = -7.0
                trail_lock_pct = 10.0
            elif grade == "B":
                stop_loss_pct = -6.0
                trail_lock_pct = 8.0
            elif buy_point == "一买":
                # 一买 (divergence) gets more room
                stop_loss_pct = -7.0
                trail_lock_pct = 8.0
            else:
                stop_loss_pct = -5.5
                trail_lock_pct = 5.0

            # 移动止盈保护: 一旦涨过2.5%, 止损上移至保本
            be_threshold = 2.5
            if max_profit_pct >= be_threshold and not pos.get('_breakeven_set'):
                pos['_breakeven_set'] = True

            # 阶梯止盈 (trailing)
            if max_profit_pct >= 20.0:
                lock = round(entry_p * 1.14, 2)
                if low <= lock:
                    sell_triggered, sell_price = True, lock
                    sell_reason = f"+14%锁利 (曾涨{max_profit_pct:.1f}%)"
            elif max_profit_pct >= trail_lock_pct:
                # Trail at 20% retracement from peak (tighter = more profit locked)
                trail_price = round(entry_p * (1 + max_profit_pct / 100 * 0.8), 2)
                if low <= trail_price:
                    sell_triggered, sell_price = True, trail_price
                    sell_reason = f"回落锁利 (曾涨{max_profit_pct:.1f}%)"
            elif pos.get('_breakeven_set'):
                # Breakeven stop: close drops below entry (not just intraday touch)
                if close < entry_p * 0.998:
                    sell_triggered, sell_price = True, close
                    sell_reason = f"保本出 (曾涨{max_profit_pct:.1f}%)"

            # 动态硬止损
            if not sell_triggered:
                stop = round(entry_p * (1 + stop_loss_pct / 100), 2)
                if low <= stop:
                    sell_triggered, sell_price = True, stop
                    sell_reason = f"止损{stop_loss_pct:.0f}%"

            # 缠论卖点 (持有时长 >= 3 天才允许)
            if not sell_triggered:
                held = (dt.date.fromisoformat(curr_date) - dt.date.fromisoformat(pos["entry_date"])).days
                if held >= 3:
                    lookback = [b for b in all_bars.get(sym, []) if str(b.get("time", "")) <= curr_date]
                    if len(lookback) >= 60:
                        a2 = analyze_chanlun(lookback)
                        sp = a2.get("sell_point")
                        if sp:
                            sell_triggered, sell_price = True, close
                            sell_reason = f"{sp} {a2.get('trend_type','')}"
                        elif a2.get("trend_type") == "downtrend" and curr_profit_pct < -2:
                            sell_triggered, sell_price = True, close
                            sell_reason = "转下行出局"

            # 情绪冰点且浮亏清仓
            if not sell_triggered and sent_phase == "ice" and curr_profit_pct < -2:
                sell_triggered, sell_price = True, close
                sell_reason = f"冰点{curr_profit_pct:.1f}%清仓"

            if sell_triggered:
                revenue = pos["qty"] * sell_price
                fee = revenue * 0.0013
                cash += (revenue - fee)
                total_commissions += fee
                pnl = (revenue - fee) - (pos["qty"] * entry_p)
                pnl_pct = pnl / (pos["qty"] * entry_p) * 100
                hold = (dt.date.fromisoformat(curr_date) - dt.date.fromisoformat(pos["entry_date"])).days
                trade_log.append({
                    "date": curr_date, "direction": "SELL",
                    "symbol": sym, "price": sell_price, "qty": pos["qty"],
                    "amount": revenue, "pnl": pnl, "pnl_pct": pnl_pct,
                    "hold_days": hold, "reason": sell_reason,
                })
                cooldowns[sym] = (dt.date.fromisoformat(curr_date) + dt.timedelta(days=cooldown_days)).isoformat()

                # Track stats by signal
                bp = pos.get("buy_point", "?")
                if bp in stats_by_signal:
                    if pnl > 0:
                        stats_by_signal[bp]["wins"] += 1
                    else:
                        stats_by_signal[bp]["losses"] += 1
                    stats_by_signal[bp]["total_pnl"] += pnl
                    stats_by_signal[bp]["total_hold"] += hold

                grade = pos.get("signal_grade", "?")
                if grade in stats_by_grade:
                    if pnl > 0:
                        stats_by_grade[grade]["wins"] += 1
                    else:
                        stats_by_grade[grade]["losses"] += 1
                    stats_by_grade[grade]["total_pnl"] += pnl

                del positions[sym]

        # 日终结算
        pos_val = 0.0
        for sym, p in positions.items():
            cb = next((b for b in all_bars.get(sym, []) if str(b.get("time", "")) == curr_date), None)
            cp = _safe_float(cb.get("close", p["entry_price"])) if cb else p["entry_price"]
            pos_val += p["qty"] * cp
        daily_equity.append({
            "date": curr_date, "cash": round(cash, 2),
            "pos_val": round(pos_val, 2),
            "total": round(cash + pos_val, 2),
            "holdings": len(positions),
        })

    # ── 5. 统计 ──
    final = daily_equity[-1]
    net = final["total"] - initial_capital
    ret = net / initial_capital * 100
    closed = [t for t in trade_log if t["direction"] == "SELL"]
    wins = [t for t in closed if t.get("pnl", 0) > 0]
    losses = [t for t in closed if t.get("pnl", 0) <= 0]
    wr = len(wins) / len(closed) * 100 if closed else 0
    tp = sum(t["pnl"] for t in wins) or 0
    tl = abs(sum(t["pnl"] for t in losses)) or 1
    pf = tp / tl
    peak = initial_capital
    mdd = 0.0
    for eq in daily_equity:
        if eq["total"] > peak:
            peak = eq["total"]
        dd = (peak - eq["total"]) / peak * 100
        if dd > mdd:
            mdd = dd

    # Average hold days
    avg_hold = sum(t.get("hold_days", 0) for t in closed) / len(closed) if closed else 0

    # Average win/loss magnitudes
    avg_win = tp / len(wins) if wins else 0
    avg_loss = -tl / len(losses) if losses else 0

    # Daily return stats for Sharpe-like metric
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

    print(f"\n{'日期':<10} {'方向':<4} {'代码':<10} {'价格':>7} {'数量':>6} {'金额':>9} {'盈亏':>9} {'%':>6} 原因")
    print("-" * 100)
    for t in trade_log:
        if t["direction"] == "BUY":
            print(f"{t['date']} BUY  {t['symbol']:10s} {t['price']:>7.2f} {t['qty']:>6d} {t['amount']:>9.0f}       ---    --- | {t['reason']}")
        else:
            print(f"{t['date']} SELL {t['symbol']:10s} {t['price']:>7.2f} {t['qty']:>6d} {t['amount']:>9.0f} {t.get('pnl',0):>+8.2f} {t.get('pnl_pct',0):>+5.1f}% | {t['reason']}")

    if positions:
        print(f"\n未平仓: {len(positions)} 只")
        for sym, p in positions.items():
            print(f"  {sym}: {p['qty']}股 成本{p['entry_price']:.2f} [{p['buy_point']}] 评分{p.get('signal_score','?')}")

    # ── 信号类型统计 ──
    print(f"\n{'='*100}")
    print("按信号类型统计:")
    print(f"{'信号':<8} {'买入':>5} {'胜':>5} {'负':>5} {'胜率':>6} {'总盈亏':>10} {'均盈亏':>10} {'均持仓':>6}")
    print("-" * 60)
    for bp in sorted(stats_by_signal.keys()):
        s = stats_by_signal[bp]
        buys = s["buys"]
        wins_c = s["wins"]
        losses_c = s["losses"]
        closed_c = wins_c + losses_c
        wr_s = wins_c / closed_c * 100 if closed_c > 0 else 0
        avg_pnl_s = s["total_pnl"] / closed_c if closed_c > 0 else 0
        avg_hld = s["total_hold"] / closed_c if closed_c > 0 else 0
        print(f"{bp:<8} {buys:>5} {wins_c:>5} {losses_c:>5} {wr_s:>5.0f}% {s['total_pnl']:>+10.0f} {avg_pnl_s:>+10.0f} {avg_hld:>5.0f}d")

    # ── 评分等级统计 ──
    print(f"\n按评分等级统计:")
    print(f"{'等级':<6} {'买入':>5} {'胜':>5} {'负':>5} {'胜率':>6} {'总盈亏':>10} {'均盈亏':>10}")
    print("-" * 50)
    for grade in sorted(stats_by_grade.keys()):
        s = stats_by_grade[grade]
        closed_g = s["wins"] + s["losses"]
        wr_g = s["wins"] / closed_g * 100 if closed_g > 0 else 0
        avg_pnl_g = s["total_pnl"] / closed_g if closed_g > 0 else 0
        print(f"{grade:<6} {s['buys']:>5} {s['wins']:>5} {s['losses']:>5} {wr_g:>5.0f}% {s['total_pnl']:>+10.0f} {avg_pnl_g:>+10.0f}")

    print(f"\n{'='*100}")
    print(f"  初始资金: {initial_capital:>10,.2f}   期末: {final['total']:>10,.2f}   净利润: {net:>+10,.2f}  收益率: {ret:>+6.2f}%")
    print(f"  交易: {len(trade_log)//2}笔   胜率: {wr:.0f}% ({len(wins)}胜/{len(losses)}负)   盈亏比: {pf:.2f}")
    print(f"  最大回撤: {mdd:.2f}%   夏普: {sharpe:.2f}   均持仓: {avg_hold:.0f}d   手续费: {total_commissions:.0f}")
    print(f"  均盈: {avg_win:>+.0f}   均亏: {avg_loss:>+.0f}   仓位上限: {effective_max_positions}   评分门槛: {min_score_threshold}")
    print(f"  {'='*100}")

    return {
        "initial_capital": initial_capital,
        "final_equity": final["total"],
        "net": net, "return_pct": ret,
        "trades": len(trade_log) // 2,
        "win_rate": wr, "profit_factor": pf,
        "mdd": mdd, "sharpe": sharpe,
        "avg_hold_days": avg_hold,
        "avg_win": avg_win, "avg_loss": avg_loss,
        "symbols": len(all_bars),
        "days": len(trade_dates),
        "stats_by_signal": stats_by_signal,
        "stats_by_grade": stats_by_grade,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="2026-06-01")
    p.add_argument("--end", default="2026-09-30")
    p.add_argument("--capital", type=float, default=400000.0)
    p.add_argument("--symbols")
    p.add_argument("--pool", type=int, default=20)
    p.add_argument("--min-score", type=int, default=30, help="Minimum signal score (0-100)")
    a = p.parse_args()

    symbols = [s.strip() for s in a.symbols.split(",")] if a.symbols else DEFAULT_POOL[:a.pool]
    run_backtest(symbols, a.start, a.end, a.capital)


if __name__ == "__main__":
    main()
