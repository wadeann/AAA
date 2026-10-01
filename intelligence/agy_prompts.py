#!/usr/bin/env python3
"""AGY prompt templates — reusable audit and review prompts for Antigravity."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# ── Template Helpers ──


def embed_file_content(path: str) -> str:
    """Read a file and wrap it in a markdown code block for embedding in prompts.

    Returns an empty string if the file cannot be read.
    """
    p = Path(path).expanduser()
    if not p.exists():
        return ""
    try:
        content = p.read_text(encoding="utf-8")
    except Exception:
        return ""
    return f"\n```python\n{content}\n```\n"


# ── Audit Prompts ──

AGY_AUDIT_PROMPT = """You are an independent auditor. Audit these Python files for bugs in a Chinese A-share trading system. The files are printed below IN FULL. Read them carefully.

{file_content}

## AUDIT CHECKLIST
1. Any None-safety bugs, type errors, div/0?
2. Are all callers of changed function signatures updated?
3. Consistency across all files?
4. Any scanner missing ebb_subtype awareness?

## OUTPUT FORMAT
## Score: X/100
## Issues Found: (numbered list with file:line and exact fix code, or "None found")
## Consistency Check: PASS/FAIL
## Verdict: APPROVED / FIXES_REQUIRED

Be strict. Do NOT pass a flawed implementation. If you find bugs, describe the exact fix."""


CLOSE_REVIEW_PROMPT = """You are an A-share position closing reviewer. Review the following position for exit decision:

{position_info}

Current market regime: {market_regime}
Current P&L: {pnl_info}

Analyze whether to hold, reduce, or close:
1. Is the original thesis still intact?
2. Has the stock broken any key technical levels?
3. Is the broader market regime supportive or adverse?
4. What is the risk/reward of holding another 1-3 days?

Output your conclusion as a JSON block with: decision (hold/reduce/close), reason, suggested_stop_loss (if holding)."""


EVOLUTION_AUDIT_PROMPT = """You are a strategy evolution analyst. Review the following strategy performance data and provide optimization recommendations:

{strategy_stats}

Current market regime: {market_regime}

Historical action items: {action_items}

Please analyze:
1. Which strategy segments are degrading vs improving?
2. Are there regime-specific adjustments needed?
3. Should any confidence thresholds be recalibrated?
4. Are there emerging patterns worth adding as new strategy rules?

Output your analysis as a concise report with actionable recommendations."""

SECTOR_FLOW_PROMPT = """You are the A-share capital flow and sector rotation chief analyst. Based on today's sector capital flow data for deep analysis:
- Today's main force sector data: {sector_data}

【Output constraints】：Strictly limited to 4-5 lines:
1. Today's strongest net inflow sectors and leading themes
2. Main force capital withdrawal direction
3. Tomorrow's sector rotation and attack direction forecast"""
