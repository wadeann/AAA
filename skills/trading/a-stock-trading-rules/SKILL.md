---
name: a-stock-trading-rules
description: "A股交易系统全局规则参考：职责隔离、数据契约、风控硬规则、执行约束。加载此 skill 获取完整的交易系统规则框架。"
version: 2.1.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [trading, a-stock, rules, risk-control]
    related_skills: [a-stock-researcher, a-stock-strategist, a-stock-intraday-eval, a-stock-risk-officer, a-stock-executor, a-stock-reviewer]
---

# Outcome Spine

- **产出物**: 全局规则参考框架（JSON 合约 + 枚举表 + 硬约束清单）
- **下一个消费者**: 所有交易 skill（researcher/strategist/risk-officer/executor/orchestrator/intraday-eval）在各自流程中引用
- **完成条件**: 加载后，模型中可获取所有硬约束（T+1、涨跌停、仓位上限、流动性门槛）和 TradeIntent 合约字段
- **非明显意图**: 
  - 规则分为 **协议**（违反必出错：T+1、委托单位、代码格式、必填字段）和 **判断**（指导性：三分类、催化剂选择、信心阈值）
  - 执行约束中「禁止绕过风控」由 exec_server 代码级强制（place_order 必须带 intent_id），非仅靠 skill 文本
  - 教训类铁律（🔴标记）是历史踩坑记录，修改前确认是否仍有当前约束力

## 快速索引

