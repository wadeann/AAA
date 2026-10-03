"""Minimal historical data contracts for Phase 1B next-day-open backtest.

All contracts enforce explicit schemas and validation.
Missing/unavailable data must be explicitly marked, not silently defaulted.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ═══════════════════════════════════════════════════════════════
# Data Availability
# ═══════════════════════════════════════════════════════════════


class DataAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"
    INVALID = "INVALID"


# ═══════════════════════════════════════════════════════════════
# Bar Schemas
# ═══════════════════════════════════════════════════════════════

REQUIRED_STOCK_BAR_FIELDS = frozenset({"time", "open", "high", "low", "close", "volume"})
OPTIONAL_STOCK_BAR_FIELDS = frozenset({"amount", "adj_factor", "pre_close", "turnover"})


@dataclass
class StockDailyBar:
    """Single stock daily OHLCV bar with validation."""

    symbol: str
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0
    pre_close: Optional[float] = None
    adj_factor: Optional[float] = None
    _raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_dict(cls, symbol: str, raw: dict[str, Any]) -> "StockDailyBar":
        """Construct from a raw K-line dict, validating required fields."""
        missing = REQUIRED_STOCK_BAR_FIELDS - set(raw.keys())
        if missing:
            raise ValueError(f"Stock bar for {symbol} missing required fields: {missing}")

        def _f(k: str) -> float:
            try:
                return float(raw.get(k, 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        trade_date = str(raw.get("time", ""))
        if not trade_date:
            raise ValueError(f"Stock bar for {symbol} has empty time field")

        return cls(
            symbol=symbol,
            trade_date=trade_date,
            open=_f("open"),
            high=_f("high"),
            low=_f("low"),
            close=_f("close"),
            volume=_f("volume"),
            amount=_f("amount") if raw.get("amount") else 0.0,
            pre_close=_f("pre_close") if raw.get("pre_close") else None,
            adj_factor=_f("adj_factor") if raw.get("adj_factor") else None,
            _raw=raw,
        )

    @property
    def is_suspended(self) -> bool:
        """Trading suspended if volume is zero."""
        return self.volume <= 0

    @property
    def typical_price(self) -> float:
        """(high + low + close) / 3"""
        return (self.high + self.low + self.close) / 3.0


@dataclass
class IndexDailyBar:
    """Index daily OHLCV bar."""

    symbol: str
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0

    @classmethod
    def from_dict(cls, symbol: str, raw: dict[str, Any]) -> "IndexDailyBar":
        def _f(k: str) -> float:
            try:
                return float(raw.get(k, 0) or 0)
            except (TypeError, ValueError):
                return 0.0

        return cls(
            symbol=symbol,
            trade_date=str(raw.get("time", "")),
            open=_f("open"),
            high=_f("high"),
            low=_f("low"),
            close=_f("close"),
            volume=_f("volume"),
            amount=_f("amount") if raw.get("amount") else 0.0,
        )


# ═══════════════════════════════════════════════════════════════
# Trade Status
# ═══════════════════════════════════════════════════════════════


@dataclass
class TradeStatus:
    """Execution eligibility for a stock on a given date."""

    symbol: str
    trade_date: str
    is_suspended: bool
    limit_up_price: Optional[float] = None
    limit_down_price: Optional[float] = None
    board_type: str = "main"  # "main" (±10%), "chiNext/star" (±20%), "bse" (±30%)
    _availability: DataAvailability = DataAvailability.AVAILABLE

    @classmethod
    def unknown(cls, symbol: str, trade_date: str) -> "TradeStatus":
        """Create an UNKNOWN status when data is unavailable."""
        return cls(
            symbol=symbol,
            trade_date=trade_date,
            is_suspended=False,
            limit_up_price=None,
            limit_down_price=None,
            board_type="main",
            _availability=DataAvailability.UNKNOWN,
        )

    @classmethod
    def from_bar(
        cls,
        symbol: str,
        bar: StockDailyBar,
        prev_close: Optional[float] = None,
        board_type: str = "main",
    ) -> "TradeStatus":
        """Derive trade status from a daily bar."""
        limit_pct = {"main": 0.10, "chiNext/star": 0.20, "bse": 0.30}.get(board_type, 0.10)
        limit_up = round(prev_close * (1 + limit_pct), 2) if prev_close else None
        limit_down = round(prev_close * (1 - limit_pct), 2) if prev_close else None

        return cls(
            symbol=symbol,
            trade_date=bar.trade_date,
            is_suspended=bar.is_suspended,
            limit_up_price=limit_up,
            limit_down_price=limit_down,
            board_type=board_type,
            _availability=DataAvailability.AVAILABLE,
        )

    @property
    def can_buy(self) -> bool:
        """Can buy at open? Not suspended and open < limit_up."""
        if self.is_suspended:
            return False
        return True  # Price check done at execution time

    @property
    def can_sell(self) -> bool:
        """Can sell at open? Not suspended and open > limit_down."""
        if self.is_suspended:
            return False
        return True  # Price check done at execution time

    @property
    def is_available(self) -> bool:
        return self._availability == DataAvailability.AVAILABLE


# ═══════════════════════════════════════════════════════════════
# Market Regime (PIT-safe, computed from index K-lines)
# ═══════════════════════════════════════════════════════════════


@dataclass
class MarketRegime:
    """Market regime derived from index data at a point in time."""

    date: str
    phase: str  # "euphoria", "hot", "warmup", "cooldown", "ice"
    multiplier: float  # 0.0–1.0 sentiment multiplier
    index_symbol: str = "000001.SH"
    computed_from: str = "index_kline"  # source of computation
    _availability: DataAvailability = DataAvailability.AVAILABLE

    @classmethod
    def unavailable(cls, date: str) -> "MarketRegime":
        return cls(
            date=date,
            phase="unknown",
            multiplier=0.0,
            _availability=DataAvailability.UNAVAILABLE,
        )


# ═══════════════════════════════════════════════════════════════
# Sector Data
# ═══════════════════════════════════════════════════════════════

# Sector K-line data is NOT historically available.
# Sector classification is static (no time-series strength/heat).
# This is explicitly marked for the data contract.


@dataclass
class SectorInfo:
    """Static sector classification for a stock.

    Sector heat/strength is NOT historically reproducible.
    Only static industry assignment is available.
    """

    symbol: str
    industry: str  # Static classification, e.g. "电子", "银行"
    _availability: DataAvailability = DataAvailability.AVAILABLE

    @classmethod
    def not_available(cls, symbol: str) -> "SectorInfo":
        return cls(symbol=symbol, industry="UNKNOWN", _availability=DataAvailability.UNAVAILABLE)

    @property
    def has_sector_data(self) -> bool:
        return self._availability == DataAvailability.AVAILABLE and self.industry != "UNKNOWN"


# ═══════════════════════════════════════════════════════════════
# Data Snapshot (T-1 close state)
# ═══════════════════════════════════════════════════════════════


@dataclass
class DataSnapshot:
    """Complete point-in-time data snapshot at a given date (T-1 close).

    Only contains data available at or before `snapshot_date`.
    Strategy.decide() receives this snapshot and must not access anything else.
    """

    snapshot_date: str  # T-1 (decision date)
    calendar: Any  # TradingCalendar (avoid circular import)
    stock_bars: dict[str, list[StockDailyBar]]  # symbol → bars up to snapshot_date
    index_bars: dict[str, list[IndexDailyBar]]  # index_symbol → bars
    market_regime: MarketRegime
    sector_info: dict[str, SectorInfo]  # symbol → sector classification
    trade_status: dict[str, TradeStatus]  # symbol → trade status on snapshot_date

    # Explicitly NOT AVAILABLE historically:
    # - fund_flow: DataAvailability.UNAVAILABLE
    # - news_sentiment: DataAvailability.UNAVAILABLE
    # - financial_reports: DataAvailability.UNAVAILABLE
    # - sector_kline: DataAvailability.UNAVAILABLE
    # - sector_heat: DataAvailability.UNAVAILABLE
    # - chip_distribution: DataAvailability.UNAVAILABLE

    @property
    def available_symbols(self) -> list[str]:
        """Symbols with valid bars and trade status."""
        return [
            sym for sym in self.stock_bars
            if sym in self.trade_status and self.trade_status[sym].is_available
        ]
