"""Next-Day-Open Backtest API — Phase 1B minimal PIT-safe backtest.

Implements the canonical T-1→T decision→execution loop:

    T-1 close → snapshot → strategy.decide() → T open → execution

Core guarantee: strategy.decide() cannot access T-day data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from core.data_contracts import (
    DataAvailability,
    DataSnapshot,
    StockDailyBar,
    TradeStatus,
)
from core.data_provider import HistoricalDataProvider
from core.decision_event import DecisionEvent, DecisionType, ExecutionStatus
from core.trading_calendar import TradingCalendar


# ═══════════════════════════════════════════════════════════════
# Strategy Protocol
# ═══════════════════════════════════════════════════════════════

# A strategy is a callable that takes a DataSnapshot (T-1 close state)
# and returns a list of DecisionEvents.
# It MUST NOT access any data not contained in the snapshot.
Strategy = Callable[[DataSnapshot], list[DecisionEvent]]


# ═══════════════════════════════════════════════════════════════
# Execution Model
# ═══════════════════════════════════════════════════════════════


@dataclass
class OpenExecutionModel:
    """Execute decisions at the next trading day's open price.

    Enforces:
    - Buy at D+1 open (D = signal_date)
    - Sell at D+1 open (D = signal_date)
    - Limit-up/down blocking
    - Suspension blocking
    - T+1 enforcement for sells (can't sell same day as buy)
    """

    # Existing position tracking for T+1 enforcement
    entry_dates: dict[str, str] = field(default_factory=dict)  # symbol → entry_date
    positions: dict[str, dict[str, Any]] = field(default_factory=dict)

    def execute(
        self,
        decisions: list[DecisionEvent],
        execution_date: str,
        data_provider: HistoricalDataProvider,
    ) -> list[DecisionEvent]:
        """Execute decisions at `execution_date` open.

        Returns the executed (or blocked) decision events.
        """
        results: list[DecisionEvent] = []

        # ── First: execute SELLs (free up cash/positions before buys) ──
        sell_decisions = [d for d in decisions if d.decision_type == DecisionType.SELL]
        buy_decisions = [d for d in decisions if d.decision_type == DecisionType.BUY]

        for d in sell_decisions:
            result = self._execute_one(d, execution_date, data_provider)
            results.append(result)

        for d in buy_decisions:
            result = self._execute_one(d, execution_date, data_provider)
            if result.execution_status == ExecutionStatus.EXECUTED:
                self.entry_dates[result.symbol] = execution_date
            results.append(result)

        return results

    def _execute_one(
        self,
        decision: DecisionEvent,
        execution_date: str,
        data_provider: HistoricalDataProvider,
    ) -> DecisionEvent:
        """Execute a single decision at open. Returns the updated event."""
        sym = decision.symbol

        # Get execution-day bar
        bars, avail = data_provider.get_stock_daily(sym, execution_date, min_bars=1)
        if avail == DataAvailability.UNAVAILABLE or not bars:
            decision.mark_blocked(ExecutionStatus.FAILED)
            decision.reason = f"No data for {execution_date}"
            return decision

        bar = bars[-1]
        if bar.trade_date != execution_date:
            decision.mark_blocked(ExecutionStatus.FAILED)
            decision.reason = f"No bar for execution date {execution_date}"
            return decision

        open_price = bar.open

        # Suspension check
        if bar.is_suspended:
            decision.mark_blocked(ExecutionStatus.BLOCKED_SUSPENDED)
            decision.reason = f"Suspended on {execution_date}"
            return decision

        # Get trade status for limit checks
        status = data_provider.get_trade_status(sym, execution_date)

        if decision.decision_type == DecisionType.BUY:
            # Limit-up check
            if status.limit_up_price is not None and open_price >= status.limit_up_price:
                decision.mark_blocked(ExecutionStatus.BLOCKED_LIMIT_UP)
                decision.reason = f"Limit-up: open {open_price} >= {status.limit_up_price}"
                return decision

        elif decision.decision_type == DecisionType.SELL:
            # T+1 check
            entry_date = self.entry_dates.get(sym)
            if entry_date == execution_date:
                decision.mark_blocked(ExecutionStatus.BLOCKED_T1)
                decision.reason = f"T+1: bought on {entry_date}, cannot sell same day"
                return decision

            # Limit-down check
            if status.limit_down_price is not None and open_price <= status.limit_down_price:
                decision.mark_blocked(ExecutionStatus.BLOCKED_LIMIT_DOWN)
                decision.reason = f"Limit-down: open {open_price} <= {status.limit_down_price}"
                return decision

        # Execute at open
        decision.mark_executed(fill_price=open_price, fill_time=execution_date)
        decision.execution_price = open_price
        return decision


# ═══════════════════════════════════════════════════════════════
# Next-Day-Open Backtest
# ═══════════════════════════════════════════════════════════════


@dataclass
class BacktestResult:
    """Results from a next-day-open backtest run."""

    decisions: list[DecisionEvent]  # All decisions (buy + sell)
    executed_buys: list[DecisionEvent]
    executed_sells: list[DecisionEvent]
    blocked: list[DecisionEvent]
    daily_equity: list[dict[str, Any]]
    metrics: dict[str, Any]

    @property
    def total_trades(self) -> int:
        return len(self.executed_sells)

    @property
    def win_rate(self) -> float:
        if not self.executed_sells:
            return 0.0
        wins = [s for s in self.executed_sells if (s.pnl or 0) > 0]
        return len(wins) / len(self.executed_sells) * 100


def run_next_day_open_backtest(
    start_date: str,
    end_date: str,
    data_provider: HistoricalDataProvider,
    strategy: Strategy,
    execution_model: OpenExecutionModel | None = None,
    initial_capital: float = 400000.0,
) -> BacktestResult:
    """Run a PIT-safe next-day-open backtest.

    For each T-1 trading day:
    1. Build PIT data snapshot at T-1 close
    2. Call strategy.decide(snapshot) → generates decisions
    3. Set execution_date = next_trading_day(T-1)
    4. Execute all decisions at T open

    Strategy never sees T-day data.

    Args:
        start_date: First T-1 decision date (YYYY-MM-DD)
        end_date: Last T-1 decision date (YYYY-MM-DD)
        data_provider: PIT-safe data provider
        strategy: callable(DataSnapshot) → list[DecisionEvent]
        execution_model: OpenExecutionModel or None (creates default)
        initial_capital: Starting capital

    Returns:
        BacktestResult with all decisions and metrics
    """
    calendar = data_provider._calendar

    if execution_model is None:
        execution_model = OpenExecutionModel()

    all_decisions: list[DecisionEvent] = []
    all_buys: list[DecisionEvent] = []
    all_sells: list[DecisionEvent] = []
    all_blocked: list[DecisionEvent] = []

    # Get the universe from the data provider
    universe = list(data_provider._stock_bars_all.keys())

    # Trading dates within [start_date, end_date]
    trade_dates = [d for d in calendar.dates if start_date <= d <= end_date]

    daily_equity: list[dict[str, Any]] = []
    cash = initial_capital
    positions: dict[str, dict[str, Any]] = {}

    for t_minus_1 in trade_dates:
        # T = next trading day
        t_day = calendar.next_trading_day(t_minus_1)
        if t_day is None:
            break  # Can't execute if no next trading day

        # ── 1. Build PIT snapshot at T-1 close ──
        snapshot = data_provider.snapshot(t_minus_1, universe)

        # ── 2. Strategy decides using ONLY snapshot data ──
        decisions = strategy(snapshot)

        # Validate: decision signal_date must be T-1
        for d in decisions:
            d.signal_date = t_minus_1  # Enforce T-1 signal date
            d.execution_date = t_day  # Enforce T execution date

        # ── 3. Execute at T open ──
        results = execution_model.execute(decisions, t_day, data_provider)

        for d in results:
            all_decisions.append(d)
            if d.is_executed:
                if d.decision_type == DecisionType.BUY:
                    all_buys.append(d)
                elif d.decision_type == DecisionType.SELL:
                    all_sells.append(d)
            else:
                all_blocked.append(d)

        # ── Track equity ──
        daily_equity.append({
            "signal_date": t_minus_1,
            "execution_date": t_day,
            "decisions": len(decisions),
            "executed": sum(1 for d in results if d.is_executed),
            "blocked": sum(1 for d in results if not d.is_executed),
        })

    # ── Compute metrics ──
    metrics = _compute_metrics(all_sells, daily_equity, initial_capital)

    return BacktestResult(
        decisions=all_decisions,
        executed_buys=all_buys,
        executed_sells=all_sells,
        blocked=all_blocked,
        daily_equity=daily_equity,
        metrics=metrics,
    )


def _compute_metrics(
    sells: list[DecisionEvent],
    daily_equity: list[dict[str, Any]],
    initial_capital: float,
) -> dict[str, Any]:
    """Compute standard backtest metrics."""
    if not sells:
        return {
            "total_trades": 0, "win_rate": 0.0, "profit_factor": 0.0,
            "total_pnl": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "avg_hold_days": 0.0,
        }

    wins = [s for s in sells if (s.pnl or 0) > 0]
    losses = [s for s in sells if (s.pnl or 0) <= 0]
    wr = len(wins) / len(sells) * 100
    total_pnl = sum(s.pnl or 0 for s in sells)
    tp = sum(s.pnl or 0 for s in wins) if wins else 0
    tl = abs(sum(s.pnl or 0 for s in losses)) if losses else 1
    pf = tp / tl if tl > 0 else 0.0
    avg_win = tp / len(wins) if wins else 0.0
    avg_loss = -tl / len(losses) if losses else 0.0
    avg_hold = sum(s.hold_days or 0 for s in sells) / len(sells) if sells else 0.0

    return {
        "total_trades": len(sells),
        "win_rate": round(wr, 1),
        "profit_factor": round(pf, 2),
        "total_pnl": round(total_pnl, 2),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "avg_hold_days": round(avg_hold, 0),
    }