| 需要什么 | 在哪里 |
|---------|--------|
| TradeIntent JSON 字段 / catalyst_type 枚举 | [数据契约 — TradeIntent JSON](#-数据契约--tradeintent-json) |
| 市场数据错误、空天梯、0板、缓存过期 | `references/market-data-freshness-and-schema-drift.md`（新鲜度、MCP契约漂移、非交易日/`--force`防陈旧数据、缺失维度权重、禁止板块龙头硬编码、**`get_limitup_ladder` 的 `board_height` 语义陷阱=当日涨停计数非累计连板**） |
| 单一指数下跌是否应全局停买 | `references/segmented-market-circuit-breakers.md`（宽基与窄基区分、科创50孤立下跌只隔离科创板、旧全局熔断自愈及回归测试） |
| 风控硬规则（T+1、涨跌停、仓位上限） | [风控硬规则](#风控硬规则risk-mcp-服务端强制执行) |
| 研究员/策略员/风控员/执行员可调用哪些 MCP | [职责隔离](#职责隔离不可违反) + [MCP 工具映射](#mcp-工具映射) |
| 第一性原则 / 紫苏叶 / 归海一刀选股 | [🔴 第一性原则选股](#-第一性原则选股2026-06-24-铁律最高优先级) |
| 卖出前 K线检查 + 持仓三分类 | [🔴 卖出前 K线检查 + 持仓分类](#-卖出前-k-线检查--持仓分类2026-06-24-铁律) |
| 脚本优先架构（kline_analyze 等） | `~/.hermes/trading/scripts/data/` |
| 沉淀闭环 learnings/ | `~/.hermes/trading/learnings/` + `scripts/compound_learnings.py` |
| Cron 定时任务清单 | `references/cron-operations.md` |
| 🔴 反转分析 - 四维否决矩阵 | [🔴 反转判断量化框架](#🔴-反转判断量化框架四维矩阵否决法) |
| 🚀 Ignition-V1 V2 首板起爆策略（含AGY审计修复） | `references/ignition-v1-strategy.md` |
| ⛔ 飞书输出铁律（v5 极简版） | [⛔ 飞书输出铁律（v5 — cron/pipeline 用此版本）](#-飞书输出铁律v5--cronpipeline-用此版本) |
| 🔴 CRON 使用本 skill 的陷阱 | [🔴 重要：本 skill 不适合直接加载到 cron job](#-重要本-skill-不适合直接加载到-cron-job)

---

## 🔴 第一性原则选股（2026-06-24 铁律，最高优先级）

> **2026-06-24 教训**：追北交 920522（-2,520）、920706（-1,920），两票合计 -4,440。北交流动性差、无基本面、纯情绪交易。根因：没有第一性原则支撑。

所有买入决策必须过以下三道关卡，缺一不可：

### 关卡 1：供需缺口（第一性）

- 这东西为什么稀缺？
- 供给端有没有壁垒（政策/技术/资源/牌照）限制？
- 需求端是不是刚需且不可替代？

**不满足的核心问题示例**：北交所小盘股 — 供给无壁垒（任何公司都能上市），需求无刚性（没有独特的不可替代性）

### 关卡 2：紫苏叶五因子

- 供需缺口 ✅/❌
- 壁垒（政策/技术/资源/牌照） ✅/❌
- 锁定（客户粘性/转换成本/网络效应） ✅/❌
- 关注度（市场热点/资金流入） ✅/❌
- 业绩��收入/利润增长） ✅/❌

**判定标准**：
- ✅ 真紫苏叶：需求真实 + 供给受限 + 至少 3 个 ✅
- ⚠️ 准紫苏叶：供给中等受限 + 至少 2 个 ✅
- ❌ 非紫苏叶：供给完全不受限 → **直接 PASS，不做任何分析**

### 关卡 3：归海一刀主升浪验证

- 是否为 8 种涨停形态之一？（攻击迫线/登高望远/进二退一/放量过顶/冲天炮/旭日东升/三线金叉/射击之星）
- 是否为拉高建仓或下跌反弹（不是主升浪）？→ 跟主升浪的是赚钱的，其他的 PASS

**禁区**：
- 流动性差的标的（日均成交 < 5000 万）→ PASS
- 纯情绪/概念炒作无基本面 → PASS
- 第一眼看不懂「为什么稀缺、为什么涨价」→ PASS

---

## 🔴 反转判断量化框架（四维矩阵否决法）

> **2026-09-07 从 memory 升级为 skill**：此前反转判断方法只存在于 memory（\"MA5/MA10死叉+MACD水下死叉=直接❌不是反转\"），但 agent 在个股分析时未能自动应用此框架。升级为 skill 后，所有\"是否反转\"类问题必须执行此检查。

**原则**：反转 = 趋势方向的根本改变，不是单日阳线反弹。反转必须有可量化的多周期验证。

### 一票否决条件（任一成立→直接❌，不做其余分析）

| 条件 | 具体规则 | 数据源 |
|:----|:--------|:------|
| MA5 < MA10 且 MA10 < MA20 空头排列 | 看收盘价，不是盘中 | `get_technical_indicators` → MA_5, MA_10, MA_20 |
| MACD 的 DIF < DEA（死叉状态） | 只认状态，不认单日柱翻红 | `get_technical_indicators` → DIF, DEA |
| MACD 的 DIF 和 DEA 均 < 0 | 水下死叉更严重 | 同上 |
| 20日主力净流出 > 5亿且加速 | 说明大资金在持续砍仓 | `get_fund_flow` → MainNetFlow20D |
| 高点到当前跌幅 > 50% 且未出现放量底分型 | 下降趋势线段未结束 | `fetch_kline` → 60日K线检验结构 |

**典型误判**：单日+3%/阳线/Bias6超卖修复 → 这些是**反弹信号，不是反转信号**。反转一定需要MA排列修复+MACD金叉+量价共振。

### 四维矩阵验证（否决不成立后执行）

所有维度必须 >= 2分（满分4分），才允许判定为\"反转观察\"。

| 维度 | 评分条件 | 满分 | 数据工具 |
|:----|:--------|:---:|:--------|
| **MA排列** | MA5金叉MA10 → +2分；MA10方向向上 → +1分；MA20被放量上穿 → +1分 | **4** | `get_technical_indicators` → `ma.MA_5`, `ma.MA_10`, `ma.MA_20` |
| **主力资金** | 当日主力净流入 > 0 → +1分；5日主力净流向上拐头 → +1分；非大宗交易资金在承接 → +1分；融资余额企稳 → +1分 | **4** | `get_fund_flow` → MainNetFlow, MainNetFlow5D, MainNetFlow20D, MarginTradeInfos |
| **K线结构** | 出现底分型且成交量放大(>前日1.5x) → +2分；回踩不破前低 → +1分；突破MA20 → +1分；布林带开口收缩后放量 → +1分 | **5** | `fetch_kline(period=\"D\", count=60)` + `get_technical_indicators` → BOLL |
| **板块共振** | 所属板块当日涨幅TOP20 → +1分；板块5日资金净流入 → +1分；同板块有>1只涨停 → +1分；板块指数站稳MA10 → +1分 | **4** | `wencai_search(\"板块名 今日涨幅\")` + `fetch_sector_history(板块code)` |

**判定**：
- 一票否决触发 → ❌ **不是反转**
- 四维 >= 8分且无否决 → ⚠️ **反转观察**（需要回踩支撑确认）
- 四维 < 8分 → ❌ **不是反转**（反弹性质）

### 反转 vs 反弹的定性选择（输出格式）

```markdown
## 反转判定
一票否决：❌ MA5/MA10死叉（MA5=X < MA10=Y）+ MACD水下死叉（DIF=Z < 0）
四维矩阵：MA_1/4 + 资金_0/4 + K线_1/5 + 板块_0/4 = **2/17**
结论：❌ **不是反转，是下降通道中的超跌反弹修复**

操作意见：
- 反转确认需要：MA5金叉MA10 + 回踩不破前低 + MACD金叉上0轴
- 上方阻力：MA10=X, BOLL中轨=Y
- 若跌破前低Z，C浪延续，下方看布林下轨=W
- 当前**不入场**（博弈超跌反弹需等回踩支撑+放量确认）
```

> **2026-06-24 教训**：海光 316.88→337.1（+6.3%）、中芯 130.00→151.5（+6.9%），两票都在半导体主升浪中被卖出，踏空约 12,656 元。根因：没有拉 K 线就决策卖出。

### 卖出前必须执行的检查

| 检查项 | 工具/方法 | 通过条件 |
|--------|----------|---------|
| 30分钟K线趋势 | `mcp_intel_fetch_kline(symbol, period="30", count=20)` | 非上升通道（高点上移+低点上移）|
| 60分钟K线确认 | `mcp_intel_fetch_kline(symbol, period="60", count=10)` | 中周期确认形态 |
| 板块共振 | `mcp_intel_wencai_search("板块名 今日涨幅排名")` | 板块跌出 top10 方可卖出 |

### 🔴 紫苏叶×第一性双轨卖出法（2026-08-05 新增铁律）

> **核心思想**：你买股票的时候是因为供需缺口+紫苏叶+第一性原则买进的，卖的时候也要用同样的逻辑框架来决策。技术面止损只是风控工具，真正决定"该不该卖"的是基本面/供需逻辑是否还在。

每次决定卖出前，必须执行两条轨道检查，任一轨道触发即可卖出：

#### 轨道A — 技术面卖出（已有规则）
| 卖出条件 | 触发动作 |
|---------|---------|
| 硬止损位跌破 | 无条件全平 |
| 目标价到达 | 减半仓，上移止盈 |
| 趋势破位/顶背离 | 形态卖法全清 |

#### 轨道B — 供需逻辑面卖出（2026-08-05 新增，与轨道A并列，独立触发）
卖出前强制检查以下4项供需逻辑，任一成立即可卖出，**不需要等轨道A的止损位**：

| 检查项 | 判定标准 | 数据源 |
|-------|---------|--------|
| **B1：供需缺口消退** | 供给瓶颈解除（新产能投产/替代方案出现/竞争对手量产），或需求端验证低于预期 | wencai_search + search_news |
| **B2：紫苏叶因子消退** | 壁垒降低（专利到期/技术路线被超越）/锁定松动（客户导入第二供应商）/关注度过热（月涨>50%散户计数加大） | wencai_search 查涨幅/研报密度/龙虎榜 |
| **B3：催化剂已兑现** | 业绩预告已出/解禁已完成/合同已公告/政策已落地，催化剂已完全price in | search_news 查事件时间线 |
| **B4：第一性原则违约** | 需求不确定性上升/定价权丧失（毛利率下降）/利润质量恶化（ROE下滑/现金流转负） | query_data + wencai_search 查财务 |

**执行规则**：
- 轨道B任一条件成立 → 直接卖出，不等轨道A止损位
- 轨道B全部不成立且轨道A未触发 → 持有不动（即使短期浮亏）
- 趋势票（主升浪中）即使轨道B也不轻易触发（B4除外），但必须在心中明确"这个票的供需逻辑是什么"

**典型误判修复**：
- 海光/中芯例：轨道B全部不成立（半导体供需缺口依然巨大+紫苏叶五因子全满），但按轨道A波段票止盈价卖出了 → **错误。趋势票应选轨道B为主轨道，轨道A仅作极端行情保护。正确做法：轨道B不触发就不卖。**

### 持仓三分类 & 卖出纪律

| 分类 | 判定标准 | 主轨道 | 卖出纪律 |
|------|---------|--------|---------|
| **趋势票** | 主升浪+板块共振top5+K线上升通道 | **轨道B优先** | 供需逻辑没破不卖，上升通道不设硬止损，卖点看形态破位/顶背离 |
| **波段票** | 明确催化剂（解禁/财报），非主升浪 | 双轨并行 | 硬止损 -6%~-15% + 到期强制离场，同时检查轨道B是否提前触发 |
| **事件票** | 消息驱动，无基本面/技术面 | **轨道B为主** | 消息兑现即走（B3催化剂兑现即卖），持仓≤2天 |

**典型案例**：
- 海光/中芯 → 趋势票（半导体主升浪+供需缺口持续）→ 主轨道B，不应按波段票止盈价卖出
- 荣昌 → 波段票（7/1 解禁 34.16%）→ 双轨并行，轨道B3催化剂兑现（解禁完成）+ 轨道A硬止损
- 纳科诺尔920522 → 事件票（合同公告）→ B3催化剂兑现即走，不等轨道A

### 买入时必须锚定的供需逻辑（写入 TradeIntent.thesis）

每只标的在研究员输出 TradeIntent 时，必须在 `thesis` 字段中强制包含供需逻辑锚定，供卖出时回溯检查：

```
格式：thesis 中必须包含 [缺口逻辑] 标签
示例：
"thesis": "[缺口逻辑] 锑价因出口管制供给受限，全球光伏需求增长20%拉动阻燃剂需求，供需缺口预计持续12-18个月。紫苏叶五因子：✅供需缺口 ✅壁垒(配额管制) ✅锁定(长期合同) ⚠️关注度(低) ✅业绩(量价齐升)"

卖出时检查：这个逻辑还在不在？锑配额是否放松？全球光伏需求是否下滑？
```

**如果不确定买入时的逻辑，先查推测日志中TradeIntent的归档记录（`~/.hermes/trading/intents/`），找到原始 thesis，再判断是否该卖。**

---

## 🔴 重要：本 skill 不适合直接加载到 cron job

> **2026-08-05 教训**：收盘复盘 cron job 加载了本 skill（1096+行规则文本），结果 agent 只输出了全部的规则内容，完全没有执行任何数据分析。用户评价\"一点用没有\"。

**根因**：本 skill 是纯参考型文档（1096+行包含：选股铁律、K线卖出规则、MCP工具映射、职责隔离、数据契约、风控硬规则——全是给**人脑/交互式 agent**查阅用的）。当 cron job 加载它时，agent 被巨量规则文本淹没，推理能力被压制到只剩"把规则转述出来"的层次。

**解决方案**：
1. **cron job 不要加载本 skill**。cron 的 prompt 应该完全自包含：只写要执行的数据步骤+飞书输出格式，不引用任何 skill。
2. 如果需要参考本 skill 中的某个规则（如风控硬规则），直接在 prompt 中嵌入该规则的一两句话（不超过50字），不要加载全量。
3. 已有 cron job 的 `skills` 列表应清空为 `[]`，或只加载执行型 skill（如 `a-stock-trading-orchestrator`）。加载本 skill = 大概率变成只输规则不做分析。

**判断标准**：cron prompt 第一行如果加载了本 skill，大概率输出全是规则。改为自包含 prompt 后，输出变回真正分析。两条路线的差别极大，选错版本 cron 就白跑。

---

## ⛔ 飞书输出铁律（v5 — cron/pipeline 用此版本）

> **2026-08-05 升级**：从旧版\"≤1800 字+写文件\"改为极简 v5。用户反馈的核心矛盾不是长度，而是**飞书塞了太多无用信息**。用户只想要操作指令，不要报告。

**飞书 = 交易指令通道，不是报告通道。** 违反此规则 = 用户收不到有效信息 = 任务白跑。

### 强制规则（所有 cron job / 交易输出必须遵守）

1. **飞书消息最多3行**，格式统一：
   ```
   [emoji 窗口] | 大盘XXXX +/-X% | 账户XXXX
   BUY/SELL 股票名 代码 方向 单价 手数 | 止损XX
   （无操作写"无信号"/"空仓无事"）
   ```

2. **有操作才写第2行**。没操作 = 1行搞定，不超过50字。

3. **完整报告写文件**（如需），飞书不需要提文件路径。

4. **不输出**：大盘分析、板块分析、浪型判定、情绪描述。这些都在文件里，用户需要会追问。

5. **空信号 = 最简**：空仓写"空仓无事"，无买点写"无信号"。

### 典型错误（禁止）
| 错误写法 | 正确写法 |
|---------|---------|
| "今日上证指数收于3878.43点，涨幅1.47%，成交量略有放大..." | 📊 收盘 | 上证3878 +1.47% | 持有 |
| "建议关注紫金矿业，当前价格34.10，趋势良好..." | BUY 紫金矿业 601899 34.10 5手 止损33.0 |
| 写出K线数据/浪型图/板块排名 | 那些写文件

---

## ⛔ 拒绝时间维度错误（2026-06-24 铁律）

> **多次教训**：agent 在盘中说"今日收盘总结"、"昨日大盘"、"明天开盘"等时间错乱表述，严重误导用户。

1. **所有时间描述必须在返回前自检**：现在几点 → 交易时段是什么 → 对应正确说法
2. **盘中 = 盘中**，不要说"收盘后"、"明天开盘"、"今天已经��盘了"
3. **无法判断当前时段时**，必须调用 `mcp_intel_trading_sessions` 先确认
4. **数据来源标注当前时间**：每条数据必须标注 `query_data: 2026-06-24 14:23` 等时间戳
5. **禁止预判未来行情**：盘中不能报"今日收盘价"，盘前不能报"今日涨幅"

---

## 6. NewsLLMAnalyzer 依赖 OpenRouter Free Tier — 频繁 429/504 超时

### 问题描述

新闻情绪分析（`NewsLLMAnalyzer`）通过 OpenRouter free tier 调用 LLM，日志频繁出现：

```
API Error: 429 - "minimax/minimax-m2.5:free is temporarily rate-limited upstream"
API Error: 429 - "google/gemma-4-26b-a4b-it:free is temporarily rate-limited upstream"
API Error: 429 - "qwen/qwen3-next-80b-a3b-instruct:free is temporarily rate-limited upstream"
Unknown response format: {'error': {'message': 'The operation was aborted', 'code': 504}}
```

### 影响

- 新闻情绪分析可能静默失败，`sentiment` 字段为 null 或 fallback 到关键词匹配
- `fetch_hot_signals` 的新闻信号可能不完整
- 非阻塞性 — 新闻拉取本身不依赖 LLM 分析，只影响情绪标注质量

### 根因

1. `NEWS_LLM_MODEL=openrouter/free` 配置使用 OpenRouter 免费模型池，上游频繁限流
2. `.env` 中 `NEWS_LLM_URL` 和 `NEWS_LLM_KEY` 为空，使用默认值
3. 免费模型池没有稳定的 rate limit 保证

### 缓解方案

1. **短期**：在 `.env` 中设置 `NEWS_LLM_KEY` 为自有 OpenRouter API Key（BYOK 模式），绕��共享 free tier 限流
2. **中期**：配置 fallback 模型列表，当 free tier 429 时切换到付费模型
3. **长期**：评估本地运行小型情感分析模型（如 HuggingFace `IDEA-CCNL/Erlangshen-Reward-LLM-7b`）替代云端 LLM

### 配置位置

```
/home/ubuntu/pup-mcp/.env:
NEWS_LLM_URL=
NEWS_LLM_KEY=
NEWS_LLM_MODEL=openrouter/free
```

### 验证

```bash
# 检查最新日志中的 LLM 错误频率
grep -c "429\|504\|rate-limited" /home/ubuntu/pup-mcp/log/intel.log | tail -1
```

---

## 外围市场数据获取（wencai_search 查询模式）

### 问题

获取外围市场数据时，直接 HTTP 请求东方财富/sina 等 API 常被防火墙拦截或超时。wencai_search 是更可靠的数据源。

### 已验证的查询模式

```python
# 个股基本面（批量）
mcp_intel_wencai_search(query="股票代码1 股票名称1 股票代码2 股票名称2 最新价 涨跌幅 市盈率 市净率 成交额 换手率 总市值")

# 个股技术指标
mcp_intel_wencai_search(query="688082 成交量 换手率 均线")
# 返回: 成交量, 换手率, ma, 成交额, 振幅

# 个股详细数据（含前复权K线）
mcp_intel_wencai_search(query="688082 最新价 涨跌幅 市盈率 市净率 成交量 成交额")
# 返回列: 最新价, 最新涨跌幅, 收盘价:前复权, 涨跌幅:前复权, 市盈率(pe,ttm), 市净率, 成交量, 成交额, 开盘价_前复权, 最高价_前复权, 最低价_前复权, 涨跌:前复权, 总市值, 动态市盈率, 振幅, 换手率

# 板块涨幅排名
mcp_intel_wencai_search(query="A股 2026年5月28日 板块涨幅排名前十 涨跌幅 成交额")

# 美股三大指数
mcp_intel_wencai_search(query="道琼斯工业平均指数 纳斯达克指数 标普500 5月27日 涨跌幅")
# 返回: DJI.GI (道琼��), IXIC.GI (纳斯达克), SPX.GI (标普500)

# 欧洲 + 港股
mcp_intel_wencai_search(query="富时100 德国DAX 法国CAC40 日经225 恒生指数 5月27日 涨跌幅")
# 返回: UKX.FS, GDAXI.GI, FCHI.GI, HSI.HK

# A股大盘指数
mcp_intel_wencai_search(query="上证指数 创业板指 科创50 5月28日 最新价 涨跌幅")

# 板块内个股筛选
mcp_intel_wencai_search(query="半导体设备 个股 涨幅3到8 市盈率20到60 成交额大于5亿 总市值大于100亿 2026年5月28日")
```

### 注意

- 问财返回的日期是 A 股交易日的日期，美股数据是前一个交易日
- 日经225 有时返回不完整的 ETF 基准指数而非原始指数，需要过滤
- 查询时包含具体日期可提高准确率，但不强求

### query_data 返回数据过于精简

`query_data` 无论传 `type="quote"`、`"financial"` 还是 `"technical"`，都只返回 `{名称, 最新价, 涨跌幅}` 三个字段。

**替代方案**：用 `wencai_search` 获取完整数据（市盈率、市净率、成交额、换手率、均线等），参见"外围市场数据获取"章节的已验证查询模式。

### search_news 频繁超时

`search_news` 经常超过 60 秒超时，返回空结果。这是已知的 LLM 情绪分析瓶颈（见"NewsLLMAnalyzer"章节）。非阻塞——新闻拉取不影响行情数据获取。

### 外围市场数据：Yahoo Finance v8 API（Python 直连）

`wencai_search` 对美股/港股/外汇/大宗商品覆盖有限。以下 Python 方法可稳定获取美股实时数据：

```python
import urllib.request, json

headers = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'}

# 美股三大指数 + 关键数据
indices = {
    'S&P 500': '^GSPC', 'Nasdaq': '^IXIC', 'Dow Jones': '^DJI',
    'VIX': '^VIX', '10Y Treasury': '^TNX', 'BTC': 'BTC-USD',
}
for name, sym in indices.items():
    url = f'https://query2.finance.yahoo.com/v8/finance/chart/{sym}?range=1mo&interval=1d'
    req = urllib.request.Request(url, headers=headers)
    resp = urllib.request.urlopen(req, timeout=10)
    data = json.loads(resp.read())
    result = data.get('chart',{}).get('result',[{}])[0]
    meta = result.get('meta',{})
    closes = result.get('indicators',{}).get('quote',[{}])[0].get('close',[])
    cur = meta.get('regularMarketPrice', 0)
    prev = meta.get('chartPreviousClose', 0)
    chg = round((cur - prev)/prev * 100, 2) if prev else 0

# 个股（美股代码直接传）
# 'NVDA', 'AAPL', 'MSFT', 'TSLA', 'AMD', 'AMZN', 'GOOGL', 'META'

# 板块ETF（美股板块轮动必看）
# 'XLK'(科技), 'XLF'(金融), 'XLY'(消费), 'SOXX'(半导体),
# 'SPY'(标普ETF), 'QQQ'(纳斯达克ETF), 'DIA'(道指ETF)
```

**可用参数**：`range=1d/5d/1mo/3mo/6mo/1y/5mx/y`，`interval=1m/5m/15m/30m/60m/1d`

**Pitfall**：Yahoo Finance 对北交所（.BJ）和部分期货代码不支持 404。美股个股和指数最可靠。

## 9. `mcp_intel_fetch_kline` — 方法存在但未注册到 MCP（已修复）

### 问题描述

`intel_server/main.py` 中有 `fetch_kline(symbol, period, count)` 方法（支持 30/60 分钟线），但该方法**未注册到 MCP 工具列表**（`tools/list`）也未加路由分发（`tools/call`），导致完全不可调用。

### 修复（2026-06-06）

1. 在 `tools/list` 响应中添加 `fetch_kline` 工具描述（含 `period` enum: 1/5/15/30/60）
2. 在 `tools/call` 路由中添加 `elif name == "fetch_kline"` 分发

### Pitfall — 新方法写了但忘注册

MCP 工具需要在**两处**同时注册才可调用：
1. `tools/list` 响应中的工具描述 JSON
2. `tools/call` 路由中的 `elif name ==` 分发

写完方法后必须检查这两处，否则方法就是死代码。

---

## 10. 东财 `push2his.eastmoney.com` K线 API 海外 IP 被封

### 问题描述

`fetch_kline` 依赖 `http://push2his.eastmoney.com/api/qt/stock/kline/get`，但从本服务器（海外 IP）调用时返回 **Empty reply from server**（curl exit code 52）。HTTP 和 HTTPS 均不可用。

### 根因

东财对海外 IP 做了回源防火墙限制，K线历史数据 API 直连被拒。

### 替代方案

| 方案 | 可靠度 | 备注 |
|------|--------|------|
| `wencai_search` | ✅ 高 | 能返回均线、振幅、成交量等衍生指标，够做 MA/多头排列判断 |
| `akshare` Python 库 | ✅ 高 | 有免费分钟线接口，需 `pip install akshare` |
| `tushare` Pro | 中 | 分钟线需 Pro 积分 |
| 新浪/腾讯 HTTP API | 中 | 可能也有 IP 限制 |

### 建议

如果只需要**均线粘合/多头排列/金叉死叉**判断 → 用 `wencai_search` 即可。
如果需要**原始 OHLCV K线数据** → 安装 `akshare` 作为数据源替代。

## Overview

本 skill 定义 A 股交易系统的全局规则，包括职责隔离、数据契约、风控硬规则和执行约束。所有交易相关的 skill 和 cron 任务都应遵守这些规则。

## When to Use

- 需要查阅交易系统的规则框架时
- 配置或修改交易相关 skill 时
- 检查某项操作是否符合风控规则时

### 🔴 低位起爆候选过滤规则（2026-09-11 渝三峡A案例强制新增）

> **案例**：9/10 渝三峡A(000565) 2连板，属于基础化工板块唯一涨停标的（光杆2板）。`select_actionable_recommendations()` 将其选入"低位起爆"候选槽，9/11 开盘跳水 -9.86%。根因：函数选低位起爆时 streak 降序排列，2板自然排首板前面，但没有过滤光杆2板。

**三条强制过滤规则（修改 `select_actionable_recommendations` 和 `premarket_plan_compiler` 时执行）：**

1. **2板标的禁止进入"低位起爆"槽**：2板已属中位，不是低位。低位起爆槽只允许 streak=1 的首板种子。2板标的即使要推荐，也应归入"次强先锋"分类，且必须经过板块梯队验证。

2. **光杆板块标的强制过滤**：若一个板块在当日连板梯田中只有1只涨停标的（无同题材首板/2板助攻），即使它只有1板或2板，系统也不应推荐。孤军作战的标的接力风险极大，无板块合力支撑。

3. **低位候选优先级排序**：`low_cands` 筛选应按以下顺序：
   - 先取 streak=1 且有板块协同的标的（所在板块当日涨停数 ≥ 2）
   - 再取 streak=1 的独苗首板（谨慎观望，标记 `low_confidence`）
   - 最后才考虑 streak=2 且有强梯队的标的（板块涨停数 ≥ 3）
   - streak=2 的光杆司令 → 直接过滤，不进入任何推荐槽

**盘中动态修正**：如果2板标的次日竞价低开 -3% 以下或竞价量异常萎缩，当天该系统标的必须从候选池彻底移除，不允许输出任何相关推荐。

### 数据真实性铁律（最高优先级，不可违反）

> **2026-06-17 教训**：板块资金流向日报编造了"国产芯片编译系统突破"这条不存在的催化因素，严重误导后续分析。

1. **绝对禁止编造**：任何角色（研究员/策略员/风控员/执行员/复盘员）、所有 cron job、所有 subagent，都绝对禁止编造新闻、催化因素、公告、政策、数据、财报数字。
2. **新闻不足的诚实处理**：如果 `fetch_hot_signals` 或 `search_news` 返回空或数据不足，**必须写"无法确认催化因素"或"今日新闻信号不足"**，绝不可自己编造补充。
3. **每条催化必须标注来源**：引用的催化因素必须逐条对应实际工具调用返回的数据，并标注来源工具（如"wencai_search: XXX"或"search_news: XXX"）。无来源标注的催化 = 编造 = 违规。
4. **禁止总结式催化列表**：不要写"催化因素：A+B+C"这种概括式列表。改为逐条列出原始数据点，每条带来源。
5. **数据只报实际查到的**：不做推测性补充。查不到的数据就写"未查询到"，不可用一个近似值或猜测值代替。
6. **违规后果**：编造数据等同于绕过风控，是**最严重的系统违规**，与直接绕过风控下单同级。

## MCP 工具映射

交易系统使用 3 个 MCP Server，工具命名规则为 `mcp_{server}_{tool}`:

| MCP Server | 用途 | 工具前缀 |
|-----------|------|---------| 
| intel | 资讯行情选股自选日历 | mcp_intel_* |
| risk | 交易意图风控审批 | mcp_risk_* |
| exec | 账户持仓与委托下单 | mcp_exec_* |
| jin10 | 全球快讯/深度资讯/财经日历/外盘行情/A股备用 | 非MCP前缀，需用原生HTTP调用 |\n\n### jin10 工具清单（2026-06-24 验证，8/8可用）\n\n> 详见 `references/jin10-mcp-tools.md` 和 `references/market-data-tool-selection.md`\n\n- `get_quote`: 实时行情（✅ 支持A股代码 000001.SZ/600519.SH + 外盘 XAUUSD）\n- `get_kline`: 分钟K线（✅ 支持A股代码）\n- `list_flash`: 7x24快讯分页\n- `search_flash`: 快讯关键词搜索\n- `list_news`: 深度财经文章分页\n- `search_news`: 文章关键词搜索（\"A股\"→每日要闻，\"半导体\"→赛道分析）\n- `get_news`: 文章详情全文\n- `list_calendar`: 本周财经日历（192条/周）\n\n### intel 工具清单
- mcp_intel_search_news: 搜索财经新闻、研报、公告
- mcp_intel_query_data: 查询行情、财务、指标数据
- mcp_intel_screen_stocks: 按条件筛选股票
- mcp_intel_wencai_search: 自然语言选股分析（问财）
- mcp_intel_get_watchlist: 查询自选股列表
- mcp_intel_update_watchlist: 更新自选股列表（增删标的）
- mcp_intel_is_trading_day: 判断是否交易日
- mcp_intel_trading_sessions: 获取当前交易时段
- `mcp_intel_fetch_kline`: 获取K线数据（period: 1/5/15/30/60，⚠️ 东财API海外IP被封，分钟级数据依赖腾讯备用源）
  - **🔴 艾略特波浪分析必须拉100根K线**（count=100），只拉20根会漏掉关键浪型结构。例：浪潮信息7/17→8/4从85跌到69，只看最近20根会误判为"底部反弹"，拉100根才能看到7/22的95.5巨量顶部出货结构。
- mcp_intel_fetch_hot_signals: 获取热门信号/涨停信号
- `mcp_intel_fetch_market_health`: 大盘健康度评分 + 指数快照。⚠️ `top_inflows`/`top_outflows` 字段经常为空/延迟（\"数据源同步中\"），不可依赖板块资金流向。查大盘资金流向用 `mcp_intel_wencai_search`。
- `mcp_intel_fetch_sector_history`: 板块历史数据（⚠️ code参数对CPO/PCB/MLCC等返回error，用wencai_search替代）
- `mcp_intel_wencai_search`: 自然语言选股。**大盘资金流向标准查询**：`"今日A股全市场资金流向 大盘主力资金 2026年6月"` + `"上证指数 深证成指 今日 资金净流入"`
- mcp_intel_query_batch_data: 批量行情查询（传 symbols 数组）
- mcp_intel_get_watchlist: 查询自选股列表（读取 ~/.hermes/trading/watchlist.json）
- mcp_intel_update_watchlist: 更新自选股列表（增删标的）

### risk 工具清单
- mcp_risk_check_intent: 对单个 TradeIntent 执行风控检查
- mcp_risk_batch_check: 批量风控检查
- mcp_risk_get_blacklist: 获取不可交易标的黑名单
- mcp_risk_daily_pnl: 获取当日累计盈亏快照

### exec 工具清单
- mcp_exec_place_order: 提交买入/卖出委托（**必须提供 intent_id**）
- mcp_exec_register_approved_intent: 注册已审批 intent（仅 risk_server 内部调用）
- mcp_exec_cancel_order: 撤销未成交委托
- mcp_exec_get_orders: 查询今日委托
- mcp_exec_get_balance: 查询账户资金
- mcp_exec_get_positions: 查询当前持仓
- mcp_exec_get_today_trades: 查询今日成交
- mcp_exec_get_pnl: 查询盈亏统计
- mcp_exec_sync_position: 同步持仓（自动扣减现金）
- mcp_exec_top_up_cash: 调整账户现金（注入资金）
- mcp_exec_eod_settlement: 日终清算

### MCP API 调用格式（必须）

**正确格式**：POST 到 `/mcp` 端点，JSON-RPC 2.0

```bash
# 错误（404��
curl http://localhost:9001/mcp-method ...

# 正确
curl -s http://localhost:9001/mcp -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/call","id":1,"params":{"name":"query_data","arguments":{"symbol":"688082","market":"SH","type":"quote"}}}'
```

**响应解析**：
```python
response = json.loads(result['output'])
content = json.loads(response['result']['content'][0]['text'])
# content 才是实际数据
```

### MCP 工具数据特征（关键避坑）

- **`mcp_exec_get_positions` 返回的是纯代码名称**（如 `603738.SH`），不是股票简称。展示给用户前必须用 `mcp_intel_query_batch_data` 或 `mcp_intel_query_data` 查询真实名称。**严禁根据代码猜测股票名称**——即使你"觉得"是某只股，也必须查确认。猜错会严重误导交易决策。（2026-06-17 教训：把 603738 错标为江丰电子、600176 错标为中天科技，实际是泰晶科技和中国巨石）
- **`mcp_intel_query_data` 只返回3个字段**（名称、最新价、涨跌幅）。需要完整数据（PE/PB/成交额/换手率）时用 `mcp_intel_wencai_search`
- **`mcp_intel_query_batch_data`** 是批量获取名称+价格+涨跌幅的最佳工具，传 symbols 数组即可
- **🔴 股票代码必须在下单前通过 wencai_search 核实**：绝对禁止凭记忆输入股票代码。每次收到用户口头报出股票名称时，先调用 `mcp_intel_wencai_search(query="股票名 股票代码")` 获取准确代码再下单。不核实直接下单 = 编造数据 = 违规。（2026-06-17 教训：纳科诺尔实际代码 920522.BJ 被我编成 001377.SZ，铁拓机械实际 920706.BJ 被我编成 300734.SZ，导致两笔错误委托，需手动取消后重新下单）
- **北交所股票代码格式**：北交所股票代码以 `9` 开头，后缀为 `.BJ`（如 920522.BJ），不是 `.SZ`。K线数据拉取时部分接口不支持 .BJ 后缀（报 Empty reply），此时改用不带后缀的代码或用 wencai_search 替代
- **交易日期验证**：在声称"今天是周末/非交易日"前，必须调用 `mcp_intel_is_trading_day` 或 `mcp_intel_trading_sessions` 验证。不可凭记忆判断。（2026-06-17 教训：6/17 是周三正常交易日，我错误地说是"周末"）

### T+1 可用股数检查（关键）

卖出前必须检查 `available_shares`，不能只看 `quantity`：

```
positions 查询返回字段:
- quantity: 总持仓
- available_shares: 今日可卖出（已T+1）

错误: 卖出 1000 股，实际 available=700 → 报错 "Insufficient available shares"
正确: 先查 available_shares，卖出的数量不能超过此值
```

### 非交易时段委托状态

- 非交易时段（9:30-11:30, 13:00-15:00 之外）提交委托，状态为 **PENDING**
- 下一交易日 9:30 自动进入交易所撮合
- 需在 `get_orders` 中查看状态是否为 FILLED/PENDING

## 职责隔离（不可违反）

| 角色 | 可访问 | 禁止访问 |
|------|--------|---------| 
| 研究员 (researcher) | intel 全部 | risk 全部, exec 全部 |
| 策略员 (strategist) | intel (query_data, screen_stocks, is_trading_day, trading_sessions, wencai_search) | risk 全部, exec 全部, intel search_news |
| 风控员 (risk_officer) | risk 全部, exec 只读 (get_balance, get_positions, get_today_trades, get_pnl) | intel 全部, exec place_order/cancel_order |
| 执行员 (executor) | exec 全部 | intel 全部, risk 全部 |
| 复盘员 (reviewer) | intel (query_data, search_news, is_trading_day), exec 只读 | risk 全部, exec place_order/cancel_order |

关键约束：
- 研究员不可直接下单，执行员不可自行决定买什么
- approval_status 只能由风控员设置，其他角色不可修改

## 数据契约 — TradeIntent JSON

所有角色之间传递交易意图必须使用 TradeIntent JSON 格式：

```json
{
  "symbol": "600519",
  "market": "SSE",
  "thesis": "[缺口逻辑] 稀缺供给驱动，茅台酒由5年基酒+地理限制决定产能上限，高端白酒需求刚性强（政务+商务+收藏），供需缺口长期存在。紫苏叶：✅供需缺口 ✅壁垒(地理+品牌) ✅锁定(渠道+消费习惯) ⚠️关注度(高但可接受) ✅业绩",
  "direction": "buy",
  "confidence": 0.8,
  "catalyst_type": "technical_breakout",
  "entry_rule": {
    "initial_entry": "价格回调至 1650 元附近首次建仓",
    "initial_position_pct": 0.05,
    "add_on_trigger": "收盘站稳 1700 元上方加仓至 max",
    "add_on_position_pct": 0.05
  },
  "exit_rule": {
    "stop_loss": "跌破 1620 元无条件全平",
    "target_profit": "触及 1800 元减半仓",
    "trailing_stop": "目标价后跌破 10 日均线全清"
  },
  "max_position_pct": 0.10,
  "time_horizon": "5d",
  "valid_until": "2026-04-05T15:00:00+08:00",
  "risk_notes": "风险提示",
  "tool_evidence": ["来源工具调用的关键证据摘要"],
  "market_condition": "BULL",
  "approval_status": "pending"
}
```

### catalyst_type 枚举及持仓规则

| catalyst_type | 含义 | valid_until 上限 | 止盈逻辑 |
|---------------|------|-----------------|---------|
| news_event | 消息/公告驱动 | 2 个交易日 | 消息淡化立刻出，不等目标价 |
| technical_breakout | 量价突破/形态 | 10 个交易日 | 用均线动态追踪止盈 |
| sector_rotation | 板块轮动 | 3 个交易日 | 板块热度退潮立刻减仓 |
| earnings | 业绩驱动 | 5 个交易日 | 业绩期前后各留1天缓冲 |

### market_condition 枚举及仓位系数

| market_condition | 判断标准 | max_position_pct 系数 |
|-----------------|---------|----------------------|
| BULL | 指数站稳 20 日线且北向净流入 | ×1.0（不限制）|
| NEUTRAL | 指数在 20 日线附近震荡 | ×0.7 |
| BEAR | 指数跌破 20 日线且成交萎缩 | ×0.5 |

必填字段: symbol, market, direction, catalyst_type
策略员填写: entry_rule, exit_rule, max_position_pct, market_condition
风控后增加字段: approval_status, rejection_reason, risk_flags, adjusted_position_pct

## 全局 confidence 阈值规则

- 研究员输出：confidence < 0.65 不输出
- 策略员过滤：confidence < 0.65 过滤（与研究员统一，消除灰色地带）
- BEAR 市场环境下：所有 intent confidence 强制 -0.2（计算后低于 0.65 则过滤）
- **🔴 sector_rotation 强制降权**：该 catalyst_type 历史胜率持续低于 25%（strategy-feedback.md 归档验证），confidence 强制 -0.1，且 max_position_pct 上限降至 0.05。如果降权后 confidence < 0.65 则直接过滤。
- **🔴 行业分散度硬约束**：同一次 pipeline 中，同一行业最多输出 2 只候选标的。如果 3+ 只同行业标的通过筛选，只保留 confidence 最高的 2 只。

## 🚨 AGY股神审计关键缺陷（2026-09-07 全系统策略审计）

### 致命缺陷1：撒胡椒面式分仓杀死复利
**现状**：系统配置 `max_single_position_pct: 0.08`（单票8%）+ 无上限持仓数量。实测持仓16只个股，每只几万元甚至200股。这是基金经理的指数增强思路，不是游资龙头打法。

**实战修正**：
- 全市场持仓上限强制收敛至 **3只**（退潮期可空仓或10%试错）
- 核心灵魂标的基准仓位提升至 **25%~35%**
- 单票8%规则废除，改为：主升期满仓3只、退潮期空仓或10%试错
- 资金利用效率目标：龙头票给账户净值带来真实拉升（不是+60% × 8%仓位 = 只贡献+4.8%）

**游资原理**：分仓=认输，重仓=合力。赵老哥\"八年一万倍\"靠核心标的半仓甚至满仓单吊。

### 致命缺陷2：T+1炸板保护全生命周期0防御
**根因**：当天买入被炸（T日），`explode_monitor`检查`actual_qty==0`（今日买入不可卖）直接跳过。次日T+1，系统规则\"只监控今日曾触及涨停的标的\"，标的低开根本不会触及涨停，再次跳过。

**结果**：天地板买入日无法卖→次日低开系统不监控→-3%拖到-12%+。整套炸板保护在实战中零作用。

**强制修正**：
1. 次日监测规则改为：**前日收盘曾触及涨停+今日开盘跌幅＞-2.5% → 自动以跌停价挂市价单核按钮**
2. `explode_monitor`应检查前一日`symbols_touched_limit`数据
3. 炸板标的次日竞价核按钮逻辑见 `a-stock-trading-orchestrator` 优先级Top1
4. **⚠️ AGY R1审计关键修复（2026-09-07）**：竞价核按钮脚本必须遵守以下5条防误杀铁律——
   - 炸板标的按今日竞价方向分叉处理：低开>1%核按钮，高开/平开留仓观察弱转强
   - 竞价量为0是数据延迟不是无量 — 直接跳过该标的，避免误判
   - price=-1 在exec_server合法传入被拒 — 必须传原子对照表合规跌停价
   - 串行MCP调用会耗尽09:25之后的5分钟天窗 — 用 query_batch_data 批量获取
   - 时间守卫硬锁：仅允许 09:25:05~09:29:50 + 交易日验证
### 致命缺陷3：伪弱转强导致打板胜率0%

**根因**：`call_auction_scanner` 判定"昨日涨停+今日竞价高开2%~7.5%"=弱转强。但实战中：昨天缩量一字板今天竞价只开+2.5%叫**强转弱**；昨天烂板炸板5次换手翻倍今天超预期高开+4%爆量才叫真正弱转强。

**实际结果**：经验贝叶斯系统记录 `1to2_weak_to_strong` 样本7次、胜率**0.0%**（全亏），已被系统自动冷却。实战已证明这套逻辑完全错误。

**修正算法（v1 理论版）**：
- 前置条件：昨日必须是烂板（炸板≥2次 或 尾盘14:30后封板 或 换手率超历史均值80%）
- 量价比门禁：今日竞价金额 ≥ 昨日全天成交额 × 10%
- 竞价涨幅：+3%~+6%（排除了+2%的不及预期和+7.5%+的过度一致）
- 预期效果：打板胜率从0%→55%~60%

### ✅ 实际实施：弱转强v2（commit 618a2ee, 2026-09-07）

v1 **保留不动**作为可信基线。v2 并行运行作为补充扩展，两路候选互不干扰。

**v2 相对 v1 的 7 项改进**：

| # | 改进 | v1 行为 | v2 行为 |
|---|---|:---|:---|
| 1 | 竞价范围 | 2.0%~7.5% | **1.5%~7.5%**（放宽 + 质量过滤兜底）|
| 2 | 竞价抢筹质量 | 无条件通过 | **L1五因子评分**（涨幅0.3+量比0.25+行业排名0.2+封单强度0.15+额外0.1），<4分标记weak跳过 |
| 3 | 2进3同等对待 | 绕过AlphaBot评分 | **统一评分链路**，与1进2走相同scoring |
| 4 | 放量/缩量区分 | 统一条件 | 缩量(<20%换手)正常条件；**放量(≥20%)要求更严**：高开>3%+量比≥10% |
| 5 | 5分钟K线趋势 | 无 | **get_trend_acceleration_l1**：slope>0才准买入 |
| 6 | 板块持仓保护 | 无 | 中低位(<3板)同板块已有持仓则直接跳过 |
| 7 | 炸板过滤 | ≥2次直接跳过 | ≥2次+换手<15%才跳过（允许放量烂板通过） |

**评分阈值的双轨退化**（2026-09-07 修复前 R3 误判）：
- 第一版 v2 将评分阈值设为 ≥6，导致量比≥10的高换手票也被一律关闭
- **修复后的合理退化逻辑**：quality<4 直接跳过（五因子综合劣质），quality=4~5 触发二次确认（允许通过但打分偏低），quality≥6 自动通过
- 核心原则：quality 阈值应当下放面而不是收紧——v2 的本意是"拓势捕获优质弱转强"，不是"比 v1 更挑剔"

**预期效果**：v1 0%胜率 → v1+v2 联合捕获更多候选，预期 30%~50% 胜率的弱转强信号（当前经验贝叶斯系统无足够样本）。

**实施文件**：
- `scripts/call_auction_scanner.py` — `scan_weak_to_strong_v2()` ~350行
- `scripts/l2_interface.py` — L2 接口骨架（5个函数）+ 当前用 L1 降级版
- `references/l2-interface-contract.md` — 完整 L2 接口合约与 L1 降级细节

### 致命缺陷4：无L2盘口 → 打板在黑暗中送人头
**现状**：封单硬度（`seal_ratio` 5%铁板）基于估算公式（封单金额靠amount推算、换手率靠市值推算），买一排单量看不到、主力撤单看不见。

**实战真相**：在A股打板，凡是你通过普通行情能买进的涨停板，都是主力撤单倒给你的面。真正封死的铁板你连车尾灯都看不见。

**修正方向**：
- 必须接入真实L2千档盘口数据
- 封单不足直接拒买（不做估算）

### 致命缺陷5：缠论与超短执行形成两座孤岛
**现状**：`chanlun_engine.py` 写了漂亮的分型/笔/中枢/背驰，但 `call_auction_scanner` 和 `limit_up_scanner` 中 `chan_confirmed` 全部为 `False`。缠论成了系统里的\"花瓶摆设\"——对超短打板和竞价策略零影响。

**修正原则**：超短抓的是秒级情绪共振，缠论算的是中周期几何中枢。两者使命不同，不应强行嫁接。打板/竞价策略直接使用量价+盘口数据，不依赖缠论买点。

### AGY 铁律大修：四道门禁框架（2026-09-08 继任AGY股神审计的第二轮AGY改造）

**背景**：2026-09-08 AGY第二轮回溯审计，直接检查了8笔自主操作的实际执行记录。结论：全部亏损的根本原因可以用一条可编码的铁律锁定。

**AGY的 is_order_forbidden_by_iron_rule 铁律（伪代码 → 已编码实现）**：

```python
def iron_rule_gate(candidate, now_cst):
    # 门禁0：卖单豁免（止盈止损神圣不可阻断）
    if direction == "sell": return True
    
    # 门禁1：策略熔断器 — strategy_circuit_breaker.py
    is_blocked, reason = check_strategy(catalyst_type)
    if is_blocked: return False
    
    # 门禁2：市场状态机 — market_regime.py
    regime = get_market_regime(output_only=True)
    regime_name = regime.get("regime", "震荡")
    ebb_subtype = regime.get("ebb_subtype", "")
    
    if regime_name == "极寒": return False  # 禁止一切开仓
    if regime_name == "退潮":
        ## 市场状态机增强（2026-09-15 AGY审计改进）

        ### 退潮三子类型

        > **审计前**：市场状态机只有"退潮"这一个大类，所有扫描器统一HALT熔断。审计指出：同一退潮期内的冰点衰竭与初退潮分歧应区分对待。

        由 `scripts/market_regime.py` 自动根据**炸板率**和**退潮持续天数**判定：

        | 子类型 | 触发条件 | 扫描器行为 | 仓位限制 |
        |-------|---------|-----------|---------|
        | **initial_ebb** (初退潮) | 第1-2天, 炸板率<45% | 所有扫描器HALT熔断 | 空仓/0% |
        | **panic_ebb** (恐慌杀跌) | 第2天+, 炸板率≥45% | 所有扫描器HALT熔断 | 空仓/0% |
        | **exhaustion_ebb** (衰竭冰点) | 第4天+, 炸板率<30% | TDX回踩扫描器允许迷你模式 | ≤10%首板迷你仓 |

        ### 数据字段

        - `market_regime.json` 新增 `ebb_subtype`（initial_ebb/panic_ebb/exhaustion_ebb）
        - `market_regime.json` 新增 `broken_seal_rate`（炸板率百分数，通过问财`涨停炸板家数` fallback）
        - `market_regime.json` 新增 `retreat_days`（连续退潮天数，链式递增）
        - `strategy_params.json` 新增 `redline_state.ebb_subtype`
        - `fetch_limitup_count()` 返回类型从 `int` 改为 `(int, float)` — **只有 self-call，无外部 callers 需要更新**

        ### 退潮天数计算

        从上一期 `market_regime.json` 的 `retreat_days` 字段递增（而非 datetime diff），
        链式规则：prev_regime=="退潮" → retreat_days = prev_retreat_days + 1
                    非退潮 → retreat_days = 1（首日退潮）
        优势：跨周末/非交易日时自动递增，不受日期差影响。

        ### 扫描器适配

        `tdx_pullback_scanner.py` 的 `scan_tdx_pullback_candidates()` 中：
        - initial_ebb / panic_ebb → `[HALT]`（严格熔断）
        - exhaustion_ebb → `[MINI]`（首板迷你仓模式，获利盘>40%放宽，非主线放行）
        - `generate_report()` 接收 `regime_data` 和 `is_exhaustion_ebb` 参数，输出子类型提示

        `market_regime_check.py` 的 `iron_rule_gate()` 中：
        - exhaustion_ebb → 直接 PASS（首板迷你仓免检）
        - initial_ebb / panic_ebb → 非龙头拦截，追高拦截

        所有其他直接读 `market_regime.json` 缓存的脚本自动兼容（忽略未知字段）。
        if ebb_subtype != "exhaustion_ebb":
            # initial_ebb / panic_ebb：严格HALT
            if not is_sector_leader: return False  # 非龙头禁止
            if target_change_pct >= 1.5: return False  # 龙头追涨禁止
        # exhaustion_ebb：允许首板迷你仓
    
    # 门禁3：龙头精选池 — leader_universe_filter.py
    # （退潮期和垃圾时间需要龙头身份验证）
    
    # 门禁4：垃圾时间拦截 — 10:00-14:30
    if 10:00 <= now <= 14:30:
        if not is_sector_leader: return False
        if target_change_pct >= 1.5: return False
    
    return True
```

**实盘检验**：如果这套规则在9/3-9/8运行，8笔亏损中：
- 鸣志电器(10:28)→垃圾时间+非龙头+追涨=阻断 ✅
- 旗天科技(10:26)→垃圾时间+非龙头+追涨=阻断 ✅
- 东信和平(10:28)→垃圾时间+非龙头+追涨=阻断 ✅
- 晶合集成(14:44)→退潮期非龙头=阻断 ✅
- 平潭发展(用户点名,身位唯一,龙头)=放行 ✅

**全部阻断，平潭放行。8笔亏损=0，平潭+17,200全部留在账户。**

**已部署文件**（commit 7e7976e）：
| 文件 | 路径 | 功能 |
|:----|:----|:----|
| market_regime.py | ~/.hermes/scripts/ | 市场状态机(四维:创业板/中位数/成交额/涨停) |
| strategy_circuit_breaker.py | ~/.hermes/scripts/ | 策略闭环熔断器(连败7天/重伤14天) |
| leader_universe_filter.py | ~/.hermes/scripts/ | 龙头精选池(身位唯一+8亿量+10日2板) |
| market_regime_check.py | ~/.hermes/scripts/ | 铁律总闸门(聚合四道门禁) |
| direct_executor.py | ~/.hermes/scripts/ | patch: 注入iron_rule_gate检查 |

**cron调度**：
- market_regime.py: 09:20/13:05/15:05（每交易日3次刷新）
- leader_universe_filter.py: 每30分钟盘中刷新
- strategy_circuit_breaker.py: 随direct_executor触发（无独立cron）

**数据文件**（gitignored，不提交）：
- ~/.hermes/trading/config/market_regime.json
- ~/.hermes/trading/config/leader_universe.json
- ~/.hermes/trading/strategy_circuit_breaker/breaker_state.json
- ~/.hermes/trading/strategy_circuit_breaker/trade_history.jsonl

**注意**：`leader_universe_filter.py`使用`get_limitup_ladder()`获取连板梯队，这意味着它只在交易日（盘后/盘中）有数据。龙头池为空≠市场无机会，只说明当前无满足三条件的身位标的。

### 分市场熔断：窄基不得一票否决全市场

- 上证、深证、创业板等宽基指数跌超阈值，可结合跌停数、炸板率触发全局熔断。
- 科创50等窄基/风格指数单独跌超阈值时，必须先检查宽基与市场广度；若宽基平稳、跌停与炸板未恶化，只隔离对应市场，禁止写入全局 `sell_only_mode=true`。
- 候选闸门必须识别证券市场类型：科创板候选被分市场阻断，其他市场继续走正常门禁。
- 若旧逻辑已经写入错误全局熔断，只允许在旧原因明确指向该窄基指数时自愈，并保留其他题材隔离、黑名单和红线。
- 详细判定矩阵、状态字段与测试要求见 `references/segmented-market-circuit-breakers.md`。

### 致命缺陷6：情绪红线假自愈陷阱
**现状**：`sentiment_redline_monitor`判定空间龙炸板后回落不超过4%且过30分钟=自愈（恢复全盘买入）。

**实战陷阱**：A股退潮期最经典的杀人走势就是\"早盘炸板弱势横盘假企稳→午后14:00闪崩跌停\"。10:30判定自愈大举进场买入，正好给主力午后砸盘当接盘侠。

**修正**：真正的情绪修复必须看到**龙头放量回封铁板且无大单抛压**，不能只看横盘不跌就当企稳。

---

## 🔴 买入标的连板数物理拦截铁律（2026-09-14 AGY审计强制执行）

> **2026-09-14 AGY审计发现**：盘前预案推荐闽东电力(000993)3进4，iron_rule_gate无streak≥3的物理拦截，导致违反用户铁律"≥3板不参与买入"。同时盘中天梯推大盘中军(三环集团126.71元/世运电路42.78元)混入连板天梯报告，评分公式成交额权重过高造成数据错位。

### 铁规1：买入标的streak≥3直接熔断

所有买入候选在生成时和通过iron_rule_gate之前，必须执行以下物理拦截：

```python
# 必须在 iron_rule_gate() 中新增的门禁5
streak = int(candidate.get("streak", 0) or 0)
if direction == "buy" and streak >= 3:
    return False, f"铁律熔断 [用户铁律]: 标的连板({streak}板)>=3板，绝对禁止买入！"
```

**覆盖范围**：
- `iron_rule_gate()` 作为最后一道防线的物理拦截
- 所有候选生成脚本（call_auction_scanner/theme_trigger/top_zt_scanner等）的入选逻辑中，也应前置过滤streak≥3的买入候选
- streak=2的光杆司令（同板块无≥2家涨停助攻）也禁止进入低位起爆槽

### 铁规2：盘中连板天梯数据源与评分公式

**数据源**：盘中天梯报告(10:15/14:15)必须统一读取 `ladder_enhanced_YYYY-MM-DD.json`，第一屏强制展示全市场最高空间龙。不能因为行业资金流入排序低就把7板/5板标的信息丢出天梯。

**评分公式**：废除 `成交额×10 + 涨幅×5` 的盲目权重评分。游资天梯排序改为：
```
Score = Streak×30 + 封单强度×25 + 首封时间×25 + 换手健康度×20
```

**股价过滤**：股价 > 50元的大盘趋势股从连板天梯推荐中剔除。若要推荐大盘中军，必须另起"中军观察"专刊，严禁混入"连板天梯"标题下。

### 铁规3：动态移动止盈（高浮盈持仓保护）

当持仓浮盈>10%时，禁止使用静态成本止盈线。动态止盈规则：
- 浮盈5%~10%：止盈线锚定 `成本×1.03`
- 浮盈>10%：止盈线锁定为 `max(前日收盘×0.98, 今日最高×0.95)`，盘中自动上移

### 铁规4：贝叶斯冷却解冻 + 影子候选跟踪

当所有策略大类被贝叶斯冷却（strategy_circuit_breaker休眠）时：
- 开启"影子候选跟踪(Shadow Tracking)"：被冷却策略继续在后台虚拟撮合与复盘打分
- 影子样本连续3笔获得正期望（胜率>50%且盈亏比>2:1）→ 自动解冻该策略大类
- 防止系统陷入"无有效策略→零执行→贝叶斯无正反馈"的休克闭环

## 风控硬规则（risk MCP 服务端强制执行）

1. T+1: 当日买入标的不可当日卖出；当日卖出也不可当日买入；同日禁止任何方向的重复交易
2. 涨停不追买: 涨幅 >= 9.8%（ST 为 4.8%）
3. 跌停不抄底: 跌幅 <= -9.8%（ST 为 -4.8%）
4. ~~单票集中度已取消~~
5. 行业集中度: 单行业持仓不超过总资产 40%
6. 日亏熔断: 当日累计亏损超过总资产 3%，暂停所有新建仓交易
7. 日亏加速熔断: 当日累计亏损超过总资产 5%，不需用户确认直接执行已有减仓建议
8. 问题标的: ST / 停牌 / 退市风险标的禁止交易
9. 交易时段: 非交易时段（9:30-11:30, 13:00-15:00 之外）禁止下单
10. 集合竞价: 9:15-9:25, 14:57-15:00 仅允许限价单
11. 流动性（大盘股）: 近5日日均成交额 < 1000 万的标的禁止交易
12. 流动性（小盘股例外）: 市值 < 50 亿的标的，流动性门槛放宽至 500 万（弹性更大但需降低仓位上限至 10%）
13. 委托单位: 委托数量必须为 100 的整数倍（1手 = 100股）
14. valid_until 时效: TradeIntent 超过 valid_until 且尚未入场的，自动失效不得执行
15. 半程失效: time_horizon 过去一半仍未成交首单的，confidence 降 0.1；降后低于 0.65 则自动失效

### 执行约束

- 🔴 **禁止绕过风控直接下单**：所有买入/卖出委托必须通过完整的 研究员→策略员→风控员→执行员 pipeline。绝对禁止直接调用 `mcp_exec_place_order` 而不经过 `mcp_risk_batch_check` 审批。违反此规则等于绕过所有风控硬规则，是**最严重的系统违规**。
- 🔴 **代码级强制执行（2026-06-05）**：exec_server 的 `place_order` 已改为强制要求 `intent_id` 参数。只有先通过 `mcp_risk_batch_check` 审批（自动注册到 exec_server `approved_intents` 表），执行员才能带合法 `intent_id` 下单。不传 intent_id 或传入未注册的 intent_id 都会被直接拒绝。详见 trading-infra-troubleshooting → `references/intent-approval-chain.md`。
- 🔴 **强制 TradeIntent 归档**：每次下单后必须将完整的 TradeIntent JSON（含 order_id、成交状态）归档到 `~/.hermes/trading/intents/intent_YYYYMMDD_{symbol}_{direction}.json`���这是审计追踪和复盘的硬性要求，无归档等同于违规操作。
- V0 阶段所有下单操作需主人确认后才可执行（日亏 5% 减仓除外）
- 禁止未经风控 approved 的 intent 进入执行环节
- 禁止执行员自动重试失败的委托
- 禁止任何角色修改风控员的 rejected 决定为 approved
- **同时存在多个委托源时**：盘中有 intraday cron 自动执行交易（基于每日 signal），与手动提交委托可能冲突。建议在调仓前先查询 `get_orders` 确认今日已有哪些委托。

### Cross-Script Direction Consistency (2026-08-31 铁律 — 三次迭代最终版)

**Problem:** Different monitoring cron scripts (e.g., `close_session_scan.py` vs `intraday_leader_monitor.py` vs `intraday_price_monitor.py`) may generate opposite-direction candidates for the same symbol on the same day. One script sees a breakout and generates "buy" while another sees a pullback and generates "sell." This makes the user see "为什么又买又卖同只股" — confusing and destructive.

**Root cause (two distinct problems):**

1. **System design flaw**: Independent Chan analysis without cross-awareness. Both side scripts can call `analyze_chanlun()` on the same 30-minute bars and legitimately reach different conclusions — one position-biased (find exits), one entry-biased (find entries). Neither checks the candidates JSONL for today's events from other scripts.

2. **Chan analysis ambiguity**: The same stock's structure can be decomposed differently depending on analyst bias. `close_session_scan.py` (position-holder → biased to find exits) sees 三卖; `intraday_leader_monitor.py` (entry finder → biased to find buys) sees 二买. The same 30-min bars yield opposite interpretations.

**Final fix (after 3 AGY audit iterations): Same-direction blocking, NOT opposite-direction blocking**

| Iteration | Logic | Why changed |
|:---|:---|:---|
| 1 | Opposite-direction blocking (buy blocks sell, sell blocks buy) | User complained — but missed the real issue |
| 2 | Opposite + fallback shadow indexing | Still didn't fix root cause |
| 3 (final) | **Same-direction blocking** (buy blocks buy, sell blocks sell) | T+1 truth: if you sell today, can't sell more. But buy-after-sell (做T纠错) and sell-after-buy (倒T纠错) are **legitimate** correction trades. Only same-direction repeats violate T+1. |

**⚠️ Corner case: buy-today → sell-today across day boundary (R27已验证)**

If you bought stock X yesterday (持仓), and a script generates a sell signal today — that's NOT a "又买又卖" conflict. It's a legitimate stop-loss. The conflict only exists when:
- Same-day buy AND same-day sell are both NEW signals generated today
- OR two scripts generate opposite signals for the same symbol on the same **new** generation

If the buy was from a previous day's candidate (已持仓), today's sell is the correct response to changed market conditions. The "又买又卖" complaint usually refers to **same-day dual signal generation**, not today-sell-yesterday-buy.

**Example from 2026-09-01:**
- 荣昌生物 was bought on 8/31 (candidate from previous session)
- AGY approved a sell candidate on 9/01 (缠论三卖 confirmed)
- User saw "buy AND sell 荣昌" and was confused
- **Reality**: Not a conflict — previous day's buy + today's sell = correct stop-loss chain

**Rules:**

1. **Same-direction blocking only**: `check_direction_conflict` blocks a second buy if a buy was already executed today (same for sell). Opposite directions (buy→sell or sell→buy) are **allowed** for T-trading corrections.
2. **Detection based on executed orders, not candidates**: Only `event=submitted` + `order.detail==executed` records trigger direction blocking. Unexecuted candidates don't block — they haven't consumed any T+1 quota.
3. **Cross-script visibility**: Each script must read the day's full JSONL before writing its own candidate to check for same-direction events from all scripts (via `utils_candidate.check_direction_conflict(force_refresh=True)`).
4. **LLM review bypass prevented**: No script may write candidates without `awaiting_llm_review: true`. Sell candidates must also go through LLM review. This prevents any script from bypassing the decision chain.
5. **Chan analysis honesty check**: When the user finds contradicting signals, don't just fix direction conflict detection. Also audit whether the Chan analysis itself is internally consistent. Same 30-min bars should not yield both 三卖 and 二买 for the same stock on the same day — this is a fundamental analysis quality issue.

**Implementation:** `utils_candidate.py` `check_direction_conflict()` uses same-direction blocking. See `a-stock-trading-orchestrator` → `references/cross-pipeline-direction-conflict.md` for full architecture, two-phase scan fix, and the `candidate_update` bypass known gap.

### 🔴 卖出候选被 is_trade_ready 误杀（2026-09-01 新增铁律）

> **现场重现（2026-09-01 盘中）**: 荣昌生物卖出候选(candidate_id=alert-688331.SH-sell-2026-09-01)被AGY二审批准，direct_executor反复跳过该候选，导出被`is_trade_ready()`拒绝。根因：`is_trade_ready()`第218行无条件检查`bool(candidate.get("entry_rule"))`，但卖出候选`entry_rule`为空字符串（卖出的入场规则无意义）。

**修复**: R27 `autonomous_trade_pipeline.py` 加入 `if direction == "buy"` 条件：
```python
bool(candidate.get("entry_rule")) if direction == "buy" else True,  # 卖出不需要entry_rule
```

但注意**所有`is_trade_ready`中对非卖入字段的硬性检查都可能误杀卖出候选**，包括：
- `entry_rule`: sell不需要
- `chan_buy_point`: sell不需要（用chan_sell_point替代）
- `volume_confirmed`: sell的确认标准不同
- `price > 0`: sell候选也可能有效

**检查规则**: 修改`is_trade_ready`或`is_llm_ready`时，必须同时检查sell分支。禁止新增全局必填字段而不考虑direction。

### 即时执行器（Direct Executor）模式

传统交易系统依赖固定闸门（如10:55、14:50定时触发），候选产生后等待闸门轮次才能执行，延迟高达45分钟。R25引入**direct_executor cron守护模式**：

- 每2分钟盘中轮询候选池，自动过滤AGY approved+未处理候选
- 分批风控：每次最多2笔（防风控接口阻塞导致全部瘫痪）
- 防重复机制：从candidate文件读取已执行event记录，ID去重
- 盘中时段：仅09:30-11:30 / 13:00-14:50
- 中文名补充：候选name为空时从query_batch_data自动补全

cron配置：`*/2 * * * 1-5 cd /home/ubuntu/.hermes/scripts && python3 direct_executor.py`

详见 `catch-dragon` 技能 `references/direct-executor-pattern.md`

### 盘中交易冲突处理

**场景**：用户手动提交卖出委托，但盘中 cron 已经在同一天执行了买卖操作

**处理流程**：
1. 先调用 `mcp_exec_get_orders` 查看今日所有委托（含 FILLED）
2. 检查 `mcp_exec_get_positions` 的 `available_shares` 字段（反映 T+1 规则）
3. 若 intraday bot 已卖出同一标的，手动委托会因"可用股数不足"被拒绝
4. 卖出数量必须 ≤ `available_shares`，不能只看 `quantity`

## Agent 交易建议管理规则

- **🔴 建议归属清晰**：当 agent 主动提出卖出/买入建议时，必须明确标注"这是 agent 的建议"而非默认表述。后续如需撤回或修改建议，同样要明确说明"我之前的卖出建议不成立，现在改为持有"，不可将建议归咎于用户。**严禁说"是你自己说的要卖/买"来推卸 agent 提出建议的责任。** 用户纠正时直接承认错误，不辩解。（2026-06-17 教训：agent 提出荣昌108卖出，用户撤回后 agent 错误归咎用户）
- **🔴 建议不随意翻转**：同一会话中对同一标的不应先建议卖、后建议买（或反之），除非有明确的新信息（如业绩预告、重大公告）。纯价格波动不构成翻转理由。如果确实需要修改建议，必须说明"新信息 X 改变了判断"。
- **止损线调整需用户确认**：agent 主动调整止损线（如从108改到103）属于重大操作变更，应先征求用户意见，而非单方面宣布。

## 执行闭环规则

- **🔴 下单执行必须闭环**：当用户明确要求买入/卖出时，agent 不能只做到"注册意图+风控审批+设盯盘"就停下，必须完成�� `mcp_exec_place_order` 的完整下单。只设监控不执行 = 失职。（2026-06-17 教训：南大63.3买点开盘就出现，但 agent 只设了盯盘 cron 没下单，错过最佳买点）
- **🔴 卖出前检查持仓**：执行卖出委托前，必须先调用 `mcp_exec_get_positions` 确认 exec 系统中有持仓记录。如果系统显示 `available=0` 但用户口头报有持仓，说明是 **exec 持仓未同步**（常见于周末/非交易日无法同步），应直接告知用户去券商端手动卖出，不要把错误归咎于用户。（2026-06-17 教训：4笔卖出全部报 "Insufficient shares" 因之前周末风控拒绝导致持仓未同步）
- **🔴 不追高**：当目标标的已显著高于原计划买入价（>3%），应拒绝追高，等回踩到合理区间再进。追高买入没有安全边际，不符合交易纪律。

## 用户交互规则

- **🔴 交易结果必须主动同步（2026-08-27 新增）**：每次执行买卖后，必须在飞书第一时间同步用户，格式：`{股票名}({代码}) 买入/卖出 {数量}股@{价格} 盈亏{+/-X}元`。用户需要知道模拟账户的操作以手动跟随。不要在用户追问后才汇报，执行后立刻主动推送。详见 `references/trade-reporting-format.md`。

- **🔴 用户要求"列出来哪些票买入卖出交易"时，必须输出完整买卖周期**：按股票分组，每只票的买入→卖出完整配对，计算每只票的已兑现盈亏。不可以在没有完整周期信息时只报当前持仓。这个报告格式在 `templates/trade-lifecycle-report.md`。

- **用户要求"不要问，直接给专业意见"时，跳过所有 clarify 确认环节，直接输出分析和操作指令**。由 agent 自行与风控 subagent 协商后给出确定性结论，不等待用户二次确认。
- **用户要求"自主交易/自主决策/自主自负盈亏/不需要我来确认"时，进入全自动模式**：所有买卖直接走完整 pipeline（研究员→策略员→风控员→执行员），不请示、不确认、不等待。首次启动自主交易模式时应声明数据源限制（海外 IP 实时行情延迟 1 天，详见 trading-infra-troubleshooting §22）。
- **持仓同步优先**: 当用户口头报出持仓（"我有 X 股 Y"），先用 `mcp_exec_sync_position` 将持仓写入模拟账户，然后基于真实持仓数据执行分析/风控/调仓，而不是口头计算。
- **用户说"更新持仓"=执行交易同步**: 当用户说"更新持仓：XXX"，意思是**在 MCP exec 中通过实际买卖委托完成持仓同步**，不是只更新记忆。流程：先 `get_positions` 确认当前持仓 → 对差异部分执行 `batch_check` → `register_approved_intent` → `place_order` 买卖。如果 `batch_check` 返回 `exec_registered: false`，先手动注册再下单（详见 a-stock-executor pitfall #13）。
- **价格校验**: 查询到股价后，若用户指出价格不对，立即用正确代码重新查询并修正所有计算。
- **多股对比分析格式**: 用户要求同时分析多只标的时，使用标准对比格式（单股分析 + 对比表 + ✅/⚠️/❌结论 + 行动钩子）。详见 `references/multi-stock-comparison-format.md`。

## 技能设计规范（Skill Design Standards）

本系统中所有交易 skill 遵循 Compound Engineering 方法论编写。设计参考见 `references/ce-skill-design-patterns.md`。核心原则摘要：

1. **结果脊柱优先**：每个 skill 开头四要素（产出物/消费者/完成条件/非明显意图）
2. **协议与判断分离**：硬规则保留为显式协议；指导性内容压缩或删除
3. **本地作用域**：限制量词紧挨被限制的动作，不放全局开头
4. **脚本优先**：数据密集型处理用 Python，模型只做判断不做算术
5. **沉淀闭环**：交易后结构化学习写入 `~/.hermes/trading/learnings/`

新增或修改 skill 时遵循这些原则。

## 支撑文件

- `templates/trade-intent.json` — TradeIntent JSON 标准模板（含字段注释），所有角色共用
- `references/cron-operations.md` — Cron 定时任务清单、UTC 时区换算表、多平台投递配置、管理命令速查
- `references/agy-stock-god-audit-2026-09-07.md` — AGY股神全系统策略审计（58/100分），6个致命缺陷与Top 3改进优先级
- `references/manual-rebalance-workflow.md` — 手动调仓标准工作流（持仓同步→风控诊断→执行→对比），用于用户口头报持仓或要求"帮我调仓"场景
- `references/ce-skill-design-patterns.md` — CE 方法论设计模式（从 compound-engineering-plugin 提炼），新/修改 skill 时的参考
- `references/script-pipeline.md` — 脚本优先架构实现文档：kline_analyze / sector_scanner / risk_precheck / compound_learnings 四个脚本的使用方式、输入输出、设计约束
- `references/compound-learning-loop.md` — 沉淀闭环实现文档：learnings/ 目录结构、TEMPLATE 用法、索引查询、与 reviews/ 的分工、Cron 集成
- `templates/learning-template.md` — 交易教训归档模板（YAML frontmatter），复制到 learnings/ 并填写后归档
- `templates/trade-lifecycle-report.md` — 买卖生命周期报告模板，用于用户要求列出完整交易记录时输出
- `references/market-data-freshness-and-schema-drift.md` — 市场数据纠错手册：状态新鲜度、MCP `ladder/ladders` 契约漂移、落盘回读、多源核验、盘后价格回退与TDD清单
- `references/reversal-analysis-framework.md` — 反转判断四维矩阵实战核查手册（数据提取字段+判定阈值+昊华科技全案例复盘）

## 目录结构

```
~/.hermes/trading/
├── reviews/              # 复盘报告 (review_YYYY-MM-DD.md)
├── intents/              # 交易意图归档
├── learnings/            # 交易经验沉淀（结构化学习，含YAML frontmatter）
├── scripts/data/         # 数据处理脚本（K线分析、板块扫描等）
├── logs/                 # 操作日志
├── current-holdings.json # 🔴 飞书持仓台账（外部持仓，非MCP exec系统）
└── strategy-feedback.md  # 策略迭代反馈（由复盘员持续追加）
```

### strategy-feedback.md 的职责与写入协议

`~/.hermes/trading/strategy-feedback.md` 是策略级反馈闭环台账，不是持仓表、交易日志或每日复盘报告：

- 收盘复盘员追加信号结果、交易结果、判断偏差、根因和可执行 action_items。
- 盘前研究员读取历史胜率、低胜率信号和未执行的 P0/P1 项，校正 confidence 与筛选范围。
- 每日详细事实保存在 `reviews/review_YYYY-MM-DD.md`；可复用单条教训保存在 `learnings/`；反馈台账只保留策略级摘要。
- 只追加，不改写历史。数据错误追加纠错记录，列出原值、正确值、来源和影响。
- 先事实后结论；行情、新闻、公告、财报、订单和盈亏必须有工具或成交记录来源，未核实内容明确标注。
- 每条改进必须写清角色、检查步骤/字段、生效条件和验证方式；禁止使用“加强判断”等不可执行表述。
- P0/P1 必须记录状态、负责人和截止窗口；完成后在原条目后追加 `[已执行]`，不得删除原事项。
- 胜率统计按 `catalyst_type`、`entry_rule`、confidence 分段和样本量维护；样本不足 5 次不得固化禁令。
- 本文件只影响研究和策略参数，不构成下单授权；买卖仍须经过实时行情、K 线、新闻/订单核验、策略和风险审批。
- 恢复缺失文件时保留已有历史；缺失段落不得凭记忆重建，必须用复盘报告、成交记录和工具输出补录并标注“恢复记录”。

标准追加模板见 `templates/strategy-feedback-template.md`。
```

### current-holdings.json 说明

该文件独立于 MCP exec 模拟交易系统。当 exec 系统空仓但用户在其他账户持有股票时，该文件充当持仓台账，供：

- 飞书 cron 汇报持仓状态时读取
- 盘中检查时作为额外扫描对象（与 exec positions 合并检查）
- 与 memory 分离：持仓是动态交易数据，不是永久记忆。不要将持仓信息写入 memory 工具。

**格式**：
```json
[
  {"symbol": "688331", "name": "荣昌生物", "shares": 1400, "cost": 115.0},
  {"symbol": "300199", "name": "翰宇药业", "shares": 6600, "cost": 23.0}
]
```
