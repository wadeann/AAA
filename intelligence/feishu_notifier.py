#!/usr/bin/env python3
"""Feishu message push module.

Sends text messages to Feishu groups via Feishu OpenAPI.
Uses httpx for HTTP calls and config for credential loading — no hardcoded credentials.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
from typing import Any, Optional

import httpx

from config import load_yaml

# ── 7-Layer Audit Gate ──


def audit_message_before_send(content: str) -> tuple[bool, str]:
    """Risk control gate: hardcore authenticity and compliance review before sending.

    Returns (passed: bool, reason: str).
    """
    # 1. ST risk stocks — absolute veto
    if re.search(r"【\*?ST[一-龥A-Za-z0-9]+】", content):
        if any(w in content for w in ["出击", "买入", "先锋", "补涨", "重点伏击", "推荐"]):
            return False, "拦截原因: 消息包含 ST/*ST 风险股票推荐，严重触犯风控红线！"

    # 2. Absurd concept mismatch interception
    if ("医药" in content or "创新药" in content) and ("原糖" in content or "月饼" in content):
        return False, "拦截原因: 消息存在荒谬概念错位（医药与原糖月饼错乱拼接）！"

    # 3. Low-score junk theme buy interception (<60 points, absolutely forbid stock recommendations)
    score_match = re.search(r"多维评分[:：]\s*([0-9.]+)\s*分", content)
    if score_match:
        try:
            val = float(score_match.group(1))
            if val < 60.0 and any(w in content for w in ["锁定第一套利靶向", "推荐套利出击", "黄金起爆点"]):
                return False, f"拦截原因: 题材评分仅 {val:.1f}分 (<60分及格线)，禁止推发买入指令！"
        except Exception:
            pass

    # 4. Underwater green-plate disguised breakout interception
    if any(w in content for w in ["黄金起爆点", "当下可立即买入", "出击逻辑"]):
        if re.search(r"\((?:涨幅\s*)?-[0-9.]+%\)", content):
            return False, "拦截原因: 标的处于绿盘水下负涨幅，严禁判定为起爆买入！"

    # 5. Empty stock code interception
    if re.search(r"【[^\n】]+】\(\s*\)", content):
        return False, "拦截原因: 消息包含空股票代码 '【名称】()'，存在关键数据字段缺失！"

    # 6. Stale/expired date interception
    try:
        today_cst = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d")
        date_matches = re.findall(r"(202\d-[01]\d-[0-3]\d)", content)
        for msg_date in date_matches:
            if msg_date < today_cst:
                return False, f"拦截原因: 消息包含过期历史日期 {msg_date} (今日为 {today_cst})，疑似缓存未刷新！"
    except Exception:
        pass

    # 7. High-risk broken board interception (>=10 break counts + buy recommendation)
    if any(w in content for w in ["买入", "起爆", "优质真龙", "立即出击"]):
        break_match = re.search(r"(?:炸板|开板)(?:次数)?\s*[:：]?\s*([0-9]+)\s*次", content)
        if break_match:
            try:
                b_cnt = int(break_match.group(1))
                if b_cnt >= 10:
                    return False, f"拦截原因: 标的炸板高达 {b_cnt} 次，筹码极度松动，严禁推选为买入标的！"
            except Exception:
                pass

    return True, "PASS"


# ── Credential Loading ──


def _load_feishu_credentials() -> tuple[str, str, str]:
    """Load Feishu app credentials from config YAML and env fallbacks."""
    cfg = load_yaml("config.yaml") or {}
    feishu_cfg = cfg.get("feishu", {})
    extra_cfg = feishu_cfg.get("extra", {})

    app_id = (
        os.environ.get("FEISHU_APP_ID")
        or extra_cfg.get("app_id")
        or ""
    )
    app_secret = (
        os.environ.get("FEISHU_APP_SECRET")
        or extra_cfg.get("app_secret")
        or ""
    )
    chat_id = (
        os.environ.get("FEISHU_CHAT_ID")
        or extra_cfg.get("chat_id")
        or feishu_cfg.get("chat_id")
        or ""
    )
    return app_id, app_secret, chat_id


# ── API Calls ──


def _send_via_feishu_api(content: str, app_id: str, app_secret: str, chat_id: str) -> bool:
    """Send group message via Feishu OpenAPI directly (no webhook)."""
    try:
        with httpx.Client(timeout=10.0) as client:
            # Get tenant access token
            token_resp = client.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
            )
            token_data = token_resp.json()
            token = token_data.get("tenant_access_token")
            if not token:
                return False

            # Send message
            msg_resp = client.post(
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                json={
                    "receive_id": chat_id,
                    "msg_type": "text",
                    "content": json.dumps({"text": content}),
                },
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                },
            )
            msg_data = msg_resp.json()
            return msg_data.get("code") == 0
    except Exception:
        return False


# ── Public API ──


def send_feishu_message(
    content: str,
    webhook_url: str | None = None,
) -> bool:
    """Send message to Feishu via webhook or OpenAPI.

    Applies the 7-layer audit gate before sending. Falls back to OpenAPI
    if webhook is not configured or fails. Prints to stdout as last resort.
    """
    if os.environ.get("TESTING") == "1" or os.environ.get("TEST_MODE") == "1":
        return True

    # 严格执行风控审查总闸门
    passed, reason = audit_message_before_send(content)
    if not passed:
        print(
            f"\n[飞书发送总闸门拦截] {reason}\n[拦截内容摘要]: {content[:200]}...\n",
            file=sys.stderr,
            flush=True,
        )
        return False

    url = (webhook_url or os.environ.get("FEISHU_WEBHOOK_URL", "")).strip()

    if url:
        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.post(
                    url,
                    json={
                        "msg_type": "text",
                        "content": {"text": content},
                    },
                )
                result = resp.json()
                if result.get("code") == 0:
                    return True
        except Exception:
            pass

    # Fallback: direct Feishu OpenAPI
    app_id, app_secret, chat_id = _load_feishu_credentials()
    if app_id and app_secret and chat_id:
        ok = _send_via_feishu_api(content, app_id, app_secret, chat_id)
        if ok:
            return True

    # Ultimate fallback: stdout
    print(content, flush=True)
    return False


def notify_trade_executed(
    direction: str,
    symbol: str,
    name: str,
    quantity: int,
    price: float,
    order_id: str,
    reason: str = "",
    cash_remaining: float = 0.0,
    webhook_url: str | None = None,
) -> bool:
    """Real-time trade execution notification to Feishu."""
    clean_name = (name or "").strip()
    clean_symbol = (symbol or "").strip()

    # Auto-resolve stock name if missing or identical to code
    if not clean_name or clean_name == clean_symbol or clean_name.endswith((".SZ", ".SH", ".BJ")):
        try:
            raw_code = clean_symbol.split(".")[0]
            prefix = (
                "sh" if raw_code.startswith(("60", "68"))
                else "sz" if raw_code.startswith(("00", "30"))
                else "bj"
            )
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(
                    f"http://qt.gtimg.cn/q={prefix}{raw_code}",
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                resp.encoding = "gbk"
                parts = resp.text.split("~")
                if len(parts) > 2 and parts[1] and parts[1] != raw_code:
                    clean_name = parts[1]
        except Exception:
            pass

    display_target = (
        f"{clean_name} ({clean_symbol})"
        if clean_name and clean_name != clean_symbol
        else clean_symbol
    )
    dir_label = "买入 (BUY)" if direction.upper() == "BUY" else "卖出 (SELL)"
    msg = (
        f"[实盘订单已报送·成交提醒]\n"
        f"操作方向: {dir_label}\n"
        f"标的信息: {display_target}\n"
        f"委托数量: {quantity} 股 | 委托价格: {price:.2f} 元\n"
        f"委托单号: {order_id}\n"
        f"成交原因: {reason}\n"
        f"剩余现金: {cash_remaining:,.2f} 元\n"
        f"订单已报入券商交易柜台，请注意分时成交回报。"
    )
    return send_feishu_message(msg, webhook_url=webhook_url)
