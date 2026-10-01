# Cron 系统级兜底心跳 — 完整设置指南

## 为什么需要

Gateway 内置的 cron ticker（`gateway/run.py:_start_cron_ticker`）是 gateway 进程内的后台线程。当 gateway 因任何原因重启（SIGTERM、崩溃、OOM），cron ticker 也随之停止。重启后 ticker 恢复，但在此期间的 job 已过 grace 窗口（daily job: 7200s），全被 fast-forward 到次日。

**系统 crontab 是唯一独立于 gateway 进程外的心跳源。**

## 部署步骤

### 1. 确保 venv 有 croniter

```bash
/home/ubuntu/.hermes/hermes-agent/venv/bin/python3 -m ensurepip --upgrade
/home/ubuntu/.hermes/hermes-agent/venv/bin/python3 -m pip install croniter
```

验证：
```bash
/home/ubuntu/.hermes/hermes-agent/venv/bin/python3 -c "from croniter import croniter; print('OK')"
```

### 2. 创建心跳脚本

文件路径：`~/.hermes/cron/cron_heartbeat.py`

```python
#!/home/ubuntu/.hermes/hermes-agent/venv/bin/python3
"""
Minimal cron heartbeat — called by system crontab every minute.
Triggers hermes cron scheduler tick, catching any errors gracefully.
"""
import os, sys, logging

os.environ.setdefault("HERMES_HOME", os.path.expanduser("~/.hermes"))

logging.basicConfig(
    filename=os.path.expanduser("~/.hermes/logs/cron-fallback.log"),
    level=logging.INFO,
    format="%(asctime)s %(message)s",
)
logger = logging.getLogger("cron-heartbeat")

try:
    sys.path.insert(0, os.path.expanduser("~/.hermes/hermes-agent"))
    from cron.scheduler import tick
    count = tick(verbose=False)
    if count > 0:
        logger.info("Tick OK: %d job(s) executed", count)
except Exception as e:
    logger.warning("Heartbeat tick failed: %s", e)
```

```bash
chmod +x ~/.hermes/cron/cron_heartbeat.py
```

### 3. 加入系统 crontab

```bash
(crontab -l 2>/dev/null | grep -v "cron_heartbeat"; \
 echo "* * * * * /home/ubuntu/.hermes/cron/cron_heartbeat.py 2>&1") | crontab -
```

### 4. 验证

```bash
# 确认 crontab 已添加
crontab -l | grep heartbeat

# 确认 cron 服务在运行
systemctl status cron

# 等一分钟，检查心跳日志
tail -f ~/.hermes/logs/cron-fallback.log
```

预期输出（正常）：无输出或 `Tick OK: N job(s) executed`

## 注意事项

- **不要用 `hermes cron tick` CLI 命令代替** — 该命令在遇到非法 cron 表达式时会直接崩溃退出（没有外层 try/except），crontab 会收到非零 exit code
- **不要用系统 python3** — 必须用 venv python，因为 croniter 装在 venv 中
- **日志位置**: `~/.hermes/logs/cron-fallback.log`，与 gateway/agent 日志分开，便于排查
- **与 gateway 内置 ticker 共存**：两者通过文件锁（`.tick.lock`）互斥，不会重复执行同一 job
- **静默日志**: 正常 tick 无 job due 时不输出（`verbose=False`），只有有 job 执行或异常时才写日志

## 故障排查

### 心跳日志显示 `croniter not installed`
→ venv 中未装 croniter，执行步骤 1

### 心跳日志显示 `Exactly 5, 6 or 7 columns`
→ 某个 job 使用了不被 croniter 支持的多段/范围步进表达式（见 SKILL.md §29）
→ 心跳脚本本身的 try/except 会 catch 此错误，但该 tick 内未处理的 job 不会被推进
→ 临时无影响（gateway 内置 ticker 也会遇到同样问题），根治需拆 multipart cron

### 心跳日志完全为空
→ 检查 cron 服务是否运行: `systemctl status cron`
→ 检查 crontab: `crontab -l`
→ 检查磁盘: `df -h /home/ubuntu/.hermes/logs/`
