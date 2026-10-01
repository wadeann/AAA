# Ignition-V1 V2首板起爆策略 AGY审计全程记录（2026-09-09）

## 审计轮次

### 首轮审计（V2.0 → REJECTED）
- **结果**：6个P0 + 4个P1
- **核心发现**：
  - P0-1: 竞价爆量比手/股100倍错位（行情volume=手，K线volume=股）
  - P0-2: 竞价换手率 hardcode `* 1` 导致换手率缩小数万倍
  - P0-3: 交易所后缀 `"深" in exchange` → 深市标的全变.SH
  - P0-4: T+1退出无T+0保护（当日建仓可尾盘平仓）
  - P0-5: record_position从未被买入逻辑调用（买入仅控制台打印）
  - P0-6: check_exit未持久化回写持仓文件（执行等于空转）

### 复审（V2.1 → 发现3个潜射）
- **结果**：1个P0潜射 + 2个P1潜射
- **核心发现**：
  - 潜射P0: 仓位未截断提前落盘（满足条件的全部写入active_positions.json，但CLI只报告Top 2）
  - 潜射P1: check_exit缺少price键 → history.jsonl卖出流水price=0
  - 潜射P1: record_position缺乏同一交易日幂等性防护 → 重复开仓

### AGY原位修复（V2.2 → 终结签署）
- AGY直接修改了本地代码文件（不仅仅是输出markdown diff）
- 修复内容：截断后落盘、price键补全、幂等防护、双键兼容

## 关键教训

### AGY周收缩阱
AGY同时处理"审计+编码+回测"三大任务必定超时（15m不够）。
**正确拆分**：
1. AGY只做"审计+编码"（8m timeout）
2. 回测用独立Python脚本（terminal后台+notify_on_complete）
3. 复审只审代码（5m内完成）

### AGY可以直接写代码
部分模式下AGY不只输出markdown diff，也会直接修改文件系统。
Hermes需要：
1. 检查文件修改时间戳确认AGY是否真写了代码
2. 用git diff验证改动内容
3. 特别检查缩进正确性和不破坏已有逻辑

### K线日期匹配陷阱
klines顺序是[最早...最晚]。
找下一个交易日应该**正向遍历**找第一个 > scan_date的K线。
反向遍历(klines[::-1])会找到T-1本身而不是T日。
