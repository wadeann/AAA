#!/usr/bin/env python3
"""Test MCPClient import and instantiation (no server required)."""
from __future__ import annotations

from mcp_client import MCPClient, get_mcp_client, _resolve_port


def test_singleton() -> None:
    """get_mcp_client returns the same instance on repeated calls."""
    client_a = get_mcp_client()
    client_b = get_mcp_client()
    assert client_a is client_b, "Singleton should return the same instance"


def test_singleton_direct() -> None:
    """MCPClient() constructor returns the same instance."""
    a = MCPClient()
    b = MCPClient()
    assert a is b


def test_resolve_port_intel() -> None:
    """Known intel tools resolve to port 9001."""
    assert _resolve_port("trading_sessions") == 9001
    assert _resolve_port("fetch_market_health") == 9001
    assert _resolve_port("fetch_kline") == 9001


def test_resolve_port_risk() -> None:
    """Known risk tools resolve to port 9002."""
    assert _resolve_port("check_intent") == 9002
    assert _resolve_port("batch_check") == 9002
    assert _resolve_port("get_blacklist") == 9002


def test_resolve_port_exec() -> None:
    """Known exec tools resolve to port 9003."""
    assert _resolve_port("place_order") == 9003
    assert _resolve_port("get_balance") == 9003
    assert _resolve_port("get_positions") == 9003


def test_resolve_port_unknown() -> None:
    """Unknown tool name raises ValueError."""
    import pytest
    with pytest.raises(ValueError, match="Unknown MCP tool"):
        _resolve_port("nonexistent_tool")


def test_client_has_convenience_methods() -> None:
    """MCPClient instance has expected convenience method names."""
    client = MCPClient()
    assert hasattr(client, "get_market_health")
    assert hasattr(client, "get_trading_sessions")
    assert hasattr(client, "is_trading_day")
    assert hasattr(client, "fetch_klines")
    assert hasattr(client, "query_quotes")
    assert hasattr(client, "wencai_search")
    assert hasattr(client, "get_limitup_ladder")
    assert hasattr(client, "get_mainline_lanes")
    assert hasattr(client, "get_rebound_candidates")
    assert hasattr(client, "news_search")
    assert hasattr(client, "screen_stocks")
    assert hasattr(client, "get_watchlist")
    assert hasattr(client, "get_fund_flow")
    assert hasattr(client, "get_chip_distribution")
    assert hasattr(client, "get_technical_indicators")
    assert hasattr(client, "get_financial_report")
    assert hasattr(client, "tdx_kline")
    assert hasattr(client, "tdx_quotes")
    assert hasattr(client, "tdx_screener")
    assert hasattr(client, "tdx_f10")
    assert hasattr(client, "check_intent")
    assert hasattr(client, "batch_check")
    assert hasattr(client, "get_blacklist")
    assert hasattr(client, "daily_pnl")
    assert hasattr(client, "get_balance")
    assert hasattr(client, "get_positions")
    assert hasattr(client, "get_today_trades")
    assert hasattr(client, "get_orders")
    assert hasattr(client, "place_order")
    assert hasattr(client, "register_approved_intent")
