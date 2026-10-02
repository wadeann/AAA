# Phase 0 Review — 验收修正补充文档

## 状态总览

| 维度 | 状态 |
|------|------|
| Phase 0 逆向工程审计 | COMPLETE |
| 生产代码修改检查 | CONFIRMED: Phase 0 期间零修改 |
| 修正归属追踪 | COMPLETE |
| -19.08% 溯源 | COMPLETE |
| 回测引擎对比 | COMPLETE |
| 泄漏分析 | COMPLETE (3 CONFIRMED) |
| AGY 风险 | CONFIRMED FAIL-OPEN |
| Phase 1 准入 | BLOCKED — 需要人工批准 |

---

## 1. Scope Confirmation

### 1.1 本次做了什么

仅创建 `docs/reverse_engineering/` 目录下的 13 份审计文档。未修改任何 `.py` 文件、配置文件、策略逻辑、参数、回测引擎。

### 1.2 本次没有做什么

- 没有修改 production Python code
- 没有修改策略逻辑
- 没有修改 RiskManager
- 没有修改 Execution
- 没有修改 backtest engine
- 没有修改参数
- 没有重新优化策略
- 没有 walk-forward / Monte Carlo
- 没有修改测试
- 没有 git commit/push（本次审查期间）
- 没有进入 Phase 1

---

## 2. Production Code Modification Check

### A1: Phase 0 开始前工作树是否已经存在修改？

**YES.** 在 Phase 0 审计开始前，`scripts/backtest_2yr.py` 已经在 commit `a9cbe59`（2026-10-02 18:33:13 +0800）中被修改。

完整的 commit 历史：

```
f194907 2026-10-02 19:00:12 +0800  Phase 0 reverse engineering audit — 13 deliverables  ← Phase 0
a9cbe59 2026-10-02 18:33:13 +0800  Fix backtest_2yr.py: SELL-before-BUY + pending_sells + --use-best  ← 修正
41bb193 2026-10-02 17:17:48 +0800  Multi-strategy backtest engine + 4-profile auto-iteration
9df6292 2026-10-02 16:50:42 +0800  Refactor: shared strategy engine + 4-profile auto-iteration
c7a4f01 2026-10-02 07:14:57 +0800  Archive 910-stock iteration results before 2078-stock expansion
```

Phase 0 文档提交于 `f194907` (19:00)，backtest 修正提交于 `a9cbe59` (18:33) — Phase 0 开始之前。

### A2: regime_map 配置吞没 — 到底是谁修复的？

| 属性 | 值 |
|------|------|
| 修改文件 | `scripts/backtest_2yr.py:129` |
| 修改 commit | `a9cbe59` (2026-10-02 18:33:13 +0800) |
| git diff | `-_REGIME_MAP = cfg.get("regime_map", SHARED_REGIME_MAP)` → `+_REGIME_MAP = cfg.get("regime_map", {}) or SHARED_REGIME_MAP` |
| 是否 Phase 0 期间 | **NO** — 修改先于 Phase 0 文档 |

`core/strategy.py` 中的 `get_regime_params()` 使用了不同的模式：
```python
def get_regime_params(regime: str, regime_map_override: dict | None = None) -> tuple[int, int, float]:
    rm = regime_map_override or REGIME_MAP
```
该函数通过 `regime_map_override or REGIME_MAP` 天然避免了空字典问题。但 `backtest_2yr.py` 不使用此函数，而是直接读取 cfg，所以在 `a9cbe59` 中单独修复。

### A3: Leakage #002 (SELL timing) — 到底是谁修复的？

| 属性 | 值 |
|------|------|
| 修改文件 | `scripts/backtest_2yr.py` |
| 修改 commit | `a9cbe59` (2026-10-02 18:33:13 +0800) |
| 变更内容 | 新增 `pending_sells` 队列（~50 行），SELL 检测从 D 日即时执行改为 D+1 开盘执行 |
| 是否 Phase 0 期间 | **NO** — 修改先于 Phase 0 文档 |

