# COMMANDER PLAN — Phase 2/3/4 作战部署

**制定者**: 指挥官 Agent 1 (30 年 A 股老法师)
**日期**: 2026-10-02
**当前基准**: Phase 1A 完成 (211 tests pass, integrity fixes done)
**关键前提**: 回测引擎已修正，旧参数 -19.08% 是废纸，不考虑

---

## 0. 指挥官风险评估

在布置作战任务前，先说清市场生存的底线。

### 0.1 当前系统最危险的三个缺陷（按致命程度排序）

| 排名 | 缺陷 | 致命程度 | 一句话概括 |
|------|------|----------|-----------|
| **1** | RISK-001 (AGY fail-open) | **致命** | 实盘中如果 RiskMCP 挂了，LLM/AGY 批准的单子会无风控执行。这是账户归零的直接路径。 |
| **2** | SURV-001 (survivorship bias) | **严重** | 回测只在"活下来的"股票上跑。2348 只股里不包括退市的倒霉蛋，你的回测收益就是水上部分，水下冰山你看不见。 |
| **3** | 参数过拟合到旧引擎 | **严重** | best_config_momentum_v5.json 里的参数是在泄漏的引擎上优化出来的。新引擎上这些参数废了 (-19.08%)。你不重新优化，策略永远是个废物。 |

### 0.2 A 股特别注意事项（30 年血泪教训）

1. **T+1 是双刃剑**: 你今天买的，明天才能卖。回测里 T+1 已经正确了。但实盘 pipeline 中的 `get_trading_sessions()` 如果判断错，可能在 T 日就让你买然后 T 日卖，这违反规则。
2. **涨跌停板 ±10%**: 涨停买不进、跌停卖不出。Phase 1A 只做了 suspension (volume=0) 检查，没做涨停板检测。这在实盘会很伤——你看着涨停板股票发出了买入信号，但实际上成交不了。
3. **印花税 0.05%**: 卖单的成本比买单高一截。高换手策略在 A 股就是慢性自杀。Phase 3 优化时要刻意惩罚换手率。
4. **散户不能融券**: 不能做空，只能做多。熊市里你的唯一选择就是空仓。体制检测的准确性直接决定你能不能躲过大跌。
5. **政策市 + 板块轮动**: A 股是政策主导的市场。一条新闻能让整个板块涨停或跌停。板块集中度风控不是为了分散，是为了防止一条新闻让你全军覆没。

### 0.3 指挥官对三个阶段的优先级判断

```
Phase 2 (RISK-001) > Phase 3 (策略重优化) > Phase 4 (幸存者偏差 + 滑点)
```

**理由**: 你赚钱之前，先确保不会死。RISK-001 是实盘的定时炸弹。Phase 3 晚一天做只是晚一天赚钱。Phase 4 是数据精度问题，不影响策略方向。

但是——Phase 3 需要跑 100+ 轮 auto_iterate，这是耗时大户（估计 2-6 小时取决于数据量）。如果人闲着等机器跑完是最蠢的，所以 Phase 3 设置好跑起来，然后 Phase 4 的数据工作可以并行准备。

---

## Phase 2: 风险架构修复 (Risk Architecture)

### 2.1 目标

把 pipeline.py 的 AGY fail-open 变成 **fail-closed**。无论 RiskMCP 是否在线，任何一个交易意图都必须经过 13 层风控检查。

### 2.2 涉及文件

| 文件 | 当前角色 | 变更内容 |
|------|----------|----------|
| `execution/pipeline.py` (lines 290-470) | AGY fallback 逻辑 | **核心变更**: 删除 lines 336-343 的 AGY bypass，改为 fallback 到本地 RiskManager |
| `risk/risk_manager.py` | 13 层本地风控 | **增强**: 增加离线模式适配（当 MCP 不可用时用本地数据降级），补齐缺失的数据源 |
| `execution/pipeline.py` (lines 384-443) | Snapshot checks | **强化**: snapshot 检查现在只是 3 项（现金/持仓上限/T+1），需要补充到与 RiskManager 同等级的覆盖 |
| `tests/test_risk_fail_closed.py` | **新建** | 覆盖 AGY fallback 场景、RiskMCP 超时场景、离线风控逐层通过/拒绝场景 |
| `config/strategy_params.json` | 参数配置 | **不变**（Phase 2 不改参数，只改行为） |

