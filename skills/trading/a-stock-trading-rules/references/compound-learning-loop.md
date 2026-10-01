# 沉淀闭环 (Compound / Learning Loop)

CE 方法论「沉淀闭环」的具体实现。每次交易后记录结构化教训，下次 brainstorm/plan/research 自动加载。

## 目录

```
~/.hermes/trading/learnings/
├── TEMPLATE.md            # 教训模板（YAML frontmatter + 正文）
└── YYYY-MM-DD_{symbol}_{type}.md  # 实际教训文件
```

## 使用模板

复制 TEMPLATE.md 并填写 frontmatter：
```yaml
---
module: trading
tags: [止损, 趋势, 板块共振]
problem_type: [execution, judgment]  # execution/judgment/system/data
date: "2026-08-03"
trade_id: "intent_xxx"
symbol: "603738"
cost_impact: -2520
root_cause: "卖出前未拉K线确认趋势"
fix_applied: "已更新卖出前K线检查铁律"
should_repeat: false
---
```

## 索引查询

```bash
# 最近7天教训
python3 ~/.hermes/trading/scripts/compound_learnings.py --recent 7

# 按问题类型
python3 ~/.hermes/trading/scripts/compound_learnings.py --problem execution

# 按标签
python3 ~/.hermes/trading/scripts/compound_learnings.py --tags 止损,趋势

# 统计总览
python3 ~/.hermes/trading/scripts/compound_learnings.py --stats

# 关键词搜索正文
python3 ~/.hermes/trading/scripts/compound_learnings.py --search 半导体
```

## 与 reviews/ 的分工

- `learnings/`：结构化教训，YAML frontmatter，可机器索引。每次错误/失误产生一个文件。
- `reviews/`：每日复盘报告，自然语言，面向飞书输出和人工阅读。
- 两者互补：reviews 是对外的叙事，learnings 是对内的结构化数据。

## Cron 集成

收盘复盘 cron (`b90d3891ac50`) 的 Step 4 自动执行教训归档。
盘前扫描 cron (`da4d9fc60390`) 的 Step 0 自动读取近期教训作为上下文。