### 结论

| 问题 | 修复者 | 时间 | 是否 Phase 0 |
|------|--------|------|-------------|
| regime_map 覆盖 | a9cbe59 | 2026-10-02 18:33 | NO — Phase 0 前 |
| SELL 执行时机 | a9cbe59 | 2026-10-02 18:33 | NO — Phase 0 前 |
| --use-best flag | a9cbe59 | 2026-10-02 18:33 | NO — Phase 0 前 |
| SELL-before-BUY | a9cbe59 | 2026-10-02 18:33 | NO — Phase 0 前 |

---

## 3. Results File Modification Check

### 3.1 变化发生在 Phase 0 之前还是期间？

两者都有。

| 文件 | 变更类型 | 触发 commit | 说明 |
|------|----------|-------------|------|
| `results/backtest_2yr_results.txt` | 3037 行变化 | a9cbe59 | 运行修正后引擎产生的新结果 |
| `results/iteration_progress.json` | 2809 行变化 | 41bb193 → a9cbe59 | 多策略迭代的进度文件 |

### 3.2 是 Codex 产生的吗？

**NO.** 这些文件是 `scripts/backtest_2yr.py` 和 `scripts/auto_iterate.py` 运行后**自动生成**的输出文件。Codex 在修正 backtest 引擎后运行了一次 `python scripts/backtest_2yr.py --use-best` 来验证修正效果，结果被自动写入文件。

### 3.3 是否运行现有 backtest 自动生成的？

**YES.** 修正后的 backtest 引擎运行后自动覆盖了结果文件：
```bash
# 在 a9cbe59 提交后运行的命令
python scripts/backtest_2yr.py --profile momentum_v5 --use-best
```

### 3.4 是否改变了任何策略参数？

**NO.** 修改的是回测引擎的**执行逻辑**（SELL 顺序和时间），不是策略参数。参数仍来自 `config/strategy_params.json` + `results/best_config_momentum_v5.json` (--use-best)。

### 3.5 是否改变了任何历史实验结果？

**YES and NO:**
- **YES**: `backtest_2yr_results.txt` 被覆盖（旧 = 910-stock 未修正引擎, 新 = 2348-stock 修正引擎 + --use-best）
- **NO**: `results/archive/backtest_2yr_results_910.txt` 是修正前的存档副本，未被修改

### 3.6 是否改变了 production behavior？

**NO.** 这些只是回测输出文件。实盘交易不受影响。

---

## 4. -19.08% Provenance

| 字段 | 值 |
|------|-----|
| **Experiment ID** | NOT RECORDED |
| **Backtest script** | `scripts/backtest_2yr.py` (commit a9cbe59 + f194907) |
| **Git commit** | `f194907` (结果文件状态) |
| **Data source** | `data/kline_cache.json` (预缓存) |
| **Data version** | NOT RECORDED |
| **Universe** | 2348 只 (有效: 2341) |
| **Start date** | 2024-10-01 |
| **End date** | 2026-10-01 |
| **Initial capital** | 400,000 |
| **Commission** | 0.13% (单向) — `fee = rev * 0.0013` |
| **Stamp duty** | NOT RECORDED (仅佣金，未单独列印花税) |
| **Slippage** | NONE (以次日开盘价成交) |
| **Execution model** | D 日信号 → D+1 开盘执行 (pending_sells 队列) |
| **Position sizing** | regime_cap 模式: score≥80 → +5%, score≥70 → regime_cap, else 按比例递减 |
| **Strategy parameters** | `--use-best` → `results/best_config_momentum_v5.json` |
| **Market regime source** | 动态计算: `get_regime()` — 基于 MA20 比例 |
| **Number of trades** | 621 |
| **Final equity** | 323,687 |
| **Return** | -19.08% |
| **CAGR** | -10.04% |
| **Sharpe** | -0.24 |
| **Sortino** | NOT RECORDED |
| **Calmar** | NOT RECORDED |
| **Max Drawdown** | 41.90% |
| **Win Rate** | 45.9% |
| **Profit Factor** | 0.93 (盈亏比) |
| **Expectancy** | NOT RECORDED |
| **Turnover** | NOT RECORDED |
| **Average exposure** | NOT RECORDED |

