# analyze_stock_with_antigravity.py 已知 Bug 与修复记录

## Bug 1: get_positions 返回值类型不一致

**症状**: `AttributeError: 'list' object has no attribute 'get'` 在第105行 `pos.get("positions", [])`

**时间**: 2026-09-11

**根因**: `analyze_stock_with_antigravity.py` 假设 `mcp_call("get_positions", {}, port=9003)` 返回 `{"positions": [...]}` 格式的 dict，但 Broker MCP (port 9003) 实际返回的是 raw list `[{symbol, quantity, ...}]`。

**修复**: 兼容两种返回值格式：
```python
pos_raw = mcp_call("get_positions", {}, port=9003)
pos_list = pos_raw if isinstance(pos_raw, list) else pos_raw.get("positions", [])
```

**教训**: MCP 接口返回值格式可能不一致。Broker MCP 的 `get_positions` 返回 list，而其他 MCP (如 `search_news`) 返回 `{"datas": [...]}` dict。每次调用 MCP 后必须检查返回值类型。
