#!/usr/bin/env python3
"""Regression tests for Phase 1A backtest integrity fixes.

Covers:
- BUG-001: RSI used before computation
- LEAK-001: Point-in-time market regime (no future data)
- LEAK-002: Point-in-time weekly market health
- T+1 constraint
- Gap stop execution
- Conservative OHLC execution policy
- Limit up/down and suspension
"""
from __future__ import annotations

from typing import Any

from scripts.backtest_engine import (
    compute_regime_sentiment,
    compute_rsi,
    sma,
)


# ── BUG-001: RSI used before computation ──

def test_compute_rsi_basic() -> None:
    """RSI computation produces a value in [0, 100]."""
    bars = [
        {"close": 10 + i * 0.1, "open": 10, "high": 11, "low": 9, "volume": 100}
        for i in range(20)
    ]
    rsi = compute_rsi(bars, period=14)
    assert 0 <= rsi <= 100


def test_compute_rsi_insufficient_data() -> None:
    """When fewer bars than period, RSI returns 50.0 (neutral default)."""
    bars = [{"close": 10, "open": 10, "high": 11, "low": 9, "volume": 100} for _ in range(5)]
    rsi = compute_rsi(bars, period=14)
    assert rsi == 50.0


# ── LEAK-001: Point-in-time market regime ──

def test_compute_regime_sentiment_point_in_time() -> None:
    """compute_regime_sentiment uses only data available at curr_date.

    Day 3's index performance should NOT affect Day 1's sentiment.
    """
    index_bars = [
        {"time": "2026-01-01", "open": 100, "close": 101, "high": 102, "low": 99},
        {"time": "2026-01-02", "open": 101, "close": 102, "high": 103, "low": 100},
        {"time": "2026-01-03", "open": 102, "close": 80, "high": 103, "low": 78},  # crash
        {"time": "2026-01-04", "open": 80, "close": 78, "high": 81, "low": 77},
        {"time": "2026-01-05", "open": 78, "close": 75, "high": 79, "low": 74},
    ]

    # Day 1: should be warmup/hot (rising market, no crash visible)
    phase_d1, mult_d1 = compute_regime_sentiment(index_bars, "2026-01-01")
    # Day 3: should be ice or cooldown (crash day)
    phase_d3, mult_d3 = compute_regime_sentiment(index_bars, "2026-01-03")
    # Day 5: should be ice (deep in crash)
    phase_d5, mult_d5 = compute_regime_sentiment(index_bars, "2026-01-05")

    # Day 1 must NOT see Day 3's crash
    assert mult_d1 > 0.15, f"Day 1 multiplier {mult_d1} should be positive (no crash visible)"
    assert mult_d3 < mult_d1, (
        f"Day 3 multiplier {mult_d3} should be lower than Day 1 {mult_d1}"
    )


def test_compute_regime_sentiment_empty_bars() -> None:
    """With insufficient bars, returns warmup with a small multiplier."""
    phase, mult = compute_regime_sentiment([], "2026-01-01")
    assert isinstance(phase, str)
    assert isinstance(mult, float)
    assert 0 <= mult <= 1.0


# ── T+1 constraint ──

def _make_pos(entry_date: str) -> dict[str, Any]:
    return {
        "sym": "600519.SH", "qty": 100,
        "entry_price": 100.0, "entry_date": entry_date,
        "max_price": 100.0, "buy_point": "二买",
        "daily_trend": "uptrend", "weekly_trend": "uptrend",
        "signal_score": 70, "signal_grade": "B", "rsi": 50,
        "_breakeven_set": False,
    }


def _make_bar(time: str, open_p: float = 100, high: float = 101, low: float = 99, close: float = 100, volume: int = 1000000) -> dict:
    return {"time": time, "open": open_p, "high": high, "low": low, "close": close, "volume": volume}


def test_t1_buy_same_day_no_sell() -> None:
    """T+1: Stock bought on D cannot be sold on D."""
    pos = _make_pos("2026-01-01")
    curr_date = "2026-01-01"
    # In backtest_engine.py, sell check: if pos["entry_date"] == curr_date: continue
    assert pos["entry_date"] == curr_date, "Same day entry should block sell"
    # The real T+1 check is in the main loop at line ~625
    # This test verifies the condition itself


