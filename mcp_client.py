"""MCP 客户端单例 — 通过 httpx JSON-RPC 调用 pup-mcp 服务."""

from __future__ import annotations

import json
from typing import Any

import httpx


_MCP_PORTS = {
    "intel": 9001,
    "risk": 9002,
    "exec": 9003,
}

_INTEL_TOOLS = {
    "trading_sessions", "is_trading_day", "fetch_market_health",
    "fetch_kline", "query_batch_data", "query_multi_source_quote",
    "get_watchlist", "screen_stocks", "wencai_search",
    "search_news", "fetch_hot_signals",
    "get_limitup_ladder", "get_mainline_lanes", "get_rebound_candidates",
    "get_fund_flow", "get_chip_distribution", "get_technical_indicators",
    "get_financial_report",
    "tdx_kline", "tdx_quotes", "tdx_screener", "tdx_f10", "tdx_news", "tdx_health",
    "analyze_stock_with_antigravity",
}

_RISK_TOOLS = {"check_intent", "batch_check", "get_blacklist", "daily_pnl"}

_EXEC_TOOLS = {
    "get_balance", "get_positions", "get_today_trades", "get_orders",
    "get_pnl", "cancel_order", "register_approved_intent", "place_order",
}


def _resolve_port(tool: str) -> int:
    if tool in _INTEL_TOOLS:
        return 9001
    if tool in _RISK_TOOLS:
        return 9002
    if tool in _EXEC_TOOLS:
        return 9003
    raise ValueError(f"Unknown MCP tool: {tool}")


class MCPClient:
    """单例 MCP JSON-RPC 客户端，封装对 pup-mcp 三服务器的调用。"""

    _instance: MCPClient | None = None

    def __new__(cls) -> MCPClient:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._http = httpx.Client(timeout=30.0, base_url="http://127.0.0.1")
        return cls._instance

    def call(
        self, tool: str, arguments: dict[str, Any] | None = None, port: int | None = None
    ) -> Any:
        """通用 MCP 工具调用。自动检测端口。"""
        if port is None:
            port = _resolve_port(tool)
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments or {}},
        }
        resp = self._http.post(f"http://127.0.0.1:{port}/mcp", json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"MCP error [{tool}]: {data['error']}")
        content = data.get("result", {}).get("content", [])
        if not content:
            return {}
        text = content[0].get("text", "{}")
        return json.loads(text)

    # ── 便捷方法 ──

    def get_market_health(self) -> dict[str, Any]:
        return self.call("fetch_market_health")

    def get_trading_sessions(self) -> dict[str, Any]:
        return self.call("trading_sessions")

    def is_trading_day(self) -> bool:
        r = self.call("is_trading_day")
        return bool(r.get("is_trading_day", False))

    def fetch_klines(
        self, symbol: str, period: str = "D", count: int = 100
    ) -> list[dict[str, Any]]:
        r = self.call("fetch_kline", {"symbol": symbol, "period": period, "count": count})
        return r.get("klines", [])

    def query_quotes(self, symbols: list[str]) -> dict[str, Any]:
        return self.call("query_batch_data", {"symbols": symbols})

    def wencai_search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        r = self.call("wencai_search", {"query": query, "limit": limit})
        return r.get("datas", [])

    def get_limitup_ladder(self, date: str | None = None, min_streak: int = 1) -> Any:
        args: dict[str, Any] = {"min_streak": min_streak}
        if date:
            args["date"] = date
        return self.call("get_limitup_ladder", args)

    def get_mainline_lanes(self, top_n: int = 3) -> Any:
        return self.call("get_mainline_lanes", {"top_n": top_n})

    def get_rebound_candidates(
        self, min_h: int = 2, max_h: int = 5, limit: int = 10
    ) -> Any:
        return self.call("get_rebound_candidates", {
            "min_prev_height": min_h, "max_prev_height": max_h, "limit": limit,
        })

    def news_search(self, symbol: str) -> list[dict[str, Any]]:
        r = self.call("search_news", {"symbol": symbol})
        return r.get("items", [])

    def screen_stocks(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        r = self.call("screen_stocks", {"query": query, "limit": limit})
        return r.get("stocks", [])

    def get_watchlist(self) -> list[dict[str, Any]]:
        r = self.call("get_watchlist")
        return r.get("stocks", [])

    def get_fund_flow(self, symbol: str) -> dict[str, Any]:
        return self.call("get_fund_flow", {"symbol": symbol})

    def get_chip_distribution(self, symbol: str) -> dict[str, Any]:
        return self.call("get_chip_distribution", {"symbol": symbol})

    def get_technical_indicators(self, symbol: str) -> dict[str, Any]:
        return self.call("get_technical_indicators", {"symbol": symbol})

    def get_financial_report(self, symbol: str, num: int = 2) -> dict[str, Any]:
        return self.call("get_financial_report", {"symbol": symbol, "num": num})

    # ── TDX 适配器 ──

    def tdx_kline(self, symbol: str, period: str = "D", count: int = 100) -> Any:
        return self.call("tdx_kline", {"symbol": symbol, "period": period, "count": count})

    def tdx_quotes(self, symbol: str) -> Any:
        return self.call("tdx_quotes", {"symbol": symbol})

    def tdx_screener(self, query: str, limit: int = 10) -> Any:
        return self.call("tdx_screener", {"query": query, "limit": limit})

    def tdx_f10(self, symbol: str, module: str = "basic") -> Any:
        return self.call("tdx_f10", {"symbol": symbol, "module": module})

    # ── 风控 ──

    def check_intent(self, intent: dict[str, Any]) -> dict[str, Any]:
        return self.call("check_intent", intent, port=9002)

    def batch_check(self, intents: list[dict[str, Any]]) -> dict[str, Any]:
        return self.call("batch_check", {"intents": intents}, port=9002)

    def get_blacklist(self) -> list[str]:
        r = self.call("get_blacklist", port=9002)
        return r.get("blacklist", [])

    def daily_pnl(self) -> dict[str, Any]:
        return self.call("daily_pnl", port=9002)

    # ── 交易执行 ──

    def get_balance(self) -> dict[str, Any]:
        return self.call("get_balance", port=9003)

    def get_positions(self) -> list[dict[str, Any]]:
        r = self.call("get_positions", port=9003)
        if isinstance(r, list):
            return r
        return r.get("positions", r.get("value", []))

    def get_today_trades(self) -> list[dict[str, Any]]:
        r = self.call("get_today_trades", port=9003)
        if isinstance(r, list):
            return r
        return r.get("trades", r.get("data", []))

    def get_orders(self, status: str | None = None) -> list[dict[str, Any]]:
        args = {}
        if status:
            args["status"] = status
        r = self.call("get_orders", args, port=9003)
        return r.get("orders", [])

    def place_order(
        self, symbol: str, direction: str, quantity: int,
        price: float, intent_id: str, reason: str = "",
    ) -> dict[str, Any]:
        return self.call("place_order", {
            "symbol": symbol, "direction": direction,
            "quantity": quantity, "price": price,
            "intent_id": intent_id, "reason": reason,
        }, port=9003)

    def register_approved_intent(
        self, intent_id: str, symbol: str, direction: str,
        max_quantity: int, expires_at: str | None = None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {
            "intent_id": intent_id, "symbol": symbol,
            "direction": direction, "max_quantity": max_quantity,
        }
        if expires_at:
            args["expires_at"] = expires_at
        return self.call("register_approved_intent", args, port=9003)


def get_mcp_client() -> MCPClient:
    return MCPClient()
