"""Phase 1B tests — HistoricalDataProvider, PIT safety, missing data semantics."""
from __future__ import annotations

import pytest
from core.data_contracts import DataAvailability, DataSnapshot
from core.data_provider import (
    HistoricalDataProvider,
    _compute_regime_from_bars,
    detect_board_type,
)
from core.trading_calendar import TradingCalendar


# ═══════════════════════════════════════════════════════════════
# Test fixtures
# ═══════════════════════════════════════════════════════════════

def _make_bar(time: str, open_p: float = 100, high: float = 101, low: float = 99, close: float = 100, volume: int = 1000000) -> dict:
    return {"time": time, "open": open_p, "high": high, "low": low, "close": close, "volume": volume}


def _make_index_bar(time: str, open_p: float = 3300, high: float = 3350, low: float = 3280, close: float = 3330, volume: int = 50000000) -> dict:
    return {"time": time, "open": open_p, "high": high, "low": low, "close": close, "volume": volume}


def make_provider(
    stock_bars: dict | None = None,
    index_bars: dict | None = None,
    sector_map: dict | None = None,
    start_date: str = "2026-01-05",
    end_date: str = "2026-01-16",
) -> HistoricalDataProvider:
    if stock_bars is None:
        stock_bars = {
            "600519.SH": [
                _make_bar("2026-01-05", 100, 102, 98, 101, 5000000),
                _make_bar("2026-01-06", 101, 103, 100, 102, 6000000),
                _make_bar("2026-01-07", 102, 105, 101, 104, 7000000),
                _make_bar("2026-01-08", 104, 106, 103, 105, 5000000),
                _make_bar("2026-01-09", 105, 107, 104, 106, 4000000),
                _make_bar("2026-01-12", 106, 108, 105, 107, 3000000),
            ],
        }
    if index_bars is None:
        index_bars = {
            "000001.SH": [
                _make_index_bar("2026-01-05", 3300, 3350, 3280, 3330),
                _make_index_bar("2026-01-06", 3330, 3360, 3310, 3350),
                _make_index_bar("2026-01-07", 3350, 3380, 3330, 3360),
                _make_index_bar("2026-01-08", 3360, 3390, 3340, 3370),
                _make_index_bar("2026-01-09", 3370, 3400, 3350, 3380),
                _make_index_bar("2026-01-12", 3380, 3420, 3370, 3410),
                _make_index_bar("2026-01-13", 3410, 3430, 3390, 3420),
                _make_index_bar("2026-01-14", 3420, 3440, 3400, 3430),
            ],
        }
    if sector_map is None:
        sector_map = {"600519.SH": "食品饮料"}

    # Derive calendar from whichever index bars are available, not just 000001.SH
    calendar_bars = index_bars.get("000001.SH") or next(iter(index_bars.values()), [])
    calendar = TradingCalendar.from_index_bars(calendar_bars, start_date, end_date)
    return HistoricalDataProvider(stock_bars, index_bars, sector_map, calendar)


# ═══════════════════════════════════════════════════════════════
# Board Type Detection
# ═══════════════════════════════════════════════════════════════


class TestBoardTypeDetection:
    def test_main_board(self) -> None:
        assert detect_board_type("600519.SH") == "main"
        assert detect_board_type("000001.SZ") == "main"
        assert detect_board_type("002594.SZ") == "main"

    def test_chiNext(self) -> None:
        assert detect_board_type("300750.SZ") == "chiNext/star"
        assert detect_board_type("301000.SZ") == "chiNext/star"

    def test_star(self) -> None:
        assert detect_board_type("688981.SH") == "chiNext/star"
        assert detect_board_type("689009.SH") == "chiNext/star"

    def test_bse(self) -> None:
        assert detect_board_type("830799.BJ") == "bse"
        assert detect_board_type("430047.BJ") == "bse"


# ═══════════════════════════════════════════════════════════════
# Stock Daily Data
# ═══════════════════════════════════════════════════════════════


class TestStockDaily:
    def test_get_stock_daily_available(self) -> None:
        provider = make_provider()
        bars, avail = provider.get_stock_daily("600519.SH", "2026-01-07", min_bars=3)
        assert avail == DataAvailability.AVAILABLE
        assert len(bars) == 3  # Jan 5, 6, 7
        assert bars[-1].trade_date == "2026-01-07"

    def test_get_stock_daily_unavailable_symbol(self) -> None:
        provider = make_provider()
        bars, avail = provider.get_stock_daily("999999.SH", "2026-01-07")
        assert avail == DataAvailability.UNAVAILABLE
        assert bars == []

    def test_get_stock_daily_stale_insufficient_bars(self) -> None:
        provider = make_provider()
        bars, avail = provider.get_stock_daily("600519.SH", "2026-01-05", min_bars=5)
        assert avail == DataAvailability.STALE
        assert len(bars) == 1  # Only Jan 5

    def test_get_stock_daily_pit_filtering(self) -> None:
        """Bars after end_date must not appear."""
        provider = make_provider()
        bars, avail = provider.get_stock_daily("600519.SH", "2026-01-07")
        # Should only have Jan 5, 6, 7 — NOT Jan 8, 9, 12
        dates = [b.trade_date for b in bars]
        assert "2026-01-08" not in dates
        assert "2026-01-09" not in dates
        assert "2026-01-12" not in dates


