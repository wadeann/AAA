---
name: antigravity-audit
description: "Antigravity (AGY) 独立审计、进化追踪与多轮代码修改工作流"
version: 1.7.0
author: Antigravity & Hermes
metadata:
  hermes:
    tags: [audit, antigravity, agy, code-review, self-evolution, troubleshooting, catch-dragon, 擒龙, trading-evolution]
---

# Antigravity (AGY) 独立审计与多轮代码修改工作流

⚠️ 重要参考文件：
- `references/agy-strategy-architecture-review.md`
- `references/ignition-v1-v2-audit-2026-09-09.md`
- `references/agy-prompt-hardening-haohua-case.md`
- `references/r34-agy-full-execution.md`
- `references/subagent-audit-17-module-pattern.md` — 2026-09-14: 子agent bypass AGY审计17模块，31+P0/P1 Bug修复的模式参数与性能数据
- `references/ignition-v1-score-unit-bug-pattern-2026-09-14.md` — Ignition-V1审计: cap_mult=15单位换算10倍虚高 + industry字段兜底 + 距离分负值显式处理模式
- `references/agy-post-edit-deep-audit-cases.md`
- `references/agy-multi-round-deep-dive-patterns.md`
- `references/rust-security-audit-patterns.md`
- `references/python-fastmcp-audit-patterns.md`
- `references/agy-audit-mcp-self-verify-pattern.md`
- `references/analyze-stock-script-bugfix.md` — analyze_stock_with_antigravity.py Bug修复记录(2026-09-11)
- `references/score-ceiling-bug-pattern.md` — 评分天花板vs门槛死区检测模式，含午间评分50<60典型案例
- `references/daily-decision-verdict-audit.md` — 逐日盘后决策裁决审计模式：收集多源系统输出快照→提交AGY裁决→输出Judgment/Score/Missed Opportunities。区别于代码审计，审计对象是当日系统交易判断的正确性而非代码逻辑。
- `references/agy-audit-suggestion-to-implementation-2026-09-15.md` — AGY审计建议→Hermes自主实现模式案例。区别于AGY直接写代码的"让AGY改"模式，描述"让AGY改进"场景下Hermes读代码→设计→实现→验证的六步流程。**包含5个关键pitfalls：函数签名变更扫描、retreat_days缓存计算、熔断后滤网连锁放宽、下游铁律子类型感知、字段None安全。**
- `references/agy-self-audit-timeout-workflow-2026-09-15.md` — AGY持续超时的三阶段自审计替代方案(2026-09-15)。包含6个发现Bug的完整修复记录、6个边缘情况测试结果、4个扫描器一致性验证、broken_seal_rate问财fallback修复过程。
- `references/r37-verify-before-apply-lesson.md` — R37教训: AGY输出代码含隐藏bug，Hermes必须审读验证再落地
- `references/agy-audit-r46-r47-market-regime-7bugs.md` — (2026-09-15) AGY审计7个P0/P1 bug: retreat_days日内无限递增、panic_ebb遗漏拦截、exhaustion_ebb跳过Gate 4、非退潮retreat_days泄漏、问财fallback增强、amount ValueError安全、TDX迷你仓展示修复。
- `references/evidence-contract-r95-acceptance-pattern.md` — 跨大盘/天梯/板块/个股的证据契约修复与95分验收模式：缺失值语义、缓存新鲜度、生产状态测试隔离、真实脚本复跑、AGY原子签署。
- `references/observation-to-execution-pipeline-6bugs.md` — (2026-09-23) 观察型脚本→实战执行管道改造的6个复现性P0/P1 Bug：双执行、时间戳ID穿透去重、硬编码死仓、字段缺失kill-all、量纲round归零、非原子并发写。含排查清单。
- `references/r38-push-strategy-audit-2026-09-25.md` — (2026-09-25) AGY审计盘中推送策略修改：sell_only_mode硬编码覆写状态机+噪音推送+缓存陈旧阻断。Score 70/100，3Recommendation全部修复。新增Pitfall 22/23。
- `references/rectification-plan-acceptance.md` — 跨仓库整改计划的四层验收法：计划条目→实现→专项测试→真实链路/全量回归；含TDX `Rows/Data/Close`契约、API Key冷却、返回值错误重试和生产状态污染测试隔离。

## 0. 进化追踪与治理规则

### 0.1 当前进化状态
- AGY进化已完成: 36轮 (完成至R36)
- 剩余轮次: 64轮
- 月度收益目标: 100%
- 最新里程碑: R37 — 2026-09-14 已发现教训: AGY完整代码可能含隐藏bug(UnboundLocalError/dict覆盖/天花板死区)，Hermes必须审读验证而非盲贴。新增pitfall 16"AGY输出代码必须有Hermes验证层"。
- R38 (2026-09-16) — AGY CLI成功返回审计结果! 用git diff内嵌+原子级问题(1400字,3m timeout)成功审计R6-R7修改,发现3个call_auction_scanner Bug, 3轮修复后签署验收。证明AGY CLI在合适prompt下发回正常响应,不再是沉默。

### 0.2 Governance Rules

1. 每轮修改必须AGY审核 + GitHub提交
2. 容灾数据必须核实真实涨幅
3. AGY拦截硬执行: agy_approved=False → 全局否决
4. 多管道交叉污染零容忍
5. cooldown/blacklist必须真实生效

### 0.3 核心设计缺陷

1. 盘中天梯不读增强天梯JSON，只用资金流入排序导致最高板消失
2. 天梯评分公式成交额权重过高，大盘趋势股冒充连板标的
3. 买入候选无streak>=3铁律过滤
4. 持仓止盈线静态成本锚定，高浮盈时锁利形同虚设
5. catalyst_type命名分裂
6. 情绪周期被cooldown对冲
7. **根因链条发现模式**：下游门禁层拦截了高板买入，但上游荐股引擎仍在硬编码筛选streak>=3并生成买入建议——门禁阻断的数量为0不是因为候选质量好，而是因为门禁已被上游绕开。修复时必须沿**生成链追到最上游源头**，不只是加固门禁。
8. **字段名不统一穿透**：各脚本用不同字段表示同一概念（streak vs real_streak vs board_height），门禁只读其中一个时，其他字段传入的候选直接穿透。

### 0.4 R28复盘教训

- AGY拦截11只涨停候选但绕过执行 → R29: direct_executor加硬规则
- cooldown阶段仍执行19笔买入 → R30: is_trade_ready情绪阻断
- 持仓17只分散 → R32: 全局仓位上限5只
- 虚假涨停数据 → R31: 容灾必须核实真实涨幅

### 0.5 三层擒龙闭环架构

猎杀圈: 09:25竞价→09:30-14:50龙头监控→LLM二审→direct_executor
保命圈: 炸板T+1感知→尾盘14:15/30/45纯防守
进化圈: 15:15资金流→15:25复盘→15:45次日计划→15:55策略进化

