# AGY审计建议→Hermes自主实现模式 (2026-09-15)

## 场景
用户说"让agy改进"或类似指令时，不同于"让agy自己去改代码"的AGY输出→Hermes粘贴模式，也不同于"审核今日操作"的纯裁决模式。这是**AGY审计给出改进建议，但由Hermes自主读代码、设计实现方案、写入文件、测试验证**的模式。

## 会话溯源
2026-09-15: user → "让agy审核今日没发现买入机会是正确的吗" → AGY返回98/100 CORRECT + 2条改进建议 → user → "让agy改进" → Hermes自主读取6个相关文件 → 设计与实现 → 测试 → git commit

## 流程

1. **AGY给出裁决** — 提交证据→AGY返回Judgment + Score + Improvement Suggestions
2. **用户指示"让agy改进"** → 目标从"裁决"转为"实现AGY建议"
3. **Hermes读代码层**：读所有相关文件的实际内容（`read_file` / `search_files`），理解当前代码结构
4. **设计实现方案**：确定改哪些文件、怎么改、接口兼容性
5. **逐文件修改**：用 `patch` 定向替换，每改完一个文件立即 `py_compile` 验证
6. **集成测试**：模拟新/旧逻辑的分支场景验证
7. **git commit**：含完整commit message说明变更
8. **检查其他受影响文件**：搜索被改函数的其他调用者，验证向下兼容

## vs "让AGY自己去改代码"

| 维度 | 让AGY自己去改 | 让AGY改进（此模式） |
|------|--------------|-------------------|
| 代码来源 | AGY输出完整文件块 | Hermes读代码+自主写patch |
| 文件数量 | 1文件/次 | 可达多个相关文件 |
| 适配性 | AGY不熟悉周边代码 | Hermes检查所有调用者 |
| 接口兼容 | AGY可能不考虑 | Hermes强制向下兼容 |
| 适用场景 | 纯bugfix | 审计建议→架构级增强 |

## 注意事项
- AGY的建议有启发价值，但具体实现必须基于实际代码现状
- 修改函数签名后必须搜索所有调用者
- 读market_regime.json等数据文件时，先读当前内容再设计兼容格式
- 核心原则：AGY给方向，Hermes落地

## Pitfalls（2026-09-15实战教训）

### 1. 函数签名变更后的调用者扫描
修改任何被多文件引用的函数签名（返回值类型、参数列表）后，必须：
```python
search_files(pattern="import.*被改函数|被改函数", path="scripts/", file_glob="*.py")
```
即使 search_files 只返回1-2个导入者，也要检查这些导入者是直接调用还是间接使用。
特别是当函数返回类型从 `int` 改为 `tuple[int, float]` 时，所有 `result = fn()` 后直接使用 `result` 的地方都会静默出错。

### 2. 退出缓存天数计算不能用 datetime diff
不要用 `(now - prev_timestamp).days` 来计算连续退潮天数，因为同一天内多次运行 `.days=0`。
正确做法：从缓存读取旧的 `retreat_days` 值，每次 +1。新的缓存写入 `retreat_days` 供下次累加。

### 3. 先熔断再翻修（最危险模式）
在 `tdx_pullback_scanner` 这种**先 total halt 再执行三级滤网**的架构中：
- 熔断放行（如 exhaustion_ebb 模式）后，后续的获利盘门禁和非主线门禁可能仍然不可渗透
- **修复不能只改熔断条件**，必须顺着执行链检查每一个后续过滤步骤是否也需要对应放宽
- 否则系统状态是：熔断通过 → 获利盘60%过滤 → 非主线过滤 → 返回空列表 → 用户以为放行了但没有候选

### 4. 下游铁律门禁也必须有退潮子类型感知
`market_regime_check.iron_rule_gate` 对所有退潮子类型一视同仁地拒绝非龙头买入。当上游扫描器（tdx_pullback_scanner）为 exhaustion_ebb 放行了首板候选后，这些候选会经过 iron_rule_gate 时被再次拦截。
**修复方案**：所有退潮期逻辑读取 `ebb_subtype`，exhaustion_ebb 状态下放行非龙头迷你仓买入，保留仓位限制交由策略参数单独控制。

### 5. 字段 None 安全
MCP返回的 `ladder.get("total_limitup")` 可能为 `None`，直接 `int(None)` 抛异常。
修复模式：
```python
raw = ladder.get("field")
val = int(raw) if raw is not None else default
```
