# Rules Contribution Map — 策略规则溯源映射

60 条规则 (RULE-001 至 RULE-060) 到源文件/函数的完整映射。

---

## RULE-001 至 RULE-010: FILTER

| Rule | 文件 | 函数 | 类型 |
|------|------|------|------|
| RULE-001 | `core/strategy.py:199` | `screen_candidates` | FILTER |
| RULE-002 | `core/strategy.py:206` | `screen_candidates` | FILTER |
| RULE-003 | `core/strategy.py:208` | `screen_candidates` | FILTER |
| RULE-004 | `risk/risk_manager.py:353` | `_check_st_blacklist` | FILTER \| RISK |
| RULE-005 | `core/strategy.py:269` | `score_momentum_core` | FILTER |
| RULE-006 | `core/strategy.py:271` | `score_momentum_core` | FILTER |
| RULE-007 | `core/strategy.py:195` | `screen_candidates` | FILTER |
| RULE-008 | `core/strategy.py:202` | `screen_candidates` | FILTER |
| RULE-009 | `risk/risk_manager.py:134` | `_check_symbol` | FILTER \| RISK |
| RULE-010 | `execution/direct_executor.py:549` | `main` | FILTER \| RISK |

**6 文件, 4 函数** — FILTER 集中在 `core/strategy.py` (2 函数) 和 `risk/risk_manager.py` (2 函数), 外加 `execution/direct_executor.py`。

---

## RULE-011 至 RULE-019: ALPHA

| Rule | 文件 | 函数 | 类型 |
|------|------|------|------|
| RULE-011 | `core/strategy.py:278` | `score_momentum_core` | ALPHA |
| RULE-012 | `core/strategy.py:293` | `score_momentum_core` | ALPHA |
| RULE-013 | `core/strategy.py:304` | `score_momentum_core` | ALPHA |
| RULE-014 | `core/strategy.py:315` | `score_momentum_core` | ALPHA |
| RULE-015 | `core/strategy.py:327` | `score_momentum_core` | ALPHA |
| RULE-016 | `core/strategy.py:343` | `score_momentum_core` | ALPHA |
| RULE-017 | `core/strategy.py:354` | `score_momentum_core` | ALPHA |
| RULE-018 | `core/strategy.py:359` | `score_momentum_core` | ALPHA |
| RULE-019 | `core/strategy.py:371` | `score_momentum_core` | ACCOUNTING |

**1 文件, 1 函数** — 全部 9 条 RULE 集中在 `score_momentum_core` 内, 包含 8 个 alpha 因子 + 等级映射。

---

## RULE-020 至 RULE-030: 缠论 ALPHA

| Rule | 文件 | 函数 | 类型 |
|------|------|------|------|
| RULE-020 | `core/chanlun_engine.py:39` | `inclusion_process` | ALPHA (预处理) |
| RULE-021 | `core/chanlun_engine.py:64` | `fractals` | ALPHA |
| RULE-022 | `core/chanlun_engine.py:75` | `strokes` | ALPHA |
| RULE-023 | `core/chanlun_engine.py:88` | `segments` | ALPHA |
| RULE-024 | `core/chanlun_engine.py:100` | `pivots` | ALPHA |
| RULE-025 | `core/chanlun_engine.py:128` | `divergence` | ALPHA |
| RULE-026 | `core/chanlun_engine.py:203` | `analyze_chanlun` | ALPHA (BUY) |
| RULE-027 | `core/chanlun_engine.py:212` | `analyze_chanlun` | ALPHA (BUY) |
| RULE-028 | `core/chanlun_engine.py:201` | `analyze_chanlun` | ALPHA (BUY) |
| RULE-029 | `core/chanlun_engine.py:209` | `analyze_chanlun` | ALPHA (SELL) |
| RULE-030 | `core/chanlun_engine.py:142` | `trend_breakout_signal` | ALPHA (BUY) |

**1 文件, 7 函数** — 所有缠论规则封装在 `chanlun_engine.py` 中, 管线清晰: 预处理→分型→笔→线段→中枢→背驰→买卖点。

---

## RULE-031 至 RULE-036: SELL

| Rule | 文件 | 函数 | 类型 |
|------|------|------|------|
| RULE-031 | `core/strategy.py:441` | `SellRules.evaluate` | EXECUTION |
| RULE-032 | `core/strategy.py:445` | `SellRules.evaluate` | EXECUTION |
| RULE-033 | `core/strategy.py:452` | `SellRules.evaluate` | EXECUTION \| RISK |
| RULE-034 | `core/strategy.py:456` | `SellRules.evaluate` | EXECUTION |
| RULE-035 | `core/strategy.py:460` | `SellRules.evaluate` | EXECUTION |
| RULE-036 | `core/strategy.py:463` | `SellRules.evaluate` | EXECUTION |

