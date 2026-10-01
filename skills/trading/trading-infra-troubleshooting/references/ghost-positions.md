# 幽灵持仓（Ghost Positions）故障记录

## 发现时间
2026-06-19

## 问题

exec_server positions 表中存在两条无法交易的幽灵记录：

| Symbol | Quantity | Cost Price | Market Value | Status |
|--------|----------|------------|--------------|--------|
| 001377.SZ | 2000 | 30.2 | 60,400 | 幽灵 — query_data/place_order 均失败 |
| 300734.SZ | 2000 | 19.92 | 39,840 | 幽灵 — query_data/place_order 均失败 |

**锁死资金**: 60,400 + 39,840 = 100,240 元

## 根因

2026-06-17 agent 凭记忆编造股票代码：
- 纳科诺尔实际代码 920522.BJ → 被编成 001377.SZ
- 铁拓机械实际代码 920706.BJ → 被编成 300734.SZ

当时下单被 cancel（这两个代码在交易所不存在），但 exec_server 的 `sync_position` 在处理 cancel 订单时未清理 positions 表中对应的预写入记录。

## 修复方案

```python
import sqlite3
db = sqlite3.connect('/home/ubuntu/ai/pup-mcp/exec_server/exec_local.db')
cur = db.cursor()

# 1. 确认幽灵记录
for r in cur.execute("SELECT * FROM positions WHERE symbol IN ('001377.SZ', '300734.SZ')").fetchall():
    print(r)

# 2. 删除幽灵行
cur.execute("DELETE FROM positions WHERE symbol IN ('001377.SZ', '300734.SZ')")

# 3. 修正现金（加回被锁的资金）
cur.execute("UPDATE account SET value = value + 100240 WHERE key = 'cash'")

db.commit()
db.close()
```

修复后验证：
```
mcp_exec_get_positions → 确认 001377/300734 不再出现
mcp_exec_get_balance → 确认 cash 增加 100,240
```

## 预防

- 所有股票代码必须在下单前通过 `mcp_intel_wencai_search` 核实
- exec_server 应在 order CANCELLED 时自动清理 positions 表中的预写入记录（代码改进项）