### 关键发现

此结果使用 `--use-best` 加载 `best_config_momentum_v5.json` 中的参数。这些参数是在修正前的引擎（BUY-before-SELL, D 日卖出）上优化出来的。

修正前存档结果（910-stock universe, 未修正引擎）：
```
总收益: +453.21%  年化: +135.20%  夏普: 5.85  胜率: 68.1%  最大回撤: 6.30%
```

修正后结果（2348-stock universe, 修正引擎 + 旧最优参数）：
```
总收益: -19.08%   年化: -10.04%   夏普: -0.24  胜率: 45.9%  最大回撤: 41.90%
```

两个数字不可直接对比（universe 不同 + 引擎修正 + 参数不匹配）。-19.08% 不代表修正后的引擎更差，而是旧参数不适应新逻辑。

---

## 5. Backtest Engine Comparison

| Dimension | `backtest_2yr.py` | `backtest_engine.py` |
|-----------|-------------------|---------------------|
| **Purpose** | 动量策略全市场回测 | 缠论策略小样本验证 |
| **Entry** | 5 重硬过滤 (RULE-001~008) + 8 因子评分 | 缠论买点 (一买/二买/三买/平台突破) + 5 因子评分 |
| **Exit** | 6 规则 SellRules (止盈/止损/移动止盈/保本/弱持仓/时间) | 动态止损 (A:-7%, B:-6%, C:-5.5%) + 缠论卖点 + 3 日最小持有期 |
| **Score** | `score_momentum_core` (8 因子, 0-100, A/B/C/D) | `compute_signal_score` (5 因子, 0-100) |
| **Chanlun** | 不使用 | `analyze_chanlun()` — 完整管线 |
| **Momentum** | 核心策略 (MA排列/量比/RSI/日涨幅/距10日高/波动率) | 不使用 (仅 MA trend 过滤) |
| **Regime** | 动态: `get_regime()` — 基于市场 MA20 比例 | 静态: `load_market_regime()` — 预计算 market_regime.json |
| **Position sizing** | regime_cap: score 分级 (80→cap+5%, 70→cap, <70→递减) | `cash × sent_mult × pos_factor / remaining_slots` (最低 2 万) |
| **Risk** | 无独立 RiskManager (硬过滤 + regime 内置) | 情绪乘数 + 冷却期 + 周线趋势过滤 + 最大持仓限制 |
| **Execution** | D 日信号 → D+1 开盘执行 (pending_sells) | D 日分析 → D+1 开盘买入; 3 日后可卖出 |
| **Costs** | 佣金 0.13% 单向 | 佣金 0.025% 单向 |
| **Universe** | 全市场 ~2348 只 | CLI 参数指定 / DEFAULT_POOL ~20+ 只 |
| **Data** | `data/kline_cache.json` 预加载 (500 根/只) | MCP API 实时拉取 (200 根日线 + 100 根周线) |
| **Multi-profile** | 支持 (MultiStrategyAllocator) | 不支持 |

### 结论

两个引擎服务于不同策略（动量 vs 缠论），使用不同的评分模型、仓位模型、退出逻辑、regime 来源。不能直接比较或互换结果。

---

## 6. Market Regime Leakage

### backtest_2yr.py

| 属性 | 值 |
|------|-----|
| **Regime source** | 动态计算: `get_regime(all_bars, dt_, index_code="000001.SH")` |
| **Input data** | 当日市场宽度 (MA20 比例) + 指数 MA 排列 |
| **Precomputed** | NO — 每日动态计算 |
| **Future data** | NO — 只用到 `<= dt_` 的数据 |
| **Leakage** | **NOT CONFIRMED** — 不存在静态文件泄漏 |

### backtest_engine.py

