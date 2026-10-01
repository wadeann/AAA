# Cron Watchdog 执行细节

2026-08-05 盘中 watchdog 实际运行验证的记录。

## 当前 7 个交易轮次

| job_id | 名称 | UTC 目标 | 用途 |
|--------|------|----------|------|
| da4d9fc60390 | 盘前扫描 | 01:25 | 盘前选股 |
| bdd5437b4b7c | 开盘狙击 | 01:35 | 开盘竞价 |
| 907b2ca9dcdf | 盘中检查-上午 | 02:00 | 午前评估 |
| 2b7a05c518c0 | 盘中检查-午后开盘 | 05:30 | 午后开盘 |
| 7f5916e3340f | 盘中检查-尾盘 | 06:15 | 尾盘评估（14:15 BJT） |
| b90d3891ac50 | 收盘复盘 | 07:10 | 收盘总结 |
| 770b03427acb | 板块资金流向 | 07:30 | 盘后板块资金记录 |

## Watchdog 判定逻辑

```
1. 读取 cron/jobs.json 获取所有 job 的 last_run_at 和 next_run_at
2. date -u 获取当前 UTC 时间
3. 对每个交易轮次 job：
   - last_run_at 的日期（UTC 日期）== 今天 → 已跑，跳过
   - last_run_at 的日期 < 今天 AND 当前 UTC 时间 >= 预定 UTC 时间 → 漏发，hermes cron run <job_id>
   - 当前 UTC 时间 < 预定 UTC 时间 → 未到时间，跳过
4. 排除：周度自选（周五跑，不需要 watchdog）、watchdog 自身
5. 全部正常 → 输出 [SILENT] 抑制投递
6. 有补跑 → 输出 "⚠️ watchdog补跑: 名称1/名称2"
```

## 实际执行方式

Watchdog cron job 自身（`adb6b995352b`）每15分钟运行一次，作为 agent 模式 cron job，
直接读 `/home/ubuntu/.hermes/cron/jobs.json` 判定，而非通过 `hermes cron list` CLI 命令。

## Gateway 串行执行（重要发现）

**实测**（2026-08-05 01:31 UTC）：watchdog 发现开盘狙击漏发，调用 `hermes cron run bdd5437b4b7c`。命令成功返回 "Triggered job"，但检查 `hermes cron list` 发现 next_run 变为触发时间（01:31:32），state=scheduled，last_run 未更新。

**根因**：gateway 一次只处理一个 cron job。watchdog 自身（adb6b995352b）占用 gateway 期间，任何 `hermes cron run` 触发的 job 都会排队。wait 了 4 分钟仍未执行——因为 watchdog 的 API 调用轮次很多。

**结论**：这是正常行为。watchdog 不需要反复重试同一个补跑。gateway 完成后自然会轮到排队 job。

## 命令清单

```bash
# 列出所有 cron job（含 last_run_at）
hermes cron list

# 查看调度器状态（PID、活跃数、next run）
hermes cron status

# 强制执行到期 jobs
hermes cron tick

# 手动补跑（设置 next_run 为当前时间，排队等待 gateway tick）
hermes cron run <job_id>

# 查看 jobs.json 原始状态
python3 -c "
import json
d = json.load(open('/home/ubuntu/.hermes/cron/jobs.json'))
for j in d['jobs']:
    print(j['id'][:12], j['state'], j['last_run_at'])
"
```

## 常见错误

- `hermes cronjob list` → 错误（正确是 `hermes cron list`）
- `hermes cron logs` → 不存在（cron 子命令只有 list/create/add/edit/pause/resume/run/remove/rm/delete/status/tick）
- `.tick.lock` 文件（`~/.hermes/cron/.tick.lock`）存在表明 gateway 正在处理 tick

## 2026-08-10 实战：调度器连续漏跑 2 个轮次

**发现**：盘中的 **尾盘14:15**（06:15 UTC, job_id `7f5916e3340f`）和 **收盘复盘+明日预案**（07:10 UTC, job_id `b90d3891ac50`）均未按时触发。
- 尾盘14:15 的 `last_run_at` 停在 2026-08-07（周五），`next_run_at` = 2026-08-10T06:15:00+00:00，当 time=07:28 UTC 时已超时 73 分钟
- 收盘复盘的 `last_run_at` 停在 2026-08-07，`next_run_at` = 2026-08-10T07:10:00+00:00，当 time=07:28 UTC 时已超时 18 分钟
- **板块资金流向**（07:30 UTC, job_id `770b03427acb`）当时还未到触发时间，因此未预判

**修复**：`hermes cron run <job_id>` 两发均成功，next_run 更新为触发时间（排队中）

**教训**：
1. **尾盘14:15 是最容易漏的轮次** — 午后开盘（05:30 UTC）到尾盘（06:15 UTC）之间可能调度器处于低负载且上一轮刚跑完，窗口较窄
2. **连续漏跑模式**：今天 2 个轮次连续漏跑，不是孤立事件。建议 watchog 自身（`adb6b995352b`）的调度间隔从 `*/15` 缩短到 `*/10`
3. **检测方法**：`hermes cron list` 输出中对比 `last_run_at` 日期和 `next_run_at`。如果 next_run 是今天且已经过了当前时间，但 last_run 是昨天或更早 → 漏跑
4. **UTC 时间 vs 北京时间**：所有 `last_run_at`/`next_run_at` 在 jobs.json 中已是 UTC。检查时直接用 `date -u` 对比，不需要换算时区
5. **验证补跑是否生效**：补跑后再次 `hermes cron list` 看 `next_run` 是否跳到下一个自然周期（而非当前时间）——这才是 job 已执行的可靠信号
