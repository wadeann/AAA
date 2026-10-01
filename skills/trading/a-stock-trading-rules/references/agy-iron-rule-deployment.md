# AGY Iron Rule Deployment (2026-09-08)

## Files Deployed

### 1. market_regime.py (市场状态机)
- **Path**: `~/.hermes/scripts/market_regime.py`
- **Cron**: `20 1 * * 1-5` (09:20 CST), `20 5 * * 1-5` (13:05), `20 7 * * 1-5` (15:05)
- **Output**: `~/.hermes/trading/config/market_regime.json`

**State Transitions**:
```
极寒: gem_change_pct < -0.5 AND is_shrink → 禁止一切开仓
退潮: gem_change_pct < -0.3 OR median_change < 0 → 仅允许总龙深水低吸
高潮: gem_change_pct > 1.0 AND limitup_count > 50
启动: gem_change_pct > 0.5 AND limitup_count > 30
震荡: 以上都不满足
```

**Data sources**: query_data(399006.SZ), wencai_search("今日个股涨跌幅中位数"), query_data(000001.SH), get_limitup_ladder()

### 2. strategy_circuit_breaker.py (闭环熔断器)
- **Path**: `~/.hermes/scripts/strategy_circuit_breaker.py`
- **Data files**:
  - `~/.hermes/trading/strategy_circuit_breaker/trade_history.jsonl` (逐笔记录)
  - `~/.hermes/trading/strategy_circuit_breaker/breaker_state.json` (熔断状态)

**Rules**:
- 连败熔断: 同策略最近2笔连续亏损 → 7天熔断
- 重伤熔断: 同策略单笔亏损>5% → 14天熔断

**CLI usage**:
```
python3 strategy_circuit_breaker.py --status          # 查看所有策略状态
python3 strategy_circuit_breaker.py --check price_alert  # 检查单个策略
python3 strategy_circuit_breaker.py --sync            # 从历史feedback同步
python3 strategy_circuit_breaker.py --record --catalyst-type x --symbol y --pnl-pct -3.2
```

**Known status (2026-09-08)**:
- price_alert: 🔴 熔断至9/17 (单笔-16.29%)
- mcp_live: 🔴 熔断至9/10 (连续2笔亏损)
- close_sell_signal: ✅ 正常 (4笔全盈)

### 3. leader_universe_filter.py (龙头精选池)
- **Path**: `~/.hermes/scripts/leader_universe_filter.py`
- **Cron**: `0,30 1-3,5-6 * * 1-5` (每30分钟盘中)
- **Output**: `~/.hermes/trading/config/leader_universe.json`

**三条件（缺一不可）**:
1. 板块内身位唯一第一（同板块无并列最高板，≥2板）
2. 5日日均成交额 >= 8亿元
3. 10日内至少2次涨停

**Note**: 依赖 `get_limitup_ladder()`，非交易日无数据。空池 = "无龙则空"。

### 4. market_regime_check.py (铁律总闸门)
- **Path**: `~/.hermes/scripts/market_regime_check.py`
- **Imported by**: `direct_executor.py` (no standalone cron)
- **Main function**: `iron_rule_gate(candidate, now_cst) -> (bool, str)`

**Four gates (in order)**:
0. Sell direction → unconditional pass (止盈止损自由通道)
1. Strategy circuit breaker check → read breaker_state.json
2. Market regime check → if "极寒" block all; if "退潮" block non-leader + chasing
3. Garbage hour check (10:00-14:30) → block non-leader + chasing

### 5. direct_executor.py (patch)
- **Changes**: two modifications in commit 7e7976e
  1. `load_processed_ids()`: added `"agy_iron_rule_blocked"` to the event tuple
  2. After quote fetch, before condition evaluator: insert `iron_rule_gate()` call

**Blocked event records**: written to candidates JSONL with `event="agy_iron_rule_blocked"` and full reason text.

## Operation Guide

### When a buy candidate is generated:
1. `market_regime.py --output-only` → reads current regime from disk
2. `leader_universe_filter.py --output-only` → reads current leader pool
3. `strategy_circuit_breaker.py --check <catalyst_type>` → checks strategy health
4. If all pass AND not in garbage hour (10:00-14:30) → proceed to risk check

### When a buy is blocked:
- Check `baller_state.json` → is the strategy in cooldown?
- Check `market_regime.json` → what's the current regime?
- Check `leader_universe.json` → is the symbol a verified leader?
- Check current time → is it 10:00-14:30?
- The blocking reason is always written to the candidates JSONL as `candidate_event`

### Cron jobs added:
```
c349dba61d27  市场状态机刷新     20 1,5,7 * * 1-5  market_regime.py --verbose
f793049e595d  龙头精选池刷新     0,30 1-3,5-6 * * 1-5  leader_universe_filter.py --force-refresh
```

## Test Results (2026-09-08)

```
market_regime.py:
  ✅ 创业板-1.15% → 退潮
  ✅ 数据: gem=-1.15% median=+0.54% turnover=91.56B shield=False zt=73

strategy_circuit_breaker.py --sync --status:
  ✅ price_alert: 7笔全亏(-16.29%最大) → 14天熔断至9/17
  ✅ mcp_live: 2笔连亏 → 7天熔断至9/10
  ✅ close_sell_signal: 4笔全盈 → 正常运行

leader_universe_filter.py --force-refresh --verbose:
  ✅ 73涨停票→18连板候选→9只身位初筛→仅1只通过容量+涨停双门禁
  ✅ 华盛昌002980: 电力设备2板 15.15亿 10日4次涨停

market_regime_check.py:
  ✅ 卖单豁免 → PASS
  ✅ 熔断策略阻断 → 🚫 price_alert
  ✅ 垃圾时间跟风 → 🚫 退潮+非龙头
  ✅ 龙头低吸 → ✅ is_sector_leader+change=-0.5%
```
