# Chanlun Rules — 缠论规则

基于 `core/chanlun_engine.py` 的完整缠论计算规则。

## 一、处理管线 (Pipeline)

```
raw OHLCV → normalize_bars → inclusion_process → fractals → strokes → segments → pivots → divergence → buy/sell points
                      → trend_breakout_signal (并行)
```

---

## 二、各步骤规则

### 2.1 normalize_bars (数据标准化)

| 属性 | 说明 |
|------|------|
| **File** | `core/chanlun_engine.py:21` |
| **Input** | Iterable[dict] — 支持中文/英文键名 |
| **Output** | list[dict] — 6 字段: index, time, open, high, low, close, volume |
| **过滤** | `high <= 0` or `low <= 0` or `close <= 0` or `high < low` 的 K 线丢弃 |
| **open 降级** | 无开盘价时取 `close` |

键名映射:
| 标准字段 | 中文备选 |
|----------|----------|
| high | 最高价 |
| low | 最低价 |
| close | 收盘价, 最新价 |
| open | 开盘价 |
| volume | 成交量 |
| time | date |

`num()` 工具函数: 兼容字符串数字含逗号、None、非数值 → 全部转 float，失败返回 0.0。

---

### 2.2 inclusion_process (K 线包含处理)

| 属性 | 说明 |
|------|------|
| **File** | `core/chanlun_engine.py:39` |
| **Function** | `inclusion_process(bars)` |
| **方向** | 跟随上一个非包含方向; 初始方向 = 1 (向上) |

**包含判定**: `(bar.high ≤ prev.high AND bar.low ≥ prev.low)` OR `(prev.high ≤ bar.high AND prev.low ≥ bar.low)`

**方向更新** (非包含 K 线):
- `bar.high > prev.high AND bar.low ≥ prev.low` → 方向 = 向上 (1)
- `bar.low < prev.low AND bar.high ≤ prev.high` → 方向 = 向下 (-1)
- 否则 → 方向不变

**合并规则**:
| 方向 | high | low |
|------|------|-----|
| 向上 (≥0) | `max(prev.high, bar.high)` | `max(prev.low, bar.low)` |
| 向下 (<0) | `min(prev.high, bar.high)` | `min(prev.low, bar.low)` |

合并后更新: `close = bar.close`, `volume += bar.volume`, `end_index = bar.index`, `time = bar.time`

---

### 2.3 fractals (分型检测)

| 属性 | 说明 |
|------|------|
| **File** | `core/chanlun_engine.py:64` |
| **Function** | `fractals(bars)` |
| **窗口** | 3 根 K 线 (i-1, i, i+1), 范围 [1, len-1] |

**顶分型**: `cur.high ≥ left.high AND cur.high ≥ right.high AND (cur.high > left.high OR cur.high > right.high)`
**底分型**: `cur.low ≤ left.low AND cur.low ≤ right.low AND (cur.low < left.low OR cur.low < right.low)`

输出: `{"kind": "top"|"bottom", "index": i, "price": high|low, "time": cur.time}`

---

### 2.4 strokes (笔连接)

| 属性 | 说明 |
|------|------|
| **File** | `core/chanlun_engine.py:75` |
| **Function** | `strokes(points)` |

**规则**:
1. 相邻分型类型相同 → 取更极端的 (顶取更高, 底取更低), 跳过当前
2. 相邻分型类型不同 → 间隔 ≥ 2 根 K 线才连接
3. 输出方向: `end_price > start_price` → up, else down

输出: `{"from": a.index, "to": b.index, "direction": "up"|"down", "start_price": a.price, "end_price": b.price}`

---

### 2.5 segments (线段)

| 属性 | 说明 |
|------|------|
| **File** | `core/chanlun_engine.py:88` |
| **Function** | `segments(stroke_list)` |

**规则**: 连续 3 笔, 同向笔 ≥ 2 笔 → 构成线段

方向判定: `group[0].start_price < group[-1].end_price` → up, else down

输出: `{"from", "to", "direction", "high", "low"}`

---

### 2.6 pivots (中枢)

| 属性 | 说明 |
|------|------|
| **File** | `core/chanlun_engine.py:100` |
| **Function** | `pivots(stroke_list)` |

**规则**: 连续 3 笔 → ZD = max(lows), ZG = min(highs), ZD < ZG 才构成有效中枢

每笔的 high/low = `max(start_price, end_price)` / `min(start_price, end_price)`

输出: `{"from", "to", "zd": ZD, "zg": ZG, "axis": (ZG+ZD)/2, "width": ZG-ZD}`

---

### 2.7 divergence (背驰检测)

| 属性 | 说明 |
|------|------|
| **File** | `core/chanlun_engine.py:128` |
| **Function** | `divergence(bars, points)` |

**MACD 直方图**: `(DIF - DEA) × 2`, 其中 DIF = EMA(close,12) - EMA(close,26), DEA = EMA(DIF,9)

