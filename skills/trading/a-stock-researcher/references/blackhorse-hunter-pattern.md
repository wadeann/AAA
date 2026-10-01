---
name: a-stock-blackhorse-hunter
description: "黑马狙击研究模板：识别长期横盘后放量突破的翻倍潜力股。作为研究员的专项扫描模式嵌入现有 pipeline，不独立输出 TradeIntent。"
version: 2.0.0
author: Hermes Agent
metadata:
  hermes:
    tags: [trading, a-stock, researcher, pattern-scan]
    related_skills: [a-stock-researcher, a-stock-strategist, a-stock-trading-rules]
---

# 黑马狙击研究模板 (Blackhorse Hunter)

## 定位

本 skill 是 **a-stock-researcher 的专项扫描扩展**，不是独立角色。它提供"横盘突破型"候选标的的发现和初步筛选逻辑，输出交给研究员整合到标准 TradeIntent pipeline（研究员→策略员→风控→执行员）。

**与现有体系的关系**：
- 研究员 Step 4 的形态3（横盘突破）是本模板的简化版，本模板提供更精细的筛选和审计
- 本模板可在盘前扫描或盘中快扫时由研究员调用，作为 Step 4 的增强替代
- 置信度计算、止损止盈、仓位控制全部交给下游角色，本模板只负责候选生成和风险标注

## 触发条件

以下任一场景触发本模板：
1. 研究员盘前扫描时，主动执行一次黑马专项扫描
2. 盘中快扫发现"放量突破"类异动，需要深度过滤
3. 用户手动说"找黑马"、"横盘突破"、"底部放量"等关键词

## 狙击流程（3步）

### Step 1：广撒网 — 横盘突破初筛

调用 `mcp_intel_wencai_search` 执行以下查询（注意：使用振幅而非收盘价涨跌幅，避免漏掉箱体震荡后突破的标的）：

**主查询（振幅版，覆盖箱体震荡）**：
```
"近60日振幅小于25% 今日量比大于2.5 今日涨幅大于4% 今日换手率3%到15% 非ST 上市超过1年"
```

**辅助查询（长周期底部突破，扩大覆盖）**：
```
"近120日内最高价与最低价之比小于1.2 今日放量2倍以上 今日涨幅大于5% 换手率大于3% 非ST"
```

**辅助查询（一阳穿多线，均线粘合后突破）**：
```
"5日10日20日30日均线粘合 今日股价同时站上5日10日20日30日均线 今日放量 非ST"
```

三个查询结果合并去重，形成候选池（通常 5-15 只）。

**Pitfall**：
- 不要用"近120天涨跌幅-10%到10%"作为横盘条件——箱体震荡的收盘价可能不变但振幅大，这个条件会漏掉真正的好票
- 不要在 Step 1 限制换手率 > 15%，那个在严禁条款里处理即可，这里限制过严会漏票

### Step 2：三道审计 — 降风险标注（不是一票否决）

对候选池中的每只标的，并行执行以下三项检查，输出**风险标注**而非直接淘汰。最终由策略员和风控员决定是否操作。

#### 审计①：行业共振（Resonance）

调用 `mcp_intel_fetch_market_health`，检查标的所属申万一级行业：

| 条件 | 标注 | 对 confidence 的建议调整 |
|------|------|------------------------|
| 行业在 top_inflows 前5 且分值 > 70 | `SECTOR_RESONANCE` | +0.15（风口共振，最强加分） |
| 行业资金流向为正但不在前5 | `SECTOR_NEUTRAL` | 无调整 |
| 行业在 top_outflows 前5 | `SECTOR_OUTFLOW` | -0.15（行业撤离，高风险警告） |
| 行业整体流向为负但不在撤离榜前5 | `SECTOR_WEAK` | -0.05 |

**注意**：`SECTOR_OUTFLOW` 是警告而非否决。如果个股量价信号极强（量比>5+涨停），行业撤离可能只是板块轮动滞后，最终由策略员综合判断。

#### 审计②：量价真实性（Authenticity）

调用 `mcp_intel_query_data` 检查个股资金流向：

| 条件 | 标注 | 含义 |
|------|------|------|
| change_pct > 0 且 net_inflow > 0 | `GENUINE_BREAKOUT` | 量价齐升，真实突破 |
| change_pct > 0 且 net_inflow ≈ 0（±流通市值0.5%） | `NEUTRAL_FLOW` | 资金中性，可能是散户推动 |
| change_pct > 0 且 net_inflow < 0 | `DIVERGENCE_WARNING` | 量价背离警告，主力可能在出货 |

**重要**：`net_inflow` 本身是估算数据，口径因数据源而异。`DIVERGENCE_WARNING` 标注为"警告"而非"TRAP/否决"，因为：
1. 资金流向数据有滞后性和估算误差
2. 主力可能分批建仓，当日净流出不代表出货
3. 最终由风控员结合持仓和整体风险做裁决

标注了 `DIVERGENCE_WARNING` 的标的，在输出时 confidence 建议值上限 0.72（不超过纯消息驱动上限）。

#### 审计③：催化验证（Catalyst）

调用 `mcp_intel_search_news` 搜索标的近期资讯，寻找突破的催化剂：

