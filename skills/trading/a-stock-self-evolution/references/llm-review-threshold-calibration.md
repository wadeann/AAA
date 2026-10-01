# LLM二审阈值校准与数据饥饿防饿死

## 问题背景

2026-08-28 前后发现：LLM二审过于严格，08-28 日 14 个候选买入信号有 13 个被 APPROVE/REJECT，
仅有 1 笔（688331.SH 荣昌生物）执行成交。结果导致两天的进化审计产出为空：

```json
{"outcome_samples": 0, "stats": [], "action_items": []}
```

这意味着**统计系统在饿死**——没有成交就没有 outcome_samples → 没有统计数据 → 审计无法生成
action_items → 系统不进反退。LLM二审的质量闸门运行良好（拒绝理由合理），但过于严格的
过滤阻塞了整个进化螺旋的学习通道。

## 数据饥饿的症状

1. `evolution_YYYY-MM-DD.md` 的 `outcome_samples` 连续多日为 0
2. `stats` 数组为空
3. `action_items` 为空
4. 进化审计日志没有新增改进项
5. 但 `candidates_YYYY-MM-DD.jsonl` 中有大量被 LLM二审拒绝的记录
6. `strategy-feedback.md` 中的 action_items 长期未执行（16 条仅执行 1 条）

## 数据饥饿的根本原因

| 根因 | 表现 | 优先级 |
|------|------|--------|
| LLM二审阈值过高 | 拒绝 13/14 候选，干掉了几乎所有潜在交易 | P0 |
| 统计样本积累为零 | 没有 outcome → 没有 stats → 没有 action_items | P0 |
| action-item 执行缺失 | 16 条 P0/P1 仅 1 条执行，10 天无改进落地 | P0 |
| 因果链断裂 | 审计生产 action_items → 但无消费机制保证执行 | P0 |

## 三阶段校准方案

### A. LLM二审阈值微调（短期）

当前 LLM二审拒绝了多数中枢震荡中的二买和缺乏实质催化的候选。在保持质量的前提下：

- 对 **缠论结构完整**（一买/二买/三买确认）+ **板块共振** + **基本面至少不差** 的候选，
  给予 **REDUCED** 状态（非 APPROVE 也非 REJECT）—— 允许以更小的仓位（建议仓位的 50%）
  进入执行。这样可以积累 outcome_samples 而不至于大幅增加风险。
- 对 **催化不足但缠论结构优秀** 的候选，标记 **PASS_WITH_WATCH** → 在 candidate 中添加
  `pending_catalyst` 标记，次日盘前若催化出现则自动升级为 APPROVE。
- 拒绝理由必须具体到缺失的字段（如 `volume_confirmed` 缺失、`sector_resonance` 无效），
  供审计系统追踪最常被拒的规则。

### B. 统计样本的替代收敛（中期）

即使提高通过率，也需要至少 5 个样本才能下统计结论。在样本不足时：

- 使用 **从属规则聚合**：把 catalyst_type 相近的归并统计（如所有 `main_uptrend_leader`
  无论具体形态）。
- 使用 **B 浪等级** 作为质量代理指标：即使未盈利，A 级 B 浪 = 逻辑正确。
- 强制记录每个候选的预期兑现情况：即使未执行（REJECT），也要记录 `thesis_status`：
  `valid`（逻辑正确/被拒是阈值问题）vs `invalid`（逻辑本身有误）。

### C. action-item 执行机制（长期）

`strategy-feedback.md` 目前只追加 action_items，没有消费机制保证执行。必须建立：

1. **P0 自动执行**：所有 P0 action_items 自动进入下一个交易日的策略员
   Step 0（遗留 action_items 优先处理），无需等待审计 cron 触发。
2. **P1 排队**：P1 按时间戳排队，每次最多执行 3 条新 P1。
3. **执行记录持久化**：action_item 执行后追加 `[已执行 YYYY-MM-DD]` 标记和证据。
4. **超期清理**：P0 超过 5 个交易日未执行、P1 超过 10 个交易日未执行 →
   自动升级标记或标记为已过期（默认配置项，可调）。
5. **阻塞报告**：每周生成一份 action-item 阻塞报告，列出长期未执行项及其阻塞原因。

## 验收标准

- 进化审计产出 `outcome_samples` 从 0 增加到 ≥3/周
- LLM二审拒绝率从 `13/14`（92.8%）降至 `60-70%` 的合理区间
- `strategy-feedback.md` 中新 action_items 的执行率 ≥ 50%
- 连续 3 周无执行改善 → 应自动触发```系统熔断，通知用户人工介入
```
