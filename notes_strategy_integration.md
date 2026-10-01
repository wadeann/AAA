# Notes Strategy Integration Report

> Generated: 2026-10-01
> Source: Cross-reference analysis of 6 notes/skills/*.md files + .docx originals vs 3 existing Astock trading skills

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [stock-selection-methods.md — 选股方法体系](#1-stock-selection-methodsmd)
3. [trading-system.md — 交易体系知识](#2-trading-systemmd)
4. [ma-system-strategies.md — 均线系统策略](#3-ma-system-strategiesmd)
5. [candlestick-patterns.md — K线形态分析](#4-candlestick-patternsmd)
6. [trend-and-limitup.md — 趋势分析与涨停战法](#5-trend-and-limitupmd)
7. [volume-price-analysis.md — 量价关系与量能分析](#6-volume-price-analysismd)
8. [Integration Priority Matrix](#8-integration-priority-matrix)
9. [Implemented Changes](#9-implemented-changes)

---

## Executive Summary

**6 notes files** and **3 existing skills** were analyzed. The notes contain rich A-share trading knowledge accumulated from real trading experience. The existing skills are structurally sound but lack coverage of several proven, quantifiable strategies.

**Key finding**: The notes contain approximately **16 distinct strategy patterns**, of which only **3-4 are partially covered** in existing skills. The remaining **12+ patterns** represent integration opportunities.

**No contradictions** were found between notes and existing skills — the notes describe price-action/MA-based strategies, while existing skills use 缠论 (chan theory) as the core framework. These are complementary approaches that can coexist.

### Strategies by Priority

| Priority | Count | Key Strategies |
|----------|-------|----------------|
| **P0 — Must have** | 4 | 集合竞价选股, 单阳不破, 量能选股三天原则, 基本面ROE/毛利率筛选 |
| **P1 — Should have** | 7 | MA5捉妖, 灵猴探路, 长阳七星, 步步莲花, 仙人指路, 老鸭头, 八种量价关系 |
| **P2 — Nice to have** | 5 | 26种卖出信号, 岛形反转, 三线金叉, 出水芙蓉/三驾马车, 八种涨停形态 |

---

## 1. stock-selection-methods.md

### Summary
Complete stock selection system with 5 major methods: 集合竞价选股, 单阳不破, 量能选股, 基本面选股, 综合战法.

### Key Strategies

| Strategy | Quantifiable | A-Share Specific | Proven | Overlap |
|----------|-------------|------------------|--------|---------|
| 集合竞价三段时间规则 | Yes | Yes | Yes | None — fully unique |
| 集合竞价四步骤 | Yes | Yes | Yes | None — fully unique |
| 黑马选股法 (量比>5, 流通盘<1亿) | Yes | Yes | Yes | None — fully unique |
| 单阳不破5条介入条件 | Yes | Yes | Yes | None — fully unique |
| 量能选股放量标准(2-3倍) | Yes | Yes | Yes | Partial in operation-guide volume conditions |
| 地量买入法(四种含义) | Yes | Yes | Yes | None — fully unique |
| 阻力位滞涨三天原则 | Yes | Yes | Yes | None — fully unique |
| 基本面ROE/毛利率/主营占比 | Yes | Yes | Yes | Partial in researcher filtering |
| 单阳不破+长阳七星综合战法 | Yes | Yes | Yes | None — fully unique |

### Gaps vs Existing Skills
- **集合竞价选股法**: Completely absent from all skills. The sniper playbooks have an auction confirmation step (09:25竞价矩阵) but lack the full 四步骤 process and 黑马 filter criteria.
- **单阳不破**: No named pattern in any skill. The 5 intervention conditions are highly quantifiable.
- **量能选股 三天原则**: No time-bound volume rule in existing skills.
- **地量+小阳线=买点**: No specific 地量 detection rule.

### Integration Recommendations

| Strategy | Target Skill | Priority | Method |
|----------|-------------|----------|--------|
| 集合竞价选股法 | short-horizon-sniper-playbooks | **P0** | New section "Playbook C: 集合竞价选股" |
| 黑马选股法 | short-horizon-sniper-playbooks | **P0** | Merge into Playbook A as auction filter enhancement |
| 单阳不破 | operation-guide | **P0** | Add as named pattern with 5 rules |
| 量能选股放量标准 | operation-guide | **P0** | Add as volume condition tables |
| 地量买入法 | operation-guide | **P0** | Add as named pattern |
| 阻力位滞涨三天原则 | operation-guide | **P0** | Add as time-bound exit rule |
| 基本面ROE/毛利率 | researcher | **P0** | Add to filtering criteria |
| 单阳不破+长阳七星综合 | operation-guide | **P1** | Add as combined pattern |

---

## 2. trading-system.md

### Summary
Trading system covering 仓位控制, 止损纪律, 交易心理, 基本面分析, 市场分析方法.

### Key Strategies

| Strategy | Quantifiable | A-Share Specific | Proven | Overlap |
|----------|-------------|------------------|--------|---------|
| 轻仓保命(3-5成仓位) | Yes | Yes | Yes | Partial — operation-guide has 8% total 4% single |
| MA20防御+MA60进攻 | Yes | Yes | Yes | None — unique hierarchy |
| 三三原则(跌破确认) | Yes | Yes | Yes | Covered in trend-and-limitup notes |
| ROE/毛利率/主营分析 | Yes | Yes | Yes | Partial — researcher uses AGY but no fixed thresholds |
| PE<50倍长线标准 | Yes | Yes | Yes | None — currently no PE filter in skills |
| 注册制分析 | No | Yes | N/A | Some overlap with researcher context |
| 两会行情统计 | Yes | Yes | Yes | None |

### Gaps vs Existing Skills
- **轻仓保命理念 vs 缠论固定仓位**: Operation-guide uses fixed 8%/4%仓位 based on structure. Notes recommend 3-5成仓位 as universal rule. These are complementary — notes add macro risk adjustment.
- **MA20防御+MA60进攻**: Notes have a cleaner MA hierarchy than existing skills. Operation-guide mentions MA20止损 in the 灵猴探路 context but not as a standalone system.
- **基本面核心指标阈值**: Researcher lacks fixed thresholds (毛利率>30%制造业, ROE>5%, PE<50).

### Integration Recommendations

| Strategy | Target Skill | Priority | Method |
|----------|-------------|----------|--------|
| 仓位控制原则(3-5成) | researcher | **P1** | Add to trade intent position sizing |
| MA20/MA60攻防体系 | operation-guide | **P1** | Add as supplementary MA framework |
| 基本面阈值标准 | researcher | **P0** | Add to filtering criteria |
| 两会行情板块轮动 | researcher | **P2** | Add as seasonal reference |
| 注册制分析观点 | researcher | **P2** | Already partially covered |

---

## 3. ma-system-strategies.md

### Summary
Complete MA system: MA5捉妖, 均线粘合(出水芙蓉/三驾马车/断头铡刀), 灵猴探路, 长阳七星, 步步莲花.

### Key Strategies

| Strategy | Quantifiable | A-Share Specific | Proven | Overlap |
|----------|-------------|------------------|--------|---------|
| MA5捉妖战法(三日新高骑大牛) | Yes | Yes | Yes | None |
| 出水芙蓉(蛟龙出海) | Yes | Yes | Yes | None |
| 三驾马车 | Yes | Yes | Yes | None |
| 断头铡刀 | Yes | Yes | Yes | None |
| 灵猴探路(白线上穿黄线) | Yes | Yes | Yes | Partial — operation-guide has 60日线作为生命线 |
| 长阳七星(变盘周期第7日) | Yes | Yes | Yes | None |
| 步步莲花(涨停+缺口+实体) | Yes | Yes | Yes | Partial — sniper playbooks cover首板 but not 步步莲花 details |

### Gaps vs Existing Skills
- **MA5捉妖战法**: Completely absent. Highly quantifiable (3日新高+MA5上方+阴线回调低吸).
- **出水芙蓉/三驾马车/断头铡刀**: Classic pattern recognition — absent from all skills.
- **灵猴探路**: Partial overlap with operation-guide's MA60 as life line, but notes add the full 带量突破→缩量回踩→右侧买入 workflow.
- **长阳七星变盘周期**: Unique time-based pattern (7日变盘窗口) — quantifiable and A-share specific.

### Integration Recommendations

| Strategy | Target Skill | Priority | Method |
|----------|-------------|----------|--------|
| MA5捉妖+三日新高 | operation-guide | **P1** | Add as named pattern section |
| 灵猴探路 | operation-guide | **P1** | Add as named pattern section |
| 长阳七星 | operation-guide | **P1** | Add as named pattern section |
| 出水芙蓉/三驾马车 | researcher | **P2** | Add as pattern recognition reference |
| 断头铡刀 | operation-guide | **P1** | Add as sell signal pattern |
| 步步莲花 | sniper-playbooks | **P1** | Add as Playbook C section |

---

## 4. candlestick-patterns.md

### Summary
26 basic sell signals + 4 advanced buy strategies (仙人指路, 三线金叉, 长阳七星, 假阴真阳).

### Key Strategies

| Strategy | Quantifiable | A-Share Specific | Proven | Overlap |
|----------|-------------|------------------|--------|---------|
| 26种K线卖出信号 | Mixed | No | Yes | None |
| 仙人指路买入法 | Yes | No | Yes | None |
| 三线金叉(均线+量线+MACD) | Yes | No | Yes | Partial — MA golden cross mentioned |
| 假阴真阳(MA5三日新高骑牛) | Yes | Yes | Yes | Duplicate of MA5捉妖 in ma-system |

### Gaps vs Existing Skills
- **仙人指路**: Cleanly defined 3-K-line pattern with specific entry rules — absent from skills.
- **三线金叉**: Three-dimension synchronization (MA+Volume+MACD) — partially covered but not complete.
- **26种卖出信号**: Very comprehensive but hard to quantize fully (many are pattern-based).

### Integration Recommendations

| Strategy | Target Skill | Priority | Method |
|----------|-------------|----------|--------|
| 仙人指路 | operation-guide | **P1** | Add as pattern section |
| 三线金叉 | operation-guide | **P2** | Add as buy confirmation |
| Top-10高频卖出信号 | operation-guide | **P2** | Add as sell signal reference |
| 假阴真阳(duplicate) | Already covered by MA5捉妖 | — | — |

---

## 5. trend-and-limitup.md

### Summary
Trend line drawing (三三原则), 8 limit-up patterns, 步步莲花(三板小妖/五板大妖/七板封神), 老鸭头, 岛形反转.

### Key Strategies

| Strategy | Quantifiable | A-Share Specific | Proven | Overlap |
|----------|-------------|------------------|--------|---------|
| 趋势线画法(倾角45度最佳) | Yes | No | Yes | Partial — 三三原则 covered |
| 三三原则(3%/3天) | Yes | No | Yes | Partial in operation-guide |
| 8种涨停形态 | Mixed | Yes | Yes | Partial in Ignition-V1 |
| 老鸭头战法(三条件) | Yes | Yes | Yes | None |
| 岛形反转 | Yes | No | Yes | None |
| 进攻迫线/登高望远/进二退一 | Yes | Yes | Yes | None |

### Gaps vs Existing Skills
- **老鸭头战法**: Completely absent. Has clear 3 conditions (5日死叉再金叉, 缩量, 不破30日线) and 2 entry signals.
- **岛形反转**: Not in any skill — classic reversal pattern with clear rules.
- **攻击迫线/登高望远/进二退一**: Missing detailed limit-up continuation patterns.

### Integration Recommendations

| Strategy | Target Skill | Priority | Method |
|----------|-------------|----------|--------|
| 老鸭头战法 | operation-guide | **P1** | Add as named pattern |
| 岛形反转 | operation-guide | **P2** | Add as named pattern |
| 攻击迫线/进二退一 | sniper-playbooks | **P2** | Add to Ignition patterns |
| 趋势线三三原则 | operation-guide | **P1** | Enhance existing coverage |

---

## 6. volume-price-analysis.md

### Summary
8 volume-price relationships + 巨量交易理论 + 地量买入法 + 阻力位滞涨三天原则.

### Key Strategies

| Strategy | Quantifiable | A-Share Specific | Proven | Overlap |
|----------|-------------|------------------|--------|---------|
| 8种量价关系(地量地价到量平价涨) | Yes | No | Yes | Partial — operation-guide has basic volume conditions |
| 巨量交易理论(突破放量当天最高价) | Yes | Yes | Yes | None |
| 放量标准(2-3倍) | Yes | Yes | Yes | No exact figure in skills |
| 缩量回调判断(绿柱<前红柱) | Yes | Yes | Yes | None |
| 地量+小阳线=买点 | Yes | Yes | Yes | None |
| 阻力位滞涨三天原则 | Yes | Yes | Yes | None |

### Gaps vs Existing Skills
- **8种量价关系详解**: Operation-guide has basic volume conditions for 缠论 but misses the full spectrum of volume-price relationships.
- **巨量交易理论核心观点**: "能够解放所有套牢盘的资金一定来盈利" — unique philosophy not present.
- **缩量具体判断方法**: Notes give a visual method (绿柱<前红柱) that can be coded.
- **地量+支撑+小阳线=买点**: Clean three-condition buy signal.

### Integration Recommendations

| Strategy | Target Skill | Priority | Method |
|----------|-------------|----------|--------|
| 8种量价关系表 | operation-guide | **P1** | Add as volume-price reference section |
| 巨量交易理论 | operation-guide | **P0** | Add to volume conditions (already implemented) |
| 地量+支撑+小阳线 | operation-guide | **P0** | Add as named pattern |
| 缩量判断方法 | operation-guide | **P1** | Add technical reference |

---

## 7. .docx Files — Additional Findings

### 归海一刀涨停战法(1).docx
- Contains original definition of 8 涨停形态 (攻击迫线/登高望远/进二退一/放量过顶/冲天炮/旭日东升/三线金叉/射击之星) — all are captured in trend-and-limitup.md.
- Philosophy quote: "下跌的时候任何均线都不是支撑，上涨的时候任何均线也不是压力" — contrasts with MA-based systems. Noted but not actionable as strategy.

### 白易技术.docx
- Original source of 步步莲花 content — fully captured in ma-system-strategies.md.
- "轻指数 重个股 / 跟趋势 弃逆势 / 抓主流 放冷门" — operational philosophy.

### 5.15集合竞价选股.docx
- Original source — content fully captured in stock-selection-methods.md §1.
- Additional context: 中信证券 + 贵州茅台 as market signal indicators.

### 5.14均线妙用.docx
- Original source for MA5捉妖 + 出水芙蓉 examples — fully captured.

### 4.22广电运通和单阳不破选股.docx
- Original source for 单阳不破 + 岛形反转 — fully captured in stock-selection-methods.md and trend-and-limitup.md.
- Also covers 灵猴探路 original definition and 广电运通 case study.

---

## 8. Integration Priority Matrix

| # | Strategy | Source | Target Skill | Priority | Quant Score | Effort | Value |
|---|----------|--------|-------------|----------|-------------|--------|-------|
| 1 | 集合竞价选股四步骤 | stock-selection §1 | sniper-playbooks | **P0** | 10/10 | Low | High |
| 2 | 黑马选股法(量比>5) | stock-selection §1.3 | sniper-playbooks | **P0** | 10/10 | Low | High |
| 3 | 单阳不破5条规则 | stock-selection §2 | operation-guide | **P0** | 9/10 | Low | High |
| 4 | 量能选股法(放量+地量) | stock-selection §3 | operation-guide | **P0** | 9/10 | Low | High |
| 5 | 阻力位滞涨三天原则 | stock-selection §3.4 | operation-guide | **P0** | 10/10 | Low | High |
| 6 | 基本面阈值(ROE/毛利率) | trading-system §4 | researcher | **P0** | 8/10 | Low | High |
| 7 | MA5捉妖+三日新高 | ma-system §2 | operation-guide | **P1** | 9/10 | Medium | High |
| 8 | 灵猴探路 | ma-system §4 | operation-guide | **P1** | 8/10 | Low | High |
| 9 | 长阳七星变盘 | ma-system §6 | operation-guide | **P1** | 8/10 | Medium | High |
| 10 | 步步莲花 | ma-system §7 | sniper-playbooks | **P1** | 8/10 | Medium | High |
| 11 | 仙人指路 | candlestick §2 | operation-guide | **P1** | 7/10 | Low | Medium |
| 12 | 老鸭头战法 | trend-and-limitup §4 | operation-guide | **P1** | 9/10 | Medium | High |
| 13 | 8种量价关系 | volume-price §1 | operation-guide | **P1** | 8/10 | Medium | High |
| 14 | 出水芙蓉/三驾马车 | ma-system §3 | researcher | **P2** | 7/10 | Medium | Medium |
| 15 | 26种卖出信号 | candlestick §1 | operation-guide | **P2** | 5/10 | High | Medium |
| 16 | 岛形反转 | trend-and-limitup §5 | operation-guide | **P2** | 7/10 | Low | Medium |
| 17 | 三线金叉 | candlestick §3 | operation-guide | **P2** | 7/10 | Low | Medium |
| 18 | 8种涨停形态 | trend-and-limitup §2 | sniper-playbooks | **P2** | 6/10 | Medium | Low |

---

## 9. Implemented Changes

The following P0 and P1 integrations have been applied:

### 9.1 a-stock-short-horizon-sniper-playbooks/SKILL.md

**Added Playbook C: 集合竞价选股法 (Auction Stock Selection)**
- Complete 四步骤 process (涨幅排行 → 总量排序 → 涨幅1%-4%筛选 → 形态筛选)
- 三段时间规则 table
- 黑马选股法 conditions (量比>5, 底部启动, 流通盘<1亿, 涨幅3%-4%最佳买点)
- 交易原则 (价格优先/时间优先)

**Added Playbook D: 步步莲花**
- 7 形态特征 rules
- 买点/卖点/止损规则
- 三板小妖/五板大妖/七板封神 framework

### 9.2 a-stock-operation-guide/SKILL.md

**Added Section: 量价关系八种形态**
- Complete 8 pattern table (地量地价/天量天价/量增价平/量增价涨/量缩价跌/量增价跌/量缩价涨/量平价涨)
- Position-specific interpretations

**Added Section: 巨量交易理论**
- 放量定义(2-3倍)
- 突破放量当天最高价买入法
- 地量+小阳线=买点
- 缩量回调判断方法
- 阻力位滞涨三天原则

**Added Section: 具名战法形态核验 — 补充形态**
- 单阳不破(定义+三种形态+五条介入条件+第九根K线规则)
- MA5捉妖战法(五日线上方三日新高骑大牛战法)
- 灵猴探路(白线上穿黄线+三条件)
- 长阳七星(变盘周期第7日+衍生形态)

### 9.3 a-stock-researcher/SKILL.md

**Enhanced 基本面筛选标准** (under Step 3/候选过滤)
- 制造业毛利率>30%, 互联网毛利率>50%
- ROE>5%且同比增长
- PE<50倍(长线)
- 主营占比>70%
- 一季报净利润门槛5000万以上

---

## Appendix: Contradiction Analysis

No material contradictions were found between notes and existing skills. Observed differences:

| Topic | Notes Position | Existing Skill Position | Assessment |
|-------|---------------|----------------------|------------|
| 均线作用 | "MA60是生命线" | 缠论重结构不重均线 | Complementary — MA can be supplementary filter |
| 仓位管理 | 3-5成仓位通用 | 8%总仓/4%单票基于结构 | Different contexts (macro vs micro) |
| 止损设置 | MA20下方/支撑下方 | 结构破坏/中枢下沿×0.97 | Can coexist |
| 入场方式 | 回踩/右侧低吸 | 缠论买点结构 | Aligned — both favor confirmation |

**Conclusion**: All notes content can be safely integrated as supplementary patterns and rules without breaking existing skill logic.
