---
# 交易教训归档模板
# 消费者: 下次 brainstorm/plan/research 时由模型或脚本读取
# 目录: ~/.hermes/trading/learnings/{date}_{symbol}_{type}.md
---
module: trading
tags: []
problem_type: []  # 分类: execution(执行)/judgment(判断)/system(系统)/data(数据)
date: ""         # YYYY-MM-DD
trade_id: ""     # intent_id 或空
symbol: ""       # 股票代码
cost_impact: 0   # 估计损失/错失收益(元)
root_cause: ""   # 根因分析（一句话）
fix_applied: ""  # 已实施的修复
should_repeat: false  # 是否应该在下次同类场景中重复此教训

## 发生了什么

<!-- 3-5 句话描述事件经过 -->

## 错在哪里

<!-- 违反了什么规则？为什么会犯错？ -->

## 如果重来

<!-- 当时应该做什么？决策树如何分叉？ -->

## 对系统的影响

<!-- 这个教训影响了哪个 skill 的哪条规则？是否需要更新？ -->
