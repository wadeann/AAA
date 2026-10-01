#!/usr/bin/env python3
"""Test market_regime_check — intraday_dynamic_check and iron_rule_gate.

Mocks MCP client, file I/O, strategy circuit breaker, and leader universe.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import market_regime_check as mrc
from market_regime_check import intraday_dynamic_check, iron_rule_gate


# ── Helpers ──

CST = dt.timezone(dt.timedelta(hours=8))


def _candidate(
    symbol: str = "600000.SH",
    direction: str = "buy",
    catalyst_type: str = "default",
    **kwargs,
) -> dict:
    cand: dict = {
        "symbol": symbol,
        "direction": direction,
        "catalyst_type": catalyst_type,
    }
    cand.update(kwargs)
    return cand


def _normal_quotes() -> dict:
    """Market-wide quotes where nothing is crashing."""
    return {
        "000001.SH": {"change_pct": 0.3, "name": "上证指数"},
        "399001.SZ": {"change_pct": 0.2, "name": "深证成指"},
        "399006.SZ": {"change_pct": -0.1, "name": "创业板指"},
        "000688.SH": {"change_pct": 0.8, "name": "科创50"},
    }


def _crash_quotes(broad_pct: float = -3.0, star_pct: float = -4.0) -> dict:
    """Quotes with both broad and STAR indices crashing."""
    return {
        "000001.SH": {"change_pct": broad_pct, "name": "上证指数"},
        "399001.SZ": {"change_pct": broad_pct + 0.2, "name": "深证成指"},
        "399006.SZ": {"change_pct": broad_pct + 0.5, "name": "创业板指"},
        "000688.SH": {"change_pct": star_pct, "name": "科创50"},
    }


# ── Fixtures ──


@pytest.fixture(autouse=True)
def path_exists():
    """Make Path.exists() return True everywhere.

    This lets iron_rule_gate hit the _read_json_safe mock instead of falling
    back to defaults.  Individual tests can override locally if needed.
    """
    with patch.object(Path, "exists", return_value=True):
        yield


@pytest.fixture
def mock_env():
    """Core mocks: MCP client, file I/O, strategy CB, leader universe.

    Yields a simple namespace with:
      .client     — the mocked MCPClient instance
      .read       — the mocked _read_json_safe
      .write      — the mocked _write_json_safe
      .regime     — mutable dict returned by _read_json_safe when reading regime file
      .cfg        — mutable dict returned by _read_json_safe when reading config file
      .cb         — the mocked check_strategy
    """
    regime: dict = {}
    cfg: dict = {}

    def _side_effect(path):
        if "strategy_params" in str(path):
            return cfg
        return regime

    with patch("market_regime_check.get_mcp_client") as mock_get, \
         patch("market_regime_check._read_json_safe", side_effect=_side_effect) as mock_read, \
         patch("market_regime_check._write_json_safe") as mock_write, \
         patch("market_regime_check.check_strategy", return_value=(False, "PASS")) as mock_cb, \
         patch("market_regime_check.get_leader_universe", return_value=[]):
        client = MagicMock()
        mock_get.return_value = client

        yield SimpleNamespace(
            client=client, read=mock_read, write=mock_write,
            cb=mock_cb, regime=regime, cfg=cfg,
        )


class SimpleNamespace:
    """Lightweight alternative to types.SimpleNamespace (avoids extra import)."""
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


# ═══════════════════════════════════════════════════════════════
#  intraday_dynamic_check
# ═══════════════════════════════════════════════════════════════


class TestIntradayDynamicCheck:
    """Tests for intraday_dynamic_check()."""

    def test_limitdown_tripped(self, mock_env):
        """limitdown_count >= 20 trips immediately."""
        tripped, details = intraday_dynamic_check(
            market_metrics={"limitdown_count": 20},
        )
        assert tripped is True
        assert any("跌停" in r for r in details["reasons"])
        assert details["limitdown_count"] == 20

    def test_limitdown_above_20_still_trips(self, mock_env):
        """limitdown_count > 20 also trips."""
        tripped, details = intraday_dynamic_check(
            market_metrics={"limitdown_count": 35},
        )
        assert tripped is True

    def test_broken_seal_tripped(self, mock_env):
        """broken_seal_rate >= 45% trips."""
        tripped, details = intraday_dynamic_check(
            market_metrics={"broken_seal_rate": 50.0},
        )
        assert tripped is True
        assert any("炸板率" in r for r in details["reasons"])
        assert details["broken_seal_rate"] == 50.0

    def test_broken_seal_at_threshold_trips(self, mock_env):
        """broken_seal_rate exactly 45.0 trips."""
        tripped, details = intraday_dynamic_check(
            market_metrics={"broken_seal_rate": 45.0},
        )
        assert tripped is True

    def test_broad_index_crash_trips(self, mock_env):
        """A broad index (SH/SZ/ChiNext) dropping >= 2% trips."""
        quotes = {
            "000001.SH": {"change_pct": -2.5, "name": "上证指数"},
            "399001.SZ": {"change_pct": -1.0, "name": "深证成指"},
            "399006.SZ": {"change_pct": -0.5, "name": "创业板指"},
            "000688.SH": {"change_pct": -0.3, "name": "科创50"},
        }
        tripped, details = intraday_dynamic_check(quotes=quotes)
        assert tripped is True
        assert any("宽基" in r for r in details["reasons"])
        assert details["index_changes"]["000001.SH"] == -2.5

    def test_multiple_broad_indices_crash(self, mock_env):
        """Multiple broad indices below -2% gets multiple trip reasons."""
        quotes = {
            "000001.SH": {"change_pct": -3.1, "name": "上证指数"},
            "399001.SZ": {"change_pct": -2.5, "name": "深证成指"},
            "399006.SZ": {"change_pct": -2.2, "name": "创业板指"},
            "000688.SH": {"change_pct": -0.5, "name": "科创50"},
        }
        tripped, details = intraday_dynamic_check(quotes=quotes)
        assert tripped is True
        broad_reasons = [r for r in details["reasons"] if "宽基" in r]
        assert len(broad_reasons) >= 2

    def test_isolated_star_crash(self, mock_env):
        """Only STAR drops >= 2%, broad indices > -1%, no limitdown/broken -> scope STAR_ONLY."""
        mock_env.regime["description"] = "something without 科创50"
        quotes = {
            "000001.SH": {"change_pct": -0.5, "name": "上证指数"},
            "399001.SZ": {"change_pct": -0.3, "name": "深证成指"},
            "399006.SZ": {"change_pct": -0.8, "name": "创业板指"},
            "000688.SH": {"change_pct": -3.5, "name": "科创50"},
        }
        tripped, details = intraday_dynamic_check(
            quotes=quotes,
            market_metrics={"limitdown_count": 5, "broken_seal_rate": 20.0},
        )
        assert details["isolated_star_crash"] is True
        assert details["scope"] == "STAR_ONLY"
        assert "STAR" in details["blocked_market_types"]
        assert tripped is False

    def test_isolated_star_crash_with_preexisting_star_reason(self, mock_env):
        """When old_reason includes 科创50, the regime file is rewritten."""
        mock_env.regime["description"] = "previously 科创50 isolated"
        mock_env.cfg["sentiment"] = {"description": "some sentiment"}
        quotes = {
            "000001.SH": {"change_pct": -0.5, "name": "上证指数"},
            "399001.SZ": {"change_pct": -0.3, "name": "深证成指"},
            "399006.SZ": {"change_pct": -0.8, "name": "创业板指"},
            "000688.SH": {"change_pct": -3.5, "name": "科创50"},
        }
        tripped, details = intraday_dynamic_check(
            quotes=quotes,
            market_metrics={"limitdown_count": 5, "broken_seal_rate": 20.0},
        )
        assert details["isolated_star_crash"] is True
        # _write_json_safe should have been called (regime file rewritten)
        mock_env.write.assert_called()
        # Verify the regime write contained STAR blocking
        call_args_list = mock_env.write.call_args_list
        regime_writes = [
            args for args, _ in call_args_list
            if "market_regime" in str(args[0])
        ]
        assert len(regime_writes) >= 1
        written = regime_writes[0][1]
        assert written["blocked_market_types"] == ["STAR"]

    def test_star_crash_with_broad_contamination_not_isolated(self, mock_env):
        """STAR crash with some broad index below -1% -> NOT isolated, trips."""
        quotes = {
            "000001.SH": {"change_pct": -0.5, "name": "上证指数"},
            "399001.SZ": {"change_pct": -1.2, "name": "深证成指"},
            "399006.SZ": {"change_pct": -0.3, "name": "创业板指"},
            "000688.SH": {"change_pct": -3.0, "name": "科创50"},
        }
        tripped, details = intraday_dynamic_check(
            quotes=quotes,
            market_metrics={"limitdown_count": 5, "broken_seal_rate": 20.0},
        )
        assert details["isolated_star_crash"] is False
        assert tripped is True
        assert any("科创50" in r for r in details["reasons"])

    def test_suspicious_data_limitdown_zero_with_crash(self, mock_env):
        """limitdown=0 alongside broad index crash -> suspicious / fail-closed."""
        quotes = _crash_quotes(broad_pct=-2.5, star_pct=-1.0)
        tripped, details = intraday_dynamic_check(
            quotes=quotes,
            market_metrics={"limitdown_count": 0, "broken_seal_rate": 10.0},
        )
        assert tripped is True
        assert any("数据失真" in r for r in details["reasons"])
        # fail_closed is written to the regime file, not returned in details
        call_args_list = mock_env.write.call_args_list
        regime_writes = [args for args, _ in call_args_list if "market_regime" in str(args[0])]
        assert len(regime_writes) >= 1
        assert regime_writes[0][1]["fail_closed"] is True

    def test_normal_market_passes(self, mock_env):
        """Nothing trips under normal conditions."""
        tripped, details = intraday_dynamic_check(
            quotes=_normal_quotes(),
            market_metrics={"limitdown_count": 5, "broken_seal_rate": 20.0},
        )
        assert tripped is False
        assert details["scope"] == "NONE"
        assert details["blocked_market_types"] == []

    def test_limitdown_from_mcp_fallback(self, mock_env):
        """When market_metrics lacks limitdown, MCP client is queried."""
        mock_env.client.get_market_health.return_value = {
            "limitdown_count": 25, "broken_seal_rate": 10.0,
        }
        tripped, details = intraday_dynamic_check(market_metrics={})
        assert tripped is True
        assert any("跌停" in r for r in details["reasons"])

    def test_broken_rate_from_mcp_fallback(self, mock_env):
        """When market_metrics lacks broken_seal_rate, MCP client is queried."""
        mock_env.client.get_market_health.return_value = {
            "limitdown_count": 5, "broken_seal_rate": 60.0,
        }
        tripped, details = intraday_dynamic_check(market_metrics={})
        assert tripped is True
        assert any("炸板率" in r for r in details["reasons"])

    def test_mcp_fallback_failure_uses_zero(self, mock_env):
        """When MCP call fails, values default to 0 (no trip)."""
        mock_env.client.get_market_health.side_effect = Exception("MCP down")
        tripped, details = intraday_dynamic_check(
            market_metrics={},
            quotes=_normal_quotes(),
        )
        assert tripped is False
        assert details["limitdown_count"] == 0
        assert details["broken_seal_rate"] == 0.0

    def test_index_queries_from_mcp_when_missing(self, mock_env):
        """When quotes dict lacks index symbols, MCP query_quotes is used."""
        mock_env.client.query_quotes.return_value = {
            "000001.SH": {"change_pct": -3.0, "name": "上证指数"},
        }
        tripped, details = intraday_dynamic_check(
            quotes={},
            market_metrics={"limitdown_count": 5, "broken_seal_rate": 20.0},
        )
        assert tripped is True
        assert any("宽基" in r for r in details["reasons"])

    def test_tripped_writes_regime_and_config(self, mock_env):
        """When tripped, regime and config files are written with 极寒 / sell_only_mode."""
        quotes = _crash_quotes(broad_pct=-2.5, star_pct=-1.0)
        tripped, details = intraday_dynamic_check(
            quotes=quotes,
            market_metrics={"limitdown_count": 25, "broken_seal_rate": 30.0},
        )
        assert tripped is True
        call_args_list = mock_env.write.call_args_list
        regime_writes = [
            args for args, _ in call_args_list
            if "market_regime" in str(args[0])
        ]
        assert len(regime_writes) >= 1
        written_regime = regime_writes[0][1]
        assert written_regime["regime"] == "极寒"
        assert written_regime["sell_only_mode"] is True


# ═══════════════════════════════════════════════════════════════
#  iron_rule_gate
# ═══════════════════════════════════════════════════════════════


class TestIronRuleGate:
    """Tests for iron_rule_gate()."""

    # ── Sell bypass ──

    def test_sell_bypasses_all_checks(self, mock_env):
        """Sell direction always passes."""
        ok, msg = iron_rule_gate(_candidate(direction="sell"))
        assert ok is True
        assert "卖出" in msg

    # ── Regime: 极寒 / freezing ──

    def test_regime_极寒_rejected(self, mock_env):
        """Regime == '极寒' blocks the trade."""
        mock_env.regime["regime"] = "极寒"
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate())
        assert ok is False
        assert "极寒" in msg

    def test_regime_freezing_rejected(self, mock_env):
        """Regime == 'freezing' blocks the trade."""
        mock_env.regime["regime"] = "freezing"
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate())
        assert ok is False
        assert "极寒" in msg or "freezing" in msg

    def test_standard_regime_freezing_rejected(self, mock_env):
        """standard_regime == 'freezing' blocks even if regime key is different."""
        mock_env.regime["regime"] = "震荡"
        mock_env.regime["standard_regime"] = "freezing"
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate())
        assert ok is False
        assert "极寒" in msg

    def test_non_trading_day_rejected(self, mock_env):
        """Regime == '非交易日' blocks the trade."""
        mock_env.regime["regime"] = "非交易日"
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate())
        assert ok is False

    # ── fail_closed ──

    def test_fail_closed_rejected(self, mock_env):
        """fail_closed=True blocks regardless of regime."""
        mock_env.regime["regime"] = "震荡"
        mock_env.regime["data_fresh"] = True
        mock_env.regime["fail_closed"] = True
        ok, msg = iron_rule_gate(_candidate())
        assert ok is False
        assert "Fail-Closed" in msg

    # ── Stale data ──

    def test_stale_data_rejected(self, mock_env):
        """data_fresh=False blocks the trade."""
        mock_env.regime["regime"] = "震荡"
        mock_env.regime["data_fresh"] = False
        ok, msg = iron_rule_gate(_candidate())
        assert ok is False
        assert "缓存陈旧" in msg

    # ── panic_ebb subtype ──

    def test_panic_ebb_blocks_all(self, mock_env):
        """ebb_subtype == 'panic_ebb' blocks all buying."""
        mock_env.regime["regime"] = "退潮"
        mock_env.regime["standard_regime"] = "panic_ebb"
        mock_env.regime["ebb_subtype"] = "panic_ebb"
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate())
        assert ok is False
        assert "恐慌" in msg

    def test_panic_ebb_via_regime_key(self, mock_env):
        """Regime key directly equals 'panic_ebb'."""
        mock_env.regime["regime"] = "panic_ebb"
        mock_env.regime["standard_regime"] = "panic_ebb"
        mock_env.regime["ebb_subtype"] = "panic_ebb"
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate())
        assert ok is False

    # ── exhaustion_ebb subtype ──

    def test_exhaustion_ebb_allows_first_board(self, mock_env):
        """exhaustion_ebb allows first-board buys (no streak, no chasing)."""
        mock_env.regime["regime"] = "退潮"
        mock_env.regime["standard_regime"] = "panic_ebb"
        mock_env.regime["ebb_subtype"] = "exhaustion_ebb"
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate(
            symbol="600000.SH",
            quote={"change_pct": 1.0},
        ))
        assert ok is True
        assert "PASS" in msg

    def test_exhaustion_ebb_rejects_multi_board(self, mock_env):
        """exhaustion_ebb rejects stocks with streak > 1."""
        mock_env.regime["regime"] = "退潮"
        mock_env.regime["standard_regime"] = "panic_ebb"
        mock_env.regime["ebb_subtype"] = "exhaustion_ebb"
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate(
            symbol="600000.SH",
            streak=2,
            quote={"change_pct": 1.0},
        ))
        assert ok is False
        assert "首板" in msg

    def test_exhaustion_ebb_rejects_chasing(self, mock_env):
        """exhaustion_ebb rejects buys with change_pct >= 1.5%."""
        mock_env.regime["regime"] = "退潮"
        mock_env.regime["standard_regime"] = "panic_ebb"
        mock_env.regime["ebb_subtype"] = "exhaustion_ebb"
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate(
            symbol="600000.SH",
            quote={"change_pct": 2.0},
        ))
        assert ok is False
        assert "追高" in msg

    # ── Non-sector-leader during 退潮 ──

    def test_non_leader_during_ebb_rejected(self, mock_env):
        """Non-sector-leader during 退潮 (without panic/exhaustion subtype) is rejected."""
        mock_env.regime["regime"] = "退潮"
        mock_env.regime["standard_regime"] = ""
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate(
            symbol="600000.SH",
            is_sector_leader=False,
            is_dragon=False,
        ))
        assert ok is False
        assert "非身位第一龙头" in msg or "跟风" in msg

    def test_leader_during_ebb_passes(self, mock_env):
        """Sector leader during 退潮 without panic sub-type may pass (if not chasing)."""
        mock_env.regime["regime"] = "退潮"
        mock_env.regime["standard_regime"] = ""
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate(
            symbol="600000.SH",
            is_sector_leader=True,
            is_dragon=False,
            quote={"change_pct": 0.5},
        ))
        assert ok is True
        assert "PASS" in msg

    # ── Garbage time filtering ──

    def test_garbage_time_non_leader_rejected(self, mock_env):
        """Garbage time (10:00-14:30) blocks non-leader buys."""
        garbage_time = dt.datetime(2026, 10, 1, 11, 0, tzinfo=CST)
        mock_env.regime["regime"] = "震荡"
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate(
            symbol="600000.SH",
            is_sector_leader=False,
            is_dragon=False,
            quote={"change_pct": 0.5},
        ), now_cst=garbage_time)
        assert ok is False
        assert "垃圾时间" in msg

    def test_garbage_time_leader_passes(self, mock_env):
        """Garbage time allows true dragon leader (score >=10, sector support)."""
        garbage_time = dt.datetime(2026, 10, 1, 11, 0, tzinfo=CST)
        mock_env.regime["regime"] = "震荡"
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate(
            symbol="600000.SH",
            is_sector_leader=True,
            is_dragon=True,
            dragon_score=12,
            has_sector_support=True,
            quote={"change_pct": 0.5},
        ), now_cst=garbage_time)
        assert ok is True
        assert "PASS" in msg

    def test_garbage_time_chasing_non_dragon_rejected(self, mock_env):
        """Garbage time chasing (>1.5%) without true dragon status is rejected."""
        garbage_time = dt.datetime(2026, 10, 1, 11, 0, tzinfo=CST)
        mock_env.regime["regime"] = "震荡"
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate(
            symbol="600000.SH",
            is_sector_leader=True,
            is_dragon=False,
            quote={"change_pct": 2.0},
        ), now_cst=garbage_time)
        assert ok is False
        assert "垃圾时间追涨" in msg

    def test_outside_garbage_time_passes(self, mock_env):
        """Outside 10:00-14:30, garbage time rules don't apply."""
        early_time = dt.datetime(2026, 10, 1, 9, 35, tzinfo=CST)
        mock_env.regime["regime"] = "震荡"
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate(
            symbol="600000.SH",
            is_sector_leader=False,
            quote={"change_pct": 0.5},
        ), now_cst=early_time)
        assert ok is True
        assert "PASS" in msg

    # ── Intraday check (re-tripped by iron_rule_gate) ──

    def test_intraday_trip_blocks_via_iron_gate(self, mock_env):
        """If intraday_dynamic_check trips, iron_rule_gate returns the trip reason."""
        cand = _candidate(market_metrics={"limitdown_count": 25})
        ok, msg = iron_rule_gate(cand)
        assert ok is False
        assert "铁律熔断" in msg

    def test_star_blocked_market_type_rejected(self, mock_env):
        """STAR symbol is rejected when blocked_market_types includes STAR."""
        quotes = {
            "000001.SH": {"change_pct": -0.5, "name": "上证指数"},
            "399001.SZ": {"change_pct": -0.3, "name": "深证成指"},
            "399006.SZ": {"change_pct": -0.8, "name": "创业板指"},
            "000688.SH": {"change_pct": -3.5, "name": "科创50"},
        }
        cand = _candidate(
            symbol="688001.SH",
            market_metrics={"limitdown_count": 5, "broken_seal_rate": 20.0},
            index_quotes=quotes,
        )
        ok, msg = iron_rule_gate(cand)
        assert ok is False
        assert "科创板隔离" in msg

    # ── Normal pass ──

    def test_normal_pass(self, mock_env):
        """All checks pass under normal conditions."""
        mock_env.regime["regime"] = "震荡"
        mock_env.regime["data_fresh"] = True
        ok, msg = iron_rule_gate(_candidate(
            symbol="600000.SH",
            quote={"change_pct": 0.5},
        ))
        assert ok is True
        assert "PASS" in msg

    # ── Missing regime file ──

    def test_missing_regime_file_defaults_to_normal(self, mock_env):
        """With no regime file, defaults to '震荡' and passes (if all else ok)."""
        with patch.object(Path, "exists", return_value=False):
            ok, msg = iron_rule_gate(_candidate(
                symbol="600000.SH",
                quote={"change_pct": 0.5},
            ))
        assert ok is True
        assert "PASS" in msg
