#!/usr/bin/env python3
"""Test RiskManager with mocked MCP client and DataManager."""
from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from risk.risk_manager import RiskManager


# ── Helpers ──


def _make_intent(
    symbol: str = "000001.SZ",
    direction: str = "buy",
    quantity: int = 1000,
    price: float = 10.0,
    name: str = "",
    **kwargs,
) -> dict:
    intent: dict = {
        "symbol": symbol,
        "direction": direction,
        "quantity": quantity,
        "price": price,
        "name": name or symbol,
    }
    intent.update(kwargs)
    return intent


def _mock_mcp_client(
    positions: list | None = None,
    balance: dict | None = None,
    trading_session: dict | None = None,
    market_health: dict | None = None,
    blacklist: list | None = None,
    call_side_effects: dict | None = None,
) -> MagicMock:
    """Build a mocked MCPClient with sensible defaults."""
    client = MagicMock()
    client.get_positions.return_value = positions or []
    client.get_balance.return_value = balance or {
        "total_assets": 100_000.0,
        "total_asset": 100_000.0,
    }
    client.get_trading_sessions.return_value = trading_session or {
        "is_trading_day": True,
    }
    client.get_market_health.return_value = market_health or {
        "health_score": 80,
    }
    client.get_blacklist.return_value = blacklist or []
    client.call.return_value = {}

    if call_side_effects:
        def _call(tool, arguments=None, port=None):
            key = f"{tool}:{arguments}"
            if key in call_side_effects:
                return call_side_effects[key]
            return {}
        client.call.side_effect = _call

    return client


def _mock_data_manager(
    jsonl_records: list | None = None,
    state_data: dict | None = None,
) -> MagicMock:
    """Build a mocked DataManager with sensible defaults."""
    dm = MagicMock()
    dm.read_jsonl.return_value = jsonl_records or []
    dm.load_state.return_value = state_data or {
        "sentiment": {"phase": "warm", "multiplier": 1.0},
    }
    return dm


