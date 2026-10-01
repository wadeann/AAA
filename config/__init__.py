"""配置加载器 — 加载 YAML/JSON 配置与环境变量."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore

ASTOCK_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ASTOCK_ROOT / "data"
STATE_DIR = DATA_DIR / "state"
LEDGER_DIR = DATA_DIR / "ledger"
MEMORY_DIR = DATA_DIR / "memory"


def _find_config(name: str) -> Path | None:
    for d in [ASTOCK_ROOT / "config", ASTOCK_ROOT]:
        p = d / name
        if p.exists():
            return p
    return None


def load_yaml(name: str) -> dict[str, Any]:
    """从 config/ 或项目根目录加载 YAML 文件."""
    p = _find_config(name)
    if not p:
        return {}
    if yaml is None:
        raise ImportError("PyYAML required to load YAML config")
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_json(name: str, subdir: str | None = None) -> dict[str, Any]:
    """从 config/ 或 data/state/ 加载 JSON 文件."""
    base = ASTOCK_ROOT / "config" if subdir is None else STATE_DIR
    p = base / name
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_json(name: str, data: Any, subdir: str | None = None) -> None:
    """原子写入 JSON 文件（tmp + replace）。"""
    base = ASTOCK_ROOT / "config" if subdir is None else STATE_DIR
    base.mkdir(parents=True, exist_ok=True)
    tmp = base / f"{name}.tmp"
    dst = base / name
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, dst)


def get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)
