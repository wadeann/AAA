#!/usr/bin/env python3
"""
Astock 动量回测引擎 v6 — 全市场动态选股 + 双模式: 趋势/反转.

核心:
  1. 双模式: 上升趋势(热/温)用动量, 下跌趋势(冷/冰)用反转
  2. 集中持仓: max 3 只, 每只 30%+
  3. 紧止损 + 大目标: -2.5% / +10%
  4. 全市场 200+ 候选池每日动态筛选

用法:
  python3 -m scripts.backtest_v6 --capital 400000 --start 2026-06-01 --end 2026-09-30
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any

from mcp_client import get_mcp_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

STOCK_UNIVERSE = [
    "600519.SH","000858.SZ","601899.SH","600036.SH","002594.SZ","300750.SZ",
    "688981.SH","000333.SZ","601318.SH","600900.SH","002415.SZ","600276.SH",
    "000568.SZ","002714.SZ","601012.SH","600309.SH","000725.SZ","601166.SH",
    "002475.SZ","600585.SH","300059.SZ","002230.SZ","300274.SZ","688041.SH",
    "002371.SZ","300124.SZ","300308.SZ","300896.SZ","300760.SZ","300033.SZ",
    "300661.SZ","601398.SH","601939.SH","601288.SH","601988.SH","600000.SH",
    "600016.SH","600030.SH","601211.SH","600837.SH","601688.SH","002736.SZ",
    "601319.SH","601628.SH","601601.SH","601336.SH","688012.SH","688008.SH",
    "688036.SH","688126.SH","002049.SZ","603501.SH","600703.SH","688396.SH",
    "300782.SZ","300604.SZ","002916.SZ","603986.SH","688099.SH","300496.SZ",
    "300454.SZ","688111.SH","600745.SH","603160.SH","300433.SZ","002241.SZ",
    "600584.SH","300015.SZ","000538.SZ","000661.SZ","300122.SZ","300347.SZ",
    "603259.SH","002821.SZ","300759.SZ","688180.SH","688185.SH","002007.SZ",
    "600438.SH","688599.SH","688223.SH","002459.SZ","300763.SZ","601615.SH",
    "603806.SH","688390.SH","300014.SZ","002074.SZ","300450.SZ","002850.SZ",
    "002709.SZ","002304.SZ","600809.SH","603369.SH","000596.SZ","600887.SH",
    "603288.SH","002311.SZ","000651.SZ","002032.SZ","300957.SZ","688169.SH",
    "600406.SH","600019.SH","002271.SZ","601100.SH","688005.SH","600760.SH",
    "600893.SH","600150.SH","601989.SH","600862.SH","300699.SZ","600416.SH",
    "600085.SH","603993.SH","600362.SH","000630.SZ","002460.SZ","002466.SZ",
    "600516.SH","600031.SH","600028.SH","600938.SH","601225.SH","601088.SH",
    "600188.SH","601857.SH","300003.SZ","300529.SZ","688029.SH","300832.SZ",
    "002938.SZ","603659.SH","600941.SH","002555.SZ","002602.SZ","300418.SZ",
    "603444.SH","002624.SZ","300502.SZ","300394.SZ","002920.SZ","002180.SZ",
    "002129.SZ","600171.SH","600460.SH","300223.SZ","300458.SZ","300672.SZ",
    "300773.SZ","301269.SZ","688200.SH","688301.SH","002625.SZ","002463.SZ",
    "300628.SZ","300576.SZ","300775.SZ","002747.SZ","300724.SZ","688598.SH",
    "300587.SZ","300666.SZ","301358.SZ","001979.SZ","600048.SH","600383.SH",
    "601155.SH","600895.SH","000002.SZ","600690.SH","601138.SH","000063.SZ",
    "600196.SH","600104.SH",
]

_MCP_CACHE: dict[str, list[dict]] = {}


def _sf(v: Any, d: float = 0.0) -> float:
    try: return float(v) if v is not None else d
    except (TypeError, ValueError): return d


def fetch_klines(symbol: str, count: int = 150) -> list[dict]:
    key = f"{symbol}_{count}"
    if key in _MCP_CACHE: return _MCP_CACHE[key]
    try:
        raw = get_mcp_client().call("fetch_kline", {"symbol": symbol, "period": "D", "count": count})
        if isinstance(raw, dict):
            k = raw.get("klines", [])
            if k: _MCP_CACHE[key] = k; return k
        if isinstance(raw, list): _MCP_CACHE[key] = raw; return raw
    except Exception: pass
    _MCP_CACHE[key] = []; return []


def sma(bars: list[dict], key: str = "close", period: int = 5) -> float:
    vals = [_sf(b.get(key)) for b in bars[-period:] if _sf(b.get(key)) > 0]
    return sum(vals) / len(vals) if vals else 0


def rsi(bars: list[dict], period: int = 14) -> float:
    closes = [_sf(b.get("close")) for b in bars if _sf(b.get("close")) > 0]
    if len(closes) < period + 1: return 50.0
    g = l = 0.0
    for i in range(-period, 0):
        c = closes[i] - closes[i - 1]; g += max(c, 0); l += max(-c, 0)
    a, b = g / period, l / period or 0.01
    return 100 - 100 / (1 + a / b)


def get_regime(index_bars: list[dict], curr_date: str) -> str:
    bars = [b for b in index_bars if str(b.get("time", "")) <= curr_date]
    if len(bars) < 10: return "warmup"
    c5 = [_sf(b.get("close")) for b in bars[-5:]]
    chg5 = (c5[-1] - c5[0]) / c5[0] * 100 if c5[0] > 0 else 0
    ma10, ma20 = sma(bars, "close", 10), sma(bars, "close", 20)
    lc = _sf(bars[-1].get("close"))
    if chg5 > 3 and lc > ma10 > ma20: return "euphoria"
    if chg5 > 1 and lc > ma20: return "hot"
    if chg5 > -1.5 and lc > ma20 * 0.95: return "warmup"
    if chg5 > -3: return "cooldown"
    return "ice"


REGIME_MAP = {
    "euphoria": (70, 2, 0.30),
    "hot":      (70, 1, 0.20),
    "warmup":   (65, 3, 0.28),
    "cooldown": (65, 2, 0.25),
    "ice":      (70, 1, 0.15),
}


def screen_candidates(bars_dict: dict[str, list[dict]], curr_date: str,
                      min_vr: float = 1.5, min_close: float = 5.0) -> list[str]:
    cand = []
    for sym, bars in bars_dict.items():
        lb = [b for b in bars if str(b.get("time", "")) <= curr_date]
        if len(lb) < 30: continue
        last = lb[-1]; close = _sf(last.get("close"))
        if close < min_close: continue
        vol = _sf(last.get("volume"))
        if vol <= 0: continue
        avg_v = sma(lb, "volume", 20)
        vr = vol / avg_v if avg_v > 0 else 0
        if vr < min_vr: continue
        ma20 = sma(lb, "close", 20)
        if close < ma20 * 0.95: continue
        cand.append(sym)
    return cand


def score_momentum(bars: list[dict]) -> dict[str, Any]:
    """动量模式: 趋势跟踪."""
    if len(bars) < 30: return {"score": 0, "grade": "D", "mode": "mom"}
    last = bars[-1]; close = _sf(last.get("close")); vol = _sf(last.get("volume"))
    avg_vol = sma(bars, "volume", 20); vr = vol / avg_vol if avg_vol > 0 else 0
    ma5, ma10, ma20 = sma(bars, "close", 5), sma(bars, "close", 10), sma(bars, "close", 20)
    rs = rsi(bars)
    h5 = [_sf(b.get("high")) for b in bars[-5:]]; hi5 = max(h5) if h5 else close
    dh5 = (hi5 - close) / hi5 * 100
    if vr < 1.2 or rs < 35 or rs > 80 or close < ma20 or not (close > ma5 > ma10) or dh5 > 5:
        return {"score": 0, "grade": "D", "mode": "mom"}
    score = 0.0; sig = []
    # Volume (0-20)
    if vr > 3.0: score += 20; sig.append("巨量")
    elif vr > 2.0: score += 16; sig.append("放量")
    elif vr > 1.5: score += 12; sig.append("温和放量")
    # MA alignment (0-30)
    if close > ma5 > ma10 > ma20: score += 30; sig.append("多头排列")
    elif close > ma5 > ma20: score += 20
    else: score += 10
    # Momentum (0-25)
    if dh5 < 0.5: score += 25; sig.append("突破")
    elif dh5 < 2: score += 18; sig.append("强势")
    else: score += 8
    h10 = [_sf(b.get("high")) for b in bars[-10:]]
    hi10 = max(h10) if h10 else close
    if hi5 >= hi10 * 0.99: score += 5; sig.append("10日新高")
    # RSI (0-15)
    if 50 <= rs <= 65: score += 15; sig.append("RSI温和")
    elif rs <= 75: score += 8
    else: score += 3
    # Change (0-10)
    chg = _sf(last.get("change_pct"))
    if chg > 5: score += 10; sig.append("大涨")
    elif chg > 2: score += 7
    elif chg > 0: score += 3
    score = min(score, 100)
    grade = "A" if score >= 75 else "B" if score >= 65 else "C"
    return {"score": score, "grade": grade, "signals": "+".join(sig) if sig else "",
            "stop_pct": -2.5, "target_pct": 10.0, "hold_days": 3, "mode": "mom"}


def score_reversal(bars: list[dict]) -> dict[str, Any]:
    """反转模式: 超卖反弹."""
    if len(bars) < 30: return {"score": 0, "grade": "D", "mode": "rev"}
    last = bars[-1]; close = _sf(last.get("close")); vol = _sf(last.get("volume"))
    avg_vol = sma(bars, "volume", 20); vr = vol / avg_vol if avg_vol > 0 else 0
    ma5, ma10, ma20 = sma(bars, "close", 5), sma(bars, "close", 10), sma(bars, "close", 20)
    rs = rsi(bars)
    l20 = [_sf(b.get("low")) for b in bars[-20:]]; lo20 = min(l20) if l20 else close
    chg = _sf(last.get("change_pct"))
    if vr > 1.8 or rs > 60 or close > ma10 or close > ma20 * 1.02 or chg > 2:
        return {"score": 0, "grade": "D", "mode": "rev"}
    score = 0.0; sig = []
    dd = (close - lo20) / lo20 * 100
    if dd < -8: score += 25; sig.append("深跌")
    elif dd < -5: score += 18; sig.append("回调")
    elif dd < -3: score += 10
    if rs < 30: score += 25; sig.append("超卖")
    elif rs < 40: score += 18
    elif rs < 50: score += 10
    if vr < 0.6: score += 15; sig.append("地量")
    elif vr < 0.8: score += 10; sig.append("缩量")
    elif vr < 1.0: score += 5
    dist = (close - ma20) / ma20 * 100
    if -1 < dist < 1: score += 20; sig.append("MA20支撑")
    elif dist < 0: score += 10
    low, high = _sf(last.get("low")), _sf(last.get("high"))
    if high > low and (close - low) / (high - low) > 0.6:
        score += 15; sig.append("下影线")
    score = min(score, 100)
    grade = "A" if score >= 70 else "B" if score >= 55 else "C"
    return {"score": score, "grade": grade, "signals": "+".join(sig) if sig else "",
            "stop_pct": -2.5, "target_pct": 6.0, "hold_days": 2, "mode": "rev"}


def run_backtest(symbols: list[str], start_date: str, end_date: str, ic: float = 400000.0) -> dict:
    print(f"Loading {len(symbols)} symbols ...")
    all_bars = {}
    for sym in symbols:
        bars = fetch_klines(sym, 200)
        if len(bars) >= 60: all_bars[sym] = bars
    print(f"Loaded {len(all_bars)}/{len(symbols)}")
    index_bars = fetch_klines("000001.SH", 200)
    if not index_bars: print("No index"); return {}
    dates = sorted({str(b.get("time")) for b in index_bars
                    if start_date <= str(b.get("time", "")) <= end_date})
    if len(dates) < 10: print(f"Too few dates: {len(dates)}"); return {}
    print(f"Universe: {len(all_bars)} | Days: {len(dates)} ({dates[0]}~{dates[-1]}) | Cap: {ic:,.0f}")
    print("=" * 110)

    cash, peak = ic, ic
    pos: dict[str, dict] = {}; log: list[dict] = []; eq: list[dict] = []; comm = 0.0

    for di, dt_ in enumerate(dates):
        regime = get_regime(index_bars, dt_)
        ms, mx, cp = REGIME_MAP[regime]
        use_mom = regime in ("hot", "euphoria", "warmup")

        if len(pos) < mx:
            screen = screen_candidates(all_bars, dt_, min_vr=1.5, min_close=5.0)
            cand = []
            for sym in screen:
                if sym in pos: continue
                lb = [b for b in all_bars[sym] if str(b.get("time", "")) <= dt_]
                if len(lb) < 30: continue
                r = score_momentum(lb) if use_mom else score_reversal(lb)
                if r["grade"] in ("D", "C") or r["score"] < ms: continue
                cand.append((sym, r))
            cand.sort(key=lambda x: -x[1]["score"])
            for sym, r in cand[:mx - len(pos)]:
                ei = di + 1
                if ei >= len(dates): continue
                ed = dates[ei]; eb = next((b for b in all_bars[sym] if str(b.get("time", "")) == ed), None)
                if not eb: continue
                ep = _sf(eb.get("open"))
                if ep <= 0: continue
                sc = r["score"]
                alloc = min(cp + 0.05, 0.35) if sc >= 80 else cp if sc >= 70 else cp * 0.8
                amt = min(cash * alloc, ic * 0.30)
                qty = max(100, int(amt / ep / 100) * 100); cost = qty * ep; fee = cost * 0.0003
                if cash < cost + fee: continue
                cash -= cost + fee; comm += fee
                pos[sym] = {"sym": sym, "qty": qty, "ep": ep, "ed": ed, "mp": ep,
                            "tp": r["target_pct"], "sp": r["stop_pct"], "hd": r["hold_days"],
                            "sc": r["score"], "sig": r.get("signals", ""), "reg": regime, "mode": r["mode"]}
                log.append({"date": ed, "d": "B", "sym": sym, "p": ep, "q": qty,
                            "sc": r["score"], "sig": r.get("signals", ""), "mode": r["mode"], "reg": regime})

        for sym in list(pos.keys()):
            p = pos[sym]
            td = next((b for b in all_bars.get(sym, []) if str(b.get("time", "")) == dt_), None)
            if not td: continue
            hi, lo, cl = _sf(td.get("high")), _sf(td.get("low")), _sf(td.get("close"))
            if hi > p["mp"]: p["mp"] = hi
            if p["ed"] == dt_: continue
            ep, cp_, mp_ = p["ep"], (cl - p["ep"]) / p["ep"] * 100, (p["mp"] - p["ep"]) / p["ep"] * 100
            hold = (dt.date.fromisoformat(dt_) - dt.date.fromisoformat(p["ed"])).days
            sell = False; sp_ = cl; why = ""
            if cp_ >= p["tp"]:
                sell = True; why = f"目标+{p['tp']:.0f}%"
            elif mp_ >= 5.0:
                tr = 0.3 if mp_ >= 8 else 0.4
                tp = ep * (1 + mp_ * (1 - tr) / 100)
                if lo <= tp: sell = True; sp_ = tp; why = f"回落{tr*100:.0f}%(高{mp_:.1f}%)"
            elif cp_ <= p["sp"]:
                sell = True; why = f"止损{p['sp']:.0f}%"
            elif mp_ >= 3.0 and cp_ < 0.3:
                sell = True; why = f"保本(曾{mp_:.1f}%)"
            elif hold >= 2 and cp_ < -0.5:
                sell = True; why = f"弱{hold}d"
            elif hold >= 5:
                sell = True; why = f"时间{hold}d"
            if sell:
                rev = p["qty"] * sp_; fee = rev * 0.0013
                cash += rev - fee; comm += fee
                pnl = (rev - fee) - (p["qty"] * ep); pnl_pct = pnl / (p["qty"] * ep) * 100
                log.append({"date": dt_, "d": "S", "sym": sym, "p": sp_, "q": p["qty"],
                            "pnl": pnl, "pp": pnl_pct, "hold": hold, "why": why,
                            "sc": p["sc"], "mode": p["mode"], "reg": p["reg"]})
                del pos[sym]

        pv = sum(p["qty"] * _sf(next((b for b in all_bars.get(sym, [])
                    if str(b.get("time", "")) == dt_), {}).get("close", p["ep"]))
                for sym, p in pos.items())
        te = cash + pv
        if te > peak: peak = te
        eq.append({"date": dt_, "te": round(te, 2), "n": len(pos), "reg": regime})

    fin = eq[-1]; net = fin["te"] - ic; ret = net / ic * 100
    mo = max(1, (dt.date.fromisoformat(end_date) - dt.date.fromisoformat(start_date)).days / 30)
    mr = ((1 + ret / 100) ** (1 / mo) - 1) * 100
    closed = [t for t in log if t["d"] == "S"]
    wins = [t for t in closed if t.get("pnl", 0) > 0]
    losses = [t for t in closed if t.get("pnl", 0) <= 0]
    wr = len(wins) / len(closed) * 100 if closed else 0
    aw = sum(t["pnl"] for t in wins) / len(wins) if wins else 0
    al = abs(sum(t["pnl"] for t in losses)) / len(losses) if losses else 1
    pf = (sum(t["pnl"] for t in wins) or 0) / (abs(sum(t["pnl"] for t in losses)) or 1)
    peak2 = ic; mdd = 0.0
    for e in eq:
        if e["te"] > peak2: peak2 = e["te"]
        dd = (peak2 - e["te"]) / peak2 * 100
        if dd > mdd: mdd = dd

    # Summary
    print(f"\n{'Date':<10} D {'Sym':<10} {'Prc':>6} {'Qty':>5} {'Sc':>4} {'Mode':<4} {'PnL':>8} {'%':>5} Reason")
    print("-" * 95)
    for t in log:
        if t["d"] == "B":
            print(f"{t['date']} B {t['sym']:10s} {t['p']:>6.2f} {t['q']:>5d} {t.get('sc',0):>4.0f} {t.get('mode',''):<4s} {'---':>8}  ---")
        else:
            print(f"{t['date']} S {t['sym']:10s} {t['p']:>6.2f} {t['q']:>5d} {t.get('sc',0):>4.0f} {t.get('mode',''):<4s} {t.get('pnl',0):>+8.0f} {t.get('pp',0):>+5.1f}% | {t['why']}")

    for mode, label in [("mom", "Momentum"), ("rev", "Reversal")]:
        sub = [t for t in closed if t.get("mode") == mode]
        if sub:
            sw = [t for t in sub if t["pnl"] > 0]; sl = [t for t in sub if t["pnl"] <= 0]
            avg_w = sum(t["pnl"] for t in sw) / len(sw) if sw else 0
            avg_l = abs(sum(t["pnl"] for t in sl)) / len(sl) if sl else 0
            print(f"  {label}: {len(sub)}t WR={len(sw)/len(sub)*100:.0f}% "
                  f"PnL={sum(t['pnl'] for t in sub):+,.0f} W={avg_w:+,.0f} L={avg_l:+,.0f}")

    print(f"\n{'='*110}")
    print(f"Period: {dates[0]}~{dates[-1]} ({len(dates)}d)  "
          f"Init: {ic:,.0f}  Final: {fin['te']:,.0f}  PnL: {net:+,.0f}  Ret: {ret:+.2f}%")
    print(f"Monthly: {mr:+.2f}%  WR: {wr:.0f}%  PF: {pf:.2f}  MDD: {mdd:.2f}%  "
          f"Trades: {len(closed)}  AvgW: {aw:+,.0f}  AvgL: {al:+,.0f}  Comm: {comm:.0f}")
    print(f"W/L: {aw/max(al,1):.2f}x")
    print("=" * 110)
    return {"ret": ret, "mr": mr, "wr": wr, "pf": pf, "mdd": mdd, "trades": len(closed)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-09-30")
    ap.add_argument("--capital", type=float, default=400000.0)
    args = ap.parse_args()
    run_backtest(STOCK_UNIVERSE, args.start, args.end, args.capital)


if __name__ == "__main__":
    main()
