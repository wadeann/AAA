# Cron Job Skill 加载污染：症状、诊断与修复

## 问题概述（2026-08-05 发现）

Cron job 的 prompt 或子 agent 返回结果中如果包含类似 `[IMPORTANT: The user has invoked the "a-stock-trading-rules" skill...]` 的文本，cron 调度器会将其识别为 skill 加载指令，自动将对应 skill 的 SKILL.md 全部内容注入子 agent 的 system prompt。

## 症状

- cron `last_status: ok`，但输出为空或只有 skill 内容摘要
- 飞书未收到任何有效报告
- 执行时间异常长（被 skill 文件阅读占满）
- 关联日志中有大量 SKILL.md 内容

## 根因链

1. Agent 在之前的会话中使用了 skill（如 a-stock-trading-rules），系统自动在 prompt 中注入了 skill 引用
2. 该 prompt 被 cron 调度器保存为 cron job 的 prompt
3. Cron 调度器检测到 prompt 中的 `"a-stock-trading-rules"` → 触发 skill 自动加载
4. SKILL.md（1096+行）被注入 agent 上下文
5. Agent 用完整窗口读取规则，不执行实际数据采集

## 诊断

```bash
# 查看 cron job 的 prompt 内容
python3 -c "
import json
with open('/home/ubuntu/.hermes/cron/jobs.json') as f:
    jobs = json.load(f)
for j in jobs['jobs']:
    if 'IMPORTANT' in j.get('prompt','') or 'skill' in j.get('prompt',''):
        print(f'CONTAMINATED: {j[\"name\"]} ({j[\"id\"]})')
        print(f'  prompt[:200]={j[\"prompt\"][:200]}')
"
```

## 修复

### 修复 A：使用 no_agent=True 脚本模式（推荐）

创建新 cron job，用 Python 脚本通过 HTTP 直连 MCP：

```bash
hermes cron create "10 7 * * 1-5" --prompt "收盘采集" --script close_review.py --no-agent
```

脚本参考：`a-stock-trading-orchestrator SKILL.md §3`

### 修复 B：清理旧 cron 的 prompt（不推荐，仍有 LLM 调用开销）

删除旧 job + 重新创建（清理被 skill 污染的 prompt）：

```bash
hermes cron list | grep 目标job名
hermes cron remove <old_job_id>
hermes cron create "schedule" --prompt "干净的 prompt（不含任何 skill 引用）"
```

## 历史教训

2026年8月5日：收盘复盘 cron（`0cb9f149cd44`）连续多天输出为空，飞书收不到报告。诊断为 prompt 中 skill 引用导致 agent 被规则内容淹没。修复方案：改用 no_agent=True + 脚本模式。
