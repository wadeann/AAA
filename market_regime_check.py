#!/usr/bin/env python3
"""AGY 铁律唯一门禁检查器 (Market Regime Check - Iron Rule Gate).

移植至 Astock: urllib MCP 调用替换为 MCPClient,
~/.hermes/trading/config 路径替换为 STATE_DIR.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any, Optional

from config import STATE_DIR
from mcp_client import get_mcp_client
from utils_market import get_stock_market_type

# 门禁依赖（熔断时 fallback 为宽松的默认实现）
try:
    from strategy_circuit_breaker import check_strategy
except ImportError:
    def check_strategy(catalyst_type: str) -> tuple[bool, str]:
        return False, "PASS"
try:
    from leader_universe_filter import get_leader_universe
except ImportError:
    def get_leader_universe(force_refresh: bool = False, output_only: bool = True, verbose: bool = False) -> list:
        return []

CST = dt.timezone(dt.timedelta(hours=8))
REGIME_FILE = STATE_DIR / "market_regime.json"
CONFIG_FILE = STATE_DIR / "strategy_params.json"


def _read_json_safe(path) -> dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _write_json_safe(path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def intraday_dynamic_check(
    quotes: Optional[dict[str, Any]] = None,
    market_metrics: Optional[dict[str, Any]] = None,
    verbose: bool = False,
) -> tuple[bool, dict[str, Any]]:
    """盘中实时动态熔断器 (P0-02)."""
    if market_metrics is None:
        market_metrics = {}

    tripped = False
    reasons: list[str] = []
    client = get_mcp_client()

    limitdown = market_metrics.get("limitdown_count")
    if limitdown is None:
        try:
            health = client.get_market_health()
            limitdown = int(health.get("limitdown_count", 0))
        except Exception:
            limitdown = 0
    if limitdown is not None and limitdown >= 20:
        tripped = True
        reasons.append(f"全市场跌停 {limitdown} 家(>=20)")

    broken_rate = market_metrics.get("broken_seal_rate")
    if broken_rate is None:
        try:
            health = client.get_market_health()
            broken_rate = float(health.get("broken_seal_rate", 0.0))
        except Exception:
            broken_rate = 0.0
    if broken_rate is not None and broken_rate >= 45.0:
        tripped = True
        reasons.append(f"炸板率 {broken_rate:.1f}%(>=45%)")

    idx_symbols = ["000001.SH", "399006.SZ", "399001.SZ", "000688.SH"]
    idx_quotes: dict[str, Any] = {}
    if quotes and isinstance(quotes, dict):
        for s in idx_symbols:
            q = (quotes.get(s) or quotes.get(s.split(".")[0]) or
                 quotes.get(f"sh{s.split('.')[0]}") or quotes.get(f"sz{s.split('.')[0]}"))
            if q:
                idx_quotes[s] = q
    missing = [s for s in idx_symbols if s not in idx_quotes]
    if missing:
        try:
            q_res = client.query_quotes(missing)
            if isinstance(q_res, dict):
                for s in missing:
                    for k, v in q_res.items():
                        if s in k:
                            idx_quotes[s] = v
                            break
        except Exception:
            pass

    index_changes: dict[str, float] = {}
    for s, q in idx_quotes.items():
        try:
            chg = float(q.get("change_pct", q.get("pct_change", 0.0)) or 0.0)
            index_changes[s] = chg
            name = q.get("name", s)
            if s != "000688.SH" and chg <= -2.0:
                tripped = True
                reasons.append(f"宽基 {name}({s}) 暴跌 {chg:+.2f}%")
        except Exception:
            pass

    star_change = index_changes.get("000688.SH")
    broad_symbols = ("000001.SH", "399001.SZ", "399006.SZ")
    broad_changes = [index_changes[s] for s in broad_symbols if s in index_changes]
    isolated_star_crash = (
        star_change is not None and star_change <= -2.0
        and broad_changes and all(chg > -1.0 for chg in broad_changes)
        and (limitdown is None or limitdown < 20)
        and (broken_rate is None or broken_rate < 45.0)
    )
    if star_change is not None and star_change <= -2.0 and not isolated_star_crash:
        tripped = True
        reasons.append(f"科创50暴跌 {star_change:+.2f}% 且宽基/情绪恶化")

    broad_index_crash = any(chg <= -2.0 for chg in broad_changes)
    suspicious = limitdown == 0 and broad_index_crash
    if suspicious:
        tripped = True
        reasons.append("宽基暴跌但跌停为0，数据失真 Fail-Closed")

    details: dict[str, Any] = {
        "tripped": tripped, "reasons": reasons,
        "limitdown_count": limitdown, "broken_seal_rate": broken_rate,
        "index_changes": index_changes, "isolated_star_crash": isolated_star_crash,
        "blocked_market_types": ["STAR"] if isolated_star_crash else [],
        "scope": "STAR_ONLY" if isolated_star_crash and not tripped else ("GLOBAL" if tripped else "NONE"),
    }

    if isolated_star_crash and not tripped:
        details["reason"] = (
            f"科创50孤立下跌{star_change:+.2f}%，宽基未跌超-1%、跌停{limitdown}家、"
            f"炸板率{broken_rate}%；仅隔离科创板"
        )
        try:
            regime_data = _read_json_safe(REGIME_FILE) if REGIME_FILE.exists() else {}
            cfg_data = _read_json_safe(CONFIG_FILE) if CONFIG_FILE.exists() else {}
            old_reason = " ".join([str(regime_data.get("description", "")),
                                   str((cfg_data.get("sentiment") or {}).get("description", ""))])
            if "科创50" in old_reason:
                now_cst = dt.datetime.now(CST)
                segmented = {
                    "regime": "震荡", "standard_regime": "diverging", "regime_multiplier": 0.25,
                    "max_regime_ratio": 0.25, "sell_only_mode": False,
                    "blocked_market_types": ["STAR"],
                    "description": f"【分市场风控】{details['reason']}",
                    "updated_at": now_cst.isoformat(), "source_date": now_cst.strftime("%Y-%m-%d"),
                    "ttl_seconds": 900, "data_fresh": True, "fail_closed": False,
                    "limitdown_count": limitdown, "broken_seal_rate": broken_rate,
                    "index_changes": index_changes,
                }
                _write_json_safe(REGIME_FILE, segmented)
                cfg_data["sell_only_mode"] = False
                cfg_data.setdefault("global_guards", {})["sell_only_mode"] = False
                cfg_data["market_scope_guards"] = {
                    "blocked_market_types": ["STAR"], "reason": details["reason"],
                    "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
                cfg_data["sentiment"] = {
                    "phase": "diverging", "multiplier": 0.25,
                    "description": f"分市场风控: {details['reason']}",
                    "cand_count": int((cfg_data.get("sentiment") or {}).get("cand_count", 0) or 0),
                    "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
                _write_json_safe(CONFIG_FILE, cfg_data)
        except Exception:
            pass

    if tripped:
        trip_reason = " | ".join(reasons)
        details["reason"] = trip_reason
        details["regime"] = "panic_ebb"
        details["standard_regime"] = "panic_ebb"
        details["sell_only_mode"] = True
        details["regime_multiplier"] = 0.0
        details["max_regime_ratio"] = 0.0

        try:
            now_str = dt.datetime.now(CST).isoformat()
            downgrade = {
                "regime": "极寒", "standard_regime": "panic_ebb", "ebb_subtype": "panic_ebb",
                "regime_multiplier": 0.0, "max_regime_ratio": 0.0, "sell_only_mode": True,
                "description": f"【盘中实时动态熔断】{trip_reason}",
                "updated_at": now_str, "source_date": dt.datetime.now(CST).strftime("%Y-%m-%d"),
                "ttl_seconds": 900, "data_fresh": not suspicious, "fail_closed": suspicious,
                "limitdown_count": limitdown, "broken_seal_rate": broken_rate,
            }
            _write_json_safe(REGIME_FILE, downgrade)

            cfg = _read_json_safe(CONFIG_FILE)
            cfg["sell_only_mode"] = True
            cfg.setdefault("global_guards", {})["sell_only_mode"] = True
            cfg["sentiment"] = {
                "phase": "ice", "multiplier": 0.0,
                "description": f"市场状态机同步熔断: {trip_reason}",
                "cand_count": int((cfg.get("sentiment") or {}).get("cand_count", 0) or 0),
                "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            }
            _write_json_safe(CONFIG_FILE, cfg)
        except Exception:
            pass

    return tripped, details


def iron_rule_gate(candidate: dict[str, Any], now_cst: Optional[dt.datetime] = None) -> tuple[bool, str]:
    """AGY唯一铁律入口，一次性聚合四道门禁."""
    if now_cst is None:
        now_cst = dt.datetime.now(CST)

    sym = candidate.get("symbol", "").strip().upper()
    direction = candidate.get("direction", "buy").strip().lower()
    cat = candidate.get("catalyst_type", "").strip() or "default"

    if direction == "sell":
        return True, "PASS: 卖出方向豁免铁律"

    # 盘中动态熔断
    metrics = candidate.get("market_metrics")
    quotes_ctx = candidate.get("index_quotes") or candidate.get("quotes")
    tripped, trip_info = intraday_dynamic_check(quotes=quotes_ctx, market_metrics=metrics)
    if tripped:
        return False, f"铁律熔断: {trip_info.get('reason', '盘中指标触及红线')}"
    if get_stock_market_type(sym) in set(trip_info.get("blocked_market_types") or []):
        return False, f"科创板隔离: {trip_info.get('reason', '')}"

    # 连板深度核验
    if direction == "buy":
        streak_val = candidate.get("streak") or candidate.get("real_streak") or candidate.get("board_height")
        if streak_val is not None:
            try:
                streak = int(float(streak_val))
                if streak >= 3:
                    is_dragon = candidate.get("is_dragon", False) or candidate.get("catalyst_type") == "dragon_screener"
                    has_support = candidate.get("has_sector_support", True)
                    score = candidate.get("dragon_score", 0)
                    if is_dragon and has_support and score >= 10:
                        pass
                    elif is_dragon and not has_support:
                        return False, f"铁律熔断: {streak}板但无梯队助攻(光杆司令)"
                    else:
                        return False, f"铁律熔断: {streak}板且非优质真龙(得分={score})"
            except (ValueError, TypeError):
                pass

    # 策略熔断器
    is_blocked, cb_reason = check_strategy(cat)
    if is_blocked:
        return False, f"铁律熔断 [策略]: {cb_reason}"

    # 市场状态机
    regime_info = _read_json_safe(REGIME_FILE) if REGIME_FILE.exists() else {"regime": "震荡"}
    regime = regime_info.get("regime", "震荡")
    standard_regime = regime_info.get("standard_regime", "")

    if regime_info.get("data_fresh") is False:
        return False, "铁律熔断: 市场状态缓存陈旧"
    if regime in ("非交易日", "极寒", "freezing") or standard_regime == "freezing":
        return False, "铁律熔断: 市场极寒状态"
    if regime_info.get("fail_closed") is True:
        return False, "铁律熔断: Fail-Closed 防御熔断"

    # 龙头池门禁
    try:
        leaders = get_leader_universe(output_only=True)
        leader_syms = {l.get("symbol", "").upper() for l in leaders if isinstance(l, dict)}
    except Exception:
        leader_syms = set()

    is_sector_leader = (sym in leader_syms) or candidate.get("is_sector_leader", False) or candidate.get("is_dragon", False)

    quote = candidate.get("quote", {})
    try:
        if isinstance(quote, dict) and "change_pct" in quote:
            target_change_pct = float(quote.get("change_pct", 0.0) or 0.0)
        else:
            target_change_pct = float(candidate.get("change_pct", candidate.get("price_change_pct", 0.0)) or 0.0)
    except (ValueError, TypeError):
        target_change_pct = 0.0

    is_chasing = target_change_pct >= 1.5
    is_exhaustion_first_board = False

    # 退潮期门禁
    if regime in ("退潮", "panic_ebb") or standard_regime == "panic_ebb":
        ebb_sub = regime_info.get("ebb_subtype", "panic_ebb" if standard_regime == "panic_ebb" else "")

        if ebb_sub == "panic_ebb":
            return False, "铁律熔断: 恐慌杀跌期，禁止一切开仓"

        if ebb_sub == "exhaustion_ebb":
            streak_v = candidate.get("streak") or candidate.get("real_streak") or candidate.get("board_height") or 1
            try:
                streak_n = int(float(streak_v))
            except (ValueError, TypeError):
                streak_n = 1
            if streak_n > 1:
                return False, f"铁律熔断: 衰竭冰点仅允许首板，标的{streak_n}板"
            if is_chasing:
                return False, f"铁律熔断: 衰竭冰点严禁追高({target_change_pct:+.2f}%)"
            is_exhaustion_first_board = True

        elif not is_sector_leader:
            return False, f"铁律熔断: 退潮期非身位第一龙头，严禁买入跟风杂毛"
        elif is_chasing and not (candidate.get("is_dragon") and candidate.get("dragon_score", 0) >= 10 and candidate.get("has_sector_support", True)):
            return False, f"铁律熔断: 退潮期龙头追高({target_change_pct:+.2f}%)"

    # 垃圾时间门禁
    cur_time = now_cst.time()
    is_garbage_hour = dt.time(10, 0) <= cur_time <= dt.time(14, 30)
    if is_garbage_hour:
        if not is_sector_leader and not is_exhaustion_first_board:
            return False, f"铁律熔断: 垃圾时间({cur_time.strftime('%H:%M')})非龙头"
        is_true_dragon = bool(candidate.get("is_dragon") and candidate.get("dragon_score", 0) >= 10 and candidate.get("has_sector_support", True))
        if is_chasing and not is_true_dragon:
            return False, f"铁律熔断: 垃圾时间追涨({target_change_pct:+.2f}%)"

    return True, "PASS: 通过AGY铁律门禁"
