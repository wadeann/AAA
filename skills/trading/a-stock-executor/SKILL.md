---
name: a-stock-executor
description: "A股执行员：将风控批准的 TradeIntent 转成委托订单并回报状态。只执行 approved/reduced 的 intent。"
version: 2.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [trading, a-stock, executor, order-execution]
    related_skills: [a-stock-trading-rules, a-stock-risk-officer]
---

# A股执行员

## 🔴 卖出前持仓分类（2026-06-24 铁律）

在执行卖出前，必须将持仓按以下维度分类，不同分类的卖出纪律完全不同：

| 分类 | 判定标准 | 卖出纪律 |
|------|---------|---------|
| **趋势票** | 处于主升浪，板块共振强（板块涨跌幅 top5），K 线上升通道 | **不设硬止损价**，卖点看形态（破位/顶背离），止盈线上移 |
| **波段票** | 有明确催化剂（如解禁、财报），非主升浪，板块一般 | 设硬止损价（-6%~-15%）+ 到期强制离场 |
| **事件票** | 消息驱动，无基本面/技术面支撑 | 消息兑现即走，持仓不超过 2 天 |

**海光、中芯属于趋势票（半导体主升浪）→ 不应该按波段票止盈价卖出。**
**荣昌属于波段票（7/1 解禁 34.16%）→ 必须在 6/30 前减仓/清仓。**

## Overview

A股执行员角色。只负责执行已通过风控审批的交易，将 approved/reduced 的 TradeIntent 转成委托订单。

## When to Use

- 风控员输出审批结果后需要下单执行时
- 紧急止损需要撤销未成交委托时
- 作为 subagent 被交易编排流程调用时

## 可用工具

| 工具 | 用途 |
|------|------|
| mcp_exec_place_order | 提交买入/卖出委托（支持非交易时段排队 PENDING） |
| mcp_exec_cancel_order | 撤销未成交/排队中（PENDING）的委托 |
| mcp_exec_get_orders | 查询今日委托（含 PENDING 状态） |
| mcp_exec_get_balance | 查询账户资金 |
| mcp_exec_get_positions | 查询当前持仓 |
| mcp_exec_get_today_trades | 查询今日成交 |
| mcp_exec_get_pnl | 查询盈亏统计 |

## 禁止使用的工具

- 不可调用 mcp_intel_* 任何工具（不做研究）
- 不可调用 mcp_risk_* 任何工具（不做风控）

## 输入

接收风控员输出的 TradeIntent JSON 数组（通过 context 注入）。

## 工作流程

### Step 0：卖出前强制 K 线检查（2026-06-24 铁律，不可跳过）

**任何 SELL 操作前必须执行以下检查，不满足条件则拒绝卖出：**

1. **拉 30 分钟 K 线**：调用 `mcp_intel_fetch_kline(symbol, period="30", count=20)` 分析趋势
2. **拉 60 分钟 K 线**：调用 `mcp_intel_fetch_kline(symbol, period="60", count=10)` 确认中周期形态
3. **趋势判断**：
   - 上升通道中（高点上移+低点上移）→ 🔴 **禁止卖出**，保留持仓
   - 横盘震荡 → 🟡 可部分减仓（50%），留半仓观察突破方向
   - 下跌中继/破位/顶背离 → 🟢 允许卖出，全仓出清
4. **板块共振验证**：用 `mcp_intel_wencai_search` 确认该股所属板块今日涨幅排名。如果板块涨幅 top5 且个股处于上升通道 → 禁止卖出
5. **违规记录**：如果在上升通道中强行卖出，必须在 reason 中写"⚠️ 违反卖出规则：上升通道中卖出"，并记录到 `strategy-feedback.md`

**教训（2026-06-24）**：海光 316.88→337.1（+6.3%）、中芯 130.00→151.5（+6.9%），两票都在半导体主升浪中被卖出，踏空约 12,656 元。根因：没有拉 K 线就决策卖出。

### Step 1：解析审批结果

1. 过滤出 approval_status == "approved" 或 "reduced" 的 intent
2. 检查是否有 `auto_execute_reduction: true` 的 intent（日亏≥5% 触发，无需用户确认，直接执行）
3. 其余 approved/reduced intent 正常等待用户确认（V0 阶段规则）

### Step 2：风控前置检查（不可跳过）

**必须先完成风控审批，再执行下单。缺少风控审批的intent禁止执行。**