### 0.6 Pitfalls

1. 双信号不是冲突，T+1方向冲突只防同一天
2. 卖出候选被is_trade_ready误杀需direction分支
3. direct_executor超时分批处理
4. 竞价候选name空需运行时补全
5. 容灾兜底必须核实涨幅
6. AGY拦截后被绕过需position_guard重叠检测
7. 天梯推送必须展示全市场最高板（即使资金流入排名靠后），第一行永远展示最高空间龙
8. 候选标的股价>50元时判定为大盘机构票，不适合游资连板天梯，必须过滤
10. AGY写代码输出完整文件时，仅用patch定向替换新加部分，不无脑覆盖全文件
11. **根因链条追踪**：下游门禁层发现的问题，必须向上游生成层追溯相同逻辑的源头（例：铁律熔断拦截streak>=3无效→追到premarket_plan_compiler硬编码streak>=3生成买入→"门禁拦截数=0"不是好事，是上游根本没生合规候选）
12. **复审P0闭环签署模式**：AGY首轮审计→Hermes落地修改→AGY复审必须检查：修改本身是否正确 + 是否有新的P0级隐患被发现 + 直到AGY说"签署终结"。复审可能发现新的P0（如字段兼容漏洞），这属于正常，需要二轮修改+二轮复审
13. **字段多源兼容**：所有字段读取必须考虑系统中各脚本字段命名不统一的问题，用 `candidate.get("A") or candidate.get("B") or candidate.get("C")` 链式兼容
14. **评分天花板vs及格门槛死区检测**：审计时必须检查评分公式的理论最高分是否 ≥ 及格门槛。例：`score = min(30, inflow*3) + (20 if chg>0 else 5)` 理论最高50分但门禁写 `>=60`——这是数学上永远不及格的死区bug。排查方法：对每个 `if X >= THRESHOLD` 门禁，反算上游评分的理论最大值并验证 ≥ THRESHOLD。
15. **AGY自己改代码→复审两阶段模式**：用户说"让AGY自己去修改"时，第一阶段AGY输出完整代码文件；第二阶段重新请求AGY复审。复审可能发现新的P0（字段兼容、上游逻辑分裂等），需要多轮循环直到AGY说"签署终结"——非Hermes自行判断。
18. **Hermes自审计不等于AGY审计，不能替代AGY闭环（2026-09-16新增）**：
    - Hermes可以做文件安全检查（tmp+replace扫描）、py_compile验证、全量覆盖率分析——这些是**工程前置工作**，不是AGY审计。
    - **用户说的是"让AGY审核"，意味AGY CLI必须实际被调用并返回结果**。Hermes自行完成了R1-R7 50+模块的修改后，用户发现AGY根本没有参与，批评为"我给你说多少轮，你走完了吗"。
    - 正确时序：Hermes做工程摸底（发现什么文件有写操作问题、什么是纯格式修改）→ 把**有实际逻辑风险的修改**浓缩到1-3个原子问题提交AGY → AGY审计 → 修复 → AGY复审签署 → 才算走完一轮。
    - 纯tmp+replace的批量文件安全修复不需要AGY审计（太琐碎，AGY会浪费时间确认原子写入正确性），但每个**逻辑修改**必须AGY过。
    - **快速判断标准**：
      - 只有 `.write_text` → `.tmp.replace()` 的改写（无逻辑变化）→ 跳过AGY
      - 有 `if`, `for`, `try/except`, 变量赋值变化, 单位换算, 字段读取 → 必须AGY审计

19. **学习闭环审计必须穿透“统计层→配置层→物理执行层”（2026-09-19新增）**：
    - 审计`evolution_audit`产生P0/action item不足以证明风控生效；必须继续检查`strategy_params.json`、`breaker_state.json`以及执行前门禁是否读取并阻断。
    - 对收益率/MAE类字段，AGY必须核对**符号、单位、极值选择**：MAE通常为负值，重伤判断应是`<= -阈值`；小数制`-0.1181`与百分制`-11.81`必须统一；worst trade不能只按收盘PnL排序，要考虑盘中MAE。
    - 检查样本边界：影子样本可用于研究统计，但不得驱动物理实盘熔断；SELL退出质量不得污染BUY开仓策略。
    - 检查冷却方向：cooldown/blacklist应阻断BUY新增暴露，但SELL止损止盈必须有逃生通道。
    - 检查历史去重是否支持schema升级：已有candidate_id若缺MAE，必须原位回填，不能因“已存在”永久跳过。
    - 测试审计必须区分unit fixture与live state：生产策略真实熔断导致旧“BUY应放行”测试失败，不得误判为代码回归，也不得清空线上状态迎合测试。
    - 推荐证据：真实outcome行→修复前状态→backfill后history→breaker状态→SELL豁免→隔离单测与live integration各自结果。

21. **观察型脚本→实战执行管道改造的6类P0/P1陷阱（2026-09-23新增）**：
    - 当把仅推送看板的脚本升级为"识别买点→写入候选池→风控→真实下单"的执行引擎时，必须预扫以下6类Bug（详见 `references/observation-to-execution-pipeline-6bugs.md`）：
      - **P0 双执行**：脚本自调 `risk_check_and_execute` + 常驻执行器扫同一JSONL = 重复下单。报单权必须收敛给单一执行器。
      - **P0 穿透去重**：候选ID用时间戳（非业务主键）→ 同标的反复识别写入不同ID → 穿透去重。ID必须为 `{symbol}-{date}-{direction}`。
      - **P0 死仓**：quantity 硬编码100/未拉账户快照推导 → 执行器只校验不重算 → 100股消耗持仓名额。写候选前必须拉 `get_balance` 按仓位比例算量。
      - **P1 字段缺失kill-all**：外部字段 `X.get("k", 0)` 缺失时默认0 → `if X > 0: keep else: filter` 误杀全部。必须 Fail-Open：字段缺失时放行，数据确认净流出才拦截。
      - **P1 量纲round归零**：`round(value, 2)` 前值恒 < 0.005 → round后 = 0.00。排查：反算 `amount_yi = cur_p/10000` 对10元股=0.001，万→亿=÷1e4不是÷1e8。
      - **P1 并发非原子写**：`.write_text` 直接覆盖 → 多进程读到0字节。必须 `.tmp` + `os.replace`。
    - Contract tests 验证的是函数级逻辑，不能覆盖全部格式化与展示分支。
    - 缺失值从 `0.0` 修成 `None` 后，下游展示中常残留 `flow > 0`、`abs(flow)`、格式化 `:.1f` 等崩溃点。
    - 完整验收必须实际执行打法卡、盘中天梯、复盘等代表性脚本，并检查输出来源、缺失值文字、持仓失败语义与具名标的是否真实。
    - 单测受线上熔断污染时，不得清空生产状态；应在单测中 monkeypatch 健康依赖，同时保留独立集成测试验证生产熔断。