**顶背驰**: 最后两个顶分型, `b.price > a.price` (新高) 且 `hb < ha × 0.8` (MACD 柱体面积缩小 ≥ 20%)
**底背驰**: 最后两个底分型, `b.price < a.price` (新低) 且 `hb < ha × 0.8` (MACD 柱体面积缩小 ≥ 20%)

ha = 从 a.index 到 b.index 的 |hist| 之和
hb = 从 b.index 到末尾的 |hist| 之和

输出: `{"status": "confirmed"|"none", "type": "top_divergence"|"bottom_divergence"|"none", "first_index", "second_index", "prior_strength", "latest_strength"}`

---

### 2.8 trend_breakout_signal (平台突破)

| 属性 | 说明 |
|------|------|
| **File** | `core/chanlun_engine.py:142` |
| **Function** | `trend_breakout_signal(bars)` |

**条件链**:
1. `len(bars) ≥ 8`
2. 从后往前扫描, 每 8 根 K 线作为 base 窗口
3. `base_high - base_low) / base_low < 12%` → 平台压缩
4. `breakout.close > base_high` AND `breakout.volume > avg_volume × 1.25` → 放量突破
5. 回踩确认: retest 阶段最低价 ≥ `base_high × 0.985` AND 最新收盘价 > base_high

输出:
- `"alert"`: 突破但尚未确认回踩
- `"confirmed"`: 突破 + 回踩确认 → `buy_point = "二买"`
- `"none"`: 无信号

---

### 2.9 analyze_chanlun (综合分析)

| 属性 | 说明 |
|------|------|
| **File** | `core/chanlun_engine.py:184` |
| **Function** | `analyze_chanlun(rows)` |

**趋势判定**:
| 条件 | trend_type |
|------|-----------|
| `last > last_pivot.zg` 且大于前中枢.zg | uptrend |
| `last < last_pivot.zd` | downtrend |
| 其它 | range |

**买卖点**:

| 信号 | 条件 | 优先级 |
|------|------|--------|
| 一买 | `div.type == "bottom_divergence"` AND (downtrend OR range) | 高 |
| 二买 | 底分型 ≥ 2 个, 最后一个底抬高, 趋势 uptrend/range | 低 |
| 三买 | 最后一个 stroke 向上, last.low > pivot.zg | 中 |
| 平台突破二买 | breakout signal confirmed → `buy_point = "二买"` | 中 |
| 一卖 | `div.type == "top_divergence"` | 高 |
| 三卖 | downtrend AND last < prior.zd | 低 |

**Breakout buy_point 覆盖逻辑**: `buy_point = buy or breakout.get("buy_point")` — breakout 的二买在无缠论买点时生效。

---

## 三、leader_score (龙头评分)

| 属性 | 说明 |
|------|------|
| **File** | `core/chanlun_engine.py:226` |
| **Function** | `leader_score(row, sector_count, sector_rank, continuity_days)` |

**6 分量**:
| 分量 | 最大值 | 计算 |
|------|--------|------|
| 连板 | 30 | `streak × 10`, capped at 30 |
| 成交额 | 20 | `amount / 50_000_000 × 4`, capped at 20 |
| 板块宽度 | 15 | `sector_count × 3`, capped at 15 |
| 板块内排名 | 15 | rank ≤ 3 → 15; rank ≤ 10 → 8; else 0 |
| 持续性 | 10 | `continuity_days × 3`, capped at 10 |
| 换手质量 | 10 | 3%-18% → 10; > 0 → 4; else 0 |

**风险扣分**:
| 条件 | 扣分 |
|------|------|
| turnover > 25% | -12 (excessive_turnover) |
| streak=1 AND sector_count < 3 | -10 (one_day_isolated) |
| amount < 5000 万 | -10 (low_liquidity) |

**分类**: Score ≥ 70 → `main_uptrend_leader`, ≥ 55 → `strong_watch`, else → `observation_only`

---

## 四、analyze_from_mcp (MCP 入口)

| 属性 | 说明 |
|------|------|
| **File** | `core/chanlun_engine.py:243` |
| **Function** | `analyze_from_mcp(symbol, period="D", count=200)` |

调用 `mcp_client.fetch_klines()` 获取 K 线数据后执行 `analyze_chanlun()`。

---

## 五、关键参数

| 参数 | 默认值 | 位置 |
|------|--------|------|
| 包含处理初始方向 | 1 (向上) | inclusion_process |
| 分型窗口 | 3 bars | fractals |
| 笔最小间隔 | 2 bars | strokes |
| 中枢窗口 | 3 strokes | pivots |
| 背驰阈值 | MACD 面积缩小 ≥ 20% | divergence |
| 平台压缩宽度 | < 12% | trend_breakout_signal |
| 突破量比 | ≥ 1.25× 均量 | trend_breakout_signal |
| 回踩容忍度 | ≥ 98.5% base_high | trend_breakout_signal |
| EMA 参数 | 12/26/9 | macd_strength |
| 平台扫描窗口 | 8 bars | trend_breakout_signal |
| leader 连板权重 | 10/板 | leader_score |
| leader 成交额基准 | 5000 万 | leader_score |
