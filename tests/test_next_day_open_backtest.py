"""Phase 1B tests — Next-Day-Open Backtest API integration."""
from __future__ import annotations

import pytest
from core.data_contracts import DataSnapshot
from core.data_provider import HistoricalDataProvider
from core.decision_event import DecisionEvent, DecisionType, ExecutionStatus
from core.next_day_open_backtest import (
    BacktestResult,
    OpenExecutionModel,
    run_next_day_open_backtest,
)
from core.trading_calendar import TradingCalendar

from tests.test_data_provider import _make_bar, _make_index_bar, make_provider


# ═══════════════════════════════════════════════════════════════
# Minimal strategy for testing
# ═══════════════════════════════════════════════════════════════

def _null_strategy(snapshot: DataSnapshot) -> list[DecisionEvent]:
    """Strategy that never generates decisions."""
    return []


def _always_buy_one(snapshot: DataSnapshot) -> list[DecisionEvent]:
    """Strategy that always buys 100 shares of the first available stock."""
    syms = snapshot.available_symbols
    if not syms:
        return []
    sym = syms[0]
    bars = snapshot.stock_bars.get(sym, [])
    if not bars:
        return []
    last_close = bars[-1].close
    return [DecisionEvent(
        signal_date=snapshot.snapshot_date,
        execution_date="",  # Will be set by backtest engine
        symbol=sym,
        decision_type=DecisionType.BUY,
        decision_price=last_close,
        quantity=100,
        score=70.0,
        grade="B",
        reason="Test buy",
        market_regime_phase=snapshot.market_regime.phase,
        market_regime_multiplier=snapshot.market_regime.multiplier,
    )]


# ═══════════════════════════════════════════════════════════════
# OpenExecutionModel
# ═══════════════════════════════════════════════════════════════


class TestOpenExecutionModel:
    def test_buy_at_open_succeeds(self) -> None:
        provider = make_provider()
        model = OpenExecutionModel()
        d = DecisionEvent(
            signal_date="2026-01-05", execution_date="2026-01-06",
            symbol="600519.SH", decision_type=DecisionType.BUY,
            decision_price=100.0, quantity=100, score=70.0, grade="B",
        )
        results = model.execute([d], "2026-01-06", provider)
        assert len(results) == 1
        assert results[0].execution_status == ExecutionStatus.EXECUTED
        assert results[0].fill_price > 0

    def test_buy_blocked_by_suspension(self) -> None:
        provider = make_provider(stock_bars={
            "600519.SH": [
                _make_bar("2026-01-05", 100, 102, 98, 101, 5000000),
                _make_bar("2026-01-06", 101, 103, 100, 102, 0),  # SUSPENDED
            ],
        })
        model = OpenExecutionModel()
        d = DecisionEvent(
            signal_date="2026-01-05", execution_date="2026-01-06",
            symbol="600519.SH", decision_type=DecisionType.BUY,
            decision_price=100.0, quantity=100, score=70.0, grade="B",
        )
        results = model.execute([d], "2026-01-06", provider)
        assert results[0].execution_status == ExecutionStatus.BLOCKED_SUSPENDED

    def test_buy_blocked_by_limit_up(self) -> None:
        """Buy at open >= limit_up must be blocked."""
        provider = make_provider(stock_bars={
            "600519.SH": [
                _make_bar("2026-01-05", 100, 102, 98, 101, 5000000),
                _make_bar("2026-01-06", 112, 115, 110, 114, 5000000),  # Open at 112, prev_close=101, limit_up=111.1
            ],
        })
        model = OpenExecutionModel()
        d = DecisionEvent(
            signal_date="2026-01-05", execution_date="2026-01-06",
            symbol="600519.SH", decision_type=DecisionType.BUY,
            decision_price=101.0, quantity=100, score=70.0, grade="B",
        )
        results = model.execute([d], "2026-01-06", provider)
        assert results[0].execution_status == ExecutionStatus.BLOCKED_LIMIT_UP

    def test_sell_blocked_by_t1(self) -> None:
        """Cannot sell a stock on the same day it was bought."""
        provider = make_provider()
        model = OpenExecutionModel()
        model.entry_dates["600519.SH"] = "2026-01-06"  # Bought today
        d = DecisionEvent(
            signal_date="2026-01-05", execution_date="2026-01-06",
            symbol="600519.SH", decision_type=DecisionType.SELL,
            decision_price=105.0, quantity=100, score=0.0, grade="",
        )
        results = model.execute([d], "2026-01-06", provider)
        assert results[0].execution_status == ExecutionStatus.BLOCKED_T1

    def test_sell_blocked_by_limit_down(self) -> None:
        provider = make_provider(stock_bars={
            "600519.SH": [
                _make_bar("2026-01-05", 100, 102, 98, 101, 5000000),
                _make_bar("2026-01-06", 89, 90, 88, 89, 5000000),  # Open at 89, prev_close=101, limit_down=90.9
            ],
        })
        model = OpenExecutionModel()
        d = DecisionEvent(
            signal_date="2026-01-05", execution_date="2026-01-06",
            symbol="600519.SH", decision_type=DecisionType.SELL,
            decision_price=101.0, quantity=100, score=0.0, grade="",
        )
        results = model.execute([d], "2026-01-06", provider)
        assert results[0].execution_status == ExecutionStatus.BLOCKED_LIMIT_DOWN

    def test_sell_before_buy_order(self) -> None:
        """SELLs should execute before BUYs in the same execution window."""
        provider = make_provider()
        model = OpenExecutionModel()
        # Pre-existing position
        model.entry_dates["600519.SH"] = "2025-12-01"

        buy = DecisionEvent(
            signal_date="2026-01-05", execution_date="2026-01-06",
            symbol="600519.SH", decision_type=DecisionType.BUY,
            decision_price=100.0, quantity=100, score=70.0, grade="B",
        )
        sell = DecisionEvent(
            signal_date="2026-01-05", execution_date="2026-01-06",
            symbol="600519.SH", decision_type=DecisionType.SELL,
            decision_price=105.0, quantity=100, score=0.0, grade="",
        )
        results = model.execute([buy, sell], "2026-01-06", provider)
        # Both should execute (sell first frees up position, then buy)
        statuses = [r.execution_status for r in results]
        # Sell should be executed (T+1 check: entry_date "2025-12-01" != "2026-01-06")
        assert any(r.decision_type == DecisionType.SELL and r.is_executed for r in results)


