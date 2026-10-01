# AGY审计R46-R47: market_regime + iron_rule_gate 7 Bug修复 (2026-09-15)

## 审计范围
3 个文件: `market_regime.py`, `market_regime_check.py`, `tdx_pullback_scanner.py`

## AGY发现的7个Bug

### 1. fetch_limitup_count 问财fallback不足
- **BAD**: 仅当 `broken_rate<=0 and limitup_count>0` 时才问财，且只解析炸板数
- **GOOD**: 条件改为 `limitup_count==0 or broken_rate<=0`，同步解析涨停家数和炸板家数

### 2. retreat_days 日内无限递增（P0）
- **BAD**: 每次调用 `get_market_regime()` 都无条件 `prev_days+1` → cron 5分钟跑一次，15分钟从第1天跳到第4天 → 误触 exhaustion_ebb 迷你仓试盘模式
- **GOOD**: 加 `today_str` 校验，同一天内保持 `prev_days` 不变，仅跨交易日 +1

### 3. 非退潮状态 retreat_days 泄漏（P0）
- **BAD**: 震荡/启动/高潮也持久化 `retreat_days=3`，污染下游消费
- **GOOD**: `retreat_days: retreat_days if regime_data["regime"] == "退潮" else 0`

### 4. iron_rule_gate 缺 panic_ebb 拦截（P0）
- **BAD**: `panic_ebb` 完全未被识别，fall through 到通用退潮分支 → 恐慌杀跌期还能买"龙头低吸"
- **GOOD**: 新增 3a 门禁：`ebb_subtype=="panic_ebb"` → 直接熔断"禁止一切开仓"

### 5. exhaustion_ebb 提前 return 跳过 Gate 4（P0）
- **BAD**: `exhaustion_ebb` 直接 `return True` → 跳过垃圾时间门禁(10:00-14:30)、连板、追高校验
- **GOOD**: exhaustion_ebb 做首板+低吸校验后不 return，继续走 Gate 4

### 6. fetch_turnover_info 缺 ValueError 防护（P1）
- **BAD**: `float(row.get("amount", 0.0) or 0.0)` → 问财返回 "" / "N/A" 时直接崩溃
- **GOOD**: try/except 包裹，兜底 0.0

### 7. tdx_pullback_scanner 迷你仓展示不一致（P2）
- **BAD**: 说"首板迷你仓"但实际是均线回踩；候选存在时无迷你仓标记
- **GOOD**: "均线回踩迷你仓模式(≤10%)"；候选行尾加 `⚠️[衰竭冰点迷你仓≤10%]`

## 修复后的关键设计改变

### exhaustion_ebb 不走捷径
**之前**: `iron_rule_gate` 中 `exhaustion_ebb` 直接 `return True` 跳过一切后续门禁
**之后**: exhaustion_ebb 做首板校验和追高限制后**不提前return**，必须通过 Gate 4 垃圾时间门禁
**教训**: 退潮期的迷你仓试盘也需要遵守盘中纪律，不能因为"衰竭冰点"就把所有防线都打开

### retreat_days 的时间感知
retreat_days 不再是无条件链式递增，必须查 `updated_at` 日期字段：
- 同一天内任何调用次数 → retreat_days 不变
- 跨交易日 → +1
- 非退潮状态 → 持久化为 0

## 一致性检查结果
- `tdx_pullback_scanner.py` — FAIL (标签名问题，已修复)
- `market_regime_check.py` — FAIL (panic_ebb遗漏+exhaustion_ebb短路，已修复)
- `ignition_v1_sniper.py` — FAIL by Inheritance (通过 iron_rule_gate 断点)
- `intraday_theme_trigger.py` — FAIL by Inheritance (同上)