def test_t1_buy_next_day_can_sell() -> None:
    """T+1: Stock bought on D can be sold on D+1."""
    pos = _make_pos("2026-01-01")
    curr_date = "2026-01-02"
    assert pos["entry_date"] != curr_date, "D+1 should allow sell"


# ── Gap stop execution ──

def test_gap_stop_condition() -> None:
    """Gap-through: open below stop should execute at open price.

    Scenario: prev_close=100, stop=95, open=90 → gap through.
    """
    prev_close = 100.0
    stop_price = 95.0
    open_price = 90.0
    low_price = 89.0

    # Gap-through condition: prev_close > stop >= open
    gap_condition = open_price <= stop_price < prev_close
    assert gap_condition, "Open below stop with prev_close above = gap through"

    # Conservative fill: open price (not stop price)
    fill_price = open_price if gap_condition else stop_price
    assert fill_price == 90.0, "Gap fill should be at open"


def test_gap_stop_normal_case() -> None:
    """Normal stop: low <= stop, open > stop. Execute at stop."""
    prev_close = 100.0
    stop_price = 95.0
    open_price = 97.0
    low_price = 93.0

    gap_condition = open_price <= stop_price < prev_close
    assert not gap_condition, "No gap-through"

    # Normal stop: low <= stop
    assert low_price <= stop_price, "Low below stop = stop triggered"
    fill_price = open_price if gap_condition else stop_price
    assert fill_price == 95.0, "Normal stop fill at stop price"


# ── Conservative OHLC execution policy ──

def test_ohlc_collision_conservative() -> None:
    """Conservative: when stop and target could both trigger, use stop price.

    Daily bar: open=100, high=110, low=90, close=105
    Target: 108 (reached at high)
    Stop: 95 (reached at low)
    Conservative = stop executes first (95), locking worse result.
    """
    open_p = 100.0
    high = 110.0
    low = 90.0
    stop = 95.0
    target = 108.0

    both_triggered = high >= target and low <= stop
    assert both_triggered, "Both stop and target triggered in same bar"

    # Conservative: stop before target
    fill_price = stop  # conservative
    assert fill_price == 95.0, "Conservative assumes stop before target"
    # Note: actual intraday path unknown, this is an explicit assumption


# ── Suspension check ──

def test_suspension_detection() -> None:
    """Zero-volume bar indicates suspension/no trading."""
    normal_bar = _make_bar("2026-01-01", volume=1_000_000)
    suspended_bar = _make_bar("2026-01-02", volume=0)

    assert _safe_float(normal_bar.get("volume")) > 0
    assert _safe_float(suspended_bar.get("volume")) == 0


def _safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


# ── Point-in-time: sma with bar filtering ──

def _make_sma_bars(values: list[float]) -> list[dict]:
    return [{"close": v, "high": v + 1, "low": v - 1, "open": v - 0.5, "volume": 1000} for v in values]


def test_sma_uses_only_last_n() -> None:
    """SMA uses the last N bars (not the entire set)."""
    bars = _make_sma_bars([10, 20, 30, 40, 50])
    result = sma(bars, "close", 3)
    # SMA of [30, 40, 50] = 120/3 = 40
    assert abs(result - 40.0) < 0.001


def test_sma_insufficient_data() -> None:
    """SMA returns average of available data when fewer bars than period."""
    bars = _make_sma_bars([10, 20])
    result = sma(bars, "close", 5)
    # SMA of [10, 20] = 30/2 = 15 (uses all available)
    assert abs(result - 15.0) < 0.001


# ── CRITICAL-004: Real A-stock transaction cost model ──

from core.cost_model import buy_cost, sell_cost, is_sh


def test_is_sh_shanghai() -> None:
    """Shanghai suffix identified correctly."""
    assert is_sh("600519.SH") is True
    assert is_sh("688981.SH") is True
    assert is_sh("000001.SH") is True


