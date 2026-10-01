# AGY 策略体系架构审计 — 四层嵌套计划方案

## 来源
- 分析时间: 2026-09-02
- 参考标的: 别人写的9/2交易计划（reference_plan_20260902.md）
- AGY调用方式: `ask_antigravity()` via antigravity_bridge.py

## 背景：参考计划特征

别人写的9/2交易计划具有**四层嵌套**结构：

```
Layer 1: 板块分级（农业主攻 / 传媒次攻 / 高位只卖）
Layer 2: 标的具名 + 梯队身位（首板种子 vs 2板梯队 vs 7板空间龙）
Layer 3: 微观竞价条件（高开<3% / 高开2~5% / >8%不追 / 9:35前封板）
Layer 4: 情绪红线熔断（海鸥断板或万向炸板 = 此后只卖不买）
```

## AGY 审计核心发现

### 四大差距的根因

| 差距 | Root Cause | 关键代码 |
|:---|:---|:---|
| 数据源与梯队 | 盘后复盘缺乏"连板天梯图(Ladder Graph)"归档，容灾逻辑写假数据(streak全=1) | `build_limitup_watchlist.py:L132-L192` |
| 交易条件 | Candidate Schema的`entry_rule`是纯文本字符串（人类注释），执行端无法运算 | `call_auction_scanner.py`, `direct_executor.py:L213-L230` |
| 情绪红线 | `is_strong_leader`特权穿透后门让cooldown名存实亡；卖单被缠论门禁误杀 | `direct_executor.py:L201-L210`, `autonomous_trade_pipeline.py:L226-L233` |
| 板块层级 | 系统缺少"早盘战役编译(Plan Compiler)"，候选池是扁平单向池 | 缺少 `premarket_plan_compiler.py` |

### 特权穿透后门（最致命Bug）

```python
is_strong_leader = (
    candidate.get("confidence", 0) >= 0.75 or
    candidate.get("catalyst_type") in ("limit_up_ladder", "call_auction_strong", "1to2_weak_to_strong") or
    "龙头" in candidate.get("thesis", "") or "弱转强" in candidate.get("thesis", "")
)
if is_strong_leader:
    adj_pct = max(0.20, min(0.35, base_pct))  # 强制20%~35%重仓！
```

竞价候选天然 confidence≥0.75 + catalyst_type=call_auction_strong → 100%触发 → cooldown被完全覆盖 → 退潮期买入19只。

### 卖单被缠论门禁误杀

`autonomous_trade_pipeline.py:L260-L269` 要求卖出候选必须提供 `chan_sell_point` 与 `chan_confirmed`，导致主动调仓卖单被网关以 `research evidence gate incomplete` 错误拦截。

## R34-R40 进化方案

### R34: 连板天梯图全量归档
- 改 `build_limitup_watchlist.py`：主板10%/双创20%/北交所30%真实封板验证 + `generate_ladder_tree()` 识别空间龙
- 新增 `trading/data/ladder_YYYY-MM-DD.json`

### R35: 四层嵌套预案编译器
- 新建 `premarket_plan_compiler.py`：输入天梯+行业动量+宏观参数 → 输出 `strategic_layer`/`condition_triggers`/`redline_bind`
- 改 `morning_master_orchestrator.py`：09:20挂载预案编译器

### R36: 盘口微观时空条件求值器
- 新建 `condition_evaluator.py`：`evaluate_auction_condition()` + `evaluate_intraday_condition()`
- 改 `direct_executor.py`：在循环中调用条件求值器，未达标不报单

### R37: 情绪红线总线
- 新建 `sentiment_redline_monitor.py`：每10秒拉取空间标/先锋标盘口，断板秒级写入 `sell_only_mode=true`
- 改 `strategy_params.json`：新增 `redline_state` 字段

### R38: 板块战略动作矩阵
- 新建 `sector_action_matrix.py`：主攻(60%配额)/次攻(30%)/高位(0%)仓位分配
- 改 `active_portfolio_cleaner.py`：开盘自动挂高位股止盈卖单

### R39: 执行闸门加固
- 删除 `is_strong_leader` 特权逻辑
- 卖单剥离对 `chan_buy_point`/`chan_sell_point`/`chan_confirmed` 的校验
- 统一收敛 `catalyst_types` 命名

### R40: 全链路推演测试
- 新建 `tests/test_round5_nested_plan.py`

## 优先级
- **P0（本周必须）**: 拔除is_strong_leader + 修复卖单门禁 + 简易sentiment_redline
- **P1（本周完成）**: 连板天梯图 + condition_evaluator + 板块动作矩阵
- **P2（两周内）**: 盘前AGY自动编译预案 + 产业链图谱 + 参数自寻优

## 改造后的数据结构(Schema)

```json
{
  "candidate_id": "nested-002041.SZ-buy-2026-09-02",
  "strategic_layer": {
    "sector_role": "primary_attack",
    "strategy_action": "low_suck_first_board",
    "position_tier": "first_board_seed",
    "allocated_capital_pct": 0.20
  },
  "condition_triggers": {
    "auction_open_min_pct": -1.0,
    "auction_open_max_pct": 3.0,
    "max_chase_pct": 6.0,
    "must_seal_before": null,
    "sector_open_max_pct": 3.0,
    "dependency_anchor": {
      "symbol": "600371.SH",
      "min_auction_open_pct": 2.0,
      "must_not_explode": true
    }
  },
  "redline_bind": {
    "market_sentinel": "002084.SZ",
    "sector_sentinel": "600371.SH",
    "action_on_breach": "abort_and_sell_only"
  }
}
```

## 架构图

参见 Markdown mermaid 架构图: 四层嵌套计划引擎（Layer1 板块战役定调 → Layer2 连板天梯身位 → Layer3 盘口条件求值器 → Layer4 情绪红线总线 → 执行闸门）
