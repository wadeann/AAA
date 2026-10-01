# First-Principles Stock Analysis (第一性原则分析)

## When to Use

When the user asks for deep analysis of a stock, sector, or competing stocks ("分析XXX", "找出最有价值的票", "按照第一性原则分析"). This is a **strategic layer** that sits above technical pattern scanning—it answers "why own this" not "when to buy this."

## The Four Questions

Every stock/sector must pass these four questions. Fail one = eliminate or downgrade.

### Q1: Is demand real and irreversible?
- Not "story," but actual orders, revenue, and profit.
- Verify with: 2025 revenue, YoY growth, Q1 2026 momentum, customer capex validation.
- Red flag: "expected to grow in the future" with no current revenue to show.

### Q2: Is supply constrained / are there barriers?
- Can competitors easily replicate? How long would it take?
- Verify with: global market share concentration, certification cycles, patent moats, technical lead time.
- Red flag: "everyone can do it" — low barriers = margin compression.

### Q3: Who has pricing power?
- Is the company a price maker or price taker?
- Key proxies: gross margin trajectory, net margin vs peers, customer concentration.
- Red flag: gross margin < 15% and declining = price taker.

### Q4: What is profit quality?
- High ROE + high net margin + strong operating cash flow = barriers are real.
- Key metrics: ROE > 20%, net margin > 15%, operating cash flow ≥ net profit.
- Red flag: high profit but negative cash flow (receivables risk).

## Industry Comparison Template

When comparing multiple sectors/companies, use this scoring matrix:

| 维度 | Weight | Data Source | Scoring |
|------|--------|------------|---------|
| 需求确定性 | 25% | 营收增速 + 客户capex | 营收同比>20% = ✅ |
| 供给壁垒 | 25% | 市场份额 + 技术领先 | 全球前2 + 独供 = ✅ |
| 定价权 | 25% | 毛利率 + 净利率 | 毛利率>30% + 净利率>15% = ✅ |
| 利润质量 | 25% | ROE + 经营现金流 | ROE>20% + CF/利润>1 = ✅ |

## Multi-Timeframe Technical Entry (技术面入场)

### Structure: 60min → 30min hierarchy
1. **60min K-line**: structural analysis (trend, support/resistance, pattern formation)
2. **30min K-line**: intraday confirmation (volume spike, breakout/loss of key levels)
3. **Realtime quote**: current price vs key levels

### "进二退一" Pattern (Two Steps Forward, One Step Back)
The most reliable main-uptrend pattern:
- Phase 1: Strong rally (e.g., +15-20% over 5-10 days) — "进二"
- Phase 2: Pullback to support (5-day or 10-day MA), < 10% — "退一"
- Phase 3: Resume upward with volume confirmation — entry signal

**Key verification points:**
- Pullback must NOT break the prior swing low
- Volume must be declining during pullback (not distribution)
- Breakout candle must have > 1.5x average volume

### Entry Parameters
- **Stop loss**: Below the pullback low (~-4-5%)
- **Target 1**: Prior high + half the rally range
- **Target 2**: Full rally extension (prior rally range projected from pullback low)
- **Position**: 3-5% initially, add on confirmed breakout above prior high

## Anti-Patterns

1. Don't analyze without real-time data — always pull query_data first
2. Don't compare stocks on PE alone — PE is meaningless without ROE + net margin context
3. Don't recommend stocks with high margin but no growth — they're value traps in hot sectors
4. Don't ignore the "price taker" problem — packaging/testing stocks with 4-5% net margin are structurally inferior to manufacturers with 30%+ net margin
