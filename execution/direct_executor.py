#!/usr/bin/env python3
"""
即时响应执行器 v2 (Instant Trade Executor)
R25: 持续运行cron守护 + 分批风控 + 防重复 + 超时保护
R36: 条件求值器前置门禁 (竞价区间/超幅拒买/封板时效/依赖锚定)
R37: 挂单超时撤单 + 成交确认轮询

cron入口: * * * * 1-5 cd /home/wade/workspace/ai/Astock && python3 -m execution.direct_executor
每次最多处理2笔候选(分批防阻塞),已执行的跳过
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

from data import get_data_manager
from mcp_client import get_mcp_client
from condition_evaluator import evaluate_all as cond_eval
from execution.pipeline import (
    is_catalyst_enabled,
    load_strategy_params,
    normalize_intent,
    risk_check_and_execute,
)


def in_trading_session(now_cst: dt.datetime) -> bool:
    """盘中时段检查 (09:30-11:30, 13:00-14:50)"""
    t = now_cst.hour * 60 + now_cst.minute
    morning = 570 <= t <= 690   # 09:30-11:30
    afternoon = 780 <= t <= 890  # 13:00-14:50
    return morning or afternoon


def load_processed_ids(date: str) -> set[str]:
    """从JSONL读取已执行event"""
    dm = get_data_manager()
    processed: set[str] = set()
    records = dm.read_jsonl(date)
    for d in records:
        if d.get("record_type") == "candidate_event" and d.get("event") in (
            "executed", "risk_blocked", "t1_conflict", "agy_iron_rule_blocked",
            "condition_rejected", "position_limit_rejected", "catalyst_cooldown",
        ):
            candidate_id = d.get("candidate_id")
            if candidate_id:
                processed.add(candidate_id)
    return processed


def get_total_assets() -> float:
    try:
        client = get_mcp_client()
        b_json = client.get_balance()
        return float(b_json.get("total_assets", b_json.get("total_asset", 0)) or 0)
    except Exception as e:
        print(f"  ? 余额获取失败: {e}", flush=True)
        return 0


def get_account_snapshot() -> tuple[float, float, float]:
    """获取账户资产快照 (total_assets, available_cash, current_market_val)."""
    client = get_mcp_client()
    total_assets = 0.0
    available_cash = 0.0
    current_market_val = 0.0

    try:
        b_json = client.get_balance()
        total_assets = float(b_json.get("total_assets", b_json.get("total_asset", 0)) or 0)
        available_cash = float(
            b_json.get("available_cash", b_json.get("available_balance", b_json.get("cash", 0))) or 0
        )
        if total_assets <= 0 and available_cash > 0:
            total_assets = available_cash
    except Exception as e:
        print(f"  ? 余额获取失败: {e}", flush=True)

    try:
        positions = client.get_positions()
        for p in positions:
            if isinstance(p, dict):
                mv = float(
                    p.get("market_value", 0)
                    or (
                        float(p.get("current_price", p.get("cost_price", 0)) or 0)
                        * float(p.get("quantity", 0) or 0)
                    )
                )
                current_market_val += mv
    except Exception as e:
        print(f"  ? 持仓获取失败: {e}", flush=True)

    # 包含在途买单 (BUG-04 / P0): 将未成交买单计入已占用仓位，防止并发击穿仓位天花板
    try:
        orders = client.get_orders()
        for o in orders:
            if isinstance(o, dict):
                d = str(o.get("direction", "")).upper()
                st = str(o.get("status", "")).upper()
                if d == "BUY" and st in ("PENDING", "SUBMITTED", "PARTIALLY_FILLED", "PARTIAL_FILLED"):
                    qty = float(o.get("quantity", 0) or 0)
                    filled = float(o.get("filled_quantity", o.get("filled_qty", 0)) or 0)
                    rem_qty = max(0.0, qty - filled)
                    p_price = float(o.get("price", 0) or 0)
                    current_market_val += rem_qty * p_price
    except Exception:
        pass

    return total_assets, available_cash, current_market_val


def load_max_regime_ratio() -> float:
    try:
        from config import STATE_DIR
        import json as _json
        _r_path = STATE_DIR / "market_regime.json"
        if _r_path.exists():
            _r = _json.loads(_r_path.read_text(encoding="utf-8"))
            return float(_r.get("max_regime_ratio", 0.80) or 0.80)
        return 0.80
    except Exception:
        return 0.80


def parse_mcp_quote(q_data: dict) -> dict:
    """解包 Intel MCP query_data 表格格式 -> 平铺 dict"""
    if isinstance(q_data, dict) and "tables" in q_data:
        try:
            tbl = q_data["tables"][0]
            return dict(zip(tbl["columns"], tbl["rows"][0]))
        except (IndexError, KeyError):
            return {}
    return q_data if isinstance(q_data, dict) else {}


def check_call_auction_unmatched_cancel(
    orders: list[dict[str, Any]] | None = None,
    now_cst: dt.datetime | None = None,
) -> list[dict[str, Any]]:
    """09:29:55 竞价未撮合开盘防被动接盘撤单机制 (P0-02 & P1-02)."""
    client = get_mcp_client()
    cst = dt.timezone(dt.timedelta(hours=8))
    current_time = now_cst or dt.datetime.now(cst)

    cancelled_auction_orders: list[dict[str, Any]] = []
    if orders is None:
        try:
            orders = client.get_orders()
        except Exception:
            orders = []

    active_statuses = ("PENDING", "SUBMITTED", "PARTIALLY_FILLED", "PARTIAL_FILLED")
    active_orders = [
        o for o in orders
        if isinstance(o, dict) and str(o.get("status", "")).upper() in active_statuses
    ]

    for o in active_orders:
        direction = str(o.get("direction", o.get("side", ""))).upper()
        if direction != "BUY":
            continue

        oid = o.get("order_id") or o.get("id")
        sym = str(o.get("symbol", ""))
        price = float(o.get("price", 0) or 0)
        ts_str = str(o.get("timestamp") or o.get("created_at") or o.get("time") or "")

        is_call_auction_order = False
        if str(o.get("order_type", "")).upper() in ("CALL_AUCTION", "AUCTION", "0925"):
            is_call_auction_order = True
        elif ts_str:
            try:
                ot = dt.datetime.fromisoformat(ts_str)
                if (ot.hour == 9 and ot.minute <= 28) or (ot.hour == 1 and ot.minute <= 28):
                    is_call_auction_order = True
            except Exception:
                pass

        if not is_call_auction_order or not oid:
            continue

        # 查询标的现价/开盘价
        try:
            q_data = client.call("query_data", {"symbol": sym}, port=9001)
        except Exception:
            q_data = {}
        q_flat = parse_mcp_quote(q_data) if isinstance(q_data, dict) else {}
        cur_price = float(q_flat.get("price", 0) or q_flat.get("open", 0) or 0)
        open_price = float(q_flat.get("open", 0) or 0)
        check_p = cur_price if cur_price > 0 else open_price
        chg = float(q_flat.get("change_pct", q_flat.get("price_pct", 0.0)) or 0.0)

        weak_open = False
        weak_reason = ""
        if check_p > 0 and price > 0 and check_p < price:
            weak_open = True
            weak_reason = f"开盘价/现价 {check_p:.2f} 弱于竞价买入挂单价 {price:.2f}"
        elif chg < 0:
            weak_open = True
            weak_reason = f"开盘低开水下 ({chg:.2f}%) 预期转弱"

        if weak_open:
            try:
                c_resp = client.call("cancel_order", {"order_id": oid})
            except Exception as e:
                c_resp = {"error": str(e)}
            log_msg = f"? [09:29:55 竞价未撮合强平撤单] #{oid} ({sym}): {weak_reason} -> 结果: {c_resp}"
            print(log_msg, flush=True)
            cancelled_auction_orders.append({
                "order_id": oid,
                "symbol": sym,
                "reason": weak_reason,
                "response": c_resp,
                "timestamp": current_time.isoformat(),
            })

    return cancelled_auction_orders


def _check_direction_conflict(
    dm: Any,
    date: str,
    symbol: str,
    direction: str,
) -> str | None:
    """检查T+1方向冲突 (内联实现, 替代 utils_candidate.check_direction_conflict)."""
    if not symbol or not direction:
        return None
    direction = direction.lower().strip()
    records = dm.read_jsonl(date)

    # 构建 symbol -> last_direction 映射
    events: dict[str, str] = {}
    for r in records:
        if r.get("record_type") != "candidate_event":
            continue
        ev = r.get("event", "")
        sym = r.get("symbol", "")
        dr = str(r.get("direction", "")).lower().strip()
        if not sym:
            continue
        if ev in ("executed", "submitted", "submitted_unverified"):
            events[sym] = dr

    last_dir = events.get(symbol)
    if not last_dir:
        return None
    if last_dir == direction:
        return direction  # 同方向重复阻断

    # 反方向: 查持仓决定
    client = get_mcp_client()
    if direction == "sell":
        try:
            pos_list = client.get_positions()
            for p in pos_list:
                if p.get("symbol", "") == symbol:
                    av_raw = p.get("available_quantity")
                    if av_raw is None:
                        av_raw = p.get("available_shares")
                    av = int(float(av_raw if av_raw is not None else 0))
                    if av > 0:
                        return None  # 有可用持仓允许卖出
                    break
        except Exception:
            pass
        return direction  # 无可用持仓阻断卖出

    # direction == "buy" 且 last_dir == "sell"
    try:
        pos_list = client.get_positions()
        has_pos = any(
            p.get("symbol", "") == symbol
            and (
                int(
                    float(
                        p.get("quantity")
                        or p.get("available_quantity")
                        or p.get("available_shares")
                        or 0
                    )
                )
                > 0
            )
            for p in pos_list
        )
    except Exception:
        has_pos = True
    if not has_pos:
        return None  # 已卖完允许反手买入
    return direction  # 还有持仓T+1阻断买入


def reconcile_pending_orders() -> None:
    """挂单超时撤单 + 成交确认轮询 (R37 v2)."""
    client = get_mcp_client()
    dm = get_data_manager()
    cst = dt.timezone(dt.timedelta(hours=8))
    now_cst = dt.datetime.now(cst)
    now_utc = dt.datetime.now(dt.timezone.utc)
    today = now_cst.strftime("%Y-%m-%d")

    try:
        orders = client.get_orders()
        ACTIVE_STATUSES = ("PENDING", "SUBMITTED", "PARTIALLY_FILLED", "PARTIAL_FILLED")
        pending_orders = [
            o for o in orders
            if isinstance(o, dict) and o.get("status", "").upper() in ACTIVE_STATUSES
        ]

        # 09:29:55 竞价未撮合开盘防被动接盘撤单触发检查
        if now_cst.hour == 9 and now_cst.minute == 29 and 50 <= now_cst.second <= 59:
            check_call_auction_unmatched_cancel(orders=orders, now_cst=now_cst)

        for o in pending_orders:
            oid = o.get("order_id", "")
            sym = o.get("symbol", "")
            price = float(o.get("price", 0) or 0)
            ts_str = o.get("timestamp") or o.get("created_at") or o.get("time") or ""
            print(f"  ? 活动订单: {sym} #{oid} 状态={o.get('status')} 价格={price} 字段ts_str={ts_str[:25]}", flush=True)

            # 从Intel MCP(9001)查现价
            try:
                q_data = client.call("query_data", {"symbol": sym}, port=9001)
            except Exception:
                q_data = {}
            q_flat = parse_mcp_quote(q_data)
            cur_price = float(q_flat.get("price", 0) or q_flat.get("open", 0) or 0)

            should_cancel = False
            cancel_reason = ""
            deviation = 0.0

            if cur_price > 0 and price > 0:
                deviation = abs(cur_price - price) / price * 100.0
                if deviation > 1.5:
                    should_cancel = True
                    cancel_reason = f"价格偏离 {deviation:.1f}% > 1.5%"
                    print(f"    ? {cancel_reason}", flush=True)

            if not should_cancel and ts_str:
                try:
                    ot = dt.datetime.fromisoformat(ts_str)
                    if ot.tzinfo is None:
                        ot = ot.replace(tzinfo=dt.timezone.utc)
                    if (now_utc - ot).total_seconds() > 300:
                        should_cancel = True
                        cancel_reason = "挂单超过5分钟未成交"
                        print(f"    ? {cancel_reason}", flush=True)
                except Exception:
                    pass

            if should_cancel and oid:
                try:
                    c_resp = client.call("cancel_order", {"order_id": oid})
                    cancel_ok = "error" not in c_resp
                except Exception:
                    c_resp = {"error": "cancel failed"}
                    cancel_ok = False
                print(f"    {'?' if cancel_ok else '?'} 撤单 #{oid} {sym}", flush=True)
                if cancel_ok:
                    dm.append_jsonl({
                        "record_type": "candidate_event",
                        "event": "order_cancelled_timeout",
                        "candidate_id": f"cancel-{sym}-{oid}",
                        "symbol": sym,
                        "direction": "",
                        "date": today,
                        "timestamp": now_cst.isoformat(),
                        "reason": cancel_reason or "自动撤单",
                    }, date=today)

        # 2. 查询今日成交回报
        try:
            trades = client.get_today_trades()
            if trades:
                trade_summary = [
                    (t.get("symbol", ""), t.get("price", 0), t.get("quantity", 0))
                    for t in trades[:5]
                ]
                print(f"  ? 今日 {len(trades)} 笔成交: {trade_summary}", flush=True)
                for t in trades:
                    t_time = t.get("timestamp") or now_cst.isoformat()
                    dm.append_jsonl({
                        "record_type": "candidate_event",
                        "event": "trade_execution",
                        "candidate_id": f"trade-{t.get('symbol','')}-{t.get('direction','')}-{t.get('price',0)}-{t_time}",
                        "symbol": t.get("symbol", ""),
                        "direction": t.get("direction", ""),
                        "price": t.get("price", 0),
                        "quantity": t.get("quantity", 0),
                        "timestamp": t_time,
                        "date": today,
                        "trade_id": t.get("trade_id", ""),
                    }, date=today)
                print(f"  ? {len(trades)} 笔成交已写入 candidates_{today}.jsonl", flush=True)
        except Exception:
            pass

    except Exception as e:
        print(f"  ? 成交确认轮询异常: {e}", flush=True)


def load_sentiment_multiplier() -> float:
    try:
        sp = load_strategy_params()
        return float(sp.get("sentiment", {}).get("multiplier", 1.0))
    except Exception:
        return 1.0


def main() -> int:
    cst = dt.timezone(dt.timedelta(hours=8))
    now_cst = dt.datetime.now(cst)

    if not in_trading_session(now_cst):
        return 0

    today = now_cst.strftime("%Y-%m-%d")
    dm = get_data_manager()
    client = get_mcp_client()
    cand_path = dm.ledger_dir / f"candidates_{today}.jsonl"

    if not cand_path.exists():
        return 0

    print(f"? 即时执行 [{now_cst.strftime('%H:%M:%S')}]", flush=True)

    # R37: 挂单超时撤单 + 成交确认轮询
    reconcile_pending_orders()

    # 1. 已处理ID
    processed_ids = load_processed_ids(today)

    # 2. 加载候选
    candidates = dm.load_candidates(date=today)
    if not candidates:
        return 0

    # 3. 过滤: AGY approved + 未处理 + 方向+持仓感知
    ready: list[dict[str, Any]] = []
    for c in candidates:
        cid = c.get("candidate_id", "")
        if cid in processed_ids:
            continue
        if c.get("agy_approved") is False:
            continue
        if c.get("llm_approved") is False:
            continue
        if not (c.get("llm_approved") is True or c.get("agy_approved") is True or c.get("llm_status") == "approved"):
            continue
        cat = c.get("catalyst_type", "")
        if cat and not is_catalyst_enabled(cat, direction=c.get("direction")):
            print(f"  ? {cat} 策略暂停中,跳过 {c.get('symbol','')}", flush=True)
            dm.append_jsonl({
                "record_type": "candidate_event",
                "event": "catalyst_cooldown",
                "candidate_id": cid, "symbol": c.get("symbol", ""),
                "direction": c.get("direction", ""),
                "date": today, "timestamp": now_cst.isoformat(),
                "reason": f"{cat} 策略cooldown中",
            }, date=today)
            continue
        sym = c.get("symbol", "")
        direction = c.get("direction", "")
        if not direction or not sym:
            continue
        # T1方向冲突
        try:
            conflict = _check_direction_conflict(dm, today, sym, direction)
            if conflict:
                print(f"  ? T1冲突 {sym} {direction}: {conflict}", flush=True)
                dm.append_jsonl({
                    "record_type": "candidate_event",
                    "event": "t1_conflict",
                    "candidate_id": cid, "symbol": sym,
                    "direction": direction, "date": today,
                    "timestamp": now_cst.isoformat(),
                    "reason": str(conflict),
                }, date=today)
                continue
        except Exception as e:
            print(f"  ? T1检查失败 {sym}: {e}", flush=True)

        ready.append(c)

    if not ready:
        print(f"  无待处理 (总:{len(candidates)} 已处理:{len(processed_ids)})", flush=True)
        return 0

    # sell_only_mode 硬卡口
    _sell_only = False
    try:
        _sp = load_strategy_params()
        _sell_only = (
            _sp.get("sell_only_mode") is True
            or _sp.get("global_guards", {}).get("sell_only_mode") is True
        )
        if not _sell_only:
            _rl_path = dm.state_dir / "redline_state.json"
            if _rl_path.exists():
                _rl = json.loads(_rl_path.read_text(encoding="utf-8"))
                _sell_only = _rl.get("tripped") is True
    except Exception:
        pass

    if _sell_only:
        buy_count = sum(1 for c in ready if c.get("direction", "") == "buy")
        if buy_count > 0:
            print(f"  ? sell_only_mode: 拦截 {buy_count} 笔买入候选，仅允许卖出", flush=True)
        ready = [c for c in ready if c.get("direction", "") == "sell"]
        if not ready:
            print(f"  ? sell_only_mode: 无卖出候选，退出", flush=True)
            return 0

    # R37 cooldown/ice 精细化防守
    if not _sell_only:
        try:
            _sp2 = load_strategy_params()
            _phase = _sp2.get("sentiment", {}).get("phase", "")
            _mult = float(_sp2.get("sentiment", {}).get("multiplier", 1.0))
            if _phase in ("cooldown", "ice") and _mult <= 0.3:
                leader_cats = {"dragon_screener", "limit_up_ladder", "limitup_leader", "1to2_weak_to_strong"}
                kept: list[dict[str, Any]] = []
                for c in ready:
                    if c.get("direction") == "sell":
                        kept.append(c)
                    else:
                        cat = c.get("catalyst_type", "")
                        conf = float(c.get("confidence", 0) or 0)
                        is_leader = cat in leader_cats or c.get("is_dragon") or c.get("is_sector_leader")
                        if is_leader and conf >= 0.70:
                            print(f"  ? {_phase}阶段放行破局龙头: {c.get('name')}({c.get('symbol')}) cat={cat} conf={conf}", flush=True)
                            kept.append(c)
                        else:
                            print(f"  ? {_phase}阶段拦截普通跟风买入: {c.get('name')}({c.get('symbol')}) cat={cat} conf={conf}", flush=True)
                ready = kept
                if not ready:
                    print(f"  ? {_phase}阶段: 无符合条件的卖出或破局龙头候选，退出", flush=True)
                    return 0
        except Exception as e:
            print(f"  ? R37 过滤异常: {e}", flush=True)

        # 板块级定向隔离检查
        _blocked_secs: list[str] = []
        try:
            _sp = load_strategy_params()
            _blocked_secs = _sp.get("blocked_sectors", []) if isinstance(_sp, dict) else []
        except Exception:
            pass
        if _blocked_secs:
            kept = []
            for c in ready:
                if c.get("direction", "") == "buy" and c.get("sector") in _blocked_secs:
                    print(f"  ? 板块红线拦截: 标的 {c.get('name')}({c.get('symbol')}) 所属板块【{c.get('sector')}】已避险隔离", flush=True)
                    continue
                kept.append(c)
            ready = kept
            if not ready:
                print(f"  ? 所有买入候选均属于避险隔离板块，暂无可用候选，退出", flush=True)
                return 0

    BATCH_SIZE = 2
    batch = ready[:BATCH_SIZE]
    remaining = len(ready) - len(batch)

    print(f"  待处理:{len(ready)} 本次:{len(batch)} 剩余:{remaining}", flush=True)

    total_assets, available_cash, current_market_val = get_account_snapshot()
    sent_multiplier = load_sentiment_multiplier()
    max_regime_ratio = load_max_regime_ratio()

    # 四大指数实时行情
    index_quotes: dict[str, Any] = {}
    try:
        idx_syms = ["000001.SH", "399006.SZ", "399001.SZ", "000688.SH"]
        idx_res = client.query_quotes(idx_syms)
        index_quotes = idx_res.get("quotes", {}) if isinstance(idx_res, dict) else {}
    except Exception as ie:
        print(f"  ? 指数行情获取异常: {ie}", flush=True)

    for candidate in batch:
        sym = candidate.get("symbol", "")
        cid = candidate.get("candidate_id", "")
        direction = candidate.get("direction", "")
        nm = candidate.get("name") or sym.split(".")[0]

        print(f"  ? {sym} ({nm}) dir={direction}", flush=True)

        # 行情与盘口获取
        quote: dict[str, Any] = {}
        try:
            anchor_sym = (
                candidate.get("condition_triggers", {}).get("dependency_anchor", {}).get("symbol")
                if isinstance(candidate.get("condition_triggers"), dict)
                and candidate.get("condition_triggers", {}).get("dependency_anchor")
                else None
            )
            query_symbols = [sym] + ([anchor_sym] if anchor_sym else [])
            name_quotes_data = client.query_quotes(query_symbols)
            name_quotes = name_quotes_data.get("quotes", {}) if isinstance(name_quotes_data, dict) else {}
            quote = name_quotes.get(sym, {})
            if anchor_sym and anchor_sym in name_quotes:
                quote["anchors"] = {anchor_sym: name_quotes[anchor_sym]}
            if sym in name_quotes and name_quotes[sym].get("name"):
                candidate["name"] = name_quotes[sym]["name"]
                nm = candidate["name"]
        except Exception:
            pass

        # ===== AGY-IRON-RULE 铁律注入 BEGIN =====
        try:
            candidate["quote"] = quote
            candidate["index_quotes"] = index_quotes
            from market_regime_check import iron_rule_gate  # type: ignore
            gate_ok, gate_reason = iron_rule_gate(candidate, now_cst)
            if not gate_ok:
                print(f"    ? AGY铁律阻断: {gate_reason}", flush=True)
                dm.append_jsonl({
                    "record_type": "candidate_event",
                    "event": "agy_iron_rule_blocked",
                    "candidate_id": cid,
                    "symbol": sym,
                    "direction": direction,
                    "date": today,
                    "timestamp": now_cst.isoformat(),
                    "reason": gate_reason,
                }, date=today)
                continue
        except Exception as e:
            print(f"    ? AGY铁律检查异常: {e}", flush=True)
        # ===== AGY-IRON-RULE 铁律注入 END =====

        # 条件求值器核验
        if direction == "buy":
            try:
                now_time_str = now_cst.strftime("%H:%M")
                sentinel_quotes = quote.get("anchors", {}) if isinstance(quote, dict) else {}
                ce = cond_eval(candidate, quote, now_time=now_time_str,
                               sentinel_quotes=sentinel_quotes,
                               index_quotes=index_quotes)
                if not ce["pass"]:
                    fail_reason = ce.get("first_failure", "条件不满足")
                    print(f"    ? 条件门禁阻断: {fail_reason}", flush=True)
                    dm.append_jsonl({
                        "record_type": "candidate_event",
                        "event": "condition_rejected",
                        "condition_type": ce.get("first_failure", "unknown"),
                        "candidate_id": cid, "symbol": sym,
                        "date": today, "timestamp": now_cst.isoformat(),
                        "reason": fail_reason,
                    }, date=today)
                    continue
            except Exception as ce:
                print(f"    ? 条件求值异常: {ce}", flush=True)

        base_pct = float(candidate.get("max_position_pct") or candidate.get("risk_adjusted_pct") or 0.25)

        if direction == "sell":
            adj_pct = base_pct
            real_avail_qty = 0
            try:
                positions = client.get_positions()
                for p in positions:
                    if isinstance(p, dict) and str(p.get("symbol")) == sym:
                        av_raw = p.get("available_quantity") if p.get("available_quantity") is not None else p.get("available_shares")
                        if av_raw is not None:
                            real_avail_qty = int(float(av_raw))
                        else:
                            real_avail_qty = int(float(p.get("quantity", 0) or 0))
                        break
            except Exception as pe:
                print(f"    ? 获取券商持仓异常: {pe}", flush=True)

            cand_qty = int(candidate.get("quantity", 0) or 0)
            if real_avail_qty < 100:
                rej_msg = f"券商可用股数不足100股({real_avail_qty}股)，可能在途挂单临时冻结，跳过本轮执行待解冻"
                print(f"    ? 临时可用股数不足: {rej_msg}", flush=True)
                dm.append_jsonl({
                    "record_type": "candidate_event",
                    "event": "temporary_insufficient_shares",
                    "candidate_id": cid,
                    "symbol": sym,
                    "direction": "sell",
                    "date": today,
                    "timestamp": now_cst.isoformat(),
                    "reason": rej_msg,
                }, date=today)
                continue

            clamped_qty = min(cand_qty, real_avail_qty) if cand_qty > 0 else real_avail_qty
            candidate["quantity"] = clamped_qty
        else:
            adj_pct = base_pct * sent_multiplier

            cand_p = float(candidate.get("price") or quote.get("price") or 0.0)
            if cand_p > 0 and total_assets > 0:
                new_alloc = total_assets * adj_pct
                max_allowed_val = max(0.0, total_assets * max_regime_ratio - current_market_val)
                if (current_market_val + new_alloc) > (total_assets * max_regime_ratio):
                    new_alloc = max_allowed_val
                target_val = min(new_alloc, available_cash * 0.95) if available_cash > 0 else new_alloc
                target_qty = int(target_val / cand_p / 100) * 100
                if target_qty < 100:
                    cancel_msg = f"总持仓天花板或可用现金兜底不足(配额{target_val:.2f}元不足100股)，取消下单"
                    print(f"    ? 仓位配额阻断: {cancel_msg}", flush=True)
                    dm.append_jsonl({
                        "record_type": "candidate_event",
                        "event": "position_limit_rejected",
                        "candidate_id": cid, "symbol": sym,
                        "date": today, "timestamp": now_cst.isoformat(),
                        "reason": cancel_msg,
                    }, date=today)
                    continue
                adj_pct = target_val / total_assets

        # normalize
        try:
            intent = normalize_intent(
                candidate, total_assets=total_assets,
                adjusted_pct=adj_pct,
                available_cash=available_cash,
                current_market_val=current_market_val,
                max_regime_ratio=max_regime_ratio,
            )
        except Exception as e:
            print(f"    ? normalize失败: {e}", flush=True)
            dm.append_jsonl({
                "record_type": "candidate_event",
                "event": "normalize_failed",
                "candidate_id": cid, "symbol": sym,
                "date": today, "timestamp": now_cst.isoformat(),
                "reason": str(e),
            }, date=today)
            continue

        # 风控+下单
        try:
            result = risk_check_and_execute(
                [intent], dry_run=os.environ.get("ASTOCK_DRY_RUN") == "1")
        except Exception as e:
            result = {"executed": [], "blocked": [str(e)], "skipped": []}

        executed_count = len(result.get("executed", []))
        skipped_count = len(result.get("skipped", []))
        if executed_count > 0:
            status = "executed"
            reason = "direct_executor"
            print(f"    ? 成交 {sym} {direction}", flush=True)
            if direction == "buy":
                cand_p = float(intent.get("price", candidate.get("price", 0)) or 0)
                exec_qty = int(intent.get("quantity", 0))
                current_market_val += exec_qty * cand_p
                available_cash -= exec_qty * cand_p
        elif skipped_count > 0:
            first_skip = result["skipped"][0]
            reason = str(first_skip.get("reason", first_skip.get("detail", "订单提交被跳过(注册/下单失败)")))
            if "temporary_insufficient_shares" in reason:
                status = "temporary_insufficient_shares"
            else:
                status = "risk_blocked"
            print(f"    ? 订单提交跳过 {sym}: {reason[:80]}", flush=True)
        else:
            reason = str(result.get("blocked", result.get("error", "")))
            rejected_list = result.get("rejected", [])
            has_temp_insufficient = any(
                "temporary_insufficient_shares" in str(r.get("rejection_reason", ""))
                for r in rejected_list
            )
            if has_temp_insufficient or "temporary_insufficient_shares" in reason:
                status = "temporary_insufficient_shares"
            else:
                status = "risk_blocked"
            print(f"    ? 风控阻断 {sym}: {reason[:80]}", flush=True)

        dm.append_jsonl({
            "record_type": "candidate_event",
            "event": status,
            "candidate_id": cid, "symbol": sym,
            "direction": direction,
            "date": today, "timestamp": now_cst.isoformat(),
            "reason": reason,
        }, date=today)

        # 影子追踪
        try:
            from execution.pipeline import is_shadow_ready, record_shadow_candidate
            if is_shadow_ready(candidate):
                record_shadow_candidate(candidate, date=today)
        except Exception:
            pass

    print(f"  批次完成", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
