# Parameter Registry — Astock 参数注册表

## 参数来源分布

| 来源类型 | 文件 | 参数数量 |
|----------|------|----------|
| JSON 配置文件 | config/strategy_params.json | ~50+ |
| Python 默认值 | core/strategy.py | ~20 |
| Python 默认值 | core/strategy_profiles.py | ~30 per profile |
| Python 默认值 | risk/risk_manager.py | ~10 |
| Python 默认值 | execution/pipeline.py | ~5 |
| Python 默认值 | scripts/backtest_2yr.py | ~10 |
| Python 默认值 | scripts/backtest_engine.py | ~15 |
| Python 默认值 | execution/direct_executor.py | ~8 |
| argparse | scripts/backtest_2yr.py | 4 flags |
| argparse | scripts/backtest_engine.py | 6 flags |
| argparse | scripts/auto_iterate.py | 5 flags |
| 环境变量 | config/__init__.py | 1 (ASTOCK_DRY_RUN) |

---

## 1. score_weights (评分权重)

| Parameter | File | Line | Default | Type | Used By | Meaning |
|-----------|------|------|---------|------|---------|---------|
| volume | core/strategy.py | 232 | 25 | int | score_momentum_core | 量比因子权重 |
| dh | core/strategy.py | 233 | 20 | int | score_momentum_core | 距10日高因子权重 |
| ma | core/strategy.py | 234 | 20 | int | score_momentum_core | 均线排列因子权重 |
| rsi | core/strategy.py | 235 | 15 | int | score_momentum_core | RSI 因子权重 |
| chg | core/strategy.py | 236 | 15 | int | score_momentum_core | 日涨幅因子权重 |
| vol_bonus | core/strategy.py | 237 | 5 | int | score_momentum_core | 波动率加分权重 |
| new_high_bonus | core/strategy.py | 238 | 5 | int | score_momentum_core | 新高加分权重 |
| pullback_bonus | core/strategy.py | 239 | 10 | int | score_momentum_core | 回踩加分权重 |

## 2. Trade Parameters (交易参数)

| Parameter | File | Line | Default | Type | Used By | Meaning |
|-----------|------|------|---------|------|---------|---------|
| target_pct | core/strategy.py | 242 | 8 | float | SellRules | 目标止盈百分比 |
| stop_pct | core/strategy.py | 243 | -2.8 | float | SellRules | 硬止损百分比 |
| hold_days | core/strategy.py | 244 | 3 | int | SellRules | 预期持仓天数 |
| min_close | core/strategy.py | 37 (screen) | 10 | float | screen_candidates | 最低收盘价过滤 |
| min_vr | core/strategy.py | 247 | 0.8 | float | score_momentum_core | 最低量比 |
| min_rs | core/strategy.py | 248 | 25 | float | score_momentum_core | 最低 RSI |
| ma_pct | core/strategy.py | 249 | 0.95 | float | score_momentum_core | MA20 位置要求 |

## 3. SellRules (卖出规则)

| Parameter | File | Line | Default | Type | Used By | Meaning |
|-----------|------|------|---------|------|---------|---------|
| trail_trigger | core/strategy.py | 409 | 3.0 | float | SellRules | 触发移动止盈的最低盈利% |
| trail_high_rate | core/strategy.py | 410 | 0.3 | float | SellRules | 高盈利回撤比率 (大收益锁利) |
| trail_low_rate | core/strategy.py | 411 | 0.4 | float | SellRules | 低盈利回撤比率 |
| trail_high_thresh | core/strategy.py | 412 | 5.0 | float | SellRules | 高低回撤比率分界阈值 |
| breakeven_peak | core/strategy.py | 413 | 3.0 | float | SellRules | 触发保本的最低峰值 |
| breakeven_thresh | core/strategy.py | 414 | 0.5 | float | SellRules | 保本触发回落阈值 |
| weak_hold | core/strategy.py | 415 | 2 | int | SellRules | 弱持仓检查起始天数 |
| weak_thresh | core/strategy.py | 416 | -0.5 | float | SellRules | 弱持仓收益阈值 |
| max_hold | core/strategy.py | 417 | 5 | int | SellRules | 最大持仓天数 |

## 4. Regime (市场体制)

| Parameter | File | Line | Default | Type | Used By | Meaning |
|-----------|------|------|---------|------|---------|---------|
| euphoria | core/strategy.py | 129 | (65, 2, 0.35) | tuple | get_regime_params | 高潮期 (min_score, max_pos, cap_pct) |
| hot | core/strategy.py | 130 | (70, 1, 0.20) | tuple | get_regime_params | 走强期 |
| warmup | core/strategy.py | 131 | (60, 5, 0.30) | tuple | get_regime_params | 震荡期 |
| cooldown | core/strategy.py | 132 | (60, 3, 0.28) | tuple | get_regime_params | 退潮期 |
| ice | core/strategy.py | 133 | (70, 1, 0.15) | tuple | get_regime_params | 极寒期 |

## 5. Risk Manager (13 层风控)

