"""Decision event contract for next-day-open backtest.

Every decision has strictly separated:
- signal_date (T-1): when the decision was made
- execution_date (T): when the trade executes at open
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class DecisionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class ExecutionStatus(str, Enum):
    PENDING = "PENDING"  # Signal generated, awaiting execution
    EXECUTED = "EXECUTED"  # Filled at open
    BLOCKED_SUSPENDED = "BLOCKED_SUSPENDED"  # Volume=0, position persists
    BLOCKED_LIMIT_UP = "BLOCKED_LIMIT_UP"  # Buy at limit-up, blocked
    BLOCKED_LIMIT_DOWN = "BLOCKED_LIMIT_DOWN"  # Sell at limit-down, blocked
    BLOCKED_T1 = "BLOCKED_T1"  # Same-day buy → sell blocked
    CANCELLED = "CANCELLED"  # Decision cancelled (e.g. signal reversed)
    FAILED = "FAILED"  # Other failure


@dataclass
class DecisionEvent:
    """A single trading decision with strict signal/execution separation.

    signal_date = T-1 (when the decision was made using T-1 close data)
    execution_date = T (when the trade executes at T open)

    For BUY: signal_date = T-1, execution_date = T
    For SELL: signal_date = T-1 (signal detection date), execution_date = T
    """

    signal_date: str  # T-1: when decision was made
    execution_date: str  # T: when decision executes
    symbol: str
    decision_type: DecisionType
    decision_price: float  # The target/signal price (from T-1 data)
    execution_price: Optional[float] = None  # Actual fill price (set after execution)
    quantity: int = 0
    score: float = 0.0  # Strategy score at decision time
    grade: str = ""  # Signal grade (A/B/C/D)
    reason: str = ""  # Human-readable reason

    # Market context at decision time (T-1)
    market_regime_phase: str = ""
    market_regime_multiplier: float = 0.0
    sector: str = ""

    # Execution result
    execution_status: ExecutionStatus = ExecutionStatus.PENDING
    fill_price: Optional[float] = None  # Actual execution price
    fill_time: Optional[str] = None  # Execution timestamp
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    hold_days: Optional[int] = None

    # Data snapshot reference (lightweight — only key fields)
    data_snapshot_ref: dict[str, Any] = field(default_factory=dict)

    def mark_executed(self, fill_price: float, fill_time: str) -> None:
        self.execution_status = ExecutionStatus.EXECUTED
        self.fill_price = fill_price
        self.fill_time = fill_time

    def mark_blocked(self, status: ExecutionStatus) -> None:
        self.execution_status = status

    def record_pnl(self, pnl: float, pnl_pct: float, hold_days: int) -> None:
        self.pnl = pnl
        self.pnl_pct = pnl_pct
        self.hold_days = hold_days

    @property
    def is_buy(self) -> bool:
        return self.decision_type == DecisionType.BUY

    @property
    def is_sell(self) -> bool:
        return self.decision_type == DecisionType.SELL

    @property
    def is_executed(self) -> bool:
        return self.execution_status == ExecutionStatus.EXECUTED

    @property
    def signal_to_execution_gap(self) -> int:
        """Days between signal and execution (should be 1 for next-day-open)."""
        from datetime import date
        sd = date.fromisoformat(self.signal_date)
        ed = date.fromisoformat(self.execution_date)
        return (ed - sd).days

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_date": self.signal_date,
            "execution_date": self.execution_date,
            "symbol": self.symbol,
            "decision_type": self.decision_type.value,
            "decision_price": self.decision_price,
            "execution_price": self.execution_price,
            "quantity": self.quantity,
            "score": self.score,
            "grade": self.grade,
            "reason": self.reason,
            "market_regime_phase": self.market_regime_phase,
            "market_regime_multiplier": self.market_regime_multiplier,
            "sector": self.sector,
            "execution_status": self.execution_status.value,
            "fill_price": self.fill_price,
            "pnl": self.pnl,
            "pnl_pct": self.pnl_pct,
            "hold_days": self.hold_days,
        }
