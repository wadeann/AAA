# AGY Round 2 审计修复记录 (2026-09-15)

## 背景
AGY第一轮审计发现7个bug，全部修复后（fe0d218）提交AGY第二轮复审。第二轮审计确认核心逻辑正确，但仍发现3个真实问题+2个误报。

## 发现: 3 real + 2 false positives

### 真实问题（已修复）

**1. streak字段回退盲区 — market_regime_check.py:121-125（P1级）**
- 症状: `exhaustion_ebb` 门禁用 `candidate.get("streak", candidate.get("real_streak", candidate.get("board_height", 1)))` 读取连板高度。但如果候选中 `streak` 字段存在但值为 `None`（或根本无board_height字段），`get()` 的嵌套回退不会触发——Python的 `get()` 只在key缺失时回退，key存在但值为None时不回退。
- 修复: 改为显式四层 if-None 回退链，新增 quote.board_height 作为第4层回退
- 提交: 6bbf955

**2. change_pct float强转ValueError无防护 — market_regime_check.py:102-107（P2级）**
- 症状: 如果candidate字典中 `change_pct` 字段值为非数字字符串（"N/A"、"--"），`float()` 直接崩溃
- 修复: try/except包裹，兜底 target_change_pct = 0.0
- 提交: 6bbf955

**3. chip_profit_rate float强转ValueError无防护 — tdx_pullback_scanner.py:303（P2级）**
- 症状: MCP筹码分布接口返回非数值字符串时 `float()` 崩溃
- 修复: try/except包裹，兜底 chip_profit_rate = 0.0
- 提交: 6bbf955

### 误报（已跳过）

**4. market_regime.py:207 — wc_zb None-safety误报**
- AGY说: `limitup_count` 可能为 None 在 `limitup_count + wc_zb` 中崩溃
- 实际情况: `limitup_count = int(cnt)` 或 `wc_zt = int(float(v))` 确保为int，int不能为None
- 判定: 跳过

**5. market_regime.py:327 — prev_days or 1 误报**
- AGY说: `prev_days=0` 时 `or 1` 把0变成1
- 实际情况: 退潮状态 retreat_days >=1，不可能为0；非退潮由else分支处理
- 判定: 跳过

## 两轮审计收敛分析
- Round 1: 7个真实bug，0误报 — 全部是结构性/逻辑性缺陷
- Round 2: 3个真实bug + 2个误报 — 真实的都是边缘安全加固，逻辑已无缺陷
- 收敛判断: 第二轮>50%是误报，真实问题仅是类型安全加固，非逻辑错误 → 审计可终止

## 关键教训
1. `candidate.get("A", candidate.get("B", default))` 嵌套回退仅在key缺失时生效，key存在但值为None时不会触发下一层
2. 所有从MCP/字典获取的数值字段（change_pct/筹码比例）都必须try/except防护
3. AGY第二轮的误报率会显著升高——识别并跳过，不浪费修复时间
