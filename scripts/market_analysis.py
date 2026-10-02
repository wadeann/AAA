#!/usr/bin/env python3
"""
Astock 大盘分析 + 选股扫描 — 基于 9/30 收盘价.
使用 momentum_v5 (最佳 composite 41.63) 策略筛选全市场.
"""
import json
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.strategy import (
    score_momentum_core, get_regime, REGIME_MAP, REGIME_NAMES_CN,
    screen_candidates, sma, rsi, SellRules, load_strategy_config,
)
from core.strategy_profiles import get_profile

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "kline_cache.json"
DATE = "2026-09-30"

def load_cache():
    with open(DATA_FILE) as f:
        return json.load(f)

def estimate_market_regime(bars_dict, date):
    """使用市场宽度 (breadth) 估计体制."""
    above_ma20 = 0
    above_ma60 = 0
    total = 0
    rsi_vals = []
    chg5_vals = []

    for sym, bars in bars_dict.items():
        lb = [b for b in bars if str(b.get("time", "")) <= date]
        if len(lb) < 60:
            continue
        total += 1
        close = lb[-1].get("close", 0)
        ma20 = sma(lb, "close", 20)
        if close > ma20:
            above_ma20 += 1
        if close > sma(lb, "close", 60):
            above_ma60 += 1
        rsi_vals.append(rsi(lb, 14))
        c5 = [b.get("close", 0) for b in lb[-5:]]
        if len(c5) == 5 and c5[0] > 0:
            chg5 = (c5[-1] - c5[0]) / c5[0] * 100
            chg5_vals.append(chg5)

    breadth_ma20 = above_ma20 / total * 100 if total else 0
    breadth_ma60 = above_ma60 / total * 100 if total else 0
    avg_rsi = sum(rsi_vals) / len(rsi_vals) if rsi_vals else 50
    avg_chg5 = sum(chg5_vals) / len(chg5_vals) if chg5_vals else 0

    if breadth_ma20 > 70 and avg_rsi > 60 and avg_chg5 > 3:
        regime = "euphoria"
    elif breadth_ma20 > 55 and avg_rsi > 55:
        regime = "hot"
    elif breadth_ma20 > 40 and avg_chg5 > -1.5:
        regime = "warmup"
    elif breadth_ma20 > 25:
        regime = "cooldown"
    else:
        regime = "ice"

    return regime, {
        "regime": regime,
        "regime_cn": REGIME_NAMES_CN.get(regime, regime),
        "breadth_ma20": round(breadth_ma20, 1),
        "breadth_ma60": round(breadth_ma60, 1),
        "avg_rsi": round(avg_rsi, 1),
        "avg_chg5": round(avg_chg5, 2),
        "total_stocks": total,
        "above_ma20": above_ma20,
        "above_ma60": above_ma60,
    }

