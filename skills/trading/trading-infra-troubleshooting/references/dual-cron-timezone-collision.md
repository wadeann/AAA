# 双调度系统冲突：传统 crontab + Hermes cron 时区碰撞

**日期**：2026-09-15
**来源**：用户问"为什么晚上9点会有午后预警"

## 症状

用户在 **CST 21:00（晚上9点）** 收到"午后预警"类飞书推送（如题材扫描、盘中起爆点检查），这些消息本应在交易时段（CST 09:00-15:00）推送。

## 根因分析

两个独立调度系统在**同时运行同一批脚本**，且时区基准不同：

| 系统 | 时区 | 调度方式 | 来源 |
|------|------|---------|------|
| **Hermes cron** | CST（Asia/Shanghai） | `cronjob action=create` 创建的 job | Hermes gateway 内部调度器 |
| **传统 crontab** | **UTC**（系统时区） | `crontab -e` / `crontab -l` | systemd cron daemon |

**传统 crontab 的时间偏移**：系统时区是 `Etc/UTC`，但传统 crontab 中所有定时的小时字段是按 **CST 意图** 编写的（注释写 `08:30`、`09:25`、`13:00` 等）。实际运行时间 = crontab 小时字段作为 UTC → CST +8h：

```
crontab写 CST意图         实际按UTC解析→CST运行
30 8  (盘前扫描 08:30)     UTC 08:30 → CST 16:30 (下午4点半)
25 9  (竞价确认 09:25)     UTC 09:25 → CST 17:25 (下午5点半)
0 13  (午间驱动 13:00)     UTC 13:00 → CST 21:00 🔥 晚上9点！
*/5 13 (午后监控 13:00)    UTC 13:00-13:55 → CST 21:00-21:55 🔥 晚上9点！
```

## 诊断方法

```bash
# 1. 检查系统时区
timedatectl | head -5
# Local time: Tue 2026-09-15 13:06:13 UTC  ← 系统是 UTC！
# Time zone: Etc/UTC (UTC, +0000)

# 2. 对比 CST 与 UTC
date                          # UTC 时间
TZ='Asia/Shanghai' date       # CST 时间

# 3. 列出传统 crontab
crontab -l

# 4. 列出 Hermes cron
cronjob action=list

# 5. 检查 crontab 日志确认实际运行时间
tail /tmp/theme_arbitrage_scanner.log | head -2
# 👑【隔日题材套利雷达 | 盘前预判 (08:30-09:15) | 16:30】 ← 盘前预判跑在16:30！
```

## 统一方案

**方案 A（推荐）**：禁用传统 crontab 中所有被 Hermes cron 覆盖的旧定时，只保留必需的系统行：

- **保留**：`cron_heartbeat.py`（Hermes gateway 核心心跳）
- **保留**：`direct_executor.py`（盘中即时执行器，Hermes cron 中无对应）
- **删除**：所有被 Hermes cron 覆盖的旧定时（盘前扫描、竞价确认、盘中监控、午间驱动、午后监控、尾盘扫描等）

```bash
# 1. 备份
crontab -l > /home/ubuntu/.hermes/trading/crontab_backup_YYYYMMDD.txt

# 2. 写入干净 crontab
crontab - <<'EOF'
* * * * * /home/ubuntu/.hermes/cron/cron_heartbeat.py 2>&1
*/2 * * * 1-5 cd /home/ubuntu/.hermes/scripts && python3 direct_executor.py >> /tmp/direct_executor.log 2>&1
EOF

# 3. 验证
crontab -l
```

**方案 B**：给传统 crontab 的小时字段全部减 8（CST → UTC 偏移校正），不推荐——维护两套是持续的隐患。

## 验证方法

清理后检查：
1. `crontab -l` 只显示 2 行（heartbeat + direct_executor）
2. Hermes cron 的时间段覆盖检查：遍历每个旧 crontab 行，确认 Hermes cron 中有对应 job 在正确 CST 时间运行
3. 备份文件存在：`/home/ubuntu/.hermes/trading/crontab_backup_YYYYMMDD.txt`

## 关键教训

1. **系统时区是 UTC 时，传统 crontab 的时间字段全按 UTC 解析**——注释里写的 CST 时间全是错的
2. **Hermes cron 自动处理 CST 时区**，`schedule` 字段按 CST 填写即可（如 `20 1 * * 1-5` = 09:20 CST）
3. **两套调度系统同时跑同一脚本** 在 Hermes cron 体系和传统 crontab 之间不预警、不防冲突，只能手动检查和排除
4. `cron_heartbeat.py` 是 Hermes gateway 的触发器，必须保留；`direct_executor.py` 只在传统 crontab 中，Hermes cron 无覆盖，也必须保留