### 2.3 具体方案

#### 2.3.1 核心修改: pipeline.py `risk_check_and_execute()` (lines 336-343)

**当前代码逻辑（FAIL-OPEN）**:
```python
# Line 336-343: AGY fallback — 4次重试全部失败后
agy_approved = [i for i in intents if i.get("llm_approved") or i.get("agy_approved")]
if agy_approved:
    # 直接批准，跳过所有风险检查 ← 这是致命缺陷
    for i in agy_approved:
        results.append({"approved": True, ...})
        i["agy_fallback"] = True
    intents = agy_approved
```

**修改后逻辑（FAIL-CLOSED）**:
```python
# 4次重试全部失败后 → 降级到本地RiskManager
from risk.risk_manager import RiskManager
local_risk = RiskManager()

# 所有intents（不管AGY不AGY）都走本地风控
risk = local_risk.batch_check({"intents": [
    {"symbol": i["symbol"], "direction": i["direction"],
     "quantity": i["quantity"], "price": i["price"], "name": i.get("name", ""),
     "agy_fallback": True}
    for i in intents
]})
# 本地风控返回的结果直接当作risk结果使用
# 如果本地风控也挂了（不应该），拒绝所有intents
```

**关键决策**: AGY 不再有任何特权。当 RiskMCP 不可用时，系统降级到本地 RiskManager，但绝不跳过风控。

#### 2.3.2 RiskManager 离线模式增强

当前 RiskManager 的 13 层检查中，以下层次依赖外部 MCP 调用，离线时会 fail-open (异常被静默吞掉):

| Layer | 依赖 MCP? | 离线时行为 | 需要修改 |
|-------|-----------|-----------|----------|
| 1. symbol | NO | 正常 | 不需要 |
| 2. weekend | YES (get_trading_sessions) | 回退到 weekday 判断 | **标注为降级模式** |
| 3. position_cap | YES (get_balance/get_positions) | 返回 True (无法校验) | **离线时返回 WARNING 而非静默通过** |
| 4. market_crash | YES (get_market_health) | 返回 True (静默通过) | **离线时如果有本地 health cache 则使用，否则保守拒绝** |
| 5. outflow | YES (get_fund_flow) | 返回 True (静默通过) | **离线时使用最后已知的 outflow 值** |
| 6. sentiment | NO (load_state) | 正常 | 不需要 |
| 7. sector_conc | YES (query_data + get_balance) | 返回 True (静默通过) | **离线时 if 离线标记: 采用更保守的集中度限制 (0.25 vs 0.40)** |
| 8. total_exp | YES (get_balance) | 返回 True (静默通过) | **离线时 if 离线标记: 采用更保守的敞口限制 (0.60 vs 0.80)** |
| 9. t1_rule | YES (get_positions + read_jsonl) | **有状态缓存** | 可以工作，读本地日志 |
| 10. st_blacklist | YES (get_blacklist) | 返回 [] (空黑名单) | **使用本地硬编码 ST 判断 + 本地 blacklist 文件** |
| 11. avg_down | YES (get_positions) | 返回 True | **离线时保守拒绝同方向买入** |
| 12. tail_chase | NO (本地时间) | 正常 | 不需要 |
| 13. freeze | NO (load_state) | 正常 | 不需要 |

**修改策略**: 给 RiskManager 增加一个 `offline_mode: bool` 参数。
- `offline_mode=False` (默认): 当前行为不变
- `offline_mode=True`: 各层使用降级策略，偏向保守拒绝而非静默通过

#### 2.3.3 Snapshot 检查强化 (lines 384-443)

当前 snapshot 检查只有三项:
1. 买入: 现金不足 → 拒绝
2. 买入: 持仓数超限 → 拒绝
3. 卖出: 可用数量不足 → 拒绝

**增加**:
4. T+1 冲突检查（当前只有 RiskManager 做了，snapshot 阶段也应该交叉验证）
5. 单标仓位上限检查（与 RiskManager Layer 3 交叉验证，双重保险）
6. 当日已执行记录去重（防止同一 candidate 被重复执行）

