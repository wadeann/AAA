# 渝三峡A 光杆2板低位候选误筛案（2026-09-11）

## 案例摘要

- **日期**：2026-09-11（周五交易日）
- **标的**：渝三峡A (000565.SZ)
- **当天走势**：开盘7.91 → 直接跳水 → 收盘-9.86%（接近跌停）
- **系统错误**：`select_actionable_recommendations()` 将其选入"低位起爆"推荐槽

## 数据追溯

### 9/10 盘后梯田数据（ladder_enhanced_2026-09-10.json）

```
渝三峡A: streak=2 (2连板), sector="基础化工", seal_time=null
基础化工板块涨停标的：仅渝三峡A 1只（光杆2板，无首板助攻）
```

### sector_matrix 中基础化工的角色

```json
"基础化工": {
  "role": "secondary_attack",
  "max_streak": 2,
  "strength_score": 70,
  "momentum": {
    "total_count": 1,   // 只有1只标的！
    "tiers": 1,          // 只有1层梯队
    "above_2_ratio": 1.0
  },
  "action_type": "breakout_ladder",
  "single_position_pct": 0.12
}
```

### 系统推荐链路

1. `compile_plan()` 从梯田数据生成 `position_ids` → 渝三峡 streak=2 进入 `position_ids`（type: capacity_core）
2. `select_actionable_recommendations()` 读取 `position_ids`
3. 第1槽（主攻空间）：`space_leaders` = streak≥3的 → 只有瑞尔特3板当选
4. 第2槽（次强先锋）：`second_leaders` = 其他streak≥3 → 无
5. 第3槽（低位起爆）：`low_cands` = streak in (1,2) 且 sector在 primary_secs → 按streak降序 → **渝三峡(2板)排首位** → 当选

## Bug 根因分析

### 代码位置
`premarket_plan_compiler.py` 第904-907行：

```python
low_cands = [c for c in sub_cands if c["sector"] in primary_secs and c["streak"] in (1, 2)]
low_cands.sort(key=lambda x: x["streak"], reverse=True)
# ↑ streak=2的自然排首位，但没有检查板块稀缺性
```

### 三个独立的过滤缺失

1. **无位置层级校验**：streak=2（中位）应禁止进入"低位起爆"槽。该槽的设计意图是捕获首板/一进二，不是二进三。
2. **无板块稀缺性校验**：当板块只有1只涨停标的时，该标的不应推荐。因为没有同板块助攻的票 = 孤军 = 无人接力。
3. **无 2板 vs 首板优先排序**：即使 streak=2 要进低位槽，也应该放在 streak=1 后面（首板才是真正的低位）。

## 修复方案

### 方案A：streak 分层校验（推荐）

```python
# 在 low_cands 中区分首板和2板
# 禁用2板进低位槽
low_cands = [c for c in sub_cands if c["sector"] in primary_secs and c["streak"] == 1]
# ↑ 只保留首板种子
```

### 方案B：板块稀缺性校验

```python
# 对于 streak=2 且板块只有1只涨停的，直接过滤
if c["streak"] == 2:
    sector_tickers = [t for t in p_ids if t.get("sector") == c["sector"]]
    if len(sector_tickers) < 2:
        continue  # 光杆2板不推荐
```

### 方案C：多槽位策略评估（远期架构）

- 低位起爆槽 → 只放首板（streak=1）
- 次强先锋槽 → 放2板有板块梯队支撑的（streak=2 + sector_count≥2）
- 主攻空间槽 → 放≥3板（已有）
- 新增"观望池" → 放光杆2板/首板，不作为推荐只作为观察

## 相关文件

- `premarket_plan_compiler.py` — `select_actionable_recommendations()` 第904-925行
- `a-stock-strategist/SKILL.md` — 低位起爆选股过滤规则章节
- `a-stock-trading-rules/SKILL.md` — 新增的🔴低位起爆候选过滤规则章节
