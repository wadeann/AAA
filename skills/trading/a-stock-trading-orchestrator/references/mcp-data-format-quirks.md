# MCP 数据格式兼容性记录

## query_batch_data 返回格式差异

`mcp_intel_query_batch_data` (端口 9001) 返回格式不统一，依赖后端数据源：

### 格式 A: 完整行情对象
```json
{"data": [{"symbol": "300308.SZ", "name": "中际旭创", "price": 943.0, "change_pct": 4.29}]}
```

### 格式 B: symbol 字符串列表 ⚠️
```json
{"quotes": ["688111.SH", "300308.SZ", "000001.SH"]}
```

**格式 B 时无法从返回中提取价格、涨跌幅等字段**，`extract_rows()` 无效。

### 修复方案（已应用）

在 `current_prices()` 和 `market_scenario_score()` 中增加 fallback:

```python
rows = extract_rows(raw, ("data", "rows", "quotes"))
# batch_data 可能返回 {"quotes": [str]} 格式
if not rows and isinstance(raw.get("quotes"), list):
    quotes = raw["quotes"]
    if quotes and isinstance(quotes[0], str):
        rows = []
        for sym in quotes:
            try:
                q = mcp_call(9001, "query_data", {"symbol": sym})
                if isinstance(q, dict):
                    rows.append(q)
            except Exception:
                continue
```

### 受影响的脚本

- `scripts/intraday_leader_monitor.py` — `current_prices()` 函数
- `scripts/intraday_scan.py` — `market_scenario_score()` 函数（四指数数据）

### 发现日期

2026-08-22 全系统验证时发现。非交易日格式B仍然返回正确的symbol列表，但交易日两种格式都可能出现。
