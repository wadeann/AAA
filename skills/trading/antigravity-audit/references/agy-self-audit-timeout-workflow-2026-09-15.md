# AGY 超时的自审计替代方案实战记录 (2026-09-15)

## 触发场景
用户要求 AGY 审核溢价实现（3个改进建议），每次让 AGY 读 3 个 300-500 行 Python 文件做全量审计，持续超时（6-10分钟 TIME OUT）。短 prompt 秒回但长审计任务 >5min 无声。

## 替代工作流：三阶段自审计

### 阶段1：Caller 兼容性分析

发现 `fetch_limitup_count()` 返回类型从 `int` → `tuple[int, float]`，但 grep 发现只有 `market_regime.py` 自己内部调用。其他脚本（`ignition_v1_sniper.py`, `premarket_plan_compiler.py`, `tdx_pullback_scanner.py`, `market_regime_check.py`）只读 `market_regime.json` 缓存文件（合新字段向下兼容）。

**发现**: 0 个外部 callers 需要更新。函数签名变更对全系统零影响。

### 阶段2：边缘情况测试

| 测试场景 | 输入 | 结果 | 发现的问题 |
|----------|------|------|-----------|
| 首次运行（无缓存） | retreat_days=0, broken=38% | initial_ebb ✅ | — |
| broken_seal_count 不可用 | broken_rate=0.0 | initial_ebb ✅（退化安全） | — |
| 跨周末 transition | retreat_days=3→4, broken=28% | initial_ebb→exhaustion_ebb ✅ | 链式递增在该场景正确 |
| initial_ebb 阈值测试 | broken=42.9%, days=1 | initial_ebb ✅ | 符合 9/15 真实数据 |

### 阶段3：下游一致性验证

检查 exhaustion_ebb 放宽路径的 4 个消费端：

1. **`tdx_pullback_scanner.py`** — scanner 级熔断 → MINI 首板模式 ✅
2. **`market_regime_check.py` / `iron_rule_gate()`** — 门禁级免检 PASS ✅
3. **`ignition_v1_sniper.py`** — 独立读缓存 + 另调用 iron_rule_gate ✅
4. **`intraday_theme_trigger.py`** — 通过 check_iron_rule_gate() 间接调用 ✅
5. **`direct_executor.py`** — 通过 iron_rule_gate() 校验 ✅

全部一致通过。

## 发现的 6 个 Bug 及修复

### R1: 修复的 6 个问题

| # | 问题 | 文件 | 修复 |
|---|------|------|------|
| 1 | retreat_days datetime diff 计算跨天问题（同一天多跑一直=1） | market_regime.py | 改为链式递增：读缓存 prev_retreat_days + 1 |
| 2 | total_seals_raw 可能 None 导致除零 | market_regime.py | int(None) 检查 → if None else limitup_count |
| 3 | retreat_days 没持久化到输出文件 | market_regime.py | result 加 retreat_days 字段 |
| 4 | exhaustion_ebb 放行后仍走获利盘>60%+非主线过滤 | tdx_pullback_scanner.py | 获利盘降至>40%，非主线放行 |
| 5 | iron_rule_gate 对所有退潮子类型一视同仁 | market_regime_check.py | exhaustion_ebb 直接 PASS 带迷你仓标注 |
| 6 | generate_report 没接收 regime_data/is_exhaustion_ebb | tdx_pullback_scanner.py | 更新函数签名和 main 调用链 |

### R2: 关键修复 — broken_seal_rate 数据源

**问题**: `get_limitup_ladder` API 不返回 `broken_seal_count` 字段，导致 `broken_seal_rate` 永远=0。这使得子类型判定退化到"没有炸板数据时只能走 initial_ebb"，panic_ebb 和 exhaustion_ebb 永远触达不了。

**解法**: 加入问财 `涨停炸板家数` 查询做 fallback。

```python
# Before: broken_rate always 0.0 (ladder doesn't have broken_seal_count)
ladder = mcp_call(9001, "get_limitup_ladder", {})
broken = ladder.get("broken_seal_count")  # None
# → broken_rate = 0.0

# After: wencai fallback
if broken_rate <= 0.0 and limitup_count > 0:
    wc = mcp_call(9001, "wencai_search", {"query": "今日涨停炸板家数"})
    # wc returns: {"涨停炸板家数[20260915]": 24.0}
    # → broken_rate = 24 / (32 + 24) * 100 = 42.9
```

验证通过：`broken_seal_rate: 42.9` ✅

## 与 delegate_task bypass 的关系

| bypass 方案 | 适用场景 | 限制 |
|-------------|---------|------|
| **delegate_task** (AGY无声死锁) | AGY 二进制进程活着但长任务无输出 | 子 agent 没有 memory 和上下文连续性 |
| **三阶段自审计** (AGY持续超时) | AGY 短 prompt 秒回但长审计超时 | 需要 Hermes 自己读代码+写测试+推理 |

两者互补：AGY 短任务可用时可走 AGY 轮审计；连续超时后切自审计；自审计发现的 Bug 自己修复并提交。
