# 盘中脚本从"观察器"升级为"执行器"的工程模式

> 本文档记录将只输出看板（观察器）的盘中监控脚本，系统性地升级为"识别买点→风控审批→真实下单"三级实战引擎的通用方法。

## 适用场景

任何盘中 cron 脚本当前是 **no_agent 脚本模式**，只做 `print()` 推送看板到飞书，**不产生任何实质性买卖信号或下单操作**。典型表现：
- 脚本能输出板块天梯、连板梯队、持仓状态，但永远只有"防守"卡
- 不会写入 `candidates_{date}.jsonl`
- 不会触发 `run_autonomous_trades.py` 或 `direct_executor.py`
- 用户问"为什么一个买入信号都没发现"时，脚本确实没有产生

## 诊断：先定位阻断原因

在动手改造前，必须用实际数据定位为什么脚本不产出买点。常见阻断层：

| 阻断层 | 特征 | 根因 |
|--------|------|------|
| **数据源白名单门禁** | 天梯抓取正常(涨停50家)但候选始终为空 | 候选生成函数绑定 `data_source_used != "wencai"` 做白名单过滤 |
| **问财API额度耗尽** | 涨停梯队数据正常(akshare/tdx容灾)但候选用问财搜索返回空 | 候选生成**始终依赖 wencai_search**，未给候选添加其他数据源容灾 |
| **筛选条件过窄** | 板块有涨停梯队，但涨幅/量比/成交额/股价等条件组合太严 | 涨幅 1.5%~6.0%、量比>1.1、成交额>1亿、现价≤50 等窗口极窄 |
| **缺乏资金验证** | 脚本有候选生成逻辑但候选质量极低 | 只靠量比/换手率，没看主力净流入，跟风诱多标的大量混入 |
| **执行链路断开** | 候选已生成但只用于 print() 看板输出 | 未写入 `candidates_{date}.jsonl`，无 `llm_approved=True` 标记，无 `normalize_intent` → `risk_check_and_execute` 调用 |
| **情绪/退潮熔断缺失** | 退潮日(炸板率>40%)仍试图生成买入候选 | 无保护逻辑，导致退潮日买入信号泛滥 |

### 数据源白名单门禁

```python
# ❌ 错误模式：候选生成绑定天梯数据源
def get_buyable_candidates(top_sectors, data_source_used="wencai"):
    if not top_sectors or data_source_used != "wencai":
        return []  # 天梯从akshare/tdx容灾时就无条件返回空！
```

**修复**：候选生成函数不应该关心涨停天梯的数据源源头。问财接口被用于候选筛选时，只依赖问财本身的可用性——如果问财不可用，候选生成应该通过**其他数据源**（如 tdx_screener）做容灾，而不是因为天梯侧用了不同数据源就直接返回空。

### 问财API额度陷阱

**关键事实**：问财 API（wencai_search）的频率限制非常严格，交易日盘中可能随时额度用尽。表现为：
- 非交易时段返回 `"所有 API Key 均已失效或达到上限"`
- 盘中连续调用后突然返回空/error
- **容灾必须是非问财通道**（如 tdx_screener、akshare_em 的板块选股能力）

```python
# ✅ 候选生成的容灾模式
# 层级1：wencai_search（主通道，额度充足时可用）
# 层级2：tdx_screener（通达信NLP选股器，不同API额度，独立限流）
# 层级3：从已核验涨停梯队的板块数据中找跟风股
```

### 情绪熔断保护

买入候选必须在生成后、写入前经过情绪熔断：

```python
# 炸板率>40% → 强制防守，拦截所有买点
# 最高板≤1且炸板率>30% → 退潮熔断，不生成买点
if zb_rate > 40.0:
    candidates = []  # 强制防守
elif max_streak <= 1 and zb_rate > 30.0:
    candidates = []  # 退潮熔断
```

### 主力资金流向过滤

候选生成后必须过资金关：

```python
for c in candidates:
    flow = get_fund_flow(c["symbol"])
    main_net = flow.get("MainNetFlow", 0)
    if main_net <= 0:
        continue  # 主力净流出→诱多，排除
    c["main_net_flow"] = main_net
    verified.append(c)
```

