# DATA LINEAGE AUDIT: AAA/Astock

**Date**: 2026-10-03  
**Auditor**: Data Engineer (Read-Only Audit)  
**Scope**: All of `/home/wade/workspace/ai/Astock`  
**Goal**: "Where does AAA's data come from, how is it acquired, cached, normalized, exposed through Intel MCP, and consumed by Backtest/Live -- and are these paths consistent?"

---

## TABLE OF CONTENTS

1. Executive Summary
2. Architecture Overview
3. External Data Sources
4. Acquisition Path - Per Data Type
5. K-Line Deep Dive
6. Intel MCP Audit (Port 9001)
7. Backtest vs Live Parity
8. PIT / Timestamp Audit
9. Cache Audit
10. Data Failure Behavior
11. Data Consistency Checks
12. Full Data Flow Diagram (Mermaid)
13. Piper 生态系统对接分析
14. Raw Remote Provider Chain
15. Configuration & Secrets
16. Reproduction Guide
17. Risk & Findings
18. Recommendations
19. Appendix - File-to-Data-Mapping

---

## 1. Executive Summary

**Primary Finding: ALL data flows through a single remote gateway -- `pup-mcp` at 152.69.201.170 -- which acts as a unified provider aggregator. No Astock code directly calls TDX, iWenCai, or any other provider API.** The local `MCPClient` (mcp_client.py) is an HTTP JSON-RPC passthrough to `pup-mcp`, which internally routes calls to TDX, iWenCai, financial APIs, news sources, etc.

The SSH tunnel (scripts/mcp_tunnel.py) forwards ports 9001/9002/9003 from remote to localhost, making the remote `pup-mcp` service appear local.

**Key Data Flow**:
```
External Providers (TDX, iWenCai, News APIs, etc.)
    |
    v
pup-mcp (remote 152.69.201.170:9001/9002/9003)
    |
    v  SSH Tunnel (mcp_tunnel.py)
    |
localhost:9001 (Intel) | localhost:9002 (Risk) | localhost:9003 (Exec)
    |
    v  HTTP JSON-RPC (httpx, mcp_client.py)
All Astock Python modules
```

**Critical Risk**: The live trading path ("Live") depends entirely on real-time MCP data. The backtest path uses a static `kline_cache.json` persisted from historical MCP fetches. There is NO backtest parity for non-K-line data types (fund flow, financial reports, news, sentiment).

---

## 2. Architecture Overview

### 2.1 Three-Tier MCP Architecture

| Port | Service | Purpose | Tools Count |
|------|---------|---------|-------------|
| 9001 | Intel MCP | Data queries, screening, analysis | 26 |
| 9002 | Risk MCP | Risk checks, blacklist, PnL | 4 |
| 9003 | Exec MCP | Order placement, positions, balance | 6 |

### 2.2 Module Map

```
Astock/
  config/             -- settings.yaml, strategy_params.json
  data/               -- DataManager, kline_cache.json, full_universe*.json
  core/               -- Strategy, chanlun_engine, sentiment, market_regime
  discovery/          -- Scanners (auction, limitup, theme, leader, full_market)
  execution/          -- Pipeline, direct_executor, dragon_screener
  intelligence/       -- AGY bridge, sector_flow, feishu_notifier
  scripts/            -- Backtest engines, scheduler, expand_cache
  orchestrator/       -- morning_master, watchdog
  utils/              -- Fund flow, market, chip, leader_universe
  risk/               -- RiskManager (13-layer)
  defense/            -- Explode monitor, close_session_defense
  evolution/          -- Performance reporter, strategy audit
```

---

## 3. External Data Sources

### 3.1 Primary Upstream Providers (Routed Through pup-mcp)

| Provider | What It Provides | Accessed Via | Astock Files |
|----------|-----------------|--------------|--------------|
| **TDX (通达信)** | K-line, real-time quotes, F10 fundamentals, screener, news | `tdx_kline`, `tdx_quotes`, `tdx_screener`, `tdx_f10`, `tdx_news`, `tdx_health` | `mcp_client.py` lines 149-159 |
| **iWenCai (问财)** | Natural-language stock screening, sector scanning, auction data | `wencai_search` | `mcp_client.py` line 103, `discovery/*.py` |
| **Financial API** | Fund flow, chip distribution, technical indicators, financial reports | `get_fund_flow`, `get_chip_distribution`, `get_technical_indicators`, `get_financial_report` | `mcp_client.py` lines 135-146 |
| **News API** | Stock-specific news | `search_news` | `mcp_client.py` line 123 |
| **Market Data** | Limit-up ladder, mainline lanes, rebound candidates, hot signals | `get_limitup_ladder`, `get_mainline_lanes`, `get_rebound_candidates`, `fetch_hot_signals` | `mcp_client.py` lines 107-121 |
| **Index Data** | Real-time index quotes for 000001.SH, 399001.SZ, 399006.SZ, 000688.SH | `query_batch_data` | `mcp_client.py` line 83 |
| **Session Info** | Trading sessions, trading day check, market health | `trading_sessions`, `is_trading_day`, `fetch_market_health` | `mcp_client.py` lines 84-91 |
| **AGY (Antigravity)** | LLM-based qualitative analysis, sector flow analysis, strategy review | `agy_bridge.py` (subprocess calling `agy` CLI) | `intelligence/agy_bridge.py` |

### 3.2 Provider API Keys (Stored in .env)

The `.env` file contains:
- 5x iWenCai API keys (`IWENCAI_API_KEY` through `IWENCAI_API_KEY_5`)
- 1x TDX API key (`TDX_API_KEY`)
- SSH credentials for tunnel to remote server

These keys are used by `pup-mcp` on the remote server, NOT directly by Astock code.

### 3.3 Static Data Files

| File | Contents | Source | Consumers |
|------|----------|--------|-----------|
| `data/kline_cache.json` | 2537 entries of daily K-line data (format: `{SYMBOL}_{COUNT}` -> list of bars) | Historical MCP `fetch_kline` calls | All backtest scripts |
| `data/full_universe_raw.json` | Raw full universe symbol list | Pre-populated / MCP-derived | expand_kline_cache.py |
| `data/full_universe.json` | Processed full universe | Derived from raw | Backtests |
| `config/strategy_params.json` | Strategy parameters, sell rules, regime map | Manual / auto_iterate evolution | All strategy consumers |
| `data/state/market_regime.json` | Current market regime state | `MarketRegime.detect()` from real-time index quotes | Sentiment engine, execution |
| `data/state/sentiment.json` | Current sentiment phase | `compute_sentiment()` from real-time quotes | Execution, risk management |
| `data/state/strategy_params.json` | Runtime strategy params (sentiment block injected) | `strategy_params_init.py` | Direct executor, pipeline |

