#!/usr/bin/env python3
"""System health check — test MCP connectivity, data directories, chanlun engine."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root is importable when run as a script
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("check_system")


def check_mcp() -> bool:
    """Test MCP server connectivity via trading_sessions on intel port."""
    try:
        from mcp_client import get_mcp_client
        client = get_mcp_client()
        sessions = client.get_trading_sessions()
        if isinstance(sessions, dict):
            logger.info("MCP intel: OK (trading_sessions returned %d keys)", len(sessions))
            return True
        logger.warning("MCP intel: unexpected response type: %s", type(sessions).__name__)
        return False
    except ImportError:
        logger.warning("MCP client module not found")
        return False
    except Exception as exc:
        logger.warning("MCP intel: FAIL — %s", exc)
        return False


def check_data_dirs() -> bool:
    """Verify all expected data directories exist."""
    from config import ASTOCK_ROOT, DATA_DIR, STATE_DIR, LEDGER_DIR, MEMORY_DIR
    expected = [
        ("root", ASTOCK_ROOT),
        ("data", DATA_DIR),
        ("state", STATE_DIR),
        ("ledger", LEDGER_DIR),
        ("memory", MEMORY_DIR),
        ("config", ASTOCK_ROOT / "config"),
        ("scripts", ASTOCK_ROOT / "scripts"),
        ("tests", ASTOCK_ROOT / "tests"),
    ]
    all_ok = True
    for name, path in expected:
        if path.exists():
            logger.info("Directory %s: %s — OK", name, path)
        else:
            logger.warning("Directory %s: %s — MISSING", name, path)
            all_ok = False
    return all_ok


def check_chanlun() -> bool:
    """Test chanlun engine with sample synthetic data."""
    try:
        from core.chanlun_engine import analyze_chanlun
        test_bars = [
            {"time": f"2026-01-{d:02d}", "open": 10 + i * 0.1, "high": 11 + i * 0.2,
             "low": 9 + i * 0.05, "close": 10.5 + i * 0.15, "volume": 1_000_000 + i * 10_000}
            for i, d in enumerate(range(1, 31), 1)
        ]
        result = analyze_chanlun(test_bars)
        required_keys = {"bar_count", "merged_bar_count", "fractal_count", "stroke_count",
                         "pivot_count", "trend_type", "buy_point", "sell_point", "confirmed"}
        missing = required_keys - set(result.keys())
        if missing:
            logger.warning("Chanlun: missing keys: %s", missing)
            return False
        logger.info(
            "Chanlun: OK — %d bars, %d strokes, trend=%s buy=%s confirmed=%s",
            result["bar_count"], result["stroke_count"],
            result["trend_type"], result["buy_point"], result["confirmed"],
        )
        return True
    except ImportError as exc:
        logger.warning("Chanlun engine import FAIL: %s", exc)
        return False
    except Exception as exc:
        logger.warning("Chanlun engine runtime FAIL: %s", exc)
        return False


def main() -> None:
    """Run all system checks and report PASS/FAIL."""
    checks = [
        ("MCP Server Connectivity", check_mcp),
        ("Data Directories", check_data_dirs),
        ("Chanlun Engine", check_chanlun),
    ]

    print("=" * 60)
    print("  A-stock System Health Check")
    print("=" * 60)
    print()

    all_pass = True
    for name, func in checks:
        print(f"  [{name:30s}] ", end="", flush=True)
        ok = func()
        if ok:
            print(f"  {'PASS':>4s}")
        else:
            print(f"  {'FAIL':>4s}")
            all_pass = False

    print()
    print("=" * 60)
    if all_pass:
        print("  OVERALL: ALL CHECKS PASSED")
    else:
        print("  OVERALL: SOME CHECKS FAILED")
    print("=" * 60)

    sys.exit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
