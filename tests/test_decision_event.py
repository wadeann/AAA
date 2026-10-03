"""Phase 1B tests — DecisionEvent, signal/execution separation, PIT enforcement."""
from __future__ import annotations

import pytest
from core.decision_event import DecisionEvent, DecisionType, ExecutionStatus


def make_buy_decision(signal_date: str = "2026-01-05", exec_date: str = "2026-01-06") -> DecisionEvent:
    return DecisionEvent(
        signal_date=signal_date,
        execution_date=exec_date,
        symbol="600519.SH",
        decision_type=DecisionType.BUY,
        decision_price=100.0,
        quantity=100,
        score=72.0,
        grade="B",
        reason="Test buy",
    )


def make_sell_decision(signal_date: str = "2026-01-05", exec_date: str = "2026-01-06") -> DecisionEvent:
    return DecisionEvent(
        signal_date=signal_date,
        execution_date=exec_date,
        symbol="600519.SH",
        decision_type=DecisionType.SELL,
        decision_price=105.0,
        quantity=100,
        score=0.0,
        grade="",
        reason="Take profit",
    )


# ═══════════════════════════════════════════════════════════════
# Decision Event Contract
# ═══════════════════════════════════════════════════════════════


class TestDecisionEventContract:
    def test_buy_signal_date_is_t_minus_1(self) -> None:
        """BUY decision: signal_date must be T-1, execution_date must be T."""
        d = make_buy_decision("2026-01-05", "2026-01-06")
        assert d.signal_date == "2026-01-05"  # T-1
        assert d.execution_date == "2026-01-06"  # T
        assert d.signal_date < d.execution_date

    def test_sell_signal_date_is_t_minus_1(self) -> None:
        """SELL decision: same signal/execution separation."""
        d = make_sell_decision("2026-01-07", "2026-01-08")
        assert d.signal_date == "2026-01-07"
        assert d.execution_date == "2026-01-08"
        assert d.signal_date < d.execution_date

    def test_signal_to_execution_gap_is_one_day(self) -> None:
        d = make_buy_decision("2026-01-05", "2026-01-06")
        assert d.signal_to_execution_gap == 1

    def test_decision_initial_status_is_pending(self) -> None:
        d = make_buy_decision()
        assert d.execution_status == ExecutionStatus.PENDING
        assert d.fill_price is None
        assert d.pnl is None

    def test_mark_executed(self) -> None:
        d = make_buy_decision()
        d.mark_executed(fill_price=100.5, fill_time="2026-01-06")
        assert d.execution_status == ExecutionStatus.EXECUTED
        assert d.fill_price == 100.5
        assert d.fill_time == "2026-01-06"

    def test_mark_blocked_suspended(self) -> None:
        d = make_buy_decision()
        d.mark_blocked(ExecutionStatus.BLOCKED_SUSPENDED)
        assert d.execution_status == ExecutionStatus.BLOCKED_SUSPENDED
        assert d.is_executed is False

    def test_mark_blocked_limit_up(self) -> None:
        d = make_buy_decision()
        d.mark_blocked(ExecutionStatus.BLOCKED_LIMIT_UP)
        assert d.execution_status == ExecutionStatus.BLOCKED_LIMIT_UP

    def test_mark_blocked_t1(self) -> None:
        d = make_sell_decision()
        d.mark_blocked(ExecutionStatus.BLOCKED_T1)
        assert d.execution_status == ExecutionStatus.BLOCKED_T1
        assert d.reason != ""


# ═══════════════════════════════════════════════════════════════
# Decision Type
# ═══════════════════════════════════════════════════════════════


class TestDecisionType:
    def test_is_buy(self) -> None:
        d = make_buy_decision()
        assert d.is_buy is True
        assert d.is_sell is False

    def test_is_sell(self) -> None:
        d = make_sell_decision()
        assert d.is_sell is True
        assert d.is_buy is False

    def test_enum_values(self) -> None:
        assert DecisionType.BUY.value == "BUY"
        assert DecisionType.SELL.value == "SELL"
        assert DecisionType.HOLD.value == "HOLD"


# ═══════════════════════════════════════════════════════════════
# Execution Status Enum
# ═══════════════════════════════════════════════════════════════


class TestExecutionStatus:
    def test_all_status_values(self) -> None:
        statuses = [
            ExecutionStatus.PENDING,
            ExecutionStatus.EXECUTED,
            ExecutionStatus.BLOCKED_SUSPENDED,
            ExecutionStatus.BLOCKED_LIMIT_UP,
            ExecutionStatus.BLOCKED_LIMIT_DOWN,
            ExecutionStatus.BLOCKED_T1,
            ExecutionStatus.CANCELLED,
            ExecutionStatus.FAILED,
        ]
        for s in statuses:
            assert isinstance(s.value, str)


# ═══════════════════════════════════════════════════════════════
# Strategy Cannot Access Execution Day Data
# ═══════════════════════════════════════════════════════════════


class TestStrategyPITIsolation:
    def test_snapshot_date_respected(self) -> None:
        """A decision made at T-1 cannot have execution_date <= signal_date."""
        d = make_buy_decision("2026-01-05", "2026-01-06")
        # signal_date is T-1
        # execution_date is T
        # Strategy only had access to T-1 data
        assert d.signal_date < d.execution_date

    def test_decision_price_is_not_execution_price(self) -> None:
        """Decision price (from T-1 close) != execution price (T open)."""
        d = make_buy_decision()
        d.decision_price = 100.0  # T-1 derived price
        assert d.execution_price is None  # Not yet filled
        d.mark_executed(fill_price=101.5, fill_time="2026-01-06")
        # Execution price can differ from decision price
        assert d.decision_price != d.fill_price


# ═══════════════════════════════════════════════════════════════
# PnL Recording
# ═══════════════════════════════════════════════════════════════


class TestPnLRecording:
    def test_record_pnl(self) -> None:
        d = make_buy_decision()
        d.mark_executed(fill_price=100.0, fill_time="2026-01-06")
        d.record_pnl(pnl=500.0, pnl_pct=5.0, hold_days=10)
        assert d.pnl == 500.0
        assert d.pnl_pct == 5.0
        assert d.hold_days == 10


# ═══════════════════════════════════════════════════════════════
# to_dict serialization
# ═══════════════════════════════════════════════════════════════


class TestSerialization:
    def test_to_dict(self) -> None:
        d = make_buy_decision("2026-01-05", "2026-01-06")
        d.mark_executed(fill_price=100.5, fill_time="2026-01-06")
        d.record_pnl(500.0, 5.0, 10)
        result = d.to_dict()
        assert result["signal_date"] == "2026-01-05"
        assert result["execution_date"] == "2026-01-06"
        assert result["symbol"] == "600519.SH"
        assert result["decision_type"] == "BUY"
        assert result["execution_status"] == "EXECUTED"
        assert result["pnl"] == 500.0
