# AGY 审计修复：cron 脚本时序故障排查实战记录

**日期**：2026-09-07
**来源**：用户要求 AGY 审计"build_ladder.py + morning_master_orchestrator.py"的修改
**AGY 模型**：Claude Sonnet 4.6 (Thinking) via AGY CLI

## 审计发现摘要

AGY 发现**3个致命问题**（不通过），全部修复后重新上线：

### 🔴 问题1：Phase 1 `(target - now)` 冻结时间 BUG

**症状**：main() 开头捕获 `now` 时间，经过 Phase 0/0.5/0.8 约 15s 后，Phase 1 的等待计算仍用冻结的 `now`，永远 sleep 15s。

**原始代码**：
```python
# morning_master_orchestrator.py
now = dt.datetime.now(...)  # 启动时 09:24:50
# ... 经过 15s 实际已到 09:25:05 ...
target = now.replace(hour=9, minute=25, second=5)
sleep_sec = (target - now).total_seconds()  # 永远 15s！实际已不需要等待
```

**修复**：
```python
def now_cst() -> dt.datetime:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))

# Phase 1:
target = now_cst().replace(hour=9, minute=25, second=5)
sleep_sec = (target - now_cst()).total_seconds()  # 实时判断，若已过时直接跳过
```

### 🔴 问题2：retry 退避策略不合理

**症状**：恒定 8s timeout + 5s/10s wait（总 39s 击穿父级 30s 超时），且不捕获 JSON-RPC error

**修复（build_ladder.py mcp_call 函数）**：
- 递增 timeout：8s → 12s → 16s
- 缩短退避：1s, 2s（instead of 5s, 10s）
- 增加 `if "error" in resp: raise RuntimeError(...)`

### 🔴 问题3：cron 300s 超时 < 实际生命周期 425s

**症状**：09:24:50 启动 → 09:31:55 结束 ≈ 425s，cron 默认 `script_timeout_seconds: 300` 在 ~09:29:50 时 SIGKILL

**修复**：`config.yaml` → `script_timeout_seconds: 480`

## 时间线估算

```
09:24:50 启动
Phase0~0.8 (~13s) → 09:25:03
Phase1 (等~2s + 30s) → 09:25:35
Phase2 (sleep 5s + 30s) → 09:26:10
Phase3 (等 225s + 120s) → 09:31:55
总耗时 ~425s ✅ < 480s
```

## 心得

1. 所有 `time.sleep()` 等待明确定时器的脚本，必须使用**实时时间**（每次 re-read `datetime.now()`），不能用 main() 开头的冻结变量
2. Retry 策略必须与**调用链中所有父级超时**做预算约束（本地 MCP 没有网络抖动，短 timeout + 快重试比长 timeout 好）
3. `no_agent=True` 脚本被 cron 调度器 SIGKILL 时，脚本内部的 `try/except` 无法捕获，只能增大 `script_timeout_seconds`
4. AGY 审计比自审发现更多问题：本来自以为改好了（加了 elapsed/timeout），AGY 挖出 3 个意料之外的问题
