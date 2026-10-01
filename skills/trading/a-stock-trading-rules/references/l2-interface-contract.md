# L2 接口合约 & L1 降级模式

> 创建: 2026-09-07 (R3弱转强v2改造)
> 文件: `scripts/l2_interface.py`

## 架构哲学

L2 盘口数据对 A 股打板是**必不可少的**——AGY股神审计致命缺陷4明确指出"无L2盘口→打板在黑暗中送人头"。但当前无L2数据源。

**策略**：I/F 先上（接口隔离 + 完整类型签名），L1 降级保运行，买到 L2 源后只实现函数体，不改调用处。

## 接口清单

### 1. `get_l2_order_book(symbol)` → L1 降级: `None`

```python
def get_l2_order_book(symbol: str) -> Optional[L2OrderBook]:
    """
    L2千档盘口。
    当前返回 None (无L2数据源)。
    未来实现后返回: {asks: [(price, volume), ...], bids: [...]}
    """
```

**L2 数据源的 5 个核心威胁**（AGC 审计缺陷4）：
- 封单硬度的真实度量（L1 的 `seal_ratio` 靠量价推算，偏差极大）
- 主力撤单实时信号（大单堆高→撤完→砸盘，L1 完全看不见）
- 千档挂单分布（识别资金上攻意愿 / 抛压集中区）
- 逐笔成交还原（判断拉升的资金性质：游资 vs 机构 vs 散户）
- 买一到买五的等额变化（WACD 堆积判断主力封板诚意）

### 2. `get_tick_trades(symbol)` → L1 降级: `None`

```python
def get_tick_trades(symbol: str) -> Optional[List[TickTrade]]:
    """
    L2逐笔成交。L1不可替代——逐笔还原是L2独有能力。
    当前返回 None。
    """
```

### 3. `get_acceleration(symbol, period)` → L1 降级: `get_trend_acceleration_l1()`

```python
def get_acceleration(symbol: str, period: str = "5m") -> Optional[float]:
    """
    L2级加速度判断：逐笔成交还原。
    L1降级: 5分钟K线斜率 + 成交量变化率。
    """
```

### 4. `estimate_weak_to_strong_bid_quality(symbol, data)` → 完全用 L1

**核心评分矩**：弱转强竞价抢筹质量 L1 五因子评分

| 因子 | 权重 | L1数据源 | 满分条件 |
|------|------|---------|---------|
| 竞价涨幅 | 0.30 | `query_data` → `change_pct` | 3.0%~5.5% |
| 量比 | 0.25 | `query_batch_data` 竞价量 | ≥8.0 (抢筹明显) |
| 行业排名 | 0.20 | `wencai_search` | 板块涨幅 TOP3 |
| 封单强度 | 0.15 | 估算(量×价/流通市值) | 假seal_ratio≥3% |
| 额外因子 | 0.10 | 多源交织 | 前日炸板+竞价爆量齐备 |

**总分 < 4.0 → `weak` 标记 → v2 跳过**。

L2 升级后可直接替代以下因子：
- 竞价涨幅 → 买一挂单的真实增长（分辨主力做盘 vs 真抢筹）
- 量比 → 开盘前30秒曝光成交（L2逐笔还原更精准）
- 封单强度 → 买一至买五的扣单(撤掉又加回来的假量)识别

### 5. `get_trend_acceleration_l1(symbol, period)` → 纯 L1

```python
def get_trend_acceleration_l1(symbol: str, period: str = "5m") -> float:
    """
    5分钟K线斜率（close[-1]-close[0]）/ len(closes)。
    正值 = 趋势向上加速，负值 = 趋势衰减。
    L1可替代L2加速度判断的基础版。
    """
```

## v2弱转强改进中 L1 降级的使用方式

| v2改进点 | 使用了哪些 L1 按 |
|---------|----------------|
| 竞价抢筹质量五因子评分 | ①竞价涨幅 ②量比 ③行业排名 ④封单估 ⑤额外因子 |
| 缩量/放量区分策略 | query_batch_data 换手率(change_pct=0时读amount推算) |
| 5分钟K线加速度 | get_trend_acceleration_l1: 5分钟K线斜率 |
| 板块持仓保护 | wencai_search 查标的所属板块 → get_positions 对照 |

## L2接入待办

**当用户买到L2源后**，只需要以 `scripts/l2_interface.py`：

1. `get_l2_order_book()` — 替换 `None` 为真 L2 千档盘口
2. `get_tick_trades()` — 替换 `None` 为真 L2 逐笔成交
3. `get_acceleration()` — 增加 L2 级加速度(逐笔还原)，L1 作为 fallback
4. `estimate_weak_to_strong_bid_quality()` — 增加 L2 因子，修正 done 各因子权重
5. 所有调用方(`call_auction_scanner.py`)不变——调合已隔离

**注意**：L2 接入后必须使「⑤额外因子」权重从 0.10 提高到 0.20（因为 L2 的额外信息量远大于其他 L1 因子的精度提升）。

## 相关脚本

- `scripts/l2_interface.py` — L2接口模块（296行，5个函数）
- `scripts/call_auction_scanner.py` — `scan_weak_to_strong_v2()` 使用前3个接口
