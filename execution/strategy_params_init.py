#!/usr/bin/env python3
"""Strategy params init — sentiment engine shim.

Morning master Phase 0.5: compute sentiment from index quotes
and persist to strategy_params.json sentiment block.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from config import STATE_DIR
from core.sentiment_engine import compute_sentiment


def main() -> None:
    sentiment = compute_sentiment()
    params_path = STATE_DIR / "strategy_params.json"
    if params_path.exists():
        params = json.loads(params_path.read_text(encoding="utf-8"))
    else:
        params = {}
    params["sentiment"] = sentiment
    tmp = params_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(params, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(params_path)
    print(f"sentiment: {sentiment['phase']} multiplier={sentiment['multiplier']}")


if __name__ == "__main__":
    main()
