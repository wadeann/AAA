# MCP Position Field Compatibility (Hotfix Pattern)

## The Bug

Multiple scripts read MCP `get_positions` output expecting field names that don't match the actual server response.

### Actual server response format (mcp_exec_get_positions):
```json
{
  "symbol": "688331.SH",
  "quantity": 5000,
  "available_quantity": 5000,
  "cost": 121.07,
  "price": 121.78,
  "pnl": 3550.0,
  "pnl_pct": 0.0059
}
```

### What scripts were using:
```python
# BROKEN — these fields don't exist in the server response
p.get("available_shares", 0) or p.get("total_shares", 0)  # → always 0
```

## The Fix Pattern

Use a **fallback chain** that tries all possible field names:

```python
actual_qty = int(float(
    p.get("available_quantity") 
    or p.get("available_shares") 
    or p.get("quantity") 
    or p.get("total_shares") 
    or 0
))
```

## Files Fixed

| File | Lines | Issue |
|------|-------|-------|
| `scripts/explode_monitor.py` | ~L137 | 炸板卖出候选quantity=0 → 写入sell候选被is_trade_ready拒绝 |
| `scripts/utils_candidate.py` | ~L261, L284 | T+1方向冲突检查av=0 → 有持仓也被误阻断卖单 |

## Root Cause

The MCP exec server (`exec_server/main.py`) returns `quantity` and `available_quantity` as the position field names. Multiple scripts were written assuming position data uses `available_shares` and `total_shares` conventions from a different API or previous version.

## Prevention

When reading position data from MCP, always use the fallback chain pattern. When writing code that consumes `get_positions`, add a debug print of the first position's keys:

```python
positions = mcp_call(9003, "get_positions", {})
if positions and isinstance(positions, list) and len(positions) > 0:
    p0 = positions[0]
    print(f"[DEBUG] position keys: {list(p0.keys())}", flush=True)
```