## 迭代修复跟踪（2026-09-15 第二期）

### 传统 crontab 最终状态（2026-09-15 R2）

```bash
# 最终：只保留 cron_heartbeat.py
crontab -l
# * * * * * /home/ubuntu/.hermes/cron/cron_heartbeat.py 2>&1
```

**direct_executor.py 也迁移了**：
- Hermes cron job id: `54b320cbb76a`（新增）
- schedule: `*/2 1-3,5-6 * * 1-5`（CST 09:30-11:30/13:00-14:50 每2分钟）
- workdir: `/home/ubuntu/.hermes/scripts`
- 脚本内部有 `in_trading_session()` 自检（UTC/CST 双保险）
- deliver: local（不推飞书，脚本自主处理推送）

### leader-monitor-pm 重新激活

Hermes job id: `09c0786f286d`，原被遗忘在 disabled 状态（最后运行 2026-09-09）。

修复：
- **从 disabled → enabled**
- 频率从 `*/5 5-6 * * 1-5`（CST 每5分钟）改为 `*/10 5-6 * * 1-5`（CST 每10分钟）
- **同频原则**：与 `fa763ca049ba` 保持一致（都是 10 分钟），减少并发冲突

**为什么改为 */10 是安全的？**
- `leader-monitor-am`（`4e5f7f6df31e`）每 5 分钟跑 `intraday_leader_monitor.py`（龙头突破扫描，不同脚本）
- `fa763ca049ba` 每 10 分钟跑 `intraday_theme_trigger.py`（题材套利起爆扫描）
- `leader-monitor-pm` 每 10 分钟跑 `intraday_leader_monitor.py`（下午龙头扫描）
- 上午 5 分钟 + 下午 10 分钟 + 题材 10 分钟 → 三个不同扫描线路，覆盖足够

### fa763ca049ba 频率从 5min → 10min 的影响判断

| 维度 | 旧 crontab | Hermes cron | 影响 |
|------|-----------|-------------|------|
| 频率 | 每 5 分钟 | 每 10 分钟 | 减半 |
| 并行覆盖 | 无 | leader-monitor-am 每 5 分钟（不同脚本） | 龙头突破仍 5 分钟 |
| 常驻守护 | 无 | intraday_proactive_trader.py 每 30 秒巡检 | 持仓防守高频覆盖 |
| 结论 | — | — | **可接受**，非同一逻辑的单一依赖 |

### 两轮修复对比

| 修复项 | R1（原文档） | R2（本次更新） | 原因 |
|--------|-------------|---------------|------|
| direct_executor.py | 保留在传统 crontab | 迁移到 Hermes cron `54b320cbb76a` | 彻底消除双轨 |
| 传统 crontab 行数 | 3 行（heartbeat + direct_executor + 注释） | 1 行（仅 heartbeat） | direct_executor 迁移后 |
| leader-monitor-pm | disabled（被遗忘） | enabled, */10 | 下午龙头监控盲区修复 |
| fa763ca049ba 频率 | 未讨论 | */10 判定安全 | 有并行覆盖证据 |

## 被清理的旧定时列表（2026-09-15 R1 实例）

| # | 意图脚本 | 意图时段 | 实际跑在 | Hermes cron job |
|---|---|---|---|---|
| 1 | theme_arbitrage_scanner premarket | 08:30 | 16:30 | `695559af50ea` (盘前雷达 09:10 CST) |
| 2 | intraday_theme_trigger auction | 09:25 | 17:25 | `1bd3b0e3b593` (竞价共振 09:25 CST) |
| 3-5 | intraday_theme_trigger intraday (上午) | 09:30-11:30 | 17:30-19:30 | `fa763ca049ba` (盘中引擎 09:30-11:30) |
| 6 | theme_arbitrage_scanner midday | 13:00 | **21:00** | `c0d0d451844f` (午间驱动 13:00 CST) |
| 7-8 | intraday_theme_trigger intraday (下午) | 13:00-14:50 | **21:00-22:50** | `fa763ca049ba` (盘中引擎 13:00-14:50) |
| 9 | intraday_theme_trigger tail | 14:00/14:15/14:30 | **22:00-22:30** | `4783ad7bfe1c` (尾盘扫描 14:00/14:15/14:30 CST) |