#### 2.3.4 实盘交易时段保护

当前 line 313-318: 非交易时段，如果 AGY fallback，仍然可以执行。这应该修改：
- 非交易时段 + AGY fallback: **仍然拒绝**。只在交易日/交易时段才能执行交易。
- 唯一例外: 盘后分析/候选生成 不受交易时段限制（这是 discovery 阶段，不是执行阶段）

#### 2.3.5 测试要求

新建 `tests/test_risk_fail_closed.py`，至少包含：

```
test_agy_fallback_rejected_when_risk_unavailable     — RiskMCP 超时 + AGY=true → 本地风控检查（不是跳过）
test_agy_fallback_local_risk_passes                   — 本地风控通过的情况
test_agy_fallback_local_risk_rejects                  — 本地风控拒绝的情况
test_non_agy_rejected_when_risk_unavailable           — 非 AGY + RiskMCP 超时 → 拒绝
test_offline_mode_sector_conservative                 — 离线模式板块集中度更保守
test_offline_mode_exposure_conservative                — 离线模式敞口限制更保守
test_offline_mode_avg_down_conservative                — 离线模式禁止摊平
test_snapshot_t1_cross_validation                      — snapshot 阶段 T+1 交叉验证
test_snapshot_dedup                                    — 重复 candidate 去重
test_outside_trading_session_always_blocked            — 非交易时段一律拦截
```

目标: **新增 ~15 个测试，全部绿色**。

### 2.4 P&L 影响

| 指标 | 预期影响 |
|------|----------|
| **回测收益** | 无直接影响（回测不使用 pipeline.py） |
| **实盘避险** | **大幅减少尾部风险**，AGY bypass 路径被堵死 |
| **最大回撤改善** | 离线风控自动收紧，熊市里自动减仓 |
| **交易频率** | **微降**: 离线时段更保守，少做少错 |
| **策略夏普** | **微升**: 减少冲动交易，提高交易质量 |

**一句话**: Phase 2 让你少亏钱，而不是多赚钱。这是防守型部署。

### 2.5 引入的风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 离线风控过于保守，错失好机会 | 中 | 机会成本 | 可调降级参数，后期根据实盘数据校准 |
| 本地风控与 RiskMCP 风控结果不一致 | 低 | 执行不一致 | 本地风控是 RiskMCP 的保守近似，偏差方向是更保守 |
| RiskManager 离线模式 BUG 导致正常单被拒 | 低 | 交易中断 | 充分测试，并在首次上线时 dry_run 观察 |

### 2.6 验收标准

- [ ] `pipeline.py` 中 AGY bypass (lines 336-343) 的注释/删除/替换完成
- [ ] `RiskManager` 支持 `offline_mode` 参数，13 层每层有明确的离线降级策略
- [ ] Snapshot 检查从 3 项增加到 6 项
- [ ] 非交易时段一律拦截（移除 AGY 特例）
- [ ] 新增 ~15 个测试全部通过
- [ ] 所有已有 211 个测试不受影响
- [ ] `python -m pytest tests/ -x -q` 全部绿色
- [ ] **人工审查**: pipeline.py 中不再存在任何绕过风控的代码路径

---

## Phase 3: 策略重优化 (Strategy Re-optimization)

### 3.1 目标

在修正后的回测引擎上重新搜索最优参数，消除 -19.08% 的尴尬，让引擎真正赚钱。

### 3.2 前置条件（必须先完成 Phase 2）

Phase 3 不依赖 Phase 2（Phase 2 改的是实盘 pipeline，Phase 3 跑的是回测引擎），所以可以并行启动。但从指挥官角度，Phase 2 的修复是保命措施，应该先确认完成。

**实际建议**: Phase 2 和 Phase 3 可以并行。Phase 2 改 pipeline.py 和 risk_manager.py，Phase 3 跑 backtest_2yr.py，两套代码不冲突。

### 3.3 涉及文件

