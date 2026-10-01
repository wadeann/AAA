#!/usr/bin/env python3
"""高层分析编排器 — 综合缠论、情绪、体制输出信号。"""

from __future__ import annotations

from typing import Any

from core.chanlun_engine import analyze_from_mcp, leader_score
from core.sentiment_engine import compute_sentiment
from core.market_regime import MarketRegime
from mcp_client import get_mcp_client


class MarketAnalyzer:
    """市场分析编排器，组合多维度分析。"""

    def __init__(self) -> None:
        self.client = get_mcp_client()
        self.regime = MarketRegime()

    def get_market_context(self) -> dict[str, Any]:
        """获取完整的市场环境上下文。"""
        try:
            health = self.client.get_market_health()
        except Exception:
            health = {"score": 50, "summary": "数据不可用"}
        sentiment = compute_sentiment()
        regime = self.regime.detect()
        try:
            sessions = self.client.get_trading_sessions()
        except Exception:
            sessions = {"is_trading_day": False, "is_open": False}

        return {
            "health_score": health.get("score", 50),
            "health_summary": health.get("summary", ""),
            "sentiment_phase": sentiment.get("phase", "warmup"),
            "sentiment_multiplier": sentiment.get("multiplier", 0.45),
            "market_regime": regime.get("regime", "震荡"),
            "regime_multiplier": regime.get("regime_multiplier", 0.45),
            "is_trading_day": sessions.get("is_trading_day", False),
            "is_open": sessions.get("is_open", False),
            "server_time": sessions.get("server_time", ""),
        }

    def analyze_symbols(self, symbols: list[str]) -> list[dict[str, Any]]:
        """对多个标的批量缠论分析。"""
        results = []
        for symbol in symbols:
            try:
                chan = analyze_from_mcp(symbol)
                results.append({
                    "symbol": symbol,
                    "trend_type": chan.get("trend_type"),
                    "buy_point": chan.get("buy_point"),
                    "sell_point": chan.get("sell_point"),
                    "divergence": chan.get("divergence", {}).get("type"),
                    "confirmed": chan.get("confirmed", False),
                    "bar_count": chan.get("bar_count", 0),
                })
            except Exception as e:
                results.append({"symbol": symbol, "error": str(e)})
        return results

    def get_daily_overview(self) -> dict[str, Any]:
        """生成每日市场概览。"""
        ctx = self.get_market_context()
        try:
            ladder = self.client.get_limitup_ladder()
        except Exception:
            ladder = {}
        try:
            mainline = self.client.get_mainline_lanes(top_n=3)
        except Exception:
            mainline = {}
        try:
            watchlist = self.client.get_watchlist()
        except Exception:
            watchlist = []

        return {
            "market_context": ctx,
            "limitup_ladder": ladder,
            "mainline_lanes": mainline,
            "watchlist_count": len(watchlist),
        }


if __name__ == "__main__":
    import json
    analyzer = MarketAnalyzer()
    overview = analyzer.get_daily_overview()
    print(json.dumps(overview, ensure_ascii=False, indent=2, default=str)[:500])