| 催化类型 | 标注 | confidence 建议调整 |
|---------|------|-------------------|
| 实质性利好（重大订单/重组获批/新产品量产/行业政策直接利好） | `STRONG_CATALYST` | +0.10 |
| 一般性利好（机构评级上调/业绩预增/行业会议） | `MODERATE_CATALYST` | +0.05 |
| 无明显催化（纯技术面突破） | `NO_CATALYST` | 无调整 |
| 利空消息（减持/诉讼/业绩预警） | `NEGATIVE_CATALYST` | -0.10 |

**催化验证要点**：
- "订单"要看金额占营收比，< 5% 的是例行公告不算催化
- "定增"要看用途，补充流动性的不算，投新产能的才算
- "政策利好"要看是否直接利好该标的主营，概念沾边的降级为 MODERATE

### Step 3：整合输出 — 候选清单（非 TradeIntent）

将审计结果整理为结构化候选清单，**交给研究员整合到标准 TradeIntent 输出**。

```json
{
  "scan_mode": "blackhorse_hunter",
  "candidates": [
    {
      "symbol": "688331",
      "name": "荣昌生物",
      "pattern": "横盘60日后放量突破",
      "consolidation_days": 60,
      "volume_ratio": 3.2,
      "breakout_pct": 5.8,
      "audit": {
        "sector": "SECTOR_RESONANCE",
        "authenticity": "GENUINE_BREAKOUT",
        "catalyst": "STRONG_CATALYST"
      },
      "suggested_confidence": 0.80,
      "risk_flags": [],
      "evidence": ["近60日振幅22%", "今日量比3.2", "医药行业top_inflow前3", "主力净流入1.2亿", "ADC药物获批临床"]
    }
  ],
  "rejected": [
    {
      "symbol": "600XXX",
      "reason": "DIVERGENCE_WARNING + SECTOR_OUTFLOW 双重警告"
    }
  ]
}
```

**confidence 建议值计算**：

基础值 0.65（横盘突破形态的基准），叠加审计调整：

| 因子 | 调整 |
|------|------|
| SECTOR_RESONANCE | +0.15 |
| SECTOR_NEUTRAL | 0 |
| SECTOR_WEAK | -0.05 |
| SECTOR_OUTFLOW | -0.15 |
| GENUINE_BREAKOUT | +0.05 |
| NEUTRAL_FLOW | 0 |
| DIVERGENCE_WARNING | -0.10（且上限0.72） |
| STRONG_CATALYST | +0.10 |
| MODERATE_CATALYST | +0.05 |
| NO_CATALYST | 0 |
| NEGATIVE_CATALYST | -0.10 |

最终值 clamp 到 [0.50, 0.90] 区间。**研究员收到后还需叠加 market_condition 调整（BULL/NEUTRAL/BEAR）**，最终低于 0.65 的不输出。

## 严禁规则

1. **换手率 > 25%** 的标的标记 `TURNOVER_EXCESS`，建议过滤（老庄出逃信号）
2. **fetch_market_health 评分 < 40** 时，所有候选标记 `MACRO_RISK`，confidence 强制上限 0.65（几乎不操作）
3. **ST / 退市风险** 标的直接排除，不走审计流程
4. **近5日日均成交额 < 5000万** 的标的标记 `LIQUIDITY_RISK`，小盘股（市值<50亿）放宽至 1000万

## 与现有 Pipeline 的集成方式

### 盘前扫描（a-stock-premarket-scan）

研究员 subagent 在执行 Step 4 形态扫描时，将本模板的三个 wencai 查询替换原有的"形态3 — 横盘突破"简单查询。审计流程在研究员 Step 6（财务与流动性核查）中并行执行。输出格式不变，仍然是 TradeIntent JSON 数组。

### 盘中快扫（a-stock-intraday-eval）

当盘中快扫发现"放量突破"类异动时，加载本模板执行 Step 2 审计和 Step 3 输出，跳过 Step 1（因为异动标的已经确定）。

### 手动触发

用户说"找黑马"、"扫描横盘突破"时，执行完整 Step 1→2→3 流程。

## 关键约束

- **不直接输出 TradeIntent**：只输出候选清单，由研究员整合为标准 TradeIntent
- **不填写止损止盈**：交给策略员根据 catalyst_type 统一规则填写
- **不填写仓位**：交给策略员根据 confidence + market_condition + 金字塔规则填写
- **不执行风控**：只做风险标注，不替代风控员的审批职责
- **审计标注是建议而非裁决**：DIVERGENCE_WARNING 不是否决，SECTOR_OUTFLOW 不是禁入，最终决策权在策略员和风控员

## Common Pitfalls

1. 把 DIVERGENCE_WARNING 当一票否决 — 资金流向数据是估算，假阳性高，只能当警告
2. 用收盘价涨跌幅代替振幅做横盘判断 — 箱体震荡股收盘价可能没怎么变但日内波动大，会漏票
3. confidence 建议值超过 0.90 — 横盘突破只是形态信号，不是确定性事件，上限 0.90
4. 跳过行业共振审计直接输出 — 横盘突破如果发生在撤离行业，大概率是反弹而非反转
5. 在 Step 1 过度限制换手率 — 上限 15% 够了，下限 3% 以下的多是无人关注的僵尸股
6. catalyst 标注把例行公告当重大利好 — 必须看金额占营收比和与主营的关联度
8. 当 fetch_market_health 返回空 top_inflows/top_outflows（数据延迟）时，应降级处理：改用 wencai_search 查当日申万一级板块主力净流入排名作为替代。如果 wencai 也同样不可用，则所有候选 SECTOR 标注统一为 SECTOR_NEUTRAL，不做任意正负标注。