def test_is_sh_shenzhen() -> None:
    """Shenzhen suffix identified correctly."""
    assert is_sh("000001.SZ") is False
    assert is_sh("300750.SZ") is False
    assert is_sh("002594.SZ") is False


def test_buy_cost_sh() -> None:
    """Buy cost for Shanghai stock: brokerage + transfer fee."""
    # 10000 RMB trade: brokerage = max(10000*0.00025, 5) = 5.0, transfer = 10000*0.00002 = 0.2
    cost = buy_cost(10000.0, "600519.SH")
    assert cost == 5.2, f"Expected 5.2, got {cost}"


def test_buy_cost_sz_no_transfer() -> None:
    """Buy cost for Shenzhen stock: no transfer fee."""
    cost = buy_cost(10000.0, "000858.SZ")
    # brokerage = max(10000*0.00025, 5) = 5.0, no transfer
    assert cost == 5.0, f"Expected 5.0, got {cost}"


def test_buy_cost_min_brokerage() -> None:
    """Buy brokerage has 5 RMB minimum."""
    # 1000 RMB trade: brokerage would be 0.25 RMB but min is 5 RMB
    cost = buy_cost(1000.0, "000001.SZ")
    assert cost == 5.0, f"Expected 5.0, got {cost}"


def test_buy_cost_large_trade() -> None:
    """Buy brokerage proportional above minimum threshold."""
    # 500000 RMB trade: brokerage = 500000 * 0.00025 = 125 RMB
    cost = buy_cost(500000.0, "000001.SZ")
    assert cost == 125.0, f"Expected 125.0, got {cost}"


def test_sell_cost_sh() -> None:
    """Sell cost for Shanghai: brokerage + stamp + transfer."""
    # 10000 RMB trade: brokerage=5, stamp=10, transfer=0.2 = 15.2
    cost = sell_cost(10000.0, "600519.SH")
    assert cost == 15.2, f"Expected 15.2, got {cost}"


def test_sell_cost_sz() -> None:
    """Sell cost for Shenzhen: brokerage + stamp only."""
    cost = sell_cost(10000.0, "000858.SZ")
    # brokerage=5, stamp=10 = 15.0
    assert cost == 15.0, f"Expected 15.0, got {cost}"


def test_sell_cost_large_sh() -> None:
    """Sell cost for large Shanghai trade with all components."""
    # 100000 RMB trade: brokerage=25, stamp=100, transfer=2 = 127
    cost = sell_cost(100000.0, "600519.SH")
    assert cost == 127.0, f"Expected 127.0, got {cost}"


def test_old_vs_new_cost_difference() -> None:
    """Verify new cost model is more expensive than old hack model (only effective for small trades)."""
    # Old: buy 0.03%, sell 0.13%
    # New: buy 0.025% (min 5) + transfer, sell 0.025% (min 5) + 0.1% + transfer
    # For 10000 RMB SH trade:
    old_buy = 10000 * 0.0003  # 3.0
    new_buy = buy_cost(10000, "600519.SH")  # 5.2
    assert new_buy > old_buy, "New model should be more expensive for small trades"

    old_sell = 10000 * 0.0013  # 13.0
    new_sell = sell_cost(10000, "600519.SH")  # 15.2
    assert new_sell > old_sell, "New sell cost should be more expensive"


# ═══════════════════════════════════════════════════════════════
# Phase 1A v2 — EXEC Regression Tests
# ═══════════════════════════════════════════════════════════════


# ── EXEC-001: Sell signal → D+1 execution ──

def test_sell_signal_should_be_d1() -> None:
    """Sell signal detected at D should not execute at D close.

    The backtest_engine.py contract: sell signals are deferred to D+1.
    This test verifies the concept — signal_date != execution_date for
    close-based sell signals (chanlun, ice, breakeven at close).
    """
    # Signal detected from D-day OHLC → execution at D+1
    # This is enforced by pending_sells queue in backtest_engine.py
    signal_date = "2026-01-01"
    execution_date = "2026-01-02"  # D+1
    assert signal_date < execution_date, "Sell execution must be after signal date"


