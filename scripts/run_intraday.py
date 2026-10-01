#!/usr/bin/env python3
"""盘中扫描+执行入口."""
from __future__ import annotations

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("intraday")


def main() -> None:
    """Run intraday pipeline: discovery, theme trigger, execution loop."""
    logger.info("Starting intraday pipeline")

    pool: list[dict] = []
    try:
        from discovery.full_market_discovery import discover_wide_pool
        pool = discover_wide_pool() or []
        logger.info("Discovered %d candidates in wide pool", len(pool))
    except ImportError:
        logger.warning("discovery.full_market_discovery not available")

    try:
        from discovery.theme_trigger import trigger_themes
        themes = trigger_themes(pool) if pool else []
        logger.info("Triggered %d themes", len(themes))
    except ImportError:
        logger.warning("discovery.theme_trigger not available")

    try:
        from execution.direct_executor import execute_loop
        execute_loop()
        logger.info("Execution loop completed")
    except ImportError:
        logger.warning("execution.direct_executor not available")


if __name__ == "__main__":
    main()
