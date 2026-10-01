#!/usr/bin/env python3
"""APScheduler-based scheduler for A-stock trading pipeline.

Maps cron job definitions from myhermes/cron/jobs.json to APScheduler jobs
running in the Astock project context. Uses Asia/Shanghai timezone.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("scheduler")


# ── Premarket (09:00-09:25 CST) ──


def theme_arbitrage_scanner() -> None:
    """09:10 — 隔日题材套利盘前雷达: discovery scan for theme arbitrage."""
    try:
        from discovery.theme_arbitrage_scanner import scan
        scan()
    except ImportError:
        logger.warning("discovery.theme_arbitrage_scanner not available")


def print_playbook() -> None:
    """09:20 — 盘前预案与实战打法指令卡."""
    try:
        from scripts.run_premarket import main
        main()
    except ImportError:
        logger.warning("scripts.run_premarket not available")


def morning_master() -> None:
    """09:25 — 早盘主控 orchestrator."""
    try:
        from orchestrator.morning_master import run
        run()
    except ImportError:
        logger.warning("orchestrator.morning_master not available")


# ── Intraday (every 5 min, 09:30-14:55 CST) ──


def market_regime() -> None:
    """Refresh market regime state."""
    try:
        from core.market_regime import MarketRegime
        mr = MarketRegime()
        mr.detect()
        mr.save()
        logger.info("Market regime refreshed")
    except ImportError:
        logger.warning("core.market_regime not available")


def direct_executor() -> None:
    """即时执行轮询 — check and execute approved intents."""
    try:
        from execution.direct_executor import execute_loop
        execute_loop()
    except ImportError:
        logger.warning("execution.direct_executor not available")


def full_market_discovery() -> None:
    """全A盘中多入口宽发现器."""
    try:
        from discovery.full_market_discovery import discover_wide_pool
        discover_wide_pool()
    except ImportError:
        logger.warning("discovery.full_market_discovery not available")


def leader_monitor() -> None:
    """持仓与警戒计划统一监控."""
    try:
        from execution.leader_monitor import monitor
        monitor()
    except ImportError:
        logger.warning("execution.leader_monitor not available")


# ── Watchdog (every 15 min) ──


def watchdog() -> None:
    """交易轮次守护 — check for missed cron runs and backfill."""
    try:
        from defense.watchdog import check
        check()
    except ImportError:
        logger.warning("defense.watchdog not available")


# ── Close session gate (10:55, 14:55 CST) ──


def batch_trade_gate() -> None:
    """统一交易闸门 — 持仓检查/未成交过期撤单."""
    try:
        from execution.batch_trade_gate import run_gate
        run_gate()
    except ImportError:
        logger.warning("execution.batch_trade_gate not available")


# ── Close session defense (14:15, 14:30, 14:45 CST) ──


def close_session_defense() -> None:
    """尾盘清仓防守 — 弱势持仓止损/止盈."""
    try:
        from defense.close_session_defense import run_defense
        run_defense()
    except ImportError:
        logger.warning("defense.close_session_defense not available")


# ── Post-market (15:15+ CST) ──


def performance_report() -> None:
    """盘后绩效报告."""
    try:
        from intelligence.performance_report import generate
        generate()
    except ImportError:
        logger.warning("intelligence.performance_report not available")


def sector_flow() -> None:
    """盘后板块资金流向记录."""
    try:
        from intelligence.sector_flow import report
        report()
    except ImportError:
        logger.warning("intelligence.sector_flow not available")


def evolution_audit() -> None:
    """每日策略进化审计."""
    try:
        from evolution.evolution_audit import audit
        audit()
    except ImportError:
        logger.warning("evolution.evolution_audit not available")


# ── Scheduler setup ──


def build_scheduler() -> BlockingScheduler:
    """Build and configure the blocking scheduler with all trading jobs."""
    scheduler = BlockingScheduler(timezone="Asia/Shanghai")

    # Premarket
    scheduler.add_job(
        theme_arbitrage_scanner,
        CronTrigger(hour=9, minute=10, timezone="Asia/Shanghai"),
        id="theme_arbitrage_scanner",
        name="隔日题材套利盘前雷达",
    )
    scheduler.add_job(
        print_playbook,
        CronTrigger(hour=9, minute=20, timezone="Asia/Shanghai"),
        id="print_playbook",
        name="盘前预案与实战打法指令卡",
    )
    scheduler.add_job(
        morning_master,
        CronTrigger(hour=9, minute=25, timezone="Asia/Shanghai"),
        id="morning_master",
        name="早盘主控 orchestrator",
    )

    # Intraday — every 5 min during trading hours (09:30-11:30, 13:00-14:55)
    for job_id, func, desc in [
        ("market_regime", market_regime, "市场状态机刷新"),
        ("direct_executor", direct_executor, "即时执行轮询"),
        ("full_market_discovery", full_market_discovery, "全市场发现"),
        ("leader_monitor", leader_monitor, "持仓与警戒监控"),
    ]:
        scheduler.add_job(
            func,
            CronTrigger(minute="*/5", hour="9-11,13-14", timezone="Asia/Shanghai"),
            id=job_id,
            name=desc,
        )

    # Watchdog — every 15 min during trading
    scheduler.add_job(
        watchdog,
        CronTrigger(minute="*/15", hour="9-15", timezone="Asia/Shanghai"),
        id="watchdog",
        name="交易轮次守护",
    )

    # Trade gate — 10:55 AM and 14:55 PM
    scheduler.add_job(
        batch_trade_gate,
        CronTrigger(minute=55, hour="10,14", timezone="Asia/Shanghai"),
        id="batch_trade_gate",
        name="统一交易闸门",
    )

    # Close session defense — 14:15, 14:30, 14:45
    scheduler.add_job(
        close_session_defense,
        CronTrigger(minute="15,30,45", hour=14, timezone="Asia/Shanghai"),
        id="close_session_defense",
        name="尾盘清仓防守",
    )

    # Post-market — 15:15, 15:30, 15:55
    scheduler.add_job(
        sector_flow,
        CronTrigger(minute=15, hour=15, timezone="Asia/Shanghai"),
        id="sector_flow",
        name="盘后板块资金流向",
    )
    scheduler.add_job(
        performance_report,
        CronTrigger(minute=30, hour=15, timezone="Asia/Shanghai"),
        id="performance_report",
        name="盘后绩效报告",
    )
    scheduler.add_job(
        evolution_audit,
        CronTrigger(minute=55, hour=15, timezone="Asia/Shanghai"),
        id="evolution_audit",
        name="每日策略进化审计",
    )

    return scheduler


def main() -> None:
    """Start the blocking scheduler."""
    logger.info("Starting A-stock trading scheduler (Asia/Shanghai)")
    scheduler = build_scheduler()
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
        scheduler.shutdown(wait=False)


if __name__ == "__main__":
    main()
