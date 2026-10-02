# Backtest Data Flow — 回测数据流与潜在问题

## 一、数据来源

### 1.1 主回测引擎 (backtest_2yr.py)

| 数据 | 来源 | 格式 | 说明 |
|------|------|------|------|
| K 线 | data/kline_cache.json | JSON dict | 预缓存的日线数据 |
| 参数 | config/strategy_params.json | JSON | 主配置 |
| 最佳参数 | results/best_config_{profile}.json | JSON | --use-best 加载 |
| 股票池 | 内置于 backtest_2yr.py | list | ~2348 只 |

### 1.2 缠论回测引擎 (backtest_engine.py)

| 数据 | 来源 | 方式 | 说明 |
|------|------|------|------|
| 日线 | MCP fetch_klines (9001) | 实时 API | 200 根/只 |
| 周线 | MCP fetch_klines period=W (9001) | 实时 API | 100 根/只 |
| 指数 | MCP fetch_klines 000001.SH | 实时 API | 200 根 |
| 市场状态 | data/state/market_regime.json | 状态文件 | 预计算 |
| 股票池 | DEFAULT_POOL / CLI 参数 | list | 20 只+ |

---

## 二、每日回测推进流程

### 2.1 backtest_2yr.py 每日循环

```
for each date in trading_dates:
  1. 执行前日卖出信号 (pending_sells) — 用今日开盘价
  2. SELL 检测 — 用今日 hi/lo/cl，检测到则存入 pending_sells
  3. BUY — 用今日筛选+评分，ed = next_date, 用 next_date 开盘价买入
  4. Equity — 日终市值计算
```

**使用数据**: 每个日期 T 只用到 ≤ T 的 K 线数据
**市场体制**: 用日期 T 及之前的市场宽度 (MA20 比例) 估计

### 2.2 backtest_engine.py 每日循环

```
for each date in trading_dates:
  1. Sentiment: compute_regime_sentiment(index_bars, date)
  2. BUY: analyze_chanlun(lookback≤T) → buy_signal → score → entry_date=T+1, price=open
  3. SELL: analyze_chanlun(lookback≤T) + trailing stop + hard stop + chanlun sell point
  4. Equity: 日终结算
```

---

## 三、关键数据使用检查

### 数据时间戳
- 所有 K 线数据按 time 字段过滤：`str(b.get("time", "")) <= curr_date`
- ✅ 不会用到未来数据

### 市场体制
- `backtest_2yr.py`: 用当日 market breadth 估计体制
- `backtest_engine.py`: 从预计算的 market_regime.json 读取，该文件在回测期间不变
- ⚠️ **Potential Leakage #001**: market_regime.json 是盘后预计算的，可能包含未来信息

### 预缓存数据
- `data/kline_cache.json`: 一次性加载，全部 K 线数据在回测开始时已存在
- 通过 `<= curr_date` 过滤来模拟"当时只能看到过去数据"
- 这是标准的时间序列回测做法，不视为泄漏

---

## 四、Potential Leakage 清单

### Leakage #001: market_regime.json 静态加载
- **Severity**: MEDIUM
- **File**: `scripts/backtest_engine.py:124-148`
- **Description**: 市场状态文件 `market_regime.json` 在回测开始时一次性加载，包含回测期间之外的盘后数据。虽然只用 regime_multiplier/standard_regime 等宏观参数，但这些参数可能基于未来信息生成。
- **Impact**: 实际交易中市场状态是实时计算的，回测使用预先计算的固定值可能高估/低估表现

### Leakage #002: backtest_2yr.py 盘中 high/low 用于 SELL 检测
- **Severity**: LOW
- **File**: `scripts/backtest_2yr.py` (SELL 检测部分)
- **Description**: SELL 检测使用当日的 high/low/close 来判断是否触发卖出。这是 bar-based 回测的标准做法。
- **Note**: 已修正为信号日检测 → 次日开盘执行，不再是泄漏

### Leakage #003: kline_cache.json 预加载所有数据
- **Severity**: LOW
- **File**: `scripts/backtest_2yr.py:118-119`
- **Description**: 所有 K 线数据一次性加载到内存。通过 `<= curr_date` 过滤。
- **Impact**: 无实际泄露，但内存占用大

### Leakage #004: weekly_bars 预加载
- **Severity**: LOW
- **File**: `scripts/backtest_engine.py:356-361`
- **Description**: 周线数据在回测开始时全部加载，通过 `<= curr_date` 过滤使用。

### Leakage #005: sell_rules 使用当日收盘价
- **Severity**: LOW (已修正)
- **File**: `scripts/backtest_2yr.py` (修正前)
- **Description**: 修正前 SELL 信号使用当日收盘价作为卖出价 (future function)。当前版本已改为 D 日检测 + D+1 开盘执行。

---

## 五、数据尺寸

| 数据类型 | 数量 | 大小 |
|----------|------|------|
| K 线缓存 | ~2348 只 × 500 根 | ~200MB |
| 交易日 | 485 天 (2 年) | - |
| 候选日志 | 1 文件/天 | JSONL 格式 |
| 策略参数 | 1 文件 | ~5KB |
| 市场状态 | 1 文件 | ~1KB |
