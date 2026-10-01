# AGY 多报告联合审计 + 根因链条追踪模式 (2026-09-14)

## 审计标的
6份自动化推送报告的合理性与一致性：
1. 盘前预案(09:20) ❌ — 推闽东电力4板买入直接违反用户铁律
2. 盘中天梯10:15 ❌ — 国芳7板/桂林5板消失，推三环集团126元机构票
3. 盘中天梯14:15 ❌ — 同上，世运电路/上海电力等大盘中军
4. 涨停归档15:05 ✅ — 数据准确
5. 收盘复盘15:35 ⚠️ — 盘前7.32 vs 收盘8.00止盈不一致
6. 策略进化审计15:55 ❌ — 贝叶斯平均17%死锁，候选0笔

## 修复的5个P0
| P0 | 问题 | 文件 | 修复 |
|:--:|:-----|:-----|:-----|
| 1 | iron_rule_gate无≥3板拦截 | market_regime_check.py | 新增门禁0.5: streak>=3买入熔断 |
| 2 | 天梯数据源/评分/候选过滤 | intraday_hot_sector_sniper.py | 读增强天梯+涨停家数*0.6+龙头*1.0+净流入*0.4+剔>50元股 |
| 3 | 持仓静态止盈过低 | premarket_plan_compiler.py | 浮盈>10%锁max(昨收*0.98,今高*0.95) |
| 4 | 荐股引擎硬编码streak>=3推买入 | premarket_plan_compiler.py | 改为高位观察哨, action=只卖不买, position=0% |
| 5 | 字段兼容穿透 | market_regime_check.py | 兼容streak/real_streak/board_height |

## 根因链条追踪发现（关键模式）
审计P0-1发现在iron_rule_gate增加streak>=3拦截。但复审时发现：
- 下游门禁拦截streak>=3成功率=0，不是因为候选质量好
- 原因是上游premarket_plan_compiler的select_actionable_recommendations()硬编码筛选c["streak"]>=3并推买入建议
- 门禁拦截数=0 不是好事，是上游根本没生成合规候选
- 修复必须沿生成链追到最上游源头

## 字段兼容性（关键教训）
系统中不同脚本用不同字段名表示同一概念：
- market_regime_check.py: candidate.get("streak")
- call_auction_scanner.py: candidate["real_streak"]
- leader_universe.json: "board_height"

门禁只读"streak"时，其他字段传入的streak>=3候选直接穿透。
修复方案：candidate.get("streak") or candidate.get("real_streak") or candidate.get("board_height")

## 执行模式
- AGY CLI后台跑代码生成：terminal(background, notify_on_complete) + --print-timeout 15m
- execute_code有300s硬限，代码生成需600-900s
- Hermes用patch或terminal python脚本定向替换，非无脑覆盖全文件
- 复审可能发现新的P0，持续循环直到AGY签署终结
