#!/usr/bin/env python3
"""市场体制检测 — 根据指数表现判断市场状态。"""

from __future__ import annotations

import datetime as dt
from typing import Any


_REGRIME_MAP = {
    "euphoria": "高潮",
    "hot": "走强",
    "warmup": "震荡",
    "cooldown": "退潮",
    "ice": "极寒",
}


class MarketRegime:
    """市场体制状态机。"""

    def __init__(self) -> None:
        from data import get_data_manager
        self.dm = get_data_manager()
        self.data: dict[str, Any] = self.dm.load_state("market_regime.json") or {
            "regime": "震荡",
            "standard_regime": "warmup",
            "regime_multiplier": 0.45,
            "sell_only_mode": False,
            "fail_closed": False,
            "updated_at": "",
        }

    def detect(self, indices: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
        """从指数数据检测市场体制。"""
        from mcp_client import get_mcp_client

        if indices is None:
            client = get_mcp_client()
            try:
                quotes = client.query_quotes(["000001.SH", "399001.SZ", "399006.SZ", "000688.SH"])
                indices = {}
                for s in ["000001.SH", "399001.SZ", "399006.SZ", "000688.SH"]:
                    if s in quotes:
                        indices[s] = quotes[s]
            except Exception:
                return self.data

        chgs = []
        for s, q in indices.items():
            if isinstance(q, dict) and q.get("change_pct") is not None:
                chgs.append(float(q["change_pct"]))

        if not chgs:
            return self.data

        avg_chg = sum(chgs) / len(chgs)
        max_chg = max(chgs)
        min_chg = min(chgs)

        # 检测市场体制
        if avg_chg > 1.2 and max_chg > 1.5:
            regime = "高潮"
            standard = "euphoria"
            multiplier = 0.85
        elif avg_chg >= 0.4:
            regime = "走强"
            standard = "hot"
            multiplier = 0.75
        elif avg_chg >= -0.3:
            regime = "震荡"
            standard = "warmup"
            multiplier = 0.45
        elif avg_chg >= -1.2:
            regime = "退潮"
            standard = "cooldown"
            multiplier = 0.25
        else:
            regime = "极寒"
            standard = "ice"
            multiplier = 0.15

        self.data.update({
            "regime": regime,
            "standard_regime": standard,
            "regime_multiplier": multiplier,
            "avg_change_pct": round(avg_chg, 2),
            "max_change_pct": round(max_chg, 2),
            "min_change_pct": round(min_chg, 2),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        })
        return self.data

    def save(self) -> None:
        self.dm.save_state("market_regime.json", self.data)

    def load(self) -> dict[str, Any]:
        self.data = self.dm.load_state("market_regime.json")
        return self.data

    def get_multiplier(self) -> float:
        return float(self.data.get("regime_multiplier", 0.45))

    def is_defensive(self) -> bool:
        return (
            self.data.get("sell_only_mode") is True
            or self.data.get("fail_closed") is True
            or self.data.get("standard_regime") in {"freezing", "panic_ebb"}
        )


if __name__ == "__main__":
    mr = MarketRegime()
    state = mr.detect()
    print(f"体制: {state['regime']}, 乘数: {state['regime_multiplier']}")