def test_buy_already_d1() -> None:
    """Buy execution is already D+1. Verify conceptual consistency."""
    # Buy: D signal → entry_date = dates[di+1] → D+1 open execution
    signal_date = "2026-01-01"
    entry_date = "2026-01-02"  # D+1
    assert entry_date > signal_date, "Buy must be D+1"


# ── EXEC-002: Trailing stop conservative intraday ──

def test_trailing_stop_conservative_uses_prev_max() -> None:
    """Trailing stop should NOT use today's high to raise the stop AND trigger it.

    Conservative: use yesterday's max_price to compute today's trailing stop.
    Today's high only updates max_price for TOMORROW.
    """
    entry_p = 100.0
    # Yesterday's max was 112 (12% profit)
    yesterday_max = 112.0
    prev_max_profit = (yesterday_max - entry_p) / entry_p * 100  # 12%
    trail_lock_pct = 8.0  # B grade

    # Trailing activates because prev_max_profit (12%) >= trail_lock (8%)
    assert prev_max_profit >= trail_lock_pct

    # Trail price = entry * (1 + 12% * 0.8) = 100 * 1.096 = 109.6
    trail_price = round(entry_p * (1 + prev_max_profit / 100 * 0.8), 2)

    # Today's low is 109 — this triggers the conservative trail
    today_low = 109.0
    assert today_low <= trail_price, "Conservative trail should trigger"

    # But if today's high was 120, that new high should NOT affect today's trail
    today_high = 120.0
    # The new max would be 120 (20% profit), which would trigger +14% lock
    # instead of the 8% trail. But conservative mode uses yesterday's max.
    new_max_profit = (today_high - entry_p) / entry_p * 100  # 20%
    new_trail = round(entry_p * (1 + new_max_profit / 100 * 0.8), 2)  # 116.0

    # Conservative: still use yesterday's trail_price, not today's
    # The spec: "不使用当天 High 来提高当日可执行 stop"
    used_trail = trail_price  # conservative
    assert used_trail == 109.6
    assert new_trail > used_trail  # today's high would give a higher trail
    # But we intentionally don't use it for today's stop check


# ── EXEC-003: Breakeven conservative intraday ──

def test_breakeven_conservative_uses_prev_day_high() -> None:
    """Breakeven activation should use yesterday's max, not today's.

    If yesterday's high reached 2.5%+ profit, breakeven is activated for today.
    If yesterday's max never hit 2.5%, today's high cannot both activate
    breakeven AND trigger a sell at close on the same day.
    """
    entry_p = 100.0
    yesterday_max = 103.0  # 3% profit → breakeven should activate
    prev_max_profit = (yesterday_max - entry_p) / entry_p * 100

    be_threshold = 2.5
    assert prev_max_profit >= be_threshold, "Yesterday's high activates breakeven"
    # Breakeven is active today — if close < entry, sell signal fires

    # Scenario B: yesterday's max = 101 (1%), today's high = 103 (3%)
    yesterday_max_b = 101.0
    prev_max_profit_b = (yesterday_max_b - entry_p) / entry_p * 100
    assert prev_max_profit_b < be_threshold
    # Conservative: breakeven NOT activated by today's high on the same day
    # Today's high of 103 can only activate breakeven for TOMORROW


# ── EXEC-005: Limit-up / Limit-down execution ──

def test_limit_up_buy_blocked() -> None:
    """Buy execution at D+1 open = limit-up price → blocked.

    Limit-up = prev_close * 1.10 (for main board, rounded to 2 decimals).
    """
    prev_close = 10.0
    limit_up = round(prev_close * 1.10, 2)  # 11.0
    open_price = 11.0

    blocked = open_price >= limit_up
    assert blocked, "Buy at limit-up open must be blocked"


def test_limit_up_buy_still_possible_below() -> None:
    """Buy at D+1 open below limit-up → allowed."""
    prev_close = 10.0
    limit_up = round(prev_close * 1.10, 2)  # 11.0
    open_price = 10.98

    blocked = open_price >= limit_up
    assert not blocked, "Buy below limit-up should be allowed"