1. **调用 `mcp_risk_daily_pnl`** — 获取当日盈亏，判断是否触发日亏熔断
2. **调用 `mcp_risk_get_blacklist`** — 获取黑名单，过滤ST/退市标的
3. **调用 `mcp_risk_batch_check`** — 批量风控检查，传入所有待执行intent（含symbol/direction/quantity/price）
4. **等待风控员输出带 `intent_id` 的审批结果**
5. **用户已明确授权自主交易时**：对本次新建仓只要风控结果为 `approved` 或 `reduced` 且 `intent_id` 有效，即可直接执行，无需再次询问；不得把“立即通知”误解为“等待确认”。仍必须完整保留风控、注册、下单和订单回查链路。

**⚠️ 7/3 教训**：agent 跳过了 batch_check 直接下单，这是流程违规。即使用户要求"自负盈亏"，风控前置仍是硬约束。

### Step 3：资金确认

调用 `mcp_exec_get_balance` 确认可用资金；调用 `mcp_exec_get_positions` 确认当前持仓。

### Step 4：逐笔委托

对每个待执行 intent：

**买入 intent 委托价格逻辑**（根据 entry_rule 判断）：

| entry_rule 类型 | 委托价格设置 |
|----------------|-------------|
| 回调至某价附近 | 限价单，使用该价格 |
| 开盘3分钟内追进 | 开盘后前3分钟挂略高于现价的限价单 |
| 竞价直接开板 | 涨停板封单，挂涨停价 |

**数量计算**：
- reduced intent：使用 adjusted_position_pct × 总资产 / 价格，向下取整到 100 的整数倍
- approved intent：使用 initial_position_pct（首次建仓）× 总资产 / 价格，向下取整到 100 的整数倍

**注意**：金字塔加仓的第二笔（add_on_trigger）在 add_on_trigger 条件满足时才下单，当前只执行首次建仓。

调用 `mcp_exec_place_order` 参数：
```json
{
  "symbol": "600519",
  "direction": "buy",
  "quantity": 100,
  "price": 1680.00,
  "intent_id": "INTENT-xxxxxxxxxxxx",
  "reason": "突破均线，LLM情感分0.8利好"
}
```

**🔒 intent_id 是必填参数**：从风控员收到的审批结果中，每个 approved intent 已附带 `intent_id` 字段（格式 `INTENT-{uuid}`）。不带 intent_id 下单会被 exec_server 直接拒绝（返回 `MISSING_INTENT_ID` 错误）。

**盘外下单逻辑**：
执行 `place_order` 时，如果返回结果 `detail: "queued_as_pending"`，这表示此时非开盘时间，订单已成功进入排队队列，开盘后会自动按市价撮合。执行员应将其视为**成功下单**，在最终汇报中记录状态为 `PENDING`。

记录 order_id 和状态。

### Step 4：输出执行结果

```json
{
  "executed": [
    {
      "symbol": "600519",
      "direction": "buy",
      "quantity": 100,
      "price": 1680.00,
      "order_id": "260854300000078983",
      "status": "submitted",
      "source_intent_thesis": "原始交易理由",
      "auto_executed": false
    }
  ],
  "skipped": [
    {
      "symbol": "000001",
      "reason": "approval_status was rejected",
      "rejection_reason": "T+1 violation"
    }
  ],
  "summary": {
    "total_intents": 5,
    "executed": 3,
    "auto_executed": 1,
    "skipped": 2,
    "total_amount": 504000.00
  }
}
```

## 约束

- **强制风控前置**：只接受 approval_status == "approved" 或 "reduced" 的完整 TradeIntent JSON 作为输入。如果没有 approval_status 字段，或 approval_status 为 "pending"，直接拒绝执行并报错 "TradeIntent 未经过风控审批，禁止下单"。绝对禁止跳过风控直接调用 mcp_exec_place_order。
- **单字/emoji确认立即执行**：用户已授权全权自主交易后，"买"/"卖"/"需要"/👍/👌 等极简回应 = 立即执行全链路（研究员→策略→风控→注册→下单→回查→归档）。不等第二句话，不问"确认吗"。这是用户明确的极简沟通偏好，反复索取确认会降低执行时效性。
- **强制归档**：每次下单（无论成功或失败）后，必须将完整的 TradeIntent JSON（含 order_id、成交状态）归档到 `~/.hermes/trading/intents/intent_YYYYMMDD_{symbol}_{direction}.json`。如果 intents/ 目录不存在则创建。这是审计追踪的硬性要求。
- 只执行 approved 或 reduced 的 intent，rejected 的绝不执行
- `auto_execute_reduction: true` 的 intent 无需用户确认，直接执行
- 其他 intent 仍遵守 V0 阶段规则：需用户确认
- 不做任何研究、策略判断或风控覆盖
- 下单失败时记录错误原因，**不自动重试**
- 委托数量必须为 100 的整数倍（A股 1 手 = 100 股）
- 当前仅执行首次建仓（initial_position_pct），加仓（add_on_trigger）待后续盘中触发

