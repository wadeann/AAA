# 盘中评估技能从嵌入式到独立的教训 (2026-06-29)

## 问题

`a-stock-intraday-eval` 此前是 `a-stock-trading-orchestrator` skill 中的一个嵌入流程模块。当 cron job 在 `skills` 列表中引用 `a-stock-intraday-eval` 时，调度器试图加载独立的 skill 文件但找不到，导致加载跳过。

**症状**：
- Cron job 提示：`[IMPORTANT: The following skill(s) were listed for this job but could not be found and were skipped: a-stock-intraday-eval]`
- 输出文件显示该 skill 的详细流程内容被替换成了 `a-stock-trading-rules` 的内容
- 任务输出从预期的 6 维度分析退化为通用规则复述

## 修复

1. 将 `a-stock-intraday-eval` 提取为独立的 skill 文件（`~/.hermes/skills/a-stock-intraday-eval/SKILL.md`）
2. 将全局规则引用改为 `a-stock-trading-rules`（而不是同时引用两个 skill）

## 配置示例（正确）

```
cronjob skills: [a-stock-trading-rules, a-stock-intraday-eval]
```

## 影响

- 所有引用 `a-stock-intraday-eval` 的 cron job 需要重新验证输出格式（因为流程执行可能不同）
- 潜在影响：盘中检查-上午（02:00 UTC，10:00 CST）的历史输出前后不一致（6/26 以前的输出加载了嵌入模块，6/29 以后加载独立模块后格式应该更完整）
- 建议：下次 manual run 盘中检查-上午后人工核对输出格式一致性
