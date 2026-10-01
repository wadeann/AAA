#!/usr/bin/env python3
"""Audit forward-recorded candidate outcomes and persist actionable feedback.

Empirical Bayes win rate smoothing with strategy state machine:
- <5 samples: observe only
- 5-9 samples: use shrunk (prior-pooled) win rate
- >=10 samples: use raw win rate
- eval_rate < 40% with >=5 samples: generate P1 action items
- Per-catalyst-type state machine with adaptive confidence/position scaling

Replaces evolution_audit.py — all data via DataManager, config via config module.
"""

from __future__ import annotations

import datetime as dt
import glob
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from config import LEDGER_DIR, STATE_DIR, load_json, save_json
from data import get_data_manager

STRATEGY_PARAMS = "strategy_params.json"
REVIEWS_DIR = STATE_DIR / "reviews"
STRATEGY_FEEDBACK = STATE_DIR / "strategy-feedback.md"


def pct_value(value: Any) -> float:
    """Normalize decimal-return inputs to percentage points."""
    number = float(value or 0.0)
    if -0.5 < number < 0.5 and number != 0.0:
        number *= 100.0
    return number


def read_outcomes(recent_files_limit: int = 14) -> list[dict[str, Any]]:
    """Read candidate outcome records from JSONL ledger files."""
    outcomes: list[dict[str, Any]] = []
    all_files = sorted(glob.glob(str(LEDGER_DIR / "candidates_*.jsonl")))
    recent_files = all_files[-recent_files_limit:] if len(all_files) > recent_files_limit else all_files
    for path in recent_files:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rec_type = row.get("record_type")
                if rec_type in {"candidate_outcome", "shadow_outcome"} and row.get("candidate_id"):
                    outcomes.append(row)
                elif rec_type == "shadow_candidate" and row.get("candidate_id") and row.get("outcome") in {"win", "loss", "flat"}:
                    outcomes.append(row)
    return outcomes


def key_for(row: dict[str, Any]) -> tuple[str, ...]:
    """Build a composite grouping key for strategy stratification."""
    confidence = float(row.get("confidence", 0) or 0)
    band = (
        "0.65-0.70" if confidence < 0.70
        else "0.70-0.80" if confidence < 0.80
        else "0.80+"
    )
    cat = row.get("catalyst_type", "unknown")
    chan_pt = row.get("chan_buy_point") or row.get("chan_sell_point") or "unknown_point"
    vol_state = "vol_conf" if row.get("volume_confirmed") else "vol_unconf"
    pattern = f"{chan_pt}/{vol_state}"
    entry_rule = row.get("entry_rule", "unknown")
    return (cat, pattern, band, entry_rule)


