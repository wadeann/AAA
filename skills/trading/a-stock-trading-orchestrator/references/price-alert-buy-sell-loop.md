# 收盘警戒计划与盘中买卖闭环

## 适用场景

适用于需要在盘中及时发现买卖机会、减少重复K线/新闻查询、并通过 Hermes MCP 模拟账户自主执行的A股流程。

## 标准状态流（三段式：no_agent → LLM → no_agent）

`close_review -> alert_plan -> price_scan -> triggered_reaudit -> awaiting_llm_review -> llm_review(verdict) -> candidate_update -> risk -> intent -> order -> reconciliation -> performance_snapshot`

**关键设计决策**：触价后不直接进入执行闸门，而是先由no_agent做预审（缠论+新闻+基本面），写入 `awaiting_llm_review: true` 标记，再由独立的LLM agent cron做深度定性分析，只有APPROVE后才进入风控闸门。用户明确要求"触发买卖价格之后，由LLM进行一次真正的认真的分析"。

### 三阶段职责

| 阶段 | 组件 | 类型 | 频率 | 职责 |
|------|------|------|------|------|
| Stage 1 | `intraday_leader_monitor.py` | no_agent | 5min | 扫描价格 → 触价预审 → 写 `awaiting_llm_review` 候选 |
| Stage 2 | `盘中触价LLM审核` cron | LLM agent | 5min (offset 2min) | 深度定性分析 → 7道买入关/4道卖出关 → APPROVE/REJECT/HOLD |
| Stage 3 | `run_autonomous_trades.py` | no_agent | 15min | 跳过 `awaiting_llm_review` → 只处理 `llm_approved` → 风控→执行 |

## 收盘阶段

1. 使用收盘复盘的重点观察池生成买入计划。
2. 读取 MCP exec 持仓，为每个可卖持仓生成卖出计划。
3. 每条计划至少保存：`symbol`、方向、计划日期、买/卖警戒价、前置中枢上下沿、缠论结构、失效条件、来源、持仓分类；卖出计划还必须保存 `available_shares` 和原始 `exit_rule/thesis`。
4. 警戒价是唤醒条件，不是授权价格；不可因为触价单独下单。
5. 计划应对应最近一个已确认交易日，禁止把任意旧观察池静默当成次日计划。

## 盘中阶段

1. 先检查交易日和交易时段；异常或字段缺失直接静默/fail closed。
2. 每5分钟只读取计划并批量查询价格。价格未触发时不拉100根K线、不查新闻、不查基本面、不调用风控。

### 盘中窗口控制（双层闸门）

Hermes cron 单个表达式无法表达 "09:31 起" 或 "14:57 止" 这样的精确分钟边界。标准解决方案是双层闸门：

1. **cron 层**（粗粒度） — 在工作日对应小时的每5分钟唤醒，忽略 $X:30 和 $X:00 开始的误差：
   ```
   31-59/5 1 * * 1-5     # 北京时间 09:31-09:59
   */5 2-3 * * 1-5        # 10:00-11:35
   */5 5-6 * * 1-5        # 13:00-14:55
   ```

   ⚠️ **croniter 陷阱**：上面这三个表达式是分开写的，但绝不能把它们合并成逗号分隔的单个表达式（如 `31-59/5 1 * * 1-5,*/5 2-3 * * 1-5,*/5 5-6 * * 1-5`）！croniter 不支持 Unix cron 的逗号分隔多段表达式，会报错 "Exactly 5, 6 or 7 columns has to be specified for iterator expression"，导致 job 进入 `state=error, next_run_at=null` 永久停摆。

   **正确做法**：将此 cron 拆成 3 个独立 cron job（每个对应一个表达式），或者用一个更宽松的表达式 `*/5 1-3,5-6 * * 1-5` 配合脚本层的 `in_monitor_window()` 过滤。

2. **脚本层**（精确闸门） — `in_monitor_window()` 函数使用北京时间 `datetime.time` 精确比较：
   ```python
   def in_monitor_window(now=None):
       now = now or dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))
       current = now.time().replace(second=0, microsecond=0)
       return (dt.time(9, 31) <= current <= dt.time(11, 35) or
               dt.time(13, 0) <= current <= dt.time(14, 57))
   ```
   脚本第0行检查此闸门，窗口外直接 `return 0`，不执行任何 MCP 调用和行情查询。

验证边界：`09:30 → False, 09:31 → True, 11:35 → True, 11:36 → False, 14:57 → True, 14:58 → False`。

此模式可复用任何需要精确北京时间分钟边界的 no_agent 脚本，不需每个脚本重新发明判断逻辑。
3. 买入计划：价格上破警戒位时唤醒完整复核。
4. 卖出计划：价格下破警戒位时唤醒完整复核。
5. 触发后再查实时行情、100根30分钟K线、成交量、板块共振、新闻/公告、基本面、账户余额和持仓。
6. 同一计划/触发事件使用持久化事件键去重；失败、拒绝或已提交都不得在后续轮次重复下单。

### Stage 2: LLM 深度审核

触价预审通过后，候选携带 `awaiting_llm_review: true` 标记。独立LLM agent cron（每5分钟，晚2分钟偏移）扫描并执行深度审核：

1. 读取候选JSONL，筛选 `awaiting_llm_review: true` 的记录
2. 对每个候选拉MCP数据：实时行情、30min/60min缠论K线、新闻/公告、板块资金、策略反馈
3. 执行7道买入关/4道卖出关定性审核
4. 输出 `llm_review` 记录，包含 verdict (APPROVE/REJECT/HOLD)、reasoning、suggested_price、stop_loss、target_price
5. 同步写入 `candidate_update` 记录更新候选状态

审核规范详见 `skills/trading/price-trigger-llm-review/SKILL.md`。

## 买卖复核差异

- 买入：要求一买/二买/三买、结构确认、量价、板块、新闻、基本面、实时证据和研究 thesis。
- 卖出：要求卖出结构/顶背驰/破位证据；必须检查上升通道保护、板块强势保护、T+1 和 `available_shares`。上升通道中的趋势票不能仅因价格触发而卖出。
- 卖出数量不得超过 `available_shares`，且必须是100股整数倍。
- 价格触发但结构复核失败时，只记录 `triggered_reaudit`/预警，不生成 candidate。

## 执行闭环

确认后的买卖 candidate 统一进入：

`candidate JSONL -> risk_batch_check -> get_balance/get_positions -> register_approved_intent(必要时) -> place_order -> get_orders(order_id回查) -> intent归档 -> 飞书通知`

MCP exec 是模拟账户时，可以默认允许 MCP 模拟委托；使用专用 `HERMES_MCP_DRY_RUN=1` 做演练，不要用真实券商的 `HERMES_EXECUTE` 开关阻断模拟闭环。

## 性能与正确性验收

- 价格未命中周期不得调用完整审计工具。
- 命中后必须能从事件记录追溯计划、价格、完整证据和最终状态。
- 买入和卖出各有至少一个 mock candidate 测试。
- 非交易日、无计划、账户/持仓不可用、T+1不可卖和上升通道卖出都必须 fail closed。
- 周/月收益以持久化账户快照计算，不能用当前累计盈亏冒充区间收益。
- 三阶段链路必须完整：no_agent触发 → LLM审核 → no_agent执行。跳过LLM审核直接进入执行闸门的候选必须被拦截。