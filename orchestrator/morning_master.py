#!/usr/bin/env python3
"""
09:25-09:30 pre-market unified orchestrator (Morning Master Orchestrator).

Sequential phases:
1. 09:24:50 MCP warmup
2. 09:25:05 call_auction_scanner (gap-up high-volume recognition)
3. 09:25:20 limit_up_scanner (yesterday limit-up weak-to-strong scan)
4. 09:25:35 batch risk control + dynamic position calculation
5. 09:26:00 autonomous-trade-gate pending order prep
6. 09:30:00 market open auto-submit orders

Single cron entry: trading day 09:24:50
All MCP via MCPClient. All paths via config.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from mcp_client import get_mcp_client

SCRIPTS = Path(__file__).resolve().parent.parent / "execution"


def build_non_buy_notice(
    reason: str,
    position_lines: list[str] | None = None,
    *,
    catchup: bool = False,
) -> str:
    """Build the 09:25 deterministic non-buy notice to avoid Feishu silence."""
    title = "竞价09:25补发" if catchup else "竞价09:25"
    lines = [title, f"非买入：{reason}"]
    if position_lines:
        lines.append("持有 " + "、".join(position_lines[:3]))
    return "\n".join(lines)


def send_non_buy_notice(
    reason: str,
    position_lines: list[str] | None = None,
    *,
    catchup: bool = False,
) -> bool:
    """Send non-buy notice; fallback to stdout."""
    message = build_non_buy_notice(reason, position_lines, catchup=catchup)
    try:
        from intelligence.feishu_notifier import send_feishu_message

        ok = bool(send_feishu_message(message))
    except Exception as exc:
        print(f"Non-buy notice send exception: {exc}", flush=True)
        ok = False
    print(message, flush=True)
    return ok


def summarize_non_buy_reason(phase1: str, phase2: str, phase25: str) -> str:
    """Compress zero-candidate conclusions from all scanners into a decision summary."""
    reasons: list[str] = []
    if "无满足条件候选" in phase1:
        reasons.append("竞价无满足条件候选")
    if "最终写入 0 个" in phase2 or "首板: 0只" in phase2:
        reasons.append("连板/真龙候选0只")
    if "注入实盘候选 0 笔" in phase25 and "连板/真龙候选0只" not in reasons:
        reasons.append("真龙策略无可执行候选")
    return "；".join(reasons) or "扫描完成但无可执行买入候选"


def now_cst() -> dt.datetime:
    """Return current CST time (UTC+8)."""
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))


def check_trading_day() -> bool:
    """Check if today is a trading day via MCP + weekday double-check."""
    try:
        client = get_mcp_client()
        return client.is_trading_day()
    except Exception:
        pass
    return dt.date.today().weekday() < 5


def run_phase(script_name: str, timeout: int = 60) -> str:
    """Run a sub-script and return its output summary (last 400 chars)."""
    script = SCRIPTS / script_name
    if not script.exists():
        return f"脚本不存在: {script_name}"
    try:
        r = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = r.stdout.strip()
        if r.returncode != 0:
            output += f"\n[stderr] {r.stderr.strip()[:300]}"
        return output[-400:]
    except subprocess.TimeoutExpired:
        return f"超时({timeout}s): {script_name}"
    except Exception as e:
        return f"异常: {script_name}: {e}"


def run_dragon_phase_and_execute(timeout: int = 75) -> str:
    """Run dragon screener then immediately execute candidates."""
    scan_out = run_phase("dragon_screener_engine.py", timeout=timeout)
    if scan_out.startswith("超时") or scan_out.startswith("异常"):
        return scan_out
    execute_out = run_phase("direct_executor.py", timeout=75)
    return f"{scan_out}\n[即时执行] {execute_out}"


def main() -> int:
    """Execute the morning orchestration sequence."""
    start_ts = time.time()
    now = now_cst()
    print(f"早盘调度器启动 [{now.strftime('%H:%M:%S')}]", flush=True)

    if not check_trading_day():
        print("非交易日，跳过", flush=True)
        return 0

    timeline: list[str] = []
    elapsed = lambda: f"+{time.time() - start_ts:.0f}s"
    client = get_mcp_client()

    # ── Phase 0: MCP warmup (09:24:50) ──
    print(f"\n[{elapsed()}] Phase 0: MCP预热", flush=True)
    for port, name in [(9001, "Intel"), (9002, "Risk"), (9003, "Exec")]:
        try:
            if port == 9003:
                client.get_balance()
            else:
                client.call("query_batch_data", {"codes": "000001"}, port=port)
            print(f"  {name} MCP ({port}) 在线 [{elapsed()}]", flush=True)
        except Exception as e:
            print(f"  {name} MCP ({port}) 连接异常: {e} [{elapsed()}]", flush=True)
    timeline.append(f"Phase0 MCP预热: {now_cst().strftime('%H:%M:%S')}")

    # ── Phase 0.5: Strategy params init ──
    print(f"\n[{elapsed()}] Phase 0.5: 情绪策略参数初始化", flush=True)
    t05 = time.time()
    try:
        p = subprocess.run(
            [sys.executable, str(SCRIPTS / "strategy_params_init.py")],
            capture_output=True, text=True, timeout=15,
        )
        print(p.stdout.strip(), flush=True)
        if p.returncode != 0:
            print(f"  [stderr] {(p.stderr or '').strip()[:200]}", flush=True)
    except subprocess.TimeoutExpired:
        print(f"  strategy_params_init.py 超时(15s) [{elapsed()}]", flush=True)
    except Exception as e:
        print(f"  策略参数初始化异常: {e} [{elapsed()}]", flush=True)
    d05 = time.time() - t05
    timeline.append(f"Phase0.5 策略参数: {now_cst().strftime('%H:%M:%S')} ({d05:.1f}s)")

    # ── Phase 0.75: Market regime refresh ──
    print(f"\n[{elapsed()}] Phase 0.75: 刷新市场状态机", flush=True)
    t075 = time.time()
    try:
        p = subprocess.run(
            [sys.executable, str(SCRIPTS / "market_regime.py")],
            capture_output=True, text=True, timeout=30,
        )
        output = p.stdout.strip()
        print(f"  {output[:300] if output else '(空输出)'}", flush=True)
        if p.returncode != 0:
            print(f"  [stderr] {(p.stderr or '').strip()[:200]}", flush=True)
    except subprocess.TimeoutExpired:
        print(f"  market_regime.py 超时(30s) [{elapsed()}]", flush=True)
    except Exception as e:
        print(f"  市场状态机刷新异常: {e} [{elapsed()}]", flush=True)
    d075 = time.time() - t075
    timeline.append(f"Phase0.75 市场状态: {now_cst().strftime('%H:%M:%S')} ({d075:.1f}s)")

    # ── Phase 0.8: Active portfolio cleaning ──
    print(f"\n[{elapsed()}] Phase 0.8: 主动持仓调仓腾槽", flush=True)
    t08 = time.time()
    position_names: list[str] = []
    try:
        p = subprocess.run(
            [sys.executable, str(SCRIPTS / "active_portfolio_cleaner.py")],
            capture_output=True, text=True, timeout=20,
        )
        print(p.stdout.strip(), flush=True)
        for line in p.stdout.splitlines():
            if "[" in line and "]" in line:
                label = line.split("[", 1)[1].split("]", 1)[0].strip()
                if label:
                    position_names.append(label)
        if p.returncode != 0:
            print(f"  [stderr] {(p.stderr or '').strip()[:200]}", flush=True)
    except subprocess.TimeoutExpired:
        print(f"  active_portfolio_cleaner.py 超时(20s) [{elapsed()}]", flush=True)
    except Exception as e:
        print(f"  主动持仓调仓腾槽异常: {e} [{elapsed()}]", flush=True)
    d08 = time.time() - t08
    timeline.append(f"Phase0.8 调仓腾槽: {now_cst().strftime('%H:%M:%S')} ({d08:.1f}s)")

    # ── Phase 0.85: Wait for auction match (09:25:05) ──
    print(f"\n[{elapsed()}] Phase 0.85: 等待竞价撮合(09:25:05)", flush=True)
    target = now_cst().replace(hour=9, minute=25, second=5, microsecond=0)
    sleep_sec = (target - now_cst()).total_seconds()
    if sleep_sec > 0:
        print(f"等待 {sleep_sec:.1f}s 到 09:25:05... [{elapsed()}]", flush=True)
        time.sleep(sleep_sec)
    timeline.append(f"Phase0.85 等待竞价: {now_cst().strftime('%H:%M:%S')}")

    # ── Phase 0.9: Auction kill switch (09:25:05+) ──
    print(f"\n[{elapsed()}] Phase 0.9: 竞价核按钮决断(09:25:05)", flush=True)
    t09 = time.time()
    try:
        p = subprocess.run(
            [sys.executable, str(SCRIPTS / "auction_kill_switch.py"), "--force"],
            capture_output=True, text=True, timeout=20,
        )
        output = p.stdout.strip()
        print(f"  {output[:400] if output else '无持仓/无触发'}", flush=True)
        if p.returncode != 0:
            print(f"  [stderr] {(p.stderr or '').strip()[:200]}", flush=True)
    except subprocess.TimeoutExpired:
        print(f"  auction_kill_switch.py 超时(20s) [{elapsed()}]", flush=True)
    except Exception as e:
        print(f"  竞价核按钮异常: {e} [{elapsed()}]", flush=True)
    d09 = time.time() - t09
    timeline.append(f"Phase0.9 核按钮: {now_cst().strftime('%H:%M:%S')} ({d09:.1f}s)")

    # ── Phase 0.95: Position guard ──
    print(f"\n[{elapsed()}] Phase 0.95: 风控前置拦截检查", flush=True)
    guard_blocked = False
    guard_out = ""
    t095 = time.time()
    try:
        p = subprocess.run(
            [sys.executable, str(SCRIPTS / "position_guard.py")],
            capture_output=True, text=True, timeout=10,
        )
        guard_out = p.stdout.strip()
        print(f"  {guard_out[:400] if guard_out else '(空)'}", flush=True)
        guard_blocked = False
        try:
            for line in reversed(guard_out.splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    data = json.loads(line)
                    guard_blocked = bool(data.get("blocked", False))
                    break
            else:
                guard_blocked = '"blocked": true' in guard_out.lower()
        except Exception:
            guard_blocked = '"blocked": true' in guard_out.lower()
    except subprocess.TimeoutExpired:
        print(f"  position_guard.py 超时(10s) [{elapsed()}]", flush=True)
    except Exception as e:
        print(f"  position_guard异常: {e} [{elapsed()}]", flush=True)
    d095 = time.time() - t095
    timeline.append(f"Phase0.95 风控: {now_cst().strftime('%H:%M:%S')} ({d095:.1f}s) blocked={guard_blocked}")

    if guard_blocked:
        print(f"Phase 0.95 仓位/情绪硬拦截触发，阻断今日新增买入流水线！[{elapsed()}]", flush=True)
        timeline.append("Phase0.95 阻断: 仅允许核按钮卖出，跳过买入扫描")
        reason = "风控硬拦截，今日新增买入阻断"
        try:
            for line in reversed(guard_out.splitlines()):
                line = line.strip()
                if line.startswith("{") and line.endswith("}"):
                    reason = str(json.loads(line).get("reason") or reason)
                    break
        except Exception:
            pass
        send_non_buy_notice(reason, position_names)
    else:
        # ── Phase 1: Auction scan (09:25:05+) ──
        print(f"\n[{elapsed()}] Phase 1: 竞价高开爆量识别", flush=True)
        t1 = time.time()
        phase1 = run_phase("call_auction_scanner.py", timeout=45)
        d1 = time.time() - t1
        print(f"[{elapsed()}] Phase1 完成 (耗时 {d1:.1f}s): {phase1}", flush=True)
        timeline.append(f"Phase1 竞价扫描: {now_cst().strftime('%H:%M:%S')} ({d1:.1f}s)")

        # ── Phase 2: Limit-up weak-to-strong scan (09:25:20) ──
        print(f"\n[{elapsed()}] Phase 2: 连板/弱转强扫描", flush=True)
        time.sleep(5)
        t2 = time.time()
        phase2 = run_phase("limit_up_scanner.py", timeout=45)
        d2 = time.time() - t2
        print(f"[{elapsed()}] Phase2 完成 (耗时 {d2:.1f}s): {phase2}", flush=True)
        timeline.append(f"Phase2 连板扫描: {now_cst().strftime('%H:%M:%S')} ({d2:.1f}s)")

        # ── Phase 2.5: Dragon candidate filtering (09:25:35) ──
        print(f"\n[{elapsed()}] Phase 2.5: 六因子真龙筛选与卡位决断", flush=True)
        time.sleep(3)
        t25 = time.time()
        phase25 = run_dragon_phase_and_execute(timeout=75)
        d25 = time.time() - t25
        print(f"[{elapsed()}] Phase2.5 完成 (耗时 {d25:.1f}s): {phase25}", flush=True)
        timeline.append(f"Phase2.5 真龙筛选: {now_cst().strftime('%H:%M:%S')} ({d25:.1f}s)")

        # Send non-buy notice if zero candidates across all scan phases
        zero_candidate = (
            "无满足条件候选" in phase1
            and ("最终写入 0 个" in phase2 or "首板: 0只" in phase2)
            and "注入实盘候选 0 笔" in phase25
        )
        if zero_candidate:
            send_non_buy_notice(
                summarize_non_buy_reason(phase1, phase2, phase25),
                position_names,
            )

    # Hand off to direct-executor polling
    print(f"\n[{elapsed()}] Phase 3: 已交接 direct-executor 开盘执行轮询", flush=True)
    timeline.append(f"Phase3 交接执行器: {now_cst().strftime('%H:%M:%S')}")

    print(f"\n[{elapsed()}] 时间线:", flush=True)
    for t in timeline:
        print(f"  {t}", flush=True)

    total = time.time() - start_ts
    print(f"\n早盘调度完毕 (总耗时 {total:.0f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
