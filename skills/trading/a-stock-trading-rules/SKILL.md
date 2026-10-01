# a-stock-trading-rules — A-Share Trading Global Rules Reference

Global rules framework for the A-share trading system: responsibility isolation, data contracts, hard risk-control rules, execution constraints. Load this skill for the complete trading system rule framework. **Do NOT load into cron jobs** — rules text will drown agent reasoning.

## Quick Index

| Need | Location |
|------|----------|
| TradeIntent JSON / catalyst_type enum | [Data Contract](#-data-contract--tradeintent-json) |
| First-principle stock selection | [First-Principle Selection](#-first-principle-stock-selection) |
| Reversal quantification framework | [Reversal Decision Framework](#-reversal-decision-framework) |
| Pre-sell K-line check + position 3-classification | [Pre-Sell K-Line Check](#-sell-discipline-three-category-position-model) |
| Risk hard rules (T+1, price limits, position) | [Risk Hard Rules](#risk-hard-rules-risk-mcp-server-enforced) |
| MCP tool mapping | [MCP Tool Mapping](#mcp-tool-mapping) |

## First-Principle Stock Selection

All buy decisions must pass three gates:

### Gate 1: Supply-Demand Gap
- Why is this scarce?
- Supply barriers (policy/technology/resource/license)?
- Demand non-substitutable?

### Gate 2: Purple Perilla Five Factors
- Supply-demand gap / Barrier / Lock-in (customer stickiness) / Attention (market hot money inflow) / Performance (revenue/profit growth)
- True purple perilla: real demand + limited supply + >= 3 checks
- No supply barrier → **direct PASS**

### Gate 3: Guihai Yidao Main Uptrend Verification
- Must be one of 8 limit-up forms (attack chase line / lookout / advance-two-retreat-one / volume-through-top / etc.)
- PASS: liquidity < 50M daily avg volume / pure concept no fundamentals / can't explain "why scarce"

## Reversal Decision Framework

### One-Vote Veto (any true → NOT a reversal)
| Condition | Rule | Data Source |
|-----------|------|-------------|
| MA5 < MA10 < MA20 bearish alignment | By close, not intraday | `MCPClient.instance().call('get_technical_indicators', ...)` → MA_5/10/20 |
| MACD DIF < DEA (dead cross) | State-based, not single bar | Same → DIF, DEA |
| MACD DIF and DEA both < 0 | Underwater dead cross | Same |
| 20-day main force net outflow > 500M accelerating | Large capital cutting | `MCPClient.instance().call('get_fund_flow', ...)` |
| Peak-to-current drop > 50% no volume bottom fractal | Downtrend segment not ended | `MCPClient.instance().call('fetch_kline', ...)` 60-day |

### Four-Dimension Matrix (must score >= 8/17)
| Dimension | Scoring (max) | Tool |
|-----------|---------------|------|
| MA alignment | 4 | `get_technical_indicators → MA` |
| Main force capital | 4 | `get_fund_flow` |
| K-line structure | 5 | `fetch_kline(D, 60)` + technical indicators |
| Sector resonance | 4 | `wencai_search` + `fetch_sector_history` |

## Sell Discipline: Three-Category Position Model

| Category | Criteria | Primary Track | Sell Rules |
|----------|----------|---------------|------------|
| **Trend Stock** | Main uptrend + sector top5 + K-line rising channel | Track B (supply-demand) | Don't sell if supply-demand logic intact. No hard stop. Sell on structure breakdown / top divergence |
| **Swing Stock** | Clear catalyst, non-main uptrend | Dual track | Hard stop -6%~-15% + expiration forced exit. Also check Track B |
| **Event Stock** | News-driven, no fundamentals/chart | Track B | News realized → leave immediately, hold <= 2 days |

### Dual-Track Pre-Sell Check

**Track A — Technical**:
| Condition | Action |
|-----------|--------|
| Hard stop-loss broken | Unconditional full close |
| Target reached | Half position, raise stop |
| Trend breakdown / top divergence | Full clear |

**Track B — Supply-Demand Logic**:
| Check | Standard | Data |
|-------|----------|------|
| B1: Gap fading | Supply bottleneck relieved / demand below expectations | wencai + news |
| B2: Purple perilla fading | Barrier lowered / lock-in loosened / overheated | wencai (gain / research density) |
| B3: Catalyst realized | Earnings / contract / policy already priced in | news timeline |
| B4: First-principle breach | Demand uncertainty / pricing power loss | query_data + wencai |

## Data Contract — TradeIntent JSON

```json
{
  "symbol": "600519",
  "market": "SSE",
  "thesis": "[缺口逻辑] ...purple perilla 5 factors...",
  "direction": "buy",
  "confidence": 0.8,
  "catalyst_type": "technical_breakout",
  "entry_rule": {
    "initial_entry": "Buy near 1650",
    "initial_position_pct": 0.05,
    "add_on_trigger": "Close above 1700, add to max",
    "add_on_position_pct": 0.05
  },
  "exit_rule": {
    "stop_loss": "Below 1620 unconditional",
    "target_profit": "Hit 1800 half close",
    "trailing_stop": "After target, break 10MA full close"
  },
  "max_position_pct": 0.10,
  "time_horizon": "5d",
  "valid_until": "2026-04-05T15:00:00+08:00",
  "risk_notes": "",
  "tool_evidence": [],
  "market_condition": "BULL",
  "approval_status": "pending"
}
```

### catalyst_type Enum & Holding Rules

| Type | Meaning | valid_until max | Stop-profit logic |
|------|---------|-----------------|-------------------|
| news_event | News/announcement driven | 2 trading days | News fades → exit immediately |
| technical_breakout | Volume-price breakout | 10 trading days | Moving average trailing stop |
| sector_rotation | Sector rotation | 3 trading days | Sector cools → reduce |
| earnings | Earnings driven | 5 trading days | +/-1 day buffer around earnings date |

### market_condition & Position Coefficient

| Condition | Criteria | max_position_pct multiplier |
|-----------|----------|----------------------------|
| BULL | Index above 20MA + northbound inflow | x1.0 |
| NEUTRAL | Index near 20MA震荡 | x0.7 |
| BEAR | Index below 20MA + volume shrinking | x0.5 |

### Confidence Thresholds
- Research output: confidence < 0.65 not output
- Strategist filter: confidence < 0.65 filter
- BEAR market: all intent confidence forced -0.2
- sector_rotation historical win rate < 25%: confidence forced -0.1, max_position_pct capped at 0.05
- Industry dispersion: max 2 candidates per industry per pipeline

## Risk Hard Rules (Risk MCP Server Enforced)

1. T+1: Same-day buy cannot be sold same-day; same-day sell cannot buy same-day; no same-direction repeat same-day
2. No limit-up chase: gain >= 9.8% (ST 4.8%)
3. No limit-down bottom-fish: drop <= -9.8% (ST -4.8%)
4. Industry concentration: single industry <= 40% total assets
5. Daily loss circuit breaker: cumulative loss > 3% total assets → pause all new positions
6. Daily loss accelerated: > 5% → auto execute reduction suggestions
7. Problem stocks: ST / suspended / delisting risk → prohibited
8. Trading hours: only 09:30-11:30, 13:00-15:00
9. Auction periods: 09:15-09:25, 14:57-15:00 → limit orders only
10. Liquidity (large cap): 5-day avg < 10M daily → prohibited
11. Liquidity (small cap exception): market cap < 5B, threshold 5M, position cap 10%
12. Order unit: 100 shares multiples
13. valid_until expiry: expired TradeIntent auto-invalid
14. Half-life: time_horizon half past without first fill → confidence -0.1, if < 0.65 auto-invalid

## MCP Tool Mapping

Use `MCPClient.instance().call(tool_name, arguments)` pattern. Port auto-detected.

### Intel Tools (Port 9001)
| Tool | Description |
|------|-------------|
| `query_data` | Quote, financial, technical data |
| `query_batch_data` | Batch quote query |
| `fetch_kline` | K-line (period: 1/5/15/30/60, count: 100 for Elliott wave) |
| `wencai_search` | Natural language stock screening |
| `search_news` | News, research, announcements |
| `screen_stocks` | Multi-factor stock screening |
| `get_watchlist` | Query watchlist |
| `update_watchlist` | Add/remove watchlist stocks |
| `is_trading_day` | Check if trading day |
| `trading_sessions` | Get current trading session |
| `fetch_market_health` | Market health score + index snapshot |
| `fetch_hot_signals` | Hot signals / limit-up signals |
| `fetch_sector_history` | Sector historical data |
| `get_fund_flow` | Main force fund flow |
| `get_chip_distribution` | Chip distribution / concentration |
| `get_technical_indicators` | MA/MACD/KDJ/RSI/BOLL/BIAS |
| `get_financial_report` | Financial statements |
| `get_limitup_ladder` | Limit-up ladder |
| `get_mainline_lanes` | Main line track scoring |

### Risk Tools (Port 9002)
| Tool | Description |
|------|-------------|
| `check_intent` | Single TradeIntent risk check |
| `batch_check` | Batch risk check |
| `get_blacklist` | Get blacklisted stocks |
| `daily_pnl` | Get daily PnL |

### Exec Tools (Port 9003)
| Tool | Description |
|------|-------------|
| `place_order` | Submit order (must include intent_id) |
| `register_approved_intent` | Register approved intent |
| `cancel_order` | Cancel pending order |
| `get_orders` | Query today's orders |
| `get_balance` | Query account balance |
| `get_positions` | Query current positions |
| `get_today_trades` | Query today's trades |
| `get_pnl` | Query PnL summary |
| `sync_position` | Sync position |
| `top_up_cash` | Adjust account cash |

### Responsibility Isolation

| Role | Allowed | Forbidden |
|------|---------|-----------|
| Researcher | Intel all | Risk all, Exec all |
| Strategist | Intel (query, screen, trading_day, sessions, wencai, market_health) | Risk all, Exec all, Intel search_news |
| Risk Officer | Risk all, Exec read-only (balance, positions, trades, pnl) | Intel all, Exec place/cancel |
| Executor | Exec all | Intel all, Risk all |
| Reviewer | Intel (query, news, trading_day), Exec read-only | Risk all, Exec place/cancel |

### MCP Data Pitfalls
- `get_positions` returns code only (e.g. `603738.SH`), not stock name. Must use `query_batch_data` to get names.
- `query_data` returns only 3 fields (name, price, change%). Use `wencai_search` for full data.
- Stock code must be verified via `wencai_search` before placing order. Never input from memory.
- Beijing Exchange stocks: code starts with `9`, suffix `.BJ` (e.g. 920522.BJ).
- Before saying "today is weekend/non-trading day", call `is_trading_day` to verify.
- T+1 check: sell using `available_shares`, not `quantity`.

## AGY God-Stock Audit Key Fixes (Commit 7e7976e)

### Iron Rule Four-Gate Framework (market_regime_check.py)

```python
def iron_rule_gate(candidate, now_cst):
    # Gate 0: Sell exemption
    if direction == "sell": return True
    # Gate 1: Strategy circuit breaker
    is_blocked, reason = check_strategy(catalyst_type)
    if is_blocked: return False
    # Gate 2: Market regime
    regime = get_market_regime()
    if regime == "极寒": return False
    if regime == "退潮" and subtype != "exhaustion_ebb":
        if not is_sector_leader: return False
        if target_change_pct >= 1.5: return False
    # Gate 3: Leader universe filter
    # Gate 4: Garbage time (10:00-14:30) non-leader + chase reject
    # Gate 5: streak >= 3 buy reject
    return True
```

### Key Deployed Files
| File | Path | Function |
|------|------|----------|
| market_regime.py | ~/.hermes/scripts/ | Market regime (4-dim: ChiNext/median/volume/limit-up) |
| strategy_circuit_breaker.py | ~/.hermes/scripts/ | Strategy breaker (2 consecutive losses → 7 day cooldown) |
| leader_universe_filter.py | ~/.hermes/scripts/ | Leader pool (unique position + 800M volume + 2 boards in 10 days) |
| market_regime_check.py | ~/.hermes/scripts/ | Iron rule aggregate gate |
| direct_executor.py | ~/.hermes/scripts/ | Inject iron_rule_gate check |

### Ebb Type Differentiation (market_regime.py)
| Subtype | Trigger | Scanner behavior | Position |
|---------|---------|-----------------|----------|
| initial_ebb (early ebb) | Day 1-2, broken seal < 45% | All scanners HALT | 0% |
| panic_ebb | Day 2+, broken seal >= 45% | All scanners HALT | 0% |
| exhaustion_ebb | Day 4+, broken seal < 30% | TDX pullback scanner mini-mode | <= 10% mini position |

### Key Rules: streak >= 3 Buy Reject
All buy candidates with streak >= 3 must be blocked by iron_rule_gate (Gate 5). This is a hard physical barrier, not just a recommendation.

### Position Sizing: Strategy Recommendations vs Hard Limits

**Hard Limits (programmatic, enforced by risk MCP server)**:
- Single stock max: not hard-coded (dynamic per intent)
- Industry concentration: 40% max
- Total position: not hard-coded (market-condition dependent)
- Daily loss breaker: 3% pause new, 5% auto-reduce

**Strategy Recommendations (guidance, not programmatically enforced)**:
- Main uptrend full position: 3 stocks max
- Core soul stock: 25-35%
- Ebb/recession: 0% or 10% probe
- These are tactical guidelines, not hard limits enforced by the risk server

### Data Authenticity Iron Rule
Absolute prohibition on fabricating news, catalysts, announcements, or data. Every catalyst must cite its tool source. "Cannot confirm" is the only acceptable fallback.

## References
- `references/agy-stock-god-audit-2026-09-07.md` — Full system strategy audit (58/100), 6 fatal defects
- `references/manual-rebalance-workflow.md` — Manual rebalance workflow
- `references/segmented-market-circuit-breakers.md` — Narrow-base vs wide-base circuit breaker isolation
- `references/script-pipeline.md` — Script-first architecture documentation
- `references/compound-learning-loop.md` — Learning loop documentation
- `templates/trade-lifecycle-report.md` — Full trade lifecycle report template
- `templates/strategy-feedback-template.md` — Strategy feedback template