22. **静态配置覆写状态机反模式（2026-09-25新增）**：
    - `strategy_params.json` 中的 `sell_only_mode` 字段曾在顶层和 `global_guards` 两处同时硬编码为 `true`，完全绕过了 `market_regime.json` 状态机的动态升降级机制。
    - 同理，多个策略的 `cooldown_until` 被手动批量改为 `2026-10-01`（延长5天），绕过了 evolution audit 引擎按真实表现逐策略评估的能力。
    - **修复原则**：sell_only_mode 只应由 market_regime 状态机驱动，strategy_params 只保留 global_guards.sell_only_mode 作为兜底默认值（false）。cooldown 日期由 evolution audit 逐策略计算，不得手工批量修改。
    - **审计检查点**：`grep -n '"sell_only_mode"' strategy_params.json` 确认只出现在 global_guards 中一次且值为 false；`grep -rn '"cooldown_until"' strategy_params.json` 确认所有日期各不相同（非批量粘贴）。

23. **市场状态缓存陈旧阻断合规单（2026-09-25新增）**：
    - `market_regime_check.py` 的 iron_rule_gate 会在 `data_fresh: false` 时返回全面禁止开仓（"市场状态缓存陈旧或非实时"）。
    - 根因：`market_regime.py` 下午刷新后到次日09:25之间 >14小时无刷新，TTL仅900秒。`source_date` 仍是昨日，`data_fresh` 验证失败。
    - **修复**：在 `morning_master_orchestrator.py` 的 Phase 0.75（Phase 0.5策略参数初始化后、Phase 0.8调仓前）调用 `market_regime.py` 刷新，确保 `data_fresh=True` 在09:25扫描和09:30 direct_executor 执行前。
    - **注意**：market_regime cron job 只在09:05/13:05/15:05运行，如果09:05前 orchestrator 已启动，仍需显式刷新。
    - **验证方法**：检查 `market_regime.json` 的 `updated_at` 是否在今日09:25之后、`data_fresh` 是否为 true。

17. **exhaustion_ebb不能提前return绕过Gate 4（2026-09-15新增）**：
    - `iron_rule_gate` 中对 `exhaustion_ebb` 做首板+低吸校验后**不能直接return True**，必须继续流向 Gate 4（垃圾时间门禁 10:00-14:30）
    - 之前错误设计成 `if exhaustion_ebb: return True` → 垃圾时间的迷你仓买入不受限制
    - 正确模式：做首板校验 + 追高限制，然后不return，让代码自然下跌到 Gate 4
    - 同理，`panic_ebb` 也必须被显式处理（绝对防守，禁止一切开仓），不能fall through到通用退潮分支。

    ```python
    # CORRECT pattern for iron_rule_gate
    if ebb_subtype == "panic_ebb":
        return False, "禁止一切开仓"
    if ebb_subtype == "exhaustion_ebb":
        if streak > 1: return False, "仅允许首板"
        if is_chasing: return False, "禁止追高"
        # 不return！继续走Gate 4
    elif not is_sector_leader:
        return False, "初退潮禁跟风"
    # ... 后续 Gate 4 垃圾时间门禁
    ```
    - **审读修改逻辑**而非机械粘贴：检查变量是否在所有条件分支中被定义、dict update是否被for循环覆盖导致丢失数据、评分理论最大值是否≥门禁阈值
    - **运行语法检查**：`python3 -c "compile(open('file.py').read(), 'file.py', 'exec')"` 或 `python3 -m py_compile file.py`
    - **运行功能测试**：创建最小化测试用例验证修改的逻辑分支是否正确
    - **用户发现代码坏了时的修复流程**：先git diff看变更→确认是否Hermes应用时引入错误→回到AGY的原始输出逐行分析→用patch定向替换→测试验证→用户确认后再继续

## 故障排查表（新增）

- 用户要求AGY审计、审查、调用
- 系统出现重大交易逻辑缺陷
- 策略代码重构后需要独立验证
- AGY二进制启动后无任何输出（进程running但output_preview为空），所有prompt类型（短/长/简单/结构化）均超时无声

## 2c. 盘中画图与代码定向修改铁律（2026-09-14新增）

### 审计中发现数据类Bug的定向修复模式（无需AGY写代码）

当审计发现以下模式的问题时，Hermes直接修复而非等待AGY：

1. **单位换算Bug（~10x偏差）**：当MCP返回数值与代码预期单位不一致时（如问财返回亿但代码当元处理、amt已是元但cap_mult放大10倍），直接修正乘数因子。例：`cap_mult=15.0→1.5`

2. **字段降级兜底链**：当MCP不返回预期字段时（如wencai不返回"所属同花顺行业"），用 `field_A or field_B or field_C` 三级兜底线。三层兜底后仍空才判定为系统级缺失。

3. **条件分支完整性**：当逻辑条件如 `if dist <= X` 未覆盖所有数学可能（如负值dist未被显式处理），补充分支以避免隐式通过。例：新增 `if dist < 0: score_dist = 20 # 突破前高创新高`

#### Iron rule gate 中 exhaustion_ebb 的正确处理（撤回旧模式）

**～2026-09-10旧模式（已撤回）**: `if ebb_subtype == "exhaustion_ebb": return True, "PASS"` — 绕过所有后续门禁
**2026-09-15新模式**: exhaustion_ebb 做首板+追高限制后不return，继续走 Gate 4 垃圾时间门禁 — 详见 Pitfall 17

**为什么撤回**: 旧模式下exhaustion_ebb期间的迷你仓买入在 10:00-14:30 垃圾时间不被拦截，实际等于全天任意时刻都能买，破坏了盘中纪律。退潮衰竭冰点只能放松筹码和主线门禁，不能放松时间门禁。

#### 评分天花板审计快速检查表

| 步骤 | 检查项 | 如何发现 |
|------|--------|---------|
| 1 | 理论总分 MAX < 门禁阈值 THRESHOLD？ | 逐项分录评分维度→求和→比较门禁 |
| 2 | MCP返回单位与代码预期一致？ | cross-ref 问财值 vs 代码除/乘数 |
| 3 | score_pct > max_possible 是bug吗？ | N/A — 可能是百分比计算无误但字段名看起来奇怪(97.5% of 80 = 正确) |
| 4 | 所有字段有兜底链？ | 查每个 d.get() 的第3个参数或用 or 连接 |
| 5 | 条件语句覆盖所有数学可能？ | 列出条件的全部可能值域，检查分支是否穷尽 |

## 2b. 铁律：AGY可以写代码（有限制条件）

1. 涉及scripts/的策略/风控/执行代码修改**优先**通过AGY
2. AGY原始报告零转述
3. 每次调用AGY后展示commit证据
4. 用户问股=拉MCP数据直接报结论

当用户明确说"让AGY自己去修改代码"或类似指令时：

