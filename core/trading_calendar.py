"""Trading calendar for A-share market.

Provides explicit trading day enumeration, next-trading-day lookup,
and validation — replacing implicit `dates[di+1]` index-based access.

Calendar is derived from actual index K-line timestamps (000001.SH),
which automatically excludes weekends and holidays (no bars exist on non-trading days).
"""

from __future__ import annotations

import datetime as dt
from typing import Optional


class TradingCalendar:
    """Explicit trading day calendar derived from index K-line data."""

    def __init__(self, trade_dates: list[str]) -> None:
        if len(trade_dates) < 2:
            raise ValueError(f"Need at least 2 trading dates, got {len(trade_dates)}")
        self._dates: list[str] = sorted(trade_dates)
        self._date_set: set[str] = set(self._dates)
        self._index: dict[str, int] = {d: i for i, d in enumerate(self._dates)}

    @classmethod
    def from_index_bars(
        cls,
        index_bars: list[dict],
        start_date: str,
        end_date: str,
    ) -> "TradingCalendar":
        """Build calendar from 000001.SH index K-line timestamps."""
        dates = sorted({
            str(b.get("time", ""))
            for b in index_bars
            if start_date <= str(b.get("time", "")) <= end_date
        })
        return cls(dates)

    # ── Query ──

    def is_trading_day(self, date: str) -> bool:
        """Check if a date string is a trading day."""
        return date in self._date_set

    def next_trading_day(self, date: str) -> Optional[str]:
        """Return the next trading day after `date`, or None if `date` is the last."""
        idx = self._index.get(date)
        if idx is None:
            raise KeyError(f"Date {date} is not in trading calendar")
        next_idx = idx + 1
        if next_idx >= len(self._dates):
            return None
        return self._dates[next_idx]

    def prev_trading_day(self, date: str) -> Optional[str]:
        """Return the previous trading day before `date`, or None if first."""
        idx = self._index.get(date)
        if idx is None:
            raise KeyError(f"Date {date} is not in trading calendar")
        if idx == 0:
            return None
        return self._dates[idx - 1]

    def trading_days_between(self, start_date: str, end_date: str) -> int:
        """Count trading days between two dates (inclusive)."""
        si = self._index.get(start_date)
        ei = self._index.get(end_date)
        if si is None or ei is None:
            raise KeyError(f"Date range [{start_date}, {end_date}] not fully in calendar")
        return ei - si + 1

    # ── Iteration ──

    @property
    def dates(self) -> list[str]:
        """All trading dates in order."""
        return list(self._dates)

    def __len__(self) -> int:
        return len(self._dates)

    def __contains__(self, date: str) -> bool:
        return date in self._date_set

    def __repr__(self) -> str:
        return f"TradingCalendar({len(self._dates)} days: {self._dates[0]}..{self._dates[-1]})"
