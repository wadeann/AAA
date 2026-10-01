# 大盘数据工具选择指南

## 完整工具矩阵

| 数据需求 | 首选工具 | 备用 | 不可用 |
|---------|---------|------|--------|
| 大盘资金净流入/流出 | `wencai_search` | - | market_health top_inflows/outflows(常为空) |
| 板块资金流向TOP5 | `wencai_search` | - | market_health top_inflows(常为空) |
| 实时指数价格 | `query_batch_data` | `wencai_search` | market_health indices(可能过期) |
| A股个股实时行情 | `query_data`/`query_batch_data` | Jin10 `get_quote`(已验证支持A股) | - |
| A股分钟级K线 | `intel fetch_kline`(东财IP受限) | Jin10 `get_kline`(已验证支持A股) | - |
| 大盘健康度评分 | `market_health`(仅score) | - | - |
| 外盘行情(黄金/外汇/商品) | Jin10 `get_quote`/`get_kline` | - | intel(不支持) |
| 7x24快讯 | Jin10 `list_flash`/`search_flash` | intel `hot_signals` | - |
| 深度财经文章 | Jin10 `search_news`/`get_news` | intel `search_news`(不稳定) | - |
| 财经日历 | Jin10 `list_calendar` | - | - |
| A股每日要闻 | Jin10 `search_news "A股"` | intel `search_news` | - |
| 赛道分析(半导体等) | Jin10 `search_news "半导体"` | - | - |
| 宏观焦点(降息/美联储) | Jin10 `search_news "降息"` | - | - |

## 标准查询模板

```python
# 大盘资金流向（唯一可靠源 = wencai_search）
wencai_search("今日A股全市场资金流向 大盘主力资金")
wencai_search("上证指数 深证成指 今日 资金净流入")
wencai_search("今日 行业板块 资金净流入 前5")

# 外盘行情 → Jin10 get_quote
get_quote(code="XAUUSD")  # 现货黄金
get_quote(code="USOIL")   # 原油

# 7x24快讯 → Jin10
list_flash()              # 最新快讯
search_flash(keyword="美联储")

# 深度文章 → Jin10
search_news(keyword="半导体")
get_news(id="文章ID")      # 全文

# A股个股行情（双源验证）
query_batch_data(symbols=["688082.SH", "300502.SZ"])  # Intel 主源
get_quote(code="688082.SH")                            # Jin10 备用

# 财经日历
list_calendar()  # 本周全部事件
```

## Jin10 MCP 完整流程

MCP session 需要3步: `initialize` → `notifications/initialized` → `tools/call`
SSE 格式响应: `data: {"result": ...}`（需自定义解析，非纯JSON）
Token: `${MCP_JIN10_API_KEY}`（Bearer auth header）
