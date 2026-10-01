#!/usr/bin/env python3
"""盘前流水线入口."""
from __future__ import annotations

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("premarket")


def main() -> None:
    """Run pre-market pipeline: sentiment + regime detection."""
    logger.info("Starting pre-market pipeline")
    try:
        from core.sentiment_engine import compute_sentiment
        sent = compute_sentiment()
        logger.info("Sentiment: phase=%s multiplier=%.2f", sent["phase"], sent["multiplier"])
    except ImportError:
        logger.warning("core.sentiment_engine not available")
        sent = {"phase": "unknown", "multiplier": 0.0}

    try:
        from core.market_regime import MarketRegime
        mr = MarketRegime()
        state = mr.detect()
        mr.save()
        logger.info("Regime: %s (multiplier=%.2f)", state["regime"], state["regime_multiplier"])
    except ImportError:
        logger.warning("core.market_regime not available")
        state = {"regime": "unknown", "regime_multiplier": 0.0}

    print(f"Sentiment: {sent['phase']}, Regime: {state['regime']}")


if __name__ == "__main__":
    main()
