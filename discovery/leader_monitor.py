"""龙头 + 持仓监控器 — 追踪连板龙头标的，三档离场信号."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from mcp_client import get_mcp_client


def monitor_leaders() -> dict:
    """Scan ladder + watchlist and build a leadership snapshot.

    Returns:
        dict with keys:
          leaders: list of leader dicts with entry/exit metadata
          positions: current open positions with exit triggers checked
          signals: aggregate summary of exit signals fired
    """
    client = get_mcp_client()

    # ── Fetch ladder — high-board stocks are leaders ──
    ladder_raw: Any = client.get_limitup_ladder(min_streak=2)
    ladder: list[dict] = []
    if isinstance(ladder_raw, list):
        ladder = ladder_raw
    elif isinstance(ladder_raw, dict):
        ladder = ladder_raw.get("ladder", ladder_raw.get("items", []))

    leaders: list[dict] = []
    for entry in ladder:
        symbol = str(entry.get("股票代码", entry.get("code", entry.get("symbol", ""))))
        name = str(entry.get("股票简称", entry.get("name", "")))
        boards = int(entry.get("连板数", entry.get("boards", entry.get("streak", 0))))
        if not symbol:
            continue
        leaders.append({
            "symbol": symbol,
            "name": name,
            "boards": boards,
            "source": "ladder",
            "entry_price": _safe_float(entry, ("封单金额", "sealing_amount")),
            "current_price": 0.0,
            "highest_price": 0.0,
            "pnl_pct": 0.0,
        })

    # ── Fetch positions from exec server ──
    positions: list[dict] = []
    try:
        positions_raw = client.get_positions()
        if isinstance(positions_raw, list):
            positions = positions_raw
        elif isinstance(positions_raw, dict):
            positions = positions_raw.get("positions", positions_raw.get("data", []))
    except Exception as exc:
        print(f"[WARN] Failed to fetch positions: {exc}")

    current_positions: list[dict] = []
    for pos in positions:
        symbol = str(pos.get("code", pos.get("symbol", pos.get("stock_code", ""))))
        if not symbol:
            continue

        cost = _safe_float(pos, ("cost_price", "cost", "avg_price", "avg_cost"))
        volume = int(pos.get("volume", pos.get("quantity", pos.get("amount", 0))))
        current_price = _safe_float(pos, ("current_price", "price", "last_price", "market_value"))

        highest_price = _safe_float(pos, ("highest_price", "high"))
        if highest_price <= 0:
            highest_price = current_price

        entry_time = pos.get("entry_time", pos.get("open_time", ""))
        pnl_pct = ((current_price - cost) / cost * 100) if cost > 0 else 0.0

        position_entry: dict[str, Any] = {
            "symbol": symbol,
            "name": str(pos.get("name", pos.get("stock_name", ""))),
            "cost": cost,
            "volume": volume,
            "current_price": current_price,
            "highest_price": highest_price,
            "pnl_pct": round(pnl_pct, 2),
            "entry_time": entry_time,
        }

        exit_signal = check_exit_triggers(position_entry, current_price)
        position_entry["exit_signal"] = exit_signal
        current_positions.append(position_entry)

    # ── Aggregate signals ──
    signals = {
        "trailing_stop": sum(1 for p in current_positions if p.get("exit_signal") == "trailing_stop"),
        "hard_stop_loss": sum(1 for p in current_positions if p.get("exit_signal") == "hard_stop_loss"),
        "time_exit": sum(1 for p in current_positions if p.get("exit_signal") == "time_exit"),
        "hold": sum(1 for p in current_positions if p.get("exit_signal") is None),
    }

    return {
        "leaders": leaders,
        "positions": current_positions,
        "signals": signals,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def check_exit_triggers(position: dict, current_price: float) -> str | None:
    """Evaluate 3-tier exit rules for a position.

    Tier 1 — Trailing stop-profit (锁盈):
        If price falls >= 5% from highest since entry, signal 'trailing_stop'.

    Tier 2 — Hard stop-loss (止损):
        If PnL <= -7%, signal 'hard_stop_loss'.

    Tier 3 — Time-based exit (时间止损):
        If held > 10 trading days and PnL < 3%, signal 'time_exit'.

    Returns:
        'trailing_stop' | 'hard_stop_loss' | 'time_exit' | None (hold).
    """
    cost = position.get("cost", 0.0)
    highest = position.get("highest_price", current_price)
    entry_time = position.get("entry_time", "")
    pnl_pct = position.get("pnl_pct", 0.0)

    if cost <= 0 or current_price <= 0:
        return None

    # Tier 1: trailing stop-profit
    if highest > cost * 1.03:
        drawdown = (highest - current_price) / highest * 100
        if drawdown >= 5.0:
            return "trailing_stop"

    # Tier 2: hard stop-loss
    if pnl_pct <= -7.0:
        return "hard_stop_loss"

    # Tier 3: time-based exit
    if entry_time:
        try:
            entry_dt = datetime.fromisoformat(entry_time)
            days_held = (datetime.now() - entry_dt).days
            if days_held > 10 and pnl_pct < 3.0:
                return "time_exit"
        except (ValueError, TypeError):
            pass

    return None


def _safe_float(row: dict, keys: tuple[str, ...]) -> float:
    for k in keys:
        v = row.get(k)
        if v is not None:
            try:
                return float(v)
            except (ValueError, TypeError):
                continue
    return 0.0


if __name__ == "__main__":
    snapshot = monitor_leaders()
    leaders = snapshot["leaders"]
    positions = snapshot["positions"]
    signals = snapshot["signals"]

    print(f"Leader monitor snapshot @ {snapshot['updated_at']}\n")

    print(f"Leaders from ladder ({len(leaders)}):")
    for ld in leaders[:10]:
        print(f"  {ld['symbol']} {ld['name']} {ld['boards']}板")

    print(f"\nPositions ({len(positions)}):")
    for pos in positions:
        signal = pos.get("exit_signal") or "hold"
        print(
            f"  {pos['symbol']} {pos['name']:<10} "
            f"pnl={pos['pnl_pct']:+.2f}% "
            f"signal={signal}"
        )

    print(f"\nSignals: trailing_stop={signals['trailing_stop']} "
          f"hard_stop={signals['hard_stop_loss']} "
          f"time_exit={signals['time_exit']} "
          f"hold={signals['hold']}")