## 无风控MCP时的替代链路（2026-09-03）

当 `mcp_risk_batch_check` / `mcp_risk_*` 工具不在可用工具列表中时，无法走标准风控审批。替代流程：

1. **K线手动验证**：调用 `mcp_intel_fetch_kline(period="30", count=20)` 判断趋势。上升通道内禁止卖出，大阴破位允许卖出。
2. **直接注册intent**：`mcp_exec_register_approved_intent(intent_id, symbol, direction, max_quantity, expires_at)` — 不依赖risk_server自动注册。
3. **下单**：`mcp_exec_place_order` 传入已注册的 `intent_id`。
4. 此为**降级模式**，风控硬规则（T+1/涨跌停/仓位等）不会自动校验，需agent自行判断替代。

**北交所K线数据覆盖差异**：`mcp_intel_fetch_kline` 对北交所股票（`.BJ` 后缀，如 920593.BJ）可能返回 `{"status": "error"}`，但 `mcp_exec_place_order` 仍可正常执行。北交所标的的K线验证需依赖 `mcp_intel_query_batch_data` 获取实时价格作为替代，或搜索外部源交叉验证。

## MCP 模拟账户自主闭环（2026-08-15）

当用户要求“自主交易”且目标是 Hermes 内置 MCP 模拟账户时，执行链必须完整闭环：

1. 盘中监控器在信号确认后写入结构化 `record_type: candidate`，不能只发通知。
2. 交易闸门调用 `mcp_risk_batch_check`，只保留 `approved/reduced` intent。
3. 对仍有 approved intent 的批次，先调用 `mcp_exec_get_balance` 和 `mcp_exec_get_positions`；账户快照失败必须 fail closed。买入金额不得超过可用现金，卖出数量不得超过 `available_shares`。
4. 必要时调用 `mcp_exec_register_approved_intent`，再调用 `mcp_exec_place_order`。
5. 下单后必须调用 `mcp_exec_get_orders` 回查，并归档完整 intent、order_id、状态和错误。
6. 使用 candidate_id/intent_id 做幂等，已提交、失败、跳过或模拟完成的 candidate 不得重复下单。
7. MCP exec 是模拟账户，不应被 `HERMES_EXECUTE=1` 这个真实交易开关阻断。建议默认允许 MCP 模拟委托；需要演练时使用专门的 `HERMES_MCP_DRY_RUN=1`。
8. 盘中突破应拆为两个状态：`breakout_alert` 只通知等待回踩，`confirmed` 才可写入候选并进入风控/执行。

### 收盘警戒计划驱动的买卖执行

当系统使用收盘生成的次日价格警戒计划时，价格命中只是唤醒完整审计，不是授权下单。盘中先做轻量批量价格查询；只有命中后才复核实时行情、100根30分钟K线、成交量、板块、新闻/基本面和exec账户。买卖方向均写结构化candidate后走同一risk -> intent -> place_order -> order回查链。卖出必须额外核验卖出结构、趋势票上升通道保护、T+1和available_shares；价格触发但复核失败时只发预警并归档，不下单。详见编排技能 `references/price-alert-buy-sell-loop.md`。

### 收益闭环

- 每个交易日收盘保存 MCP 账户余额、现金、总资产、累计盈亏、持仓数量、成交数量快照。
- 每周和每月以持久化快照计算区间收益金额和收益率，不能只读取当前累计盈亏冒充周/月收益。
- 收益报告只读账户和成交数据，不改变持仓或订单。

## Common Pitfalls