def main():
    print("=" * 70)
    print("  Astock 大盘分析 + 选股扫描")
    print(f"  基准日期: {DATE}")
    print("=" * 70)

    # 1. 加载数据
    print("\n[1/5] 加载数据...")
    bars_dict = load_cache()
    total_symbols = len(bars_dict)
    print(f"  股票池: {total_symbols} 只")

    # 2. 市场体制检测
    print(f"\n[2/5] 市场体制检测...")
    regime, stats = estimate_market_regime(bars_dict, DATE)
    regime_params = REGIME_MAP.get(regime, (60, 3, 0.25))
    print(f"  市场体制: {stats['regime_cn']} ({regime})")
    print(f"  市场宽度(MA20上): {stats['above_ma20']}/{stats['total_stocks']} ({stats['breadth_ma20']}%)")
    print(f"  市场宽度(MA60上): {stats['above_ma60']}/{stats['total_stocks']} ({stats['breadth_ma60']}%)")
    print(f"  平均 RSI: {stats['avg_rsi']}")
    print(f"  近5日平均涨幅: {stats['avg_chg5']}%")
    print(f"  体制参数: min_score={regime_params[0]}, 最大持仓={regime_params[1]}, 仓位上限={regime_params[2]*100}%")

    # 3. 初步筛选
    print(f"\n[3/5] 全市场初步筛选...")
    # 从配置加载具体参数
    cfg = load_strategy_config()
    hf = cfg.get("hard_filters", {})
    min_vr = hf.get("min_vr", 0.7)
    ma_pct = hf.get("ma_pct", 0.95)
    min_rs = hf.get("min_rs", 30)

    candidates = screen_candidates(bars_dict, DATE, min_vr=min_vr, ma_pct=ma_pct)
    print(f"  通过硬过滤: {len(candidates)} 只 (VR>={min_vr}, MA20位置>{ma_pct*100}%)")

    # 4. 评分排序
    print(f"\n[4/5] 动量评分排序...")
    min_score = regime_params[0]  # 根据体制动态调整

    scored = []
    for sym in candidates:
        bars = bars_dict.get(sym, [])
        lb = [b for b in bars if str(b.get("time", "")) <= DATE]
        if len(lb) < 30:
            continue
        result = score_momentum_core(lb, cfg.get("score_weights") or None)
        if result["grade"] in ("A", "B") and result["score"] >= min_score:
            close = lb[-1].get("close", 0)
            vol = lb[-1].get("volume", 0)
            avg_vol = sma(lb, "volume", 20)
            vr = vol / avg_vol if avg_vol > 0 else 0
            chg = lb[-1].get("change_pct", 0)
            name = lb[-1].get("name", "")
            scored.append((sym, result["score"], result["grade"], result["name"], chg, vr, close))

    scored.sort(key=lambda x: -x[1])
    print(f"  A/B 级评分通过: {len(scored)} 只 (min_score={min_score})")
    print(f"  各类型分布: {Counter(s[3] for s in scored)}")

    # 5. 结果输出
    print(f"\n[5/5] 精选推荐 (Top {min(20, len(scored))}):")
    print(f"  {'代码':<12} {'评分':>4} {'等级':<4} {'类型':<12} {'涨幅%':>6} {'量比':>5} {'收盘价':>8}")
    print(f"  {'-'*55}")
    for sym, score, grade, stype, chg, vr, close in scored[:20]:
        name = sym.split(".")[0]
        print(f"  {sym:<12} {score:>4} {grade:<4} {stype:<12} {chg:>+6.2f} {vr:>5.2f} {close:>8.2f}")

    # 操作建议
    print(f"\n{'=' * 70}")
    print(f"  操作建议")
    print(f"{'=' * 70}")

    if regime in ("ice", "cooldown"):
        print(f"  [谨慎] 市场处于{stats['regime_cn']}期，建议:")
        print(f"    - 仓位控制在 {regime_params[2]*100:.0f}% 以内")
        print(f"    - 仅关注评分 >= {regime_params[0]} 的强势股")
        print(f"    - 缩短持仓周期，快进快出")
        print(f"    - 严格止损 (-2.8%)")
        if len(scored) < 10:
            print(f"    - 市场机会少，建议观望为主")
    elif regime == "warmup":
        print(f"  [中性] 市场处于{stats['regime_cn']}期，建议:")
        print(f"    - 仓位控制在 {regime_params[2]*100:.0f}% 以内")
        print(f"    - 精选评分 >= 70 的个股")
        print(f"    - 分散到 {regime_params[1]} 只以内")
        print(f"    - 结合板块热点操作")
    elif regime == "hot":
        print(f"  [积极] 市场处于{stats['regime_cn']}期，建议:")
        print(f"    - 仓位可加至 {regime_params[2]*100:.0f}%")
        print(f"    - 积极选股，评分 >= 65 即可参与")
        print(f"    - 适当放宽止损")
    elif regime == "euphoria":
        print(f"  [进攻] 市场处于{stats['regime_cn']}期，建议:")
        print(f"    - 满仓操作")
        print(f"    - 追涨强势股，评分 >= 60 即可参与")
        print(f"    - 适当放宽止损")

    # Top 5 推荐理由
    if len(scored) >= 5:
        print(f"\n  Top 5 推荐理由:")
        sell_rules = SellRules(cfg.get("sell_rules", {}))
        for sym, score, grade, stype, chg, vr, close in scored[:5]:
            bars = [b for b in bars_dict.get(sym, []) if str(b.get("time", "")) <= DATE]
            if len(bars) >= 20:
                ma5 = sma(bars, "close", 5)
                ma10 = sma(bars, "close", 10)
                ma20 = sma(bars, "close", 20)
                vol = bars[-1].get("volume", 0)
                avg_v20 = sma(bars, "volume", 20)
                vr_ratio = vol / avg_v20 if avg_v20 > 0 else 0
                dh = (bars[-1].get("high", close) - close) / close * 100
                print(f"    {sym}: score={score} {stype} | MA5={ma5:.2f} MA10={ma10:.2f} MA20={ma20:.2f} | VR={vr_ratio:.2f} | 距10日高={dh:.1f}%")
                if score >= 80:
                    print(f"      → 强烈推荐: 多因子共振，量价配合良好")
                elif score >= 70:
                    print(f"      → 推荐: 趋势明确，可积极介入")
                else:
                    print(f"      → 观望: 评分尚可，需结合板块确认")

    print(f"\n{'=' * 70}")
    print(f"  数据日期: {DATE} | 股票池: {total_symbols} 只")
    print(f"{'=' * 70}")

if __name__ == "__main__":
    main()
