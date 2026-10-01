# Candidate JSONL 去重模式参考

## 问题

`candidates_YYYY-MM-DD.jsonl` 被多个脚本并发/顺序追加写入，每个脚本用 `open("a")` 不检查已有 `candidate_id`，导致同一天相同候选出现多次（不同时间戳的价格快照）。周期性脚本（如 `intraday_leader_monitor.py` 每 5 分钟）是主要重复源。

## 去重策略

- **去重键**：`candidate_id` 字段（如 `alert-600468.SH-buy-2026-08-27`）
- **无 `candidate_id` 的记录**（如 `run_marker`）：以 `record_type` 为去重键
- **保留规则**：最后写入的版本胜出（latest wins），因为最新快照有最新价格和状态
- **in-place 覆写**：读入全部已有记录 → 合并去重 → 覆写整个文件。对于 <100KB 的日文件安全且快速

## 共享工具

`~/.hermes/scripts/utils_candidate.py` 提供两个函数：

```python
def dedup_append(path: str, record: dict) -> None:
    """追加单条记录，自动去重。用 candidate_id 去重，fallback 到 record_type。"""

def dedup_append_many(path: str, records: list) -> None:
    """批量追加记录，自动去重。"""
```

使用方式：
```python
from utils_candidate import dedup_append, dedup_append_many

# 单条
dedup_append(str(ledger_path), candidate)

# 批量
dedup_append_many(str(ledger_path), [cand1, cand2])
```

## 写入候选 JSONL 的脚本清单（10 个）

| 脚本 | 写入方式 | 运行频率 |
|------|----------|----------|
| `build_limitup_watchlist.py` | `dedup_append_many` | 每日盘后 |
| `intraday_scan.py` | `dedup_append` | 盘中 10:00/13:30 |
| `close_session_scan.py` | `dedup_append` | 14:15 尾盘 |
| `review_open_watchlist.py` | `dedup_append_many` | 盘前 09:35 |
| `candidate_snapshot.py` | `dedup_append_many` | 触发式 |
| `intraday_leader_monitor.py` | `dedup_append` (x2) | 每 5 分钟 |
| `limitup_pipeline.py` | `dedup_append_many` | 涨停处理后 |
| `autonomous_trade_pipeline.py` | `dedup_append` (via append_jsonl) | 交易闸门 |
| `run_autonomous_trades.py` | 继承 `append_jsonl` → 自动去重 | 交易执行 |
| `cron_close_review.py` | `dedup_append` | 收盘复盘 |

## 批量去重（修复已有文件）

`~/.hermes/scripts/dedup_candidates.py` 可对全部历史 `candidates_*.jsonl` 做批量去重：

```bash
python3 ~/.hermes/scripts/dedup_candidates.py
```

## 重要限制

- **无并发写保护**：工具假设同一文件不会被并发写入（cron 串行执行保证安全）
- **in-place 覆写非原子**：写入中断可能导致数据丢失。可通过写入临时文件 + rename 改进
- **大文件风险**：单日文件通常 <100KB/ <100 行，in-memory 去重安全。如果候选量显著增长，应考虑 SQLite 或分片方案