| 文件 | 当前角色 | 变更内容 |
|------|----------|----------|
| `scripts/backtest_2yr.py` | 主回测引擎 | **不变**（Phase 1A 已修正） |
| `core/strategy.py` | 共享策略模块 | **不变**（策略逻辑正确，只是参数需要重新搜） |
| `scripts/auto_iterate.py` | 自动迭代引擎 | **增强**: 增加 walk-forward 验证模式，增加 early-stopping，增加 ensemble 候选保存 |
| `core/strategy_profiles.py` | 策略 Profile | **不变**（Profile 定义是对的） |
| `config/strategy_params.json` | 策略参数 | **将被覆盖**: 写入新最优参数 |
| `results/best_config_momentum_v5.json` | 最优配置 | **将被覆盖**: 新引擎上的最优解 |
| `results/iteration_log.txt` | 迭代日志 | **追加**: 新迭代记录 |

### 3.4 具体方案

#### 3.4.1 Round 1: 全参数空间搜索

使用 `auto_iterate.py --profile momentum_v5 --rounds 200` 在修正后引擎上重新搜索。

**参数空间** (~50 个参数，见 auto_iterate.py lines 30-165):
- 硬过滤: min_vr, min_rs, ma_pct (3 个)
- 选池: min_vr, min_close (2 个)
- 仓位: max_pos_pct (1 个)
- 卖出 8 参数: trail_trigger, trail_high_rate, trail_low_rate, breakeven_peak, breakeven_thresh, weak_hold, weak_thresh, max_hold (8 个)
- 评分权重 9 参数: volume, dh, ma, rsi, chg, vol_bonus, new_high_bonus, pullback_bonus, target_pct, stop_pct, hold_days (11 个)
- 体制映射 15 参数: 5 个 regime x 3 tuple (15 个)
- Score 阈值等其他参数 (~7 个)

**关键**: composite_score 公式 (auto_iterate.py:241-268) 需要审查。当前公式偏重夏普 (×3.0) 和总收益，但惩罚回撤力度不够 (mdd/10)。对于 A 股这种高波动市场，建议加强回撤惩罚:

```python
# 当前
score -= mdd / 10

# 建议修改为
score -= mdd / 6  # 加大回撤惩罚
score -= max(0, mdd - 20) / 4  # 超过20%回撤的额外惩罚（非线性）
```

**理由**: A 股的 40% 回撤是不可接受的。你看 -19.08% 那个结果，最大回撤 41.90%。如果你的实盘最大回撤超过 25%，你就已经精神崩溃了。参数搜索必须惩罚深度回撤。

#### 3.4.2 Round 2: Walk-Forward Validation

这是区分"运气好拟合"和"真的赚钱"的核心步骤。

**方法**:
1. 将 2 年历史数据分为 4 个窗口: 2024Q4, 2025Q1, 2025Q2, 2025Q3-2026Q3
2. 在 2024Q4 上优化参数 → 在 2025Q1 上验证（样本外）
3. 滚动窗口: 2024Q4-2025Q1 优化 → 2025Q2 验证
4. 最终: 2024Q4-2025Q2 优化 → 2025Q3-2026Q3 验证
5. 取所有窗口的**平均表现**，而非最佳窗口

**需要新增的功能** (`auto_iterate.py`):
```python
def walk_forward_validate(profile: str, windows: list[tuple], rounds_per_window: int = 50):
    """Walk-forward 交叉验证。
    
    Returns:
        {
            "in_sample_avg": {...},
            "out_of_sample_avg": {...},
            "stability_score": float,  # OOS/IS 比值, 越接近1越稳定
            "best_params": dict,       # 所有窗口中最稳定的参数
        }
    """
```

**验收标准**: walk-forward 的样本外夏普 >= 样本内夏普的 60%。如果低于 60%，说明参数过拟合，不要上线。

#### 3.4.3 Round 3: 多 Profile Ensemble

`backtest_2yr.py` 支持多策略 Profile。最优配置不是单个 Profile，而是一个组合。

**目标组合**:
- `momentum_v5`: 动量因子 (主力)
- `trend_following`: 趋势跟踪 (辅助)
- `pullback_reversal`: 回调反转 (辅助)
- 资金分配: 50% / 30% / 20%

**输出**: `results/best_config_ensemble.json` — 组合最优配置

#### 3.4.4 回测参数硬编码检查

在跑优化之前，确认这些回测参数是正确的:

| 参数 | 值 | 位置 | 是否合理 |
|------|-----|------|----------|
| START_DATE | 2024-10-01 | backtest_2yr.py:39 | 2 年数据，合理 |
| END_DATE | 2026-10-01 | backtest_2yr.py:40 | 刚好 2 年，合理 |
| INITIAL_CAPITAL | 400,000 | backtest_2yr.py:41 | 40 万起始资金，散户水平 |
| KLINE_COUNT | 500 | backtest_2yr.py:42 | 500 根日 K 线 ~2 年，够用 |
| MIN_BARS | 120 | backtest_2yr.py:43 | 120 日 ~6 个月，次新股被排除 |
| 佣金 | 0.13% 单向 | backtest_2yr.py (fee line) | **过高**。A 股实际佣金 ~0.025% 单向，印花税 0.05% 卖单。合计买入 0.025%，卖出 0.075%。0.13% 是对旧系统的保守估计，但偏离现实 |
| 印花税 | 隐藏在 0.13% 里 | backtest_2yr.py | 应该拆分: fee_buy=0.00025, fee_sell=0.00075 (佣金+印花税) |

**建议**: 在 Phase 3 起跑前，把佣金拆分为实际的买卖双向费率。0.13% 单向对策略太不公平了——高换手策略会被不合理地惩罚。

#### 3.4.5 运行时间估计

| 步骤 | 轮数 | 单轮耗时 | 总耗时 | 备注 |
|------|------|----------|--------|------|
| Round 1: 全参数搜索 | 200 | ~60-120s | 3.3-6.7h | 取决于 2348 只股票的数据获取速度 |
| Round 2: Walk-forward | 50×3 窗口 | ~60-120s | 2.5-5h | 3 个滚动窗口 |
| Round 3: Ensemble | ~20 组合 | ~60-120s | 0.3-0.7h | 组合探索 |
| **总计** | | | **6-12.5h** | 建议 overnight 运行 |

### 3.5 P&L 影响

| 指标 | 预期改善 | 置信度 |
|------|----------|--------|
| 总收益 | -19.08% → **正收益** (目标 +15% ~ +60%) | 中高 — 泄漏修正后的引擎给了诚实的基础，参数要重新适配 |
| 夏普比率 | -0.24 → **>0.5** (目标 >1.0) | 中 — 取决于策略 alpha 是否真实存在 |
| 最大回撤 | 41.90% → **<25%** (目标 <20%) | 高 — composite_score 惩罚大回撤后会自动避开激进参数 |
| 胜率 | 45.9% → **>50%** | 中 — A 股动量策略胜率通常在 45-55% |
| 盈亏比 | 0.93 → **>1.2** | 中高 — 卖出规则优化应该能截断亏损 |

**一句话**: Phase 3 的目标不是找到"回测最好看"的参数，而是找到"最稳定、最不挑市场"的参数。

### 3.6 引入的风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 参数过拟合到 2024-2026 特定行情 | **高** | 实盘表现远差于回测 | Walk-forward 验证必须通过。如果 OOS/IS < 0.6，拒绝上线 |
| composite_score 公式本身有偏差 | 中 | 优化方向错了 | 多维度审查: 夏普、回撤、胜率、盈亏比、月胜率都要看 |
| 数据质量问题导致假 alpha | 中 | 以为是策略好，其实是数据错 | Phase 4 应该并行处理数据质量 |
| 佣金拆分后参数不适用 | 低 | 需要重新跑一次 | 在跑优化前就拆分佣金 |

### 3.7 验收标准

- [ ] 修正后引擎 + 新参数的回测收益 > 0% (底线)
- [ ] 夏普比率 > 0.5 (基本要求)
- [ ] 最大回撤 < 25% (风控底线)
- [ ] Walk-forward OOS 夏普 / IS 夏普 > 0.6 (稳健性)
- [ ] 胜率 > 48%
- [ ] 盈亏比 > 1.0
- [ ] 月胜率 > 50% (24 个月中至少 12 个月盈利)
- [ ] 单月最大亏损 < 8%
- [ ] 佣金拆分为买卖双向实际费率
- [ ] `config/strategy_params.json` 更新为新最优参数
- [ ] `results/best_config_momentum_v5.json` 更新
- [ ] 迭代日志完整记录所有轮次