1. **AGY输出完整代码文件**：prompt中直接写"直接输出完整代码，不要只描述"，AGY会输出带```python包裹的完整文件内容
2. **Hermes只做三件事**：
   - 应用代码修改到目标文件（用patch定向替换，不用完整覆盖）
   - 运行测试验证（python3 -c "from ... import ..."语法检查 + 功能测试用例）
   - git commit 提交修改
3. **AGY会输出整个文件**而非仅diff。Hermes提取实际修改的部分用patch插入，不是无脑覆盖整个文件（AGY输出有时包含不必要的格式变更或注释调整）

## 2d. 多报告联合审计模式

当审计对象是多个自动化推送报告（盘前预案、盘中天梯、涨停归档、收盘复盘等）时：

1. 收集所有报告的原始输出内容
2. 在prompt中按编号列出每个报告的内容摘要
3. 每个报告附合理性评级✅/⚠️/❌
4. 对❌报告给出P0/P1级别根因分析
5. 逐份给出具体代码修改建议
6. 输出标准化整改清单（P0立即整改/P1 3日内优化）

## 2e. 逐日盘后决策裁决审计模式（2026-09-15新增）

当用户要求"AGY审核今日操作/判断是否正确"时，这不是代码审计，而是**决策裁决审计**。

### 流程
1. **收集证据** — 从cron/output/收集盘前预案、天梯、扫描器、收盘复盘报文；运行system_health_check
2. **构建审计Prompt** — 按 `references/daily-decision-verdict-audit.md` 的模板，填入所有系统证据
3. **提交AGY裁决** — 用 `ask_antigravity(prompt, timeout=360)` 或 `terminal(bg, notify, "agy -p ... --print-timeout 6m")`
4. **原样展示裁决结果** — Judgment/Reasoning/Score/Missed Opportunities完整呈现给用户

### 关键差异提醒
- 不需要读代码、找Bug、写patch
- 审计对象是**当日交易判断**而非策略代码
- 输出格式是裁决报告（含Score打分）而非Bug修复清单
- 当AGY返回98/100等高置信度打分时，说明系统决策正确，无需进一步修改

### 2e.1 决策裁决审计 vs 代码审计的区分规则（2026-09-15新增）

**用户问"今天的买入机会判断是否正确"→ 走决策裁决审计**
**用户问"代码逻辑有问题"→ 走代码审计**

两者的区别：
- 决策裁决审计：收集全部系统输出（盘前预案、天梯、扫描器、收盘复盘）→ 提交AGY评估今日信号质量 → 输出 Judgment/Score/Missed Opportunities。不需要读代码、找Bug、写patch。
- 代码审计：读文件 → 找Bug → patch修 → 验证 → commit。需要完整代码理解。

**当用户说"让AGY审核"但指向的是系统交易信号而非代码质量时：**
1. 先拉取系统真实输出（print_playbook、intraday_hot_sector_sniper、market_regime）
2. 把这些输出作为证据提交给AGY，附上用户质疑的焦点
3. 让AGY裁决"今日判断是否正确"而非"代码有没有Bug"
4. 如果AGY确认判断正确 + 代码有Bug，Aggregate两步：先出裁决，再审计代码

**PITFALL**: 不要默认走代码审计。如果用户质疑的是"为什么今天没推XX"（系统判断质量），走决策裁决审计，拿当日真实输出给AGY审；如果用户质疑的是"为什么系统推荐了断板标的"（代码逻辑缺陷），才走代码审计。

当代码审计中发现的问题与决策结果一致时（如退潮期确实不该开仓），在报告开头明确标注"今日判断正确"，然后再逐条审计代码Bug。

### 2f. 核心角色（补充）

Antigravity (AGY): 首席架构师 / 独立审计员 → 输出Markdown审计报告
Hermes Agent: 执行员 → 落地修改、运行测试、提交Git

### 2g. AGY审计prompt注入方式：内嵌文件内容优于cat命令（2026-09-15新增教训）

**2026-09-15再次验证**: proc_d8e624268b66使用内嵌文本prompt（约2KB，无cat命令），依然耗时13分钟57秒才接近返回。AGY对审计类任务（即使prompt很小）的推理深度决定其耗时。**内嵌文本减少了死锁风险，但未缩短推理时间——这是AGY模型特性，不是prompt问题。**

### 2g.2 AGY成功返回模式：内嵌git diff + 原子问题 + 3m timeout（2026-09-16新发现）

**之前认为AGY审计必然超时，但2026-09-16成功复现了AGY返回**：

| 轮次 | Prompt | 字数 | Timeout | 结果 |
|------|--------|------|---------|------|
| Batch1 审计 | 内嵌4个文件diff(187行)+逐项问 | ~1400字 | 3m | ✅ **成功在2m内返回**，发现call_auction_scanner量比伪修复 |
| Batch2 复审+12文件 | 内嵌修复代码+问12个文件 | ~1950字 | 3m | ✅ 成功返回，发现volume手/股量纲100倍差 |
| Batch3 最终验收 | 简短判断 | ~650字 | 3m | ✅ 返回YES签署验收 |

**成功模式**：
- prompt内容：内嵌git diff摘录（不是完整文件，是用`git diff`提取的变更部分）
- 字数：<700字符（单问题）/ <2000字符（含上下文）
- timeout：**3m就够**（不是之前以为的15m），大prompt约2-3分钟返回
- 分轮：每轮提1-2个核心问题，不等完整审计报告，而是**发现Bug→修→复审→再发现→再修→直到签署**
- CLI命令：`cat prompt.txt | agy -p "$(cat)" --dangerously-skip-permissions --print-timeout 3m`

**与2026-09-15失败的区别分析**：
- 2026-09-15失败的是让AGY自己 `cat file.py` 读文件 → AGY shell调用卡死
- 2026-09-16成功的是Hermes先用 `git diff` 提取变更，内嵌到prompt中 → AGY纯文本推理，无shell操作
- 关键差异：**不要让AGY执行shell命令读取文件**，而是Hermes先准备好纯文本变更摘要

AGY CLI 对任何需要推理的审计类任务（即使 prompt < 100 字）持续 1-15 分钟超时——这不是 cat 命令的问题，是 AGY 模型本身的推理耗时。

**核心发现**：让 AGY 一次回答一个选择题式的超短问题（<60字），设 `--print-timeout 1m`，可以稳定在 10-30 秒内返回。但让 AGY 分析/审计/阅读任何超过 3 行文本的内容，必然超时。

```bash
# ✅ WORKS: 原子级问题，<60字，1m timeout
echo '审计如下内容（100字以内回答）：
2. leader-monitor-pm重新激活是否合理？' | agy -p "$(cat)" --dangerously-skip-permissions --print-timeout 1m

