# Stock Analysis Query Patterns

Proven wencai_search query templates for ad-hoc deep analysis. Each template targets a specific data need.

## Round 1: Fundamentals

```
"{股票名} 基本面 业绩 估值 归母净利润 营业收入 2025 2026"
```
Returns: PE(TTM), 基本面评分, 归母净利润, 营收, 同比增长率

## Round 2: Analyst Coverage

```
"{股票名} 机构评级 研报 目标价 2026"
```
Returns: 原始评级, 目标价(前复权), 研报标题, 研究机构, 研究员, 调整方向

## Round 2: Technical Levels

```
"{股票名} 近一个月 最高价 最低价 支撑位 压力位 {代码}"
```
Returns: 每日最高/最低价, 支撑位, 压力位, 开盘价/收盘价

## Round 3: Capital Flow

```
"{股票名} 成交量 换手率 资金流向 {年}年{月}月"
```
Returns: 每日成交量, 换手率, 资金流向金额

## Industry-Specific Queries

### 有色金属/铜矿
```
"{股票名} 铜产量 产能 玉龙铜矿/TFM/KFM 2025 2026 分红"
```

### 医药/创新药
```
"{股票名} 大盘环境 资金流向 {子公司名} 创新药 输液 2025 2026 业绩增长"
```
Note: This query also pulls subsidiary data (e.g. 川宁生物 for 科伦药业)

### General industry keyword
```
"{股票名} {行业特色关键词1} {行业特色关键词2} 2025 2026 业绩增长"
```

## Pre-Market Queries

### Market Overview
```
"今日大盘 上证指数 深证成指 创业板指 {日期} 盘前 市场情绪"
```
Returns: 指数涨跌幅, 板块热度

### Sector Sentiment
```
"有色金属板块 铜板块 医药板块 今日盘前 资金流向 {日期}"
```
Returns: 板块涨跌幅, 集合竞价涨跌幅

### Auction Data (per stock)
```
"{股票名} 集合竞价 {日期}"
```
Key fields: 竞价涨幅, 竞价匹配价, 竞价量, 竞价金额, 竞价异动说明, 竞价异动类型, 竞价评级, 竞价未匹配量/金额

## Query Tips

1. **Always include year** in queries — wencai returns different time horizons based on dates in query
2. **Use exact stock name** not ticker — wencai matches on 股票简称
3. **Add stock code at end** of technical queries to disambiguate same-name stocks
4. **Industry keywords matter** — generic queries return too many columns; specific keywords narrow results
5. **Separate fundamental vs technical queries** — combining them returns 100+ columns that get truncated
6. **News search (mcp_intel_search_news) often returns empty** — don't rely on it alone; always pair with wencai_search
7. **Stock code verification** — `query_data` returns wrong stock names for some codes (001208→华菱线缆 not 大中矿业, 000980→众泰汽车). Always verify with `wencai_search("股票名")` first.
8. **Yahoo Finance for A-share indices** — Yahoo's coverage of A-share sector indices is poor. Use `wencai_search` for sector/板块 analysis instead.

## Sector Rotation Queries

### 板块涨幅排名
```
"近一个月涨幅最大的行业板块 涨幅排名前10"
"近一个月跌幅最大的行业板块 跌幅排名前10"
```
Returns: 同花顺行业指数代码, 指数简称, 涨跌幅, 指数类型(二级行业/三级行业/概念)

### 资金净流入排名
```
"资金净流入最多的板块 近5日"
```
Returns: 概念指数和行业指数的资金净流入额，交叉验证板块涨幅是否可持续

### US Market Data (via Yahoo Finance)

For US stock analysis (NASDAQ, S&P 500, tech giants), Yahoo Finance works well:
```
# Daily K-line for US stocks/indices (works for: ^IXIC, ^GSPC, NVDA, AAPL, MSFT, etc.)
https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=6mo&interval=1d
```
Headers needed: `User-Agent: Mozilla/5.0`

**Note**: Yahoo Finance uses `^IXIC` for NASDAQ Composite, `^GSPC` for S&P 500, `^VIX` for VIX. A-share indices are unreliable via Yahoo.