**如果达不到**: 说明 momentum 策略在当前市场环境下 alpha 不足。考虑 Profile 升级或者加入 Chanlun 信号做增强。

---

## Phase 4: 幸存者偏差 + 滑点修复 (Data Quality)

### 4.1 目标

修正回测中的数据质量缺陷，让回测结果更接近实盘。

### 4.2 涉及文件

| 文件 | 当前角色 | 变更内容 |
|------|----------|----------|
| `scripts/stock_universe_full.py` | 硬编码 2348 只股票 | **新增**: 历史成分股数据（退市股列表 + IPO 日期） |
| `scripts/backtest_2yr.py` | 主回测引擎 | **修改**: universe 加载逻辑支持时间点过滤（当前日期之后的 IPO 排除） |
| `scripts/backtest_engine.py` | 缠论回测引擎 | **修改**: 同 backtest_2yr.py |
| `core/strategy.py` | 共享策略模块 | **修改**: `screen_candidates` 增加退市/ST 标记检查 |
| **NEW** `data/delisted_stocks.json` | 退市股清单 | **新建**: 2024-2026 年退市的 A 股完整数据 |
| **NEW** `data/ipo_dates.json` | IPO 日期清单 | **新建**: 每只股票的上市日期 |
| `core/slippage.py` | **新建** | 滑点模型: 按流动性/市值/波动率计算预期滑点 |
| `tests/test_slippage.py` | **新建** | 滑点模型测试 |
| `tests/test_survivorship.py` | **新建** | 幸存者偏差修复验证 |

### 4.3 具体方案

#### 4.3.1 SURV-001: 幸存者偏差修复

**问题本质**: `stock_universe_full.py` 里的 2348 只股票是"现在还在交易"的股票。2024-2026 年间退市的股票不在里面，但它们的糟糕表现本来应该在回测里拖后腿。

**修复方法**:

1. **退市股补偿**: 创建一个 `data/delisted_stocks.json`，包含退市日期、退市前最后价格、退市原因。在回测中，这些股票在退市日期之前**应该参与选股**，退市日期之后**强制平仓（价格归零或退市结算价）**。

2. **IPO 日期过滤**: 创建一个 `data/ipo_dates.json`。在回测循环中，`curr_date < ipo_date` 的股票不出现在候选中。

   ```python
   # backtest_2yr.py 中修改 universe 加载逻辑
   def get_active_universe(curr_date: str) -> list[str]:
       """获取 curr_date 当天实际可交易的股票池."""
       active = []
       for sym in STOCK_UNIVERSE:
           ipo_date = IPO_DATES.get(sym)
           delist_date = DELISTED_STOCKS.get(sym, {}).get("delist_date")
           if ipo_date and curr_date < ipo_date:
               continue  # 还没上市
           if delist_date and curr_date >= delist_date:
               continue  # 已退市
           active.append(sym)
       return active
   ```

3. **数据获取困难**: 退市股数据可能无法从当前 MCP 获取（已退市的股票可能不在数据源中）。如果不能获取 K 线，可以采用以下降级方案:
   - 假设退市股在存续期间的表现为同类股票中位数
   - 在退市日用一个惩罚性的结算价格（如 -50%）强制平仓
   - 实在获取不到就标记为 KNOWN_LIMITATION，至少要知道这个偏差的方向和量级

#### 4.3.2 SLIPPAGE-001: 滑点模型

**问题本质**: 两个回测引擎都假设以指定价格完全成交。现实中:
- 小盘股 (<50 亿流通市值): 滑点 0.3-0.5%
- 中盘股 (50-200 亿): 滑点 0.1-0.3%
- 大盘股 (>200 亿): 滑点 0.05-0.15%
- 涨停板追买: 根本买不到
- 跌停板止损: 根本卖不出

**滑点模型** (`core/slippage.py`):