# ❌ FAILS: 任何需要推理的任务，即使<100字
# ❌ FAILS: 审计多个文件
# ❌ FAILS: 让AGY读代码找bug
```

**实战验证（2026-09-15）**：
| Prompt类型 | 字数 | Timeout | 结果 |
|-----------|------|---------|------|
| 单选择题(3选项) | ~50字 | 1m | ✅ 10-30秒返回 |
| 单问题(3行) | ~100字 | 1m | ✅ 10-30秒返回 |
| 审计3件事(含背景) | ~600字 | 3m | ❌ 超时 |
| 审计5问题(含背景) | ~1500字 | 5m | ❌ 超时 |
| 审计+代码路径 | ~2500字 | 15m | ❌ 超时 |

**2026-09-15 R2 再次验证**：成功使用原子级选择题进行 AGY 审计的三次调用：
| 轮次 | Prompt | 字数 | Timeout | 结果 |
|------|--------|------|---------|------|
| direct_executor审计 | 带背景的单问题 | ~200字 | 1m | ✅ 成功返回4条发现 |
| leader-monitor审计 | 带背景的单问题 | ~200字 | 1m | ✅ 成功返回2条发现 |
| 频率审计 | 带背景的单问题 | ~250字 | 1m | ✅ 成功返回"不够"结论 |
| 最终验收 | 简短判断 | ~150字 | 1m | ✅ 返回"验收通过" |

**处理超时的工程模式**：当需要AGY做审计时，不尝试一次问完，而是：
1. 自己完成80%的工程排查（读代码、找Bug、patch、验证）
2. 对关键的1-2个决策点，逐个拆成原子选择题问AGY（如"A方案vs B方案，选哪个？"）
3. AGY回答后根据建议修改
4. 再拆下一个原子问题问AGY验收
5. 循环2-3次完成一轮"审计迭代"

之前AGY审计的prompt习惯让AGY自己执行 `cat file.py` 读取代码，但AGY CLI的shell调用方式对大文件cat持续超时（6-10分钟无声死锁）。

**更好的方式**: 将文件内容直接内嵌到AGY prompt中，这样AGY不需要执行任何shell命令，直接阅读文本即可完成审计。

```python
# BAD — AGY需要执行cat读取文件，大文件卡死
prompt = "Read file1.py and file2.py, audit them"

# GOOD — 内嵌完整文件内容，AGY不需要shell调用
prompt = "```python\n" + open("file1.py").read() + "\n```\n```python\n" + open("file2.py").read() + "\n```\nAudit these 2 files."
```

**优点**:
- 消除AGY的shell cat死锁风险
- prompt长度可控（16KB = ~400行Python代码没问题）
- AGY直接看到文本，无需额外步骤
- 运行时间从15分钟缩短到5分钟

**注意**: 如果文件超过~500行或总行数>1500行，仍然拆分到多个AGY调用或使用子agent delegate_task模式。
- 即使prompt较小（~2KB纯文本），AGY也可能因推理过深而耗时8-12分钟，这是正常范围。
- 15分钟 `--print-timeout` 是最低安全值，不要设更短。

**2026-09-15再次验证**: proc_d8e624268b66使用内嵌文本prompt（约2KB，无cat命令），依然耗时13分钟57秒才接近返回。AGY对审计类任务（即使prompt很小）的推理深度决定其耗时。**内嵌文本减少了死锁风险，但未缩短推理时间——这是AGY模型特性，不是prompt问题。**

### 2h. AGY 两轮审计闭环中的误报识别与处理（2026-09-15新增）

AGY 审计不是100%准确的——它会误报代码问题。必须区分**真实bug**与**误报**，否则会浪费时间修复不存在的问题。

### 误报排查清单

当AGY报告一个问题时，在执行修复前先做快速确认：

| 场景 | 确认方式 | 误报判定依据 |
|------|---------|-------------|
| None-safety: `int(x.get("k", 0))` | 检查 `x.get("k",0)` 返回类型——`int` 不可能为 None | AGY忽略 `get()` 的默认返回值类型 |
| None-safety: `x = (val or 0)` | 检查 `val` 是否预期为 int——int 不可能为 None | Python `int or 0` 是防御性写法，非潜在bug |
| 条件分支不完整 | 列出全部可能的值域+数学边界 | 若值域中不存在无分支覆盖的情况则为误报 |
| 类型安全: `int(float(v))` | 确认 `v` 来源（MCP返回数值字符串还是内部直接量） | 若来源已由前序代码保证为数字，则为冗余防御（非必须但无害） |

### 2h.1 已知误报模式

**模式A: `int` 类型变量的 None-safety 误报**
```python
# AGY 报: "prev_days 可能为 None, 需要 or 0 兜底"
prev_days = int(prev_data.get("retreat_days", 1) or 1)  # 现有代码
# 实际情况: prev_data.get("retreat_days",1) 返回 int（默认值1确保返回值类型）
# int 类型不可能为 None，或 1 只是防御写法
# 判定: 误报 — 跳过
```

**模式B: 防御性写法的误报**
```python
# AGY 报: "wc_zb 可能为 None 导致 int(float(None)) 崩溃"
wc_zb = 0  # 初始化为 0
if wc_zb > 0:  # 只有大于0才使用
# 实际情况: wc_zb 循环前初始化为 0 且后续只赋值 int(v) 或保持0
# 使用前有 if > 0 守卫
# 判定: 误报 — 跳过
```

**模式C: 0/1 语义边界的误报**
```python
# AGY 报: "prev_days or 1 会在 prev_days=0 时错误地变成 1"
# 实际情况: retreat_days 在退潮状态下最小值为1，不可能为0
# 非退潮时由 else 分支处理
# 判定: 误报 — 数据逻辑层面不存在值为0的情况
```

### 2h.2 合理区分：哪些是真正的误报，哪些是值得加固的

| 误报场景 | 是否修复 | 理由 |
|---------|---------|------|
| `int` 变量的 None-safety | ❌ 跳过 | 静态类型保证不可能 |
| 防御性 `or 0` 但已有 if 守卫 | ❌ 跳过 | 逻辑上安全 |
| 0/1语义边界无实际风险 | ❌ 跳过（但不改也不影响） | 数据约束已保证 |
| 非数字字符串到 `float()` 强转 | ✅ 必须加固 | MCP 数据不可靠 |
| 字典key缺失 | ✅ 必须加固 | MCP 返回结构不可靠 |

### 2h.3 多层级连板高度字段回退链（2026-09-15完善）

系统中各脚本用不同字段名表示连板高度（streak/real_streak/board_height），甚至可能在 `quote` 字典内有 `board_height`。门禁读取时必须逐层回退，否则高位板标的会从字段命名不统一处穿透。

```python
# CORRECT: 四层回退
streak_val = candidate.get("streak")
if streak_val is None:
    streak_val = candidate.get("real_streak")
if streak_val is None:
    streak_val = candidate.get("board_height")
