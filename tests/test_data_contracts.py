"""Phase 1B tests — Data Contracts (schemas, validation, availability)."""
from __future__ import annotations

import pytest
from core.data_contracts import (
    DataAvailability,
    DataSnapshot,
    IndexDailyBar,
    MarketRegime,
    SectorInfo,
    StockDailyBar,
    TradeStatus,
)


# ═══════════════════════════════════════════════════════════════
# StockDailyBar
# ═══════════════════════════════════════════════════════════════


class TestStockDailyBar:
    def test_from_valid_dict(self) -> None:
        raw = {"time": "2026-01-05", "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.8, "volume": 1000000}
        bar = StockDailyBar.from_dict("600519.SH", raw)
        assert bar.symbol == "600519.SH"
        assert bar.trade_date == "2026-01-05"
        assert bar.open == 10.0
        assert bar.high == 11.0
        assert bar.low == 9.5
        assert bar.close == 10.8
        assert bar.volume == 1000000

    def test_missing_required_fields_raises(self) -> None:
        raw = {"time": "2026-01-05", "open": 10.0}  # Missing high, low, close, volume
        with pytest.raises(ValueError, match="missing required fields"):
            StockDailyBar.from_dict("600519.SH", raw)

    def test_empty_time_raises(self) -> None:
        raw = {"time": "", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1000}
        with pytest.raises(ValueError, match="empty time"):
            StockDailyBar.from_dict("600519.SH", raw)

    def test_is_suspended_zero_volume(self) -> None:
        raw = {"time": "2026-01-05", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 0}
        bar = StockDailyBar.from_dict("600519.SH", raw)
        assert bar.is_suspended is True

    def test_is_not_suspended_normal_volume(self) -> None:
        raw = {"time": "2026-01-05", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 5000000}
        bar = StockDailyBar.from_dict("600519.SH", raw)
        assert bar.is_suspended is False

    def test_typical_price(self) -> None:
        raw = {"time": "2026-01-05", "open": 10, "high": 12, "low": 9, "close": 10.5, "volume": 1000}
        bar = StockDailyBar.from_dict("600519.SH", raw)
        assert bar.typical_price == pytest.approx((12 + 9 + 10.5) / 3)

    def test_none_values_default_to_zero(self) -> None:
        raw = {"time": "2026-01-05", "open": None, "high": None, "low": None, "close": None, "volume": None}
        bar = StockDailyBar.from_dict("600519.SH", raw)
        assert bar.open == 0.0
        assert bar.volume == 0.0

    def test_pre_close_and_adj_factor(self) -> None:
        raw = {
            "time": "2026-01-05", "open": 10, "high": 11, "low": 9, "close": 10,
            "volume": 1000, "pre_close": 9.8, "adj_factor": 1.05,
        }
        bar = StockDailyBar.from_dict("600519.SH", raw)
        assert bar.pre_close == 9.8
        assert bar.adj_factor == 1.05


# ═══════════════════════════════════════════════════════════════
# IndexDailyBar
# ═══════════════════════════════════════════════════════════════


class TestIndexDailyBar:
    def test_from_valid_dict(self) -> None:
        raw = {"time": "2026-01-05", "open": 3300, "high": 3350, "low": 3280, "close": 3330, "volume": 50000000}
        bar = IndexDailyBar.from_dict("000001.SH", raw)
        assert bar.symbol == "000001.SH"
        assert bar.trade_date == "2026-01-05"
        assert bar.open == 3300.0
        assert bar.close == 3330.0


# ═══════════════════════════════════════════════════════════════
# TradeStatus
# ═══════════════════════════════════════════════════════════════


class TestTradeStatus:
    def test_from_bar_with_prev_close(self) -> None:
        raw = {"time": "2026-01-06", "open": 11, "high": 12, "low": 10.5, "close": 11.5, "volume": 5000000}
        bar = StockDailyBar.from_dict("600519.SH", raw)
        status = TradeStatus.from_bar("600519.SH", bar, prev_close=10.0, board_type="main")
        assert status.is_suspended is False
        assert status.limit_up_price == 11.0  # 10.0 * 1.10
        assert status.limit_down_price == 9.0  # 10.0 * 0.90
        assert status.can_buy is True
        assert status.can_sell is True

    def test_suspended_bar(self) -> None:
        raw = {"time": "2026-01-06", "open": 11, "high": 12, "low": 10.5, "close": 11.5, "volume": 0}
        bar = StockDailyBar.from_dict("600519.SH", raw)
        status = TradeStatus.from_bar("600519.SH", bar, prev_close=10.0)
        assert status.is_suspended is True
        assert status.can_buy is False
        assert status.can_sell is False

    def test_unknown_status(self) -> None:
        status = TradeStatus.unknown("600519.SH", "2026-01-06")
        assert status.is_available is False
        assert status._availability == DataAvailability.UNKNOWN
        assert status.limit_up_price is None

    def test_chiNext_board_limits(self) -> None:
        raw = {"time": "2026-01-06", "open": 30, "high": 32, "low": 29, "close": 31, "volume": 5000000}
        bar = StockDailyBar.from_dict("300750.SZ", raw)
        status = TradeStatus.from_bar("300750.SZ", bar, prev_close=28.0, board_type="chiNext/star")
        assert status.limit_up_price == pytest.approx(28.0 * 1.20)
        assert status.limit_down_price == pytest.approx(28.0 * 0.80)


# ═══════════════════════════════════════════════════════════════
# MarketRegime
# ═══════════════════════════════════════════════════════════════


class TestMarketRegime:
    def test_warmup_regime(self) -> None:
        mr = MarketRegime(date="2026-01-05", phase="warmup", multiplier=0.45)
        assert mr.phase == "warmup"
        assert mr.multiplier == 0.45
        assert mr.computed_from == "index_kline"
        assert mr._availability == DataAvailability.AVAILABLE

    def test_unavailable_regime(self) -> None:
        mr = MarketRegime.unavailable("2026-01-05")
        assert mr.phase == "unknown"
        assert mr.multiplier == 0.0
        assert mr._availability == DataAvailability.UNAVAILABLE


# ═══════════════════════════════════════════════════════════════
# SectorInfo
# ═══════════════════════════════════════════════════════════════


class TestSectorInfo:
    def test_available_sector(self) -> None:
        si = SectorInfo(symbol="600519.SH", industry="食品饮料")
        assert si.has_sector_data is True
        assert si.industry == "食品饮料"

    def test_not_available_sector(self) -> None:
        si = SectorInfo.not_available("999999.SH")
        assert si.has_sector_data is False
        assert si.industry == "UNKNOWN"

    def test_unknown_industry(self) -> None:
        si = SectorInfo(symbol="000001.SZ", industry="UNKNOWN")
        assert si.has_sector_data is False


# ═══════════════════════════════════════════════════════════════
# DataAvailability
# ═══════════════════════════════════════════════════════════════


class TestDataAvailability:
    def test_enum_values(self) -> None:
        assert DataAvailability.AVAILABLE.value == "AVAILABLE"
        assert DataAvailability.UNAVAILABLE.value == "UNAVAILABLE"
        assert DataAvailability.STALE.value == "STALE"
        assert DataAvailability.UNKNOWN.value == "UNKNOWN"
        assert DataAvailability.INVALID.value == "INVALID"