---

## 4. Acquisition Path - Per Data Type

### 4.1 K-Line (Daily/Weekly)

```
TDX / Financial API
    |
    v  pup-mcp MCP tool: fetch_kline(symbol, period, count)
    |
    v  mcp_client.py: MCPClient.fetch_klines()
    |
    +---> Live Path: direct executor, discovery scanners, chanlun analysis
    |     (real-time MCP call, no local caching of K-lines in live path)
    |
    +---> Backtest Path: backtest_engine.py, backtest_v5.py, backtest_v6.py, etc.
    |     (MCP HTTP call per symbol, optional in-memory _MCP_CACHE dict)
    |
    +---> Cache Build Path: expand_kline_cache.py
    |     (batch fetch -> save to kline_cache.json)
    |
    +---> Cached Backtest Path: backtest_2yr.py, backtest_3m.py,
    |     backtest_notes_strategies.py, backtest_ma_strategies.py
    |     (read from kline_cache.json, no MCP call needed)
```

**Critical**: The `kline_cache.json` keys use format `{SYMBOL}_{COUNT}` (e.g., `000001.SZ_500`), where COUNT is the number of bars fetched. Different backtest scripts request different counts (200, 500, 150), requiring matching keys in cache.

### 4.2 Index Data

```
TDX / Market API
    |
    v  pup-mcp MCP tool: query_batch_data([000001.SH, 399001.SZ, 399006.SZ, 000688.SH])
    |
    v  mcp_client.py: MCPClient.query_quotes()
    |
    v  core/sentiment_engine.py: compute_sentiment() -> sentiment phase + multiplier
    v  core/market_regime.py: MarketRegime.detect() -> regime state
    v  execution/direct_executor.py: intraday index health check
```

### 4.3 Fund Flow

```
Financial API (TDX or proprietary)
    |
    v  pup-mcp MCP tool: get_fund_flow(symbol) AND fetch_market_health()
    |
    v  mcp_client.py: MCPClient.get_fund_flow()
    |
    v  utils/fund_flow.py: parse_fund_flow_raw() -> structured dict
    |                        evaluate_fund_flow_safety() -> FundFlowEvaluationResult
    |
    v  risk/risk_manager.py: _check_outflow() (market-level outflow check)
    |
    v  intelligence/sector_flow.py: sector-level flow for AGY analysis
```

### 4.4 Financial Reports

```
Financial API / TDX F10
    |
    v  pup-mcp MCP tool: get_financial_report(symbol, num)
    v  pup-mcp MCP tool: tdx_f10(symbol, module)
    |
    v  mcp_client.py convenience methods
    |
    v  Used by execution pipeline for fundamental_confirmed checks
```

### 4.5 News

```
News API (proprietary)
    |
    v  pup-mcp MCP tool: search_news(symbol)
    |
    v  mcp_client.py: MCPClient.news_search()
    |
    v  Used by execution pipeline for news_confirmed checks
```

### 4.6 Sector / Theme Data

```
iWenCai (问财) Natural Language Query
    |
    v  pup-mcp MCP tool: wencai_search(query, limit)
    |
    v  discovery/full_market_discovery.py: 5 parallel wencai queries for wide pool
    v  discovery/auction_scanner.py: auction gap-up candidates
    v  discovery/theme_trigger.py: deep-screen themes
    v  discovery/limitup_scanner.py: get_limitup_ladder -> grade_seal_strength
    v  intelligence/sector_flow.py: sector flow via wencai fallback
```

### 4.7 Sentiment / Market Regime

```
Real-time Index Quotes (query_batch_data)
    |
    v  Index change percentages (4 indices)
    |
    +---> compute_sentiment(): avg_chg -> phase + multiplier
    |     phase: euphoria(>1.2%), hot(>0.4%), warmup(-0.3%~0.4%),
    |            cooldown(-1.2%~-0.3%), ice(<-1.2%)
    |     multiplier: 0.85, 0.75, 0.45, 0.25, 0.15
    |     persisted to: data/state/sentiment.json, data/state/strategy_params.json
    |
    +---> MarketRegime.detect(): same index data -> regime + standard_regime
    |     persisted to: data/state/market_regime.json
```

---

## 5. K-Line Deep Dive

### 5.1 Source

**Single source: TDX (通达信) through pup-mcp `fetch_kline` tool.**

The `mcp_client.py` also exposes `tdx_kline()` as an alternative/adapter, but the primary backtest path uses `fetch_kline`. Per the comment in `backtest_2yr.py` line 7-8:
> `CRITICAL-003 复权说明: MCP _fetch_kline 接口默认返回后复权(hfq)数据，经验证无除权除息缺口。所有回测价格已自动完成复权调整，无需额外处理。`

### 5.2 复权 (Adjustment) Status

**后复权 (hfq / backward-adjusted)**. This is explicitly stated in `backtest_2yr.py:7-8`.

All K-line prices include dividend/split adjustments done by TDX at source. The `pup-mcp` does not perform additional adjustment -- it passes through the hfq data from TDX.

### 5.3 Cache Structure (`kline_cache.json`)

- **Format**: Single JSON object, keys = `"{SYMBOL}_{COUNT}"` (e.g., `"000001.SZ_500"`)
- **Entry count**: 2537 entries (as of audit date)
- **Values**: Array of bar dicts with keys: `time`, `open`, `close`, `high`, `low`, `volume`, `amount`, `change`, `change_pct`, `amplitude`
- **Date range**: From ~2024-09-06 onward (varies by symbol)
- **No timestamp metadata**: The cache file has no header with dump date, source, or adjustment status -- this information is only known from code comments
- **Cache file path**: `data/kline_cache.json` (single monolithic JSON, ~270MB)

