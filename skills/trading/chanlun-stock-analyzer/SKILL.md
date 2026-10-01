---
name: chanlun-stock-analyzer
description: 缠论股票分析与交易系统总调度 Skill，自动识别用户需求并路由至对应的阶段子 Skill（选股、分析、做T交易、风控）
---

# 缠论股票交易系统总控 (Chan Theory Master Dispatcher System)

本 Skill 作为缠论交易系统的**总路由器与调度中心**。根据用户的指令类型，自动转接至对应的专用阶段子 Skill 处理，确保交易分析的高效与精准。

---

## 一、子 Skill 架构与职责分工

系统的 5 大模块构成如下：

- **总调度入口** → `chanlun-stock-analyzer`（本文件）
- **共享理论字典** → `chanlun-theory`（被各模块引用）
- **阶段一：选股扫描** → `chanlun-screener`
- **阶段二：个股深度分析** → `chanlun-analyzer`
- **阶段三：持仓与做T执行** → `chanlun-trader`
- **阶段四：风险与资金管控** → `chanlun-risk`

数据流水线：`screener → analyzer → trader → risk`

| 子 Skill | 角色说明 | 触发场景 | 输出 |
|----------|----------|----------|------|
| `chanlun-theory` | 共享理论字典 | 基础定义、定理与公式速查（被引用） | 静态理论定义 |
| `chanlun-screener` | 选股扫描器 | "帮我选股"、"扫描机会"、"看哪个板块" | `candidate_pool` JSON |
| `chanlun-analyzer` | 个股深度分析器 | "分析某股票"、"画笔画中枢"、"找买卖点" | `trading_plan` JSON |
| `chanlun-trader` | 持仓与做T执行 | "要不要做T"、"手上的票要卖吗"、"做差价" | `portfolio_status` JSON |
| `chanlun-risk` | 风险与资金管控 | "风险大吗"、"仓位怎么配"、"止损设哪" | `risk_assessment` JSON |

---

## 二、路由与调度规则

当接收到用户请求时，按以下逻辑路由：

1. **选股/搜股诉求**（"帮我选几只符合三买的股票"）→ 调用 `chanlun-screener`，生成 `candidate_pool` JSON
2. **具体股票深度分析 / 纯股票名代码直达 / 诊断 / 做T指导**（"渝三峡A"、"三美股份"、"000565"、"分析荣昌生物"、"金山办公怎么做T"、"300248能买吗"）：
   - **默认执行路径**：由 Hermes 当前主模型亲自分析。调用 Intel MCP 获取实时行情、日线与30m/60m K线、筹码、资金、技术指标、财务和新闻，并进行多源交叉核验；不得凭记忆或单一碎片数据下结论。
   - **AGY按需路径**：仅当用户在当前请求中明确要求“AGY / Antigravity / 让AGY分析或审计”时，才调用 `mcp_intel_analyze_stock_with_antigravity(...)` 或 `analyze_stock_with_antigravity.py`。未明确要求时严禁自动调用。
   - **来源披露**：Hermes 自研判与 AGY 报告必须明确标注来源，不得把 AGY 输出冒充主模型亲自分析。
3. **直接买入/卖出指令**（"买入金山办公"、"买回来"、"补仓戈碧迦"）→ 自动触发全执行管线：
   - 默认由 Hermes 基于 MCP 实时数据完成分析；仅当用户当前明确要求 AGY 时才增加 AGY 分析（禁止仅凭记忆回答）
   - 分析结论为可买入/可持有 → 自动走 wind_down 流程：风控检查（`mcp_risk_batch_check`）→ 注册 intent（`mcp_exec_register_approved_intent`）→ 下单（`mcp_exec_place_order`）→ 回查（`mcp_exec_get_orders`）
   - 分析结论为不可买入 → 直接输出拒绝理由，不下单
   - 用户已授权全权自主执行，单字"买"="卖"="补"即触发全链路，不需要二次确认
   - 详见 `a-stock-executor` skill 的完整下单协议
4. **持仓卖出或做T执行状态**（"查看持仓状态"）→ 调用 `chanlun-trader`，生成 `portfolio_status` JSON
5. **整体风险控制或仓位评估**（"仓位80%风险高吗"）→ 调用 `chanlun-risk`，生成 `risk_assessment` JSON

---

## 三、核心心法速查

无论调用哪个阶段子 Skill，系统始终遵守缠论终极原则：
- **走势终完美**：走势类型必将完成并发生转化。
- **只看和干**：用眼睛看当下的走势结构，不预测不幻想。
- **杜绝一切喜好**：空头陷阱买入，多头陷阱卖出；股票玩过就扔，绝不产生感情。
- **卖点手起刀落，买点义无反顾**：严格执行买卖点纪律，实现零成本凭证运作。
