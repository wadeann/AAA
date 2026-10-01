# a-stock-researcher — A-Share Stock Researcher

Multi-dimensional stock screening, news aggregation, and TradeIntent generation. Merges chanlun-screener (Chan theory screening: top-down sector analysis, main force capital patterns, bull market selection methods) into a unified research skill. Covers cron auto-screening and user interactive stock inquiry.

## Inputs
- User oral command (e.g., "find two stocks", "what's the market opportunity")
- Cron job triggered timed scan

## Merged Chanlun-Screener Methods

### 0. Sector Trend Identification (P0 — Highest Priority, Must Execute Every Scan)
**Before looking at individual stocks, identify the sector picture.**

**A. Sector Duration Scan**
- Primary: `MCPClient.instance().call('wencai_search', {'query': '近5日涨幅最大的行业板块'})` + `MCPClient.instance().call('wencai_search', {'query': '近10日涨幅最大的行业板块'})`
- Fallback: `MCPClient.instance().call('search_news', ...)` or aggregate sites (hhxg.top, lianban.net)
- Cross-reference: sectors appearing on BOTH 5-day and 10-day leaderboards → **hot sustained theme**
- Output format:
  ```
  🔥 Sustained theme: [sector] N consecutive days strong | Ladder: N-board(X stocks) N-1-board(Y stocks)
  ⚡ New sector: [sector] first entry today TOP5 | Catalyst: XXX
  ```

**B. Sector Capital Flow**
- `MCPClient.instance().call('wencai_search', {'query': '今日主力资金净流入最大的行业板块'})`
- 3 consecutive days net inflow → 🔥 mark

**C. Limit-up Sector Categorization**
- `MCPClient.instance().call('wencai_search', {'query': '今日涨停 非ST'})`
- >= 5 limit-up stocks in a sector → must deep analyze
- Identify ladder leader (highest board, seal strength, turnover)

**D. Sector Catalyst Tracing (Cannot Skip)**
- For each 🔥 sector: wencai search `{sector name} 利好消息 政策`
- Identify catalyst type: policy/earnings/product/event/oversold bounce
- Oversold bounce → don't chase; Policy + Earnings dual-drive → highest priority

### 1. Systematic Top-Down Three-Step Selection
1. **Policy & Industry Direction**: Filter 5-7 key sectors by national policy + industry climate
2. **Sector Index Timing**: Decompose sector index pivot structure, lock onto sectors with buy points
3. **Individual Stock Pool**: Remove explosive/uncapped risks, pick active stocks stronger than sector

### 2. Bull Market Selection Methods
- **Strong Stock Insert**: Buy dips in strong stocks ("dip = discount" in bull market)
- **New Stock Breakout**: Volume breakout above IPO first-day high
- **Annual Line Breakout**: Volume breakout above 250MA then pullback to MA (most reliable bull form)

### 3. Main Force Capital Driven Selection
- **Mode A: Short-term Main Uptrend (hot theme + hot money)**: Limit-up boards / volume yang / seal > 100M. Buy on sub-level pullback buy point.
- **Mode B: Long-term Trend Bull (leader + institutional)**: 3 consecutive years net profit growth > 30%, EPS > 0.5, PE < 40-50x. Buy near 20-week MA.

### 3b. Fundamental Analysis Screening Thresholds (实战基本面筛选标准)

When evaluating candidate stocks, apply these A-share proven fundamental thresholds:

**Core Financial Metrics**:
| Metric | Standard | Notes |
|--------|----------|-------|
| 归属净利润同比增长 | > 30% preferred | 一季报/中报确认，避免基数过小假象 |
| 净利润门槛 | > 5000万（去年同期） | 避免因基数过小引起的高增长假象 |
| ROE（加权净资产收益率） | > 5% + 同比增长 | 衡量主营能力强弱的核心指标，看增长趋势非绝对值 |
| 毛利率（制造业） | > 30% | 参考格力美的标准 |
| 毛利率（互联网/科技） | > 50% | 硕世生物85%、贵州茅台93% |
| PE（长线投资） | < 50倍 | 科创板可适当放宽 |
| 主营占比 | > 70% | 拳头产品突出，行业壁垒高 |

