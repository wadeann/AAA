# AGY 二次审计方法与验证记录 — 2026-09-02

> 场景：用户说"AGY编程完成，你审计一下得分" → Hermes独立审计 → 发现6个P0/P1/P2问题 → AGY修复 → Hermes二次审计验证

## 本次审计的独特价值

本参考文档记录了R34-R38二次审计中**真正验证了修复效果**的方法，而不仅仅是"检查代码改没改"。

## 验证方法（before/after对比）

### 重要原则：只检查代码不够，必须运行验证

| 检查维度 | 代码上看出 | 运行验证看出 |
|----------|-----------|-------------|
| 函数存在性 | ✅ grep | ✅ |
| 参数签名正确 | ✅ | ✅ |
| 逻辑正确性 | ❌ 凭猜 | ✅ 真跑 |
| 数据源真实性 | ❌ 凭检验 | ✅ 看字段值 |
| 下游消费 | ❌ | ✅ 链路全跑 |

### R35 sector_kinetics 参数传递修复验证

这是最好的例子——修复后农业种子板块角色**自动变化**：

```
# BEFORE（修复前 — sector_kinetics 未传递，涨幅和资金流因子永远为0）
农业种子: 动能35分 → defensive_exit（只卖不买）

# AFTER（修复后 — load_sector_kinetics 从天梯标的均值和 sector_flow 融合）
农业种子: 动能45分 → secondary_attack（允许买入）
```

验证步骤：
```python
# 1) 确认 load_sector_kinetics 被调用
grep -n 'sector_kinetics = load_sector_kinetics' premarket_plan_compiler.py

# 2) 确认参数传到了两个消费方
grep -n 'sector_kinetics=sector_kinetics' premarket_plan_compiler.py
# → assess_sector_momentum 和 classify_sector_role 都拿到了

# 3) 运行看实际输出变化
python3 scripts/premarket_plan_compiler.py
# 对比历史输出：农业种子从defensive_exit→secondary_attack
```

### R36 海象运算符修复验证

```
# BEFORE
if direction := cand.get("direction", "buy") == "buy":  # direction=布尔值

# AFTER
if (direction := cand.get("direction", "buy")) == "buy":  # direction="buy"
```

验证：单元测试覆盖买卖方向
```python
# sell方向不应该触发板块偏离检查
args = {'quote': {'current_pct': 3.5, 'change_pct': 3.5},
        'sector_quote': {'current_pct': -2.0, 'change_pct': -2.0}}
r = evaluate_all({'direction': 'sell'}, **args)
assert r['pass'] == True  # 卖单跳过板块偏离！

# buy方向应该触发
r = evaluate_all({'direction': 'buy'}, **args)
assert r['pass'] == False  # 买单被板块偏离拦截
```

不同类型的测试覆盖不同维度：
```
evaluate_all({'direction': 'buy'}, {})                     # 降级：无quote→默认放行
evaluate_all({'direction': 'sell'}, ...)                   # 卖单：跳过所有买入检查
evaluate_all({'direction': 'buy'}, quote={speed_pct_3min:6.0})  # 涨速过滤
evaluate_all(..., index_quotes={...四大指数-1%})            # 大盘熔断
evaluate_all(..., index_quotes={'000001.SH':{'change_pct':-2.5}}) # 上证熔断
```

### R38 hit_rates 重写验证

**核心原题**：`calculate_hit_rates` 返回硬编码字典。

验证：
```python
hr = calculate_hit_rates()
for sec, d in hr.items():
    print(f'{sec}: 样本={d["sample_count"]}, 胜率={d["win_rate"]}, 数据源={d["data_source"][:30]}')
```

关键检查点：
1. `data_source` 字段是否写死固定字符串 → 标记为 `feedback/candidates_*.jsonl (real)`
2. 样本数是否与实际 JSONL 行数匹配 → `wc -l candidates_*.jsonl` 总行数 vs sum of sample_count
3. 三大核心板块（装配式建筑、短剧传媒、农业种子）是否有非零样本 → 是否真的读到了历史记录

### R38 动态配额消费验证

**核心原题**：`dynamic_quota_adjustment` 的动态配额只在 main() 打印，没有被 `check_position_quota` 或 `classify_and_constrain` 使用。

验证：
```bash
# 检查消费方是否调用了动态调整
grep -n 'dynamic_quota_adjustment' sector_action_matrix.py
# 应在 check_position_quota 和 classify_and_constrain 中都出现
```

运行验证（retreat模式）：
```python
adj = dynamic_quota_adjustment('装配式建筑', plan=plan)
print(adj['adjusted_quota_pct'])  # retreat模式→0.0

quota = check_position_quota('装配式建筑', {}, plan=plan)
print(quota['pass'])  # False（因配额已调为0）

result = classify_and_constrain(
    {'primary_sector': '装配式建筑', 'direction': 'buy'}, plan=plan)
print(result['action'])  # 'pop_sell'
print(result['max_position_pct'])  # 0.0
```

## 常见P3问题

即使主要P0/P1修复后，仍会留出P3边界问题：

1. **sector_flow 日期滞后**：`load_sector_kinetics` 取最新sector_flow_*.json，但这个文件可能是7天前的（如果没生成）。不影响核心逻辑但降低动能因子时效性。

2. **板块名噪点**：`_resolve_sector` 对于不在alias_map中的细分子行业会保留原始长名（如`电子||消费电子||消费电子零部件及组装`），导致板块名膨胀。不影响核心三大板块。

3. **边界降级路径**：某些函数在空数据时正常降级（返回默认值）但没有日志打印，造成后续消费方可能"收不到数据但不报错"。
