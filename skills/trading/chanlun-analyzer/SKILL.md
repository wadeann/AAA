---
name: chanlun-analyzer
description: 缠论个股深度分析器 Skill，进行十步几何结构与背驰拆解，定位买卖点与转折形态，输出格式化交易计划 JSON
---

# 缠论个股深度分析器 (Chan Theory Stock Analyzer)

本 Skill 专门用于对单一股票进行详细的缠论结构拆解，计算中枢区间、买卖点及转折类型。

> 理论字典引用：[`chanlun-theory`](skill:chanlun-theory)

---

## 一、触发条件与执行引擎
用户要求分析某只具体股票、定位买卖点、画笔线段中枢、评估当下走势类型或询问做T点位时使用。

### 🚀 执行引擎优先级（⚠️ 用户明确要求，不可跳过）

分析股票时严格按照以下优先级顺序调用，**不得跳过引擎直接手动分析**：

1. **Antigravity 量化总监（首选，直接调用原生 MCP 工具或脚本）**
   - **原生 MCP 工具**：`mcp_intel_analyze_stock_with_antigravity(symbol="<股票代码或名称>", focus="<用户具体问题>")`
   - **或 Terminal 脚本**：
   ```bash
   /home/ubuntu/.hermes/hermes-agent/venv/bin/python3 /home/ubuntu/.hermes/scripts/analyze_stock_with_antigravity.py "<股票名称或代码>" [--focus "<用户具体问题>"]
   ```
   （注意：通过 terminal 调用时超时 timeout 参数必须指定为 300 秒，严禁传 120 秒）
   自动从 MCP 获取实时行情、30m/60m K线、筹码分布、主力资金与突发新闻，交由 Google Antigravity 进行深度推理并输出【依据、打法、红线】确定性操盘预案。

2. **Gravity 引擎（Antigravity 失败时降级）**
   如果 Antigravity 脚本因网络超时、API 错误、脚本异常等原因失败，再尝试 Gravity 引擎。调用方式视具体可用的 Gravity 接口而定。

3. **手动分析（前两者均失败时兜底）**
   仅当 Antigravity 和 Gravity 都不可用时，才通过 MCP 拉取行情+K线+新闻，结合缠论结构做手动分析。此时需在报告中说明原因（如 "AA/Gravity 引擎不可用，改为手动分析"）。

**⚠️ 铁律：** 用户会检查是否调用了引擎。直接手动分析会被纠正（"你分析调用antigravity了吗"）。养成先跑脚本的习惯。

---

## 二、标准化输入 (JSON)

```json
{
  "stock_code": "600XXX",
  "stock_name": "某某股份",
  "analysis_level": "日线 | 30分钟 | 5分钟 | 1分钟",
  "context_from_screener": { "optional": "来自 screener 的选股上下文" }
}
```

---

## 回测与龙头突破的强制流程

当用户要求“回测最近N日”“能否第一时间发现”“继续改进买点”时，不能把当前静态分析当作答案。必须按逐根30分钟K线回放，严格禁止未来数据泄漏，并区分两个状态：

1. `breakout_alert`：放量突破前置中枢/横盘区间上沿时立即发现；只输出预警、观察和等待回踩，不直接下单。
2. `confirmed`：后续回踩不跌回区间上沿，并重新站稳后，确认二买/三买，才允许生成交易候选。

回测必须记录首次触发的时间、价格、中枢上下沿、突破量、回踩低点和信号年龄；同一突破只提示一次。信号超过约3根30分钟K线后只能作为历史证据，不能再次生成当前买入候选。

连续涨停或一字/近一字压缩K线可能无法构造足够的传统分型、笔、线段和中枢。此时使用“原始K线突破回抽”分支，不得把涨停本身当买点；包含处理用于传统缠论结构，原始K线用于保留突破和回踩的时序。

回测报告必须回答：当时何时首次发现、何时才可执行、何时已经错过，以及如果没有信号是因为结构不足还是数据不足。参考实现与复现要点见 `references/leader-breakout-backtest.md`。

## 三、十步分析流程

1. **确定分析级别**：大级别定趋势方向，次级别寻买卖波段，小级别精确定位。
2. **K线包含处理与分型识别**：按时间顺序进行包含处理，标记顶分型与底分型。
3. **画笔与划分线段**：连接分型形成笔，识别特征序列及其破坏，划出本级别线段。
4. **定位走势中枢**：
   - 提取连续3个次级别走势重叠区间，计算 $ZG = \min(g_1, g_2, g_3)$, $ZD = \max(d_1, d_2, d_3)$。
   - 判定中枢中轴 $Z = (ZG+ZD)/2$ 及强弱状态 $Z_n$。
5. **判断走势类型与背驰**：
   - 趋势（$\ge 2$ 个中枢）还是盘整（1个中枢）。
   - 比较进入段 $b$ 与离开段 $c$ 的力度（MACD柱面积 / 黄白线高度）。
6. **定位三类买卖点**：
   - 1买：趋势背驰点（或1卖：顶背驰点）。
   - 2买：1买后第一次次级别回调（二三买合一/依次递升/盘背破底）。
   - 3买：突破中枢后次级别回抽低点 $> ZG$。
7. **判断四种转折方式**：
   - 标准趋势背驰转折 / 非标转折（3买转2卖） / 盘整转折 / 小转大。
8. **区间套精确定位**：从本级别锁定背驰段，逐级进入次级别/次次级别找共振点。
9. **走势表里诊断**：观察笔状态矩阵 (1,1), (-1,1), (1,0), (-1,0)，诊释未病/欲病/已病状态。
10. **生成交易计划**：制定确定性应对方案，明确买卖边界条件。

---

## 四、标准化输出格式 (JSON)

```json
{
  "stock_info": {
    "code": "600XXX",
    "name": "某某股份",
    "analysis_date": "YYYY-MM-DD",
    "level": "日线 / 30分钟"
  },
  "structure_analysis": {
    "current_trend_type": "上涨趋势 | 盘整震荡 | 下跌趋势",
    "pivots": [
      {
        "level": "日线",
        "range": [25.3, 28.7],
        "center_axis": 27.0,
        "status": "已向上突破"
      }
    ],
    "divergence_status": {
      "has_divergence": true,
      "type": "标准趋势背驰 | 盘整背驰 | 无背驰",
      "evidence": "c段MACD红柱面积仅为b段的40%"
    }
  },
  "buy_sell_points": {
    "first_buy": { "price_range": [23.5, 24.2], "triggered": true },
    "second_buy": { "price_range": [25.8, 26.5], "status": "当下买点区域" },
    "third_buy": { "price_range": [29.0, 29.5], "status": "待突破后确认" }
  },
  "trading_plan": {
    "action_recommendation": "分批建仓 / 观望 / 减仓",
    "entry_zone": [25.8, 26.5],
    "suggested_position_pct": 30,
    "stop_loss_price": 24.8,
    "target_zone": [29.0, 32.5],
    "holding_condition": "30日均线未跌破前持续持有"
  },
  "contingency_scenarios": [
    { "if": "跌破25.8元", "then": "减仓观望，等待下级别1买" },
    { "if": "突破29.0元且回抽不跌破28.7元", "then": "确认3买，加仓20%" }
  ]
}
```