def audit(outcomes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run Empirical Bayes audit and generate action items.

    Returns (stats, actions).
    """
    grouped: defaultdict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    all_completed = [r for r in outcomes if r.get("outcome") in {"win", "loss", "flat"}]
    all_wins = [r for r in all_completed if r.get("outcome") == "win"]
    prior_win_rate = len(all_wins) / len(all_completed) if all_completed else 0.50

    for row in outcomes:
        grouped[key_for(row)].append(row)

    stats: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []

    for key, rows in sorted(grouped.items()):
        completed = [r for r in rows if r.get("outcome") in {"win", "loss", "flat"}]
        wins = [r for r in completed if r.get("outcome") == "win"]
        n = len(completed)
        win_rate = len(wins) / n if n else None
        shrunk_win_rate = (
            round((len(wins) + 5.0 * prior_win_rate) / (n + 5.0), 4) if n else None
        )
        b_waves = {r.get("b_wave") for r in completed if r.get("b_wave")}

        status = "observe" if n < 5 else ("shrunk_eval" if n < 10 else "evaluated")
        eval_win_rate = shrunk_win_rate if n < 10 else win_rate

        item: dict[str, Any] = {
            "catalyst_type": key[0],
            "pattern_l2": key[1],
            "confidence_band": key[2],
            "entry_rule": key[3],
            "sample": n,
            "wins": len(wins),
            "win_rate": round(win_rate, 4) if win_rate is not None else None,
            "shrunk_win_rate": shrunk_win_rate,
            "avg_mfe": round(sum(pct_value(r.get("mfe", 0)) for r in completed) / n, 4) if n else None,
            "avg_mae": round(sum(pct_value(r.get("mae", 0)) for r in completed) / n, 4) if n else None,
            "b_wave_counts": {
                wave: sum(1 for r in completed if r.get("b_wave") == wave)
                for wave in sorted(b_waves)
            },
            "status": status,
        }
        stats.append(item)

        # P1: sustained low win rate (>=5 samples, eval < 40%)
        if n >= 5 and eval_win_rate is not None and eval_win_rate < 0.40:
            actions.append({
                "priority": "P1",
                "rule": f"{key[0]} / {key[1]} / {key[2]}",
                "action": "confidence -0.10 next round; do not pause until a second consecutive audit remains below 40%",
                "owner": "strategy",
                "verification": "recompute from candidate_outcome records after next trading round",
                "status": "open",
            })

        # 优化：仅对单边恶性重伤（真实买入单亏损 <= -9.0% 跌停割肉）进行置信度提升预警
        is_sell_defense = any(s in key[0].lower() for s in ["sell", "stop_loss", "exit"])
        if not is_sell_defense:
            severe_loss_trades = [
                r for r in completed
                if r.get("outcome") == "loss"
                and str(r.get("direction", "")).lower() == "buy"
                and pct_value(r.get("pnl_pct", 0)) <= -9.0
            ]
            if severe_loss_trades:
                worst = min(severe_loss_trades, key=lambda x: pct_value(x.get("pnl_pct", 0)))
                pnl_val = pct_value(worst.get("pnl_pct", 0))
                actions.append({
                    "priority": "P1",
                    "rule": f"{key[0]} / {key[1]} / {key[2]}",
                    "action": f"单笔异常大幅回撤(亏损 {pnl_val}%): 提升置信度门槛+0.05并动态降半仓试错，避免再次遭遇单边跌停",
                    "owner": "strategy",
                    "verification": "adaptive_threshold_tuning",
                    "status": "open",
                })

    return stats, actions


def update_strategy_params(stats: list[dict[str, Any]]) -> None:
    """Update strategy_params.json with state machine transitions."""
    params = load_json(STRATEGY_PARAMS)
    if "catalyst_types" not in params:
        params["catalyst_types"] = {}

    # Aggregate per catalyst_type
    cat_stats: defaultdict[str, dict[str, int]] = defaultdict(lambda: {"sample": 0, "wins": 0})
    for item in stats:
        cat = item.get("catalyst_type")
        if cat:
            cat_stats[cat]["sample"] += item.get("sample", 0)
            cat_stats[cat]["wins"] += item.get("wins", 0)

    # Get current market sentiment phase
    market_phase = params.get("sentiment", {}).get("phase", "warmup")
    is_adverse_regime = market_phase in ("cooldown", "ice")

    all_cats = set(params["catalyst_types"].keys()) | set(cat_stats.keys())
    for cat in all_cats:
        cdata = cat_stats.get(cat, {"sample": 0, "wins": 0})
        sample = cdata["sample"]
        wins = cdata["wins"]
        win_rate = round(wins / sample, 4) if sample > 0 else None
        shrunk_rate = round((wins + 5.0 * 0.50) / (sample + 5.0), 4) if sample > 0 else None

        is_defensive = any(s in cat.lower() for s in ["sell", "stop_loss", "exit"])

        if cat not in params["catalyst_types"]:
            params["catalyst_types"][cat] = {
                "enabled": True,
                "min_confidence": 0.65,
                "win_rate": win_rate,
                "shrunk_win_rate": shrunk_rate,
                "sample_count": sample,
                "cooldown_until": None,
            }
        else:
            if sample > 0:
                params["catalyst_types"][cat]["sample_count"] = sample
                params["catalyst_types"][cat]["win_rate"] = win_rate
                params["catalyst_types"][cat]["shrunk_win_rate"] = shrunk_rate

        # 状态机迁移逻辑（单分类样本<10时使用先验平滑胜率，防止过拟合误杀）
        eval_rate = shrunk_rate if sample < 10 else win_rate

        # 卖出防守/止损战法：绝对保持常开，严禁任何形式的 cooldown
        if is_defensive:
            params["catalyst_types"][cat]["enabled"] = True
            params["catalyst_types"][cat]["cooldown_until"] = None
            continue

        # 核心改进：废除"单笔止损就锁死7天"的不合理机制
        if sample >= 10 and eval_rate is not None and eval_rate < 0.35 and not is_adverse_regime:
            params["catalyst_types"][cat]["enabled"] = True
            params["catalyst_types"][cat]["min_confidence"] = min(0.85, 0.75)
            params["catalyst_types"][cat]["cooldown_until"] = None
            params["catalyst_types"][cat]["position_scale"] = 0.5
        elif sample < 10 or is_adverse_regime:
            params["catalyst_types"][cat]["enabled"] = True
            params["catalyst_types"][cat]["cooldown_until"] = None
            cur_conf = params["catalyst_types"][cat].get("min_confidence", 0.65)
            if cur_conf > 0.75:
                params["catalyst_types"][cat]["min_confidence"] = 0.70
        elif eval_rate is not None and eval_rate >= 0.55:
            params["catalyst_types"][cat]["enabled"] = True
            params["catalyst_types"][cat]["cooldown_until"] = None
            params["catalyst_types"][cat]["position_scale"] = 1.0
        else:
            params["catalyst_types"][cat]["enabled"] = True
            params["catalyst_types"][cat]["cooldown_until"] = None

    params["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    save_json(STRATEGY_PARAMS, params)


def main() -> dict[str, Any]:
    """Run strategy audit and return the report."""
    today = dt.date.today().isoformat()
    outcomes = read_outcomes()
    stats, actions = audit(outcomes)
    real_count = sum(1 for o in outcomes if o.get("record_type") == "candidate_outcome")
    shadow_count = sum(1 for o in outcomes if o.get("record_type") in {"shadow_outcome", "shadow_candidate"})

    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "date": today,
        "outcome_samples": len(outcomes),
        "real_samples": real_count,
        "shadow_samples": shadow_count,
        "stats": stats,
        "action_items": actions,
    }

    evo_path = REVIEWS_DIR / f"evolution_{today}.md"
    tmp = evo_path.with_suffix(".md.tmp")
    tmp.write_text(
        f"# Strategy Evolution Audit {today}\n\n{json.dumps(report, ensure_ascii=False, indent=2)}",
        encoding="utf-8",
    )
    tmp.replace(evo_path)

    # 更新 strategy_params
    try:
        update_strategy_params(stats)
    except Exception as e:
        print(f"Error updating strategy_params.json: {e}")

    # 写回送记录
    if actions:
        STRATEGY_FEEDBACK.parent.mkdir(parents=True, exist_ok=True)
        with STRATEGY_FEEDBACK.open("a", encoding="utf-8") as handle:
            handle.write(f"\n## Evolution audit {today}\n")
            for action in actions:
                handle.write(f"- {json.dumps(action, ensure_ascii=False)}\n")

    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == "__main__":
    main()
