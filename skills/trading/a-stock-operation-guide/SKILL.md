# a-stock-operation-guide — A-Share Operation Guide v3

Chan theory (pen → segment → pivot → divergence → buy/sell point) complete classification decision system for individual stock operations. Merges chanlun-analyzer (10-step geometric decomposition, pivot calculation, three buy/sell point types, four turn types, interval nesting). For cron scripts and daily stock Q&A.

## Core Principle

**No trend, no divergence. No divergence, no buy/sell point.**

## Merged Chanlun-Analyzer: 10-Step Analysis Flow

### Step 1: Determine Level
- Short-term: **30-minute level** (cron standard)
- Medium-term: Daily level

### Step 2: Inclusion Processing + Fractal Identification
Process 30-min K-line inclusion. Identify **top fractals** and **bottom fractals**.

### Step 3: Draw Pens + Segments
- Pen: Adjacent top-bottom fractal with at least 1 independent K-line between
- Segment: Composed of at least 3 pens

### Step 4: Construct Pivot
Pivot = overlap of 3 consecutive sub-level trend types. `Pivot range = (max(lows), min(highs))`.
- Consolidation = 1 same-level pivot
- Trend = 2+ same-direction same-level pivots (non-overlapping)

### Step 5: Divergence Determination
**Standard trend divergence (a+A+b+B+c)**: Compare b vs c strength (MACD DEA/bar area). c must be sub-level containing third buy/sell point. c must make new high/low.

**Consolidation divergence**: Compare entry vs exit segment strength with only 1 pivot.

### Step 6: Buy/Sell Point Classification

**Sell point priority (A-share practice)**: 三卖 > 一卖 > 二卖

| Buy Point | Feature | Operation |
|-----------|---------|-----------|
| First Buy (一买) | Downtrend divergence, >= 2 pivots + c divergence | Aggressive buy, high volatility |
| Second Buy (二买) | First sub-level pullback after first buy | Add position, safest |
| Third Buy (三买) | Break pivot + pullback doesn't enter pivot | Add, trend confirmation |

| Sell Point | Feature | Operation |
|------------|---------|-----------|
| First Sell (一卖) | Uptrend divergence, c-segment exhaustion | Clear position |
| Second Sell (二卖) | Bounce fails prior high | Reduce position |
| Third Sell (三卖) | Break pivot + bounce doesn't enter pivot | **Highest priority** — clear position |

### Step 7: Four Turn Types
Standard trend divergence / Non-standard (3-buy to 2-sell) / Consolidation / Small-to-large

### Steps 8-10: Interval Nesting → Trend Table Diagnosis → Trading Plan
Large level enters divergence segment → drill into sub-level step by step. Pen state matrix (1,1)/(-1,1)/(1,0)/(-1,0) diagnoses undisease/wanting-disease/diseased. Define deterministic response with clear buy/sell boundary conditions.

## Data Source Fallback Strategy

| Priority | Source | Usage |
|----------|--------|-------|
| 1 | `MCPClient.instance().call('get_positions')` | Position stock current_price |
| 2 | Sina hq.sinajs.cn | Real-time: `https://hq.sinajs.cn/list=sz300161` (Referer: finance.sina.com.cn) |
| 3 | Sina K-line API | History: `https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sz300161&scale=30&ma=no&datalen=100` |

⚠️ EastMoney (`push2.eastmoney.com`) returns 502 from overseas IP — prefer Sina.

## Step 0: Confirm Review Date + Data Boundary
- Check if today is trading day. If not, lock most recent completed trading day.
- Historical review must use that day's close field, K-line, and news published by that close. No mixing in post-review news or "latest price" fields.
- 4 indices (SH/SZ/ChiNext/STAR50) + 100 30-min K-lines minimum per stock.

## Output Rules

- Close review: clear action — buy/sell/hold/no trade. Don't write "observe" as buy signal.
- Intraday: distinguish three scopes: "no buy point all day" / "buy point appeared but now missed/cannot chase" / "executable buy point still available"
- Each action must label evidence date and data boundary. If dates inconsistent → downgrade to "observe only"
- User-facing playbook: must give specific executable prices (entry/add/reduce/stop). Range allowed but not pure Chan terms alone.

