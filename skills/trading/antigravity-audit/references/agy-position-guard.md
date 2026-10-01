# 全局仓位上限引擎 (Position Guard) — R32

## 动机
持仓17只极度分散，cooldown/ice阶段仍大量买入。需要候选写入阶段硬阻断。

## 设计
`position_guard.py` 作为独立脚本/模块，被cron调用或在候选写入前检查：
1. 总持仓数 > max_position_count → buy候选被reject
2. cooldown/ice阶段 + multiplier ≤ 0.3 → buy候选被reject  
3. 多管道交叉污染检测：同一标的被≥2个管道同时产候选时报警

## 调用方式
```python
from position_guard import check_position_limits
result = check_position_limits()
```

## 关键参数
- max_position_count = 5（来自 strategy_params.global_guards）
- 单笔上限 = 8%（来自 position_limits.max_single_pct）
- cooldown阻断阈值 = multiplier ≤ 0.3

## 已知缺陷
- 依赖 `get_positions` 实时获取，盘中调用有延迟
- 如果盘中持仓剧烈波动（炸板/回封），count可能不准确