if streak_val is None:
    quote = candidate.get("quote", {})
    if isinstance(quote, dict):
        streak_val = quote.get("board_height")
if streak_val is None:
    streak_val = 1  # 默认首板
```

**Why**: `candidate.get("A", candidate.get("B", default))` 的嵌套写法只在第一层为None时回退——如果 `candidate` 有 `streak` 但值为 `None`，`get()` 不会触发回退。必须用显式 if-None 链。

### 2h.4 多轮审计收敛模式

当AGY发现一组Bug → Hermes修复 → AGY再审计的循环中：

1. **首轮审计**发现的通常是最明显的Bug（结构性缺陷、逻辑错误）
2. **第二轮审计**发现的通常是边缘类Bug（具体字段兼容、类型安全、兜底不全）
3. **第三轮及以后**最后的Bug通常是：
   - 误报（AGY开始极限找茬，会把合理的防御写法也当成问题）
   - 极端边缘情况（通行证中无score字段、仅存在于测试环境的N/A等）
   - 循环约2-3轮后收敛到0个真实问题+少数误报

**收敛判断标准**：当第二轮审计中>50%的问题被判定为误报，且剩余真实问题都是简单的类型安全加固（非逻辑错误），即可宣告AGY审计终止。

### 2h.5 幽灵调用模式：函数调用未定义且未导入（2026-09-15 P1发现）

**场景**: 在一个大型脚本（~1100行）中，一个函数被调用但既没有在本文件定义，也没有从任何其他模块导入。

```python
# 调用处 (call_auction_scanner.py:1046)
config = load_config()  # NameError: name 'load_config' is not defined
```

**为什么会发生**: 
- 该函数可能在早期版本中存在，重构时被删除或重命名
- 该函数可能在其他脚本中定义但未导入
- 大文件（>1000行）中容易遗漏

**审计检查点**:
1. `grep -rn "def load_config" scripts/` — 检查函数是否在某处定义
2. 如果不存在定义 → P1 级 Bug（运行时崩溃）
3. 修复: 要么导入外部模块的函数，要么在本文件新增定义

**为什么从P0降到P1**: 取决于该代码路径是否被实际执行。如果只在特殊配置下触发（如 `is_sell_only=False` + 有 `blocked_sectors`），它属于条件路径Bug，不会每次都崩溃。

**注意**: 如果文件中有 `from X import *`，该调用可能合法。优先搜索 `grep` 确认来源。

### 2h.6 量比跨字段混淆：成交量(股) vs 成交额(元)（2026-09-15 P1.5发现）

**场景**: MCP返回数据中，`volume` 为成交量（股数），`amount` 为成交额（元）。量比计算必须用`volume / 昨日成交量`，但常被写成`volume / amount`。

```python
# BAD — 股/元 单位不匹配
volume_ratio = volume / fb.get("amount", 1)