| Parameter | File | Line | Default | Type | Used By | Meaning |
|-----------|------|------|---------|------|---------|---------|
| max_position_count | risk/risk_manager.py | 86 | 5 | int | batch_check | 最大持仓数 |
| sector_max_concentration | risk/risk_manager.py | 84 | 0.40 | float | _check_sector_concentration | 板块集中度上限 |
| total_exposure_limit | risk/risk_manager.py | 85 | 0.80 | float | _check_total_exposure | 总敞口上限 |
| position_cap_ratio | risk/risk_manager.py | 180 | 0.30 | float | _check_position_cap | 单标仓位上限 |
| market_crash_threshold | risk/risk_manager.py | 192 | 30 | float | _check_market_crash | 大盘熔断阈值 |
| outflow_threshold | risk/risk_manager.py | 202 | -80_000_000_000 | float | _check_outflow | 主力流出熔断 |
| tail_chase_time | risk/risk_manager.py | 380 | 14:35 | time | _check_tail_chase | 尾盘追高拦截时间 |
| sentiment_cooldown_mult | risk/risk_manager.py | 215 | 0.3 | float | _check_sentiment | 情绪系数熔断阈值 |

## 6. Hard Filters (硬过滤)

| Parameter | File | Line | Default | Type | Used By |
|-----------|------|------|---------|------|---------|
| min_vr | config/strategy_params.json | 246 | 0.7 | float | screen_candidates |
| min_rs | config/strategy_params.json | 244 | 30 | float | screen_candidates |
| ma_pct | config/strategy_params.json | 245 | 0.95 | float | screen_candidates |

## 7. Global Guards (全局防护)

| Parameter | File | Line | Default | Type | Meaning |
|-----------|------|------|---------|------|---------|
| max_position_count | strategy_params.json | 192 | 5 | int | 最大持仓数 |
| max_single_position_pct | strategy_params.json | 193 | 0.35 | float | 单票仓位上限 |
| sector_max_concentration | strategy_params.json | 194 | 0.40 | float | 板块集中度上限 |
| sell_only_mode | strategy_params.json | 195 | false | bool | 只卖不买模式 |
| tighten_stops | strategy_params.json | 196 | false | bool | 收紧止损 |
| total_exposure_limit | strategy_params.json | 197 | 0.80 | float | 总仓位上限 |

## 8. Sentiment (情绪周期)

| Parameter | File | Line | Default | Type | Meaning |
|-----------|------|------|---------|------|---------|
| phase | strategy_params.json | 200 | "" | string | 情绪相位 |
| multiplier | strategy_params.json | 201 | 1.0 | float | 仓位乘数 (0.0-1.0) |

## 9. Backtest CLI (argparse)

| Parameter | File | Line | Default | Type | Meaning |
|-----------|------|------|---------|------|---------|
| --profile | backtest_2yr.py | 756 | momentum_v5 | str | 策略档案 |
| --use-best | backtest_2yr.py | 757 | False | bool | 使用最优参数 |
| --start | backtest_engine.py | 861 | 2026-06-01 | str | 回测开始日期 |
| --end | backtest_engine.py | 862 | 2026-09-30 | str | 回测结束日期 |
| --capital | backtest_engine.py | 863 | 400000 | float | 初始资金 |
| --min-score | backtest_engine.py | 866 | 30 | int | 最低信号评分 |

## 10. Auto Iteration (自动迭代)

| Parameter | File | Line | Default | Type | Meaning |
|-----------|------|------|---------|------|---------|
| hard_filters.min_vr | auto_iterate.py | 32 | 0.8 | float | 迭代搜索空间 |
| hard_filters.min_rs | auto_iterate.py | 33 | 25 | int | 迭代搜索空间 |
| hard_filters.ma_pct | auto_iterate.py | 34 | 0.95 | float | 迭代搜索空间 |
| min_vr | auto_iterate.py | 36 | 1.5 | float | 迭代搜索空间 |
| min_close | auto_iterate.py | 37 | 10.0 | float | 迭代搜索空间 |
| max_pos_pct | auto_iterate.py | 39 | 0.35 | float | 迭代搜索空间 |

## 11. Strategy Profile Defaults (策略档案)

### momentum_v5
| Parameter | Default | Meaning |
|-----------|---------|---------|
| volume/dh/ma/rsi/chg weights | 25/20/20/15/15 | 评分权重 |
| vol_bonus/new_high/pullback | 5/5/10 | 加分权重 |
| target_pct/stop_pct | 8/-2.8 | 目标/止损 |
| hold_days | 3 | 持仓天数 |

### single_yang
| Parameter | Default | Meaning |
|-----------|---------|---------|
| yang_gain | 5.0 | 大阳线涨幅要求 |
| max_consolidation_bars | 9 | 最长回调天数 |
| score_weight | 70 | 基础评分 |

### lotus / ma5_monster / etc.
See core/strategy_profiles.py for each profile's default_params.

---

## Potential Overfit Parameters

| Parameter | Reason |
|-----------|--------|
| stop_pct = -2.8 | 精确到 0.1%，可能过度优化 |
| trail_high_rate = 0.3 | 回撤比率 30% 是否普适 |
| breakeven_peak = 3.0 | 正好 3% 触发保本 |
| trail_trigger = 3.0 | 恰好 3% 才启动移动止盈 |
| regime_map values | 每个体制的 min_score/max_pos 可能过拟合特定市场周期 |
