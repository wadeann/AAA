# Cron 可靠性调试与周一恢复

## 问题：周一开盘 cron 全部静默无飞书输出

**典型症状（从本会话 2026-08-24 例）：**

- 用户周一上午 09:47 CST 发现飞书没有任何 cron 报告
- `cronjob action=list` 显示所有 cron `enabled: true`, `state: scheduled`
- no_agent 脚本类 cron 正常运行（watchdog 01:15, candidate_snapshot 01:15, intraday-leader-monitor 01:20）— 但它们只是写文件，用户看不到飞书消息
- LLM agent 类 cron（盘前扫描 09:25, 开盘狙击 09:35, 盘中10:00）`last_run_at` 仍为上周末（08-21），`next_run_at` 被 fast-forward 到 08-25
- 被手动 `cronjob action=run` 触发后，`next_run_at` 重置为当前时间但不执行 — 在 LLM 推理队列中排队

## 根因分析

**调度器在周末完全停止工作。** 周一凌晨恢复时：

1. Gateway ticker 醒来，发现所有 job 的 `next_run_at` 已过期超过 grace 窗口 → 全部 fast-forward 到次日
2. 但部分 no_agent 脚本 job（如 watchdog）的 cron 表达式是 `*/15 1-7 * * 1-5` — 周一 01:00 UTC 进入窗口后又产生了新的 next_run_at → 这些成功触发
3. LLM agent cron 的 next_run_at 已经被 fast-forward 到 08-25 → 周一整天都不会再触发

**关键差异**：`*/N` 型 cron 表达式会在窗口内不断重新产生 next_run_at，即使之前被 fast-forward 也能在下一分钟重新进入窗口。但固定时间 cron（如 `25 1 * * 1-5`）一旦被 fast-forward 就彻底错过当天。

## 检测法（周一开盘后 2 分钟内完成）

```bash
# 1. 确认现在是北京时间的交易时段
TZ='Asia/Shanghai' date

# 2. 检查今日应有的 cron 是否跑了
cronjob action=list  # 人工对比上表

# 3. 快速检测：只查 last_run_at < 今日 UTC 00:00 的 enabled cron
# 高优先级 — 这些是盘前窗口的 LLM cron
# da4d9fc60390 (盘前扫描 09:25)  |  bdd5437b4b7c (开盘狙击 09:40)  |  907b2ca9dcdf (盘中-上午10:00)
```

## 恢复步骤（按优先级）

### Step 1：确认 MCP 服务和数据源正常

```python
# 四指数行情
mcp_intel_query_data("000001.SH")  # 上证
mcp_intel_query_data("399001.SZ")  # 深证
mcp_intel_query_data("399006.SZ")  # 创业板
mcp_intel_query_data("000688.SH")  # 科创50
mcp_intel_trading_sessions()       # 确认交易日+时段
mcp_exec_get_positions()           # 持仓
mcp_risk_daily_pnl()               # 盈亏
```

### Step 2：手动补跑漏掉的 LLM cron

```python
cronjob(action="run", job_id="da4d9fc60390")  # 盘前扫描
cronjob(action="run", job_id="bdd5437b4b7c")  # 开盘狙击
cronjob(action="run", job_id="907b2ca9dcdf")  # 盘中-上午10:00
```

**⚠️ 注意**：手动提交的 LLM cron 排队等待推理，可能需要 2-5 分钟。不应干等 — 同时在对话中直接执行盘前扫描流程（拉实时数据→输出飞书格式）。

### Step 3：不要依赖排队的 cron — 手动输出

即使手动触发后 cron 在排队，主 agent 也应该直接：
1. 拉四指数+MCP 持仓+实时行情+盈亏
2. 按 `cron-feishu-format` 规范输出飞书消息
3. 在对话中直接发送给用户

**理由**：等待可能 2-5 分钟，用户已经不耐烦了。直接干。

### Step 4：验证 cron 恢复后当天后续窗口

手动补跑后，检查 `cronjob action=list`：
- 后续窗口（尾盘14:15, 收盘复盘15:10等）的 `next_run_at` 是否回到今天的正确时间
- 如果仍然被 fast-forward 到明天 → 逐个 `cronjob action=run` 手动触发

## 预防 — 系统 crontab 心跳

见 `trading-infra-troubleshooting` skill §28。系统级 `cron_heartbeat.py` 脚本每分钟 tick 一次，独立于 gateway 进程，防止调度器在周末/重启后静默。

## 为什么 watchdog 没抓到这次漏发

Watchdog 脚本 (`trading_watchdog.py`) 在 01:15 UTC 和 01:30 UTC 跑了，但：
1. 盘前扫描应该在 01:25 UTC（09:25 CST）— watchdog 01:15 跑时还没过期，01:30 跑时应该发现已过期
2. 但 watchdog 可能只看 `last_run_at` 是否早于今天 → 如果 fast-forward 后 `next_run_at` 已经更新到明天，watchdog 不会把"没跑今早"当成"漏跑" — 它认为 job 的下次就是明天

**watchdog 的漏跑检测逻辑需要增强**（见下方 patch）。