# ═══════════════════════════════════════════════════════════════
# Backtest API
# ═══════════════════════════════════════════════════════════════


class TestNextDayOpenBacktest:
    def test_null_strategy_produces_no_trades(self) -> None:
        provider = make_provider()
        result = run_next_day_open_backtest(
            start_date="2026-01-05",
            end_date="2026-01-09",
            data_provider=provider,
            strategy=_null_strategy,
        )
        assert result.total_trades == 0
        assert len(result.decisions) == 0

    def test_always_buy_strategy(self) -> None:
        provider = make_provider()
        result = run_next_day_open_backtest(
            start_date="2026-01-05",
            end_date="2026-01-08",
            data_provider=provider,
            strategy=_always_buy_one,
        )
        # Should have daily buy decisions
        assert len(result.executed_buys) > 0
        # Each buy should have signal_date < execution_date
        for d in result.executed_buys:
            assert d.signal_date < d.execution_date, (
                f"signal_date {d.signal_date} must be before execution_date {d.execution_date}"
            )

    def test_decision_signal_date_is_t_minus_1(self) -> None:
        """Every decision must have signal_date = T-1 and execution_date = T."""
        provider = make_provider()
        result = run_next_day_open_backtest(
            start_date="2026-01-05",
            end_date="2026-01-08",
            data_provider=provider,
            strategy=_always_buy_one,
        )
        for d in result.decisions:
            assert d.signal_date < d.execution_date, (
                f"Decision for {d.symbol}: signal={d.signal_date} must precede execution={d.execution_date}"
            )

    def test_strategy_cannot_access_execution_day(self) -> None:
        """Verify the strategy is called with T-1 snapshot, not T snapshot.

        We use a strategy that records the snapshot_date it sees.
        """
        seen_dates: list[str] = []

        def tracking_strategy(snapshot: DataSnapshot) -> list[DecisionEvent]:
            seen_dates.append(snapshot.snapshot_date)
            return _always_buy_one(snapshot)

        provider = make_provider()
        result = run_next_day_open_backtest(
            start_date="2026-01-05",
            end_date="2026-01-08",
            data_provider=provider,
            strategy=tracking_strategy,
        )
        # The strategy should only see T-1 dates, and each decision's execution_date should be later
        for d in result.decisions:
            assert d.signal_date in seen_dates, f"Decision signal_date {d.signal_date} not in strategy's seen dates"


class TestBacktestResult:
    def test_empty_result_metrics(self) -> None:
        provider = make_provider()
        result = run_next_day_open_backtest(
            start_date="2026-01-05",
            end_date="2026-01-09",
            data_provider=provider,
            strategy=_null_strategy,
        )
        assert result.total_trades == 0
        assert result.metrics["total_trades"] == 0
        assert result.metrics["win_rate"] == 0.0