**毛利率下滑预警**：毛利率大幅下滑1%，行业整体利润大幅衰减。运输、能源、媒体、服装受疫情毛利率大幅下滑。

**选股逻辑框架（四层过滤）**：
1. **行业景气度向上**（政策驱动/消费复苏/国产替代）
2. **个股业绩增长确定**（一季报/中报高增长，ROE同比增长）
3. **技术面形态配合**（突破/回踩确认，均线多排）
4. **资金面关注**（放量/缩量回调）

**数据源**：通过 `get_financial_report` 获取利润表、资产负债表数据；校验归属净利润、ROE、毛利率三个核心指标。

**两条主线**：
- 盈利水平持续增长的板块——半导体、科技股（国产替代+科技崛起）
- 经济复苏和政策刺激方向——基础产业（水泥、零售、食品饮料）→ 政策驱动新基建（大数据、云计算等）

> 核心口诀："科技为矛，医药为盾，趋势向导，业绩为王，高抛低吸吃大肉。"

### 4. High Win-Rate Buy Point Combinations
- ✅ Weekly 2-buy + Daily 2-buy resonance
- ✅ Daily 2-buy + 30min 2-buy resonance
- ✅ 30min 2-buy + 5min 1-buy
- ❌ Taboo: 30min 2-sell + 5min 1-buy (large-level down not exhausted)

### 5. Screening Prohibited Zones (Auto-Filter)
- ST / delisting risk / small garbage stocks
- High-control manipulative stocks
- High-position holding-stock crash phase
- Bearish MA alignment or price below 250MA long-term
- ED stocks (persistent volume contraction)

### 6. Post-Screening Landing Actions (For strength_rating >= A candidates)
1. Write to alert_plan: `~/.hermes/trading/alert_plans/alert_plan_YYYY-MM-DD.json`
2. Add to watchlist: `MCPClient.instance().call('update_watchlist', {'action': 'add', 'symbol': code, 'name': name})`
3. Calculate three-pieces (add/profit/stop) immediately — never just give a direction

## User Interaction Modes

### Mode A: Cron/Auto Screening
Standard steps 1-6, output JSON candidate report.

### Mode B: User Real-Time Inquiry ("what's the market opportunity", "can I buy XX")

#### Sub-scenario: Single Stock Inquiry
**Iron rule**: Default to Hermes current main model analysis. Only use AGY when user explicitly requests it.

Flow:
1. Call Intel MCP for: `query_data`, `fetch_kline`, `get_fund_flow`, `get_chip_distribution`, `get_technical_indicators`, `get_financial_report`, `search_news`
2. Output standard [Basis, Play, Redline] operation plan with source marked
3. Only if user explicitly asks for AGY: `MCPClient.instance().call('analyze_stock_with_antigravity', {...})`

#### Sub-scenario: "Has it Reversed?" Decision Framework
Must pull full MCP data and apply four-matrix judgment, not just report price change.

**Dimension priority**:
1. MA alignment + MACD: MA5 above MA10 golden cross + price above MA20 + MACD underwater golden cross = reversal
2. Main force capital: 5-day net positive = reversal signal
3. K-line structure: daily bottom fractal + upward segment confirmed
4. Sector resonance: sector also in uptrend

**Iron rule**: MA5/MA10 dead cross + MACD underwater dead cross → single yang bar cannot overturn = **NOT a reversal**.

### Mode C: Ignition-V1 First Board Detonation
When user asks about first-board candidates, postmarket scan:
```
MCPClient.instance().call('terminal', {'command': 'cd ~/.hermes/scripts && python3 ignition_v1_sniper.py --mode postmarket --verbose'})
```

## Step 0: Full Market Sorting & Direction Locking

When user asks "what to buy across the whole market" with no preset direction:

