"""Phase 1B tests — Trading Calendar."""
from __future__ import annotations

import pytest
from core.trading_calendar import TradingCalendar


def make_calendar(dates: list[str] | None = None) -> TradingCalendar:
    if dates is None:
        dates = [
            "2026-01-05",  # Mon
            "2026-01-06",  # Tue
            "2026-01-07",  # Wed
            "2026-01-08",  # Thu
            "2026-01-09",  # Fri
            "2026-01-12",  # Mon (weekend Jan 10-11 skipped)
        ]
    return TradingCalendar(dates)


class TestTradingCalendar:
    def test_from_index_bars(self) -> None:
        bars = [
            {"time": "2026-01-05", "open": 100, "close": 101, "high": 102, "low": 99, "volume": 1000},
            {"time": "2026-01-06", "open": 101, "close": 102, "high": 103, "low": 100, "volume": 1000},
            {"time": "2026-01-07", "open": 102, "close": 103, "high": 104, "low": 101, "volume": 1000},
        ]
        cal = TradingCalendar.from_index_bars(bars, "2026-01-05", "2026-01-07")
        assert len(cal) == 3

    def test_is_trading_day(self) -> None:
        cal = make_calendar()
        assert cal.is_trading_day("2026-01-05") is True
        assert cal.is_trading_day("2026-01-10") is False  # Sunday

    def test_next_trading_day(self) -> None:
        cal = make_calendar()
        assert cal.next_trading_day("2026-01-05") == "2026-01-06"
        assert cal.next_trading_day("2026-01-09") == "2026-01-12"  # Friday → Monday

    def test_next_trading_day_last_day(self) -> None:
        cal = make_calendar()
        assert cal.next_trading_day("2026-01-12") is None  # Last day, no next

    def test_prev_trading_day(self) -> None:
        cal = make_calendar()
        assert cal.prev_trading_day("2026-01-07") == "2026-01-06"
        assert cal.prev_trading_day("2026-01-12") == "2026-01-09"

    def test_prev_trading_day_first(self) -> None:
        cal = make_calendar()
        assert cal.prev_trading_day("2026-01-05") is None

    def test_weekend_not_trading_day(self) -> None:
        cal = make_calendar()
        # Saturday and Sunday should never be in the calendar
        assert cal.is_trading_day("2026-01-10") is False  # Saturday
        assert cal.is_trading_day("2026-01-11") is False  # Sunday

    def test_weekend_next_trading_day(self) -> None:
        """Friday's next trading day should be Monday (skip weekend)."""
        cal = make_calendar()
        friday = "2026-01-09"
        monday = "2026-01-12"
        assert cal.next_trading_day(friday) == monday

    def test_trading_days_between(self) -> None:
        cal = make_calendar()
        assert cal.trading_days_between("2026-01-05", "2026-01-07") == 3
        assert cal.trading_days_between("2026-01-09", "2026-01-12") == 2  # Fri + Mon

    def test_contains(self) -> None:
        cal = make_calendar()
        assert "2026-01-07" in cal
        assert "2026-01-11" not in cal

    def test_invalid_date_raises(self) -> None:
        cal = make_calendar()
        with pytest.raises(KeyError):
            cal.next_trading_day("2026-01-11")  # Not a trading day

    def test_empty_calendar_raises(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            TradingCalendar(["2026-01-05"])  # Only 1 date

    def test_dates_property(self) -> None:
        cal = make_calendar()
        assert cal.dates == ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12"]

    def test_len(self) -> None:
        cal = make_calendar()
        assert len(cal) == 6
