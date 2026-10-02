#!/usr/bin/env python3
"""Batch trade gate — 10:55/14:55 batch promotion from shadow candidates.

Replaces run_autonomous_trades.py. Uses MCPClient for all MCP communication
and DataManager for ledger persistence.

BUGFIX 2026-09-01 R1: Shadow candidates with high confidence (>=0.65) are now
promoted to trade-ready intents so AGY-approved picks actually reach execution.
Previously they were recorded to the ledger but never read by the trade gate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import Any

from data import get_data_manager
from mcp_client import get_mcp_client
from execution.pipeline import (
    is_catalyst_enabled,
    is_shadow_ready,
    is_trade_ready,
    load_shadow_candidates,
    load_strategy_params,
    normalize_intent,
    record_shadow_candidate,
    risk_check_and_execute,
)
from config import STATE_DIR


def is_llm_ready(candidate: dict[str, Any]) -> bool:
    """LLM readiness check: not awaiting review, not explicitly rejected."""
    if candidate.get("agy_approved") is False or candidate.get("llm_approved") is False:
        return False
    if candidate.get("awaiting_llm_review"):
        return False
    if candidate.get("llm_approved") is True or candidate.get("agy_approved") is True:
        return True
    if candidate.get("llm_status") == "approved":
        return True
    return False


def processed_execution_candidate_ids(records: list[dict[str, Any]]) -> set[str]:
    processed: set[str] = set()
    for row in records:
        event = row.get("event")
        cid = row.get("candidate_id")
        if not cid:
            continue
        if event in {"submitted", "submitted_unverified", "failed", "simulated", "shadow_promoted", "llm_rejected"}:
            processed.add(cid)
        elif event == "execution_skipped":
            reason = str(row.get("reason", ""))
            if "outside trading session" not in reason:
                processed.add(cid)
    return processed


def _check_direction_conflict(
    records: list[dict[str, Any]],
    symbol: str,
    direction: str,
) -> str | None:
    """检查T+1方向冲突 (内联实现)."""
    if not symbol or not direction:
        return None
    direction = direction.lower().strip()

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
        return direction

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
                        return None
                    break
        except Exception:
            pass
        return direction

    try:
        pos_list = client.get_positions()
        has_pos = any(
            p.get("symbol", "") == symbol
            and (
                int(float(p.get("quantity", p.get("available_quantity", p.get("available_shares", 0))) or 0)) > 0
            )
            for p in pos_list
        )
    except Exception:
        has_pos = True
    if not has_pos:
        return None
    return direction


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm-review", action="store_true",
                        help="Trigger LLM review for awaiting_llm_review candidates")
    args = parser.parse_args()

    dm = get_data_manager()
    client = get_mcp_client()
    today = dt.date.today().isoformat()

    if args.llm_review:
        candidates = dm.load_candidates(date=today)
        pending = [c for c in candidates if c.get("awaiting_llm_review")]
        print(f"LLM pending review: {len(pending)} candidates")
        for c in pending:
            print(f"  {c.get('name','')}({c.get('symbol')}) {c.get('direction')}@{c.get('price')}")
        return

    candidates = dm.load_candidates(date=today)
    strategy_params = load_strategy_params()
    records = dm.read_jsonl(date=today)
    processed = processed_execution_candidate_ids(records)

    unique: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        candidate_id = candidate.get("candidate_id")
        if candidate_id in processed:
            continue
        if not is_llm_ready(candidate):
            continue
        unique.setdefault(candidate_id, candidate)
    candidates = list(unique.values())

    # Shadow candidate promotion (BUGFIX R1/R7)
    shadows = load_shadow_candidates(date=today)
    shadow_promoted = 0
    for shadow in shadows:
        shadow_id = shadow.get("candidate_id")
        if shadow_id in processed:
            continue
        shadow_dir = shadow.get("direction", "")
        shadow_conf = float(shadow.get("confidence", 0) or 0)
        if shadow_dir == "buy":
            chan_ok = bool(
                shadow.get("chan_buy_point") in {"一买", "二买", "三买"}
                and shadow.get("chan_confirmed")
                and shadow.get("volume_confirmed")
            )
        elif shadow_dir == "sell":
            chan_ok = bool(shadow.get("chan_sell_point") and shadow.get("chan_confirmed"))
        else:
            chan_ok = False
        has_fields = bool(shadow.get("symbol")) and bool(shadow_dir) and float(shadow.get("price", 0) or 0) > 0
        if not (chan_ok and has_fields and shadow_conf >= 0.65):
            continue

        shadow_promoted += 1
        dm.append_jsonl({
            "record_type": "candidate_event",
            "event": "shadow_promoted",
            "candidate_id": shadow_id,
            "symbol": shadow.get("symbol"),
            "date": today,
        }, date=today)

        fake_candidate = dict(shadow)
        fake_candidate.pop("record_type", None)
        fake_candidate.pop("shadow_tracked_at", None)
        if not fake_candidate.get("thesis"):
            fake_candidate["thesis"] = (
                f"[shadow] {shadow.get('chan_buy_point') or shadow.get('chan_sell_point') or 'signal'}·shadow promotion"
            )
        if not fake_candidate.get("entry_rule"):
            fake_candidate["entry_rule"] = "shadow_promote"

        catalyst_type = fake_candidate.get("catalyst_type", "")
        is_breakout = any(c in catalyst_type for c in ("limit_up", "call_auction", "explode"))
        if not fake_candidate.get("llm_approved"):
            if is_breakout:
                fake_candidate["llm_approved"] = True
                fake_candidate["reasoning"] = "shadow_promote: auto-approved for breakout"
            else:
                fake_candidate["llm_approved"] = False
                fake_candidate["awaiting_llm_review"] = True
                fake_candidate["reasoning"] = "shadow_promote: pending LLM review"
        if not is_llm_ready(fake_candidate):
            continue
        if shadow_id not in unique and shadow_id not in processed:
            unique[shadow_id] = fake_candidate

    candidates = list(unique.values())

    intents: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    total_assets = 0.0
    available_cash = 0.0
    current_market_val = 0.0
    max_regime_ratio = 0.80

    try:
        from config import STATE_DIR
        import json as _json
        _r_path = STATE_DIR / "market_regime.json"
        if _r_path.exists():
            _r = _json.loads(_r_path.read_text(encoding="utf-8"))
            max_regime_ratio = float(_r.get("max_regime_ratio", 0.80) or 0.80)
    except Exception:
        max_regime_ratio = 0.80

    try:
        b_json = client.get_balance()
        total_assets = float(b_json.get("total_assets", b_json.get("total_asset", 0)) or 0)
        available_cash = float(
            b_json.get("available_cash", b_json.get("available_balance", b_json.get("cash", 0))) or 0
        )
    except Exception:
        pass

    try:
        positions = client.get_positions()
        for p in positions:
            if isinstance(p, dict):
                current_market_val += float(
                    p.get("market_value", 0)
                    or (float(p.get("current_price", p.get("cost_price", 0)) or 0) * float(p.get("quantity", 0) or 0))
                )
    except Exception:
        pass

    # Pending order market value adjustment (BUG-04 / P0)
    try:
        orders = client.get_orders()
        for o in orders:
            if isinstance(o, dict):
                d = str(o.get("direction", "")).upper()
                st = str(o.get("status", "")).upper()
                if d == "BUY" and st in ("PENDING", "SUBMITTED", "PARTIALLY_FILLED", "PARTIAL_FILLED"):
                    qty = float(o.get("quantity", 0) or 0)
                    filled = float(o.get("filled_quantity", o.get("filled_qty", 0)) or 0)
                    current_market_val += max(0.0, qty - filled) * float(o.get("price", 0) or 0)
    except Exception:
        pass

    sent_multiplier = strategy_params.get("sentiment", {}).get("multiplier", 1.0)

    for candidate in candidates:
        if candidate.get("record_type") != "shadow_candidate" and is_shadow_ready(candidate):
            record_shadow_candidate(candidate, date=today)

        is_buy = str(candidate.get("direction", "")).lower() == "buy"
        require_risk = is_buy  # buys MUST pass risk check; sells are defensive

        if is_trade_ready(candidate, require_risk=require_risk):
            sym = candidate.get("symbol", "")
            cid = candidate.get("candidate_id", "")
            dir_ = candidate.get("direction", "")
            conflict = _check_direction_conflict(records, sym, dir_) if sym and dir_ else None
            if conflict is not None:
                events.append({
                    "record_type": "candidate_event",
                    "event": "direction_conflict",
                    "candidate_id": cid,
                    "symbol": sym,
                    "direction": dir_,
                    "date": today,
                    "conflict_direction": conflict,
                    "reason": f"T+1 direction conflict: prior {conflict} order exists",
                })
                continue
            raw_pct = float(candidate.get("max_position_pct", candidate.get("risk_adjusted_pct", 0.2)))
            adj_pct = raw_pct * sent_multiplier
            intents.append(normalize_intent(
                candidate,
                total_assets=total_assets,
                adjusted_pct=adj_pct,
                available_cash=available_cash,
                current_market_val=current_market_val,
                max_regime_ratio=max_regime_ratio,
            ))
        else:
            events.append({
                "record_type": "candidate_event",
                "event": "filtered",
                "candidate_id": candidate.get("candidate_id"),
                "date": today,
                "reason": "research evidence gate incomplete",
            })

    # sell_only_mode check (BUG-05 / P0)
    sell_only = False
    try:
        from core.market_regime_check import intraday_dynamic_check  # type: ignore
        is_circuit_breaker, dyn_info = intraday_dynamic_check()
        if is_circuit_breaker:
            print(f"Dynamic circuit breaker tripped: {dyn_info.get('reason', '')}", flush=True)
            sell_only = True
    except Exception:
        pass
    try:
        sell_only = (
            strategy_params.get("sell_only_mode") is True
            or strategy_params.get("global_guards", {}).get("sell_only_mode") is True
        )
        if not sell_only:
            _rl_path = STATE_DIR / "redline_state.json"
            if _rl_path.exists():
                import json as _json
                _rl = _json.loads(_rl_path.read_text(encoding="utf-8"))
                sell_only = _rl.get("tripped") is True
    except Exception:
        pass

    valid_intents: list[dict[str, Any]] = []
    for intent in intents:
        if sell_only and intent.get("direction") == "buy":
            events.append({
                "record_type": "candidate_event",
                "event": "filtered",
                "candidate_id": intent.get("candidate_id"),
                "symbol": intent.get("symbol"),
                "date": today,
                "reason": "global guard: sell_only_mode is active",
            })
            continue
        cat_type = intent.get("catalyst_type")
        if intent.get("direction") == "buy" and not is_catalyst_enabled(cat_type, strategy_params):
            events.append({
                "record_type": "candidate_event",
                "event": "filtered",
                "candidate_id": intent.get("candidate_id"),
                "symbol": intent.get("symbol"),
                "date": today,
                "reason": f"catalyst_type {cat_type} is disabled or in cooldown",
            })
            continue
        valid_intents.append(intent)
    intents = valid_intents

    dry_run = os.environ.get("ASTOCK_MCP_DRY_RUN") == "1"
    result = risk_check_and_execute(intents, dry_run=dry_run)

    for item in result.get("rejected", []):
        events.append({
            "record_type": "candidate_event",
            "event": "risk_rejected",
            "candidate_id": item.get("candidate_id"),
            "symbol": item.get("symbol"),
            "date": today,
            "reason": item.get("reason", item.get("rejection_reason", "risk rejected")),
        })
    for item in result.get("executed", []):
        events.append({
            "record_type": "candidate_event",
            "event": item.get("execution_status", "submitted"),
            "candidate_id": item.get("candidate_id"),
            "symbol": item.get("symbol"),
            "date": today,
            "intent_id": item.get("intent_id"),
            "order": item.get("order"),
        })
    for item in result.get("skipped", []):
        intent = item.get("intent", {})
        events.append({
            "record_type": "candidate_event",
            "event": "execution_skipped",
            "candidate_id": intent.get("candidate_id"),
            "symbol": intent.get("symbol"),
            "date": today,
            "reason": item.get("reason"),
        })

    if events:
        for ev in events:
            dm.append_jsonl(ev, date=today)

    report = {
        "candidate_count": len(candidates),
        "shadow_promoted": shadow_promoted,
        "intent_count": len(intents),
        "dry_run": dry_run,
        "events_written": len(events),
        "result": result,
    }

    json_log = dm.state_dir / f"trade_gate_report_{today}.json"
    tmp = json_log.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(json_log)

    pending_count = len([c for c in dm.load_candidates(date=today) if c.get("awaiting_llm_review")])
    executed = result.get("executed", [])
    skipped = result.get("skipped", [])
    rejected = result.get("rejected", [])

    lines: list[str] = []
    if executed:
        for item in executed:
            symbol = item.get("symbol", "")
            direction = item.get("direction", "")
            price = item.get("price", 0)
            qty = item.get("quantity", 0)
            oid = ""
            if isinstance(item.get("order"), dict):
                oid = item["order"].get("order_id", "")
            dir_char = "S" if direction == "sell" else "B"
            lines.append(f"[EXEC] {dir_char} {symbol} {qty}@{price} {oid}")
    if rejected:
        for item in rejected[:5]:
            symbol = item.get("symbol", item.get("candidate_id", "?"))
            reason = item.get("rejection_reason", "unknown")
            lines.append(f"[REJ] {symbol}: {reason}")
    if skipped:
        for item in skipped[:3]:
            sym = item.get("intent", {}).get("symbol", item.get("candidate_id", "?"))
            reason = item.get("reason", "unknown")
            lines.append(f"[SKIP] {sym}: {reason}")
    if pending_count:
        lines.append(f"[PENDING] {pending_count} candidates awaiting LLM review")
    if not executed and not rejected and not skipped:
        lines.append("[NOOP] no actionable intents")

    print("\n".join(lines))


if __name__ == "__main__":
    main()