```python
def estimate_slippage(
    symbol: str,
    direction: str,  # "buy" or "sell"
    intended_price: float,
    volume_today: float,
    avg_volume_20d: float,
    market_cap: float,  # 流通市值（亿）
    is_limit_up: bool = False,
    is_limit_down: bool = False,
) -> tuple[float, bool]:
    """
    Returns:
        (execution_price, is_filled)
        - 如果涨停买 / 跌停卖: (intended_price, False)
        - 否则: (intended_price * (1 ± slippage_ratio), True)
    """
    # 涨跌停不可交易
    if direction == "buy" and is_limit_up:
        return (intended_price, False)
    if direction == "sell" and is_limit_down:
        return (intended_price, False)

    # 基础滑点率
    if market_cap < 30:
        base = 0.004  # 0.4%
    elif market_cap < 100:
        base = 0.0025  # 0.25%
    elif market_cap < 500:
        base = 0.0015  # 0.15%
    else:
        base = 0.0008  # 0.08%

    # 成交量调整: 当日买入量占日均量比例越高，滑点越大
    vol_ratio = volume_today / avg_volume_20d if avg_volume_20d > 0 else 1.0
    vol_mult = min(vol_ratio, 3.0)  # 最高 3 倍

    slippage = base * vol_mult

    if direction == "buy":
        price = intended_price * (1 + slippage)
    else:
        price = intended_price * (1 - slippage)

    return (round(price, 2), True)
```

**集成到回测引擎**:
- `backtest_2yr.py`: 在买入执行（`ed = dates[di+1]` 的 open）和卖出执行（`pending_sells`）时调用 `estimate_slippage`
- `backtest_engine.py`: 在买入和止损执行时调用

#### 4.3.3 涨跌停板检测增强

Phase 1A 只做了 suspension (volume=0) 检测。Phase 4 补上真正的涨跌停板检测。

**所需数据**: 前一日收盘价（已在 K 线数据中可用）。

```python
def is_limit_up(bars: list[dict], limit_ratio: float = 0.10) -> bool:
    """检测当日是否涨停."""
    if len(bars) < 2:
        return False
    prev_close = bars[-2].get("close", 0)
    today_close = bars[-1].get("close", 0)
    if prev_close <= 0:
        return False
    return (today_close - prev_close) / prev_close >= limit_ratio * 0.995  # 允许 0.5% 容差

def is_limit_down(bars: list[dict], limit_ratio: float = 0.10) -> bool:
    """检测当日是否跌停."""
    if len(bars) < 2:
        return False
    prev_close = bars[-2].get("close", 0)
    today_close = bars[-1].get("close", 0)
    if prev_close <= 0:
        return False
    return (prev_close - today_close) / prev_close >= limit_ratio * 0.995
```

**注意**: 创业板 (300/301) 涨跌幅 ±20%，科创板 (688) ±20%，北交所 (920/8/4) ±30%，主板 ±10%，ST ±5%。`limit_ratio` 需要根据股票代码判断。

#### 4.3.4 测试要求

`tests/test_slippage.py`:
```
test_slippage_small_cap_buy          — 小盘买入滑点
test_slippage_large_cap_buy          — 大盘买入滑点
test_slippage_sell                   — 卖出滑点
test_limit_up_buy_not_filled         — 涨停买不进
test_limit_down_sell_not_filled      — 跌停卖不出
test_slippage_volume_adjustment      — 大单量滑点放大
test_chinext_limit_ratio             — 创业板 20% 涨跌幅
test_star_limit_ratio                — 科创板 20% 涨跌幅
test_bse_limit_ratio                 — 北交所 30% 涨跌幅
```

`tests/test_survivorship.py`:
```
test_ipo_not_in_universe_before_listing  — IPO 前不出现在候选
test_delisted_removed_after_date         — 退市后不出现在候选
test_delisted_forced_liquidation         — 退市时持仓被清算
test_active_universe_size_changes        — 活跃股票数随时间变化
```

### 4.4 P&L 影响

| 指标 | 预期影响 | 量级估计 |
|------|----------|----------|
| 总收益 | **下降** | -3% ~ -8% （滑点 + 退市股惩罚 + 涨停买不到） |
| 夏普比率 | **下降** | -0.1 ~ -0.3 |
| 最大回撤 | **微降或持平** | 跌停卖不出的情景会被计入 |
| 交易次数 | **下降** | 涨停候选无法成交，成交率下降 10-20% |
| 胜率 | **微降** | 滑点降低盈利空间 |

