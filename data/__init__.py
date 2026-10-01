"""数据管理器 — JSONL 账本、状态文件、原子写入."""

from __future__ import annotations

import datetime as dt
import fcntl
import json
import os
from pathlib import Path
from typing import Any

from config import DATA_DIR, LEDGER_DIR, MEMORY_DIR, STATE_DIR


class DataManager:
    """线程安全的持久化数据管理。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or DATA_DIR
        self.ledger_dir = self.root / "ledger"
        self.state_dir = self.root / "state"
        self.memory_dir = self.root / "memory"
        for d in [self.ledger_dir, self.state_dir, self.memory_dir]:
            d.mkdir(parents=True, exist_ok=True)

    # ── JSONL 账本 ──

    def append_jsonl(self, record: dict[str, Any], date: str | None = None) -> None:
        """线程安全的 JSONL 追加（fcntl.flock 直接追加到目标文件，避免 tmp 覆盖丢失数据）。"""
        date = date or dt.date.today().isoformat()
        path = self.ledger_dir / f"candidates_{date}.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                f.flush()
                os.fsync(f.fileno())
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)

    def read_jsonl(self, date: str | None = None) -> list[dict[str, Any]]:
        date = date or dt.date.today().isoformat()
        path = self.ledger_dir / f"candidates_{date}.jsonl"
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return records

    # ── 状态文件（JSON）──

    def load_state(self, name: str) -> dict[str, Any]:
        path = self.state_dir / name
        if not path.exists():
            return {}
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def save_state(self, name: str, data: Any) -> None:
        """原子写入状态文件。"""
        path = self.state_dir / name
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)

    # ── 候选管理 ──

    def load_candidates(self, date: str | None = None) -> list[dict[str, Any]]:
        """从 JSONL 加载候选并合并更新记录。"""
        records = self.read_jsonl(date)
        candidates: dict[str, dict[str, Any]] = {}
        updates: dict[str, dict[str, Any]] = {}
        for rec in records:
            rt = rec.get("record_type", "candidate")
            cid = rec.get("candidate_id")
            if not cid:
                continue
            if rt == "candidate":
                candidates[cid] = rec
            elif rt in ("candidate_update", "llm_review"):
                updates[cid] = rec
        for cid, upd in updates.items():
            if cid in candidates:
                candidates[cid].update(upd)
                # Preserve original record_type — update records should not overwrite it
                candidates[cid]["record_type"] = "candidate"
        return list(candidates.values())


_data_manager: DataManager | None = None


def get_data_manager() -> DataManager:
    global _data_manager
    if _data_manager is None:
        _data_manager = DataManager()
    return _data_manager
