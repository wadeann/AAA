#!/usr/bin/env python3
"""Astock 本地风控管理器 — 13 层风险检查 + 批量注册。

check_intent:   单笔意图逐层核验
batch_check:   批量检查 + 自动将通过意图注册到 exec server

13 层风控 (按检查顺序):
  1. symbol        标的合法性
  2. weekend       周末非交易日前置拦截
  3. position_cap  单标的仓位 <= 30%
  4. market_crash  大盘健康度 < 30 触发熔断
  5. outflow       主力净流出 < -800 亿拦截买入
  6. sentiment     情绪周期系数过低时拒买
  7. sector_conc   板块集中度 <= 40%
  8. total_exp     总敞口 <= 80%
  9. t1_rule       T+1 方向冲突
  10. st_blacklist  ST / *ST / 退市黑名单
  11. avg_down     禁止摊平 (已有持仓时同方向买入)
  12. tail_chase   14:35 后禁止追高买入
  13. freeze       冻结期/冷静期检查
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from config import DATA_DIR, STATE_DIR
from data import get_data_manager
from mcp_client import get_mcp_client


CST = dt.timezone(dt.timedelta(hours=8))

# 板块涨跌幅限制
LIMIT_RATIO_MAP: dict[str, float] = {
    "主板": 0.10,
    "创业板": 0.20,
    "科创板": 0.20,
    "北交所": 0.30,
    "ST": 0.05,
}

ST_KEYWORDS = ("ST", "*ST", "退市", "S*ST", "SST")


def _get_limit_ratio(symbol: str, name: str = "") -> float:
    sym_up = symbol.upper()
    if any(st in name for st in ST_KEYWORDS):
        return 0.05
    if sym_up.startswith(("300", "301")):
        return 0.20  # 创业板
    if sym_up.startswith("688"):
        return 0.20  # 科创板
    if sym_up.startswith(("920", "8", "4")):
        return 0.30  # 北交所
    return 0.10  # 主板


def _is_st(name: str, symbol: str) -> bool:
    if any(st in name for st in ST_KEYWORDS):
        return True
    sym_up = symbol.upper()
    if sym_up.startswith(("300", "301", "688")):
        return False
    return False


class RiskManager:
    """本地风控管理器 — 13 层逐级检查 + 批量注册。"""

    def __init__(self) -> None:
        self._client = get_mcp_client()
        self._dm = get_data_manager()

    # ──────────────────────────────────────────────
    # 工具方法
    # ──────────────────────────────────────────────

    def _now_cst(self) -> dt.datetime:
        return dt.datetime.now(CST)

    def _now_time_cst(self) -> dt.time:
        return self._now_cst().time()

    def _is_trading_day(self) -> bool:
        try:
            session = self._client.get_trading_sessions()
            return bool(session.get("is_trading_day", False))
        except Exception:
            wd = self._now_cst().weekday()
            return wd < 5  # 周一到周五

    def _get_positions(self) -> list[dict[str, Any]]:
        try:
            return self._client.get_positions()
        except Exception:
            return []

    def _get_balance(self) -> dict[str, Any]:
        try:
            return self._client.get_balance()
        except Exception:
            return {}

    def _load_blacklist(self) -> list[str]:
        try:
            bl = self._client.get_blacklist()
            return bl if isinstance(bl, list) else []
        except Exception:
            return []

    # ──────────────────────────────────────────────
    # 单层检查 (每层返回 (pass: bool, reason: str))
    # ──────────────────────────────────────────────

    def _check_symbol(self, symbol: str) -> tuple[bool, str]:
        """Layer 1: 标的合法性."""
        if not symbol or not isinstance(symbol, str):
            return False, "symbol为空或非法"
        sym_up = symbol.upper()
        # 必须包含 .SH .SZ .BJ
        if not any(sym_up.endswith(suf) for suf in (".SH", ".SZ", ".BJ", "SH", "SZ")):
            return False, f"标的代码格式异常: {symbol}"
        # 简单代码长度校验 (6位数字 + 后缀)
        code = sym_up.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        if not code.isdigit() or len(code) != 6:
            return False, f"标的代码数字部分异常: {symbol}"
        return True, ""

    def _check_weekend(self) -> tuple[bool, str]:
        """Layer 2: 周末拦截."""
        now = self._now_cst()
        if now.weekday() >= 5:
            return False, f"周末非交易日 ({now.strftime('%A')})"
        if not self._is_trading_day():
            return False, "非交易日 (节假日)"
        return True, ""

    def _check_position_cap(
        self, symbol: str, direction: str, quantity: int, price: float,
    ) -> tuple[bool, str]:
        """Layer 3: 单标的仓位 <= 30%."""
        if direction != "buy":
            return True, ""
        try:
            balance = self._client.get_balance()
            total_assets = float(balance.get("total_assets", balance.get("total_asset", 0)) or 0)
            if total_assets <= 0:
                return True, ""  # 无法校验时放行
            positions = self._client.get_positions()
            current_position_value = 0.0
            for p in positions:
                if isinstance(p, dict) and str(p.get("symbol", "")) == symbol:
                    mv = float(p.get("market_value", 0) or 0)
                    if mv <= 0:
                        mv = float(p.get("current_price", p.get("cost_price", 0)) or 0) * float(p.get("quantity", 0) or 0)
                    current_position_value = mv
                    break
            new_value = quantity * price
            total_value = current_position_value + new_value
            ratio = total_value / total_assets
            if ratio > 0.30:
                return False, f"单标仓位 {ratio:.1%} > 30% 上限"
        except Exception as e:
            return False, f"仓位检查异常: {e}"
        return True, ""

    def _check_market_crash(self) -> tuple[bool, str]:
        """Layer 4: 大盘健康度 < 30 熔断."""
        try:
            health = self._client.get_market_health()
            score = float(health.get("health_score", health.get("score", 100)) or 100)
            if score < 30:
                return False, f"市场健康度 {score} < 30，触发大盘熔断"
        except Exception:
            pass  # 无法获取时放行
        return True, ""

    def _check_outflow(self) -> tuple[bool, str]:
        """Layer 5: 主力净流出 < -800亿 拦截买入."""
        try:
            sh = self._client.call("get_fund_flow", {"symbol": "000001.SH"})
            net_out = float(sh.get("net_outflow", sh.get("net_flow", 0)) or 0)
            if net_out < -80_000_000_000:  # < -800亿
                return False, f"主力净流出 {net_out / 1e8:.0f}亿 < -800亿，拦截买入"
        except Exception:
            pass
        return True, ""

    def _check_sentiment(self) -> tuple[bool, str]:
        """Layer 6: 情绪周期系数过低时拒买."""
        try:
            sp = self._dm.load_state("strategy_params.json")
            sent = sp.get("sentiment", {})
            phase = sent.get("phase", "")
            multiplier = float(sent.get("multiplier", 1.0))
            if phase in ("ice", "cooldown") and multiplier <= 0.3:
                return False, f"情绪周期 {phase} 系数 {multiplier}，禁止新开买入"
        except Exception:
            pass
        return True, ""

    def _check_sector_concentration(
        self, symbol: str, quantity: int, price: float,
    ) -> tuple[bool, str]:
        """Layer 7: 板块集中度 <= 40%."""
        try:
            positions = self._client.get_positions()
            # 尝试获取标的板块信息
            try:
                quote = self._client.call("query_data", {"symbol": symbol}, port=9001)
                sector = str(quote.get("sector", quote.get("industry", "")))
            except Exception:
                sector = ""
            if not sector:
                return True, ""  # 无板块信息时放行

            total_assets = 0.0
            sector_value = 0.0
            try:
                balance = self._client.get_balance()
                total_assets = float(balance.get("total_assets", balance.get("total_asset", 0)) or 0)
            except Exception:
                total_assets = 0.0
            if total_assets <= 0:
                return True, ""

            new_value = quantity * price
            for p in positions:
                if isinstance(p, dict):
                    mv = float(p.get("market_value", 0) or 0)
                    if mv <= 0:
                        mv = float(p.get("current_price", p.get("cost_price", 0)) or 0) * float(p.get("quantity", 0) or 0)
                    try:
                        p_quote = self._client.call("query_data", {"symbol": p.get("symbol", "")}, port=9001)
                        p_sector = str(p_quote.get("sector", p_quote.get("industry", "")))
                        if p_sector == sector:
                            sector_value += mv
                    except Exception:
                        pass

            sector_ratio = (sector_value + new_value) / total_assets
            if sector_ratio > 0.40:
                return False, f"板块 {sector} 集中度 {sector_ratio:.1%} > 40% 上限"
        except Exception:
            pass
        return True, ""

    def _check_total_exposure(
        self, direction: str, quantity: int, price: float,
    ) -> tuple[bool, str]:
        """Layer 8: 总敞口 <= 80%."""
        if direction != "buy":
            return True, ""
        try:
            balance = self._client.get_balance()
            total_assets = float(balance.get("total_assets", balance.get("total_asset", 0)) or 0)
            if total_assets <= 0:
                return True, ""
            positions = self._client.get_positions()
            current_exposure = 0.0
            for p in positions:
                if isinstance(p, dict):
                    mv = float(p.get("market_value", 0) or 0)
                    if mv <= 0:
                        mv = float(p.get("current_price", p.get("cost_price", 0)) or 0) * float(p.get("quantity", 0) or 0)
                    current_exposure += mv
            new_exposure = current_exposure + quantity * price
            ratio = new_exposure / total_assets
            if ratio > 0.80:
                return False, f"总敞口 {ratio:.1%} > 80% 上限"
        except Exception:
            pass
        return True, ""

    def _check_t1_rule(self, symbol: str, direction: str) -> tuple[bool, str]:
        """Layer 9: T+1 方向冲突."""
        if not symbol or not direction:
            return False, "symbol/direction缺失"
        direction = direction.lower().strip()
        today = dt.date.today().isoformat()
        records = self._dm.read_jsonl(date=today)

        events: dict[str, str] = {}
        for r in records:
            if r.get("record_type") != "candidate_event":
                continue
            ev = r.get("event", "")
            sym = r.get("symbol", "")
            dr = str(r.get("direction", "")).lower().strip()
            if not sym:
                continue
            if ev in ("executed", "submitted", "submitted_unverified"):
                events[sym] = dr

        last_dir = events.get(symbol)
        if not last_dir:
            return True, ""
        if last_dir == direction:
            return False, f"T+1冲突: 今日已有{direction}方向执行记录"

        # 反方向: 查持仓
        if direction == "sell":
            try:
                positions = self._client.get_positions()
                for p in positions:
                    if p.get("symbol", "") == symbol:
                        av_raw = p.get("available_quantity")
                        if av_raw is None:
                            av_raw = p.get("available_shares")
                        av = int(float(av_raw if av_raw is not None else 0))
                        if av > 0:
                            return True, ""  # 有可用持仓允许卖出
                        break
            except Exception:
                pass
            return False, "T+1冲突: 无可用持仓卖出"

        # direction == "buy" 且 last_dir == "sell"
        try:
            positions = self._client.get_positions()
            has_pos = any(
                p.get("symbol", "") == symbol
                and (int(float(p.get("quantity", p.get("available_quantity", p.get("available_shares", 0))) or 0)) > 0)
                for p in positions
            )
        except Exception:
            has_pos = True
        if not has_pos:
            return True, ""  # 已卖完允许反手
        return False, "T+1冲突: 已有持仓禁止当日买入"

    def _check_st_blacklist(self, symbol: str, name: str) -> tuple[bool, str]:
        """Layer 10: ST / *ST / 退市黑名单."""
        if _is_st(name, symbol):
            return False, f"ST标的禁止交易: {name}({symbol})"
        bl = self._load_blacklist()
        if symbol in bl:
            return False, f"标的在黑名单中: {symbol}"
        return True, ""

    def _check_avg_down(self, symbol: str, direction: str) -> tuple[bool, str]:
        """Layer 11: 禁止摊平 (已有持仓时同方向买入)."""
        if direction != "buy":
            return True, ""
        try:
            positions = self._client.get_positions()
            for p in positions:
                if p.get("symbol", "") == symbol:
                    qty = int(float(p.get("quantity", 0) or 0))
                    if qty > 0:
                        return False, f"禁止摊平: {symbol} 已有持仓 {qty} 股"
        except Exception:
            pass
        return True, ""

    def _check_tail_chase(self) -> tuple[bool, str]:
        """Layer 12: 14:35 后禁止追高买入."""
        now_time = self._now_time_cst()
        if now_time >= dt.time(14, 35):
            return False, f"尾盘追高拦截: {now_time.strftime('%H:%M')} >= 14:35"
        return True, ""

    def _check_freeze(self, symbol: str) -> tuple[bool, str]:
        """Layer 13: 冻结期/冷静期检查."""
        try:
            state = self._dm.load_state("freeze_state.json")
            freeze_list = state.get("freeze", {})
            if symbol in freeze_list:
                frozen_until = freeze_list[symbol]
                today_str = dt.date.today().isoformat()
                if today_str < frozen_until:
                    return False, f"{symbol} 冻结至 {frozen_until}"
        except Exception:
            pass
        return True, ""

    # ──────────────────────────────────────────────
    # 公开接口
    # ──────────────────────────────────────────────

    def check_intent(self, intent: dict[str, Any]) -> dict[str, Any]:
        """13 层逐级风控检查。

        Args:
            intent: {
                "symbol": str,
                "direction": "buy" | "sell",
                "quantity": int,
                "price": float,
                "name": str (optional),
                ...
            }

        Returns:
            {"approved": bool, "reason": str, "layer": str|None}
        """
        symbol = str(intent.get("symbol", ""))
        direction = str(intent.get("direction", "")).lower().strip()
        quantity = int(intent.get("quantity", 0) or 0)
        price = float(intent.get("price", 0) or 0)
        name = str(intent.get("name", intent.get("symbol", "")))

        checks: list[tuple[str, Any]] = [
            ("symbol", self._check_symbol(symbol)),
            ("weekend", self._check_weekend()),
            ("st_blacklist", self._check_st_blacklist(symbol, name)),
        ]

        if direction == "buy":
            checks.extend([
                ("position_cap", self._check_position_cap(symbol, direction, quantity, price)),
                ("market_crash", self._check_market_crash()),
                ("outflow", self._check_outflow()),
                ("sentiment", self._check_sentiment()),
                ("sector_conc", self._check_sector_concentration(symbol, quantity, price)),
                ("total_exp", self._check_total_exposure(direction, quantity, price)),
                ("avg_down", self._check_avg_down(symbol, direction)),
                ("tail_chase", self._check_tail_chase()),
            ])

        checks.extend([
            ("t1_rule", self._check_t1_rule(symbol, direction)),
            ("freeze", self._check_freeze(symbol)),
        ])

        for layer_name, (passed, reason) in checks:
            if not passed:
                return {
                    "approved": False,
                    "reason": reason,
                    "layer": layer_name,
                }

        return {
            "approved": True,
            "reason": "全部风控通过",
            "layer": None,
        }

    def batch_check(self, intents: list[dict[str, Any]]) -> dict[str, Any]:
        """批量风控检查 + 自动注册通过意图到 exec server。

        Args:
            intents: 意图列表

        Returns:
            {"results": [{"approved": bool, "reason": str, "layer": str|None, ...}], "registered": int}
        """
        results: list[dict[str, Any]] = []
        registered_count = 0

        for intent in intents:
            check_result = self.check_intent(intent)
            result_entry = {
                "symbol": intent.get("symbol", ""),
                "direction": intent.get("direction", ""),
                "candidate_id": intent.get("candidate_id", ""),
                "intent_id": intent.get("intent_id", ""),
                "approved": check_result["approved"],
                "approval_status": "approved" if check_result["approved"] else "rejected",
                "rejection_reason": check_result["reason"] if not check_result["approved"] else "",
                "layer": check_result["layer"],
            }

            if check_result["approved"]:
                # 注册到 exec server
                intent_id = intent.get("intent_id", "")
                if intent_id:
                    try:
                        reg = self._client.register_approved_intent(
                            intent_id=intent_id,
                            symbol=intent["symbol"],
                            direction=intent["direction"],
                            max_quantity=int(intent.get("quantity", 0) or 0),
                        )
                        if isinstance(reg, dict) and not reg.get("error"):
                            result_entry["exec_registered"] = True
                            registered_count += 1
                        else:
                            result_entry["exec_registered"] = False
                    except Exception as e:
                        result_entry["exec_registered"] = False
                        result_entry["registration_error"] = str(e)

            results.append(result_entry)

        return {
            "results": results,
            "registered": registered_count,
        }
