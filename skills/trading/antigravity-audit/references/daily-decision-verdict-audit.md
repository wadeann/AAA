⚠️ 本文件是 antigravity-audit 技能的子参考，主技能文档位于 SKILL.md。

# 逐日盘后决策裁决审计模式

## 适用场景
用户或系统自动触发：要求AGY独立审计当日系统交易决策的正确性。
典型触发："让agy审核今日XX是对的/错的吗"、"AGY审计今日操作"、"verify today's call"

## 与代码审计的区别
| 维度 | 代码审计 | 决策裁决审计 |
|------|---------|-------------|
| 对象 | 代码逻辑、Bug、策略参数 | 当日系统输出的交易判断 |
| 输入 | 文件路径+代码片段 | 多源系统输出快照（盘前预案、天梯、扫描器、收盘复盘） |
| 审计标准 | 代码正确性、数学一致性 | 规则遵守度、市场条件匹配度、资本保全合理性 |
| 输出形式 | P0/P1修复清单 | Judgment + Reasoning + Score + Missed Opportunities |

## 证据收集清单
审计前必须收集以下系统证据：
1. 盘前实战打法卡 → cron/output/premarket-plan-playbook/YYYY-MM-DD*.md
2. 盘中连板天梯 → cron/output/intraday-hot-sector-sniper/YYYY-MM-DD*.md
3. 通达信回踩起爆扫描器 → cron/output/tdx-pullback-sniper/YYYY-MM-DD*.md
4. 收盘复盘 → cron/output/agy-close-review/YYYY-MM-DD*.md
5. 系统底座体检 → python3 scripts/system_health_check.py
6. 当日候选/成交日志 → trading/trade_log.jsonl + trading/intents/
7. 状态机/策略参数 → trading/strategy_params.json

## AGY Prompt模板
```
You are an independent audit agent. Verify whether the trading system's 
decision on [DATE] was CORRECT.

## System Evidence
- System health: [GREEN/YELLOW/RED]
- Market status state machine: [state]
- Positions: N
- Market stats: limit-ups:N, broken-seals:N, rate:N%
- Space dragon: [ticker N板 (sector, tier support)]
- Ladder: [breakdown]

## Morning Plan [key items]

## Scanning Results [key findings]

## Close Review [key verdict]

## Rules Applied [1. ... 2. ...]

Output:
## Judgment: [CORRECT/INCORRECT/PARTIALLY]
## Reasoning: (max 5 bullets)
## Missed Opportunities: (ticker + brief, or None)
## Score: X/100
## Improvement Suggestions:
```

## 评分标准
- 90-100: 完全正确，规则执行无偏差
- 70-89: 基本正确，少量边缘机会遗漏
- 50-69: 部分正确，存在可商榷判断
- <50: 决策错误

## 常见审计结论模式
1. Correct(退潮空仓) — 高炸板率+空间龙孤立+放量滞涨，系统规则全覆盖
2. Correct but lazy(正确但僵化) — 规则正确但过于保守，应增加低仓位逆周期首板选项
3. Incorrect — 存在真实低风险机会但被规则误杀，需调整门禁/豁免
