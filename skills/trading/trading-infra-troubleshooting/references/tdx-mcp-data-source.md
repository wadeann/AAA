# 通达信 TDX MCP 数据源

## 状态

✅ **已上线**（2026-09-06）。4个 Tool 注册于 Intel MCP Server（port 9001）。

## 端点与认证

```
端点: POST https://txmcp.tdx.com.cn:3001/txmcp
认证: Bearer Token (TDX_API_KEY in .env)
协议: MCP Streamable-HTTP (SSE responses)
```

**启动**：无需额外配置，`intel_server/main.py` 自动从 `pup-mcp/.env` 读取 `TDX_API_KEY`。

## 已注册 MCP Tools

| Tool | 参数 | 描述 |
|:---|:---|:---|
| `tdx_quotes` | `symbol`（如 `600519`） | 实时行情快照（最新价/涨跌幅/五档盘口/换手率/估值/内外盘） |
| `tdx_kline` | `symbol`, `period`(D/W/M/5m/15m/30m/60m/1m), `count` | 历史K线（前复权 OHLCV） |
| `tdx_screener` | `query`（如"3连板"）, `limit` | 自然语言NLP条件选股 |
| `tdx_f10` | `symbol`, `module`(basic/profit/balance/cashflow/shareholder/fund_flow/dividend) | 深度F10资料 |

## 能力对比（互补关系）

| 能力域 | westock_adapter | TDX MCP | 建议主源 |
|:---|:---|:---|:---|
| 实时行情 | ✅ 基础行情 | ✅ **委比/内外盘/官方复权** | TDX |
| K线数据 | ✅ 基础K线 | ✅ **前复权高精度K线** | TDX |
| 筹码分布 | ✅ 独家算法 | ❌ 不提供 | westock |
| 资金流向 | ✅ 5/10/20日主力 | ✅ 龙虎榜+大宗交易 | westock |
| F10/财报 | ❌ 仅腾讯三表 | ✅ **30×83个F10模块** | TDX |
| 选股筛选 | ❌ | ✅ NLP选股（问财容灾） | TDX + wencai |
| 新闻/公告 | ✅ 东财快讯 | ✅ 公告原文+券商研报 | 双活 |

**核心原则**：westock 的筹码分布算法 TDX 不提供，不可替代；其他场景优先用 TDX。

## 快速调用（Hermes Agent 中）

```python
from intel_server.tdx_adapter import TDXAdapter
tdx = TDXAdapter()

# 实时行情
tdx.get_quotes("600519")

# K线（日线，100根）
tdx.get_kline("600519", "D", 100)

# 自然语言选股
tdx.screener("3连板 放量突破", 10)

# F10 深度
tdx.get_f10("600519", "basic")       # 公司概况
tdx.get_f10("600519", "profit")      # 利润表
tdx.get_f10("600519", "shareholder") # 十大股东
```

## K线周期映射

| 传入参数 | TDX 代码 |
|:---|:---:|
| D / DAY / 日线 | 4 |
| W / WEEK / 周线 | 5 |
| M / MONTH / 月线 | 6 |
| 1m | 7 |
| 5m | 0 |
| 15m | 1 |
| 30m | 2 |
| 60m / 1h | 3 |

## 代码解析规则（自动推导）

- `600519` / `SH600519` / `600519.SH` → code=600519, setcode=1 (沪)
- `000001` / `SZ000001` / `000001.SZ` → code=000001, setcode=0 (深)
- `920XXX` / `BJ920XXX` → code=920XXX, setcode=2 (北交所)
- 5位纯数字 → setcode=31 (港股)

## 待实现（P2）

- `futures_quotes` / `option_t_quote` — 期货持仓/期权Greeks
- `wenda_report` / `wenda_notice` — 公告原文+券商研报
- `security_deep_info` — ESG/治理/港美股数据

## Common Pitfalls

1. **Token 权限分级**：基础 Token 可能不含全部 F10 子表，需 try/except 软降级。
2. **westock_adapter 不可替代**：筹码分布算法 TDX 不提供，必须保留。
3. **MCP 断联不是 TDX 问题**：后端在监听（`ss -tlnp | grep 9001` OK），是 Hermes 客户端 session 断开。重启 Hermes 即可。