## 核心升级：从 print 到执行链路

### 执行链路架构

```
脚本生成候选
    ↓
情绪熔断(炸板率>40%拦截)
    ↓
资金流向验证(主力净流入>0)
    ↓
写入 candidates_{date}.jsonl (record_type=candidate)
  - catalyst_type: intraday_sector_sniper (或其他策略标识)
  - llm_approved: True (标记已通过系统级审核)
  - agy_approved: True
    ↓
autonomous_trade_pipeline (direct_executor 每2分钟扫描)
  - normalize_intent() → 动态仓位计算
  - risk_check_and_execute() → 风控审批
  - place_order() → 真实下单
    ↓
输出看板 + 执行统计
```

### 候选写入模板

```python
from autonomous_trade_pipeline import append_jsonl

cand_path = Path(f"~/.hermes/trading/feedback/candidates_{today}.jsonl")
candidate = {
    "record_type": "candidate",
    "candidate_id": f"iss-{symbol}-{timestamp}",
    "symbol": symbol, "name": name,
    "direction": "buy",
    "price": price,
    "quantity": 100,  # normalize_intent 会重算
    "confidence": 0.7,
    "thesis": f"板块跟风中军, 对标龙头{leader_name}",
    "entry_rule": f"回踩分时均线企稳买入",
    "stop_loss": stop_loss, "target": target,
    "catalyst_type": "intraday_sector_sniper",
    "llm_approved": True,
    "agy_approved": True,
    "reviewed_by": "intraday_sector_sniper",
    "reasoning": f"主力净流入{main_net_flow}, 量比{volume_ratio}",
    "created_at": datetime.now(timezone.utc).isoformat(),
}
append_jsonl(cand_path, candidate)
```

### 激进出单模式（推荐）

候选写入后，**立即在同一线程中调用执行链路**（而非等 direct_executor 每2分钟扫描）：

```python
from autonomous_trade_pipeline import normalize_intent, risk_check_and_execute, _mcp_call

intent = normalize_intent(candidate, total_assets=0, adjusted_pct=0.20)
res = risk_check_and_execute([intent], call=_mcp_call, dry_run=False)
```

**优势**：候选写入后立即走风控→下单，无需等待 direct_executor 的下一个2分钟周期，缩短执行延迟。

**注意事项**：
1. `normalize_intent` 的 total_assets=0 会导致跳过动态仓位计算（使用候选中的 `adjusted_pct` 或默认 20%）
2. `risk_check_and_execute` 内部会自行获取账户快照和仓位数据
3. 非交易时段 `risk_check_and_execute` 会正确返回 `blocked_outside_trading_session`，不会误下单
4. 需要有 `autonomous_trade_pipeline` 模块的导入权限（与脚本同目录下）
5. 如果导入失败，fallback 为仅写入候选，由 direct_executor 后续处理

### 去重与方向冲突

- `append_jsonl` 内部使用 `dedup_append_many` → 自动防同ID重复
- `check_direction_conflict` 防同日同标的方向冲突
- candidate_id 建议包含时间戳（`%H%M%S`）以区分不同时段的候选
- 写入前最好调用一次 `check_direction_conflict` 主动拦截

## 实战改造核对表

1. [ ] 确认问题：检查 cron output 日志，确认脚本只输出防守看板，无候选写入
2. [ ] 检查 `get_buyable_candidates` 等候选生成函数是否有数据源白名单门禁
3. [ ] 检查候选筛选条件（涨幅、量比、换手率、成交额、股价）是否过窄
4. [ ] 确认问财 API 额度：非交易时段 `wencai_search` 是否返回 error
5. [ ] 确认候选生成是否有非问财容灾（tdx_screener 等）
6. [ ] 检查脚本是否有写 `candidates_{date}.jsonl` 的代码
7. [ ] 检查是否在候选写入时标记了 `llm_approved=True`
8. [ ] 检查是否需要情绪熔断保护（炸板率/退潮拦截）
9. [ ] 检查是否需要主力资金流向验证
10. [ ] 验证整条链路：手动执行脚本 → 检查 candidates jsonl → 检查 direct_executor 输出

