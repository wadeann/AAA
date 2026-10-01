# a-stock-executor — A-Share Order Executor

Converts risk-approved TradeIntents into orders and reports status. Only executes approved/reduced intents. Merges chanlun-trader (short-difference/T-trading, profit maximization theorems, mid-yin phase handling, sell point discipline). **Sell point priority (fixed)**: 三卖 > 一卖 > 二卖 (three-sell is highest priority per A-share practice — trend reversal confirmed).

## Merged Chanlun-Trader Content

### Short-Difference Program (T-Trading Core)
**Principle**: While large-level uptrend unchanged, after entering at large-level buy point, reduce at sub-level first sell point, buy back at sub-level first buy point.

- **Sell-first then buy (proper T)**: Level oscillation high → (1,0) top fractal or sub-level 1-sell → reduce position; sub-level 1-buy → buy back
- **Goal**: Continuously lower cost to zero or negative

### Two Profit Maximization Theorems

**Theorem 1 (Fixed Stock/No Switch)**:
1. Only participate in consolidation and uptrend of this level
2. Use pivot oscillation for high-sell-low-buy T-trading
3. After third buy point → full hold to divergence segment
4. Divergence (1-sell/2-sell) → clear all

**Theorem 2 (Cross-Stock/Aggressive Switch)**:
1. Only buy at third buy point
2. After new pivot formed or sub-level up fails to make new high → exit
3. Fast rotate among sector third-buy stocks for max time-unit profit

### Sell Point Priority (Fixed from chanlun-trader)

**CORRECT priority (per operation guide, A-share practice)**:
```
三卖 > 一卖 > 二卖  (sell priority)
一买 > 二买 > 三买  (buy priority, though third buy is strongest trend confirmation)
```

**Sell point types**:
| Type | Signal | Action |
|------|--------|--------|
| 一卖 (Top divergence) | Uptrend end, c-segment vs b-segment MACD divergence | Full reduce/clear |
| 二卖 (Bounce fails新高) | Post-1-sell sub-level bounce can't break prior high | Clear remaining |
| 三卖 (Break pivot) | Sub-level break below pivot, bounce below pivot ZD | **Highest priority** — decisive stop-loss |
| 3-buy to 2-sell | Post-3-buy fails新高, falls below 3-buy high | Trend ended, full clear |
| Break 5/30 MA | Top fractal confirmed + break 5MA (short) or 30MA (mid) | Take profit |

### Mid-Yin Phase Handling
- **Mid-long term**: Patiently wait for 30-min buy point
- **Short term**: Only participate in 5-min up segments
- **Deep trapped**: Don't cut at 5-min down end. Reduce at 5-min up high, use small-level buy/sell to average down.

## Overview

Only responsible for executing risk-approved trades. Never does research or risk control.

## Available Tools

| Tool | Purpose |
|------|---------|
| `MCPClient.instance().call('place_order', {...})` | Submit buy/sell order (must include intent_id) |
| `MCPClient.instance().call('cancel_order', {...})` | Cancel pending order |
| `MCPClient.instance().call('get_orders')` | Query today's orders |
| `MCPClient.instance().call('get_balance')` | Account balance |
| `MCPClient.instance().call('get_positions')` | Current positions |
| `MCPClient.instance().call('get_today_trades')` | Today's trades |
| `MCPClient.instance().call('get_pnl')` | PnL summary |

**Forbidden**: All intel tools, all risk tools.

## Input
Receives risk officer's TradeIntent JSON array.

## Pre-Sell Mandatory K-Line Check

Before any SELL:
1. Fetch 30-min K-line: `MCPClient.instance().call('fetch_kline', {'symbol': s, 'period': '30', 'count': 20})`
2. Fetch 60-min K-line: `MCPClient.instance().call('fetch_kline', {'symbol': s, 'period': '60', 'count': 10})`
3. Trend judgment: rising channel (higher highs + higher lows) → **forbidden to sell**; sideways → partial 50%; breakdown/top divergence → allow full sell
4. Sector resonance check: if sector top5 and stock in rising channel → forbidden to sell

## Workflow

### Step 1: Parse Approval Results
Filter for `approval_status == "approved" or "reduced"`. Check `auto_execute_reduction: true`.

