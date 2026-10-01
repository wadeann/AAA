# exec_server symbol 归一化 Bug 记录

## 发生时间

2026-06-04 盘前减仓时首次发现

## 症状

SELL 委托报 `Insufficient shares`，detail 显示 `available=0, total_qty=0`，但 DB 中实际 `available_quantity=3000`。

## 根因

`LedgerService.normalize_symbol()` 将 `600460.SH` 转为 `sh600460`（小写前缀+无后缀格式），但 DB 中 `positions` 表通过 `sync_position` 写入的 symbol 是 `600460.SH`（大写后缀格式）。两处格式不一致导致 SELL 时 `WHERE symbol = ?` 查询返回 NULL。

```python
# 旧版 normalize_symbol (有 bug):
def normalize_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if "." in s:
        s = s.split(".")[0]  # 600460.SH → 600460
    if s.startswith(("SH", "SZ")):
        pure_code = s[2:]
    else:
        pure_code = s
    if pure_code.startswith(("6", "9", "N")):
        return "sh" + pure_code  # → sh600460 ❌
    else:
        return "sz" + pure_code
```

```
# DB 中的 symbol 格式:
600460.SH    ← sync_position 写入
300820.SZ    ← sync_position 写入
# normalize_symbol 输出:
sh600460     ← 不匹配 ❌
sz300820     ← 不匹配 ❌
```

## 修复

```python
def normalize_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if s.startswith(("SH", "SZ")) and "." not in s:
        pure_code = s[2:]
    elif "." in s:
        parts = s.split(".")
        return f"{parts[0]}.{parts[1]}"  # 600460.SH → 600460.SH ✅
    else:
        pure_code = s
    if pure_code.startswith(("6", "9", "N")):
        return pure_code + ".SH"  # 600460 → 600460.SH ✅
    else:
        return pure_code + ".SZ"
```

## 关联修复

同一次排查还发现 `orders` 表有 8 列（含 `reason` 字段），但 `INSERT INTO orders` 只传 7 个值，导致所有新订单都报 `table orders has 8 columns but 7 values`。修复：INSERT 增加 `reason` 占位符和空字符串参数。

## 验证

修复后重新 SELL 600460.SH，成功提交 order_id: ORD1780560283117。