## 已知陷阱

1. **问财额度在非交易时段耗尽但交易日会重置**：非交易时段测试时问财返回 error 不代表交易时会失败。但盘中也要为额度用尽做好准备。
2. **问财字段带日期后缀且可能混入昨收**：盘中查询即使写了“现价”，也可能返回 `收盘价[YYYYMMDD]`、`换手率[YYYYMMDD]`、`ma50[YYYYMMDD]`。字段契约必须支持别名/日期后缀；若价格来自 `收盘价[...]`，必须再用腾讯等第一手实时行情替换价格、涨幅和成交额，实时价缺失则 fail-closed，禁止拿昨收生成买入区间。
3. **字段存在不等于字段名完全匹配**：不要用 `k == "最新价"` 或只认 `50日均线`；按语义别名匹配，例如价格=`最新价|收盘价`、均线=`50日均线|ma50`，再做实时性校验。
4. **tdx_screener 也有单独配额度**：通达信 API 有独立限额，两个通道独立消耗，不会互相影响额度。
5. **多数据源候选可能相互竞争**：不同 cron 脚本写入的候选都进入同一 JSONL，需要统一的去重和方向冲突检测。
6. **生产脚本手动验证可能写真实候选**：直接运行会调用 `emit_candidates_and_execute()` 的脚本前，优先增加/使用无副作用测试入口；若必须实跑，先记录台账基线，运行后核对订单，再精准删除本次测试 candidate_id，绝不能用带行号的展示文本回写 JSONL。
7. **文件工具输出含行号前缀**：`read_file` 展示的 `1|...` 不是文件内容。程序化清理 JSONL 时应直接读取原始文件或明确剥离前缀，写回后立即重新解析验证，防止把行号写进账本或误清空文件。
8. **激进出单(call in same thread)可能被风控拒绝**：风控在非交易时段返回 `blocked_outside_trading_session`，不是 bug，是正确行为。
9. **direct_executor 处理同ID候选只一次**：一旦 candidate_id 被标记为 `executed`/`risk_blocked`/`condition_rejected`，后续不处理。写入新 candidate_id 不受影响。

## 盘中推送必须从“行情说明”升级为“交易指令”

用户看到天梯、板块热度后，真正需要的是下一步怎么做。盘中卡片无论是否存在即时买点，都必须回答以下问题：

1. **当前结论**：立即买、条件买、持有/减仓，或明确“不下单”；
2. **具名标的**：股票名称与代码，禁止只写板块、中军、龙头等泛称；
3. **价格纪律**：买入区间/触发价、止损或清仓价、第一减仓目标；
4. **仓位纪律**：单票仓位与总仓上限；
5. **形态触发**：如“回踩分时均线缩量企稳后重新放量转强”；
6. **弃买条件**：指数继续下杀、板块涨停少于2家、龙头开板回撤、高开过度等；
7. **高位防守名单**：>=3板原则上只卖不买，不得挤占低位条件预案名额。

### 有买点时的固定句式

```text
标的名称 代码 买入X.XX~X.XX｜止损/清仓X.XX｜第一减仓X.XX｜仓位15%~20%；
触发条件：回踩分时均线缩量企稳后重新放量转强；
弃买条件：跌破分时均线3分钟不能收回、板块涨停少于2家或龙头开板回撤超4%。
```

### 无即时买点时也不能只写“观察”

必须分成两层：

```text
1、当前结论：无可立即执行买点，现阶段不下单。
2、解除熔断后的条件预案：低位首板/2板标的 + 触发价 + 止损/清仓价 + 第一减仓价 + 试错仓位 + 触发/弃买条件。
3、高位只卖不买：具名高标及减仓/清仓规则。
```

条件预案只能选择**首板或2板低位种子**。不得把5板、6板空间龙写成“解除熔断后买入候选”，高标只能进入防守名单。

## 条件预案必须进入持续监控闭环（不能停留在消息文本）

盘中看板给出“触发价/解除熔断后买入”时，**打印出来不等于系统会跟踪**。只有同时完成以下状态转换，才允许向用户表述“将持续跟踪并自动交易”：

