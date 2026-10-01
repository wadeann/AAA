# R34-R38 全栈实现参考 — 2026-09-02

## 背景
AGY分析了策略体系差距后超时（600秒不够），改为手动实现全部P0+P1任务。

## P0三修（已验证通过，已git push）

### P0-1: 删除is_strong_leader特权后门
文件: `scripts/direct_executor.py`
Before: 有is_strong_leader检测confidence≥0.75/catalyst_type/龙头关键词→绕过情绪系数直接给20%~35%仓位
After: 全部删除——cooldown时所有候选强制`base_pct * sent_multiplier`，卖单走`base_pct`

### P0-2: cooldown阶段买方向阻断
文件: `scripts/autonomous_trade_pipeline.py` (is_trade_ready)
Before: cooldown只拦截"非强力标的"，龙头/竞价/弱转强特权放行
After: cooldown+multiplier≤0.3时所有buy候选直接return False

### P0-3: 卖单缠论门禁剥离
Before: 卖方向必须chan_sell_point+chan_confirmed，非缠论止盈单被拦截
After: 卖出方向完全剥离缠论校验，止盈止损秒级放行

### P0-4: 仓位上限is_super_leader特权拔除
Before: is_super_leader检测→超过5只持仓上限仍通融放行
After: 持仓上限硬约束，5只满了就拒，不区分龙头杂毛

## 文件清单

| 轮次 | 文件 | 类型 | 功能 |
|------|------|------|------|
| R34 | build_limitup_watchlist.py | 已有 | generate_ladder_tree()+废除假数据容灾 |
| R35 | premarket_plan_compiler.py | 新建 | 板块分级→四层嵌套预案 |
| R36 | condition_evaluator.py | 新建 | 竞价区间/封板时效/追高阈值 |
| R36 | direct_executor.py | 修改 | 调用condition_evaluator前置核验 |
| R37 | sentiment_redline_monitor.py | 新建 | 空间龙断板→sell_only_mode+撤单 |
| R38 | sector_action_matrix.py | 新建 | 主攻50%/次攻30%/只卖0%+配额校验 |

## 部署cron
红线监控: */1 9-14 * * 1-5, job_id: cef6f35a93a9
所有文件路径: /home/ubuntu/.hermes/scripts/
配置文件: trading/config/strategy_params.json (新增sell_only_mode/redline_state/global_guards)