**1 文件, 1 类方法** — 全部 6 条卖出规则集中在 `SellRules.evaluate()` 内, 顺序执行, 首次触发即返回。

---

## RULE-037 至 RULE-055: RISK

| Rule | 文件 | 函数 | 类型 |
|------|------|------|------|
| RULE-037 | `risk/risk_manager.py:148` | `_check_weekend` | RISK |
| RULE-038 | `risk/risk_manager.py:157` | `_check_position_cap` | RISK |
| RULE-039 | `risk/risk_manager.py:186` | `_check_market_crash` | RISK |
| RULE-040 | `risk/risk_manager.py:197` | `_check_outflow` | RISK |
| RULE-041 | `risk/risk_manager.py:208` | `_check_sentiment` | RISK |
| RULE-042 | `risk/risk_manager.py:221` | `_check_sector_concentration` | RISK |
| RULE-043 | `risk/risk_manager.py:268` | `_check_total_exposure` | RISK |
| RULE-044 | `risk/risk_manager.py:296` | `_check_t1_rule` | RISK |
| RULE-045 | `risk/risk_manager.py:362` | `_check_avg_down` | RISK |
| RULE-046 | `risk/risk_manager.py:377` | `_check_tail_chase` | RISK |
| RULE-047 | `risk/risk_manager.py:384` | `_check_freeze` | RISK |
| RULE-048 | `execution/direct_executor.py:496` | `main` | RISK |
| RULE-049 | `execution/direct_executor.py:521` | `main` | RISK |
| RULE-050 | `execution/direct_executor.py:141` | `check_call_auction_unmatched_cancel` | RISK \| EXECUTION |
| RULE-051 | `execution/direct_executor.py:346` | `reconcile_pending_orders` | RISK \| EXECUTION |
| RULE-052 | `core/market_regime_check.py:55` | `intraday_dynamic_check` | RISK |
| RULE-053 | `core/market_regime_check.py:244` | `iron_rule_gate` | RISK |
| RULE-054 | `core/market_regime_check.py:301` | `iron_rule_gate` | RISK |
| RULE-055 | `core/market_regime_check.py:326` | `iron_rule_gate` | RISK |

**4 文件, 16 函数** — RISK 分布最广:
- `risk_manager.py`: 11 条 (13 层风控中 11 层)
- `direct_executor.py`: 4 条 (熔断/情绪防御/撤单)
- `market_regime_check.py`: 4 条 (动态熔断 + 铁律门禁)

---

## RULE-056 至 RULE-060: EXECUTION

| Rule | 文件 | 函数 | 类型 |
|------|------|------|------|
| RULE-056 | `execution/direct_executor.py:39` | `load_processed_ids` | EXECUTION |
| RULE-057 | `execution/direct_executor.py:451` | `main` | EXECUTION |
| RULE-058 | `execution/pipeline.py:39` | `is_catalyst_enabled` | EXECUTION |
| RULE-059 | `execution/direct_executor.py:568` | `main` | EXECUTION |
| RULE-060 | `execution/pipeline.py:473` | `risk_check_and_execute` | EXECUTION |

**2 文件, 5 函数** — 执行规则分布在 `direct_executor.py` (入口) 和 `pipeline.py` (管线)。

---

## 汇总

| 类型 | 规则数 | 文件数 | 函数数 | 核心文件 |
|------|--------|--------|--------|----------|
| FILTER | 10 | 3 | 4 | `core/strategy.py`, `risk/risk_manager.py` |
| ALPHA | 9 (动量) | 1 | 1 | `core/strategy.py` |
| ALPHA | 11 (缠论) | 1 | 7 | `core/chanlun_engine.py` |
| SELL | 6 | 1 | 1 | `core/strategy.py` |
| RISK | 19 | 4 | 16 | `risk/risk_manager.py` (11), `execution/direct_executor.py` (4), `core/market_regime_check.py` (4) |
| EXECUTION | 5 | 2 | 5 | `execution/direct_executor.py`, `execution/pipeline.py` |
| **总计** | **60** | **7** | **~30** | |

### 按文件热度

| 文件 | 规则数 | 占比 |
|------|--------|------|
| `core/strategy.py` | 17 | 28.3% |
| `risk/risk_manager.py` | 12 | 20.0% |
| `execution/direct_executor.py` | 8 | 13.3% |
| `core/chanlun_engine.py` | 11 | 18.3% |
| `core/market_regime_check.py` | 4 | 6.7% |
| `execution/pipeline.py` | 2 | 3.3% |

**策略密度最高**: `core/strategy.py` (17 条), `risk/risk_manager.py` (12 条), `core/chanlun_engine.py` (11 条) — 三文件占总规则数的 66.7%。
