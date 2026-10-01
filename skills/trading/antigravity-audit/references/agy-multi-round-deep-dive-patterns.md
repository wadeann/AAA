# AGY多轮深度审计潜射问题链模式（2026-09-07 R1→R4 auction_kill_switch实战）

## 场景

auction_kill_switch.py 经过 R1(15.9%)→R2(42%)→R3(58%)→R4(82%)→R5(100%) 共5轮AGY审计，每轮AGY都挖出**前一轮完全没发现的深水炸弹**。这不是"一轮修不好再修"的问题，是AGY在每轮看到新的文件状态后才能发现更深层的问题。

## 审计分数演进

| 版 本 | AGY分数 | 关键发现 | 前一轮完全没发现的深水炸弹 |
|:----|:--------|:---------|:------------------------|
| R1 (原始) | 15.9% | 10个问题 | — |
| R2 (第一次修) | 42% | 代码过滤器/手股/飞书 | 3个P0(代码过滤排除沪市/成交量100倍/无通知) |
| R3 (第二次修) | 58% | Decimal/K线索引/手/股统一/T+1 | 3个新P0(Decimal废单/K线prev_day_close错取/手/股100倍仍未统一) |
| R4 (第三次修) | 82% | 弱转强逻辑斩断/K线容灾/观察列表 | 2个P1(低开放量误当弱转强/K线超时阻断跌停强平) |
| R5 (最终) | **100%** | 3行微调通过 | 同上 |

## 模式1：数值驱动发现 — AGY不是看代码改没改，是**算数值看变没变**

AGY在每轮复审中不只是检查"代码是否写了"，而是**重新计算数值**来戳穿假修复。

### 典型案例

```
R2修复：改timeout递增(8→12→16)+缩短退避(5→1, 10→2)，但retries=2不变
AGY复审计算：8+1+12+2+16 = 39s → 还是39s，一秒没少 ❌
```

### auction_kill_switch中的数值验证：

```
R2→R3的calc_limit_price验证：
  输入: base_price=1.15, ratio=-0.10
  交易所规则: 1.15*0.9=1.035 → 四舍五入=1.04
  Python float: 1.15*0.9=1.03499999... → floor(103.9999+0.5)=103/100=1.03 ❌(废单!)
  Decimal: Decimal('1.15')*Decimal('0.9')=1.035 → quantize(0.01, ROUND_HALF_UP)=1.04 ✅

R3→R4的量比验证：
  腾讯query_batch_data volume=手(100股)
  新浪fetch_kline volume=股
  raw_auction_vol / yesterday_vol = 手/股 = 真实值/100
  锁仓阈值检查: (手/股*100) > 1.0 → 需要竞价>昨日全量100%才能触发 → 永远为False
  修正: auction_shares = raw_auction_vol * 100 (统一转为股)
```

### 审计员必须做的计算检查

每次提交修复后，复审应检查：
1. **看代码改了没有**（低级，但必须做）
2. **算数值改了没有**（中级 — 只改公式不改基数，数值不变）
3. **计算边界情况**（高级 — timeout+retries+sleep都在上限时的最坏值）

```python
# AGY模式：得知retry参数后立即计算最坏耗时
attempts = retries_count + 1
timeouts = [base + i * increment for i in range(attempts)]
worst = sum(timeouts) + sum(sleeps[i] for i in range(retries_count))
assert worst < parent_timeout, f"{worst}s > {parent_timeout}s — 假修复!"
```

## 模式2：P0问题链潜射 — 一个简单需求引发深度连锁修正

### auction_kill_switch潜射链

**需求"用合规价格卖出不要price=-1"** 触发了全线重写：

```
price=-1 (原始)
  → P0: 跌停价格式不对
    → float计算calc_limit_price (R2)
      → P0: float精度下溢(1.15*0.9=1.0349≠1.035)  
        → Decimal+ROUND_HALF_UP (R3 ✅)
```

**需求"昨天涨停的标的今天竞价锁仓"** 触发了：

```
手/股单位混用 (R2)
  → P0: auction_vol_ratio缩小100倍，锁仓恒假
    → auction_shares=raw*100统一股 (R3)
      → P0: prev_day_close取了昨天=涨停价基准错误
        → count=3剥离今日K线+取history[-2] (R3 ✅)
```