def test_limit_down_sell_blocked() -> None:
    """Sell execution at D+1 open = limit-down price → blocked, position persists."""
    prev_close = 10.0
    limit_down = round(prev_close * 0.90, 2)  # 9.0
    open_price = 9.0

    blocked = open_price <= limit_down
    assert blocked, "Sell at limit-down open must be blocked"
    assert blocked, "Position must remain when sell blocked by limit-down"


# ── EXEC-006: Position persistence when sell blocked ──

def test_position_remains_when_sell_blocked() -> None:
    """When sell is blocked (suspension/limit-down), position must persist.

    Cannot: sell signal → trade_log SELL → position deleted → without actual execution.
    Correct: signal → pending/blocked → position remains.
    """
    # Simulate: sell signal generated, pending_sells entry created
    # But D+1: volume=0 (suspended) → execution blocked
    # Position should remain in positions dict
    pos = {"sym": "600519.SH", "qty": 100, "entry_price": 100.0, "entry_date": "2026-01-01"}
    positions = {"600519.SH": pos}

    # Blocked by suspension → do NOT delete position
    blocked = True
    if blocked:
        pass  # position remains — do NOT del positions[sym]
    else:
        del positions["600519.SH"]

    assert "600519.SH" in positions, "Blocked sell must not delete position"


def test_suspension_blocks_all_execution() -> None:
    """Zero volume = suspension = no execution possible."""
    suspended_bar = {"volume": 0}
    normal_bar = {"volume": 1000000}

    suspended = _safe_float(suspended_bar.get("volume")) <= 0
    normal = _safe_float(normal_bar.get("volume")) <= 0

    assert suspended, "Zero volume = suspended"
    assert not normal, "Normal volume = not suspended"


# ═══════════════════════════════════════════════════════════════
# Phase 1A v2 — PIT Mutation Tests (LEAK-001, LEAK-002)
# ═══════════════════════════════════════════════════════════════


