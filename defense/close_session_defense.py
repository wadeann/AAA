#!/usr/bin/env python3
"""尾盘14:15-14:56脚本 — 卖出 + 恐慌抄底。

三遍扫描: 14:15 / 14:30 / 14:45 (由 cron 或调度器触发)
卖出: 持仓出现卖点/背驰 → 写候选 → 闸门执行
恐慌抄底: 上证跌>1.5% + 个股底背驰 + 企稳 → 写awaiting_llm_review候选 → LLM二审 → 闸门执行
normal: 上证未达恐慌线 → 只卖不买
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from data import get_data_manager
from mcp_client import get_mcp_client
from config import DATA_DIR, STATE_DIR

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from chanlun_engine import analyze_chanlun  # type: ignore
except ImportError:
    analyze_chanlun = None  # type: ignore

MONITOR = STATE_DIR / "monitor"
STATE_FILE = MONITOR / "close-session-state.json"


def parse_quote(raw: Any) -> dict[str, Any]:
    """将 query_data 返回的 {"tables": [...]} 格式解析为平铺字典。"""
    if isinstance(raw, dict):
        if "tables" in raw:
            try:
                table = raw["tables"][0]
                cols = table["columns"]
                row = table["rows"][0]
                return dict(zip(cols, row))
            except (IndexError, KeyError, TypeError):
                return {}
        return raw
    return {}


def extract_rows(raw: Any, keys=("klines", "data", "rows", "datas", "items")) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        for key in keys:
            value = raw.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
    return []


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    MONITOR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def in_close_window(now: dt.datetime | None = None) -> bool:
    now = now or dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
    current = now.time().replace(second=0, microsecond=0)
    return dt.time(14, 15) <= current <= dt.time(14, 56)


def get_positions(client: Any) -> list[dict[str, Any]]:
    try:
        result = client.get_positions()
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("positions", [])
        return []
    except Exception:
        return []


def get_holdings_today(
    client: Any,
    positions: list[dict[str, Any]],
    today_trades: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """区分今日真实可用持仓(T+0底仓可卖)与今日买入的T+1锁定股票。"""
    if today_trades is None:
        try:
            raw_trades = client.get_today_trades()
            today_trades = raw_trades if isinstance(raw_trades, list) else raw_trades.get("trades", raw_trades.get("data", [])) if isinstance(raw_trades, dict) else []
        except Exception:
            today_trades = []

    today_buys: dict[str, int] = {}
    for t in (today_trades or []):
        if str(t.get("direction", "")).upper() == "BUY":
            s = str(t.get("symbol", ""))
            today_buys[s] = today_buys.get(s, 0) + int(float(t.get("quantity", 0) or 0))

    can_sell: list[dict[str, Any]] = []
    locked_t1: list[dict[str, Any]] = []
    for pos in positions:
        sym = str(pos.get("symbol", ""))
        qty = int(float(pos.get("quantity", 0) or 0))
        av_raw = pos.get("available_quantity")
        if av_raw is None:
            av_raw = pos.get("available_shares")

        buy_date = str(pos.get("buy_date", ""))[:10]
        if av_raw is not None:
            av = int(float(av_raw or 0))
        elif buy_date == dt.date.today().isoformat():
            av = 0
        else:
            bought_today = today_buys.get(sym, 0)
            av = max(0, qty - bought_today)

        pos["available_calc"] = av
        if av <= 0:
            locked_t1.append(pos)
        else:
            can_sell.append(pos)
    return can_sell, locked_t1


def format_price(price: float) -> str:
    if price >= 100:
        return f"{price:.1f}"
    return f"{price:.2f}"


def append_candidate(dm: Any, record: dict[str, Any]) -> bool:
    """写入候选。"""
    dm.append_jsonl(record, date=dt.date.today().isoformat())
    return True


def run_trade_gate() -> str:
    gate = Path(__file__).resolve().parent.parent / "execution" / "batch_trade_gate.py"
    if not gate.exists():
        return ""
    try:
        result = subprocess.run(
            [sys.executable, str(gate)],
            capture_output=True, text=True, timeout=90,
        )
        return (result.stdout or result.stderr or "").strip()[-800:]
    except Exception:
        return ""


def is_panic_day(sh_pct: float, cy_pct: float = 0.0) -> bool:
    """恐慌日判定: 上证跌 > 1.5% 或 创业板跌 > 2.0% 或 双指均跌 > 1.5%"""
    if sh_pct < -1.5:
        return True
    if cy_pct < -2.0:
        return True
    if cy_pct != 0.0 and (sh_pct + cy_pct) / 2 < -1.5:
        return True
    return False


def check_bottoming(bars: list[dict[str, Any]]) -> bool:
    """检查最近30分钟是否企稳: 最后3根K线低点不再创新低。"""
    if len(bars) < 5:
        return False
    lows = [float(b.get("low", 0) or 0) for b in bars[-5:]]
    if any(l <= 0 for l in lows):
        return False
    return lows[-3] < lows[-2] < lows[-1]


def get_watchlist_stocks(client: Any) -> list[dict[str, Any]]:
    """从涨停观察池 + 警戒计划拉出潜在抄底标的。"""
    client_mcp = client
    candidates: list[dict[str, Any]] = []

    # 从 Intel MCP 获取 watchlist
    try:
        watch_data = client_mcp.get_watchlist()
        if watch_data:
            for r in watch_data:
                if r.get("watch_level") in ("重点关注", "涨停观察"):
                    r["direction"] = "buy"
                    candidates.append(r)
    except Exception:
        pass

    # 去重
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for c in candidates:
        sym = str(c.get("symbol", ""))
        if sym and sym not in seen:
            seen.add(sym)
            unique.append(c)
    return unique


def evaluate_panic_buy(
    client: Any,
    plan: dict[str, Any],
    bars30: list[dict[str, Any]],
    live_price: float,
) -> dict[str, Any] | None:
    """评估恐慌抄底候选。"""
    if analyze_chanlun is None:
        return None

    symbol = str(plan["symbol"])

    if len(bars30) < 50:
        return None

    analysis = analyze_chanlun(bars30)
    trend = analysis.get("trend_type", "undetermined")
    buy_point = analysis.get("buy_point")
    divergence = analysis.get("divergence", {})
    breakout = analysis.get("breakout_signal", {})

    # 必要条件1: 跌到支撑位 (中枢下沿附近)
    pivots = analysis.get("pivots") or []
    last_pivot = pivots[-1] if pivots and isinstance(pivots[-1], dict) else {}
    zs = last_pivot.get("zd") or analysis.get("pivot_low") or analysis.get("base_low")
    if not zs and trend == "downtrend":
        lows = [float(b.get("low", 0) or 0) for b in bars30[-30:-5]]
        if lows:
            zs = min(lows)

    near_support = bool(zs) and zs > 0 and abs(live_price - zs) / zs < 0.03

    # 必要条件2: 30分钟出现底背驰或一买
    has_buy_structure = (
        buy_point in ("一买", "二买")
        or divergence.get("type") == "bottom_divergence"
        or breakout.get("status") == "confirmed"
    )

    # 必要条件3: 价格企稳
    bottoming = check_bottoming(bars30)

    if not has_buy_structure:
        return None
    if not near_support and not buy_point:
        return None
    if not bottoming and buy_point != "一买":
        return None

    # 查新闻排除暴雷
    try:
        news = client.news_search(symbol)
        news_text = json.dumps(news, ensure_ascii=False)
        if "亏损" in news_text or "退市" in news_text or "立案" in news_text:
            return None
    except Exception:
        pass

    # 查基本面
    try:
        quote = parse_quote(client.call("query_data", {"symbol": symbol}, port=9001))
    except Exception:
        quote = {}

    confidence = 0.62
    if buy_point == "一买" and bottoming:
        confidence = 0.68
    if near_support and has_buy_structure:
        confidence = 0.65
    if near_support and has_buy_structure and bottoming:
        confidence = 0.68

    return {
        "symbol": symbol,
        "name": plan.get("name", symbol),
        "price": live_price,
        "buy_point": buy_point,
        "trend": trend,
        "divergence_type": divergence.get("type"),
        "pivot_low": zs,
        "near_support": near_support,
        "bottoming": bottoming,
        "confidence": confidence,
        "thesis": (
            f"[尾盘恐慌抄底] {buy_point or '底背驰'}·支撑{zs:.2f}"
            if zs is not None and zs > 0
            else f"[尾盘恐慌抄底] {buy_point or '底背驰'}"
        ),
    }


def main() -> int:
    client = get_mcp_client()
    dm = get_data_manager()

    if not in_close_window():
        return 0

    try:
        sessions = client.get_trading_sessions()
        if not isinstance(sessions, dict) or sessions.get("is_trading_day") is not True:
            return 0
    except Exception:
        return 0

    # 大盘快照 (上证 + 创业板)
    try:
        sh = parse_quote(client.call("query_data", {"symbol": "000001.SH"}, port=9001))
        sh_price = float(sh.get("price", 0) or 0)
        sh_pct = float(sh.get("change_pct", 0) or 0)
        cy = parse_quote(client.call("query_data", {"symbol": "399006.SZ"}, port=9001))
        cy_pct = float(cy.get("change_pct", 0) or 0)
    except Exception:
        sh_price, sh_pct, cy_pct = 0.0, 0.0, 0.0

    try:
        pnl_data = client.daily_pnl()
        pnl = pnl_data.get("daily_pnl", 0) if isinstance(pnl_data, dict) else 0
    except Exception:
        pnl = 0

    header = f"?尾盘14:15 | 上证{sh_price:.0f}({sh_pct:+.2f}%) 创指{cy_pct:+.2f}% | 盈亏≈{pnl:+.0f}元"

    # ── 模式判定 ──
    is_panic = is_panic_day(sh_pct, cy_pct)
    mode_label = "?恐慌·卖+抄底" if is_panic else "?正常·只卖"

    positions = get_positions(client)
    can_sell, locked_t1 = get_holdings_today(client, positions) if positions else ([], [])

    if locked_t1:
        locked_names = " · ".join(
            f"{p.get('name', p.get('symbol','?'))}"
            for p in locked_t1[:3])
        header += f"\n?T+1锁定: {locked_names}"

    state = load_state()
    today = dt.date.today().isoformat()
    all_signals: list[str] = []

    # ══════════════════════════
    # 卖出: 持仓卖出信号（含涨停豁免）
    # ══════════════════════════
    for pos in can_sell:
        symbol = str(pos.get("symbol", ""))
        name = pos.get("name", symbol)
        available = int(pos.get("available_calc", pos.get("available_quantity", pos.get("available_shares", pos.get("quantity", 0)))) or 0)

        if not symbol or available < 100:
            continue

        try:
            raw30 = client.call("fetch_kline", {"symbol": symbol, "period": "30", "count": 100})
            bars30 = extract_rows(raw30)
            raw60 = client.call("fetch_kline", {"symbol": symbol, "period": "60", "count": 100})
            bars60 = extract_rows(raw60)
        except Exception:
            continue

        if len(bars30) < 50:
            continue

        live_price = 0.0
        pre_close = 0.0
        try:
            quote = parse_quote(client.call("query_data", {"symbol": symbol}, port=9001))
            live_price = float(quote.get("price", quote.get("最新价", 0)) or 0)
            pre_close = float(quote.get("pre_close", quote.get("prev_close", quote.get("昨收", 0))) or 0)

            if pre_close > 0 and live_price > 0:
                sym_up = symbol.upper()
                limit_ratio = 0.10
                if sym_up.startswith(("300", "301", "688")):
                    limit_ratio = 0.20
                elif sym_up.startswith(("920", "8", "4")):
                    limit_ratio = 0.30

                name = quote.get("name", "") or name
                if "ST" in name:
                    limit_ratio = 0.05

                limit_price = round(pre_close * (1 + limit_ratio), 2)
                ask1_vol = float(quote.get("ask1_volume", quote.get("卖一量", 0)) or 0)
                limit_threshold = max(0.015, limit_price * 0.003)
                is_at_limit = abs(live_price - limit_price) < limit_threshold

                if is_at_limit and ask1_vol == 0:
                    all_signals.append(f"?涨停豁免 {name}({symbol}) 今日涨停·跳过尾盘清仓")
                    continue
                elif is_at_limit and ask1_vol > 0:
                    all_signals.append(f"?触及涨停未封 {name}({symbol}) 卖一有{ask1_vol}股·继续评估")
        except Exception:
            pass

        if analyze_chanlun is None:
            continue

        analysis30 = analyze_chanlun(bars30)
        analysis60 = analyze_chanlun(bars60) if len(bars60) >= 30 else None

        if live_price <= 0:
            continue

        trend30 = analysis30.get("trend_type", "undetermined")
        sell30 = analysis30.get("sell_point")
        div30 = analysis30.get("divergence", {})
        trend60 = analysis60.get("trend_type", "undetermined") if analysis60 else ""
        sell60 = analysis60.get("sell_point") if analysis60 else None

        if trend30 == "uptrend" and trend60 == "uptrend":
            continue
        if trend60 == "uptrend" and sell30 and not sell60:
            event_key = f"{symbol}:sell-skip-uptrend60:{today}"
            if not state.get(event_key):
                state[event_key] = {
                    "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                    "price": live_price,
                    "reason": "60m依然上行,30m回调不卖",
                }
            continue

        # 四维共振保护
        try:
            from market_resonance_engine import analyze_sector_resonance  # type: ignore
            sec_diag = analyze_sector_resonance(symbol)
            if sec_diag.get("role") == "primary_attack" and not (sell30 == "一卖" and sell60 == "一卖"):
                sec_name = sec_diag.get("sector", "主攻板块")
                event_key = f"{symbol}:sell-skip-primary-sector:{today}"
                if not state.get(event_key):
                    state[event_key] = {
                        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "price": live_price,
                        "reason": f"{sec_name}为主攻核心题材，小级别背驰享受溢价保护不卖",
                    }
                all_signals.append(f"?主线溢价保护 {name}({symbol}) 所属{sec_name}为主攻核心·暂不因小级别背驰卖出")
                continue
        except Exception:
            pass

        has_signal = bool(sell30 or sell60 or div30.get("type") == "top_divergence")
        if not has_signal:
            continue

        event_key = f"{symbol}:sell:{today}"
        if state.get(event_key):
            continue

        state[event_key] = {
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "price": live_price,
        }

        candidate_id = f"close-{symbol}-sell-{today}"
        record = {
            "record_type": "candidate",
            "date": today,
            "candidate_id": candidate_id,
            "symbol": symbol, "name": name,
            "direction": "sell", "price": live_price,
            "quantity": available,
            "confidence": 0.78 if sell30 == "一卖" else 0.70,
            "llm_approved": True,
            "agy_approved": True,
            "reviewed_by": "TailRiskDefense",
            "reasoning": f"尾盘风控触发{sell30 or sell60}·背驰{div30.get('type','无')}·防守卖出",
            "chan_sell_point": sell30 or sell60,
            "chan_confirmed": True,
            "trend_type": trend30, "trend60": trend60,
            "divergence": div30.get("type"),
            "position_class": "波段票",
            "thesis": f"[尾盘] {sell30 or sell60}触发·{trend30}/{trend60}·背驰{div30.get('type','无')}",
            "entry_rule": sell30 or sell60 or "sell_structure",
            "catalyst_type": "close_sell_signal",
            "source": "close_session",
        }
        append_candidate(dm, record)

        all_signals.append(
            f"?卖出 {name}({symbol}) 现价{format_price(live_price)} → {available}股\n"
            f"　{sell30 or sell60}·{trend30}/{trend60}·{div30.get('type','')}")

    # ══════════════════════════
    # 恐慌抄底: 只在恐慌日
    # ══════════════════════════
    panic_buys: list[dict[str, Any]] = []
    if is_panic:
        watchlist = get_watchlist_stocks(client)
        checked_buy: set[str] = set()

        for plan in watchlist:
            symbol = str(plan.get("symbol", ""))
            if symbol in checked_buy:
                continue

            # 跳过已持仓的
            holding_symbols = {str(p.get("symbol", "")) for p in positions}
            if symbol in holding_symbols:
                checked_buy.add(symbol)
                continue

            dedup_key = f"{symbol}:panic_buy:{today}"
            if state.get(dedup_key):
                checked_buy.add(symbol)
                continue

            try:
                raw30 = client.call("fetch_kline", {"symbol": symbol, "period": "30", "count": 100})
                bars30 = extract_rows(raw30)
            except Exception:
                checked_buy.add(symbol)
                continue

            if len(bars30) < 50:
                checked_buy.add(symbol)
                continue

            try:
                quote = parse_quote(client.call("query_data", {"symbol": symbol}, port=9001))
                live_price = float(quote.get("price", quote.get("最新价", 0)) or 0)
            except Exception:
                checked_buy.add(symbol)
                continue

            if live_price <= 0:
                checked_buy.add(symbol)
                continue

            result = evaluate_panic_buy(client, plan, bars30, live_price)
            state[dedup_key] = {
                "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "price": live_price,
                "passed": bool(result),
            }

            if result:
                candidate_id = f"close-{symbol}-panic_buy-{today}"
                record = {
                    "record_type": "candidate",
                    "date": today,
                    "candidate_id": candidate_id,
                    "symbol": symbol,
                    "name": result["name"],
                    "direction": "buy",
                    "price": result["price"],
                    "quantity": 100,
                    "confidence": result["confidence"],
                    "awaiting_llm_review": True,
                    "chan_buy_point": result["buy_point"],
                    "chan_confirmed": True,
                    "trend_type": result["trend"],
                    "divergence_type": result.get("divergence_type"),
                    "near_support": result.get("near_support"),
                    "bottoming": result.get("bottoming"),
                    "thesis": result["thesis"],
                    "entry_rule": "次日开盘30分钟评估反弹强度, ±3%止盈止损",
                    "catalyst_type": "panic_bottom_fishing",
                    "source": "close_session_panic",
                }
                append_candidate(dm, record)
                panic_buys.append(result)

            checked_buy.add(symbol)
            if len(panic_buys) >= 2:
                break

        for pb in panic_buys:
            zs_str = f"支撑{pb['pivot_low']:.2f}" if pb.get("pivot_low") else ""
            all_signals.append(
                f"?抄底 {pb['name']}({pb['symbol']}) 现价{format_price(pb['price'])} {zs_str}\n"
                f"　{pb['buy_point'] or '底背驰'}·{'企稳' if pb['bottoming'] else ''}·等待LLM二审")

    save_state(state)

    # 执行闸门
    if all_signals:
        if any("卖出" in s for s in all_signals):
            run_trade_gate()

    if not all_signals:
        if is_panic:
            print(f"{header}\n{mode_label}\n?无卖出信号·无合适抄底标的")
        elif positions:
            pos_summary = " · ".join(
                f"{p.get('name', p.get('symbol','?'))}"
                for p in positions[:4])
            print(f"{header}\n{mode_label}\n?持有 {pos_summary}\n　无卖出信号")
        else:
            print(f"{header}\n{mode_label}\n?空仓")
        return 0

    print(header)
    print(mode_label)
    for note in all_signals[:4]:
        print(note)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