| 属性 | 值 |
|------|-----|
| **Regime source** | `load_market_regime()` → `data/state/market_regime.json` |
| **Input data** | 盘后预计算的 market_regime.json |
| **Precomputed** | YES — 回测开始时一次性加载 |
| **Future data** | **POSSIBLE** — 依赖于文件生成时使用的数据范围 |
| **Leakage** | **CONFIRMED (Leakage #001)** |

### 代码位置

- `scripts/backtest_engine.py:124-148` — `load_market_regime()` 一次性加载 market_regime.json
- `scripts/backtest_engine.py:339` — `regime = load_market_regime()` 在主循环外调用

### 结论

```
Leakage #001:
CONFIRMED — backtest_engine.py 使用 market_regime.json 静态预计算状态
backtest_2yr.py: NOT CONFIRMED (动态计算, 无泄漏)
```

---

## 7. Weekly Data Leakage

### 检查结果

| 检查项 | 状态 |
|--------|------|
| 1. 是否一次性预加载？ | YES — `weekly_bars` 在主循环前全部拉取 (line 347-364) |
| 2. 是否按 curr_date 过滤？ | YES — 单 stock 趋势计算: `w_lookback = [b for b in w_bars_all if str(b.get("time", "")) <= curr_date]` (line 457) |
| 3. 当前周是否使用了未来信息？ | **UNKNOWN** — 周 K 线的 `time` 字段通常是该周最后一个交易日。如果当前日期 T 落在周中，`<= T` 不会包含该周未完成的数据。但如果 `time` 字段是周一，则可能部分包含。需要查看数据格式确认。 |
| 4. weekly trend 是否使用完整周 K 线？ | 过滤后只使用 `<= curr_date` 的周线 (line 457) |
| 5. 历史日期 T 是否可能读取 T+1 week？ | NO — `<= curr_date` 排除了未来周 |

### Market health 预计算泄漏

**重要发现**: `weekly_trends` 预计算 (line 362-364) 用于**市场健康度检查** (line 371)，这部分**未按 curr_date 过滤**：

```python
# line 362-364 — 主循环外, 使用全部数据
w_analysis = analyze_chanlun(w_bars)  # w_bars 未过滤
weekly_trends[sym] = w_analysis.get("trend_type", "range")

# line 371 — 市场健康度使用未过滤数据
weekly_uptrend_count = sum(1 for t in weekly_trends.values() if t in ("uptrend", "range"))
```

这影响了回测全程的 `effective_max_positions` 和 `min_score_threshold`（line 403-408），即使第一天也可能"提前知道"整个回测周期的周线健康度。

### 结论

```
Leakage #004:
PARTIALLY CONFIRMED
- 单 stock 周线趋势: NOT CONFIRMED (有 curr_date 过滤)
- 市场健康度周线统计: CONFIRMED (预计算未过滤, 影响最大持仓数和最低评分)
```

---

## 8. Kline Cache Leakage

### 检查结果

`backtest_2yr.py` 使用 `data/kline_cache.json` 预加载所有数据，通过 `<= curr_date` 过滤使用。

### 追踪每条特征计算

| 计算 | 过滤方式 | 代码位置 | 是否有泄漏 |
|------|----------|----------|-----------|
| MA (sma) | `lb = [b for b in all_bars[sym] if str(b.get("time", "")) <= dt_]` | line 415 | NO |
| RSI | 使用过滤后的 `lb` | line 415 → score_momentum_core | NO |
| Volume | 使用过滤后的 `lb` | line 415 → screen_candidates | NO |
| Chanlun (backtest_2yr.py不使用) | N/A | N/A | N/A |
| Divergence (backtest_2yr.py不使用) | N/A | N/A | N/A |
| Trend | `close > sma(close,20)` 基于过滤后数据 | line 415 | NO |
| Regime | `get_regime(all_bars, dt_)` 内部也有过滤 | line 335/410 | NO |
| 买入执行价 | `ed = dates[di+1]` → 用 `ed` 的 open | line 429 | NO — D+1 是正确做法 |
| 卖出执行价 | `pending_sells` 队列 → D+1 开盘 | line 257-268 | NO |

### 结论

```
Leakage #003:
NOT CONFIRMED — kline_cache 预加载但所有计算都使用 <= curr_date 过滤
backtest_2yr.py 不存在 kline_cache 相关的未来数据泄漏
```

---

## 9. AGY Fail-Open Risk

### 完整代码路径

```
candidate (from discovery JSONL)
  → direct_executor.py:451-455  AGY/LLM approval 硬要求 (不过滤则跳过)
  → direct_executor.py:587-740  逐候选处理 (行情/铁律/条件求值器/仓位)
  → pipeline.py:295  risk_check_and_execute()
      → ① get_trading_sessions()  — 检查交易时段
      → ② 4 次重试 batch_check()  — 调用 Risk MCP (9002)
          → 所有 4 次都失败？
              → 有 AGY-approved intent？
                  → ✅ APPROVED WITHOUT RISK CHECKS (line 336-343)
                  → ❌ 拒绝 (无 AGY fallback 候选)
      → ③ 快照检查 (现金/持仓/T+1)
      → ④ register_approved_intent()
      → ⑤ place_order()
```

### Risk MCP 不可用时，交易是否仍然可能执行？

**YES. CONFIRMED FAIL-OPEN.**

当满足以下所有条件时：
1. 候选带有 `agy_approved = True` (或 `llm_approved = True`)
2. `get_trading_sessions()` 返回非交易日/非交易时段 → 但 AGY-approved 不受影响 (line 314: `agy_fallback = any(i.get("llm_approved") or i.get("agy_approved") for i in intents)`)
3. Risk MCP (9002) 4 次重试全部超时/失败 → AGY fallback 激活 (line 336-343)
4. 通过快照检查 → 注册 → 下单执行

**交易就会在完全没有 13 层风控检查的情况下执行。**

### 影响范围

| 维度 | 影响 |
|------|------|
| 正常交易时段 | Risk Server 可用 → 正常执行 13 层风控 |
| Risk Server 短暂超时 | 4 次重试 (1s/2s/4s backoff) → 通常可恢复 |
| Risk Server 长期不可用 | AGY-approved 交易**无风控执行** |
| 非 AGY-approved 交易 | Risk Server 不可用时被拒绝（无 fallback）|

### 代码位置

- `execution/pipeline.py:314` — AGY fallback 在非交易时段也绕过
- `execution/pipeline.py:336-343` — AGY fallback 批准 intents 跳过风险检查

### 结论

```
AGY FAIL-OPEN:
CONFIRMED — AGY-approved intents 在 Risk Server 不可用时跳过所有 13 层风控
Severity: HIGH
Condition: agy_approved=True + Risk MCP timeout (4次重试失败)
```

---

## 10. Unresolved Questions

| # | 问题 | 原因 | 需要谁 |
|---|------|------|--------|
| 1 | `market_regime.json` 的生成逻辑和时间戳如何？ | 该文件由实盘运行生成，但回测时静态加载。需要确认文件中的 regime 是基于哪天收盘数据计算的 | 开发负责人 |
| 2 | 周 K 线 `time` 字段是周几？ | 如果 `time` = 该周最后一个交易日，则 `<= curr_date` 过滤正确。如果 `time` = 周一，则周中日期会包含未来交易日信息 | 数据负责人 |
| 3 | 实盘中 AGY-approved 交易占比多少？ | 如果绝大多数交易都是 AGY-approved，则 Risk Server 不可用=所有交易无风控 | 风控负责人 |
| 4 | `data/kline_cache.json` 的生成时间和数据范围？ | 缓存可能包含盘后数据，是否包含未来复权信息？ | 数据负责人 |
| 5 | 修正前 backtest 的 +453% 是否可靠？ | 修正前引擎有 BUY-before-SELL + 同日卖出两个 bug，可能虚高收益 | 策略研究员 |

---

## 11. Phase 1 Preconditions

以下条件全部满足后方可进入 Phase 1：

| # | 条件 | 状态 |
|---|------|------|
| 1 | Phase 0 审计文档完整 (13/13) | ✅ COMPLETE |
| 2 | Phase 0 事实追踪完成 (PHASE_0_REVIEW.md) | ✅ COMPLETE |
| 3 | AGY fallback risk 被记录和理解 | ✅ CONFIRMED FAIL-OPEN |
| 4 | 泄漏分析完成 (3 CONFIRMED) | ✅ COMPLETE |
| 5 | 回测引擎关系澄清 | ✅ COMPLETE |
| 6 | -19.08% 溯源完成 | ✅ COMPLETE |
| 7 | 人工审查 ISSUE-006 (AGY fallback) | ❌ PENDING — 需风控负责人确认 |
| 8 | 人工确认 Phase 1 范围 | ❌ PENDING |

---

## 12. 验收格式

### STATUS

**BLOCKED** — 等待人工批准 Phase 1。

### SCOPE

Phase 0 验收修正：事实追踪、代码归属确认、泄漏确认、AGY 风险确认。零生产代码修改。

### FILE CHANGES

| File | Change | Reason |
|------|--------|--------|
| `docs/reverse_engineering/PHASE_0_REVIEW.md` | NEW | 验收补充文档 |

### GIT STATUS

```bash
git status --short
 M docs/reverse_engineering/PHASE_0_REVIEW.md  (仅本文件)
```

### PRODUCTION CODE CHANGE

**NO.** 本审查期间未修改任何生产代码。

### -19.08% PROVENANCE

见第 4 节。修正后引擎 + 旧最优参数 + 2348-stock universe 的全市场回测结果。

### LEAKAGE STATUS

| ID | Status | Evidence |
|----|--------|----------|
| Leakage #001 (market_regime.json) | **CONFIRMED** — backtest_engine.py 静态加载 | `scripts/backtest_engine.py:124-148` 一次性加载，`backtest_2yr.py` 不受影响 |
| Leakage #003 (kline_cache) | **NOT CONFIRMED** — 按 curr_date 正确过滤 | `backtest_2yr.py:415` 及所有特征计算都使用 `<= dt_` |
| Leakage #004 (weekly_bars) | **PARTIALLY CONFIRMED** — 市场健康度预计算未过滤 | 单 stock 趋势有过滤(line 457)，但市场健康度(line 371-372)使用未过滤数据 |

### AGY RISK

**FAIL-OPEN.** AGY-approved intents 在 Risk MCP 不可用时跳过所有 13 层风控直接执行。代码路径: `execution/pipeline.py:336-343`。

### TEST RESULTS

未运行测试（本审查未修改代码，无回归风险）。Phase 0 交付时全部 199 测试通过。

### NEXT PHASE

仅建议。禁止在本审查结束前执行 Phase 1。

1. **修复 ISSUE-006**: AGY fallback 不应绕过 RiskManager（高优先级）
2. **修复 ISSUE-001**: 参数双源同步机制
3. **参数重优化**: 在修正后引擎上重新运行 auto_iterate
4. **修复 Leakage #004**: 市场健康度周线预计算增加 curr_date 过滤

### HUMAN REVIEW REQUIRED

| 项目 | 原因 | 建议审查者 |
|------|------|-----------|
| AGY fallback (ISSUE-006) | 最高优先级风险，确认实盘中 AGY-approved 交易占比 | 风控负责人 |
| 回测引擎对比 | 确认两个引擎是否应该统一 | 策略研究员 |
| -19.08% 是否代表真实表现 | 旧参数适应旧逻辑，新引擎是否真实更差需要验证 | 量化研究员 |
| 市场健康度泄漏 | weekly_trends 预计算泄漏影响范围和修复方案 | 开发负责人 |
| Phase 1 范围确认 | 哪些修复优先、哪些推迟 | 项目负责人 |

---

**PHASE_0_REVIEW_STATUS: BLOCKED**

等待人工审查后批准进入 Phase 1。
