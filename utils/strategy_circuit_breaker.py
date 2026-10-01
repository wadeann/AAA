#!/usr/bin/env python3
"""策略闭环熔断器 (Strategy Circuit Breaker).

移植至 Astock: ~/.hermes 路径替换为 STATE_DIR.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Optional

from config import STATE_DIR

BREAKER_DIR = STATE_DIR / "strategy_circuit_breaker"
HISTORY_FILE = BREAKER_DIR / "trade_history.jsonl"
STATE_FILE = BREAKER_DIR / "breaker_state.json"
CST = dt.timezone(dt.timedelta(hours=8))


def _ensure_dirs() -> None:
    BREAKER_DIR.mkdir(parents=True, exist_ok=True)


def _parse_iso_cst(iso_str: str) -> dt.datetime:
    try:
        clean_str = iso_str.replace("Z", "+00:00")
        t = dt.datetime.fromisoformat(clean_str)
        if t.tzinfo is None:
            t = t.replace(tzinfo=CST)
        else:
            t = t.astimezone(CST)
        return t
    except Exception:
        return dt.datetime.now(CST)


def _load_history() -> list[dict[str, Any]]:
    _ensure_dirs()
    if not HISTORY_FILE.exists():
        return []
    records = []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def _load_state() -> dict[str, Any]:
    _ensure_dirs()
    if not STATE_FILE.exists():
        return {"updated_at": dt.datetime.now(CST).isoformat(), "strategies": {}}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"updated_at": dt.datetime.now(CST).isoformat(), "strategies": {}}


def _save_state(state: dict[str, Any]) -> None:
    _ensure_dirs()
    state["updated_at"] = dt.datetime.now(CST).isoformat()
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def recalculate_breaker_state(now_cst: Optional[dt.datetime] = None) -> dict[str, Any]:
    if now_cst is None:
        now_cst = dt.datetime.now(CST)
    history = _load_history()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for r in history:
        if str(r.get("direction", "buy")).strip().lower() != "buy":
            continue
        cat = r.get("catalyst_type", "").strip() or "unknown"
        grouped.setdefault(cat, []).append(r)

    strategies_state: dict[str, Any] = {}
    for cat, trades in grouped.items():
        trades.sort(key=lambda x: _parse_iso_cst(x.get("timestamp", "")))
        is_blocked = False
        blocked_until: Optional[dt.datetime] = None
        block_reasons = []

        for t in reversed(trades):
            t_time = _parse_iso_cst(t.get("timestamp", ""))
            pnl = float(t.get("pnl_pct", 0.0))
            if pnl <= -5.0:
                until_14d = t_time + dt.timedelta(days=14)
                if until_14d > now_cst:
                    is_blocked = True
                    if blocked_until is None or until_14d > blocked_until:
                        blocked_until = until_14d
                    block_reasons.append(
                        f"单笔严重亏损({pnl:+.2f}%)于{t.get('symbol')}，触发14天熔断(至{until_14d.strftime('%Y-%m-%d %H:%M')})")
                    break

        if len(trades) >= 2 and not is_blocked:
            last1 = trades[-1]
            last2 = trades[-2]
            pnl1 = float(last1.get("pnl_pct", 0.0))
            pnl2 = float(last2.get("pnl_pct", 0.0))
            if pnl1 < 0.0 and pnl2 < 0.0:
                t_time = _parse_iso_cst(last1.get("timestamp", ""))
                until_7d = t_time + dt.timedelta(days=7)
                if until_7d > now_cst:
                    is_blocked = True
                    if blocked_until is None or until_7d > blocked_until:
                        blocked_until = until_7d
                    block_reasons.append(
                        f"最近连续2笔亏损({last2.get('symbol')} {pnl2:+.2f}%, {last1.get('symbol')} {pnl1:+.2f}%)，触发7天熔断")

        recent_pnl = [round(float(x.get("pnl_pct", 0.0)), 2) for x in trades[-5:]]
        strategies_state[cat] = {
            "catalyst_type": cat, "is_blocked": is_blocked,
            "blocked_until": blocked_until.isoformat() if blocked_until else None,
            "reason": "；".join(block_reasons) if block_reasons else "无熔断限制",
            "total_trades": len(trades), "recent_5_pnl": recent_pnl,
            "last_trade_time": trades[-1].get("timestamp") if trades else None,
        }

    full_state = {"updated_at": now_cst.isoformat(), "strategies": strategies_state}
    _save_state(full_state)
    return full_state


def record_trade(catalyst_type: str, symbol: str, direction: str,
                 entry_price: float, exit_price: float, pnl_pct: float,
                 reason: str = "", timestamp: Optional[str] = None) -> None:
    _ensure_dirs()
    now_cst = dt.datetime.now(CST)
    ts = timestamp or now_cst.isoformat()
    norm_pnl = float(pnl_pct)
    if -0.5 < norm_pnl < 0.5 and norm_pnl != 0.0:
        norm_pnl = norm_pnl * 100.0
    record = {"timestamp": ts, "catalyst_type": str(catalyst_type).strip() or "unknown",
              "symbol": str(symbol).strip().upper(), "direction": str(direction).strip().lower(),
              "entry_price": round(float(entry_price), 3), "exit_price": round(float(exit_price), 3),
              "pnl_pct": round(norm_pnl, 2), "reason": str(reason).strip()}
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    recalculate_breaker_state(now_cst=now_cst)


def check_strategy(catalyst_type: str) -> tuple[bool, str]:
    """校验某个策略是否被熔断."""
    cat = str(catalyst_type).strip()
    if not cat:
        return False, "PASS: 策略为空，豁免熔断"
    state = _load_state()
    strat_info = state.get("strategies", {}).get(cat)
    now_cst = dt.datetime.now(CST)
    if not strat_info:
        recalc_state = recalculate_breaker_state(now_cst)
        strat_info = recalc_state.get("strategies", {}).get(cat)
    if not strat_info:
        return False, f"PASS: 策略【{cat}】无不良记录"
    is_blocked = strat_info.get("is_blocked", False)
    blocked_until_str = strat_info.get("blocked_until")
    if is_blocked and blocked_until_str:
        blocked_until = _parse_iso_cst(blocked_until_str)
        if now_cst < blocked_until:
            return True, f"策略【{cat}】熔断冻结中(至{blocked_until.strftime('%Y-%m-%d %H:%M')}): {strat_info.get('reason', '')}"
        else:
            strat_info["is_blocked"] = False
            strat_info["reason"] = "熔断期已届满解除"
            _save_state(state)
            return False, f"PASS: 策略【{cat}】熔断期满"
    return False, f"PASS: 策略【{cat}】正常运行"