The `expand_kline_cache.py` script:
1. Computes missing stocks by comparing cache keys vs `full_universe_raw.json`
2. Fetches 500 bars per missing stock via MCP (`fetch_kline`, period="D", count=500)
3. Saves incrementally back to `kline_cache.json`

### 5.4 Backtest K-Line Path vs Live K-Line Path

| Aspect | Backtest Path | Live Path |
|--------|--------------|-----------|
| Data Source | `kline_cache.json` (static JSON file) OR direct MCP `fetch_kline` | Direct MCP `fetch_kline` (HTTP to pup-mcp) |
| Latency | Loaded once upfront (all symbols) | Per-symbol, real-time |
| Count | 150-500 bars (strategy-specific) | 30-200 bars (analysis-specific) |
| Adjustment | 后复权 (hfq) via TDX | 后复权 (hfq) via TDX |
| Caching | In-memory `_MCP_CACHE` dict (per run) | No local caching in live path |
| Point-in-Time | CAN reconstruct historical PIT (by filtering bars <= curr_date) | Always current |
| Price Types | OHLCV from TDX | OHLCV from TDX + real-time quote |

Each bar dict contains: `time, open, high, low, close, volume, amount, change, change_pct, amplitude`

---

## 6. Intel MCP Audit (Port 9001)

### 6.1 Implementation

The Intel MCP server runs on the remote host at port 9001, forwarded via SSH tunnel. Astock's `MCPClient` class in `mcp_client.py` communicates via HTTP JSON-RPC:

```python
POST http://127.0.0.1:9001/mcp
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {"name": "<tool_name>", "arguments": {...}}
}
```

Response format: `{"result": {"content": [{"text": "<JSON string>"}]}}`

### 6.2 Complete Tool Inventory

#### Market/Session Tools

| # | Tool | Input | Output | Source | Cache | Timestamp |
|---|------|-------|--------|--------|-------|-----------|
| 1 | `trading_sessions` | None | `{is_trading_day, is_open, session_name, ...}` | pup-mcp calendar | None | Real-time |
| 2 | `is_trading_day` | None | `{is_trading_day: bool}` | pup-mcp calendar | None | Real-time |
| 3 | `fetch_market_health` | None | `{health_score, limitup_count, limitdown_count, broken_seal_rate, ...}` | TDX / market data | None | Real-time |
| 4 | `historical_market_snapshot` | date? | `{...market state at date...}` | Historical data | Unknown | Historical |

#### K-Line / Quote Tools

| # | Tool | Input | Output | Source | Cache | Timestamp |
|---|------|-------|--------|--------|-------|-----------|
| 5 | `fetch_kline` | `{symbol, period, count}` | `{klines: [{time, open, high, low, close, volume, amount, change_pct, amplitude}]}` | TDX | None (but Astock caches in memory) | Real-time / Historical |
| 6 | `tdx_kline` | `{symbol, period, count}` | Same as fetch_kline format | TDX | None | Real-time / Historical |
| 7 | `query_batch_data` | `{symbols: [str]}` | `{quotes: {symbol: {price, change_pct, ...}}}` | TDX | None | Real-time |
| 8 | `tdx_quotes` | `{symbol}` | `{price, change_pct, open, high, low, volume, ...}` | TDX | None | Real-time |
| 9 | `query_multi_source_quote` | `{symbol}` | `{quotes from multiple sources}` | TDX + others | None | Real-time |

#### Screening / Discovery Tools

| # | Tool | Input | Output | Source | Cache | Timestamp |
|---|------|-------|--------|--------|-------|-----------|
| 10 | `screen_stocks` | `{query, limit}` | `{stocks: [{symbol, name, ...}]}` | TDX screener | None | Real-time |
| 11 | `tdx_screener` | `{query, limit}` | Stock list | TDX | None | Real-time |
| 12 | `wencai_search` | `{query, limit}` | `{datas: [{股票代码, 股票简称, ...}]}` | iWenCai | None | Real-time |
| 13 | `get_watchlist` | None | `{stocks: [...]}` | pup-mcp internal | Unknown | Real-time |

#### Leader/Ladder/Lanes Tools

| # | Tool | Input | Output | Source | Cache | Timestamp |
|---|------|-------|--------|--------|-------|-----------|
| 14 | `get_limitup_ladder` | `{date?, min_streak}` | `{ladder: [{symbol, name, boards, ...}]}` | Market data + TDX | None | Intraday |
| 15 | `get_mainline_lanes` | `{top_n}` | Sector lanes | Market screener | None | Intraday |
| 16 | `get_rebound_candidates` | `{min_prev_height, max_prev_height, limit}` | Rebound candidates | Screening engine | None | Intraday |

#### Flow / Technical / Fundamental Tools

| # | Tool | Input | Output | Source | Cache | Timestamp |
|---|------|-------|--------|--------|-------|-----------|
| 17 | `get_fund_flow` | `{symbol}` | `{JumboNetFlow, BlockNetFlow, MainNetFlow, SmallNetFlow, ...}` | Financial API | None (Astock has TTL cache 60s) | Intraday |
| 18 | `get_chip_distribution` | `{symbol}` | Cost distribution | Financial API | None | Intraday |
| 19 | `get_technical_indicators` | `{symbol}` | `{MACD, RSI, KDJ, BOLL, ...}` | TDX | None | Intraday |
| 20 | `get_financial_report` | `{symbol, num}` | `{revenue, profit, growth, ...}` | Financial API / TDX F10 | None | Quarterly |

#### News / Signals Tools

| # | Tool | Input | Output | Source | Cache | Timestamp |
|---|------|-------|--------|--------|-------|-----------|
| 21 | `search_news` | `{symbol}` | `{items: [{title, content, time}]}` | News API | None | Real-time |
| 22 | `fetch_hot_signals` | None | Hot market signals | Market screener | None | Intraday |

#### F10 / Analysis Tools

| # | Tool | Input | Output | Source | Cache | Timestamp |
|---|------|-------|--------|--------|-------|-----------|
| 23 | `tdx_f10` | `{symbol, module}` | F10 fundamentals | TDX | None | Real-time |
| 24 | `tdx_news` | `{symbol}` | TDX news | TDX | None | Real-time |
| 25 | `tdx_health` | `{symbol}` | Stock health metrics | TDX | None | Real-time |
| 26 | `analyze_stock_with_antigravity` | `{symbol, ...}` | AGY LLM analysis | AGY (Gemini) | None | Real-time |

