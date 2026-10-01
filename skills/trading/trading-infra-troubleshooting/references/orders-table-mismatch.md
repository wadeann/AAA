# orders 表列数不匹配故障记录

**发现时间**: 2026-06-01

## 症状

所有 `place_order` 调用返回:
```json
{"error": "table orders has 8 columns but 7 values were supplied"}
```

## 根因

`exec_local.db` 中 `orders` 表实际有 8 列（被外部操作添加了 `reason` 列），但 `main.py` 中的 INSERT 只提供了 7 个占位符:

```
PRAGMA table_info(orders):
(0, 'id', 'TEXT', ...)
(1, 'symbol', 'TEXT', ...)
(2, 'direction', 'TEXT', ...)
(3, 'quantity', 'INTEGER', ...)
(4, 'price', 'REAL', ...)
(5, 'status', 'TEXT', ...)
(6, 'reason', 'TEXT', ...)   <-- 额外列
(7, 'timestamp', 'TEXT', ...)
```

原 INSERT:
```python
conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?)",
    (oid, symbol, side.upper(), qty, price, "PENDING", datetime.now().isoformat()))
```

## 修复

`main.py` 第 200 行:
```python
conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?)",
    (oid, symbol, side.upper(), qty, price, "PENDING", "", datetime.now().isoformat()))
```

同时更新 `CREATE TABLE` 语句 (第 66 行):
```python
conn.execute("CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, symbol TEXT, direction TEXT, quantity INTEGER, price REAL, status TEXT, reason TEXT, timestamp TEXT)")
```

## 预防

未来如果 DB 表结构再次变更，先跑 PRAGMA 检查，再对照 main.py 中所有涉及 orders 表的 SQL 语句。
