#!/usr/bin/env python3
"""Antigravity Bridge — delegate qualitative analysis to AGY CLI.

Provides a robust interface for trading workflows to delegate deep qualitative
analysis, Chanlun geometry reasoning, and strategy reviews to Google Antigravity
(AGY).

Features:
- Default invocation without hardcoding model.
- Automatic fallback to Gemini 3.7 Flash (High) if quota / rate limit is reached.
- AGY CLI at ~/.local/bin/agy
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Any, Dict, Optional

AGY_PATH = os.path.expanduser("~/.local/bin/agy")
JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```")
FALLBACK_MODEL = "Gemini 3.7 Flash (High)"
QUOTA_ERROR_KEYWORDS = ("quota", "rate limit", "resource_exhausted", "429", "exceeded", "credit")


def ask_antigravity(
    prompt: str,
    timeout: int = 360,
    continue_session: bool = False,
    extra_env: Optional[Dict[str, str]] = None,
    model: Optional[str] = None,
    auto_fallback: bool = True,
) -> str:
    """Execute a prompt against Antigravity CLI and return the response."""
    cmd = [AGY_PATH]
    if continue_session:
        cmd.append("-c")
    if model:
        cmd.extend(["--model", model])
    cmd.extend(["-p", prompt, "--dangerously-skip-permissions", "--print-timeout", "6m"])

    env = {**os.environ}
    if extra_env:
        env.update(extra_env)

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        if res.returncode == 0:
            return res.stdout.strip()
        err = res.stderr.strip() or f"exited with code {res.returncode}"

        # 检查是否额度耗尽或速率受限，若是且未指定 fallback model，则降级重试
        err_lower = err.lower()
        if auto_fallback and model != FALLBACK_MODEL and any(k in err_lower for k in QUOTA_ERROR_KEYWORDS):
            print(f"[AGY] Quota/RateLimit error detected ({err[:80]}), falling back to {FALLBACK_MODEL}...", flush=True)
            return ask_antigravity(
                prompt,
                timeout=timeout,
                continue_session=continue_session,
                extra_env=extra_env,
                model=FALLBACK_MODEL,
                auto_fallback=False,
            )

        return f"[ANTIGRAVITY_ERROR]: {err}"
    except subprocess.TimeoutExpired:
        return "[ANTIGRAVITY_ERROR]: Timeout waiting for Antigravity response"
    except Exception as e:
        return f"[ANTIGRAVITY_ERROR]: {e}"


def ask_antigravity_json(
    prompt: str,
    timeout: int = 360,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a prompt expecting a JSON response from Antigravity."""
    enhanced_prompt = (
        f"{prompt}\n\n"
        "【重要要求】：请将最终结论以标准 JSON 格式输出，用 ```json ... ``` 包裹。"
    )
    raw = ask_antigravity(enhanced_prompt, timeout=timeout, model=model)
    if raw.startswith("[ANTIGRAVITY_ERROR]"):
        print(f"[AGY_ERROR] ask_antigravity_json failed: {raw}", flush=True)
        return {"status": "error", "error": raw}

    # Try extracting markdown json block
    match = JSON_BLOCK_RE.search(raw)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Try direct parse
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return {"status": "raw", "text": raw}


if __name__ == "__main__":
    print("Testing antigravity_bridge (default model with auto-fallback)...", flush=True)
    res = ask_antigravity("请用一句话回答：测试 Antigravity Bridge 运行是否正常。")
    print("Response:", res, flush=True)