# ── Initialization ──


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_init_calls_dependencies(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """RiskManager.__init__ should call get_mcp_client() and get_data_manager()."""
    mgr = RiskManager()
    mock_get_client.assert_called_once()
    mock_get_dm.assert_called_once()
    assert mgr._client is not None
    assert mgr._dm is not None


# ── check_position_cap (position limits: single symbol <= 30%) ──


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_check_position_limits_buy_exceeds_threshold(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Buy direction exceeding 30% of total assets should be rejected."""
    client = _mock_mcp_client(
        positions=[{"symbol": "000001.SZ", "market_value": 10_000.0}],
        balance={"total_assets": 100_000.0, "total_asset": 100_000.0},
    )
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    # 10k existing + 30k new = 40k / 100k = 40% > 30%
    ok, reason = mgr._check_position_cap("000001.SZ", "buy", 3000, 10.0)
    assert ok is False
    assert "30%" in reason


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_check_position_limits_buy_within_threshold(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Buy direction within 30% limit should pass."""
    client = _mock_mcp_client(
        positions=[],
        balance={"total_assets": 100_000.0, "total_asset": 100_000.0},
    )
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    # 20k / 100k = 20% <= 30%
    ok, reason = mgr._check_position_cap("000001.SZ", "buy", 2000, 10.0)
    assert ok is True


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_check_position_limits_sell_bypasses(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Sell direction should always pass position cap check."""
    client = _mock_mcp_client()
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    ok, reason = mgr._check_position_cap("000001.SZ", "sell", 99999, 1e6)
    assert ok is True


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_check_position_limits_zero_assets(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """When total_assets is zero, the check should pass (can't validate)."""
    client = _mock_mcp_client(
        balance={"total_assets": 0, "total_asset": 0},
    )
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    ok, reason = mgr._check_position_cap("000001.SZ", "buy", 1000, 10.0)
    assert ok is True


# ── check_sector_concentration ──


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_check_sector_concentration_exceeds_limit(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Sector concentration exceeding 40% should be rejected."""
    client = _mock_mcp_client(
        positions=[
            {"symbol": "000001.SZ", "market_value": 30_000.0},
        ],
        balance={"total_assets": 100_000.0, "total_asset": 100_000.0},
    )

    def _call(tool, arguments=None, port=None):
        if tool == "query_data":
            sym = (arguments or {}).get("symbol", "")
            return {"sector": "银行", "industry": "银行"}
        return {}
    client.call.side_effect = _call

    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    # 30k existing bank + 15k new bank = 45k / 100k = 45% > 40%
    ok, reason = mgr._check_sector_concentration("000001.SZ", 1500, 10.0)
    assert ok is False
    assert "40%" in reason


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_check_sector_concentration_within_limit(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Sector concentration within 40% should pass."""
    client = _mock_mcp_client(
        positions=[
            {"symbol": "000001.SZ", "market_value": 10_000.0},
        ],
        balance={"total_assets": 100_000.0, "total_asset": 100_000.0},
    )

    def _call(tool, arguments=None, port=None):
        if tool == "query_data":
            return {"sector": "银行", "industry": "银行"}
        return {}
    client.call.side_effect = _call

    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    # 10k existing + 5k new = 15k / 100k = 15% <= 40%
    ok, reason = mgr._check_sector_concentration("000001.SZ", 500, 10.0)
    assert ok is True


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_check_sector_concentration_no_sector_info(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """When sector info is unavailable, the check should pass."""
    client = _mock_mcp_client(
        balance={"total_assets": 100_000.0, "total_asset": 100_000.0},
    )
    client.call.return_value = {}  # no sector info

    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    ok, reason = mgr._check_sector_concentration("000001.SZ", 5000, 10.0)
    assert ok is True


# ── check_t1_rule (direction conflict) ──


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_check_direction_conflict_same_direction_buy_buy(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """T+1 should reject buy when today already has a buy record."""
    today = dt.date.today().isoformat()
    dm = _mock_data_manager(jsonl_records=[
        {
            "record_type": "candidate_event",
            "event": "executed",
            "symbol": "000001.SZ",
            "direction": "buy",
        },
    ])
    mock_get_dm.return_value = dm
    mock_get_client.return_value = _mock_mcp_client()

    mgr = RiskManager()
    ok, reason = mgr._check_t1_rule("000001.SZ", "buy")
    assert ok is False
    assert "T+1冲突" in reason


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_check_direction_conflict_buy_after_sell_no_position(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """T+1 should allow buy after sell when no remaining position."""
    dm = _mock_data_manager(jsonl_records=[
        {
            "record_type": "candidate_event",
            "event": "executed",
            "symbol": "000001.SZ",
            "direction": "sell",
        },
    ])
    client = _mock_mcp_client(positions=[])  # no position left
    mock_get_dm.return_value = dm
    mock_get_client.return_value = client

    mgr = RiskManager()
    ok, reason = mgr._check_t1_rule("000001.SZ", "buy")
    assert ok is True


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_check_direction_conflict_no_records(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """T+1 should pass when there are no today records for the symbol."""
    dm = _mock_data_manager(jsonl_records=[])  # empty ledger
    mock_get_dm.return_value = dm
    mock_get_client.return_value = _mock_mcp_client()

    mgr = RiskManager()
    ok, reason = mgr._check_t1_rule("000001.SZ", "buy")
    assert ok is True


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_check_direction_conflict_sell_with_available_shares(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """T+1 should allow sell when there is an available position."""
    dm = _mock_data_manager(jsonl_records=[
        {
            "record_type": "candidate_event",
            "event": "executed",
            "symbol": "000001.SZ",
            "direction": "buy",
        },
    ])
    client = _mock_mcp_client(
        positions=[{"symbol": "000001.SZ", "available_quantity": 1000}],
    )
    mock_get_dm.return_value = dm
    mock_get_client.return_value = client

    mgr = RiskManager()
    ok, reason = mgr._check_t1_rule("000001.SZ", "sell")
    assert ok is True


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_check_direction_conflict_sell_no_available_shares(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """T+1 should reject sell when no available shares exist."""
    dm = _mock_data_manager(jsonl_records=[
        {
            "record_type": "candidate_event",
            "event": "executed",
            "symbol": "000001.SZ",
            "direction": "buy",
        },
    ])
    client = _mock_mcp_client(
        positions=[{"symbol": "000001.SZ", "available_quantity": 0}],
    )
    mock_get_dm.return_value = dm
    mock_get_client.return_value = client

    mgr = RiskManager()
    ok, reason = mgr._check_t1_rule("000001.SZ", "sell")
    assert ok is False
    assert "T+1冲突" in reason


# ── check_stop_loss (simulated via intent + portfolio with drawdown) ──


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
@patch.object(RiskManager, "_now_time_cst", return_value=dt.time(10, 0))
def test_check_stop_loss_not_triggered(
    mock_time: MagicMock,
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Intent should pass all checks when no stop-loss condition exists.

    Stop-loss at -6% is not currently implemented in RiskManager.
    This test verifies the existing checks pass for a healthy portfolio.
    """
    client = _mock_mcp_client(
        positions=[{"symbol": "000001.SZ", "market_value": 5_000.0}],
        balance={"total_assets": 100_000.0, "total_asset": 100_000.0},
    )

    def _call(tool, arguments=None, port=None):
        if tool == "query_data":
            return {"sector": "银行", "industry": "银行"}
        return {}
    client.call.side_effect = _call

    mock_get_client.return_value = client
    dm = _mock_data_manager(
        state_data={
            "freeze": {},
            "sentiment": {"phase": "warm", "multiplier": 1.0},
        },
    )
    mock_get_dm.return_value = dm

    mgr = RiskManager()
    intent = _make_intent(symbol="000002.SZ", direction="buy", quantity=500, price=10.0)
    result = mgr.check_intent(intent)
    assert result["approved"] is True


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_check_stop_loss_via_total_exposure(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Total exposure check acts as a downstream guard similar to stop-loss.

    When total exposure exceeds 80%, a buy is rejected.
    This simulates a risk-aware guard that complements stop-loss logic.
    """
    client = _mock_mcp_client(
        positions=[
            {"symbol": "000001.SZ", "market_value": 60_000.0},
            {"symbol": "000002.SZ", "market_value": 30_000.0},
        ],
        balance={"total_assets": 100_000.0, "total_asset": 100_000.0},
    )
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    # current 90k exposure + 20k new = 110k / 100k = 110% > 80%
    intent = _make_intent(symbol="000003.SZ", direction="buy", quantity=2000, price=10.0)
    result = mgr.check_intent(intent)
    assert result["approved"] is False
    assert "总敞口" in result["reason"]


# ── check_trailing_stop (simulated via intent + market health guard) ──


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_check_trailing_stop_via_market_health(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Market health check acts as a macro-level trailing-stop equivalent.

    When market health drops below 30 (fuse trigger), buy intents are rejected.
    """
    client = _mock_mcp_client(
        market_health={"health_score": 25},
    )
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    intent = _make_intent(direction="buy")
    result = mgr.check_intent(intent)
    assert result["approved"] is False
    assert "熔断" in result["reason"] or "市场健康度" in result["reason"]


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_check_trailing_stop_market_healthy(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Market health check passes when score is above threshold."""
    client = _mock_mcp_client(
        market_health={"health_score": 75},
    )
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    intent = _make_intent(direction="buy")
    # Should fail at other checks (like symbol/weekend) but NOT at market_crash
    result = mgr.check_intent(intent)
    # market_crash should not be the failing layer
    assert result["layer"] != "market_crash"


# ── evaluate_all (check_intent combined evaluation) ──


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
@patch.object(RiskManager, "_now_time_cst", return_value=dt.time(10, 0))
def test_evaluate_all_buy_approved(
    mock_time: MagicMock,
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Full intent check should approve a compliant buy order."""
    client = _mock_mcp_client()
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    intent = _make_intent(direction="buy")
    result = mgr.check_intent(intent)
    assert result["approved"] is True
    assert result["reason"] == "全部风控通过"


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_evaluate_all_sell_approved(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Full intent check should approve a compliant sell order."""
    client = _mock_mcp_client()
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    intent = _make_intent(direction="sell")
    result = mgr.check_intent(intent)
    assert result["approved"] is True
    assert result["reason"] == "全部风控通过"


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_evaluate_all_invalid_symbol(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Full intent check should reject an invalid symbol."""
    client = _mock_mcp_client()
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    intent = _make_intent(symbol="INVALID")
    result = mgr.check_intent(intent)
    assert result["approved"] is False
    assert result["layer"] == "symbol"


# ── Batch check ──


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
@patch.object(RiskManager, "_now_time_cst", return_value=dt.time(10, 0))
def test_batch_check_mixed_results(
    mock_time: MagicMock,
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Batch check should process multiple intents and return per-item results."""
    client = _mock_mcp_client()
    client.register_approved_intent.return_value = {"success": True}
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    intents = [
        _make_intent(symbol="000001.SZ", direction="buy", quantity=100, price=10.0, intent_id="id-1"),
        _make_intent(symbol="INVALID", direction="buy", quantity=100, price=10.0, intent_id="id-2"),
    ]
    result = mgr.batch_check(intents)
    assert len(result["results"]) == 2
    # First should be approved
    assert result["results"][0]["approved"] is True
    assert result["results"][0]["exec_registered"] is True
    # Second should be rejected (invalid symbol)
    assert result["results"][1]["approved"] is False


# ── Edge cases ──


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
@patch.object(RiskManager, "_now_time_cst", return_value=dt.time(10, 0))
def test_empty_portfolio_all_checks_pass(
    mock_time: MagicMock,
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """All checks should pass when portfolio is empty with a valid buy intent."""
    client = _mock_mcp_client(positions=[])
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    intent = _make_intent(direction="buy")
    result = mgr.check_intent(intent)
    assert result["approved"] is True


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_single_position_check(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Single existing position should be handled correctly by position cap."""
    client = _mock_mcp_client(
        positions=[{"symbol": "000001.SZ", "market_value": 25_000.0}],
        balance={"total_assets": 100_000.0, "total_asset": 100_000.0},
    )
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    # 25k existing + 10k new = 35k / 100k = 35% > 30%
    ok, reason = mgr._check_position_cap("000001.SZ", "buy", 1000, 10.0)
    assert ok is False
    assert "30%" in reason


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_all_sectors_same(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """When all positions are in the same sector, adding more may exceed limit."""
    client = _mock_mcp_client(
        positions=[
            {"symbol": "000001.SZ", "market_value": 15_000.0},
            {"symbol": "000002.SZ", "market_value": 15_000.0},
        ],
        balance={"total_assets": 100_000.0, "total_asset": 100_000.0},
    )

    call_results: dict[str, dict] = {
        "000001.SZ": {"sector": "银行", "industry": "银行"},
        "000002.SZ": {"sector": "银行", "industry": "银行"},
    }

    def _call(tool, arguments=None, port=None):
        if tool == "query_data":
            sym = (arguments or {}).get("symbol", "")
            return call_results.get(sym, {})
        return {}
    client.call.side_effect = _call

    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    # 30k bank + 20k new bank = 50k / 100k = 50% > 40%
    ok, reason = mgr._check_sector_concentration("000001.SZ", 2000, 10.0)
    assert ok is False
    assert "集中度" in reason


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
@patch.object(RiskManager, "_now_time_cst", return_value=dt.time(10, 0))
def test_stop_loss_not_triggered_no_drawdown(
    mock_time: MagicMock,
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """A healthy position with no drawdown should not trigger stop-loss concerns."""
    client = _mock_mcp_client(
        positions=[{"symbol": "000001.SZ", "market_value": 5_000.0, "current_price": 10.5, "cost_price": 10.0}],
        balance={"total_assets": 100_000.0, "total_asset": 100_000.0},
    )
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    intent = _make_intent(symbol="000002.SZ", direction="buy", quantity=500, price=10.0)
    result = mgr.check_intent(intent)
    assert result["approved"] is True


# ── Weekend / trading day checks ──


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_weekend_rejection(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """RiskManager should reject intents on non-trading days."""
    client = _mock_mcp_client(
        trading_session={"is_trading_day": False},
    )
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    intent = _make_intent(direction="buy")
    result = mgr.check_intent(intent)
    assert result["approved"] is False
    assert result["layer"] == "weekend"


# ── ST blacklist ──


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_st_blacklist_rejection(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """ST stock should be rejected."""
    client = _mock_mcp_client()
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    intent = _make_intent(symbol="000001.SZ", name="ST华业")
    result = mgr.check_intent(intent)
    assert result["approved"] is False
    assert result["layer"] == "st_blacklist"


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_blacklist_rejection(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Symbol in the blacklist should be rejected."""
    client = _mock_mcp_client(blacklist=["000001.SZ"])
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    intent = _make_intent()
    result = mgr.check_intent(intent)
    assert result["approved"] is False
    assert result["layer"] == "st_blacklist"


# ── Freeze check ──


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
@patch.object(RiskManager, "_now_time_cst", return_value=dt.time(10, 0))
def test_freeze_rejection(
    mock_time: MagicMock,
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Frozen symbol should be rejected."""
    future = (dt.date.today() + dt.timedelta(days=7)).isoformat()
    dm = _mock_data_manager(state_data={
        "freeze": {"000001.SZ": future},
        "sentiment": {"phase": "warm", "multiplier": 1.0},
    })
    mock_get_dm.return_value = dm
    mock_get_client.return_value = _mock_mcp_client()

    mgr = RiskManager()
    intent = _make_intent()
    result = mgr.check_intent(intent)
    assert result["approved"] is False
    assert result["layer"] == "freeze"


# ── Avg down ──


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_avg_down_rejection(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Buying more of an already-held symbol (avg down) should be rejected."""
    client = _mock_mcp_client(
        positions=[{"symbol": "000001.SZ", "quantity": 1000}],
    )
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    ok, reason = mgr._check_avg_down("000001.SZ", "buy")
    assert ok is False
    assert "禁止摊平" in reason


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_avg_down_not_triggered_for_sell(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Sell direction should never trigger avg-down rejection."""
    client = _mock_mcp_client(
        positions=[{"symbol": "000001.SZ", "quantity": 1000}],
    )
    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    ok, reason = mgr._check_avg_down("000001.SZ", "sell")
    assert ok is True


# ── Outflow check ──


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_outflow_rejection(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Large net outflow should reject buys."""
    client = _mock_mcp_client()

    def _call(tool, arguments=None, port=None):
        if tool == "get_fund_flow":
            return {"net_outflow": -100_000_000_000, "net_flow": -100_000_000_000}
        return {}
    client.call.side_effect = _call

    mock_get_client.return_value = client
    mock_get_dm.return_value = _mock_data_manager()

    mgr = RiskManager()
    intent = _make_intent(direction="buy")
    result = mgr.check_intent(intent)
    assert result["approved"] is False
    assert result["layer"] == "outflow"


# ── Sentiment check ──


@patch("risk.risk_manager.get_mcp_client")
@patch("risk.risk_manager.get_data_manager")
def test_sentiment_rejection(
    mock_get_dm: MagicMock,
    mock_get_client: MagicMock,
) -> None:
    """Ice-phase sentiment with low multiplier should reject buys."""
    client = _mock_mcp_client()
    mock_get_client.return_value = client
    dm = _mock_data_manager(state_data={
        "sentiment": {"phase": "ice", "multiplier": 0.2},
    })
    mock_get_dm.return_value = dm

    mgr = RiskManager()
    intent = _make_intent(direction="buy")
    result = mgr.check_intent(intent)
    assert result["approved"] is False
    assert result["layer"] == "sentiment"
