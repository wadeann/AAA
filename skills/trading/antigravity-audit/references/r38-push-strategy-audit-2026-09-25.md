# R38 AGY Audit: 盘中推送策略修改合理性审计 (2026-09-25)

## Context
用户反馈昨日(2026-09-24)盘中推送消息"没有明确的买卖指示"——所有推送都是"非买入"/"无信号"/"空仓防守"等无具体标的、无触发条件、无价格的消息。

## AGY 裁决
- **Judgment**: 不合理（Score 70/100）
- 交易方向上的退潮空仓防守与开盘决断透明化正确，但将动态防守劣化为静态硬编码锁死（破坏了自适应机制），且将盘中未触发状态滥发为推送噪音。

## 5个原子问题评分
| Q | 问题 | 评级 |
|---|------|------|
| Q1 | sell_only_mode 硬编码 + cooldown 到10月1日 | ⚠️部分合理 |
| Q2 | zero_candidate→send_non_buy_notice | ✅合理 |
| Q3 | intraday_theme_trigger non-triggered 推送 | ❌不合理 |
| Q4 | auction_ladder_rows 昨日天梯+实时竞价 | ✅合理 |
| Q5 | 零买入+防守+告知 vs 沉默 | ✅进步 |

## 3条 Recommendation 落地情况
1. ✅ 回滚 intraday_theme_trigger.py non-triggered 推送 → 恢复"只在 triggered 时才推送飞书"
2. ✅ 删除 strategy_params.json 冗余 sell_only_mode 和 tighten_stops → global_guards.sell_only_mode=false。废除硬编码 cooldown: 2026-10-01 → 恢复 2026-09-26
3. ✅ morning_master_orchestrator.py 新增 Phase 0.75 市场状态机刷新 → 修复缓存陈旧阻断

## 发现的新 Pitfalls
- **Pitfall 22**: 静态配置覆写状态机 — strategy_params 中 sell_only_mode 硬编码 true 绕过了 market_regime 动态升降级
- **Pitfall 23**: 市场状态缓存陈旧 — market_regime 收盘后到次日09:25 >14h 无刷新导致 data_fresh=false 阻断全部开仓

## 修复前/修复后对比
### Before (strategy_params.json)
- `sell_only_mode: true` 出现在顶层和 global_guards 两处
- `tighten_stops: false` 出现在顶层和 global_guards 两处（冗余）
- 7个策略 cooldown_until 统一为 "2026-10-01"（批量硬编码）
### After
- 顶层无 sell_only_mode/tighten_stops
- global_guards.sell_only_mode = false（交还状态机）
- 7个策略 cooldown_until 恢复为 "2026-09-26"（原进化引擎日期）

### Before (intraday_theme_trigger.py)
- non-triggered 也推送 "非买入：XX共振不足" 到飞书
### After
- 只在 res.get("triggered") 时才推送，盘中静默

### Before (morning_master_orchestrator.py)
- 无 market_regime 刷新 → 09:30 direct_executor 因 data_fresh=false 阻断
### After
- Phase 0.75 在市场扫描前刷新 market_regime，确保 data_fresh=true

## AGY CLI 调用记录
- 进程ID: proc_dffd925c0120
- Prompt: 3147 chars，内嵌 git diff + 5原子问题
- Timeout: 3m，实际返回 ~2m
- 命令: `cat prompt.txt | agy -p "$(cat)" --dangerously-skip-permissions --print-timeout 3m`