**Chan four elements must cover**: trend type, pivot position/count, divergence state (yes/no/suspected), buy/sell point position.

**Feishu 3-line format**:
```
[emoji window] | 大盘XX ±X% | HOLD/操作 代码 现价 理由 | 无信号
```

**Detailed analysis to file** (`~/.hermes/trading/chanlun_analysis_YYYYMMDD.md`)

## Stop-Loss & Operation Range Calculation

**No fixed 0.97 pivot floor rule**. Calculate by price position:

| Price Position | Condition | Buy Support | Stop Reference | Target |
|---------------|-----------|-------------|----------------|--------|
| Below pivot floor 3%+ | price < ZD x 0.97 | Recent 20-bar low | recent_low x 0.97 | Pivot floor ZD |
| Inside pivot | ZD ≤ price ≤ ZG | Pivot floor ZD | ZD x 0.97 | ZG x 1.05 |
| Above pivot ceiling 3%+ | price > ZG x 1.03 | Pivot ceiling ZG | ZG x 0.97 | price x 1.15 |
| No pivot | — | Recent 20-bar low | recent_low x 0.97 | price x 1.08 |

## Buy/Sell Signal Priority

When multiple Chan signals coexist:
```
三卖 > 一卖 > 二卖  (sell priority)
一买 > 二买 > 三买  (buy priority)
```

**Critical**: 一买 + 三卖 + bottom divergence → 三卖 is newest (bounce failed → pivot downward). **三卖 highest priority — reduce/observe, not buy.**

## Volume-Price Verifications (embedded in Chan framework)

| Chan Point | Volume Verification |
|------------|-------------------|
| 三买 break pivot | Break pen volume > prev day 150% |
| 一卖 c-segment exhaustion | c-segment volume < b-segment 50% |
| Consolidation break | 三买 + sector resonance volume |
| Break pivot | 三卖 + volume increase confirm |

### Volume-Price Eight Forms (supplementary)

| Form | Position | Meaning | Strategy |
|------|----------|---------|----------|
| **Deep volume deep price** | Bottom | Extreme low activity | Mid-long entry opportunity |
| **Sky volume sky price** | Top after big rise | High volume stagnation → reversal | Sell early |
| **Volume up price flat** | Mid-rally / High top | Profit-taking / Impending drop | Hold / Reduce |
| **Volume up price up** | Bottom bounce / Rally | Capital entering | Follow, pullback = buy point |
| **Volume shrink price down** | Early decline / Bottom | Bears dominate / Exhaustion | Exit / Bottom fish |
| **Volume up price down** | High zone | Profit-taking fleeing | Sell signal |
| **Volume shrink price up** | Bounce / Rally | Not confirmed / Tightly held | Exit on bounce / Hold |
| **Volume flat price up** | Slow rise | Steady accumulation | Follow on dips |

## Volume-Price Rules (from notes实战)

**Volume standard**: 放量 = 2-3x previous avg. `放量突破当日最高价` = buy trigger. 缩量: green volume bar < recent highest red bar.

**地量+小阳线=买点**: 支撑有效 → 地量(成交量新低) → 小阳线(多头占优) → 三条件共振即入场.

**巨量交易核心**："能解放所有套牢盘的资金一定是来盈利的" — 突破放量当天最高价=主力吸筹, 买入. 选小盘股, 流通盘<5亿.

**阻力位滞涨三天原则**: D1出现绿巨量 → D2突破绿量最高价建仓(当天长上影) → D3量缩且未突破上影最高价→收盘前出场. 从发现巨量起只给3天.

**量能选股**: 放量上涨后次日创新高=买点. 放量上涨+缩量回调(绿柱<前红柱)=继续买入. 缩量回调到前支撑+地量=二次入场.

## Position Management

- Trend confirmed (post-三买): total 8%
- Pivot building (trend unclear): total 4%
- Consolidation oscillation: high-sell-low-buy, single stock < 4%
- Stop-loss: cost -6% (hard) + structure stop (pivot broken = clear)