# ═══════════════════════════════════════════════════════════════
# Index Data
# ═══════════════════════════════════════════════════════════════


class TestIndexDaily:
    def test_get_index_daily_available(self) -> None:
        provider = make_provider()
        bars, avail = provider.get_index_daily("000001.SH", "2026-01-12")  # Has 6 bars by Jan 12
        assert avail == DataAvailability.AVAILABLE
        assert len(bars) >= 5

    def test_get_index_daily_unavailable(self) -> None:
        provider = make_provider()
        bars, avail = provider.get_index_daily("399001.SZ", "2026-01-07")
        assert avail == DataAvailability.UNAVAILABLE


# ═══════════════════════════════════════════════════════════════
# Trade Status
# ═══════════════════════════════════════════════════════════════


class TestTradeStatusProvider:
    def test_get_trade_status_normal(self) -> None:
        provider = make_provider()
        status = provider.get_trade_status("600519.SH", "2026-01-07")
        assert status.is_available is True
        assert status.is_suspended is False
        assert status.limit_up_price is not None
        assert status.limit_down_price is not None

    def test_get_trade_status_unknown_symbol(self) -> None:
        provider = make_provider()
        status = provider.get_trade_status("999999.SH", "2026-01-07")
        assert status.is_available is False
        assert status._availability == DataAvailability.UNKNOWN


# ═══════════════════════════════════════════════════════════════
# Market Regime
# ═══════════════════════════════════════════════════════════════


class TestMarketRegimeProvider:
    def test_get_market_regime_available(self) -> None:
        provider = make_provider()
        regime = provider.get_market_regime("2026-01-12")  # Has 6 bars by Jan 12
        assert regime._availability == DataAvailability.AVAILABLE
        assert regime.phase in ("euphoria", "hot", "warmup", "cooldown", "ice")
        assert isinstance(regime.multiplier, float)
        assert regime.multiplier > 0

    def test_get_market_regime_no_index_data(self) -> None:
        # Provider with index data but no 000001.SH → regime unavailable
        provider = make_provider(index_bars={"399001.SZ": [
            _make_index_bar("2026-01-05", 11000, 11100, 10900, 11050),
            _make_index_bar("2026-01-06", 11050, 11200, 11000, 11150),
            _make_index_bar("2026-01-07", 11150, 11300, 11050, 11200),
            _make_index_bar("2026-01-08", 11200, 11350, 11150, 11280),
            _make_index_bar("2026-01-09", 11280, 11400, 11200, 11350),
            _make_index_bar("2026-01-12", 11350, 11500, 11300, 11400),
            _make_index_bar("2026-01-13", 11400, 11550, 11350, 11500),
            _make_index_bar("2026-01-14", 11500, 11600, 11400, 11550),
        ]})
        regime = provider.get_market_regime("2026-01-07")
        assert regime._availability == DataAvailability.UNAVAILABLE


# ═══════════════════════════════════════════════════════════════
# Sector Info
# ═══════════════════════════════════════════════════════════════


class TestSectorInfoProvider:
    def test_get_sector_info_available(self) -> None:
        provider = make_provider()
        si = provider.get_sector_info("600519.SH")
        assert si.has_sector_data is True
        assert si.industry == "食品饮料"

    def test_get_sector_info_unavailable(self) -> None:
        provider = make_provider()
        si = provider.get_sector_info("999999.SH")
        assert si.has_sector_data is False


# ═══════════════════════════════════════════════════════════════
# Missing Data Semantics
# ═══════════════════════════════════════════════════════════════


class TestMissingDataNotSilent:
    def test_missing_stock_returns_unavailable(self) -> None:
        """Missing stock data must return UNAVAILABLE, not silently default."""
        provider = make_provider()
        bars, avail = provider.get_stock_daily("NONEXISTENT.SH", "2026-01-07")
        assert avail == DataAvailability.UNAVAILABLE
        assert bars == []
        # NOT: silently returning empty dict or default values

    def test_missing_index_returns_unavailable(self) -> None:
        provider = make_provider()
        bars, avail = provider.get_index_daily("NONEXISTENT", "2026-01-07")
        assert avail == DataAvailability.UNAVAILABLE

    def test_missing_sector_is_not_silent(self) -> None:
        """Missing sector data must explicitly show UNAVAILABLE."""
        provider = make_provider()
        si = provider.get_sector_info("UNKNOWN.SH")
        assert si.has_sector_data is False
        assert si._availability == DataAvailability.UNAVAILABLE
        # NOT: silently returning "" or "综合" as default

    def test_stale_data_is_detected(self) -> None:
        """Insufficient bars should return STALE, not AVAILABLE."""
        provider = make_provider()
        _, avail = provider.get_stock_daily("600519.SH", "2026-01-05", min_bars=60)
        assert avail == DataAvailability.STALE

    def test_unavailable_data_does_not_fail_open(self) -> None:
        """UNAVAILABLE data should not trigger safe=True or default actions."""
        provider = make_provider()
        regime = provider.get_market_regime("2026-01-07")
        if regime._availability == DataAvailability.UNAVAILABLE:
            # Must be explicit, not silently defaulting to warmup
            assert regime.phase == "unknown"
            assert regime.multiplier == 0.0


