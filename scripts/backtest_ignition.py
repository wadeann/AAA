#!/usr/bin/env python3
"""
Ignition-V1 V2.2 回测：直接用K线数据做筛选，不依赖问财/通达信.

评分数据直接从 MCP 获取，无需 ignition_v1_sniper 依赖.
用法:
  python3 -m scripts.backtest_ignition --date 2026-09-07
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Any

from mcp_client import get_mcp_client
from utils.market import get_stock_market_type

CST = dt.timezone(dt.timedelta(hours=8))


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def fetch_klines(symbol: str, count: int = 30) -> list[dict[str, Any]]:
    """Fetch daily klines via MCP."""
    try:
        client = get_mcp_client()
        return client.fetch_klines(symbol, period="D", count=count)
    except Exception:
        return []


def get_limit_up_threshold(symbol: str) -> float:
    """Get limit-up threshold based on market type."""
    mkt = get_stock_market_type(symbol)
    if mkt == "STAR":
        return 19.9
    elif mkt == "CHINEXT":
        return 19.9
    elif mkt == "BSE":
        return 29.9
    else:
        return 9.9


def calc_premarket_score(
    t1_kline: dict[str, Any],
    k20: list[dict[str, Any]],
) -> dict[str, Any]:
    """Calculate premarket score from K-line data (5 factors).

    Returns dict with keys: pct, scores, details
    """
    if not k20:
        return {"pct": 0.0, "scores": {}, "details": {}}

    t1_close = _safe_float(t1_kline.get("close"))
    t1_open = _safe_float(t1_kline.get("open"))
    t1_high = _safe_float(t1_kline.get("high"))
    t1_low = _safe_float(t1_kline.get("low"))
    t1_vol = _safe_float(t1_kline.get("volume"))
    t1_amount = _safe_float(t1_kline.get("amount"))
    t1_chg = _safe_float(t1_kline.get("change_pct"))

    k20_closes = [_safe_float(k.get("close")) for k in k20 if _safe_float(k.get("close")) > 0]
    k20_highs = [_safe_float(k.get("high")) for k in k20 if _safe_float(k.get("high")) > 0]
    k20_lows = [_safe_float(k.get("low")) for k in k20 if _safe_float(k.get("low")) > 0]
    k20_vols = [_safe_float(k.get("volume")) for k in k20 if _safe_float(k.get("volume")) > 0]

    if not k20_closes:
        return {"pct": 0.0, "scores": {}, "details": {}}

    # 1. 涨幅分 (change score) — 30%
    if k20_closes:
        avg_chg = (t1_close - k20_closes[-1]) / k20_closes[-1] * 100 if k20_closes[-1] > 0 else 0
        if avg_chg > 5:
            chg_score = 30
        elif avg_chg > 3:
            chg_score = 25
        elif avg_chg > 1:
            chg_score = 20
        elif avg_chg > 0:
            chg_score = 15
        elif avg_chg > -2:
            chg_score = 10
        else:
            chg_score = 5
    else:
        chg_score = 10

    # 2. 趋势分 (trend score) — 25%
    if len(k20_closes) >= 5:
        ma5 = sum(k20_closes[-5:]) / 5
        ma10 = sum(k20_closes[-10:]) / 10 if len(k20_closes) >= 10 else ma5
        if t1_close > ma5 > ma10:
            trend_score = 25
        elif t1_close > ma5:
            trend_score = 18
        elif t1_close > ma10:
            trend_score = 12
        elif t1_close > ma10 * 0.95:
            trend_score = 8
        else:
            trend_score = 4
    else:
        trend_score = 12

    # 3. 距离分 (distance from low score) — 15%
    if k20_lows and k20_highs:
        low_20 = min(k20_lows)
        high_20 = max(k20_highs)
        if high_20 > low_20:
            pos_pct = (t1_close - low_20) / (high_20 - low_20) * 100
            if pos_pct < 30:
                dist_score = 15
            elif pos_pct < 50:
                dist_score = 12
            elif pos_pct < 70:
                dist_score = 8
            elif pos_pct < 90:
                dist_score = 5
            else:
                dist_score = 2
        else:
            dist_score = 8
    else:
        dist_score = 8

    # 4. 放量分 (volume score) — 15%
    if k20_vols and len(k20_vols) >= 2:
        avg_vol = sum(k20_vols[:-1]) / (len(k20_vols) - 1)
        if avg_vol > 0 and t1_vol > 0:
            vol_ratio = t1_vol / avg_vol
            if vol_ratio > 2.0:
                vol_score = 15
            elif vol_ratio > 1.5:
                vol_score = 12
            elif vol_ratio > 1.0:
                vol_score = 8
            elif vol_ratio > 0.7:
                vol_score = 5
            else:
                vol_score = 2
        else:
            vol_score = 5
    else:
        vol_score = 5

    # 5. 活跃分 (volatility score) — 10%
    if k20_highs and k20_lows and len(k20_closes) >= 5:
        recent_highs = k20_highs[-5:]
        recent_lows = k20_lows[-5:]
        avg_range = sum(
            (recent_highs[i] - recent_lows[i]) / recent_lows[i] * 100
            for i in range(len(recent_highs))
            if recent_lows[i] > 0
        ) / len(recent_highs)
        t1_range = (t1_high - t1_low) / t1_low * 100 if t1_low > 0 else 0
        if t1_range > avg_range * 1.2:
            vola_score = 10
        elif t1_range > avg_range * 0.8:
            vola_score = 7
        elif t1_range > avg_range * 0.5:
            vola_score = 4
        else:
            vola_score = 2
    else:
        vola_score = 5

    # 6. 流动分 (liquidity score) — 5%
    if t1_amount >= 5e8:
        liquid_score = 5
    elif t1_amount >= 2e8:
        liquid_score = 4
    elif t1_amount >= 1e8:
        liquid_score = 3
    elif t1_amount >= 5e7:
        liquid_score = 2
    else:
        liquid_score = 1

    total = chg_score + trend_score + dist_score + vol_score + vola_score + liquid_score

    return {
        "pct": round(total, 1),
        "scores": {
            "涨幅分": (f"{avg_chg:+.2f}%" if k20_closes else "0%", chg_score),
            "趋势分": ("MA多头" if trend_score >= 18 else "MA空头", trend_score),
            "距离分": (f"距20日低{pos_pct:.0f}%" if k20_highs else "N/A", dist_score),
            "放量分": (f"倍率{vol_ratio:.1f}x" if avg_vol > 0 else "N/A", vol_score),
            "活跃分": (f"当日振幅{t1_range:.1f}%" if t1_low > 0 else "N/A", vola_score),
            "流动分": (f"成交额{t1_amount:.1f}" if t1_amount else "N/A", liquid_score),
        },
        "details": {
            "close": t1_close, "change_pct": t1_chg,
            "avg_chg": round(avg_chg, 2) if k20_closes else 0,
            "vol_ratio": round(vol_ratio, 2) if k20_vols and avg_vol > 0 else 0,
        },
    }


def get_dynamic_auction_open_range(regime: str) -> tuple[float, float]:
    """Get dynamic auction open range based on market regime."""
    ranges = {
        "euphoria": (1.0, 8.0),
        "hot": (0.5, 6.0),
        "warmup": (0.0, 4.0),
        "cooldown": (-1.0, 3.0),
        "ice": (-2.0, 2.0),
    }
    return ranges.get(regime, (0.0, 4.0))


def load_market_regime() -> str:
    """Load current market regime from state file."""
    from config import STATE_DIR
    try:
        path = STATE_DIR / "market_regime.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            return data.get("standard_regime", "warmup")
    except Exception:
        pass
    return "warmup"


DEFAULT_TEST_CASES: dict[str, list[str]] = {
    "2026-09-07": ["000523.SZ", "000930.SZ", "002286.SZ", "002980.SZ",
                   "000592.SZ", "600108.SH", "002403.SZ", "002172.SZ"],
    "2026-09-04": ["002980.SZ"],
    "2026-09-03": ["600378.SH", "300179.SZ", "603728.SH", "002017.SZ",
                   "300061.SZ", "002174.SZ"],
}

DEFAULT_SCORE_THRESHOLDS = [80, 75, 70, 65]


def main() -> None:
    parser = argparse.ArgumentParser(description="Ignition-V1 V2.2 backtest")
    parser.add_argument("--date", help="Single date to test (YYYY-MM-DD)")
    parser.add_argument("--symbols", nargs="+", help="Symbols to test")
    args = parser.parse_args()

    current_regime = load_market_regime()
    auc_min, auc_max = get_dynamic_auction_open_range(current_regime)

    if args.date and args.symbols:
        test_dates = {args.date: args.symbols}
    else:
        test_dates = DEFAULT_TEST_CASES

    min_prem_score = 65.0

    print("=" * 65)
    print(f"Ignition-V1 V2.2 回测 (市况: {current_regime})")
    print(f"竞价区间: +{auc_min:.1f}% ~ +{auc_max:.1f}%, 及格线: >= {min_prem_score:.0f}")
    print("=" * 65)

    all_trades: list[dict[str, Any]] = []

    for scan_date, syms in test_dates.items():
        print(f"\n--- {scan_date} ---")
        for sym in syms:
            klines = fetch_klines(sym, 30)
            if len(klines) < 5:
                print(f"  {sym}: K线不足 {len(klines)}")
                continue

            t1_k = None
            next_k = None
            for i, k in enumerate(klines):
                kdate = str(k.get("time", "")).replace("-", "").replace("/", "")[:8]
                scan_norm = scan_date.replace("-", "")
                if kdate == scan_norm:
                    t1_k = k
                    if i + 1 < len(klines):
                        next_k = klines[i + 1]
                    break

            if t1_k is None:
                print(f"  {sym}: 无 {scan_date} 数据")
                continue

            k20 = [k for k in klines
                   if str(k.get("time", "")).replace("-", "")[:8] < scan_date.replace("-", "")]

            prem = calc_premarket_score(t1_k, k20)
            t1_close = _safe_float(t1_k.get("close"))
            t1_chg = _safe_float(t1_k.get("change_pct"))

            scores_str = " ".join(
                f"{k}:{v[1]}" for k, v in prem["scores"].items()
            )
            print(f"  {sym}: 评分{prem['pct']:5.1f}% ({scores_str}) T-1涨{t1_chg:+.2f}%")

            if next_k and t1_close > 0:
                t_open = _safe_float(next_k.get("open"))
                t_close = _safe_float(next_k.get("close"))
                t_chg = _safe_float(next_k.get("change_pct"))
                t_high = _safe_float(next_k.get("high"))

                open_pct = (t_open - t1_close) / t1_close * 100
                close_chg = (t_close - t1_close) / t1_close * 100
                high_chg = (t_high - t1_close) / t1_close * 100

                score_ok = prem["pct"] >= min_prem_score
                auction_ok = auc_min <= open_pct <= auc_max
                buyable = score_ok and auction_ok

                zt_thresh = get_limit_up_threshold(sym)
                is_zt = t_chg >= zt_thresh

                ok_mark = "+" if score_ok else "-"
                auc_mark = "+" if auction_ok else "-"
                buy_mark = "+" if buyable else "-"
                zt_mark = " ZT" if is_zt else ""

                print(f"    T日: 开{open_pct:+.1f}% 收{close_chg:+.2f}% 最{high_chg:+.1f}% "
                      f"[评分{ok_mark}][竞价{auc_mark}][买{buy_mark}]{zt_mark}")

                all_trades.append({
                    "symbol": sym, "scan_date": scan_date,
                    "score": prem["pct"], "score_pass": score_ok,
                    "auction_pct": round(open_pct, 1), "auction_pass": auction_ok,
                    "buyable": buyable, "t_close_chg": round(close_chg, 2),
                    "t_day_chg": round(t_chg, 2), "is_zt": is_zt,
                })
            else:
                print(f"    T日: 无后续数据")

    # 统计
    print(f"\n{'=' * 65}")
    print("回测统计")
    print(f"{'=' * 65}")

    if all_trades:
        avg_chg = sum(t["t_close_chg"] for t in all_trades) / len(all_trades)
        wins = sum(1 for t in all_trades if t["t_close_chg"] > 0)
        zt = sum(1 for t in all_trades if t["is_zt"])
        print(f"全体({len(all_trades)}): 均收益{avg_chg:+.2f}% 胜率{wins}/{len(all_trades)}=\
{wins / len(all_trades) * 100:.0f}% 涨停{zt}/{len(all_trades)}=\
{zt / len(all_trades) * 100:.0f}%")

        buyable = [t for t in all_trades if t["buyable"]]
        if buyable:
            bavg = sum(t["t_close_chg"] for t in buyable) / len(buyable) if buyable else 0
            bwins = sum(1 for t in buyable if t["t_close_chg"] > 0)
            bzt = sum(1 for t in buyable if t["is_zt"])
            print(f"可买({len(buyable)}): 均收益{bavg:+.2f}% 胜率{bwins}/{len(buyable)}=\
{bwins / len(buyable) * 100:.0f}% 涨停{bzt}/{len(buyable)}=\
{bzt / len(buyable) * 100:.0f}%")
            for t in buyable:
                print(f"    {t['symbol']} {t['scan_date']} 评分{t['score']:.0f}% "
                      f"竞价{t['auction_pct']:+.1f}% → {t['t_close_chg']:+.2f}%"
                      f"{' ZT' if t['is_zt'] else ''}")

        nocond = [t for t in all_trades if t["score_pass"] and not t["auction_pass"]]
        if nocond:
            navg = sum(t["t_close_chg"] for t in nocond) / len(nocond)
            print(f"达标但竞价不符({len(nocond)}): 均收益{navg:+.2f}%")
            for t in nocond:
                pct = t["auction_pct"]
                print(f"    {t['symbol']} 评分{t['score']:.0f}% 竞价{pct:+.1f}% → {t['t_close_chg']:+.2f}%")

        print("\n评分分段:")
        for thr in sorted(DEFAULT_SCORE_THRESHOLDS, reverse=True):
            seg = [t for t in all_trades if t["score"] >= thr]
            if seg:
                savg = sum(t["t_close_chg"] for t in seg) / len(seg)
                szt = sum(1 for t in seg if t["is_zt"])
                print(f"  >= {thr}分({len(seg)}笔): 均收益{savg:+.2f}% 涨停{szt}")
    else:
        print("无交易数据")

    # 保存
    out_dir = Path.cwd() / "backtest_results"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "backtest_ignition_results.json"
    tmp = out_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(all_trades, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_path)
    print(f"\n结果已保存: {out_path}")


if __name__ == "__main__":
    main()