---

## 7. Backtest vs Live Parity

### 7.1 K-Line Data

| Aspect | Backtest | Live | Parity |
|--------|----------|------|--------|
| Source | `kline_cache.json` or MCP `fetch_kline` | MCP `fetch_kline` (TDX) | **PARITY: Both use TDX hfq, same bar format** |
| Adjustment | 后复权 (hfq) | 后复权 (hfq) | **MATCH** |
| Bar fields | OHLCV + amount, change_pct, amplitude | OHLCV + amount, change_pct, amplitude | **MATCH** |
| Availability | Pre-fetched snapshot (can be stale) | Always current | **GAP: Cache can be outdated** |

### 7.2 Non-K-Line Data (MAJOR GAPS)

| Data Type | Backtest Path | Live Path | Parity |
|-----------|--------------|-----------|--------|
| Fund Flow | **NOT AVAILABLE** in backtest | `get_fund_flow(symbol)` via MCP | **NO PARITY** |
| Financial Reports | **NOT AVAILABLE** in backtest | `get_financial_report(symbol)` via MCP | **NO PARITY** |
| News | **NOT AVAILABLE** in backtest | `search_news(symbol)` via MCP | **NO PARITY** |
| Real-time Quotes | Uses next-day's OHLC bar (T+1 simulation) | `query_batch_data(symbols)` real-time | **PARTIAL (intraday timing differs)** |
| Sentiment/Regime | **Historic backtest recomputes from index bars available at time T** (PIT-safe) | `compute_sentiment()` from live index quotes | **PARITY (live has richer signals)** |
| Sector/Themes | **NOT AVAILABLE** in backtest (wencai_search not called) | `wencai_search` + `wencai_search` | **NO PARITY** |
| iWenCai Screening | **NOT AVAILABLE** in backtest | 5 parallel wencai queries in `full_market_discovery.py` | **NO PARITY** |

### 7.3 Identified Parity Gaps Summary