# GOOD — 股/股 同单位
prev_volume = fb.get("prev_volume", 1)  # 从数据中获取昨量
volume_ratio = volume / prev_volume
```

**审计检查点**:
```python
# 搜索所有 volume_ratio 计算
grep -rn "volume_ratio" scripts/*.py | grep -v __pycache__
# 检查除数：如果是 amount/金额 — 必错；如果是 prev_volume/昨量 — 正确
```

**数据结构参考**:
| 字段 | 含义 | 单位 |
|------|------|------|
| `volume` | 成交量 | 股数（手×100） |
| `amount` / `amt` | 成交额 | 元 |
| `open` / `close` / `high` / `low` / `price` | 价格 | 元 |
| `prev_volume` | 昨日成交量 | 股数 |

**修复时序内**：`volume` 除以任何不是同为股数的字段都是错误的量比——这是跨脚本级Bug，必须统一检查。

### 2h.9 量比计算的三重Bug陷阱链模式（2026-09-16发现）

在`call_auction_scanner.py`中，一个量比计算公式出现了**三层嵌套Bug**，这是高度复现性的跨脚本Bug模式：

```python
# 原始Bug（R6时Hermes"修复"但仍有Bug）：
prev_vol = float(fb.get("volume", fb.get("amount", 0)) or 0)
vol_ratio = volume / max(prev_vol, 1)

# 第1层：fb中无volume字段，永远fallback到amount（金额）
# 第2层：volume是手(×100股) vs amount/price是股（100倍差）
# 第3层：下游另一个if分支重新定义vol_ratio覆盖了正确的值：
#   vol_ratio = volume / max(fb.get("amount", 1e8), 1)  ← 重新用手/元计算
```

**审计检查清单（量比相关Bug）**：
| # | 检查项 | 示例 |
|---|--------|------|
| 1 | MCP/JSON数据源是否有 `volume` 字段？ | `fb.get("volume")` 返回None，fallback到amount(金额) |
| 2 | volume的**单位**是什么？手×100 vs 股 | MCP行情volume=手，A股1手=100股 |
| 3 | 昨量如何获取？昨量单位是什么？ | amount(元)/price(元)=股，与volume×100均为股 |
| 4 | 下游是否**重新定义**了同名变量覆盖正确值？ | 先算好vol_ratio，后面if分支内又 `vol_ratio = volume/max(amount,1)` 覆盖 |
| 5 | 量比截断阈值是否合理？ | 缩量板次日爆量量比可达3.0，截断到0.25会抹杀弱转强信号 |
| 6 | 换手率比较是百分制还是小数？ | `turnover_pct`=15.5(15.5%), `if turnover >= 20.0`是正确，`if turnover >= 0.20`是Bug |

**修复模式（正确写法）**：
```python
# 优先取volume字段；若没有则用amount/price估算昨量(股)
fb_vol = fb.get("volume")
prev_vol = float(fb_vol if fb_vol is not None
                 else (float(fb.get("amount", 0) or 0) / max(float(fb.get("price", 1) or 1), 0.01)))
# volume(手)*100 → 股, prev_vol为股, 统一用股
vol_ratio = (volume * 100) / max(prev_vol, 1)
# 极值截断5.0(500%)排除极端异常但保留弱转强爆量信号
if vol_ratio > 5.0:
    vol_ratio = 5.0
```

**场景**: 系统对买入候选有块红线隔离（如果候选与持仓同板块则隔离），但候选字典缺少 `sector` 字段，导致板块隔离逻辑永远找不到匹配，形同虚设。

```python
# 板块隔离逻辑（形同虚设）
if candidate.get("sector") == position_sector:
    return False, f"同板块{position_sector}不可加仓"
# → 如果 candidate 没有 "sector" 字段，get() 返回 None，永远不等于 position_sector
# → 同板块持仓永远不拦截 → 重仓单一板块系统性风险
```

**数据契约检查清单**（在审计每个候选生成路径时检查）:

| 字段 | 是否必须 | 用途 | 如果缺失 |
|------|---------|------|---------|
| `symbol` | ✅ 必须 | 交易标识 | 无法下单 |
| `sector` | ✅ 必须 | 板块隔离 | 同板块加仓无拦截 |
| `name` | ✅ 必须 | 展示 | 系统从未处理空name |
| `streak` | ✅ 必须 | 连板门禁 | 连板过滤形同虚设 |
| `price` | ✅ 必须 | 价格校验 | open_price无参照 |
| `reason` | ✅ 必须 | 交易日志 | 复盘无法追溯 |

**修复模式**: 生成候选时所有路径统一补充缺失字段，或建立 `required_fields` 验证函数在写入前拦截。

**审计方法**: 
1. 找出所有生成 candidate dict 的代码路径（用 grep 搜 `append(` + `{` 或 `candidate = {`）
2. 每条路径逐一比对 required_fields
3. 缺失字段的路径标记为 Bug

### 2h.8 f-string 变量名陷阱（2026-09-15 P0发现）

Python f-string 中 `res.get(variable_name, default)` 与 `res.get("string_key", default)` 是完全不同的语义——前者把变量名当作 Python 变量名解析，后者当作字符串键名。这是复制粘贴时的常见错误。

**P0 场景**：在 `intraday_proactive_trader.py:231` 发现：
```python
# BAD — Python将 order_id 当作变量名解析
msg += f"订单 {res.get(order_id, 已提交)}..."
# → NameError: name 'order_id' is not defined
# → 不在 try/except 范围内，抛到 while True 的 except Exception 被吞掉
# → 整轮巡检循环跳过(静默降级)，后续所有标的的卖点检查都不执行

# GOOD — 字符串键名 + 变量暂存
order_id_str = res.get("order_id", "已提交")
msg += f"订单 {order_id_str}..."
```

**审计检查点**：搜索所有 `res.get(` 出现在 f-string 中的位置，确认参数是字符串字面量（`"order_id"`）不是未定义变量（`order_id`）。

```bash
# 快速扫描
grep -rn 'f\".*res\.get(' scripts/*.py | grep -v '"\|"'
# 空结果 = 安全；有输出 = 可能全是变量名陷阱
```

**教训**：MCP返回的order_id在 `check_positions_guard` (卖出) 和 `check_buy_opportunities` (买入) 两处使用。卖出处是变量名陷阱（直接从买入处复制粘贴时漏了引号），买入处写法正确——说明是复制粘贴时引入的错误。

### 2h.7 Cron 调度频率审计维度（2026-09-15 新增）

从 `*/10` 降到 `*/5` 频率的 AGY 审计发现，以下调度频率维度必须在审计中覆盖：

| 维度 | 检查内容 | 判断标准 |
|------|---------|---------|
| **频率充分性** | 脚本的业务响应延迟容忍度 | 盘中急拉起爆(3-5分钟封板) → 必须 `*/5` 或更密；盘后统计 → 可 `*/10` 或更疏 |
| **资源竞争** | 同频脚本是否会并发调用同一 API | 同频 job 必须错峰（偏移至少 2-3分钟），否则触发并发限流 |
| **盲区覆盖** | 时间窗口是否覆盖全部交易时段 | 09:30-11:30 / 13:00-14:50 三段全部被独立脚本覆盖，不留空白 |
| **冗余覆盖** | 是否有不同脚本扫描同一维度 | 断面扫描(龙头突破)和起爆扫描(题材套利)可以并行，但必须有错峰或不同关注点 |

**AGY 已经验证的模式**（2026-09-15 循环）：
- 3次原子审计调用均在 1m timeout 内返回
- AGY 的结论是内容正确的（10分钟→5分钟，验收通过）
- 最终验收：一次简短问题（150字）返回"验收通过"

当需要审计某类模式在全系统的分布时，使用以下快速扫描命令而非人工逐文件 grep 阅读：

```bash
# 1. f-string 中 res.get( 变量名陷阱
grep -rn 'f\".*res\\.get(' scripts/*.py | grep -v '\"\\|\\\"\\|__pycache__' | head -5

# 2. JSON/JSONL 直接 write_text（非 tmp+replace 原子写入）
grep -rn '\\.write_text(' scripts/*.py | grep -v 'with_suffix\\|\\.tmp\\|\\.replace\\|__pycache__' | head -10

# 3. open() w 模式写入
grep -rn 'open.*\"w\"\\|open.*'\"'\"'w'\"'\"'' scripts/*.py | grep -v '__pycache__\\|\\.tmp\\|json\\.load\\|text\\|binary' | head -10

# 4. 硬编码具体标的止盈止损价格
grep -rn 'if sym ==\\|elif sym ==' scripts/*.py | grep -v 'test\\|example\\|#\\|__pycache__' | head -10
```

这些扫描应该在每次 AGY 审计 R1 完成后自动执行一次，作为 R2 的候选修复清单。

### 全量文件写操作安全审计自动化（2026-09-16 新增）

当需要审计 `scripts/` 目录下所有文件的写操作安全性时，使用以下自动化扫描（而非手动逐文件grep）：

```python
# 保存为 /tmp/scan_writes.py 后运行 python3 /tmp/scan_writes.py
# 对所有write_text/write_bytes/open('w')操作检测是否已用tmp+replace
import ast, os

SCRIPTS = "/home/ubuntu/.hermes/scripts"
for fname in sorted(os.listdir(SCRIPTS)):
    if not fname.endswith(".py"):
        continue
    fpath = os.path.join(SCRIPTS, fname)
    try:
        source = open(fpath).read()
        tree = ast.parse(source)
    except SyntaxError:
        continue
    writes = [(node.lineno, func.attr if isinstance(node.func, ast.Attribute) else "open(w)")
              for node in ast.walk(tree) if isinstance(node, ast.Call) and
              ((isinstance(node.func, ast.Attribute) and node.func.attr in ("write_text", "write_bytes"))
               or (isinstance(node.func, ast.Name) and node.func.id == "open"
                   and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and "w" in str(node.args[1].value)))]
    if writes:
        has_tmp = ".tmp" in source or "with_suffix" in source
        if not has_tmp:
            print(f"NEEDS_FIX: {fname} - {writes}")
        else:
            print(f"ALREADY_SAFE: {fname} - {writes}")
```

**经验**：scripts/目录77个文件全量审计后，共39处写操作修复为tmp+replace，6个P0/P1逻辑Bug被修复。纯写操作安全的文件（无逻辑变化）不需要走AGY审计，但逻辑Bug必须AGY亲自审。

### 3. retreat_days 链式递增的时间感知陷阱（2026-09-15新增铁律）

**core rule**: `retreat_days` 必须**按日历日期**增量，不是按调用次数。

```python
# BAD — 每次调用无条件 +1
prev_days = prev_data.get("retreat_days", 1)
retreat_days = prev_days + 1  # 所有守卫被绞杀

# GOOD — 校验缓存日期
today_str = dt.datetime.now().strftime("%Y-%m-%d")
prev_updated = prev_data.get("updated_at", "")
prev_date_str = prev_updated[:10] if len(prev_updated) >= 10 else ""
if prev_date_str == today_str:
    retreat_days = prev_days  # 同一天不变
else:
    retreat_days = prev_days + 1  # 跨天 +1
```

**Why it matters**: `retreat_days` 控制 `exhaustion_ebb` 的触发阈值（>=4天）。日内无限递增意味着退潮第一天10:00前就可能从1跳到4，提前激活迷你仓试盘模式——这是把防守期错判为进攻期的P0级bug。

**Also**: 非退潮状态必须将 `retreat_days` 持久化为 0，不能残留之前的值污染下游。

## 2g. AGY 持续超时的自审计替代方案（2026-09-15 新增）

### 场景
AGY CLI 对大文件审计任务（读 3+ 个 300-500 行 Python 文件）持续超时（6-10分钟 TIME OUT），短 prompt 秒回但审计长任务 >5min 无输出。这可能是 AGY 对超长上下文（多文件读+分析+推理）的已知限制。

### 替代工作流：Hermes 自审计（三阶段完成）

当 AGY 连续 2 次以上超时，切换到此模式：

**阶段1 — Caller 兼容性分析**
```bash
# 1. 找出所有变更函数/文件的新旧签名差异
grep -rn "fetch_limitup_count\|determine_regime" scripts/*.py
grep -rn "market_regime\.json\|iron_rule_gate" scripts/*.py

# 2. 遍历每个 caller，确认：
#   - 解包方式与新返回类型是否一致 (tuple[int,float] vs int)
#   - 新字段是否被下游忽略（兼容）或需要适配
#   - market_regime.json 的读者只读 regime 字段 = 向下兼容

# 3. 每个 caller 标记 SAFE / NEEDS_UPDATE / COMPATIBLE_WITH_RESERVATION
```

**阶段2 — 边缘情况测试**
```python
# 对以下场景逐一构造 determine_regime 输入验证
test_cases = [
    ("first-run (no cache)", retreat_days=0),
    ("broken_seal_rate=0 (data unavailable)", broken_seal_rate=0.0),
    ("broken_seal_rate missing fallback", broken_seal_rate=0.0),
    ("retreat_days transition across weekend", retreat_days=3→4),
    ("non-ebb to ebb transition", retreat_days=0→1),
    ("panic_ebb exact threshold", broken_seal_rate=45.0, retreat_days=2),
    ("exhaustion_ebb exact threshold", broken_seal_rate=29.9, retreat_days=4),
    ("exhaustion_ebb NOT triggered (days=3)", broken_seal_rate=28.0, retreat_days=3),
]
```

**阶段3 — 下游逻辑一致性验证**
```
对 exhaustion_ebb 的放宽逻辑，检查所有消费路径是否一致：
- tdx_pullback_scanner (scanner-level halt → MINI)
- market_regime_check.py / iron_rule_gate (gate-level pass-through)
- ignition_v1_sniper (separate load_market_regime via REGIME_MAP + iron_rule)
- intraday_theme_trigger (via check_iron_rule_gate → iron_rule_gate)
- direct_executor (via iron_rule_gate)

每个路径必须独立验证，不能假设"iron_rule_gate 改了所以大家都在用"。
```

### 根因识别清单（AGY 超时 vs 正常响应）

| AGY 行为 | 诊断 | 措施 |
|---------|------|------|
| 短 prompt ("hi") 秒回，长审计 >5min 无声 | 上下文太长/推理太深导致死锁 | 换用三阶段自审计 |
| 所有 prompt 都无声死锁 | AGY 二进制本身故障 | 重启 AGY 或走 delegate_task bypass |
| 短 prompt 也超时 | AGY 进程挂起 | `killall agy` + 重启 |

## 4.1 AGY CLI调用

绝对路径: /home/ubuntu/.local/bin/agy

参数顺序铁律: --dangerously-skip-permissions 必须在 --print 之前
代码生成任务必须设 --print-timeout 15m
大段prompt(<1500 chars)写文件后用Python bridge

## 4.2 Python Bridge调用

```python
from antigravity_bridge import ask_antigravity, ask_antigravity_json
report = ask_antigravity("prompt")
```

超时: audit 300s足够, 代码生成需 timeout=600
execute_code有300s硬超时, 长任务走terminal后台

## 4.4 AGY大型代码生成任务

- prompt < 1500 chars
- 不含完整参考代码
- 不含文件读取/验证步骤
- 明确输出格式
- timeout 15m

## 5. 多轮螺旋上升审计闭环

User→Hermes→AGY审计→修改代码→git commit→AGY复审→直到签署终结

## 6. 标准Prompt模板

### 6.1 首轮审计
包含: 待审计文件路径、业务场景、核心规则、输出P0/P1清单

### 6.2 第N轮复审
包含: 上一轮修改内容、最新测试结果、实际运行输出

## 故障排查表

| 症状 | 根因 | 修复 |
|------|------|------|
| --print吞参数 | 参数顺序错误：--dangerously-skip-permissions必须在--print前 | 调整参数顺序 |
| timeout waiting for response | prompt太长或内部API调用过多 | 精简到<1500 chars，去掉参考代码 |
| Python bridge 600s超时 | subprocess hard limit | 改用CLI + --print-timeout 15m |
| AGY输出只有描述文本 | prompt太宽泛 | 写"直接写出完整代码" |
| AGY二进制无声死锁 | agy --print 启动后进程running但output_preview永远为空，所有prompt格式均>5min无输出。短prompt秒回但审计长任务卡死 | 1) `timeout 120 agy -p "hi" --dangerously-skip-permissions --print-timeout 2m` 验证。2) 若短任务OK但长任务死锁，检查prompt是否含让AGY执行shell命令（如`cat file.py`）—改为内嵌纯文本diff即可。**2026-09-16验证: 内嵌git diff(1.4KB)+3m timeout模式成功返回**，AGY CLI可以处理审计任务 |
| 半成品代码残留在源文件 | 审计中途中断 | 审计前cp备份，中断后git checkout回滚 |
| 审计+编码+回测三合一超时 | AGY串行分解模式 | 拆分: AGY只做审计+编码，回测由独立Python完成 |
| AGY输出整个文件包含冗余改动 | prompt指示"直接输出完整代码"但AGY会输出整个文件包括已有不变代码 | 用patch定向替换新增部分，不无脑覆盖全文件 |
| execute_code 300s超时导致AGY任务被中断 | execute_code硬限制300s，代码生成任务需600-900s | 改用 terminal(background=true, notify_on_complete=true) + --print-timeout 15m |
| 多份推送报告联合审计prompt太长 | 每份报告内容堆叠使prompt超1500字符 | 精简为每份报告1-2行摘要+关键质疑清单+评级格式 |
