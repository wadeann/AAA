# Position Model — 仓位计算模型

## 一、实盘仓位计算 (direct_executor.py)

### 完整公式链

```
BUY 候选
  ↓
sentiment_multiplier = load_sentiment_multiplier()  # 从 strategy_params.json 读取
  ↓
adj_pct = base_pct × sentiment_multiplier
  ↓
new_alloc = total_assets × adj_pct
  ↓
max_allowed = max(0, total_assets × max_regime_ratio - current_market_val)
  ↓
if (current_market_val + new_alloc) > (total_assets × max_regime_ratio):
    new_alloc = max_allowed
  ↓
target_val = min(new_alloc, available_cash × 0.95)
  ↓
target_qty = int(target_val / price / 100) × 100
  ↓
if target_qty < 100: REJECT
  ↓
adj_pct = target_val / total_assets  # 最终调整比例
  ↓
normalize_intent(candidate, total_assets, adjusted_pct=adj_pct, ...)
```

### 关键变量

| 变量 | 来源 | 说明 |
|------|------|------|
| base_pct | candidate.max_position_pct | 默认 0.25 |
| sentiment_multiplier | strategy_params.json → sentiment.multiplier | 0.0-1.0 |
| max_regime_ratio | market_regime.json → max_regime_ratio | 默认 0.80 |
| total_assets | MCP get_balance() | 总资产 |
| available_cash | MCP get_balance() | 可用现金 |
| current_market_val | MCP get_positions() | 当前持仓市值 |

### Path in code:
1. `/home/wade/workspace/ai/Astock/execution/direct_executor.py` line 698: `adj_pct = base_pct * sent_multiplier`
2. `/home/wade/workspace/ai/Astock/execution/direct_executor.py` line 703-708: `new_alloc` → `max_allowed` → `target_val` → `target_qty`
3. `/home/wade/workspace/ai/Astock/execution/pipeline.py` line 261-268: `normalize_intent()` 第二层计算

---

## 二、回测仓位计算 (backtest_2yr.py)

### 公式链

```
regime → regime_map → (min_score, max_positions, regime_cap)
  ↓
available_slots = max_positions - len(positions)
  ↓
for each candidate (sorted by score descending):
  ↓
pos_pct = regime_cap  (default)
if score >= 80: pos_pct = min(regime_cap + 0.05, max_pos_pct)
elif score >= 70: pos_pct = regime_cap
  ↓
pos_value = cash × pos_pct    # 单笔目标金额
  ↓
shares = int(pos_value / close / 100) × 100   # 按手取整
  ↓
if shares × close > cash: continue   # 资金不足则跳过
```

### Path in code:
`/home/wade/workspace/ai/Astock/scripts/backtest_2yr.py` lines 281-300

---

## 三、MultiStrategyAllocator 仓位分配

```python
get_alloc_pct(profile_name, score, regime_cap, max_pos_pct):
    if score >= 80: return min(regime_cap + 0.05, max_pos_pct)
    elif score >= 70: return regime_cap
    elif score >= 60: return regime_cap * 0.8
    else: return regime_cap * 0.6
```

Budget allocation:
```python
get_budgets(max_positions):
    for profile sorted by weight descending:
        slots = max(1, int(max_positions * weight))
        remaining -= slots
    # remaining distributed to highest-weighted profiles
```

### Path in code:
`/home/wade/workspace/ai/Astock/core/strategy_profiles.py` lines 877-908

---

## 四、缠论回测仓位 (backtest_engine.py)

```python
cash × sent_mult × pos_factor / remaining_slots
```

Where pos_factor depends on signal score:
| Score | Factor |
|-------|--------|
| ≥ 75  | 1.0    |
| ≥ 55  | 0.8    |
| ≥ 40  | 0.6    |
| < 40  | 0.4    |

Minimum position: 20,000 元

### Path in code:
`/home/wade/workspace/ai/Astock/scripts/backtest_engine.py` lines 549-570

---

## 五、风险侧仓位约束

| 约束 | 值 | 来源 |
|------|-----|------|
| 单标仓位 | ≤ 30% | risk_manager.py _check_position_cap |
| 总敞口 | ≤ 80% | risk_manager.py _check_total_exposure |
| 板块集中度 | ≤ 40% | risk_manager.py _check_sector_concentration |
| 最大持仓数 | ≤ 5 | risk_manager.py _load_config |
| 尾盘禁买 | 14:35 后 | risk_manager.py _check_tail_chase |
| 情绪冰点 | mult ≤ 0.3 | pipeline.py normalize_intent |

---

## 六、SELL 卖出量计算

```
if direction == "sell":
    available = min(candidate_qty, real_available_qty)
    if available < 100: REJECT (temporary_insufficient_shares)
    candidate["quantity"] = available
```

Available quantity from:
1. Position.available_quantity (from MCP)
2. Fallback: position.quantity - today_buys (from get_today_trades)

### Path in code:
`/home/wade/workspace/ai/Astock/execution/direct_executor.py` lines 664-697
