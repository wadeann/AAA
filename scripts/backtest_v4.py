#!/usr/bin/env python3
"""
Astock 动量回测引擎 v4 — 目标月收益 30%.

核心: 统一评分 + 紧止损 + 移动止盈 + 大盘体制调仓.
用法:
  python3 -m scripts.backtest_v4 --pool 20 --capital 400000
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path
from typing import Any

from mcp_client import get_mcp_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.cost_model import buy_cost, sell_cost

CST = dt.timezone(dt.timedelta(hours=8))

STOCK_POOL = [
    "600519.SH", "000858.SZ", "601899.SH", "600036.SH",
    "002594.SZ", "300750.SZ", "688981.SH", "000333.SZ",
    "601318.SH", "600900.SH", "002415.SZ", "600276.SH",
    "000568.SZ", "002714.SZ", "601012.SH", "600309.SH",
    "000725.SZ", "601166.SH", "002475.SZ", "600585.SH",
    "300059.SZ", "002230.SZ", "300274.SZ", "688041.SH",
    "002371.SZ", "300124.SZ", "300308.SZ", "000977.SZ",
    "300896.SZ", "300760.SZ", "300033.SZ", "300661.SZ",
]

# 用于实盘的 MCP 动态扫描接口
def screen_market_top_n(n: int = 50, min_vol_ratio: float = 1.5) -> list[str]:
    """Use MCP screen_stocks to discover top candidates dynamically."""
    try:
        result = get_mcp_client().call("screen_stocks", {
            "query": f"成交量大于{min_vol_ratio}倍,换手率大于1%,非ST,股价大于5元",
            "limit": n,
        })
        if isinstance(result, dict) and "stocks" in result:
            return [s.get("code", "") for s in result["stocks"]]
        if isinstance(result, list):
            return [s.get("code", "") if isinstance(s, dict) else str(s) for s in result]
        return []
    except Exception:
        return []


def quick_filter(bars: list[dict], min_vr: float = 0.8, min_close: float = 3.0) -> bool:
    """快速预筛选: 避免对每只股票都跑完整评分."""
    if len(bars) < 25:
        return False
    last = bars[-1]
    close = _sf(last.get("close"))
    if close < min_close:
        return False
    vol = _sf(last.get("volume"))
    if vol <= 0:
        return False
    avg_v = sma(bars, "volume", 20)
    vr = vol / avg_v if avg_v > 0 else 0
    return vr >= min_vr

_MCP_CACHE: dict[str, list[dict]] = {}


def _sf(v: Any, d: float = 0.0) -> float:
    try: return float(v) if v is not None else d
    except (TypeError, ValueError): return d


def fetch_klines(symbol: str, count: int = 100) -> list[dict]:
    key = f"{symbol}_{count}"
    if key in _MCP_CACHE:
        return _MCP_CACHE[key]
    try:
        raw = get_mcp_client().call("fetch_kline", {"symbol": symbol, "period": "D", "count": count})
        if isinstance(raw, dict):
            klines = raw.get("klines", [])
            if klines:
                _MCP_CACHE[key] = klines
                return klines
        if isinstance(raw, list):
            _MCP_CACHE[key] = raw
            return raw
    except Exception:
        pass
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


def get_regime(index_bars: list[dict], curr_date: str) -> str:
    bars = [b for b in index_bars if str(b.get("time", "")) <= curr_date]
    if len(bars) < 10:
        return "warmup"
    c5 = [_sf(b.get("close")) for b in bars[-5:]]
    chg5 = (c5[-1] - c5[0]) / c5[0] * 100 if c5[0] > 0 else 0
    ma10, ma20 = sma(bars, "close", 10), sma(bars, "close", 20)
    lc = _sf(bars[-1].get("close"))
    if chg5 > 3 and lc > ma10 > ma20: return "euphoria"
    if chg5 > 1 and lc > ma20: return "hot"
    if chg5 > -1.5 and lc > ma20 * 0.95: return "warmup"
    if chg5 > -3: return "cooldown"
    return "ice"


# Each regime → (min_score, max_pos, cap_pct)
REGIME_MAP = {
    "euphoria": (40, 6, 0.28),
    "hot":      (52, 3, 0.15),
    "warmup":   (48, 5, 0.22),
    "cooldown": (45, 5, 0.25),
    "ice":      (55, 2, 0.12),
}


def score_stock(bars: list[dict]) -> dict[str, Any]:
    """Unified momentum score. Returns {score, name, target%, stop%, hold}."""
    if len(bars) < 25:
        return {"score": 0, "grade": "D"}

    last = bars[-1]
    close, vol, chg = _sf(last.get("close")), _sf(last.get("volume")), _sf(last.get("change_pct"))
    high, low, open_p = _sf(last.get("high")), _sf(last.get("low")), _sf(last.get("open"))
    avg_vol = sma(bars, "volume", 20)
    vr = vol / avg_vol if avg_vol > 0 else 0
    ma5, ma10, ma20 = sma(bars, "close", 5), sma(bars, "close", 10), sma(bars, "close", 20)
    rs = rsi(bars)
    h10 = [_sf(b.get("high")) for b in bars[-10:]]
    hi10 = max(h10) if h10 else close
    dh = (hi10 - close) / hi10 * 100

    # Hard filters: not in freefall, not dead
    if vr < 0.5 or rs < 25:
        return {"score": 0, "grade": "D"}

    score = 0
    name = "momentum"

    # 1. Volume ratio (0-25)
    if vr > 3.0: score += 25
    elif vr > 2.0: score += 20
    elif vr > 1.5: score += 15
    elif vr > 1.2: score += 10
    elif vr > 1.0: score += 6
    else: score += 3

    # 2. Distance from 10d high (0-20) — momentum proxy
    if dh < 1: score += 20
    elif dh < 3: score += 16
    elif dh < 5: score += 12
    elif dh < 8: score += 7
    elif dh < 12: score += 4

    # 3. MA alignment (0-20)
    if close > ma5 > ma10 > ma20: score += 20; name = "trend"
    elif close > ma5 > ma20: score += 14
    elif close > ma20: score += 10
    elif ma5 > ma10 > ma20: score += 6
    else: score += 2

    # 4. RSI zone (0-15)
    if 45 <= rs <= 65: score += 15
    elif 65 < rs <= 75: score += 10
    elif 35 <= rs < 45: score += 8
    elif rs > 75: score += 4
    else: score += 2

    # 5. Daily change (0-15)
    if chg > 7: score += 15; name = "ignition"
    elif chg > 5: score += 13; name = "ignition"
    elif chg > 3: score += 10
    elif chg > 1.5: score += 7
    elif chg > 0.5: score += 4
    else: score += 1

    # 6. Volatility (0-10)
    rng = (high - low) / low * 100 if low > 0 else 0
    if rng > 5: score += 10
    elif rng > 3: score += 7
    elif rng > 2: score += 4
    else: score += 1

    # 7. Gap-up bonus (0-5)
    pc = _sf(bars[-2].get("close")) if len(bars) > 1 else open_p
    gap = (open_p - pc) / pc * 100
    if gap > 1: score += 5
    elif gap > 0.3: score += 3

    # 8. Pullback bonus: big up in last 10d + volume shrinking (0-10)
    chgs = []
    for b in bars[-10:-1]:
        o, c = _sf(b.get("open")), _sf(b.get("close"))
        if o > 0: chgs.append((c - o) / o * 100)
    if chgs and max(chgs) > 5 and vr < 0.9:
        score += 10
        name = "pullback"

    score = min(score, 100)
    if score >= 65: grade = "A"
    elif score >= 50: grade = "B"
    elif score >= 35: grade = "C"
    else: grade = "D"

    return {"score": score, "grade": grade, "name": name,
            "target_pct": 6, "stop_pct": -4, "hold_days": 4}


def run_backtest(symbols: list[str], start_date: str, end_date: str, ic: float = 400000.0) -> dict:
    all_bars = {}
    for sym in symbols:
        bars = fetch_klines(sym, 200)
        if len(bars) >= 60:
            all_bars[sym] = bars
    index_bars = fetch_klines("000001.SH", 200)
    if not index_bars:
        print("No index data"); return {}

    dates = sorted({str(b.get("time")) for b in index_bars if start_date <= str(b.get("time", "")) <= end_date})
    if len(dates) < 10:
        print(f"Too few dates: {len(dates)}"); return {}

    print(f"Pool: {len(all_bars)} | Days: {len(dates)} ({dates[0]}~{dates[-1]}) | Cap: {ic:,.0f} | Target: 30%/mo")
    print("=" * 100)

    cash, peak = ic, ic
    pos: dict[str, dict] = {}
    log: list[dict] = []
    eq: list[dict] = []
    comm = 0.0

    for di, dt_ in enumerate(dates):
        regime = get_regime(index_bars, dt_)
        ms, mx, cp = REGIME_MAP[regime]

        # ── BUY (with quick pre-filter) ──
        if len(pos) < mx:
            cand = []
            for sym in all_bars:
                if sym in pos:
                    continue
                lb = [b for b in all_bars[sym] if str(b.get("time", "")) <= dt_]
                if len(lb) < 25:
                    continue
                # Pre-filter: skip dead stocks
                if not quick_filter(lb, min_vr=0.8):
                    continue
                r = score_stock(lb)
                if r["grade"] in ("D", "C") or r["score"] < ms:
                    continue
                cand.append((sym, r))
            cand.sort(key=lambda x: -x[1]["score"])
            for sym, r in cand[:mx - len(pos)]:
                ei = di + 1
                if ei >= len(dates):
                    continue
                ed = dates[ei]
                eb = next((b for b in all_bars[sym] if str(b.get("time", "")) == ed), None)
                if not eb:
                    continue
                ep = _sf(eb.get("open"))
                if ep <= 0:
                    continue
                amt = min(cash * cp, ic * 0.18)
                qty = max(100, int(amt / ep / 100) * 100)
                cost = qty * ep
                fee = buy_cost(cost, sym)
                if cash < cost + fee:
                    continue
                cash -= cost + fee
                comm += fee
                pos[sym] = {"sym": sym, "qty": qty, "ep": ep, "ed": ed,
                            "mp": ep, "tp": r["target_pct"], "sp": r["stop_pct"],
                            "hd": r["hold_days"], "sc": r["score"], "nm": r["name"],
                            "reg": regime}
                log.append({"date": ed, "d": "B", "sym": sym, "p": ep, "q": qty,
                            "sc": r["score"], "nm": r["name"],
                            "r": f"[{r['name']}] vr={vr:.1f}x" if 'vr' in dir() else f"[{r['name']}]"})

        # ── SELL ──
        for sym in list(pos.keys()):
            p = pos[sym]
            td = next((b for b in all_bars.get(sym, []) if str(b.get("time", "")) == dt_), None)
            if not td:
                continue
            hi, lo, cl = _sf(td.get("high")), _sf(td.get("low")), _sf(td.get("close"))
            if hi > p["mp"]:
                p["mp"] = hi
            if p["ed"] == dt_:
                continue
            ep = p["ep"]
            cp_ = (cl - ep) / ep * 100
            mp_ = (p["mp"] - ep) / ep * 100
            hold = (dt.date.fromisoformat(dt_) - dt.date.fromisoformat(p["ed"])).days

            sell = False; sp_ = cl; why = ""

            if cp_ >= p["tp"]:
                sell = True; why = f"目标{p['tp']}%"

            if not sell and mp_ >= 4.0:
                tr = ep * (1 + mp_ * 0.5 / 100)
                if lo <= tr:
                    sell = True; sp_ = tr; why = f"回落50%止盈(曾{mp_:.1f}%)"

            if not sell and cp_ <= p["sp"]:
                sell = True; why = f"止损{p['sp']:.0f}%"

            mh = int(p["hd"] * 1.3) + 1
            if not sell and hold >= mh and cp_ < 1.5:
                sell = True; why = f"持仓{hold}d平仓"

            if not sell and mp_ >= 3.0 and cp_ < 0.2:
                sell = True; why = f"保本出(曾{mp_:.1f}%)"

            if sell:
                rev = p["qty"] * sp_
                fee = sell_cost(rev, sym)
                cash += rev - fee
                comm += fee
                pnl = (rev - fee) - (p["qty"] * ep)
                pnl_pct = pnl / (p["qty"] * ep) * 100
                log.append({"date": dt_, "d": "S", "sym": sym, "p": sp_, "q": p["qty"],
                            "pnl": pnl, "pp": pnl_pct, "hold": hold, "why": why,
                            "nm": p["nm"], "reg": p["reg"], "sc": p["sc"]})
                del pos[sym]

        # Daily equity
        pv = 0.0
        for sym, p in pos.items():
            cb = next((b for b in all_bars.get(sym, []) if str(b.get("time", "")) == dt_), None)
            ccp = _sf(cb.get("close", p["ep"])) if cb else p["ep"]
            pv += p["qty"] * ccp
        te = cash + pv
        if te > peak: peak = te
        eq.append({"date": dt_, "cash": round(cash, 2), "pv": round(pv, 2),
                   "te": round(te, 2), "n": len(pos), "reg": regime})

    # ── Stats ──
    fin = eq[-1]
    net = fin["te"] - ic
    ret = net / ic * 100
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

    # Print
    print(f"\n{'Date':<10} D  {'Sym':<10} {'Prc':>6} {'Qty':>5} {'Strat':<9} {'PnL':>8} {'%':>5} Reason")
    print("-" * 95)
    for t in log:
        if t["d"] == "B":
            print(f"{t['date']} B  {t['sym']:10s} {t['p']:>6.2f} {t['q']:>5d} {t.get('nm','?'):<9} {'---':>8}  --- | {t.get('r','')}")
        else:
            print(f"{t['date']} S  {t['sym']:10s} {t['p']:>6.2f} {t['q']:>5d} {t.get('nm','?'):<9} {t.get('pnl',0):>+8.0f} {t.get('pp',0):>+5.1f}% | {t['why']}")

    # Strategy breakdown
    ss = {}
    for t in closed:
        n = t.get("nm", "?")
        if n not in ss: ss[n] = {"n": 0, "w": 0, "p": 0.0}
        ss[n]["n"] += 1
        if t.get("pnl", 0) > 0: ss[n]["w"] += 1
        ss[n]["p"] += t.get("pnl", 0)
    print(f"\n{'─'*20} Strategy {'─'*20}")
    print(f"{'Strat':<9} {'Trades':>6} {'Wins':>4} {'WR':>5} {'PnL':>10}")
    print("-" * 38)
    for n, s in sorted(ss.items(), key=lambda x: -x[1]["p"]):
        sw = s["w"] / s["n"] * 100 if s["n"] else 0
        print(f"{n:<9} {s['n']:>6} {s['w']:>4} {sw:>4.0f}% {s['p']:>+9.0f}")

    # Regime breakdown
    rs_ = {}
    for t in closed:
        r = t.get("reg", "?")
        if r not in rs_: rs_[r] = {"n": 0, "w": 0, "p": 0.0}
        rs_[r]["n"] += 1
        if t.get("pnl", 0) > 0: rs_[r]["w"] += 1
        rs_[r]["p"] += t.get("pnl", 0)
    print(f"\n{'─'*20} Regime {'─'*20}")
    print(f"{'Regime':<9} {'Trades':>6} {'Wins':>4} {'WR':>5} {'PnL':>10}")
    print("-" * 38)
    for r, s in sorted(rs_.items(), key=lambda x: -x[1]["p"]):
        rw = s["w"] / s["n"] * 100 if s["n"] else 0
        print(f"{r:<9} {s['n']:>6} {s['w']:>4} {rw:>4.0f}% {s['p']:>+9.0f}")

    print(f"\n{'='*100}")
    print(f"Period: {dates[0]}~{dates[-1]} ({len(dates)}d)  "
          f"Init: {ic:,.0f}  Final: {fin['te']:,.0f}  PnL: {net:+,.0f}  Ret: {ret:+.2f}%")
    print(f"Monthly: {mr:+.2f}%  WR: {wr:.0f}%  PF: {pf:.2f}  MDD: {mdd:.2f}%  "
          f"Trades: {len(closed)}  AvgW: {aw:+,.0f}  AvgL: {al:+,.0f}  Comm: {comm:.0f}")
    print("=" * 100)
    return {"ret": ret, "mr": mr, "wr": wr, "pf": pf, "mdd": mdd, "trades": len(closed)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-09-30")
    ap.add_argument("--capital", type=float, default=400000.0)
    ap.add_argument("--symbols")
    args = ap.parse_args()
    symbols = [s.strip() for s in args.symbols.split(",")] if args.symbols else STOCK_POOL
    run_backtest(symbols, args.start, args.end, args.capital)


if __name__ == "__main__":
    main()
