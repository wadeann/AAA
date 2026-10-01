# Watchlist 数据契约

## 存储

`~/.hermes/trading/watchlist.json`

## Schema

```json
{
  "watchlist": [
    {
      "symbol": "688331.SH",
      "name": "荣昌生物",
      "added_date": "2026-06-16",
      "reason": "持仓标的，创新药+B1反弹末端，成本110",
      "status": "active"
    }
  ],
  "last_updated": "2026-06-16T00:00:00"
}
```

## 字段说明

| 字段 | 必填 | 说明 |
|------|------|------|
| symbol | ✅ | 带后缀代码，如 688331.SH / 300014.SZ |
| name | ✅ | 股票简称 |
| added_date | ✅ | ISO 日期，加入日期 |
| reason | ✅ | 纳入理由（含成本、策略标签等） |
| status | ✅ | `active` / `removed` / `paused` |

## MCP 工具

- `mcp_intel_get_watchlist` → 读取文件并返回
- `mcp_intel_update_watchlist` → 增删标的（操作后自动更新 `last_updated`）

## 维护周期

- **日增量**：盘中/盘前 cron 自动扫描新增候选
- **周深清**：周五 20:00 cron（a-stock-watchlist-update）深度审查，清除失效标的、补充新候选

## 与持仓的关系

- 持仓标的**必须**在 watchlist 中（status=active），用于盘前/盘中监控
- 观察池标的 = watchlist 中非持仓的 active 标的
- 已清仓标的移入 status=removed，不在日常监控中但保留历史