1. **Backtests use ONLY K-line data** -- no fund flow, financial reports, news, or real-time screening factors
2. **Backtests use T+1 execution model** (buy at next day's open after signal) vs live path's immediate execution
3. **Live path has multi-source confirmation** (volume_confirmed, sector_confirmed, fundamental_confirmed, news_confirmed) that backtests cannot replicate
4. **Live path screening uses iWenCai NLP** (wencai_search) which cannot be reconstructed historically
5. **Live execution includes intraday conditions** (auction timing, garbage time gates, real-time price change checks) absent from backtests

---

## 8. PIT / Timestamp Audit

### 8.1 K-Line Point-in-Time

| Component | Can Reconstruct Historical PIT? | Method | Notes |
|-----------|-------------------------------|--------|-------|
| Daily OHLCV | **YES** | Filter bars where `time <= curr_date` | Explicitly done in all backtest loops |
| Weekly trend | **YES** | Filter weekly bars `time <= curr_date` | `backtest_engine.py:494` |
| RSI at time T | **YES** | Compute from PIT-filtered closes | `backtest_engine.py:71` |
| MA at time T | **YES** | Compute from PIT-filtered closes | All backtests |
| Volume ratio | **YES** | `current_vol / avg_vol(T-20)` from PIT data | All backtests |

### 8.2 Market Regime PIT

| Component | Can Reconstruct Historical PIT? | Method | Notes |
|-----------|-------------------------------|--------|-------|
| Market regime | **YES** (backtest engine) | `compute_regime_sentiment()` derives from index bars available at T | `backtest_engine.py:245-301` |
| Market regime | **NO** (cached backtests) | `backtest_3m.py` uses MA20 breadth from sampled universe -- different algorithm | Uses different regime detection from live |

The `backtest_engine.py` comment explicitly warns about this (lines 249-254):
> "Point-in-time sentiment from historical index bars only (no future leakage). Derives phase and multiplier purely from index data available at curr_date. This replaces the previous load_market_regime() approach which leaked future information into historical backtest dates."

However, `backtest_v5.py`, `backtest_v6.py`, and `backtest_3m.py` use different `get_regime()` implementations that compute regime from PIT index bars directly -- **this is PIT-safe** for the K-line-derived regime computation but does NOT match the live regime detection algorithm (which uses real-time quote data, not just OHLCV bars).

### 8.3 Non-K-Line PIT Summary

| Data Type | Historical PIT Available? | Why |
|-----------|--------------------------|-----|
| K-Line OHLCV | **YES** | Stored in `kline_cache.json`, filterable by date |
| Fund Flow | **NO** | Not stored historically, only available live from MCP |
| Financials | **NO** | Not stored historically, only live MCP query |
| News | **NO** | Not stored historically, only live MCP query |
| Sector/Themes | **NO** | wencai_search cannot historically reconstruct queries |
| Sentiment (backtest engine) | **YES** | Recalculated from PIT index bars |
| Sentiment (other backtests) | **PARTIAL** | Uses different algorithm from live |

---

## 9. Cache Audit

### 9.1 Cache Inventory

| Cache | Type | Location | Has Timestamp? | Has Source Info? | Can Serve Stale? | TTL |
|-------|------|----------|---------------|-----------------|-----------------|-----|
| `kline_cache.json` | JSON file | `data/kline_cache.json` | **NO** | **Implicit (TDX hfq, from code comments)** | **YES** -- no freshness check | None |
| `market_regime.json` | JSON state file | `data/state/market_regime.json` | **YES** (`updated_at` ISO) | **YES** (index changes stored) | **YES** -- 5-min cron refresh | ~5 min (intraday) |
| `sentiment.json` | JSON state file | `data/state/sentiment.json` | **YES** (`updated_at` ISO) | **YES** (phase, multiplier) | **YES** -- updated per cron cycle | ~5 min |
| `strategy_params.json` | JSON state file | `data/state/strategy_params.json` | **YES** (within sentiment block) | **YES** | **YES** -- updated by strategy_params_init | Per cron |
| `MCPClient._http` | httpx Client | In memory | **NO** | **NO** | **N/A** (single session) | Connection lifetime |
| `_MCP_CACHE` (in backtests) | Python dict | In memory | **NO** | **NO** | **N/A** (per run) | Per backtest run |
| `_FUND_FLOW_TTL_CACHE` | Python dict | In memory | **YES** (timestamp per entry) | **NO** | Configured TTL=60s | 60 seconds |
| `get_fund_flow_cached` | lru_cache | In memory | **NO** | **NO** | **YES** (no eviction by age) | Max 1024 entries |
| `strategy_circuit_breaker_dir` | JSONL + JSON | `data/state/strategy_circuit_breaker/` | **YES** | **YES** (trade history) | State file | N/A |
| `candidates_*.jsonl` | JSONL ledger | `data/ledger/candidates_{date}.jsonl` | **YES** (implicit in filename, timestamps in records) | **YES** (catalyst, source fields) | N/A (read-only after day ends) | 1 day |

### 9.2 Critical Cache Gap: kline_cache.json

The most critical cache (`kline_cache.json`, 2537 stocks, ~270MB) has:
- **No dump date** -- impossible to know when the data was fetched
- **No source identifier** -- must infer from code comments that data comes from TDX hfq
- **No adjustment status field** -- exists only as a code comment in `backtest_2yr.py`
- **No per-bar verification** -- can contain stale/outdated data for symbols
- **Different count keys** -- `000001.SZ_500` vs what `backtest_v5.py` requests (`count=200`) leading to cache misses and MCP calls during backtests

### 9.3 Cache Serving Issues

The `kline_cache.json` serves stale data to historical backtests:
- **If cache was built on date X, it contains data up to X** -- backtests after X will miss recent bars
- **Suspension/ST/IPO stocks** -- symbols may have been removed or added since cache build
- **Corporate actions** -- forward adjustments may have shifted historical prices if TDX re-bases

---

## 10. Data Failure Behavior

### 10.1 Failure Modes by Data Type

| Scenario | MCP Call | Behavior | Classification |
|----------|----------|----------|---------------|
| K-line fetch fails | `fetch_kline()` | Returns `[]`, stock skipped in backtest/screening | **PASS (silent skip)** |
| K-line missing symbol | Same | Same | **PASS** |
| Index quotes fail | `query_batch_data()` | `sentiment_engine.py` falls back to candidate count heuristic | **FALLBACK** |
| Index quotes fail (regime) | Same | `MarketRegime` returns previous state from cache | **CACHE** |
| Fund flow fails | `get_fund_flow()` | Returns `{}`, `evaluate_fund_flow_safety()` returns "degraded=True, is_safe=True" | **FALLBACK (fail-open!)** |
| Fund flow data missing | Same | Returns `FundFlowEvaluationResult(True, "数据缺失或超时，容灾降级放行")` | **FAIL-OPEN** |
| Risk MCP (9002) fails | `batch_check()` | Falls back to `degraded_risk_check()` (local-only checks) | **FALLBACK (degraded, fail-closed for some)** |
| Exec MCP (9003) fails | `get_balance()`/`get_positions()` | Returns empty dict/list, execution blocked | **BLOCK** |
| AGY (LLM) fails | `ask_antigravity()` | Falls back to Gemini 3.7 Flash if quota/rate-limit, else error text | **FALLBACK (model downgrade)** |
| wencai_search fails | `wencai_search()` | Exception caught, returns empty list, query silently skipped | **PASS (silent skip)** |
| News search fails | `search_news()` | Returns `[]` | **PASS** |
| SSH tunnel down | All MCP calls | ConnectionError, all operations fail | **BLOCK** |

### 10.2 FAIL-OPEN Patterns (Critical)

**Fund Flow Safety Check (`utils/fund_flow.py:233-238`)**: When fund flow data is missing or times out, the safety check returns `is_safe=True` with `degraded=True`. This means:
- **A buy order that should be blocked by outflow detection will PASS through if fund flow data is unavailable**
- The degraded flag is set but not universally checked by all consumers

**Sentiment Fallback (`core/sentiment_engine.py:80-86`)**: When index quotes fail, sentiment falls back to candidate-count heuristic. Low candidate count (<= 5) results in `warmup` phase with `multiplier=0.30` -- the default conservative setting. This is actually fail-safe (conservative), not fail-open.

### 10.3 RETRY Patterns

- `backtest_2yr.py: fetch_klines()`: 3 retries with exponential backoff (2s, 4s, 8s)
- `execution/pipeline.py: risk_check_and_execute()`: 4 retries for Risk MCP with backoff [1, 2, 4] seconds
- No retry for: wencai_search, fund flow, news search

---

## 11. Data Consistency Checks

### 11.1 Cross-Backtest K-Line Consistency

| Backtest | K-Line Source | Count | Universe |
|----------|--------------|-------|----------|
| `backtest_engine.py` (chanlun) | MCP `fetch_kline` | 200D, 100W | 20 hardcoded stocks |
| `backtest_v5.py` (momentum) | MCP `fetch_kline` | 200D | ~160 hardcoded stocks |
| `backtest_v6.py` (dual mode) | MCP `fetch_kline` | 200D | ~160 hardcoded stocks |
| `backtest_2yr.py` (momentum) | `kline_cache.json` then MCP | 500D | 200+ stock_universe_full |
| `backtest_3m.py` (momentum v5) | `kline_cache.json` | N/A (full cache) | All cached stocks |
| `backtest_notes_strategies.py` | `kline_cache.json` | N/A | All cached stocks |
| `backtest_ma_strategies.py` | `kline_cache.json` | N/A | All cached stocks |
| `backtest_ignition.py` | MCP `fetch_kline` | 30D | Per-symbol |

**Inconsistency**: Backtests using `kline_cache.json` get DIFFERENT data than backtests using live MCP calls if the cache is stale. Cache-based backtests may fail to find bars for the full requested count.

### 11.2 Symbol Naming Consistency

| Context | Format | Example |
|---------|--------|---------|
| MCP `fetch_kline` | `{code}.{market}` | `000001.SZ`, `600519.SH` |
| `kline_cache.json` keys | `{code}.{market}_{count}` | `000001.SZ_500` |
| Strategy hardcoded lists | `{code}.{market}` | `600519.SH` |
| `cost_model.py` | Needs `.SH` or `.SZ` suffix | Checks `symbol.endswith(".SH")` |

**Potential Issue**: `backtest_ma_strategies.py:46-48` has a `strip_suffix()` function that removes `_500` from cache keys for cost calculation, indicating awareness of this mismatch. Other backtests may not handle this.

---

## 12. Full Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        EXTERNAL PROVIDERS                                │
│                                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐ │
│  │   TDX    │  │ iWenCai  │  │Financial │  │News API  │  │  Market  │ │
│  │ (通达信) │  │  (问财)  │  │   API    │  │          │  │   Data   │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘ │
│       │              │              │              │              │       │
└───────┼──────────────┼──────────────┼──────────────┼──────────────┼───────┘
        │              │              │              │              │
        └──────────────┴──────────────┴──────────────┴──────────────┘
                                  │
                                  ▼
               ┌─────────────────────────────────────┐
               │         pup-mcp (Remote Server)      │
               │        152.69.201.170                │
               │                                      │
               │  Port 9001: Intel MCP (26 tools)     │
               │  Port 9002: Risk MCP  (4 tools)      │
               │  Port 9003: Exec MCP  (6 tools)      │
               └──────────────┬──────────────────────┘
                              │
                    SSH Tunnel (mcp_tunnel.py)
                    ssh -L 9001:127.0.0.1:9001 ...
                              │
               ┌──────────────┴──────────────────────┐
               │        localhost (Astock)            │
               │                                      │
               │  ┌────────────────────────────────┐  │
               │  │  mcp_client.py (MCPClient)     │  │
               │  │  HTTP JSON-RPC to localhost     │  │
               │  └───────────┬────────────────────┘  │
               │              │                        │
               │    ┌─────────┼─────────┐              │
               │    ▼         ▼         ▼              │
               │ ┌──────┐ ┌──────┐ ┌──────┐           │
               │ │Intel │ │Risk  │ │Exec  │           │
               │ │:9001 │ │:9002 │ │:9003 │           │
               │ └──┬───┘ └──┬───┘ └──┬───┘           │
               └────┼────────┼────────┼───────────────┘
                    │        │        │
        ┌───────────┼────────┼────────┼───────────────────────┐
        │           ▼        ▼        ▼                        │
        │  ┌─────────────────────────────────────────────┐    │
        │  │           CONSUMER LAYER                     │    │
        │  │                                              │    │
        │  │  ┌──────────────────┐  ┌──────────────────┐ │    │
        │  │  │    LIVE PATH     │  │  BACKTEST PATH    │ │    │
        │  │  │                  │  │                   │ │    │
        │  │  │ discovery/*.py   │  │ backtest_*.py     │ │    │
        │  │  │  (wencai MCP)    │  │  (MCP or cache)   │ │    │
        │  │  │                  │  │                   │ │    │
        │  │  │ execution/*.py   │  │ kline_cache.json  │ │    │
        │  │  │  (MCP + state)   │  │  (static JSON)    │ │    │
        │  │  │                  │  │                   │ │    │
        │  │  │ core/sentiment   │  │ core/strategy.py  │ │    │
        │  │  │ core/regime      │  │  (shared scoring) │ │    │
        │  │  │  (MCP quotes)    │  │                   │ │    │
        │  │  │                  │  │ core/chanlun      │ │    │
        │  │  │ orchestrator/*   │  │  (PIT analysis)   │ │    │
        │  │  │  (all MCP)       │  │                   │ │    │
        │  │  └──────────────────┘  └──────────────────┘ │    │
        │  └─────────────────────────────────────────────┘    │
        │                                                      │
        │  ┌─────────────────────────────────────────────┐    │
        │  │         PERSISTENCE LAYER                    │    │
        │  │                                              │    │
        │  │  data/kline_cache.json    (K-line snapshot)  │    │
        │  │  data/state/*.json        (runtime state)    │    │
        │  │  data/ledger/*.jsonl      (daily candidates)  │    │
        │  │  config/strategy_params.json (strategy cfg)  │    │
        │  └─────────────────────────────────────────────┘    │
        └─────────────────────────────────────────────────────┘
```

---

## 13. Piper 生态系统对接分析

### 13.1 Remote Infrastructure

The `.env` file reveals that the Astock project connects to a remote server at `152.69.201.170` via SSH tunnel. The remote host runs:
- **pup-mcp**: The unified MCP server with three ports (9001 Intel, 9002 Risk, 9003 Exec)
- **iWenCai API proxy**: pup-mcp handles iWenCai API calls using the 5 API keys
- **TDX API proxy**: pup-mcp connects to TDX using `TDX_API_KEY`
- **AGY CLI**: Antigravity CLI at `~/.local/bin/agy` with fallback to Gemini models

### 13.2 Piper Data Chain

The full upstream chain appears to be:

```
TDX Data Server / iWenCai API / Market Data APIs
    |
    v
pup-mcp (Golang/Python MCP server on 152.69.201.170)
    |-- Intel Module (port 9001): Data aggregation + screening
    |-- Risk Module (port 9002): Risk management + blacklist
    |-- Exec Module (port 9003): Broker order execution
    |
    v
SSH Tunnel (encrypted, key-based auth)
    |
    v
Astock Python Modules (localhost)
```

Key `.env` configurations:
- `MCP_MODE=ssh-tunnel` (default connectivity method)
- `ASTOCK_DRY_RUN=1` (currently in dry-run mode, no real orders)
- `ASTOCK_MCP_DRY_RUN=1`
- SSH key at `/home/wade/workspace/config/keys/ssh-key-2024-06-19.key`
- SSH user: `ubuntu`

### 13.3 What Runs on Remote vs Local

| Component | Location | Notes |
|-----------|----------|-------|
| pup-mcp (all 3 ports) | **Remote** (152.69.201.170) | Core data aggregation |
| TDX connection | **Remote** | Handled by pup-mcp |
| iWenCai connection | **Remote** | API keys used by pup-mcp |
| MCPClient | **Local** (Astock) | HTTP JSON-RPC passthrough |
| Strategy logic | **Local** (Astock) | All scoring, screening, analysis |
| K-line cache | **Local** (Astock) | `data/kline_cache.json` |
| State files | **Local** (Astock) | `data/state/*.json` |
| AGY CLI | **Local** (Astock) | `~/.local/bin/agy` |
| APScheduler | **Local** (Astock) | `scripts/scheduler.py` |

---

## 14. Raw Remote Provider Chain

### 14.1 TDX (通达信) Integration

TDX is accessed **exclusively through pup-mcp**. The following Intel MCP tools are TDX-backed:

| Tool | TDX Source | Data Format |
|------|-----------|-------------|
| `tdx_kline` | TDX K-line database | OHLCV bars with hfq adjustment |
| `tdx_quotes` | TDX real-time quote feed | `{price, change_pct, open, high, low, volume}` |
| `tdx_screener` | TDX stock screener | Filtered stock list |
| `tdx_f10` | TDX F10 fundamentals | `{module: "basic"/"finance"/"research"}` |
| `tdx_news` | TDX news feed | News items per symbol |
| `tdx_health` | TDX market health metrics | Health score |

### 14.2 iWenCai (问财) Integration

iWenCai is used for NLP-based stock screening. All queries go through `wencai_search` which routes to iWenCai's API via pup-mcp. The `.env` has 5 API keys suggesting load distribution/fallback.

| Consumer | Query Type | Example |
|----------|-----------|---------|
| `discovery/full_market_discovery.py` | 5 parallel queries | "股价突破20日均线 涨幅大于3%..." |
| `discovery/auction_scanner.py` | Auction gap-up | "集合竞价 涨幅3%到7.5%..." |
| `discovery/theme_trigger.py` | Deep-screen themes | "涨停 {theme} 连板 非ST" |
| `intelligence/sector_flow.py` | Sector flow fallback | "行业板块 资金净流入..." |

### 14.3 Financial Data Provider

Fund flow, chip distribution, technical indicators, and financial reports come from a financial data provider accessed through pup-mcp. The specific provider is **not named in code** -- it's abstracted behind the pup-mcp interface.

---

## 15. Configuration & Secrets

### 15.1 Configuration Files

| File | Purpose | Loaded By |
|------|---------|-----------|
| `config/settings.yaml` | MCP ports, trading hours, risk params, feishu, agy | `config/__init__.py` via `load_yaml()` |
| `config/strategy_params.json` | Strategy params, sell rules, catalyst types | `core/strategy.py`, `execution/pipeline.py` |
| `.env` | API keys, SSH config, dry-run flags | `scripts/mcp_tunnel.py`, pup-mcp on remote |
| `config/__init__.py` | Path constants (DATA_DIR, STATE_DIR, etc.) | All modules |

### 15.2 Secrets Audit

| Secret | Location | Risk |
|--------|----------|------|
| iWenCai API Key (x5) | `.env` (plaintext) | **HIGH** -- committed to repo? |
| TDX API Key | `.env` (plaintext) | **HIGH** |
| SSH Private Key | `/home/wade/workspace/config/keys/` | **HIGH** |
| Feishu Webhook | `settings.yaml` (empty) | **LOW** (empty/placeholder) |

The `.env` file is at the project root and `.gitignore` should exclude it. The SSH key is outside the project directory.

---

## 16. Reproduction Guide

### 16.1 To Reproduce the Live Trading Environment

1. Ensure SSH tunnel is up: `python3 -m scripts.mcp_tunnel start`
2. Verify connectivity: `python3 -m scripts.mcp_tunnel check`
3. Start the scheduler: `python3 -m scripts.scheduler` or `python3 scripts/scheduler.py`
4. Run system check: `python3 -m scripts.check_system`

### 16.2 To Reproduce Backtests

**Using MCP directly (requires tunnel)**:
```bash
python3 -m scripts.backtest_engine --start 2026-06-01 --end 2026-09-30 --capital 400000
python3 -m scripts.backtest_v5 --start 2026-06-01 --end 2026-09-30 --capital 400000
python3 -m scripts.backtest_v6 --start 2026-06-01 --end 2026-09-30
```

**Using cached K-line data (offline, no tunnel needed)**:
```bash
python3 scripts/backtest_3m.py
python3 scripts/backtest_notes_strategies.py --all
python3 scripts/backtest_ma_strategies.py
```
These read from `data/kline_cache.json` and do not make MCP calls.

### 16.3 To Expand the K-line Cache

```bash
python3 scripts/expand_kline_cache.py
```
This requires the MCP tunnel to be active.

---

## 17. Risk & Findings

### 17.1 Critical Findings

| # | Finding | Severity | Section |
|---|---------|----------|---------|
| F1 | **kline_cache.json has no metadata** -- no dump date, source, or adjustment status | **HIGH** | 5.3, 9.2 |
| F2 | **Fund flow safety check FAILS OPEN** when data unavailable -- returns `is_safe=True` | **HIGH** | 10.2 |
| F3 | **No backtest parity for non-K-line data** -- fund flow, financials, news, screening cannot be reconstructed | **HIGH** | 7.2 |
| F4 | **Backtest live regime detection uses DIFFERENT algorithm** -- `compute_regime_sentiment()` vs `MarketRegime.detect()` | **MEDIUM** | 8.2 |
| F5 | **SSH tunnel is single point of failure** -- all MCP calls fail if tunnel is down | **HIGH** | 6.1 |
| F6 | **iWenCai API keys in .env (5 keys)** -- plaintext, potential exposure | **MEDIUM** | 15.2 |
| F7 | **Symbol key format mismatch** -- `kline_cache.json` uses `{SYMBOL}_{COUNT}` but cost_model expects `{SYMBOL}` | **LOW** | 11.2 |
| F8 | **No TTL/refresh mechanism for kline_cache.json** -- unlimited staleness | **MEDIUM** | 9.2 |

### 17.2 Data Integrity Risks

1. **Stale K-line cache**: Backtests using `kline_cache.json` from June 2026 cannot test September 2026 data
2. **Missing symbols**: Newly listed stocks won't be in the cache until `expand_kline_cache.py` runs
3. **Corporate actions**: If TDX re-bases hfq adjustments, old cache entries become inconsistent
4. **No audit trail**: Cannot trace which MCP call produced which cache entry

### 17.3 Operational Risks

1. **Remote dependency**: All live trading requires the remote `pup-mcp` server
2. **No local data backup**: If remote server loses data, Astock has no fallback
3. **Silent failures in discovery**: wencai_search failures are caught and produce empty results -- missing candidates silently
4. **Degraded mode inconsistency**: When Risk MCP is down, `degraded_risk_check()` uses a DIFFERENT set of checks than the full `RiskManager.check_intent()`

---

## 18. Recommendations

### 18.1 Immediate (P0)

1. **Add metadata to `kline_cache.json`**: Include `dump_date`, `source` ("TDX-hfq-via-pup-mcp"), `adjustment` ("hfq"), and `count` as top-level keys
2. **Fix fund flow FAIL-OPEN**: Change `evaluate_fund_flow_safety()` to return `is_safe=False` when degraded, or add a strict mode
3. **Document cache staleness**: Add a README in `data/` explaining when the cache was built and how to refresh it

### 18.2 Short-term (P1)

4. **Harmonize symbol key format**: Standardize on `{code}.{market}` without count suffix, or add a mapping layer
5. **Add versioning to state files**: Include schema version in `market_regime.json`, `sentiment.json`, etc.
6. **Create PIT-aware regime detection for backtests**: Ensure all backtest scripts use the same regime detection as the live path
7. **Implement backtest fund flow simulation**: Record historical fund flow for backtest parity (or document the gap explicitly)

### 18.3 Long-term (P2)

8. **Consider local MCP server**: Reduce dependency on SSH tunnel and remote server
9. **Implement data freshness checks**: Add TTL-based validation for cached data
10. **Build a data lineage registry**: Automated tracking of which data comes from which provider through which path
11. **Add circuit breaker telemetry**: Log when degraded mode is activated and why

---

## 19. Appendix - File-to-Data-Mapping

### Data Producers (acquire or compute data)

| File | Data Produced | Destination |
|------|--------------|-------------|
| `mcp_client.py` | All MCP call wrappers (K-line, quotes, fund flow, news, etc.) | Callers |
| `scripts/expand_kline_cache.py` | `kline_cache.json` | `data/kline_cache.json` |
| `core/sentiment_engine.py` | `sentiment.json`, sentiment block in `strategy_params.json` | `data/state/sentiment.json`, `data/state/strategy_params.json` |
| `core/market_regime.py` | `market_regime.json` | `data/state/market_regime.json` |
| `discovery/full_market_discovery.py` | Candidate pool from wencai | In-memory, consumed by theme_trigger |
| `discovery/auction_scanner.py` | Auction candidates | In-memory, written to JSONL ledger |
| `discovery/limitup_scanner.py` | Limit-up ladder with grades | In-memory |
| `discovery/theme_trigger.py` | Themed seeds | In-memory |
| `discovery/leader_monitor.py` | Leader snapshot | In-memory (printed/notified) |
| `intelligence/sector_flow.py` | Sector flow AGY analysis | stdout / feishu |
| `execution/pipeline.py` | Candidate validation, intents, trade records | JSONL ledger |
| `execution/direct_executor.py` | Order execution, trade reconciliation | JSONL ledger |
| `execution/auction_kill_switch.py` | Kill switch candidates | JSONL ledger |
| `scripts/scheduler.py` | Orchestration (cron trigger) | All modules |

### Data Consumers (read data)

| File | Data Consumed | Source |
|------|--------------|--------|
| `scripts/backtest_engine.py` | MCP K-line (fetch_kline) | MCP port 9001 |
| `scripts/backtest_v5.py` | MCP K-line (fetch_kline) | MCP port 9001 |
| `scripts/backtest_v6.py` | MCP K-line (fetch_kline) | MCP port 9001 |
| `scripts/backtest_2yr.py` | `kline_cache.json` + MCP K-line | `data/kline_cache.json`, MCP |
| `scripts/backtest_3m.py` | `kline_cache.json` | `data/kline_cache.json` |
| `scripts/backtest_notes_strategies.py` | `kline_cache.json` | `data/kline_cache.json` |
| `scripts/backtest_ma_strategies.py` | `kline_cache.json` | `data/kline_cache.json` |
| `scripts/backtest_ignition.py` | MCP K-line (fetch_kline) | MCP port 9001 |
| `core/chanlun_engine.py` | Normalized K-line bars | Caller provides |
| `core/strategy.py` | K-line bars (via callers) | Caller provides |
| `core/sentiment_engine.py` | MCP quotes (query_batch_data), regime state | MCP, `data/state/market_regime.json` |
| `core/market_regime.py` | MCP quotes (query_batch_data) | MCP |
| `core/market_regime_check.py` | MCP quotes, market_health, regime state | MCP, `data/state/market_regime.json` |
| `execution/direct_executor.py` | MCP quotes, positions, orders, JSONL ledger | MCP (all 3 ports), `data/ledger/` |
| `execution/pipeline.py` | Strategy params, positions, balance, risk checks | MCP, `data/state/` |
| `risk/risk_manager.py` | MCP balance, positions, blacklist, health | MCP (9002, 9003, 9001) |
| `utils/fund_flow.py` | MCP fund flow, TTL cache | MCP, in-memory cache |
| `intelligence/agy_bridge.py` | AGY CLI (subprocess) | `~/.local/bin/agy` |
| `scripts/run_premarket.py` | Sentiment, regime | `core/sentiment_engine`, `core/market_regime` |

### Pure Logic (no data I/O)

| File | Purpose |
|------|---------|
| `core/cost_model.py` | Buy/sell cost calculation (brokerage + stamp + transfer) |
| `core/strategy_profiles.py` | Strategy profile definitions |
| `utils/market.py` | Market type classification, limit price calculation |
| `condition_evaluator.py` | Intraday condition gate evaluation |
| `utils/broken_guard.py` | Broken seal / fake healing detection |
| `utils/leader_universe_filter.py` | Leader universe filtering |
| `utils/strategy_circuit_breaker.py` | Strategy circuit breaker state machine |
| `evolution/performance_reporter.py` | Performance report generation |
| `evolution/strategy_audit.py` | Strategy audit analysis |

---

**Report Complete.**

**Total Files Audited**: 40+ Python files + all JSON/YAML configs  
**MCP Tools Documented**: 26 Intel + 4 Risk + 6 Exec = 36 total  
**Data Types Traced**: K-line, Index, Fund Flow, Financial, News, Sector/Themes, Sentiment, Market Regime  
**Backtest Paths Analyzed**: 8 distinct backtest scripts  
**Critical Findings**: 8 identified, 3 P0, 4 P1, 3 P2