### 本质规律

每个P0修复后可能暴露**下一层更深的P0**。不是因为修得不好，是**修了这一层AGY才能看到下一层**。典型的修复链深度：3~4层。

## 模式3：闭包条件陷阱 — 弱转强条件的逻辑错误

### 错误模式

```python
# ❌ R3原始：低开爆量被误判为弱转强
is_weak_turn_strong = (open_pct >= 0.0) or (auction_amount >= 10_000_000) or (auction_vol_ratio >= 1.5)
# 低开-1.5%+竞价1500万 → True(弱转强) ← 这是踩踏出货！
```

### 正确模式

```python
# ✅ R4修正：弱转强必须以平开/高开为绝对前提
is_weak_turn_strong = (open_pct >= 0.0) and (
    (open_pct >= 2.0) or (auction_amount >= 10_000_000) or (auction_vol_ratio >= 1.5)
)
# 低开就算爆量也是抢跑踩踏/主力出货，不是弱转强
```

### 闭包条件陷阱识别规则

- `and` 串联条件时，**每个子条件**独立的判断必须成立
- 低开=弱（价格是唯一权威的强弱判断），竞价量在负价格区间里不表示接盘，表示出货
- 同理：竞价量X昨日Y时（量能放大）如果是低开=放量出货；只有高开/平开才=放量承接

## 模式4：K线降级容灾 — 网络抖动不能阻断核心交易

### 错误模式

```python
# ❌ R3：K线fetch失败直接continue跳过整只标的
kline_res = mcp_call(..., "fetch_kline", ...)
if not kline_res:
    continue  # ← K线失败，跌停标的漏杀！
```

### 正确模式

```python
# ✅ R4：K线拉取失败仅降级，不影响cond1(自适应低开)和cond3(逼近跌停)
limit_ratio, _ = get_limit_ratios(symbol, name)  # 提前到K线外部
yesterday_bombed = False
yesterday_sealed = False
yesterday_vol = 0.0
prev_day_close = current_price  # 降级：保守替代

kline_res = kline_map.get(symbol)
if kline_res:
    # ... 正常处理K线 ...
```

### 容灾原则

1. **降级 ≠ 跳过**：核心逻辑（跌停卖出、低开强平）不依赖K线数据源
2. **默认安全值**：所有从降级源读取的变量有合理的安全默认值（bombed=False, sealed=False）
3. **不发散的独立路径**：cond1(C1)和cond3(C3)是独立于K线的纯行情判断

## 模式5：亚稳态检查 — 获取数据后要验证"准备好了"

### 竞价量0防御

09:25:00~09:25:03 期间MCP行情数据可能尚未推送，竞价量为0。
```python
# ✅ R4：竞价量0时跳过(数据未就绪)，不是判定为"无成交量"
if auction_shares <= 0.0:
    observe_lines.append(f"{symbol} {name} 竞价量0(数据未就绪)")
    continue
```

### 时间窗口守卫

```python
# UTC 01:25:05 ~ 01:29:50 (北京时间 09:25:05 ~ 09:29:50)
KILL_WINDOW_START = 1*3600 + 25*60 + 5
KILL_WINDOW_END = 1*3600 + 29*60 + 50
# ⚠️ 也需要一个 --force 测试旁路绕过窗口守卫做离线测试
```

## 附录：auction_kill_switch.py R5最终版关键参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 低开核按钮阈值(主板10cm) | -2.5% | `-limit_ratio * 25` |
| 低开核按钮阈值(双创20cm) | -5.0% | |
| 低开核按钮阈值(北交30cm) | -7.5% | |
| 炸板+低开>1.0%+无弱转强 | 核按钮 | 弱转强=平开及以上+放量 |
| 锁仓条件 | 高开≥2.0%+竞价额≥1500万或量比≥2%+昨日真硬板 |
| T+1铁律 | `available_qty`>=100股，严禁fallback到`total_qty` |
| 交易时间守卫 | UTC 01:25:05~01:29:50 |
| 测试旁路 | `--force`参数或`AUCTION_FORCE_RUN=1`环境变量 |
| 竞价量0处理 | 跳过(数据未就绪)，非判定为无成交量 |
