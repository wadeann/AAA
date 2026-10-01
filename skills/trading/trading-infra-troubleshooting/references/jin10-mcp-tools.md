# Jin10 MCP Server — Available Tools

**Server URL**: `https://mcp.jin10.com/mcp`
**Auth**: Bearer token (configured in `config.yaml` → `mcp_servers.jin10.headers.Authorization`, value from `.env` `MCP_JIN10_KEY`)
**Transport**: HTTP
**Documentation**: https://mcp.jin10.com/app/doc.html

## Tool List (8 tools)

### 行情数据

| Tool | Description |
|------|-------------|
| `get_quote` | Get latest quote for a financial instrument (e.g., XAUUSD). Returns price, open, high, low, change%, volume. |
| `get_kline` | Get minute-level K-line data for a financial instrument. |

### 快讯 (Flash News)

| Tool | Description |
|------|-------------|
| `list_flash` | List 7×24 flash news items (short-form breaking news). Paginated. |
| `search_flash` | Search flash news by keyword. |

### 资讯 (Articles)

| Tool | Description |
|------|-------------|
| `list_news` | List in-depth financial articles and analysis. Paginated. |
| `search_news` | Search articles by keyword. |
| `get_news` | Get full article details by ID. |

### 日历

| Tool | Description |
|------|-------------|
| `list_calendar` | Get this week's economic calendar (data releases, events, holidays). |

## Response Format

All tools return standard JSON:
```json
{
  "status": 200,
  "message": "success",
  "data": { ... }
}
```

## Notes

- Tools are auto-discovered at gateway startup via MCP protocol
- Registered with prefix `mcp_jin10_*` (e.g., `mcp_jin10_get_quote`)
- If not appearing in session, gateway may need restart (see `native-mcp` skill)
- Token must be obtained from https://mcp.jin10.com/ (login → activate → copy token)
