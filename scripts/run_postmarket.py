#!/usr/bin/env python3
"""盘后处理入口."""
from __future__ import annotations

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("postmarket")


def main() -> None:
    """Run post-market processing: performance, sector flow, evolution audit."""
    logger.info("Starting post-market pipeline")

    try:
        from evolution.performance_reporter import main as perf_main
        perf_main()
        logger.info("Performance report generated")
    except ImportError:
        logger.warning("evolution.performance_reporter not available")

    try:
        from intelligence.sector_flow import main as sector_main
        sector_main()
        logger.info("Sector flow report generated")
    except ImportError:
        logger.warning("intelligence.sector_flow not available")

    try:
        from evolution.strategy_audit import main as audit_main
        audit_main()
        logger.info("Evolution audit completed")
    except ImportError:
        logger.warning("evolution.strategy_audit not available")

    try:
        from discovery.limitup_scanner import get_ladder
        get_ladder()
        logger.info("Limit-up ladder built")
    except ImportError:
        logger.warning("discovery.limitup_scanner.get_ladder not available")

    logger.info("Post-market pipeline finished")


if __name__ == "__main__":
    main()