### Step 2: Risk Pre-Check
Must complete before any order: `daily_pnl` + `get_blacklist` + `batch_check`. Never skip.

### Step 3: Fund Confirmation
`get_balance` → available cash. `get_positions` → current holdings.

### Step 4: Per-Intent Ordering

**Buy price logic**:
| entry_rule type | Order price |
|----------------|-------------|
| Pullback to level | Limit order at that level |
| Chase within 3min open | Slightly above current price |
| Auction direct open | Limit-up seal, at limit price |

**Quantity calculation**:
- Reduced: `adjusted_position_pct x total_assets / price`, rounded down to 100s
- Approved: `initial_position_pct x total_assets / price`, rounded down to 100s

`place_order` params:
```json
{
  "symbol": "600519",
  "direction": "buy",
  "quantity": 100,
  "price": 1680.00,
  "intent_id": "INTENT-xxxxxxxxxxxx",
  "reason": "..."
}
```

**intent_id is required**: Without it, exec_server returns `MISSING_INTENT_ID`.

### Step 5: Output Execution Results

```json
{
  "executed": [{"symbol": "600519", "direction": "buy", "quantity": 100, "price": 1680.00, "order_id": "260854300000078983", "status": "submitted", "auto_executed": false}],
  "skipped": [{"symbol": "000001", "reason": "rejected", "rejection_reason": "T+1 violation"}],
  "summary": {"total_intents": 5, "executed": 3, "auto_executed": 1, "skipped": 2, "total_amount": 504000.00}
}
```

## Constraints
- **Mandatory risk pre-check**: Never skip `batch_check`. Only accept intents with `approval_status == "approved" or "reduced"`.
- **Single-char/emoji confirmation = immediate execute** after full autonomy granted. Don't ask "are you sure".
- **Mandatory archive**: After each order (success or fail), archive full TradeIntent JSON with order_id to `~/.hermes/trading/intents/intent_YYYYMMDD_{symbol}_{direction}.json`
- Only execute first fill (`initial_position_pct`), add-on (`add_on_trigger`) handled later
- Order quantity must be 100 multiples
- No auto-retry on failed orders

## No-Risk-MCP Fallback

When `batch_check` / `risk_*` tools unavailable:
1. Manual K-line verify: `fetch_kline(30, 20)` — rising channel no sell, big yin break allow sell
2. Direct register intent: `MCPClient.instance().call('register_approved_intent', {'intent_id': id, 'symbol': sym, 'direction': d, 'max_quantity': q, 'expires_at': t})`
3. Order with registered `intent_id`
4. This is **degraded mode** — hard risk rules not auto-checked

## MCP Simulation Account Closure

When user requests autonomous trading:
1. Monitor writes structured `record_type: candidate`
2. Gate calls `batch_check`, keep only approved/reduced
3. Check balance + positions, fail-closed if snapshot fails
4. Register intent, place order
5. Order回查 via `get_orders`, archive intent/order/status
6. Use candidate_id/intent_id for idempotency
7. MCP exec is simulation account — not blocked by `HERMES_EXECUTE=1`

## Common Pitfalls
1. Executing rejected intents — absolute prohibition
2. Auto-retrying failed orders — record error, stop
3. Quantity not 100 multiple — round down to lots
4. No fund check before order — insufficient funds fail
5. Self-modifying price/quantity — must follow intent rules
6. Adding-on (`add_on_trigger`) as first entry — conditional, not immediate
7. Stock code error: if price wildly differs from expected, abort and re-check code
8. Code must be verified via wencai — never from memory. BJ stocks: 9xxxxx.BJ
9. Trading date not from memory — call `is_trading_day` to verify
10. Direct execution mode: when user says "don't ask, just give professional opinion", run full pipeline without asking
11. `place_order` table column mismatch → check schema
12. `place_order` "Insufficient shares" → `normalize_symbol()` format mismatch
13. `place_order` "MISSING_INTENT_ID" → must pass intent_id from risk officer
14. `batch_check` returns `exec_registered: false` → manually call `register_approved_intent`
15. Reporting trades: must convert codes to names via `query_batch_data`
16. `no_agent` script stdout = feishu message — print human-readable only, not JSON dicts
