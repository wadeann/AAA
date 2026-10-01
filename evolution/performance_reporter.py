#!/usr/bin/env python3
"""Persist daily MCP simulation-account snapshots and report weekly/monthly returns.

Replaces the legacy account_performance_report.py — all MCP via MCPClient,
persistence via DataManager, no hardcoded paths.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from config import STATE_DIR
from data import get_data_manager
from mcp_client import get_mcp_client

SNAPSHOT_FILE = "account_snapshots.jsonl"


def _load_rows() -> list[dict[str, Any]]:
    """Load all historical snapshot rows from the state JSONL file."""
    dm = get_data_manager()
    path = dm.state_dir / SNAPSHOT_FILE
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = __import__("json").loads(line)
            if isinstance(row, dict) and row.get("total_assets") is not None:
                rows.append(row)
        except __import__("json").JSONDecodeError:
            pass
    return rows


def _save_rows(rows: list[dict[str, Any]]) -> None:
    """Atomically write all rows to the JSONL snapshot file."""
    dm = get_data_manager()
    dm.state_dir.mkdir(parents=True, exist_ok=True)
    path = dm.state_dir / SNAPSHOT_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        "".join(
            __import__("json").dumps(r, ensure_ascii=False, sort_keys=True) + "\n"
            for r in rows
        ),
        encoding="utf-8",
    )
    tmp.replace(path)


def main() -> dict[str, Any]:
    """Fetch account state, persist snapshot, compute MDD and period returns.

    Returns the report dict for downstream use.
    """
    today = dt.date.today().isoformat()
    client = get_mcp_client()

    balance = client.get_balance()
    positions = client.get_positions()
    trades = client.get_today_trades()
    pnl = client.daily_pnl()

    position_count = 0
    if isinstance(positions, dict):
        position_count = len(positions.get("positions", positions.get("value", [])))
    elif isinstance(positions, list):
        position_count = len(positions)

    trade_count = 0
    if isinstance(trades, dict):
        trade_count = len(trades.get("trades", trades.get("data", [])))
    elif isinstance(trades, list):
        trade_count = len(trades)

    row: dict[str, Any] = {
        "date": today,
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "cash": float(balance.get("cash", 0)),
        "total_assets": float(balance.get("total_assets", 0)),
        "total_pnl": float(balance.get("total_pnl", 0)),
        "total_pnl_pct": float(balance.get("total_pnl_pct", 0)),
        "position_count": position_count,
        "trade_count": trade_count,
        "daily_pnl": pnl,
    }

    rows = [r for r in _load_rows() if r.get("date") != today]
    rows.append(row)

    # 计算历史最大回撤 (MDD)
    all_assets = [r["total_assets"] for r in rows if r.get("total_assets", 0) > 0]
    mdd = 0.0
    peak = 0.0
    for a in all_assets:
        if a > peak:
            peak = a
        dd = (peak - a) / peak * 100 if peak > 0 else 0
        if dd > mdd:
            mdd = dd
    row["max_drawdown_pct"] = round(mdd, 2)

    # 周/月收益
    now = dt.date.today()
    week_start = now - dt.timedelta(days=now.weekday())
    month_start = now.replace(day=1)

    def _base(start: dt.date) -> float:
        prior = [r for r in rows if dt.date.fromisoformat(r["date"]) < start]
        return prior[-1]["total_assets"] if prior else rows[0]["total_assets"]

    week_base = _base(week_start)
    month_base = _base(month_start)
    week_return = (row["total_assets"] - week_base) / week_base * 100 if week_base else 0
    month_return = (row["total_assets"] - month_base) / month_base * 100 if month_base else 0

    _save_rows(rows)

    report = {
        "total_assets": row["total_assets"],
        "total_pnl": row["total_pnl"],
        "total_pnl_pct": row["total_pnl_pct"],
        "max_drawdown_pct": mdd,
        "week_return": round(week_return, 2),
        "month_return": round(month_return, 2),
        "trade_count": trade_count,
        "date": today,
    }

    print(
        f"收益检查 | 账户{row['total_assets']:.2f} | "
        f"累计{row['total_pnl']:+.2f}({row['total_pnl_pct']:+.2f}%) | "
        f"最大回撤{mdd:.2f}%"
    )
    print(
        f"周收益 {row['total_assets'] - week_base:+.2f} ({week_return:+.2f}%) | "
        f"月收益 {row['total_assets'] - month_base:+.2f} ({month_return:+.2f}%) | "
        f"成交{trade_count}笔"
    )

    return report


if __name__ == "__main__":
    main()
