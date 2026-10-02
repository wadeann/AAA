# Current Strategy Spec — Astock 当前策略规格

## 1. Universe

| 属性 | 值 |
|------|-----|
| 全市场股票 | ~2348 只 (回测) / ~4000+ (实盘全市场) |
| 筛选方式 | 5 路问财搜索 (动量突破/N字反包/倍量首板/平台突破/龙回头) |
| 最小 K 线 | 60 根 (回测), 25 根 (评分) |
| 排除 | ST/*ST/科创板/北交所 (部分策略) |

## 2. Data

| 数据源 | 方式 | 用途 |
|--------|------|------|
| MCP Intel (9001) | K 线/行情/问财/新闻 | 实时分析 |
| MCP Exec (9003) | 账户/持仓/订单 | 执行 |
| data/kline_cache.json | 预缓存 | 回测 |
| config/strategy_params.json | JSON 文件 | 运行时状态 |

## 3. Discovery

**实盘**: 5 路问财并发搜索 → 合并去重 → 写入 JSONL
**回测**: screen_candidates() 5 重硬过滤 → score_momentum_core() 评分

## 4. Trend (趋势)

**动量策略 (momentum_v5)**:
- MA 排列: close > ma5 > ma10 > ma20 → full score
- 距 10 日高距离: < 1% → full score
- RSI 区间: 45-65 → full score

**缠论策略**:
- 周线趋势过滤 (only uptrend/range)
- `compute_ma_trend()`: strong_up/up/range/down/strong_down

## 5. Chanlun (缠论)

See `chanlun_rules.md` for full detail.

核心: inclusion_process → fractals → strokes → segments → pivots → divergence → buy/sell points

## 6. Signal (信号)

### 信号类型
| 类型 | 来源 | 说明 |
|------|------|------|
| momentum_v5 | core/strategy.py | 8 因子动量评分 |
| chan_buy_signal | core/chanlun_engine.py | 缠论一买/二买/三买 |
| limit_up_ladder | MCP | 连板梯队 |
| dragon_screener | execution/dragon_screener_engine.py | 真龙筛选 |
| call_auction_strong | discovery/auction_scanner.py | 竞价强势 |
| opening_sniper | discovery/ | 开盘狙击 |
| sector_volume_breakout | discovery/theme_trigger.py | 板块放量突破 |
| holding_defense | defense/ | 持仓防御 |
| close_sell_signal | defense/close_session_defense.py | 尾盘卖出 |

### 催化剂冷却
Each catalyst type has:
- enabled/disabled
- cooldown_until (date)
- min_confidence threshold
- Empirical Bayes shrunk win rate tracking

## 7. Score (评分)

See `score_model.md` for full detail.

### 主流: momentum_v5 8 因子评分
Total 0-100, grade A/B/C/D
Min score per regime: 60-70

## 8. Entry (入场)

| 条件 | 要求 |
|------|------|
| 硬过滤 | VR ≥ min_vr, RSI ≥ min_rs, close ≥ MA20 × ma_pct |
| 评分 | score ≥ regime_min_score |
| 等级 | grade A or B |
| 仓位 | cash > 0, slots available |
| 风控 | 13 层全部通过 |
| 铁律 | AGY iron_rule_gate PASS |
| 执行 | T+1 无冲突, 非尾盘 |

## 9. Position (仓位)

See `position_model.md` for full formula.

核心: total_assets × adj_pct × sentiment_multiplier → target_value → shares

## 10. Stop (止损)

See SellRules in `strategy.py`:

| 规则 | 条件 | 动作 |
|------|------|------|
| 目标止盈 | cp ≥ target_pct | 市价卖出 |
| 移动止盈 | mp_pct ≥ trail_trigger, lo ≤ trail_price | `ep × (1 + mp_pct × (1 - rate))` |
| 硬止损 | cp ≤ stop_pct | 市价卖出 |
| 保本 | mp_pct ≥ breakeven_peak, cp < breakeven_thresh | 市价卖出 |
| 弱持仓 | hold ≥ weak_hold, cp < weak_thresh | 市价卖出 |
| 时间 | hold ≥ max_hold | 市价卖出 |

## 11. Exit (离场)

See risk_tree.md for SELL-specific checks (only 5 of 13 risk layers apply to sells).

## 12. Risk (风控)

See `risk_tree.md` for full detail.

## 13. Execution (执行)

See `execution_flow.md` for full chain.

## 14. Backtest (回测)

See `backtest_data_flow.md` for data flow and leakage analysis.

### 两个回测引擎:
1. **backtest_2yr.py**: 全市场 2348 只, 2 年, 动量策略
2. **backtest_engine.py**: 缠论策略, 小样本验证

## 15. Reporting (报告)

| 报告 | 存储 | 内容 |
|------|------|------|
| 交易日志 | data/ledger/candidates_{date}.jsonl | 全部候选事件 |
| 状态文件 | data/state/ | strategy_params, market_regime, freeze_state |
| 回测结果 | results/backtest_2yr_results.txt | 完整回测报告 |
| 最优参数 | results/best_config_{profile}.json | 自动迭代最优解 |

---

## KNOWN_ISSUES

### ISSUE-001: 参数双源不一致
- **File**: `config/strategy_params.json` vs `results/best_config_momentum_v5.json`
- **Description**: 运行时 config 与 auto_iterate 最优参数不同步。`--use-best` flag 临时解决，但无同步机制
- **Impact**: 实盘可能运行非最优参数

### ISSUE-002: regime_map 配置吞没
- **File**: `config/strategy_params.json:256`
- **Description**: `"regime_map": {}` 空字典覆盖了 `REGIME_MAP` 默认值
- **Impact**: 已修复为 `cfg.get("regime_map", {}) or SHARED_REGIME_MAP`

### ISSUE-003: 回测引擎分裂
- **File**: `scripts/backtest_2yr.py` vs `scripts/backtest_engine.py`
- **Description**: 两套回测引擎逻辑不同 (动量 vs 缠论)，参数/仓位/退出规则不统一
- **Impact**: 策略验证结果依赖选择哪个引擎

### ISSUE-004: 实时市场状态与回测不一致
- **File**: `core/market_regime_check.py` 盘中熔断写入 market_regime.json
- **Description**: 实盘 market_regime.json 由铁律门禁动态修改，回测时静态加载
- **Impact**: 回测无法准确模拟实盘的市场状态变化

### ISSUE-005: candidate_id 追踪断裂
- **File**: `discovery/full_market_discovery.py`, `execution/direct_executor.py`
- **Description**: 发现阶段生成的 candidate_id 与执行阶段的 intent_id 关联弱
- **Impact**: 难以端到端追踪一笔交易从发现到成交的全链路

### ISSUE-006: AGY fallback 绕过错风控
- **File**: `execution/pipeline.py:336-346`
- **Description**: 风险服务器不可用时，AGY 批准的候选跳过风险检查直接执行
- **Impact**: 实盘可能在没有风控的情况下执行交易