### 0A: Limit-up Ladder Scan
```
MCPClient.instance().call('get_limitup_ladder', {'min_streak': 1})
MCPClient.instance().call('get_mainline_lanes', {'top_n': 5})
MCPClient.instance().call('fetch_hot_signals')
```

**Interpretation**:
- 🔥 Stars Surround Moon (mainline score > 75 + height leader + complete ladder) → core direction
- 🚀 First-board cluster (score 60-75, multiple first boards no height leader) → wait for tomorrow PK winner
- ❌ Lone General (>= 3 boards no same-theme assists) → high-position bait, no chase

### 0B: Four-Dimension Track Elimination
Compare not just concepts but:
1. Mainline score
2. Ladder completeness
3. Capital inflow strength
4. Tomorrow advancement certainty

### 0C: Identify Leader in Selected Direction
1. Space dragon (highest board count)
2. Ladder support confirmation (>= 5 limit-up supports in concept)
3. Seal quality (seal count, seal amount, seal time)
4. Capital verification: `get_fund_flow`

### 0D: Deep Analysis After Direction Lock
After locking direction, enter standard analysis flow.

## Data Source Priority & Standard Call List

1. **Real-time & Multi-period**: `query_data` / `query_batch_data` + `fetch_kline` (30m/60m/Daily)
2. **Structured quantified**: `get_fund_flow`, `get_chip_distribution`, `get_technical_indicators`, `get_financial_report`
3. **Condition screening**: `screen_stocks`, `wencai_search`, `search_news`, `fetch_hot_signals`
4. **Account verification**: `get_balance`, `get_positions`, `get_today_trades`, `get_orders`

## Comparative Analysis

When user asks about 2+ stocks:
1. Independent analysis per stock (full MCP data)
2. Build comparative prompt with all data in ONE call
3. Output decision table

## Common Pitfalls
- ❌ Using `fetch_market_health` for index data (latency bug) → use `query_data` for 4 indices directly
- ❌ Relying solely on `fetch_hot_signals` for decisions → must wencai verify
- ❌ Same industry > 40% position → must disperse
- ❌ Chasing intraday gain > 8% → must give pullback range
- ❌ Comparing two stocks with separate AGY calls → must compare in one prompt
- ❌ Missing sector field in candidate dict → sector isolation logic broken
- ❌ Policy-driven analysis without 3-dimension verification → see `references/state-capital-injection-analysis.md`

## Wencai Data Notes
- `wencai_search` is unstable (frequent timeouts since 2026-09). Core analysis prefers structured MCP data.
- Historical backtesting via wencai: verify `[YYYYMMDD]` field matches target date, fail-closed on rollback.
- Keys never written in plaintext. Service reads `.env` dynamically.

## Candidate Report Output Format

```
## Candidates (N stocks)

### 1. Stock Name (Code)
- Price: XX | Change: XX%
- Sector/Concept: XXX
- Chan structure: 60m X-buy + 30m X-buy
- Entry range: XX~XX
- Stop: XX
- Target: XX~XX
- Reason (one line): XX
```

## Post-Selection Landing Checklist
- [ ] Candidate written to alert_plan?
- [ ] Added to watchlist (update_watchlist)?
- [ ] Position three-pieces (add/profit/stop) calculated?
- [ ] Industry concentration <= 40%?

## References
- `references/research-article-to-stock-mapping.md` — Supply chain mapping flow
- `references/third-party-article-analysis.md` — Third-party article analysis
- `references/supply-chain-analysis-framework.md` — Supply chain deep analysis
- `references/ignition-v1-v2-strategy.md` — Ignition V1/V2 strategy
- `references/wencai-key-rotation-and-index-low-inference.md` — Wencai key rotation
- `references/wencai-historical-strategy-backtesting.md` — Wencai historical backtesting
- `references/first-principles-analysis.md` — First principles analysis (multi-timeframe entry)
- `references/pulse-spike-detection.md` — Intraday pulse spike detection
- `references/independent-multi-stock-analysis.md` — Independent multi-stock analysis with source disclosure
