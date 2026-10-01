# Exec系统与真实持仓同步问题

## 问题描述

exec MCP 模拟交易系统在非交易时段和部分场景下拒绝交易请求。当用户有真实券商持仓但 exec 系统为空时，会导致两处不一致。

## 已知场景

### 周末/非交易日同步失败

周末手动执行 `mcp_exec_place_order` 时，风控系统返回 `"Weekend trading prohibited"`，阻止所有交易（包括买入同步持仓）。

- 错误信息: `{"approved": false, "reason": "Weekend trading prohibited"}`
- 影响: 无法在周末同步用户真实持仓到 exec

### 非交易时段风控拒绝

非交易时段（开盘前/收盘后），风控可能因 `"Non-trading hours"` 拒绝交易。

### 盘中持仓同步

盘中同步持仓时，即使 exec 为空，卖单也会返回 `"Insufficient shares"` (available=0)，因为 exec DB 中没有持仓记录。

## 处理策略

### 1. 盘前扫���遇到 exec 空持仓

- 如果用户已确认持仓（口头/消息），研究员在 context 中传入持仓列表
- 策略员/风控员在分析时不依赖 exec 数据，直接用用户口述的持仓
- 执行阶段：输出手动操作建议（限价、数量），不强行通过 exec 提交

### 2. 持仓同步最佳时机

- **最佳**: 周一 09:30 开盘后，风控 Allow 交易时段 + exec 能接收
- 先同步买入记录（establish positions），再操作卖出

### 3. 用户确认后更新记录

用户回复"已卖出"后：
- 更新当日 orders_YYYYMMDD.md 的状态
- 递延操作：下次 exec 可操作时将已执行的买卖记录同步写入

## 相关文件

- 委托记录: `~/.hermes/trading/orders_YYYYMMDD.md`
- 策略反馈: `~/.hermes/trading/strategy-feedback.md`
