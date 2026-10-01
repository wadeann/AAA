#!/usr/bin/env python3
"""Test condition evaluator functions with mock data.

Tests cover: extract_quote_metrics, evaluate_auction_condition,
evaluate_intraday_condition, evaluate_dependency, evaluate_chip_condition,
evaluate_fund_flow_condition, evaluate_trailing_profit_condition,
evaluate_scale_out_condition, and evaluate_all.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# Patch get_mcp_client() and get_data_manager() on the utility modules that
# import them.  condition_evaluator.py itself does not import these directly,
# but evaluate_chip_condition / evaluate_fund_flow_condition /
# evaluate_trailing_profit_condition lazy-import from utils_chip,
# utils_fund_flow, and utils_broken_guard at runtime.
_p_broken = patch("utils_broken_guard.get_mcp_client", return_value=MagicMock())
_p_chip = patch("utils_chip.get_mcp_client", return_value=MagicMock())
_p_fund = patch("utils_fund_flow.get_mcp_client", return_value=MagicMock())
_p_broken.start()
_p_chip.start()
_p_fund.start()

from condition_evaluator import (
    ConditionResult,
    evaluate_all,
    evaluate_auction_condition,
    evaluate_chip_condition,
    evaluate_dependency,
    evaluate_fund_flow_condition,
    evaluate_intraday_condition,
    evaluate_scale_out_condition,
    evaluate_trailing_profit_condition,
    extract_quote_metrics,
)


# ============================================================
# Helpers
# ============================================================


def _make_quote(
    symbol: str = "000001.SZ",
    open_p: float = 10.5,
    pre_close: float = 10.0,
    price: float = 10.8,
    high: float = 11.0,
    low: float = 10.2,
    **kwargs,
) -> dict:
    q: dict = {
        "symbol": symbol,
        "open": open_p,
        "pre_close": pre_close,
        "price": price,
        "high": high,
        "low": low,
    }
    q.update(kwargs)
    return q


def _make_cand(
    symbol: str = "000001.SZ",
    direction: str = "buy",
    price: float = 10.0,
    **kwargs,
) -> dict:
    cand: dict = {
        "symbol": symbol,
        "direction": direction,
        "price": price,
    }
    cand.update(kwargs)
    return cand


def _chip_safe_mock(
    is_safe: bool = True,
    reason: str = "chip_ok",
    chip_profit_rate: float = 50.0,
) -> MagicMock:
    m = MagicMock()
    m.is_safe = is_safe
    m.reason = reason
    m.chip_profit_rate = chip_profit_rate
    m.details = {"chipProfitRate": chip_profit_rate}
    return m


def _fund_safe_mock(
    is_safe: bool = True,
    reason: str = "fund_ok",
    main_net_flow: float = 1_000_000,
) -> MagicMock:
    m = MagicMock()
    m.is_safe = is_safe
    m.reason = reason
    m.main_net_flow = main_net_flow
    m.details = {"MainNetFlow": main_net_flow}
    return m


# ============================================================
# ConditionResult
# ============================================================


class TestConditionResult:
    """Basic container behavior."""

    def test_bool_true(self) -> None:
        r = ConditionResult(True, "ok")
        assert bool(r) is True
        assert r["pass"] is True
        assert r["reason"] == "ok"

    def test_bool_false(self) -> None:
        r = ConditionResult(False, "fail")
        assert bool(r) is False

    def test_tuple_unpack(self) -> None:
        ok, msg = ConditionResult(True, "passed")
        assert ok is True
        assert msg == "passed"

    def test_extra_kwargs(self) -> None:
        r = ConditionResult(True, "ok", data=42)
        assert r["data"] == 42


# ============================================================
# extract_quote_metrics
# ============================================================


class TestExtractQuoteMetrics:
    """Pure function; no mocking needed."""

    def test_full_quote(self) -> None:
        q = _make_quote()
        m = extract_quote_metrics(q)
        assert m["open_price"] == 10.5
        assert m["pre_close"] == 10.0
        assert m["current_price"] == 10.8
        assert m["high_price"] == 11.0
        assert m["low_price"] == 10.2
        assert m["open_pct"] == 5.0
        assert m["current_pct"] == 8.0
        assert m["is_sealed"] is False

    def test_empty_quote(self) -> None:
        m = extract_quote_metrics({})
        assert m["open_price"] == 0.0
        assert m["pre_close"] == 0.0
        assert m["current_price"] == 0.0
        assert m["open_pct"] == 0.0
        assert m["current_pct"] == 0.0
        assert m["is_sealed"] is False

    def test_partial_quote_no_open(self) -> None:
        q = {"price": 10.5, "pre_close": 10.0}
        m = extract_quote_metrics(q)
        assert m["open_price"] == 0.0
        assert m["open_pct"] == 0.0
        assert m["current_pct"] == 5.0

    def test_with_open_pct_direct(self) -> None:
        q = {"open_pct": 3.5, "price": 10.5, "pre_close": 10.0}
        m = extract_quote_metrics(q)
        assert m["open_pct"] == 3.5

    def test_sealed_when_ask1_zero_and_nine_eight(self) -> None:
        q = _make_quote(price=10.98, pre_close=10.0)
        q["ask1_volume"] = 0
        m = extract_quote_metrics(q)
        assert m["current_pct"] == 9.8
        assert m["is_sealed"] is True

    def test_not_sealed_below_nine_eight(self) -> None:
        q = _make_quote(price=10.5, pre_close=10.0)
        q["ask1_volume"] = 0
        m = extract_quote_metrics(q)
        assert m["current_pct"] == 5.0
        assert m["is_sealed"] is False

    def test_exploded_via_direct_key(self) -> None:
        m = extract_quote_metrics(_make_quote(exploded=True))
        assert m["exploded"] is True

    def test_exploded_via_is_exploded_key(self) -> None:
        m = extract_quote_metrics(_make_quote(is_exploded=True))
        assert m["exploded"] is True

    def test_alternative_key_names(self) -> None:
        q = {
            "open_price": 10.2,
            "last_close": 9.8,
            "current": 10.5,
            "high_price": 10.8,
            "low_price": 10.0,
            "bid_volume": 1000,
            "bid_amount": 50000,
        }
        m = extract_quote_metrics(q)
        assert m["open_price"] == 10.2
        assert m["pre_close"] == 9.8
        assert m["current_price"] == 10.5
        assert m["auction_volume"] == 1000
        assert m["auction_amount"] == 50000

    def test_none_values(self) -> None:
        m = extract_quote_metrics({"open": None, "pre_close": None, "price": None})
        assert m["open_price"] == 0.0
        assert m["pre_close"] == 0.0
        assert m["current_price"] == 0.0

    def test_change_pct_fallback(self) -> None:
        q = {"change_pct": -2.5, "open": 10.0, "pre_close": 10.0}
        m = extract_quote_metrics(q)
        assert m["open_pct"] == 0.0
        assert m["current_pct"] == -2.5

    def test_sealed_by_seal_amount(self) -> None:
        q = _make_quote(price=10.98, pre_close=10.0)
        q["ask1_volume"] = 100
        q["seal_amount"] = 99999
        m = extract_quote_metrics(q)
        assert m["is_sealed"] is True

    def test_prev_close_fallback(self) -> None:
        q = {"open": 10.0, "prev_close": 9.5, "price": 10.3}
        m = extract_quote_metrics(q)
        assert m["pre_close"] == 9.5
        assert m["open_pct"] == pytest.approx(5.26, rel=0.01)

    def test_speed_pct(self) -> None:
        q = _make_quote(speed_pct_3min=3.5)
        m = extract_quote_metrics(q)
        assert m["speed_pct_3min"] == 3.5


# ============================================================
# evaluate_auction_condition
# ============================================================


class TestEvaluateAuctionCondition:
    """Auction / gap-up condition."""

    def test_sell_bypass(self) -> None:
        ok, msg = evaluate_auction_condition(_make_cand(direction="sell"))
        assert ok is True
        assert "sell_no_auction_check" in msg

    def test_default_pass_when_no_limits_and_no_quote(self) -> None:
        cand = _make_cand()
        ok, msg = evaluate_auction_condition(cand)
        assert ok is True
        assert "默认放行" in msg

    def test_missing_quote_and_pct_returns_false_when_limits(self) -> None:
        cand = _make_cand(auction_open_min_pct=1.0)
        ok, msg = evaluate_auction_condition(cand)
        assert ok is False
        assert "missing_quote_and_pct" in msg

    def test_gap_up_meets_min(self) -> None:
        cand = _make_cand(condition_triggers={"auction_open_min_pct": 2.0})
        ok, _ = evaluate_auction_condition(cand, auction_pct=3.0)
        assert ok is True

    def test_gap_up_below_min(self) -> None:
        cand = _make_cand(auction_open_min_pct=3.0)
        ok, msg = evaluate_auction_condition(cand, auction_pct=1.5)
        assert ok is False
        assert "高开" in msg

    def test_gap_up_exceeds_max(self) -> None:
        cand = _make_cand(auction_open_max_pct=5.0)
        ok, msg = evaluate_auction_condition(cand, auction_pct=7.0)
        assert ok is False
        assert "上限" in msg

    def test_auction_pct_from_quote(self) -> None:
        cand = _make_cand(auction_open_min_pct=1.0)
        q = _make_quote(open_p=10.3, pre_close=10.0)
        ok, _ = evaluate_auction_condition(cand, quote=q)
        assert ok is True

    def test_condition_triggers_preferred(self) -> None:
        cand = _make_cand(
            auction_open_min_pct=0.5,
            condition_triggers={"auction_open_min_pct": 3.0},
        )
        ok, msg = evaluate_auction_condition(cand, auction_pct=1.0)
        assert ok is False
        assert "高开" in msg

    def test_anchor_min_pct_fails(self) -> None:
        anchor = {"symbol": "000300.SH", "min_auction_open_pct": 1.0}
        cand = _make_cand(condition_triggers={"dependency_anchor": anchor})
        q = _make_quote(anchors={"000300.SH": _make_quote(open_p=10.05, pre_close=10.0)})
        ok, msg = evaluate_auction_condition(cand, quote=q)
        assert ok is False
        assert "锚定" in msg

    def test_anchor_must_not_explode(self) -> None:
        anchor = {"symbol": "000300.SH", "must_not_explode": True}
        cand = _make_cand(dependency_anchor=anchor)
        q = _make_quote(anchors={"000300.SH": _make_quote(exploded=True)})
        ok, msg = evaluate_auction_condition(cand, quote=q)
        assert ok is False
        assert "炸板" in msg

    def test_anchor_missing_quote_bypasses(self) -> None:
        anchor = {"symbol": "000300.SH", "min_auction_open_pct": 1.0}
        cand = _make_cand(dependency_anchor=anchor)
        q = _make_quote(anchors={})
        ok, _ = evaluate_auction_condition(cand, quote=q)
        assert ok is True

    def test_normal_open_passes(self) -> None:
        cand = _make_cand(auction_open_min_pct=0.0)
        ok, _ = evaluate_auction_condition(cand, auction_pct=0.0)
        assert ok is True


# ============================================================
# evaluate_intraday_condition
# ============================================================


class TestEvaluateIntradayCondition:
    """Intraday checks (chase threshold, seal deadline).
    check_broken_and_fake_healing is imported at module level in
    condition_evaluator, so patch condition_evaluator namespace.
    """

    @patch("condition_evaluator.check_broken_and_fake_healing")
    def test_sell_bypass(self, mock_check) -> None:
        ok, msg = evaluate_intraday_condition(_make_cand(direction="sell"))
        assert ok is True
        assert "sell_no_intraday_check" in msg
        mock_check.assert_not_called()

    @patch("condition_evaluator.check_broken_and_fake_healing")
    def test_broken_rejected(self, mock_check) -> None:
        mock_check.return_value = (False, "炸板破位")
        q = _make_quote(price=10.0, pre_close=10.0)
        ok, msg = evaluate_intraday_condition(_make_cand(), quote=q)
        assert ok is False
        assert "炸板破位" in msg

    @patch("condition_evaluator.check_broken_and_fake_healing")
    def test_below_max_chase(self, mock_check) -> None:
        mock_check.return_value = (True, "ok")
        cand = _make_cand(condition_triggers={"max_chase_pct": 5.0})
        ok, _ = evaluate_intraday_condition(cand, current_pct=3.0)
        assert ok is True

    @patch("condition_evaluator.check_broken_and_fake_healing")
    def test_above_max_chase(self, mock_check) -> None:
        mock_check.return_value = (True, "ok")
        cand = _make_cand(max_chase_pct=5.0)
        ok, msg = evaluate_intraday_condition(cand, current_pct=7.0)
        assert ok is False
        assert "追高门槛" in msg

    @patch("condition_evaluator.check_broken_and_fake_healing")
    def test_must_seal_before_deadline(self, mock_check) -> None:
        mock_check.return_value = (True, "ok")
        cand = _make_cand(must_seal_before="09:35")
        ok, msg = evaluate_intraday_condition(cand, current_pct=5.0, now_time="09:40")
        assert ok is False
        assert "封板" in msg

    @patch("condition_evaluator.check_broken_and_fake_healing")
    def test_sealed_before_deadline(self, mock_check) -> None:
        mock_check.return_value = (True, "ok")
        cand = _make_cand(condition_triggers={"must_seal_before": "09:35"})
        ok, _ = evaluate_intraday_condition(cand, current_pct=9.9, now_time="09:40")
        assert ok is True

    @patch("condition_evaluator.check_broken_and_fake_healing")
    def test_no_triggers_default_pass(self, mock_check) -> None:
        mock_check.return_value = (True, "ok")
        ok, _ = evaluate_intraday_condition(_make_cand(), current_pct=3.0)
        assert ok is True

    @patch("condition_evaluator.check_broken_and_fake_healing")
    def test_cand_was_limit_up(self, mock_check) -> None:
        cand = _make_cand()
        q = _make_quote(price=10.0, pre_close=10.0, was_limit_up_today=False)
        mock_check.return_value = (True, "ok")
        ok, _ = evaluate_intraday_condition(cand, quote=q, current_pct=2.0)
        assert ok is True

    @patch("condition_evaluator.check_broken_and_fake_healing")
    def test_quote_keys_fallback(self, mock_check) -> None:
        """Fallback to cand fields when no quote is provided."""
        mock_check.return_value = (True, "ok")
        cand = _make_cand(price=10.5, high=10.8, low=10.2, pre_close=10.0)
        ok, _ = evaluate_intraday_condition(cand, current_pct=5.0)
        assert ok is True


# ============================================================
# evaluate_dependency
# ============================================================


class TestEvaluateDependency:
    """Dependency / anchor condition evaluation."""

    def test_no_dependency(self) -> None:
        ok, msg = evaluate_dependency(_make_cand(), {})
        assert ok is True
        assert "no_dependency" in msg

    def test_no_dependency_symbol(self) -> None:
        ok, msg = evaluate_dependency(_make_cand(dependency_anchor={}), {})
        # Empty dict is falsy, so the function returns "no_dependency"
        # rather than checking for a missing symbol.
        assert ok is True
        assert "no_dependency" in msg

    def test_quote_unavailable(self) -> None:
        cand = _make_cand(dependency_anchor={"symbol": "000300.SH"})
        ok, msg = evaluate_dependency(cand, {})
        assert ok is False
        assert "unavailable" in msg

    def test_min_pct_fails(self) -> None:
        dep = {"symbol": "000300.SH", "min_auction_open_pct": 2.0}
        cand = _make_cand(dependency_anchor=dep)
        q = _make_quote(open_p=10.1, pre_close=10.0)
        ok, msg = evaluate_dependency(cand, {"000300.SH": q})
        assert ok is False
        assert "锚定" in msg

    def test_min_pct_passes(self) -> None:
        dep = {"symbol": "000300.SH", "min_auction_open_pct": 1.0}
        cand = _make_cand(condition_triggers={"dependency_anchor": dep})
        q = _make_quote(open_p=10.5, pre_close=10.0)
        ok, _ = evaluate_dependency(cand, {"000300.SH": q})
        assert ok is True

    def test_must_not_explode(self) -> None:
        dep = {"symbol": "000300.SH", "must_not_explode": True}
        q = _make_quote(is_exploded=True)
        ok, msg = evaluate_dependency(_make_cand(dependency_anchor=dep), {"000300.SH": q})
        assert ok is False
        assert "炸板" in msg

    def test_ok(self) -> None:
        dep = {"symbol": "000300.SH"}
        cand = _make_cand(dependency_anchor=dep)
        ok, _ = evaluate_dependency(cand, {"000300.SH": _make_quote()})
        assert ok is True


# ============================================================
# evaluate_chip_condition
# ============================================================

# The function body does: from utils_chip import evaluate_chip_safety
# So the patch must target utils_chip (not condition_evaluator.utils_chip).


class TestEvaluateChipCondition:
    """Chip distribution safety."""

    @patch("utils_chip.evaluate_chip_safety")
    def test_sell_bypass(self, mock_chip) -> None:
        ok, msg = evaluate_chip_condition({}, {"direction": "sell"})
        assert ok is True
        assert "sell_no_chip_check" in msg
        mock_chip.assert_not_called()

    @patch("utils_chip.evaluate_chip_safety")
    def test_safe_chip_passes(self, mock_chip) -> None:
        mock_chip.return_value = _chip_safe_mock()
        ok, _ = evaluate_chip_condition(_make_quote(price=10.0), _make_cand())
        assert ok is True

    @patch("utils_chip.evaluate_chip_safety")
    def test_unsafe_chip_fails(self, mock_chip) -> None:
        mock_chip.return_value = _chip_safe_mock(is_safe=False, reason="chip_unsafe")
        ok, msg = evaluate_chip_condition(
            _make_quote(price=10.0), {"direction": "buy", "price": 10.0},
        )
        assert ok is False
        assert "chip_unsafe" in msg

    @patch("utils_chip.evaluate_chip_safety")
    def test_min_chip_profit_rate_fails(self, mock_chip) -> None:
        mock_chip.return_value = _chip_safe_mock(chip_profit_rate=10.0)
        cond = _make_cand(min_chip_profit_rate=20.0)
        ok, msg = evaluate_chip_condition(_make_quote(price=10.0), cond)
        assert ok is False
        assert "获利盘" in msg

    @patch("utils_chip.evaluate_chip_safety")
    def test_min_chip_profit_rate_from_triggers(self, mock_chip) -> None:
        mock_chip.return_value = _chip_safe_mock(chip_profit_rate=10.0)
        cond = _make_cand(condition_triggers={"min_chip_profit_rate": 20.0})
        ok, msg = evaluate_chip_condition(_make_quote(price=10.0), cond)
        assert ok is False
        assert "获利盘" in msg

    @patch("utils_chip.evaluate_chip_safety")
    def test_exception_triggers_graceful_degrade(self, mock_chip) -> None:
        mock_chip.side_effect = Exception("chip service down")
        ok, msg = evaluate_chip_condition(_make_quote(price=10.0), _make_cand())
        assert ok is True
        assert "降级放行" in msg

    @patch("utils_chip.evaluate_chip_safety")
    def test_auto_swap_args(self, mock_chip) -> None:
        mock_chip.return_value = _chip_safe_mock()
        q = _make_quote(price=10.0, direction="buy", condition_triggers={})
        ok, _ = evaluate_chip_condition(q, {"price": 10.0, "close": 10.0})
        assert ok is True

    @patch("utils_chip.evaluate_chip_safety")
    def test_direct_chip_keys(self, mock_chip) -> None:
        mock_chip.return_value = _chip_safe_mock()
        q = _make_quote(price=10.0, chipProfitRate=80.0, chipAvgCost=9.5)
        ok, _ = evaluate_chip_condition(q, {"direction": "buy"})
        assert ok is True


# ============================================================
# evaluate_fund_flow_condition
# ============================================================


class TestEvaluateFundFlowCondition:
    """Fund flow safety."""

    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_sell_bypass(self, mock_fund) -> None:
        ok, msg = evaluate_fund_flow_condition({}, {"direction": "sell"})
        assert ok is True
        assert "sell_no_fund_flow_check" in msg
        mock_fund.assert_not_called()

    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_safe_fund_passes(self, mock_fund) -> None:
        mock_fund.return_value = _fund_safe_mock()
        ok, _ = evaluate_fund_flow_condition(
            _make_quote(price=10.0), {"direction": "buy", "price": 10.0},
        )
        assert ok is True

    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_unsafe_fund_fails(self, mock_fund) -> None:
        mock_fund.return_value = _fund_safe_mock(is_safe=False, reason="fund_bad")
        ok, msg = evaluate_fund_flow_condition(_make_quote(price=10.0), _make_cand())
        assert ok is False
        assert "fund_bad" in msg

    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_min_main_net_flow_fails(self, mock_fund) -> None:
        mock_fund.return_value = _fund_safe_mock(main_net_flow=1_000_000)
        cond = _make_cand(min_main_net_flow=5_000_000)
        ok, msg = evaluate_fund_flow_condition(_make_quote(price=10.0), cond)
        assert ok is False
        assert "主力净额" in msg

    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_min_main_net_flow_from_triggers(self, mock_fund) -> None:
        mock_fund.return_value = _fund_safe_mock(main_net_flow=1_000_000)
        cond = _make_cand(condition_triggers={"min_main_net_flow": 5_000_000})
        ok, msg = evaluate_fund_flow_condition(_make_quote(price=10.0), cond)
        assert ok is False
        assert "主力净额" in msg

    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_exception_triggers_graceful_degrade(self, mock_fund) -> None:
        mock_fund.side_effect = Exception("fund service down")
        ok, msg = evaluate_fund_flow_condition(_make_quote(price=10.0), _make_cand())
        assert ok is True
        assert "降级放行" in msg

    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_auto_swap_args(self, mock_fund) -> None:
        mock_fund.return_value = _fund_safe_mock()
        q = _make_quote(price=10.0, direction="buy", condition_triggers={})
        ok, _ = evaluate_fund_flow_condition(q, {"price": 10.0, "close": 10.0})
        assert ok is True

    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_direct_fund_keys(self, mock_fund) -> None:
        mock_fund.return_value = _fund_safe_mock()
        q = _make_quote(price=10.0, MainNetFlow=5_000_000)
        ok, _ = evaluate_fund_flow_condition(q, {"direction": "buy"})
        assert ok is True


# ============================================================
# evaluate_trailing_profit_condition
# ============================================================


class TestEvaluateTrailingProfitCondition:
    """Trailing stop / take-profit logic.
    compute_limit_pct is lazy-imported inside the function body, so
    patch utils_broken_guard directly.
    """

    @patch("utils_broken_guard.compute_limit_pct")
    def test_invalid_cost(self, mock_limit) -> None:
        mock_limit.return_value = 9.9
        ok, msg = evaluate_trailing_profit_condition({"cost_price": 0.0}, {})
        assert ok is False
        assert "成本价" in msg or "无效" in msg

    @patch("utils_broken_guard.compute_limit_pct")
    def test_invalid_price(self, mock_limit) -> None:
        mock_limit.return_value = 9.9
        # quote.get("price", ...) returns 0.0, which is falsy,
        # so cur_p falls back to cost=10.0.  Since cost > 0 and
        # cur_p > 0 the function does not early-return with "无效".
        # Without pre_close the broken-limit check is also skipped.
        ok, msg = evaluate_trailing_profit_condition(
            {"cost_price": 10.0}, {"price": 0.0},
        )
        assert ok is False
        assert "未触及" in msg

    @patch("utils_broken_guard.compute_limit_pct")
    def test_no_trigger_below_thresholds(self, mock_limit) -> None:
        mock_limit.return_value = 9.9
        pos = {"cost_price": 10.0}
        # high is set close to price so broken-limit check won't trigger
        q = _make_quote(price=10.2, pre_close=10.0, high=10.2)
        ok, msg = evaluate_trailing_profit_condition(pos, q)
        assert ok is False
        assert "未触及" in msg

    @patch("utils_broken_guard.compute_limit_pct")
    def test_tier2_triggers(self, mock_limit) -> None:
        mock_limit.return_value = 9.9
        wm = {"high_watermark_price": 11.5, "high_watermark_pct": 15.0}
        pos = {"cost_price": 10.0, "symbol": "000001.SZ"}
        q = _make_quote(price=10.8, pre_close=10.0)
        ok, msg = evaluate_trailing_profit_condition(pos, q, watermark=wm)
        assert ok is True
        assert "核心锁利" in msg

    @patch("utils_broken_guard.compute_limit_pct")
    def test_tier0_breakeven(self, mock_limit) -> None:
        mock_limit.return_value = 9.9
        wm = {"high_watermark_price": 10.5, "high_watermark_pct": 5.0}
        pos = {"cost_price": 10.0, "symbol": "000001.SZ"}
        # high=10.2 so broken-limit check won't trigger (2% < 9.4%)
        q = _make_quote(price=10.01, pre_close=10.0, high=10.2)
        ok, msg = evaluate_trailing_profit_condition(pos, q, watermark=wm)
        assert ok is True
        assert "保本锁" in msg

    @patch("utils_broken_guard.compute_limit_pct")
    def test_tighten_stops_lowers_thresholds(self, mock_limit) -> None:
        mock_limit.return_value = 9.9
        wm = {"high_watermark_price": 10.3, "high_watermark_pct": 3.0}
        pos = {"cost_price": 10.0, "symbol": "000001.SZ"}
        q = _make_quote(price=10.0, pre_close=10.0, high=10.0)
        ok, msg = evaluate_trailing_profit_condition(
            pos, q, watermark=wm, tighten_stops=True,
        )
        assert ok is True
        assert "保本锁" in msg

    @patch("utils_broken_guard.compute_limit_pct")
    def test_broken_limit_triggers(self, mock_limit) -> None:
        mock_limit.return_value = 9.9
        pos = {"cost_price": 10.0, "symbol": "000001.SZ"}
        q = _make_quote(price=9.5, pre_close=10.0, high=11.0, was_limit_up_today=True)
        ok, msg = evaluate_trailing_profit_condition(pos, q)
        assert ok is True
        assert "破位" in msg

    @patch("utils_broken_guard.compute_limit_pct")
    def test_no_watermark_uses_high_price(self, mock_limit) -> None:
        mock_limit.return_value = 9.9
        pos = {"cost_price": 10.0, "symbol": "000001.SZ"}
        q = _make_quote(price=10.8, pre_close=10.0, high=11.0)
        ok, msg = evaluate_trailing_profit_condition(pos, q)
        assert ok is False
        assert "未触及" in msg


# ============================================================
# evaluate_scale_out_condition
# ============================================================


class TestEvaluateScaleOutCondition:
    """First-level scale-out (50%) logic."""

    def test_invalid_cost(self) -> None:
        ok, msg = evaluate_scale_out_condition({"cost_price": 0.0}, {})
        assert ok is False
        assert "无效" in msg

    def test_invalid_price(self) -> None:
        pos = {"cost_price": 10.0}
        # Negative price makes cur_p <= 0.0 after the falsy coalesce
        q = {"price": -1.0}
        ok, msg = evaluate_scale_out_condition(pos, q)
        assert ok is False
        assert "无效" in msg

    def test_scale_out_already_executed(self) -> None:
        pos = {"cost_price": 10.0}
        q = _make_quote(price=11.0)
        wm = {"scale_out_executed": True}
        ok, msg = evaluate_scale_out_condition(pos, q, watermark=wm)
        assert ok is False
        assert "已执行过" in msg

    def test_below_threshold(self) -> None:
        pos = {"cost_price": 10.0}
        # high matches price to avoid creating an artificial watermark
        q = _make_quote(price=10.3, high=10.3)
        ok, msg = evaluate_scale_out_condition(pos, q)
        assert ok is False
        assert "未触及" in msg

    def test_scale_out_triggers(self) -> None:
        pos = {"cost_price": 10.0, "symbol": "000001.SZ"}
        wm = {"high_watermark_price": 10.8, "high_watermark_pct": 8.0}
        q = _make_quote(price=10.3, pre_close=10.0)
        ok, msg = evaluate_scale_out_condition(pos, q, watermark=wm)
        assert ok is True
        assert "分批止盈" in msg

    def test_tighten_stops_lowers_thresholds(self) -> None:
        pos = {"cost_price": 10.0, "symbol": "000001.SZ"}
        wm = {"high_watermark_price": 10.5, "high_watermark_pct": 5.0}
        q = _make_quote(price=10.3, pre_close=10.0)
        ok, msg = evaluate_scale_out_condition(pos, q, watermark=wm, tighten_stops=True)
        assert ok is True
        assert "分批止盈" in msg

    def test_scale_out_not_triggered_when_drawdown_small(self) -> None:
        pos = {"cost_price": 10.0, "symbol": "000001.SZ"}
        wm = {"high_watermark_price": 10.8, "high_watermark_pct": 8.0}
        q = _make_quote(price=10.7, pre_close=10.0)
        ok, msg = evaluate_scale_out_condition(pos, q, watermark=wm)
        assert ok is False
        assert "未触及" in msg

    def test_no_watermark_uses_quote_high(self) -> None:
        pos = {"cost_price": 10.0, "symbol": "000001.SZ"}
        q = _make_quote(price=10.3, pre_close=10.0, high=10.8)
        ok, msg = evaluate_scale_out_condition(pos, q)
        assert ok is True
        assert "分批止盈" in msg


# ============================================================
# evaluate_all (integrated)
# ============================================================


class TestEvaluateAll:
    """Full integrated evaluation.
    Uses patch.multiple on condition_evaluator for the module-level import,
    and direct module patches for lazy-imported functions.
    """

    @patch.multiple(
        "condition_evaluator",
        check_broken_and_fake_healing=MagicMock(return_value=(True, "ok")),
    )
    @patch("utils_chip.evaluate_chip_safety")
    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_buy_candidate_passes_all(
        self, mock_fund, mock_chip,
    ) -> None:
        mock_chip.return_value = _chip_safe_mock()
        mock_fund.return_value = _fund_safe_mock()
        cand = _make_cand(auction_open_min_pct=0.0)
        q = _make_quote(open_p=10.0, pre_close=10.0, price=10.2)
        result = evaluate_all(cand, q)
        assert result["pass"] is True
        assert result["checks"]["auction"]["pass"] is True
        assert result["checks"]["intraday"]["pass"] is True
        assert "auction_amount" not in result["checks"]
        assert result["checks"]["chip_safety"]["pass"] is True

    @patch.multiple(
        "condition_evaluator",
        check_broken_and_fake_healing=MagicMock(return_value=(True, "ok")),
    )
    @patch("utils_chip.evaluate_chip_safety")
    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_sell_candidate_skips_buy_checks(
        self, mock_fund, mock_chip,
    ) -> None:
        mock_chip.return_value = _chip_safe_mock()
        mock_fund.return_value = _fund_safe_mock()
        cand = _make_cand(direction="sell")
        q = _make_quote()
        result = evaluate_all(cand, q)
        assert result["pass"] is True
        assert "chip_safety" not in result["checks"]
        assert "fund_flow_safety" not in result["checks"]

    @patch.multiple(
        "condition_evaluator",
        check_broken_and_fake_healing=MagicMock(return_value=(True, "ok")),
    )
    @patch("utils_chip.evaluate_chip_safety")
    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_auction_fails_halts(self, mock_fund, mock_chip) -> None:
        mock_chip.return_value = _chip_safe_mock()
        mock_fund.return_value = _fund_safe_mock()
        cand = _make_cand(auction_open_min_pct=3.0)
        q = _make_quote(open_p=10.0, pre_close=10.0)
        result = evaluate_all(cand, q)
        assert result["pass"] is False
        assert result["first_failure"] is not None

    @patch.multiple(
        "condition_evaluator",
        check_broken_and_fake_healing=MagicMock(return_value=(True, "ok")),
    )
    @patch("utils_chip.evaluate_chip_safety")
    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_auction_amount_filter(self, mock_fund, mock_chip) -> None:
        mock_chip.return_value = _chip_safe_mock()
        mock_fund.return_value = _fund_safe_mock()
        cand = _make_cand(auction_open_min_pct=0.0)
        q = _make_quote(open_p=10.0, pre_close=10.0, price=10.0,
                        auction_amount=200_000)
        result = evaluate_all(cand, q)
        assert result["pass"] is False
        assert "竞价金额" in result["first_failure"]

    @patch.multiple(
        "condition_evaluator",
        check_broken_and_fake_healing=MagicMock(return_value=(True, "ok")),
    )
    @patch("utils_chip.evaluate_chip_safety")
    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_speed_filter(self, mock_fund, mock_chip) -> None:
        mock_chip.return_value = _chip_safe_mock()
        mock_fund.return_value = _fund_safe_mock()
        cand = _make_cand(auction_open_min_pct=0.0)
        q = _make_quote(open_p=10.0, pre_close=10.0, price=10.0,
                        speed_pct_3min=8.0)
        result = evaluate_all(cand, q)
        assert result["pass"] is False
        assert "涨速" in result["first_failure"]

    @patch.multiple(
        "condition_evaluator",
        check_broken_and_fake_healing=MagicMock(return_value=(True, "ok")),
    )
    @patch("utils_chip.evaluate_chip_safety")
    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_index_meltdown(self, mock_fund, mock_chip) -> None:
        mock_chip.return_value = _chip_safe_mock()
        mock_fund.return_value = _fund_safe_mock()
        cand = _make_cand()
        idx_q = _make_quote(price=9.0, pre_close=10.0)
        indices = {"000001.SH": idx_q, "399001.SZ": idx_q,
                   "399006.SZ": idx_q, "000688.SH": idx_q}
        result = evaluate_all(cand, index_quotes=indices)
        assert result["pass"] is False
        assert "熔断" in result["first_failure"]

    @patch.multiple(
        "condition_evaluator",
        check_broken_and_fake_healing=MagicMock(return_value=(True, "ok")),
    )
    @patch("utils_chip.evaluate_chip_safety")
    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_sector_deviation_limit_up_bad_sector(
        self, mock_fund, mock_chip,
    ) -> None:
        mock_chip.return_value = _chip_safe_mock()
        mock_fund.return_value = _fund_safe_mock()
        cand = _make_cand(auction_open_min_pct=0.0)
        q = _make_quote(price=10.98, pre_close=10.0)
        sector = _make_quote(price=9.7, pre_close=10.0)
        result = evaluate_all(cand, q, sector_quote=sector)
        assert result["pass"] is False
        assert "板块偏离" in result["first_failure"]

    @patch.multiple(
        "condition_evaluator",
        check_broken_and_fake_healing=MagicMock(return_value=(True, "ok")),
    )
    @patch("utils_chip.evaluate_chip_safety")
    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_sentinel_dependency(self, mock_fund, mock_chip) -> None:
        mock_chip.return_value = _chip_safe_mock()
        mock_fund.return_value = _fund_safe_mock()
        dep = {"symbol": "000300.SH", "min_auction_open_pct": 2.0}
        cand = _make_cand(auction_open_min_pct=0.0, dependency_anchor=dep)
        q = _make_quote(open_p=10.0, pre_close=10.0, price=10.0)
        sentinel = {"000300.SH": _make_quote(open_p=10.05, pre_close=10.0)}
        result = evaluate_all(cand, q, sentinel_quotes=sentinel)
        assert result["pass"] is False
        assert "锚定" in result["first_failure"]

    @patch.multiple(
        "condition_evaluator",
        check_broken_and_fake_healing=MagicMock(return_value=(True, "ok")),
    )
    @patch("utils_broken_guard.compute_limit_pct")
    def test_sell_candidate_trailing_and_scale(self, mock_limit) -> None:
        mock_limit.return_value = 9.9
        pos = {"cost_price": 10.0, "symbol": "000001.SZ"}
        cand = _make_cand(
            direction="sell", position=pos,
            watermark={"high_watermark_price": 11.0, "high_watermark_pct": 10.0},
        )
        q = _make_quote(price=10.8, pre_close=10.0, high=11.0)
        result = evaluate_all(cand, q)
        assert "trailing_profit" in result["checks"]
        assert "scale_out" in result["checks"]

    @patch.multiple(
        "condition_evaluator",
        check_broken_and_fake_healing=MagicMock(return_value=(True, "ok")),
    )
    @patch("utils_chip.evaluate_chip_safety")
    @patch("utils_fund_flow.evaluate_fund_flow_safety")
    def test_weak_sector_fake_strength(self, mock_fund, mock_chip) -> None:
        mock_chip.return_value = _chip_safe_mock()
        mock_fund.return_value = _fund_safe_mock()
        cand = _make_cand(auction_open_min_pct=0.0)
        q = _make_quote(price=10.4, pre_close=10.0)
        sector = _make_quote(price=9.7, pre_close=10.0)
        result = evaluate_all(cand, q, sector_quote=sector)
        assert result["pass"] is False
        assert "弱势板块" in result["first_failure"]