1. **执行 rejected 状态的 intent** — 绝对禁止
2. **自动重试失败的委托** — 禁止，记录错误后结束
3. **委托数量不是 100 的整数倍** — 必须向下取整到手
4. **没有确认可用资金就下单** — 可能导致资金不足失败
5. **自行修改价格或数量** — 必须基于 intent 中的规则
6. **把 add_on_trigger 也当作首次入场下单** — 加仓逻辑是条件触发的，不是立即下单
7. **股票代码错误**: 执行前如果价格与预期差距巨大（如预期 60+ 却显示 5 元），立即中止并回查代码
8. **🔴 股票代码必须核实，禁止凭记忆输入**: 每次收到用户口头报出股票名称，必须先用 `mcp_intel_wencai_search(query="股票名 股票代码")` 获取准确代码后再下单。北交所股票代码以 9 开头、后缀 .BJ（如 920522.BJ）。凭记忆编造代码 = 下错单 = 严重违规。（2026-06-17 教训：纳科诺尔 920522.BJ 被编成 001377.SZ，铁拓机械 920706.BJ 被编成 300734.SZ，两笔错误委托需取消后用正确代码重下）
9. **交易日期不可凭记忆判断**: 声称"今天是周末/非交易日"前必须调用 `mcp_intel_is_trading_day` 验证。凭记忆说是周末就拒绝操作 = 失职。（2026-06-17 教训：6/17 是周三正常交易日，我错误说是周末导致延误）
10. **直接执行模式**: 用户明确要求"不要问、直接给专业意见"时，agent 串联风控校验→执行→回报全链路，不向用户提问
11. **`place_order` 返回 `table orders has N columns but M values were supplied`**: exec_server 的 `orders` 表 schema 可能与 `main.py` 中的 INSERT 语句不同步。诊断：`python3 -c "import sqlite3; conn=sqlite3.connect('exec_local.db'); [print(r) for r in conn.execute('PRAGMA table_info(orders)')]"`。修复：更新 `exec_server/main.py` 中的 INSERT VALUES 占位符数量和参数数量使之匹配实际表列数，同步更新 CREATE TABLE 语句。修复后需重启 exec 服务生效。
12. **`place_order` 报 "Insufficient shares" / available=0**: `normalize_symbol()` 输出格式与 DB 存储格式不一致导致 SELL 查不到记录。2026-06-04 已修复——确保 normalize_symbol 输出 `CODE.SH/CODE.SZ` 格式。详见 trading-infra-troubleshooting skill → `references/symbol-normalization-bug.md`
13. **`place_order` 报 "MISSING_INTENT_ID" / "INTENT_NOT_REGISTERED"**: `place_order` 现在强制要求 `intent_id` 参数。从风控员收到的审批结果中取 `intent_id` 字段，格式为 `INTENT-{uuid12}`。不带 intent_id 或被拒绝表示该交易未经过风控审批。详见 trading-infra-troubleshooting skill → `references/intent-approval-chain.md`
14. **风控报 "Weekend trading prohibited"**: 周末和非交易日风控系统会拒绝所有交易请求（包括持仓同步）。最佳同步时机是周一 09:30 开盘后。详见 a-stock-premarket-scan skill → `references/exec-sync-gap.md`
15. **`batch_check` 返回 `exec_registered: false`** — 风控通过（`approved: true`）但自动注册到 exec_server 失败（warning: "注册到 exec_server 失败，但风控已通过"）。此时 `place_order` 会报 `INTENT_NOT_REGISTERED`。**修复**：对每个 intent 手动调用 `mcp_exec_register_approved_intent(intent_id, symbol, direction, max_quantity, expires_at)` 注册后再下单。`expires_at` 格式：`YYYY-MM-DDTHH:MM:00+00:00`，设为当日下午盘后时间。这是 risk_server 自动注册偶发失败的兜底流程。
16. **🔴 向用户汇报交易记录时，必须先将股票代码转为名称**：调用 `mcp_intel_query_batch_data` 获取名称后再展示。不要只列代码让用户猜。2026-07-03 教训：用户说"把代号转成名称，还是没看懂你到底赚多少钱"。
17. **`no_agent` 脚本 stdout = 飞书消息，不是日志系统** — `run_autonomous_trades.py` 这类 trade_gate 脚本作为 `no_agent` cron 运行时，`print()` 输出的每一行内容都会投递到飞书用户。绝对不能在 stdout 里打印原始 JSON 字典/数据结构/调试信息，否则：
    - 输出超大（>16KB）→ 飞书投递被拒绝 → cron `last_status=error`（即使交易成功执行）
    - 用户看到的是一堆 JSON 垃圾而不是可读通知
    - **正确做法**：stdout 只输出精简短的可读人话；完整 JSON 报告用 `write_text()` 写入文件
    - **trade_gate 输出模板**：
      - 成功交易：`✅ 🔴卖出/🟢买入 {symbol} {qty}股@{price} {order_id}`
      - 风控拒绝：`⛔ 拒绝 {symbol}: {reason}`
      - 跳过：`⏭️ 跳过 {sym}: {reason}`
      - 无信号：`无信号`
      - 等待LLM二审：`⚡N个候选等待LLM二审中，已跳过`
    - 见 `trading-infra-troubleshooting` skill §33 完整排查指南
