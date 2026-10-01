# AGY 连接失败时的降级分析方案

> 2026-09-11 实战记录：analyze_stock_with_antigravity.py 第一次超时(120s)，第二次报错 "subscriber fell behind updates, stalled for 6s"，无法获取 AGY 分析报告。

## 问题描述

analyze_stock_with_antigravity.py 依赖 AGY CLI 的外部连接。当以下条件触发时脚本可能失败：
1. **超时**(exit_code=124)：AGY 生成响应时间 > 120s
2. **连接中断**："the connection to the agent was interrupted before the response finished: subscriber fell behind updates, stalled for Xs" — AGY 服务端推送跟不上消费端
3. **AGY 服务本身异常**（未在本次出现，但历史记录中有）

## 降级方案：手动 MCP 数据采集 + 分析师级研判

当 AGY 脚本失败后，不退化为"无法分析"，而是走手工 MCP 数据拉取链路，按 AGY 相同框架输出分析。

### 第1步：批量拉取核心数据

Intel MCP 的 JSON-RPC 端点为 `http://localhost:9001/mcp`，用 python requests 或 curl 直接调用：

```python
import requests, json

mcp = 'http://localhost:9001/mcp'

# 查询实时量价
payload = json.dumps({
    'jsonrpc': '2.0', 'method': 'tools/call', 
    'params': {'name': 'query_data', 'arguments': {'symbols': ['603728.SH']}}, 'id': 1
})
r = requests.post(mcp, data=payload, headers={'Content-Type': 'application/json'})
data = r.json()['result']['content'][0]['text']

# 日K线（获取均线系统和K线结构）
payload = json.dumps({
    'jsonrpc': '2.0', 'method': 'tools/call',
    'params': {'name': 'fetch_kline', 'arguments': {'symbol': '603728.SH', 'period': 'D', 'count': 30}}, 'id': 1
})

# 30分钟K线（缠论级别分析必备）
payload = json.dumps({
    'jsonrpc': '2.0', 'method': 'tools/call',
    'params': {'name': 'fetch_kline', 'arguments': {'symbol': '603728.SH', 'period': '30', 'count': 40}}, 'id': 1
})

# 资金流向
payload = json.dumps({
    'jsonrpc': '2.0', 'method': 'tools/call',
    'params': {'name': 'get_fund_flow', 'arguments': {'symbol': '603728'}}, 'id': 1
})

# 筹码分布
payload = json.dumps({
    'jsonrpc': '2.0', 'method': 'tools/call',
    'params': {'name': 'get_chip_distribution', 'arguments': {'symbol': '603728'}}, 'id': 1
})

# 技术指标（全套MA/MACD/KDJ/RSI/BOLL/BIAS等）
payload = json.dumps({
    'jsonrpc': '2.0', 'method': 'tools/call',
    'params': {'name': 'get_technical_indicators', 'arguments': {'symbol': '603728'}}, 'id': 1
})
```

注意：`query_data` 的 symbols 参数是 **list** 类型（`['603728.SH']`），不是字符串。

### 第2步：关键数据解读框架

采集到原始数据后，按以下框架做研判（与 AGY 输出保持一致）：

| 数据维度 | 关键字段 | 分析要点 |
|:---------|:---------|:---------|
| **筹码** | chipProfitRate, chipAvgCost, chipConcentration70/90 | 获利盘%越低→套牢越重；均价 vs 现价→主力盈亏方向 |
| **资金** | JumboNetFlow(超大单), BlockNetFlow(大单), MainNetFlow5D/10D/20D | 近日方向趋势；超大单 vs 大单谁主导 |
| **技术-MA** | MA5/10/20/30/60/120/250 | 多头/空头排列判断；MA5/10死叉=短期转弱 |
| **技术-MACD** | DIF, DEA, MACD(柱) | 零轴上下位置；DIF-DEA金叉/死叉；柱状发散方向 |
| **技术-KDJ** | KDJ_K, KDJ_D, KDJ_J | J<10=极度超卖有反抽需求；J>100=超买 |
| **技术-BOLL** | BOLL_UPPER, BOLL_MID, BOLL_LOWER | 下轨支撑位；上轨阻力位；缩口/张口方向 |
| **技术-BIAS** | BIAS_6/12/24 | 乖离率<-7=超跌反抽机会；>5=追高风险 |
| **融资融券** | FinanceBuyValue, FinanceRefundValue | 融资买入 vs 偿还，多头杠杆方向 |

### 第3步：输出标准三段式

按 AGY 相同格式输出「依据、打法、红线」三段式分析：

**依据(≤3行):**
- 【事实】具体量化证据1...
- 【事实】具体量化证据2...
- 【推断】综合判断...

**打法(≤3条，均具名):**
- 1、板块(周期阶段): 标的代码(量化依据) 买入触发条件，弃买条件。
- 2、持仓应对/做T: 标的代码(阻力/支撑依据) 具体操作。
- 3、空头防守或高位只卖不买。

**红线:**
关键防守位/条件 = 触发动作；仓位限制。

### 关键区别：手动 vs AGY 输出

| 维度 | AGY自动 | 手动降级 |
|:-----|:---------|:---------|
| 分析深度 | 芯片原生推理，有独创洞察 | 依赖数据解读框架，偏结构化 |
| 缠论判定 | 自动识别笔/中枢/背驰 | 需手动读K线判断（30F以上级别） |
| 速度 | 15-120s（联网生成） | 5-10s（纯本地） |
| 可靠性 | 受制于外部连接 | 100%本地，不依赖网络 |

### 输出示例（鸣志电器603728.SH降级分析，2026-09-11）

```
依据：
- 【事实】筹码获利盘仅7.3%，主力均价53.70元严重倒挂（现价47.41元），90%集中度18.38%
- 【事实】主力5日净流出7835万，MACD零轴下死叉，MA5<MA10<MA20空头排列，J值1.23极度超卖
- 【推断】30F级别连续下行跌破多重MA支撑，未见底分型+底背驰

打法：
- 1、人形机器人(退潮探底期)：鸣志电器 603728.SH — 放弃买入，等30F底背驰+放量突破MA5
- 2、持仓应对(做T)：BOLL下轨44.58支撑，MA5(49.01)阻力，反弹借脉冲做T高抛
- 3、空头防守

红线：
跌破BOLL下轨44.58=止损离场；总仓<10%
```

## 事前预防

1. 首次调用 AGY 脚本必须设置 timeout=300s（留出充足时间给多源交叉核验，严禁设 120s）
2. 失败后立即走降级方案，**不**反复重试同一脚本（AGY 服务端状态短期内不会自愈）
3. 若 MCP 本身也超时，检查 Intel MCP 服务状态：`ss -tlnp | grep 9001` 或 `curl -s http://localhost:9001/health`