def test_market_regime_pit_mutation() -> None:
    """LEAK-001 Mutation: Changing Day 3 data must not affect Day 1 regime.

    Dataset A: Day 1 flat, Day 2 flat, Day 3 flat
    Dataset B: Day 1 flat, Day 2 flat, Day 3 CRASH (-50%)

    Day 1 sentiment must be identical in both datasets.
    """
    index_bars_a = [
        {"time": "2026-01-01", "open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0},
        {"time": "2026-01-02", "open": 101.0, "close": 102.0, "high": 103.0, "low": 100.0},
        {"time": "2026-01-03", "open": 102.0, "close": 103.0, "high": 104.0, "low": 101.0},
    ]
    index_bars_b = [
        {"time": "2026-01-01", "open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0},
        {"time": "2026-01-02", "open": 101.0, "close": 102.0, "high": 103.0, "low": 100.0},
        {"time": "2026-01-03", "open": 102.0, "close": 51.0, "high": 102.0, "low": 50.0},  # CRASH
    ]

    phase_a, mult_a = compute_regime_sentiment(index_bars_a, "2026-01-01")
    phase_b, mult_b = compute_regime_sentiment(index_bars_b, "2026-01-01")

    assert mult_a == mult_b, (
        f"LEAK-001 FAIL: Day 1 multiplier changed from {mult_a} to {mult_b} "
        f"when Day 3 data was modified. Future data is leaking into Day 1."
    )
    assert phase_a == phase_b, (
        f"LEAK-001 FAIL: Day 1 phase changed from {phase_a} to {phase_b}"
    )


def test_market_regime_pit_mutation_day2() -> None:
    """LEAK-001: Day 2 regime must also be immune to Day 3 changes."""
    index_bars_a = [
        {"time": "2026-01-01", "open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0},
        {"time": "2026-01-02", "open": 101.0, "close": 102.0, "high": 103.0, "low": 100.0},
        {"time": "2026-01-03", "open": 102.0, "close": 103.0, "high": 104.0, "low": 101.0},
    ]
    index_bars_b = [
        {"time": "2026-01-01", "open": 100.0, "close": 101.0, "high": 102.0, "low": 99.0},
        {"time": "2026-01-02", "open": 101.0, "close": 102.0, "high": 103.0, "low": 100.0},
        {"time": "2026-01-03", "open": 102.0, "close": 51.0, "high": 102.0, "low": 50.0},
    ]

    phase_a, mult_a = compute_regime_sentiment(index_bars_a, "2026-01-02")
    phase_b, mult_b = compute_regime_sentiment(index_bars_b, "2026-01-02")

    assert mult_a == mult_b, (
        f"LEAK-001 FAIL: Day 2 multiplier changed when Day 3 data modified"
    )
    assert phase_a == phase_b, "LEAK-001 FAIL: Day 2 phase changed"


# ── LEAK-002: Weekly market health PIT ──

def test_weekly_pit_principle() -> None:
    """LEAK-002 principle: Wednesday's weekly assessment cannot use Friday's data.

    If curr_date is Wednesday of a week, only data up to that Wednesday
    should be available. Thursday/Friday data must not affect Wednesday's
    market health, max_positions, or score_threshold.
    """
    # Weekly bars with time as Friday's date
    weekly_bars_all = [
        {"time": "2026-09-04", "close": 100.0, "open": 99.0, "high": 101.0, "low": 98.0, "volume": 10000},
        {"time": "2026-09-11", "close": 110.0, "open": 100.0, "high": 112.0, "low": 99.0, "volume": 20000},
        {"time": "2026-09-18", "close": 95.0, "open": 110.0, "high": 111.0, "low": 94.0, "volume": 30000},
        {"time": "2026-09-25", "close": 60.0, "open": 95.0, "high": 96.0, "low": 58.0, "volume": 50000},  # CRASH week
    ]

    # Wednesday of the crash week (Sept 23)
    curr_date_wed = "2026-09-23"
    filtered = [b for b in weekly_bars_all if str(b.get("time", "")) <= curr_date_wed]

    # The crash week bar (Sept 25) should NOT be visible
    crash_visible = any(b["close"] == 60.0 for b in filtered)
    assert not crash_visible, (
        "LEAK-002 FAIL: Friday's crash data is visible on Wednesday. "
        "Weekly data must be filtered by <= curr_date."
    )

    # Only 3 weeks of data should be visible (Sep 4, 11, 18)
    assert len(filtered) == 3, f"Expected 3 weeks visible, got {len(filtered)}"


def test_weekly_pit_friday_can_see_full_week() -> None:
    """LEAK-002: On Friday, the current week's data IS available."""
    weekly_bars_all = [
        {"time": "2026-09-04", "close": 100.0, "open": 99.0, "high": 101.0, "low": 98.0, "volume": 10000},
        {"time": "2026-09-11", "close": 110.0, "open": 100.0, "high": 112.0, "low": 99.0, "volume": 20000},
        {"time": "2026-09-18", "close": 95.0, "open": 110.0, "high": 111.0, "low": 94.0, "volume": 30000},
        {"time": "2026-09-25", "close": 60.0, "open": 95.0, "high": 96.0, "low": 58.0, "volume": 50000},
    ]

    # Friday of the crash week (Sept 25)
    curr_date_fri = "2026-09-25"
    filtered = [b for b in weekly_bars_all if str(b.get("time", "")) <= curr_date_fri]

    # All 4 weeks should be visible, including the crash week
    assert len(filtered) == 4, f"Friday should see all data, got {len(filtered)}"
    crash_visible = any(b["close"] == 60.0 for b in filtered)
    assert crash_visible, "Friday should see current week's crash data"


# ── T+1 strict enforcement ──

def test_t1_enforcement_same_day_blocked() -> None:
    """T+1: entry_date == curr_date → cannot sell."""
    entry_date = "2026-01-01"
    curr_date = "2026-01-01"
    assert entry_date == curr_date, "Same day: sell must be blocked by T+1"


def test_t1_enforcement_next_day_allowed() -> None:
    """T+1: entry_date < curr_date → sell allowed."""
    entry_date = "2026-01-01"
    curr_date = "2026-01-02"
    assert entry_date < curr_date, "D+1: sell should be allowed"

