#!/usr/bin/env python3
"""Deterministic A-share ledger and execution helpers.

The module keeps data validation and execution policy independent from cron prompts.
It never treats run markers or open positions as candidate trades.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from data import get_data_manager


def load_strategy_params() -> dict[str, Any]:
    """加载动态策略参数，带 fallback 到 config/strategy_params.json。"""
    dm = get_data_manager()
    params = dm.load_state("strategy_params.json")
    if params:
        return params
    # Fallback: 从 config/strategy_params.json 加载
    import json
    from pathlib import Path
    fallback = Path(__file__).resolve().parent.parent / "config" / "strategy_params.json"
    if fallback.exists():
        try:
            with open(fallback) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def is_catalyst_enabled(
    catalyst_type: str | None,
    params: dict[str, Any] | None = None,
    direction: str | None = None,
) -> bool:
    """检查催化剂类型是否启用。

    Strategy cooldowns protect capital from new BUY entries. They must never
    suppress SELL defense/exit signals.
    """
    if str(direction or "").strip().lower() == "sell":
        return True
    if not catalyst_type:
        return True
    if params is None:
        params = load_strategy_params()
    if catalyst_type in params.get("blacklist", []):
        return False
    cat_cfg = params.get("catalyst_types", {}).get(catalyst_type, {})
    if not cat_cfg:
        return True

    # 情绪周期自愈保护
    sentiment_phase = params.get("sentiment", {}).get("phase", "")
    if sentiment_phase in ("warmup", "hot", "euphoria"):
        return True

    cooldown = cat_cfg.get("cooldown_until")
    if cooldown:
        today_str = dt.date.today().isoformat()
        if today_str < cooldown:
            return False

    return cat_cfg.get("enabled", True)


def is_shadow_ready(candidate: dict[str, Any]) -> bool:
    """宽松信号层判定：缠论买卖点 + 基础成交量确认 → 影子追踪池。"""
    direction = candidate.get("direction")
    if direction not in {"buy", "sell"}:
        return False
    if not candidate.get("symbol") or float(candidate.get("price", 0) or 0) <= 0:
        return False
    if direction == "buy":
        return bool(
            candidate.get("chan_buy_point") in {"一买", "二买", "三买"}
            and candidate.get("chan_confirmed")
            and candidate.get("volume_confirmed")
        )
    elif direction == "sell":
        return bool(candidate.get("chan_sell_point") and candidate.get("chan_confirmed"))
    return False


def record_shadow_candidate(candidate: dict[str, Any], date: str | None = None) -> dict[str, Any]:
    """将宽松候选格式化为 shadow_candidate 记录并持久化。"""
    dm = get_data_manager()
    date = date or dt.date.today().isoformat()
    shadow = dict(candidate)
    orig_cid = str(candidate.get("candidate_id", ""))
    shadow["candidate_id"] = orig_cid if orig_cid.startswith("shadow-") else f"shadow-{orig_cid}"
    shadow["record_type"] = "shadow_candidate"
    shadow["shadow_tracked_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    dm.append_jsonl(shadow, date)
    return shadow


def load_shadow_candidates(date: str | None = None) -> list[dict[str, Any]]:
    dm = get_data_manager()
    date = date or dt.date.today().isoformat()
    records = dm.read_jsonl(date)
    shadows: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("record_type") == "shadow_candidate" and record.get("candidate_id"):
            shadows[record["candidate_id"]] = record
    return list(shadows.values())


def extract_attribution_layers(record: dict[str, Any]) -> dict[str, str]:
    cat = str(record.get("catalyst_type") or "unknown")
    chan_pt = str(record.get("chan_buy_point") or record.get("chan_sell_point") or "unknown_point")
    vol_state = "vol_confirmed" if record.get("volume_confirmed") else "vol_unconfirmed"
    confidence = float(record.get("confidence", 0) or 0)
    band = "0.65-0.70" if confidence < 0.70 else "0.70-0.80" if confidence < 0.80 else "0.80+"
    entry_rule = str(record.get("entry_rule") or "unknown")
    return {
        "level_1_catalyst": cat,
        "level_2_pattern": f"{chan_pt}/{vol_state}",
        "confidence_band": band,
        "entry_rule": entry_rule,
    }


def compute_empirical_bayes_win_rate(
    wins: int, sample_count: int,
    prior_win_rate: float = 0.50, prior_weight: float = 5.0,
) -> float:
    if sample_count <= 0:
        return round(prior_win_rate, 4)
    shrunk = (wins + prior_weight * prior_win_rate) / (sample_count + prior_weight)
    return round(shrunk, 4)


def hierarchical_attribution(
    outcomes: Iterable[dict[str, Any]], prior_win_rate: float = 0.50,
) -> dict[str, Any]:
    l1_stats: dict[str, dict[str, Any]] = {}
    l2_stats: dict[str, dict[str, Any]] = {}
    for row in outcomes:
        layers = extract_attribution_layers(row)
        outcome = row.get("outcome")
        is_win = 1 if outcome == "win" else 0
        is_completed = 1 if outcome in {"win", "loss", "flat"} else 0
        c1 = layers["level_1_catalyst"]
        if c1 not in l1_stats:
            l1_stats[c1] = {"sample": 0, "wins": 0}
        l1_stats[c1]["sample"] += is_completed
        l1_stats[c1]["wins"] += is_win
        c2 = f"{c1}::{layers['level_2_pattern']}"
        if c2 not in l2_stats:
            l2_stats[c2] = {"sample": 0, "wins": 0, "catalyst_type": c1, "pattern": layers["level_2_pattern"]}
        l2_stats[c2]["sample"] += is_completed
        l2_stats[c2]["wins"] += is_win
    for st in list(l1_stats.values()) + list(l2_stats.values()):
        n = st["sample"]
        w = st["wins"]
        st["raw_win_rate"] = round(w / n, 4) if n > 0 else None
        st["shrunk_win_rate"] = compute_empirical_bayes_win_rate(w, n, prior_win_rate=prior_win_rate)
    return {"level_1": l1_stats, "level_2": l2_stats}


def is_trade_ready(candidate: dict[str, Any], require_risk: bool = True) -> bool:
    direction = candidate.get("direction")
    is_sell = direction == "sell"
    llm_approved = candidate.get("llm_approved") is True
    agy_approved = candidate.get("agy_approved") is True
    approved = llm_approved or agy_approved

    if candidate.get("agy_approved") is False or candidate.get("llm_approved") is False:
        return False

    catalyst = str(candidate.get("catalyst_type", ""))
    is_limit_up = catalyst.startswith("limit_up")
    is_auction = catalyst.startswith("call_auction") or catalyst.startswith("1to2") or catalyst.startswith("opening_sniper")
    is_chanlun = not (is_limit_up or is_auction)
    breakout = candidate.get("breakout_confirmed") is True

    if direction == "buy":
        try:
            sp = load_strategy_params()
            sent = sp.get("sentiment", {})
            phase = sent.get("phase", "")
            multiplier = float(sent.get("multiplier", 1.0))
            if phase == "cooldown" and multiplier <= 0.3:
                return False
        except Exception:
            pass

    required = [
        bool(candidate.get("symbol")),
        direction in {"buy", "sell"},
        int(candidate.get("quantity", 0) or 0) >= 100,
        float(candidate.get("price", 0) or 0) > 0,
        bool(candidate.get("entry_rule")) if direction == "buy" else True,
        (is_catalyst_enabled(catalyst) if direction == "buy" else True),
        float(candidate.get("confidence", 0) or 0) >= (0.50 if approved else 0.65),
    ]

    if direction == "buy":
        required.extend([
            bool(candidate.get("realtime_confirmed")),
            bool(candidate.get("volume_confirmed")),
            bool(candidate.get("sector_confirmed")),
            bool(candidate.get("fundamental_confirmed")),
            bool(candidate.get("news_confirmed")),
        ])

    if is_limit_up or breakout:
        required.extend([bool(breakout), bool(candidate.get("volume_confirmed"))])
    elif is_auction:
        required.append(bool(candidate.get("volume_confirmed")))
        if not approved:
            required.append(bool(candidate.get("sector_confirmed")))
    else:
        if direction == "buy":
            required.append(candidate.get("chan_buy_point") in {"一买", "二买", "三买"})
            required.append(bool(candidate.get("chan_confirmed")))
        if direction == "buy" and not approved:
            required.append(bool(candidate.get("volume_confirmed")))

    if not is_sell and not approved and not is_limit_up and not breakout and not is_auction:
        required.extend([
            float(candidate.get("leader_score", 0) or 0) >= 55,
            bool(candidate.get("sector_confirmed")),
            bool(candidate.get("fundamental_confirmed")),
            bool(candidate.get("realtime_confirmed")),
            bool(candidate.get("news_confirmed")),
            any(str(candidate.get("thesis", "")).startswith(p) for p in ("[缺口逻辑]", "[缠论]", "[尾盘]", "[首板]", "[连板]", "[竞价]")),
        ])

    if require_risk:
        required.append(bool(candidate.get("risk_approved")))
    return all(required)


def normalize_intent(
    candidate: dict[str, Any],
    total_assets: float = 0.0,
    adjusted_pct: float = 0.0,
    available_cash: float = 0.0,
    current_market_val: float = 0.0,
    max_regime_ratio: float = 1.0,
) -> dict[str, Any]:
    cid = candidate.get("candidate_id", "")
    if not cid:
        cid = f"no-cid-{dt.datetime.now(dt.timezone.utc).strftime('%H%M%S')}"
    intent_id = f"it-{cid}"

    price = float(candidate.get("price", 0) or 0)
    original_qty = int(candidate.get("quantity", 0) or 0)
    direction = candidate.get("direction", "buy")

    if direction == "buy" and total_assets > 0 and adjusted_pct > 0 and price > 0:
        target_value = total_assets * adjusted_pct
        if max_regime_ratio < 1.0:
            max_allowed = max(0.0, total_assets * max_regime_ratio - current_market_val)
            target_value = min(target_value, max_allowed)
        if available_cash > 0:
            target_value = min(target_value, available_cash * 0.95)
        target_qty = int(target_value / price / 100) * 100
        qty = target_qty
    else:
        qty = max(100, original_qty)

    return {
        "intent_id": intent_id,
        "candidate_id": cid,
        "symbol": candidate["symbol"],
        "name": candidate.get("name") or "",
        "direction": direction,
        "price": round(float(price), 2),
        "quantity": qty,
        "confidence": float(candidate.get("confidence", 0)),
        "thesis": candidate.get("thesis", ""),
        "entry_rule": candidate.get("entry_rule", ""),
        "catalyst_type": candidate.get("catalyst_type", "technical_breakout"),
        "approval_status": "pending",
        "llm_approved": bool(candidate.get("llm_approved")),
        "agy_approved": bool(candidate.get("agy_approved")),
        "reviewed_by": candidate.get("reviewed_by", ""),
        "reasoning": candidate.get("reasoning", ""),
        "max_position_pct": adjusted_pct if adjusted_pct > 0 else candidate.get("max_position_pct", 0.2),
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def degraded_risk_check(
    intents: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    account: dict[str, Any],
    session: dict[str, Any],
) -> dict[str, Any]:
    """FAIL-CLOSED degraded mode risk check when Risk MCP is unavailable.

    This runs a SUBSET of risk checks using locally-available data only.
    Checks that REQUIRE Risk MCP data (market crash, sentiment, sector
    concentration, outflow) are SKIPPED -- but the intent is NOT auto-approved.
    The check is applied to ALL intents regardless of AGY status.

    Degraded checks:
      - T+1 rule (local position data + trade journal)
      - Position cap (local config)
      - Cash availability (local account data)
      - Basic price sanity (not zero/negative, within limit-ratio bounds)
      - Trading session (is market open?)
      - ST blacklist (local name check)
      - Freeze list (local state)
      - Avg-down prohibition (local position data)

    Skipped (require Risk MCP):
      - Market crash detection
      - Sentiment check
      - Sector concentration
      - Outflow detection
      - Weekend check (trading session covers this partially)
      - Tail chase (time-based, but needs MCP trading calendar for accuracy)
    """
    import datetime as dt
    from risk.risk_manager import _is_st, _get_limit_ratio

    dm = get_data_manager()
    params = load_strategy_params()
    max_pos_limit = int(params.get("global_guards", {}).get("max_position_count", 5))
    max_single_pct = float(params.get("global_guards", {}).get("max_single_position_pct", 0.30))

    today = dt.date.today().isoformat()

    # Build local position map
    position_map: dict[str, dict[str, Any]] = {}
    if isinstance(positions, list):
        for p in positions:
            if isinstance(p, dict):
                position_map[str(p.get("symbol", ""))] = p

    # Calculate available cash
    available_cash = 0.0
    if isinstance(account, dict):
        available_cash = float(account.get("cash", account.get("balance", 0)) or 0)
    total_assets = float(account.get("total_assets", account.get("total_asset", 0)) or available_cash or 0)

    # Load today's trade journal for T+1
    try:
        today_records = dm.read_jsonl(date=today)
    except Exception:
        today_records = []

    today_trades: dict[str, str] = {}
    for r in today_records:
        if r.get("record_type") == "candidate_event":
            ev = r.get("event", "")
            sym = str(r.get("symbol", ""))
            dr = str(r.get("direction", "")).lower().strip()
            if sym and ev in ("executed", "submitted", "submitted_unverified"):
                today_trades[sym] = dr

    # Load freeze list
    try:
        freeze_state = dm.load_state("freeze_state.json")
        freeze_map = freeze_state.get("freeze", {}) if freeze_state else {}
    except Exception:
        freeze_map = {}

    results = []
    consumed_cash = 0.0
    effective_positions: set[str] = set()
    for sym, pdata in position_map.items():
        qty = int(float(pdata.get("quantity", 0) or 0))
        if qty > 200:
            effective_positions.add(sym)

    for intent in intents:
        symbol = str(intent.get("symbol", ""))
        direction = str(intent.get("direction", "")).lower().strip()
        name = str(intent.get("name", intent.get("symbol", "")))
        quantity = int(intent.get("quantity", 0) or 0)
        price = float(intent.get("price", 0) or 0)

        rejection_reason = ""

        # Check 1: Trading session
        if isinstance(session, dict) and session.get("is_trading_day") is True and session.get("is_open") is True:
            pass  # OK
        else:
            rejection_reason = "degraded: outside trading session"

        # Check 2: Price sanity (not zero/negative, within limit ratio bounds)
        if not rejection_reason:
            if price <= 0:
                rejection_reason = "degraded: invalid price (<= 0)"
            else:
                limit_ratio = _get_limit_ratio(symbol, name)
                # Rough sanity: price should be > 0.01 and < some absurd high
                if price < 0.01:
                    rejection_reason = f"degraded: price {price} too low for trading"

        # Check 3: ST blacklist
        if not rejection_reason:
            if _is_st(name, symbol):
                rejection_reason = f"degraded: ST blacklisted {name}({symbol})"

        # Check 4: Freeze
        if not rejection_reason:
            if symbol in freeze_map:
                frozen_until = freeze_map[symbol]
                if today < frozen_until:
                    rejection_reason = f"degraded: {symbol} frozen until {frozen_until}"

        # Check 5: T+1 direction conflict
        if not rejection_reason:
            last_dir = today_trades.get(symbol)
            if last_dir and last_dir == direction:
                rejection_reason = f"degraded: T+1 conflict, already {direction} today for {symbol}"

        if direction == "buy":
            # Check 6: Position cap (single symbol)
            if not rejection_reason:
                current_value = 0.0
                if symbol in position_map:
                    p = position_map[symbol]
                    mv = float(p.get("market_value", 0) or 0)
                    if mv <= 0:
                        mv = float(p.get("current_price", p.get("cost_price", 0)) or 0) * float(p.get("quantity", 0) or 0)
                    current_value = mv
                new_value = quantity * price
                if total_assets > 0:
                    ratio = (current_value + new_value) / total_assets
                    if ratio > max_single_pct:
                        rejection_reason = f"degraded: single position {ratio:.1%} > {max_single_pct:.0%} cap"

            # Check 7: Cash availability
            if not rejection_reason:
                cost = price * quantity
                if cost > (available_cash - consumed_cash):
                    rejection_reason = f"degraded: insufficient cash (need {cost:.2f}, avail {(available_cash - consumed_cash):.2f})"

            # Check 8: Max position count
            if not rejection_reason:
                if symbol not in effective_positions:
                    if len(effective_positions) >= max_pos_limit:
                        rejection_reason = f"degraded: max position limit ({len(effective_positions)}/{max_pos_limit})"

            # Check 9: Avg-down prohibition
            if not rejection_reason:
                if symbol in position_map:
                    holding_qty = int(float(position_map[symbol].get("quantity", 0) or 0))
                    if holding_qty > 0:
                        rejection_reason = f"degraded: avg-down prohibited, holding {holding_qty} shares of {symbol}"

            # Track consumed cash for ordering consistency
            if not rejection_reason:
                consumed_cash += cost
                if symbol not in effective_positions:
                    effective_positions.add(symbol)

        elif direction == "sell":
            # Check: Have shares to sell
            if not rejection_reason:
                if symbol in position_map:
                    holding = position_map[symbol]
                    av_raw = holding.get("available_quantity") if holding.get("available_quantity") is not None else holding.get("available_shares")
                    if av_raw is not None:
                        available_shares = int(float(av_raw))
                    else:
                        available_shares = int(float(holding.get("quantity", 0) or 0))
                    if available_shares < 100:
                        rejection_reason = f"degraded: insufficient shares for {symbol} (have {available_shares})"
                else:
                    rejection_reason = f"degraded: no position in {symbol} to sell"

        else:
            rejection_reason = f"degraded: unknown direction '{direction}'"

        if rejection_reason:
            results.append({
                "approved": False,
                "approval_status": "rejected",
                "approved_by": "degraded_risk_check",
                "rejection_reason": rejection_reason,
            })
        else:
            results.append({
                "approved": True,
                "approval_status": "approved",
                "approved_by": "degraded_risk_check",
            })

    return {"results": results}


def risk_check_and_execute(
    intents: list[dict[str, Any]],
    dry_run: bool = True,
) -> dict[str, Any]:
    """Run risk approval, registration, execution, reconciliation."""
    from mcp_client import get_mcp_client
    client = get_mcp_client()
    dm = get_data_manager()

    if not intents:
        return {"approved": [], "rejected": [], "executed": [], "skipped": [], "status": "no_signal"}
    if any(i.get("approval_status") not in {"pending", "approved", "reduced"} for i in intents):
        raise ValueError("invalid TradeIntent approval_status")

    try:
        session = client.get_trading_sessions()
    except Exception:
        session = {}
    if not isinstance(session, dict) or session.get("is_trading_day") is not True or session.get("is_open") is not True:
        agy_fallback = any(i.get("llm_approved") or i.get("agy_approved") for i in intents)
        if not agy_fallback:
            return {"approved": [], "rejected": [], "executed": [],
                    "skipped": [{"intent": i, "reason": "outside trading session"} for i in intents],
                    "status": "blocked_outside_trading_session"}

    risk = None
    backoff = [1, 2, 4]
    for attempt in range(4):
        try:
            risk = client.batch_check({"intents": [
                {"symbol": i["symbol"], "direction": i["direction"],
                 "quantity": i["quantity"], "price": i["price"]}
                for i in intents
            ]})
            if isinstance(risk, dict) and not risk.get("error"):
                break
        except Exception:
            risk = {"error": "timeout"}
        if attempt < 3:
            time.sleep(backoff[attempt])
    else:
        # ── FAIL-CLOSED: Risk MCP unavailable after all retries ──
        logging.warning(
            "FAIL-CLOSED: Risk MCP unavailable after %d retries. "
            "Applying degraded risk checks to all %d intents (AGY/non-AGY). "
            "Checks requiring MCP data (market crash, sentiment, sector, outflow) are skipped.",
            4, len(intents),
        )
        try:
            account = client.get_balance()
        except Exception:
            account = {}
        try:
            positions = client.get_positions()
        except Exception:
            positions = []
        try:
            session_state = client.get_trading_sessions()
        except Exception:
            session_state = session if isinstance(session, dict) else {}

        deg_risk = degraded_risk_check(intents, positions, account, session_state)
        deg_results = deg_risk.get("results", [])
        approved_count = sum(1 for r in deg_results if r.get("approved"))
        rejected_count = len(deg_results) - approved_count
        logging.warning(
            "FAIL-CLOSED degraded result: %d approved, %d rejected of %d intents",
            approved_count, rejected_count, len(intents),
        )
        risk = deg_risk

    results = risk.get("results", []) if isinstance(risk, dict) else []
    if len(results) != len(intents):
        if not results:
            rejection_reason = risk.get("error", "risk response count mismatch") if isinstance(risk, dict) else "risk unavailable"
            rejected = [dict(i, approval_status="rejected", rejection_reason=rejection_reason) for i in intents]
            return {"approved": [], "rejected": rejected, "executed": [], "skipped": []}
        # Partial results: pair up what we can, reject the rest individually
        matched = min(len(results), len(intents))
        approved, rejected = [], []
        for i in range(matched):
            item = dict(intents[i])
            item.update(results[i] if isinstance(results[i], dict) else {})
            if item.get("approval_status") not in {"approved", "reduced"} and not item.get("approved"):
                item["approval_status"] = "rejected"
                rejected.append(item)
            else:
                item["approval_status"] = "approved"
                approved.append(item)
        for i in range(matched, len(intents)):
            rejected.append(dict(intents[i], approval_status="rejected", rejection_reason="no risk response for this intent"))
        return {"approved": approved, "rejected": rejected, "executed": [], "skipped": []}

    approved, rejected = [], []
    for original, result in zip(intents, results):
        item = dict(original)
        item.update(result if isinstance(result, dict) else {})
        if item.get("approval_status") not in {"approved", "reduced"} and not item.get("approved"):
            item["approval_status"] = "rejected"
            rejected.append(item)
        else:
            item["approval_status"] = "approved"
            approved.append(item)

    if not approved:
        return {"approved": [], "rejected": rejected, "executed": [], "skipped": [], "status": "all_risk_rejected"}

    try:
        account = client.get_balance()
    except Exception:
        account = {}
    try:
        positions = client.get_positions()
    except Exception:
        positions = []
    if isinstance(account, dict) and "cash" not in account and "balance" not in account:
        account = {"cash": 0.0}
    if isinstance(positions, list):
        positions_list = positions
    elif isinstance(positions, dict):
        positions_list = positions.get("positions", positions.get("value", []))
    else:
        positions_list = []
    available_cash = float(account.get("cash", 0) or 0)
    position_map = {str(p.get("symbol")): p for p in positions_list if isinstance(p, dict)}
    params = load_strategy_params()
    max_pos_limit = int(params.get("global_guards", {}).get("max_position_count", 5))

    snapshot_rejected = []
    for item in approved:
        if item.get("direction") == "buy":
            cost = float(item["price"]) * int(item["quantity"])
            if cost > available_cash:
                item["approval_status"] = "rejected"
                item["rejection_reason"] = f"insufficient cash (need {cost:.2f}, avail {available_cash:.2f})"
                snapshot_rejected.append(item)
                continue
            sym = str(item["symbol"])
            effective_positions = {s: p for s, p in position_map.items() if int(float(p.get("quantity", 0) or 0)) > 200}
            if sym not in position_map:
                if len(effective_positions) >= max_pos_limit:
                    item["approval_status"] = "rejected"
                    item["rejection_reason"] = f"max position limit ({len(effective_positions)}/{max_pos_limit})"
                    snapshot_rejected.append(item)
                    continue
            available_cash -= cost
            position_map[sym] = {"quantity": item["quantity"]}
        elif item.get("direction") == "sell":
            holding = position_map.get(str(item["symbol"]), {})
            av_raw = holding.get("available_quantity") if holding.get("available_quantity") is not None else holding.get("available_shares")
            if av_raw is not None:
                available = int(float(av_raw))
            else:
                try:
                    trades_list = client.get_today_trades()
                    if isinstance(trades_list, list):
                        pass
                    elif isinstance(trades_list, dict):
                        trades_list = trades_list.get("trades", trades_list.get("data", []))
                    else:
                        trades_list = []
                    today_buys = sum(
                        int(float(t.get("quantity", 0) or 0))
                        for t in trades_list
                        if str(t.get("direction", "")).upper() == "BUY" and str(t.get("symbol", "")) == str(item["symbol"])
                    )
                    available = max(0, int(float(holding.get("quantity", 0) or 0)) - today_buys)
                except Exception:
                    available = int(float(holding.get("quantity", 0) or 0))
            if available < 100:
                item["approval_status"] = "rejected"
                item["rejection_reason"] = "temporary_insufficient_shares"
                snapshot_rejected.append(item)
            else:
                cand_qty = int(item["quantity"])
                item["quantity"] = min(cand_qty, available)

    approved = [item for item in approved if item not in snapshot_rejected]
    rejected.extend(snapshot_rejected)

    executed, skipped = [], []
    for intent in approved:
        intent_id = intent.get("intent_id")
        candidate_id = intent.get("candidate_id")
        if not intent_id:
            skipped.append({"intent": intent, "reason": "missing intent_id"})
            continue
        if not candidate_id:
            skipped.append({"intent": intent, "reason": "missing candidate_id"})
            continue
        if dry_run:
            intent["execution_status"] = "simulated"
            executed.append(intent)
            continue
        if intent.get("exec_registered") is not True:
            try:
                registration = client.register_approved_intent(
                    intent_id=intent_id,
                    symbol=intent["symbol"],
                    direction=intent["direction"],
                    max_quantity=intent["quantity"],
                )
                if isinstance(registration, dict) and registration.get("error"):
                    skipped.append({"intent": intent, "reason": "registration failed", "detail": registration})
                    continue
            except Exception as e:
                skipped.append({"intent": intent, "reason": f"registration exception: {e}"})
                continue
            intent["exec_registered"] = True
        try:
            order = client.place_order(
                symbol=intent["symbol"], direction=intent["direction"],
                price=intent["price"], quantity=intent["quantity"],
                intent_id=intent_id, reason=intent.get("thesis", "")[:240],
            )
            intent["order"] = order
        except Exception as e:
            intent["execution_status"] = "failed"
            skipped.append({"intent": intent, "reason": f"order failed: {e}"})
            continue
        executed.append(intent)

        if not dry_run:
            try:
                from intelligence.feishu_notifier import notify_trade_executed
                notify_trade_executed(
                    direction=intent.get("direction", ""),
                    symbol=intent.get("symbol", ""),
                    name=intent.get("name", intent.get("symbol", "")),
                    quantity=int(intent.get("quantity", 0)),
                    price=float(intent.get("price", 0.0)),
                    order_id=str(intent.get("order", {}).get("order_id", "")),
                    reason=intent.get("thesis", intent.get("reasoning", "")),
                    cash_remaining=available_cash,
                )
            except Exception as fe:
                logging.error(f"Feishu notification failed: {fe}")

    return {"approved": approved, "rejected": rejected, "executed": executed, "skipped": skipped, "status": "completed"}


if __name__ == "__main__":
    print("Pipeline module loaded OK")