## Speculative-Level Sell Discipline

| Auction State | Action |
|---------------|--------|
| Gap-up >= 2% | Wait 5min. If weak → exit at bounce to open/avg line |
| Flat or slight gap-down (-1%~+1%) | Check volume. Abnormal → exit at auction. Normal → wait |
| Large gap-down >= -3% | Exit at auction immediately |

**Forbidden**: Selling gap-up stock at plunge low; not giving 5-min recovery; being swept by retail panic.

## Reversal/Bounce/Oscillation — Four-Matrix
MA alignment → main force → K-line structure → chip cost. **Dead cross one-vote veto**: MA5/MA10 dead cross + MACD underwater dead cross → NOT a reversal.

## Revealed Holding Protocol
1. Full data pull: `query_data` + `get_fund_flow` + `get_technical_indicators` + `get_chip_distribution` + `fetch_kline` (D/60/30) + `search_news`
2. Update memory
3. Output: direction + three-pieces + theme attribution
4. Four-matrix for reversal/bounce anchor

## Named Battle-Form Rules

When user asks "does X match Y form", check rules below. Three-tier: **strict match** / **form-similar-unconfirmed** / **definitely-not-match**. Form match ≠ immediate buy — still need capital + sector + risk clearance.

### 单阳不破 (Single-Yang-Holds)
大阳(>5% or 涨停)或2-3根小阳累计>7%后, 后续K线不跌破大阳最低价.
- **5条介入条件**: ①大阳幅度越大越好(>5%) ②上升放量介入(量>前日150%) ③最后上升时间不过第9根K线(第11根后急跌) ④20日线拐头向上(向下不介入) ⑤弱势行情(20日线向下)任何类似形态都不介入
- **三种形态**: 最强(创大阳新高→最佳买点) / 较强(震荡未创新高→以大阳1/2位为基准) / 一般(下行但未破大阳最低)

### MA5捉妖 (5MA Demon Catch)
5日线上方, 连续3日创新高(每日最高>前日最高) = 骑大牛形态. 缩量回踩5日线=低吸点. 跌破5日线出场.

### 灵猴探路 (Spirit-Monkey Pathfinding)
白线上穿黄线(突破60日线) + 带量突破 + 缩量回踩60日线不破 + 右侧(60日线上方)买入.

### 长阳七星 (Long-Yang-Seven-Star)
大阳线后第7个交易日为变盘窗口(斐波那契). 第7日若缩量回踩支撑=买点, 若放量滞涨=卖点. 延伸至14/21日.

### 经典老鸭头 (Classic Old-Duck-Head)
3条件: ①MA5死叉MA10后再度金叉 ②死叉期间缩量(绿柱<前红柱1/2) ③不破MA30. 双进场信号: 金叉日 / 突破鸭头顶(死叉前最高价).

### 仙人指路 (Immortal-Points-the-Way)
3根K线: ①前期阳线(>3%) ②长上影(上影线>实体2倍, 放量) ③缩量回踩不破第1根阳线最低 = 狙击点. 上影线最高=止盈目标.

## Prohibited Actions
- No fixed-price-only output — must give Chan structure conditions
- No judgment without K-line — must pull 100 30-min bars
- No "form" replacing "structure" — pivot > form
- No direction prediction before pivot completed
- **No position analysis without three-pieces**: Immediately output add/profit/stop levels

## References
- `references/alert-plan-format.md` — Alert plan JSON format
- `references/watchlist-batch-analysis.md` — Batch watchlist analysis
- `references/independent-multi-stock-analysis.md` — Independent multi-stock analysis with source disclosure
- `references/chan-pivot-audit.md` — Pivot calculation audit
- `references/intraday-entry-and-bottom-fishing.md` — Intraday entry criteria
- `references/limitup-retest-pattern-and-alerting.md` — Limit-up retest monitoring
- `references/reversal-detection-four-matrix.md` — Four-matrix reversal detection
- `references/leader-breakout-backtest.md` — Leader breakout backtest
- `references/trading-strategy-document-quantization.md` — Strategy document quantization