**这是正常的、健康的下降。** 之前回测的收益包含了"运气成分"（涨停能买到、跌停能卖掉、退市股不算账）。真实的策略表现就应该比回测差一些。Phase 4 之后的结果才是你真正能期望的实盘表现。

### 4.5 引入的风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 退市股数据无法获取 | **高** | 低估退市影响 | 使用保守估计（-50% 退市结算价）作为下界 |
| 滑点模型参数不准确 | 中 | 滑点估计偏差 | 参数可配置，后期根据实盘回填 |
| 涨停/跌停检测依赖前收盘价 | 低 | 第一个交易日无法判断 | 第一日默认为非涨跌停 |

### 4.6 验收标准

- [ ] 退市股清单覆盖 2024-2026 年所有退市 A 股（至少 30 只以上）
- [ ] IPO 日期覆盖 stock_universe 中所有股票
- [ ] 回测时的 active universe 在每交易日按 IPO 日期和退市日期动态调整
- [ ] 滑点模型已集成到两个回测引擎
- [ ] 涨跌停板检测已集成到两个回测引擎
- [ ] 涨停买入订单标记为 unfilled 而非按涨停价成交
- [ ] 跌停卖出订单标记为 unfilled 而非按跌停价成交
- [ ] 佣金拆分为实际买卖双向费率（买入 0.025%，卖出 0.075%）
- [ ] `tests/test_slippage.py` 9 个测试全部通过
- [ ] `tests/test_survivorship.py` 5 个测试全部通过
- [ ] 所有已有测试不受影响
- [ ] 跑一次完整回测，记录修正后的收益（预期比 Phase 3 结果低 3-8%）

---

## 总结: 三阶段作战时间线

```
现在 (Day 0) ──────────────────────────────────────→ 上线实盘
│                                                        │
│ Phase 2: Risk Architecture (Day 0-1)                   │
│ ├─ pipeline.py AGY fix                                 │
│ ├─ RiskManager offline mode                            │
│ ├─ Snapshot 强化                                       │
│ └─ 测试 → 验收                                         │
│                                                        │
│ Phase 3: Strategy Re-optimization (Day 0-1 并行启动)    │
│ ├─ 佣金拆分 (prerequisite)                              │
│ ├─ Round 1: 200轮 auto_iterate (overnight)             │
│ ├─ Round 2: Walk-forward 验证 (Day 2 morning)          │
│ ├─ Round 3: Ensemble 组合 (Day 2 afternoon)            │
│ └─ 人工审查结果 → 验收                                  │
│                                                        │
│ Phase 4: Data Quality (Day 1-3)                        │
│ ├─ 退市股数据采集                                       │
│ ├─ IPO 日期补充                                         │
│ ├─ 滑点模型实现                                         │
│ ├─ 涨跌停检测                                           │
│ └─ 集成 + 测试 → 验收                                   │
│                                                        │
▼ 上线实盘                                                ▼
```

**指挥官最终判断**: 

这个系统的骨架是对的——逆向了 60 条规则，映射到了 7 个文件，管线清晰。Phase 1A 修掉了 3 个数据泄漏和 1 个 BUG，引擎现在诚实地反映策略表现。

但诚实的引擎告诉你一个残酷的事实: 旧参数在修正引擎上的表现是 -19.08%，最大回撤 41.90%，夏普 -0.24。这说明要么策略 alpha 本身很弱，要么参数需要重新适配。

Phase 3 的 re-optimization 会告诉我们答案。如果 walk-forward 验证也通不过（OOS/IS < 0.6），那就是策略 alpha 真的不够——需要回到 Alpha Research，从 RULE-011 到 RULE-019 重新审视每个因子的有效性。

风控第一，赚钱第二。Phase 2 先做，Phase 3 并行跑，Phase 4 收尾。

**30 年老法师的最后提醒**: 在 A 股，活下来比什么都重要。每一笔交易之前，先问自己: "这笔单子最坏的情况是什么？我能不能承受？" 如果答案是不确定，那就别做。这个原则同样适用于代码——每一行风险相关的代码，都要问: "如果这段代码在最坏的情况下执行，结果是什么？"
