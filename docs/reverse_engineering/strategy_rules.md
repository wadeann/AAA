# Strategy Rules — 完整策略规则注册表

注册规则 ID: RULE-001 至 RULE-060

---

## FILTER 规则

### RULE-001: 最低股价过滤
- **File**: `core/strategy.py:199`
- **Function**: `screen_candidates`
- **Condition**: `close < min_close` (default 10.0)
- **Action**: 排除低于最低价的股票
- **Type**: FILTER

### RULE-002: 最低量比过滤
- **File**: `core/strategy.py:206`
- **Function**: `screen_candidates`
- **Condition**: `vr < min_vr` (default 0.5-1.5)
- **Action**: 排除成交量不足的股票
- **Type**: FILTER

### RULE-003: MA20 位置过滤
- **File**: `core/strategy.py:208`
- **Function**: `screen_candidates`
- **Condition**: `close < sma(close, 20) * ma_pct` (default 0.95)
- **Action**: 排除距离 MA20 太远的股票
- **Type**: FILTER

### RULE-004: ST/退市黑名单
- **File**: `risk/risk_manager.py:353`
- **Function**: `_check_st_blacklist`
- **Condition**: name 含 ST/*ST/退市/S*ST/SST, symbol in blacklist
- **Action**: BLOCK 交易
- **Type**: FILTER | RISK

### RULE-005: 最低 RSI 过滤 (评分内)
- **File**: `core/strategy.py:269`
- **Function**: `score_momentum_core`
- **Condition**: `rs < min_rs` (default 25)
- **Action**: grade = D, score = 0
- **Type**: FILTER

### RULE-006: MA20 位置过滤 (评分内)
- **File**: `core/strategy.py:271`
- **Function**: `score_momentum_core`
- **Condition**: `close < ma20 * ma_pct` (default 0.95)
- **Action**: grade = D, score = 0
- **Type**: FILTER

### RULE-007: 最低 K 线数过滤
- **File**: `core/strategy.py:195`
- **Function**: `screen_candidates`
- **Condition**: `len(lb) < 30`
- **Action**: 跳过不足 30 根 K 线的股票
- **Type**: FILTER

### RULE-008: 最低成交量过滤
- **File**: `core/strategy.py:202`
- **Function**: `screen_candidates`
- **Condition**: `vol <= 0`
- **Action**: 跳过零成交股票
- **Type**: FILTER

### RULE-009: 标的合法性检查
- **File**: `risk/risk_manager.py:134`
- **Function**: `_check_symbol`
- **Condition**: symbol not end with .SH/.SZ/.BJ, or code not 6 digits
- **Action**: BLOCK
- **Type**: FILTER | RISK

### RULE-010: 板块级定向隔离
- **File**: `execution/direct_executor.py:549-566`
- **Condition**: `candidate.sector in blocked_sectors`
- **Action**: 跳过该板块所有买入
- **Type**: FILTER | RISK

---

## ALPHA 规则

### RULE-011: 量比因子
- **File**: `core/strategy.py:278-289`
- **Function**: `score_momentum_core`
- **Condition**: VR > 3.0 → full weight, > 2.0 → 80%, > 1.5 → 60%, > 1.2 → 40%, > 1.0 → 24%, else → 12%
- **Default Weight**: 25
- **Type**: ALPHA

### RULE-012: 距 10 日高因子
- **File**: `core/strategy.py:293-301`
- **Function**: `score_momentum_core`
- **Condition**: dh10 < 1% → full, < 3% → 80%, < 5% → 60%, < 8% → 35%, < 12% → 20%
- **Default Weight**: 20
- **Type**: ALPHA

### RULE-013: MA 排列因子
- **File**: `core/strategy.py:304-312`
- **Function**: `score_momentum_core`
- **Condition**: close>ma5>ma10>ma20 → full (name=trend), close>ma5>ma20 → 70%, close>ma20 → 50%, else → 10%
- **Default Weight**: 20
- **Type**: ALPHA

### RULE-014: RSI 因子
- **File**: `core/strategy.py:315-324`
- **Function**: `score_momentum_core`
- **Condition**: 45-65 → full, 65-75 → 67%, 35-45 → 53%, >75 → 27%, else → 13%
- **Default Weight**: 15
- **Type**: ALPHA

### RULE-015: 日涨幅因子
- **File**: `core/strategy.py:327-340`
- **Function**: `score_momentum_core`
- **Condition**: >7% → full (name=ignition), >5% → 87% (name=ignition), >3% → 67%, >1.5% → 47%, >0.5% → 27%, else → 7%
- **Default Weight**: 15
- **Type**: ALPHA

### RULE-016: 波动率加分
- **File**: `core/strategy.py:343-351`
- **Function**: `score_momentum_core`
- **Condition**: intraday range >5% → full, >3% → 60%
- **Default Weight**: 5
- **Type**: ALPHA

### RULE-017: 20 日新高加分
- **File**: `core/strategy.py:354-356`
- **Function**: `score_momentum_core`
- **Condition**: hi10 >= hi20 * 0.99 → bonus (name=breakout)
- **Default Weight**: 5
- **Type**: ALPHA

### RULE-018: 回踩加分
- **File**: `core/strategy.py:359-367`
- **Function**: `score_momentum_core`
- **Condition**: max(chg in 10d) > 5% and VR < 0.9 → bonus (name=pullback)
- **Default Weight**: 10
- **Type**: ALPHA

### RULE-019: 评分等级映射
- **File**: `core/strategy.py:371-378`
- **Function**: `score_momentum_core`
- **Condition**: score ≥ 65 = A, ≥ 50 = B, ≥ 35 = C, else = D
- **Type**: ACCOUNTING

---

## 缠论 ALPHA 规则

### RULE-020: K 线包含处理
- **File**: `core/chanlun_engine.py:39`
- **Function**: `inclusion_process`
- **Condition**: Adjacent bars with overlapping high/low ranges → merge
- **Action**: Direction-dependent: up trend → max(high), max(low); down trend → min(high), min(low)
- **Type**: ALPHA (data preprocessing)

### RULE-021: 分型检测
- **File**: `core/chanlun_engine.py:64`
- **Function**: `fractals`
- **Condition**: Top: bar.high ≥ left.high, ≥ right.high, and > at least one neighbor. Bottom: bar.low ≤ left.low, ≤ right.low, and < at least one neighbor
- **Type**: ALPHA

### RULE-022: 笔连接
- **File**: `core/chanlun_engine.py:75`
- **Function**: `strokes`
- **Condition**: Consecutive alternating top/bottom fractals with ≥ 2 bar gap; same kind → keep the more extreme
- **Type**: ALPHA

### RULE-023: 线段
- **File**: `core/chanlun_engine.py:88`
- **Function**: `segments`
- **Condition**: 3 consecutive strokes, majority same direction → segment
- **Type**: ALPHA

### RULE-024: 中枢
- **File**: `core/chanlun_engine.py:100`
- **Function**: `pivots`
- **Condition**: 3 overlapping strokes → ZD = max(lows), ZG = min(highs), ZD < ZG
- **Type**: ALPHA

### RULE-025: 背驰检测
- **File**: `core/chanlun_engine.py:128`
- **Function**: `divergence`
- **Condition**: Same-direction fractal pair, price extreme increased but MACD histogram sum decreased by ≥ 20%
- **Type**: ALPHA

### RULE-026: 一买条件
- **File**: `core/chanlun_engine.py:203`
- **Function**: `analyze_chanlun`
- **Condition**: `div.type == "bottom_divergence"` and (downtrend or range)
- **Type**: ALPHA (BUY)

### RULE-027: 二买条件
- **File**: `core/chanlun_engine.py:212-214`
- **Function**: `analyze_chanlun`
- **Condition**: ≥ 2 bottom fractals, bottoms[-1].price > bottoms[-2].price, trend in (uptrend, range)
- **Type**: ALPHA (BUY)

### RULE-028: 三买条件
- **File**: `core/chanlun_engine.py:201-202`
- **Function**: `analyze_chanlun`
- **Condition**: last > pivot.zg, stroke[-1].direction = up, bars[-1].low > pivot.zg
- **Type**: ALPHA (BUY)

### RULE-029: 一卖条件
- **File**: `core/chanlun_engine.py:209`
- **Function**: `analyze_chanlun`
- **Condition**: `div.type == "top_divergence"`
- **Type**: ALPHA (SELL)

### RULE-030: 平台突破/回踩 (二买)
- **File**: `core/chanlun_engine.py:142`
- **Function**: `trend_breakout_signal`
- **Condition**: 8-bar compression (width < 12%), breakout > base_high + 1.25x volume, retest holds above 98.5% of base_high
- **Type**: ALPHA (BUY)

---

## 卖出规则

### RULE-031: 目标止盈
- **File**: `core/strategy.py:441`
- **Function**: `SellRules.evaluate`
- **Condition**: `cp >= tp` (current profit >= target_pct, default 8%)
- **Action**: SELL at close
- **Type**: EXECUTION

### RULE-032: 移动止盈
- **File**: `core/strategy.py:445-449`
- **Function**: `SellRules.evaluate`
- **Condition**: `mp_pct >= trail_trigger` (default 3%), then `lo <= ep * (1 + mp_pct * (1 - rate))`
- **Action**: SELL at trail_price
- **Type**: EXECUTION

### RULE-033: 硬止损
- **File**: `core/strategy.py:452`
- **Function**: `SellRules.evaluate`
- **Condition**: `cp <= sp` (default -2.8%)
- **Action**: SELL at close
- **Type**: EXECUTION | RISK

### RULE-034: 保本卖出
- **File**: `core/strategy.py:456`
- **Function**: `SellRules.evaluate`
- **Condition**: `mp_pct >= breakeven_peak` (default 3%) and `cp < breakeven_thresh` (default 0.5%)
- **Action**: SELL at close
- **Type**: EXECUTION

### RULE-035: 弱持仓卖出
- **File**: `core/strategy.py:460`
- **Function**: `SellRules.evaluate`
- **Condition**: `hold >= weak_hold` (default 2) and `cp < weak_thresh` (default -0.5%)
- **Action**: SELL at close
- **Type**: EXECUTION

### RULE-036: 时间卖出
- **File**: `core/strategy.py:463`
- **Function**: `SellRules.evaluate`
- **Condition**: `hold >= max_hold` (default 5)
- **Action**: SELL at close
- **Type**: EXECUTION

---

## RISK 规则

### RULE-037: 周末/节假日拦截
- **File**: `risk/risk_manager.py:148`
- **Function**: `_check_weekend`
- **Condition**: weekday ≥ 5 OR not trading day
- **Action**: BLOCK
- **Type**: RISK

### RULE-038: 单标仓位上限
- **File**: `risk/risk_manager.py:157`
- **Function**: `_check_position_cap`
- **Condition**: `(current + new) / total_assets > 0.30`
- **Action**: BLOCK
- **Type**: RISK

### RULE-039: 大盘熔断
- **File**: `risk/risk_manager.py:186`
- **Function**: `_check_market_crash`
- **Condition**: `health_score < 30`
- **Action**: BLOCK all BUY
- **Type**: RISK

### RULE-040: 主力流出熔断
- **File**: `risk/risk_manager.py:197`
- **Function**: `_check_outflow`
- **Condition**: `net_outflow < -80_000_000_000` (< -800亿)
- **Action**: BLOCK all BUY
- **Type**: RISK

### RULE-041: 情绪周期熔断
- **File**: `risk/risk_manager.py:208`
- **Function**: `_check_sentiment`
- **Condition**: phase in (ice, cooldown) and multiplier ≤ 0.3
- **Action**: BLOCK all BUY
- **Type**: RISK

### RULE-042: 板块集中度
- **File**: `risk/risk_manager.py:221`
- **Function**: `_check_sector_concentration`
- **Condition**: `sector_ratio > sector_max_concentration` (default 0.40)
- **Action**: BLOCK
- **Type**: RISK

### RULE-043: 总敞口上限
- **File**: `risk/risk_manager.py:268`
- **Function**: `_check_total_exposure`
- **Condition**: `exposure_ratio > total_exposure_limit` (default 0.80)
- **Action**: BLOCK
- **Type**: RISK

### RULE-044: T+1 方向冲突
- **File**: `risk/risk_manager.py:296`
- **Function**: `_check_t1_rule`
- **Condition**: 今日已有同方向记录; 买入时已有持仓; 卖出时无可售持股
- **Action**: BLOCK
- **Type**: RISK

### RULE-045: 禁止摊平
- **File**: `risk/risk_manager.py:362`
- **Function**: `_check_avg_down`
- **Condition**: 已有持仓时同方向买入
- **Action**: BLOCK
- **Type**: RISK

### RULE-046: 尾盘追高拦截
- **File**: `risk/risk_manager.py:377`
- **Function**: `_check_tail_chase`
- **Condition**: `now_time >= 14:35`
- **Action**: BLOCK all BUY
- **Type**: RISK

### RULE-047: 冻结期检查
- **File**: `risk/risk_manager.py:384`
- **Function**: `_check_freeze`
- **Condition**: `today < freeze_state[symbol]`
- **Action**: BLOCK
- **Type**: RISK

### RULE-048: sell_only_mode 熔断
- **File**: `execution/direct_executor.py:496-519`
- **Condition**: `strategy_params.sell_only_mode == true` or `redline_state.tripped == true`
- **Action**: 禁止所有买入，仅允许卖出
- **Type**: RISK

### RULE-049: 情绪冰点龙头豁免
- **File**: `execution/direct_executor.py:521-545`
- **Condition**: phase=cooldown/ice AND mult ≤ 0.3 → 仅龙头 (dragon, sector_leader, conf ≥ 0.70) 可买
- **Action**: 拦截普通跟风买入
- **Type**: RISK

### RULE-050: 竞价未撮合撤单
- **File**: `execution/direct_executor.py:141-222`
- **Function**: `check_call_auction_unmatched_cancel`
- **Condition**: 09:29:55, 竞价买入挂单未成交, 开盘价/现价 < 挂单价
- **Action**: 撤单
- **Type**: RISK | EXECUTION

### RULE-051: 挂单超时撤单
- **File**: `execution/direct_executor.py:346-356`
- **Condition**: 挂单 > 5 min 未成交, or 价格偏离 > 1.5%
- **Action**: 撤单
- **Type**: RISK | EXECUTION

### RULE-052: 盘中动态熔断
- **File**: `core/market_regime_check.py:55`
- **Function**: `intraday_dynamic_check`
- **Condition**: limitdown ≥ 20 OR broken_rate ≥ 45% OR index ≤ -2%
- **Action**: 全市场熔断 (sell_only_mode=true, multiplier=0.0)
- **Type**: RISK

### RULE-053: 连板深度核验
- **File**: `core/market_regime_check.py:244-260`
- **Function**: `iron_rule_gate`
- **Condition**: streak ≥ 3 → 需要 dragon + sector_support + score ≥ 10
- **Action**: BLOCK 非真龙连板
- **Type**: RISK

### RULE-054: 退潮期门禁
- **File**: `core/market_regime_check.py:301-322`
- **Function**: `iron_rule_gate`
- **Condition**: panic_ebb → 全部禁止; exhaustion_ebb → 仅首板、禁追高; 退潮 → 仅龙头
- **Action**: BLOCK
- **Type**: RISK

### RULE-055: 垃圾时间门禁
- **File**: `core/market_regime_check.py:326-332`
- **Function**: `iron_rule_gate`
- **Condition**: 10:00-14:30 非龙头禁买; 追高仅真龙可过
- **Action**: BLOCK
- **Type**: RISK

---

## EXECUTION 规则

### RULE-056: 候选处理去重
- **File**: `execution/direct_executor.py:39-52`
- **Function**: `load_processed_ids`
- **Condition**: 已记录事件 (executed/risk_blocked/t1_conflict/condition_rejected) 跳过
- **Type**: EXECUTION

### RULE-057: AGY/LLM 审核门禁
- **File**: `execution/direct_executor.py:451-456`
- **Function**: `main`
- **Condition**: 需要 llm_approved=true 或 agy_approved=true
- **Type**: EXECUTION

### RULE-058: 催化剂冷却检查
- **File**: `execution/pipeline.py:39-72`
- **Function**: `is_catalyst_enabled`
- **Condition**: `today < cooldown_until` OR `enabled == false`
- **Type**: EXECUTION

### RULE-059: 分批处理上限
- **File**: `execution/direct_executor.py:568-569`
- **Function**: `main`
- **Condition**: `BATCH_SIZE = 2` 每次最多处理 2 笔候选
- **Type**: EXECUTION

### RULE-060: 注册 + 下单序列
- **File**: `execution/pipeline.py:473-498`
- **Function**: `risk_check_and_execute`
- **Condition**: registration ok → place_order → Feishu notify
- **Type**: EXECUTION