# ═══════════════════════════════════════════════════════════════
# PIT Mutation Tests
# ═══════════════════════════════════════════════════════════════


class TestPITMarketHeatMutation:
    """Market regime computation must be immune to future data changes."""

    def _make_index_bars_a(self):
        return [
            _make_index_bar("2026-01-05", 3300, 3350, 3280, 3330),
            _make_index_bar("2026-01-06", 3330, 3360, 3310, 3350),
            _make_index_bar("2026-01-07", 3350, 3380, 3330, 3360),
            _make_index_bar("2026-01-08", 3360, 3390, 3340, 3370),
            _make_index_bar("2026-01-09", 3370, 3400, 3350, 3380),
            _make_index_bar("2026-01-12", 3380, 3420, 3370, 3410),
        ]

    def _make_index_bars_b(self):
        return [
            _make_index_bar("2026-01-05", 3300, 3350, 3280, 3330),
            _make_index_bar("2026-01-06", 3330, 3360, 3310, 3350),
            _make_index_bar("2026-01-07", 3350, 2000, 3330, 2100),  # DAY 3 CRASH
            _make_index_bar("2026-01-08", 2100, 2150, 2000, 2120),
            _make_index_bar("2026-01-09", 2120, 2180, 2100, 2160),
            _make_index_bar("2026-01-12", 2160, 2200, 2140, 2180),
        ]

    def test_day1_regime_unchanged_by_day3_crash(self) -> None:
        """LEAK-001 mutation: Day 3 crash must not affect Day 1 market regime."""
        provider_a = make_provider(index_bars={"000001.SH": self._make_index_bars_a()})
        provider_b = make_provider(index_bars={"000001.SH": self._make_index_bars_b()})

        regime_a = provider_a.get_market_regime("2026-01-05")
        regime_b = provider_b.get_market_regime("2026-01-05")

        assert regime_a.multiplier == regime_b.multiplier, (
            f"PIT MUTATION FAIL: Day 1 multiplier changed from {regime_a.multiplier} "
            f"to {regime_b.multiplier} when Day 3 was modified to crash"
        )
        assert regime_a.phase == regime_b.phase

    def test_day2_regime_unchanged_by_day3_crash(self) -> None:
        provider_a = make_provider(index_bars={"000001.SH": self._make_index_bars_a()})
        provider_b = make_provider(index_bars={"000001.SH": self._make_index_bars_b()})

        regime_a = provider_a.get_market_regime("2026-01-06")
        regime_b = provider_b.get_market_regime("2026-01-06")

        assert regime_a.multiplier == regime_b.multiplier, (
            "PIT MUTATION FAIL: Day 2 regime changed by Day 3 crash"
        )

    def test_day3_reflects_crash(self) -> None:
        """Day 3 itself SHOULD reflect the crash (it happened on Day 3)."""
        provider_b = make_provider(index_bars={"000001.SH": self._make_index_bars_b()})
        regime = provider_b.get_market_regime("2026-01-07")
        # Should be cooldown or ice (negative blended score)
        assert regime.phase in ("cooldown", "ice")
        assert regime.multiplier < 0.45


class TestPITSectorHeatMutation:
    """Sector heat (if computed from stock data) must be immune to future changes."""

    def test_sector_info_is_static(self) -> None:
        """SectorInfo is static classification — no time dependency at all."""
        provider = make_provider()
        si_day1 = provider.get_sector_info("600519.SH")
        si_day_n = provider.get_sector_info("600519.SH")
        # Static classification, always the same regardless of date
        assert si_day1.industry == si_day_n.industry
        assert si_day1.has_sector_data == si_day_n.has_sector_data


# ═══════════════════════════════════════════════════════════════
# Snapshot
# ═══════════════════════════════════════════════════════════════


class TestSnapshot:
    def test_snapshot_contains_only_pit_data(self) -> None:
        provider = make_provider()
        snapshot = provider.snapshot("2026-01-07", ["600519.SH"])

        # Snapshot date is T-1
        assert snapshot.snapshot_date == "2026-01-07"

        # Stock bars should not contain future dates
        bars = snapshot.stock_bars["600519.SH"]
        dates = [b.trade_date for b in bars]
        for d in dates:
            assert d <= snapshot.snapshot_date, f"Future date {d} leaked into snapshot"

    def test_snapshot_all_components(self) -> None:
        provider = make_provider()
        snapshot = provider.snapshot("2026-01-12", ["600519.SH"])  # Has 6+ bars

        assert "600519.SH" in snapshot.stock_bars
        assert "000001.SH" in snapshot.index_bars
        assert "600519.SH" in snapshot.sector_info
        assert "600519.SH" in snapshot.trade_status
        assert snapshot.market_regime._availability == DataAvailability.AVAILABLE
