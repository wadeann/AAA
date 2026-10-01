# 评分天花板 vs 门槛死区检测 (Score Ceiling Bug Pattern)

## 问题模式

```
score = expr1 + expr2  # 理论最高 X 分
if score >= THRESHOLD: # X < THRESHOLD → 永久死区!
```

## 典型案例：2026-09-14 隔日起爆午间评分

**位置**: `theme_arbitrage_scanner.py:487`
**代码**:
```python
# 注释声称: 资金分(最高30) + 涨幅蓄势(最高30) + 新闻热度(最高20)
score = min(30.0, max(0.0, inflow_yi * 3.0)) + (20.0 if chg_pct > 0 else 5.0)
```
**Bug**: 代码只实现了资金分(最高30) + 涨跌符号分(最高20)，合计最高50分。但门禁写 `if score >= 60.0`，导致所有午间板块永远不及格。

**根因**: 注释承诺了三个维度，代码只实现了两个维度。第三个维度(涨幅蓄势分)的公式 `.min(30, abs(chg)*6)` 在注释中提到了但从未被写入。

**修复**:
```python
score = min(30.0, inflow_yi * 3.0) + min(30.0, abs(chg_pct) * 6.0) + (20.0 if chg_pct > 0 else 5.0)
```
理论最高80分，通过门禁。

## 排查清单

审计时对每个 `if score >= THRESHOLD` 做以下检查:

1. **阅读评分公式**，逐项计算每个维度的最大值
2. **求和得出理论最高分 MAX**
3. **比较 MAX vs THRESHOLD**：若 MAX < THRESHOLD，直接判定为永久死区Bug
4. **检查注释 vs 代码一致性**：注释说有几个维度，代码实际上有几个
5. **检查"替代通道"是否存在**：是否有另一条路径绕过评分直接进入执行层

## 历史同类案例参考

- `price_alert` 策略 confidence 计算: 贝叶斯平滑公式中先验设为极低值，导致所有策略的 confidence 被收缩到 < 0.65，而执行层门禁是 confidence >= 0.65，造成所有策略在进入执行前即被自身的置信度统计系统排除。
