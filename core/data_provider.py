"""HistoricalDataProvider with strict PIT semantics.

Wraps existing data sources (kline_cache.json, MCP fetch_kline, stock_universe)
and provides PIT-safe data access for next-day-open backtest.

Design principles:
- All data access filtered to `<= snapshot_date` (no future leakage)
- Missing data returns explicit UNAVAILABLE, not silent defaults
- No fail-open: unavailable data must be explicitly handled by callers
- No fake historical data: if data can't be PIT-reproduced, mark as UNAVAILABLE
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from core.data_contracts import (
    DataAvailability,
    DataSnapshot,
    IndexDailyBar,
    MarketRegime,
    SectorInfo,
    StockDailyBar,
    TradeStatus,
)
from core.trading_calendar import TradingCalendar

# Re-use existing components where available
_SAFE_FLOAT: Any = None  # Will be imported lazily


def _sf(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


# ═══════════════════════════════════════════════════════════════
# Board type detection (for limit percentages)
# ═══════════════════════════════════════════════════════════════

def detect_board_type(symbol: str) -> str:
    """Detect board type from symbol prefix/suffix.

    - 300xxx.SZ → ChiNext (±20%)
    - 688xxx.SH → STAR (±20%)
    - 8xxxxx.BJ / 4xxxxx.BJ → BSE (±30%)
    - others → main (±10%)
    """
    code = symbol.split(".")[0] if "." in symbol else symbol
    if code.startswith("300") or code.startswith("301"):
        return "chiNext/star"
    if code.startswith("688") or code.startswith("689"):
        return "chiNext/star"
    if code.startswith("8") or code.startswith("4"):
        suffix = symbol.split(".")[-1] if "." in symbol else ""
        if suffix in ("BJ",):
            return "bse"
    return "main"


# ═══════════════════════════════════════════════════════════════
# HistoricalDataProvider
# ═══════════════════════════════════════════════════════════════


class HistoricalDataProvider:
    """PIT-safe historical data access for backtest.

    Wraps existing data sources and enforces:
    - All queries filtered to <= snapshot_date
    - No future data leakage
    - Explicit UNAVAILABLE for missing data
    """

    def __init__(
        self,
        stock_bars_raw: dict[str, list[dict[str, Any]]],
        index_bars_raw: dict[str, list[dict[str, Any]]],
        sector_map: dict[str, str],
        calendar: TradingCalendar,
    ) -> None:
        """Initialize from pre-loaded raw data.

        Args:
            stock_bars_raw: {symbol: [raw_bar_dicts]} — pre-fetched K-line data
            index_bars_raw: {index_symbol: [raw_bar_dicts]} — index K-line data
            sector_map: {symbol: industry_name} — static classification
            calendar: TradingCalendar instance
        """
        self._stock_raw = stock_bars_raw
        self._index_raw = index_bars_raw
        self._sector_map = sector_map
        self._calendar = calendar

        # Pre-parse all bars into typed objects (filtered later per-snapshot)
        self._stock_bars_all: dict[str, list[StockDailyBar]] = {}
        for sym, bars in stock_bars_raw.items():
            parsed = []
            for b in bars:
                try:
                    parsed.append(StockDailyBar.from_dict(sym, b))
                except ValueError:
                    continue  # Skip malformed bars
            if parsed:
                self._stock_bars_all[sym] = parsed

        self._index_bars_all: dict[str, list[IndexDailyBar]] = {}
        for idx_sym, bars in index_bars_raw.items():
            parsed = []
            for b in bars:
                try:
                    parsed.append(IndexDailyBar.from_dict(idx_sym, b))
                except ValueError:
                    continue
            if parsed:
                self._index_bars_all[idx_sym] = parsed

    # ── PIT Queries ──

    def get_stock_daily(
        self, symbol: str, end_date: str, min_bars: int = 60
    ) -> tuple[list[StockDailyBar], DataAvailability]:
        """Get stock daily bars up to end_date (PIT-safe).

        Returns:
            (bars_filtered, availability) — bars is empty if unavailable.
        """
        if symbol not in self._stock_bars_all:
            return [], DataAvailability.UNAVAILABLE

        all_bars = self._stock_bars_all[symbol]
        filtered = [b for b in all_bars if b.trade_date <= end_date]

        if len(filtered) < min_bars:
            return filtered, DataAvailability.STALE

        return filtered, DataAvailability.AVAILABLE

    def get_index_daily(
        self, index_symbol: str, end_date: str
    ) -> tuple[list[IndexDailyBar], DataAvailability]:
        """Get index daily bars up to end_date."""
        if index_symbol not in self._index_bars_all:
            return [], DataAvailability.UNAVAILABLE

        all_bars = self._index_bars_all[index_symbol]
        filtered = [b for b in all_bars if b.trade_date <= end_date]

        if len(filtered) < 5:
            return filtered, DataAvailability.STALE

        return filtered, DataAvailability.AVAILABLE

    def get_sector_info(self, symbol: str) -> SectorInfo:
        """Get static sector classification for a symbol."""
        industry = self._sector_map.get(symbol)
        if industry is None:
            return SectorInfo.not_available(symbol)
        return SectorInfo(symbol=symbol, industry=industry)

    def get_trade_status(self, symbol: str, date: str) -> TradeStatus:
        """Get trade status for a symbol on a given date.

        Derives suspension from volume and limit prices from prev_close + board type.
        If the bar is missing entirely, returns UNKNOWN.
        """
        bars, avail = self.get_stock_daily(symbol, date, min_bars=1)
        if avail == DataAvailability.UNAVAILABLE or not bars:
            return TradeStatus.unknown(symbol, date)

        bar = bars[-1]  # The bar for `date` (or closest before it)

        # Find prev_close: previous bar's close
        prev_close: Optional[float] = None
        if len(bars) >= 2:
            prev_close = bars[-2].close

        board_type = detect_board_type(symbol)
        return TradeStatus.from_bar(symbol, bar, prev_close=prev_close, board_type=board_type)

    def get_market_regime(self, date: str) -> MarketRegime:
        """Compute PIT-safe market regime from index K-lines.

        Currently delegates to the existing compute_regime_sentiment() logic.
        This is a PIT computation from index bars only — no external file dependency.
        """
        index_bars, avail = self.get_index_daily("000001.SH", date)
        if avail == DataAvailability.UNAVAILABLE:
            return MarketRegime.unavailable(date)

        return _compute_regime_from_bars(index_bars, date)

    # ── Snapshot (the main entry point for strategy) ──

    def snapshot(self, date: str, symbols: list[str]) -> DataSnapshot:
        """Build a complete PIT data snapshot for `date` (T-1 close).

        This is the single entry point for strategy.decide().
        The snapshot contains only data available at or before `date`.

        Args:
            date: T-1 date (decision date, e.g. "2026-01-05")
            symbols: universe of stock symbols

        Returns:
            DataSnapshot with all PIT-safe data for decision-making
        """
        stock_bars_snapshot: dict[str, list[StockDailyBar]] = {}
        trade_status_snapshot: dict[str, TradeStatus] = {}
        sector_info_snapshot: dict[str, SectorInfo] = {}

        for sym in symbols:
            bars, _ = self.get_stock_daily(sym, date, min_bars=1)
            if bars:
                stock_bars_snapshot[sym] = bars
            trade_status_snapshot[sym] = self.get_trade_status(sym, date)
            sector_info_snapshot[sym] = self.get_sector_info(sym)

        index_bars_snapshot: dict[str, list[IndexDailyBar]] = {}
        for idx_sym in self._index_bars_all:
            bars, _ = self.get_index_daily(idx_sym, date)
            if bars:
                index_bars_snapshot[idx_sym] = bars

        market_regime = self.get_market_regime(date)

        return DataSnapshot(
            snapshot_date=date,
            calendar=self._calendar,
            stock_bars=stock_bars_snapshot,
            index_bars=index_bars_snapshot,
            market_regime=market_regime,
            sector_info=sector_info_snapshot,
            trade_status=trade_status_snapshot,
        )

    # ── Factory methods ──

    @classmethod
    def from_kline_cache(
        cls,
        cache_path: str | Path,
        symbols: list[str],
        start_date: str,
        end_date: str,
        sector_map: dict[str, str],
    ) -> "HistoricalDataProvider":
        """Create provider from kline_cache.json (existing backtest_2yr.py data path)."""
        with open(cache_path) as f:
            cache = json.load(f)

        stock_bars: dict[str, list[dict]] = {}
        for sym in symbols:
            key = f"{sym}_500"
            if key in cache:
                stock_bars[sym] = cache[key]
            elif sym in cache:
                stock_bars[sym] = cache[sym]

        # Extract index bars from the first available index symbol, or from cache
        index_bars: dict[str, list[dict]] = {}
        # Try to get 000001.SH from cache
        for key in cache:
            if "000001" in key:
                index_bars["000001.SH"] = cache[key]
                break

        # Build calendar from index bars or stock bars
        if "000001.SH" in index_bars:
            calendar = TradingCalendar.from_index_bars(index_bars["000001.SH"], start_date, end_date)
        else:
            # Fallback: derive from any stock's bar timestamps
            all_dates: set[str] = set()
            for sym in symbols:
                if sym in stock_bars:
                    for b in stock_bars[sym]:
                        t = str(b.get("time", ""))
                        if start_date <= t <= end_date:
                            all_dates.add(t)
            calendar = TradingCalendar(sorted(all_dates))

        return cls(stock_bars, index_bars, sector_map, calendar)


# ═══════════════════════════════════════════════════════════════
# Market Regime Computation (PIT-safe, from index bars only)
# ═══════════════════════════════════════════════════════════════


def _compute_regime_from_bars(
    index_bars: list[IndexDailyBar], curr_date: str
) -> MarketRegime:
    """Compute market regime purely from index K-line data (PIT-safe).

    This is the canonical PIT-safe regime computation, replacing
    both load_market_regime() (removed) and the old market_regime.json approach.
    """
    bars = [b for b in index_bars if b.trade_date <= curr_date]
    if len(bars) < 2:
        return MarketRegime(date=curr_date, phase="warmup", multiplier=0.45)

    # Compute using available bars (handles < 5 gracefully)
    lookback = min(5, len(bars))
    recent = bars[-lookback:]
    chgs: list[float] = []
    for b in recent:
        if b.open > 0:
            chgs.append((b.close - b.open) / b.open * 100)
    avg_chg = sum(chgs) / len(chgs) if chgs else 0.0

    if len(bars) >= 3:
        mom = (bars[-1].close - bars[-3].close) / max(bars[-3].close, 0.01) * 100
    elif len(bars) >= 2:
        mom = (bars[-1].close - bars[-2].close) / max(bars[-2].close, 0.01) * 100
    else:
        mom = 0.0

    # Current bar change
    cur = bars[-1]
    chg = (cur.close - cur.open) / max(cur.open, 0.01) * 100 if cur.open > 0 else 0.0

    # Weight more toward current bar when fewer bars available
    if len(bars) >= 5:
        blended = chg * 0.4 + avg_chg * 0.3 + mom * 0.3
    else:
        blended = chg * 0.6 + avg_chg * 0.2 + mom * 0.2

    if blended > 1.0:
        phase, mult = "euphoria", min(0.85, 0.45 * 1.3)
    elif blended >= 0.3:
        phase, mult = "hot", min(0.75, 0.45 * 1.2)
    elif blended >= -0.3:
        phase, mult = "warmup", min(0.60, 0.45)
    elif blended >= -1.0:
        phase, mult = "cooldown", min(0.35, 0.45 * 0.7)
    else:
        phase, mult = "ice", min(0.15, 0.45 * 0.3)

    return MarketRegime(date=curr_date, phase=phase, multiplier=round(mult, 3))
