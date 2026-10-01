# Wencai Backtest Framework

## Why wencai works for backtesting

wencai MCP stores and returns historical price/volume/limit-up data at the day level. Unlike real-time MCP endpoints that only show current prices, wencai accepts date-prefixed field names and returns structured multi-column data.

## Available queries

### Monthly ranking
```
wencai("2026年8月涨停天数最多的股票 top20")
```
Returns: `datas[0][股票代码, 股票简称, 涨停[20260803-20260831]数量, 连板次数[20260803-20260831]]`

### Date-specific prices
```
wencai(f"{code} 2026-08-03 收盘价 开盘价")
```
Returns: `datas[0][收盘价[20260803], 开盘价[20260803]]`

### Per-date field queries
```
wencai(f"{code} 首板涨停日期 2026年8月")
wencai(f"{code} 2026年8月 涨停日期 涨停封板时长")
wencai(f"{code} 2026年8月 涨停日期 一字板 封板时间")
```
Per-date fields use date-specific keys:
- `一字涨停[20260804]` — whether day was a one-character limit-up
- `涨停封板小时数[20260804]` — hours board was locked
- `首板涨停[20260804]` — whether first board on that date

## Simulation model

```
cash_per_ticket = total_assets × strategy_pct
simulated_pnl = cash_per_ticket × ((1 + one_board_gain) ** tradable_boards - 1)
```

Where:
- `strategy_pct` = 0.20 (打板/连板), 0.35 (缠论/波段), 0.15 (恐慌抄底)
- `one_board_gain` = 0.08 (8%, accounts for slippage + fees)
- `tradable_boards` = max(1, int(zt_count × 0.3)) — 30% catch rate for hand-tradeable boards

## Known limitations

1. Day-level only: cannot simulate tick/5min intraday fill timing, gap openings, false breakout traps
2. 30% catch rate is a linear estimate: real catch rate varies by stock liquidity, market phase, and execution method
3. No allowance for炸板 (board explosion) or failed limit-up queue
4. Winner-only bias: backtest only covers pre-identified winners; production scanners must discover from the full market
5. wencai field naming is inconsistent across stocks — some have `首板涨停`, others don't; fallback to `涨停封板小时数 > 0`
6. JSON returns can be deeply nested; must handle `datas[0]` being list vs dict

## Scripts

- `scripts/agy_backtest.py` — daily real PnL recording (no_agent cron)
- `scripts/agy_historical_backtest_v2.py` — full-month wencai simulation
