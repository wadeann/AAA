#!/usr/bin/env python3
"""盘后处理入口."""
from __future__ import annotations

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("postmarket")


def main() -> None:
    """Run post-market processing: performance, sector flow, evolution audit."""
    logger.info("Starting post-market pipeline")

    try:
        from intelligence.performance_report import generate
        generate()
        logger.info("Performance report generated")
    except ImportError:
        logger.warning("intelligence.performance_report not available")

    try:
        from intelligence.sector_flow import report
        report()
        logger.info("Sector flow report generated")
    except ImportError:
        logger.warning("intelligence.sector_flow not available")

    try:
        from evolution.evolution_audit import audit
        audit()
        logger.info("Evolution audit completed")
    except ImportError:
        logger.warning("evolution.evolution_audit not available")

    try:
        from discovery.ladder_builder import build
        build()
        logger.info("Limit-up ladder built")
    except ImportError:
        logger.warning("discovery.ladder_builder not available")

    logger.info("Post-market pipeline finished")


if __name__ == "__main__":
    main()