```text
飞书条件预案
  → 结构化计划落盘（仅当日有效）
  → 高频守护进程加载
  → 实时价格与市场条件反复复核
  → 触发后写 candidate/intent
  → risk 审批
  → exec 注册与报单
  → 订单回查
  → 成交后持仓止损/移动止盈守护
```

### 结构化条件计划最小字段

- `date / updated_at / symbol / name / sector / streak`
- `reference_price / trigger_price / stop_loss / target / position_pct`
- `max_break_rate / min_sector_limitups / max_change_pct`
- `source / plan_id`，并保证同日同标的幂等

### 触发纪律

1. 条件预案只允许首板/2板低位种子，`streak >= 3` 永不进入自动买入池；
2. 不能因现价第一次高于触发价就追单，至少记录“曾回踩触发线下方/附近”，再确认重新上穿；
3. 价格命中只是唤醒复核，不是授权下单；触发当刻必须重新获取实时炸板率、板块涨停家数、指数状态、个股涨幅、资金、账户现金和持仓；
4. **严禁使用生成消息时保存的炸板率/板块家数快照作为后续30秒轮询的实时门禁**。计划文件保存阈值，守护进程每轮刷新市场实际值；数据刷新失败必须 fail closed；
5. `sell_only_mode`、情绪熔断、T+1、黑名单、仓位和现金门禁任何一项不通过，都只能记录“仍在跟踪/被风控阻断”，不得报单；
6. 报单成功以有效 `order_id` 和订单回查为准；只有写入候选或调用下单不算成交；
7. 买入成交后必须自动纳入止损、保本、分批止盈和最高水位线守护。

### 运行态验证（修改后必须做）

- 单测验证：先在触发线下方记录回踩，随后上穿才调用执行函数；
- 单测验证：`sell_only_mode=true`、高标、市场数据缺失时均不下单；
- 检查守护服务确实 active，并确认加载的是修改后的代码；
- 用模拟 MCP 验证 `risk → register intent → place_order → order_id`，不得用生产实盘做测试；
- 明确向用户披露执行账户：MCP 模拟柜台还是已连接的真实券商柜台，不得把“自动报单”直接等同“真实券商成交”。

### 消息状态必须准确

盘中推送应明确区分：

- `条件预案已生成，尚未注册监控`；
- `已注册持续跟踪，尚未触发`；
- `价格触发但风控阻断`；
- `已提交委托，订单号...`；
- `已成交`。

禁止在只生成文字预案时写“系统将自动交易”，也禁止把 `PENDING/已报` 写成“已成交”。

## 历史打法的数据快照纪律

基于前一交易日生成打法时：

- 指数涨跌幅、全A中位数必须读取该交易日固化快照，不能读取今天的状态文件；
- 缺失值必须显示“数据缺失”，严禁用 `0.00%` 伪装有效数据；
- 全A中位数问财查询使用明确口径：`YYYY年M月D日全A涨跌幅中位数` 或 `今日全A涨跌幅中位数`；
- 建议在计划 JSON 内固化 `market_snapshot`：`regime / gem_change_pct / median_change / up_count / down_count / source_date / source`；
- 历史预案重放优先读取归档 plan，不得用当前熔断状态重新编译污染历史判断。

## 回归测试最小集

观察器升级为荐股/执行器后，至少覆盖：
1. 标准字段与带日期字段都能解析；
2. 带日期的历史价格必须被实时行情替换；
3. 实时行情缺失或涨幅越界时不生成候选；
4. 非交易时段 `--force` 只展示、不写候选；
5. 例行无操作状态不推送，只有买入、卖出、熔断或风险异常才通知；
6. 有候选时必须包含名称、代码、买入区间、止损/清仓、第一减仓、仓位、触发条件和弃买条件；
7. 无即时买点时必须明确“不下单”，同时给低位具名条件预案；
8. 条件预案不得包含>=3板高标；
9. 历史市场快照缺失时显示“数据缺失”，不能输出伪造的0%；
10. 历史打法使用归档日快照，不受当前 `market_regime.json` 污染。
