# MCP 服务端已知问题与修复

本文档记录 MCP 服务端的已知 Bug、修复方案和排查路径。

## 1. `mcp_intel_trading_sessions` 返回错误的 `is_open: false`

### 问题描述

即使在 A 股交易时段内（9:30-11:30 或 13:00-15:00），`trading_sessions` 接口返回 `is_open: false`。

### 根因

MCP intel 服务端运行在 UTC 服务器上，使用 `datetime.now()` 获取的是 UTC 时间，但代码将其与北京时间交易时段比较。

### 修复方案

修改 `/home/ubuntu/pup-mcp/intel_server/main.py` 使用 `datetime.now().astimezone(shanghai_tz)` 而非裸 `datetime.now()`。

---

## 2. `mcp_exec_sync_position` 清仓时不返还现金

### 问题描述

清仓（shares=0）时清空持仓记录，但**不返还市值对应的现金**到账户余额。

### 绕过方案

清仓后手动调用 `mcp_exec_top_up_cash` 补充对应金额。日常交易用 `mcp_exec_place_order` 执行委托。

---

## 3. `mcp_intel_search_news` 个股新闻命中率低

### 问题描述

新闻搜索经常超时或返回空。

### 根因

1. 数据源单一，仅从新浪财经通用快讯中按 keyword 过滤
2. OpenRouter free tier 频繁 429/504 导致 sentiment 分析失败

### 绕过方案

- 搜索新闻时设 `--max-time 30` 避免长超时
- 新闻超时不影响核心交易流程，silently skip

---

## 4. `mcp_intel_screen_stocks` — 东方财富 API 502

### 修复方案（2026-05-27）

重写为三级降级：wencai 优先 → 东方财富备用 → 兜底 wencai 默认查询。

---

## 5. `mcp_intel_update_watchlist` — 始终返回 `'NoneType' object has no attribute 'strip'`

### 问题描述

任何调用都返回 `{\"error\":{\"code\":-32000,\"message\":\"'NoneType' object has no attribute 'strip'\"}}`。

### 绕过方案

不通过 MCP 管理自选股，由 agent 在对话上下文中维护跟踪列表。`get_watchlist` 接口正常。

---

## 6. 盘中卖出限价单可能"水下"无法成交

### 问题描述

非交易时段提交的卖出限价单，如果盘中价格跌破限价，整笔委托成不了。

### 根因

PENDING 委托在交易时段按限价进入交易所撮合。如果当前价 < 限价（卖出单），永远不会成交。

### 操作规则 — PENDING SELL 检查流程

```
get_orders → 找出 PENDING 卖单
query_data(每只) → 对比 现价 vs 限价
现价 < 限价 → cancel_order + place_order(新价=现价-0.1)
现价 >= 限价 → 不动
```

每 30 分钟执行一次，发现水下立即撤单重挂。

---

## 7. MCP 接口调用格式

### 正确端点

```
http://localhost:9001/mcp      (intel)
http://localhost:9002/mcp      (risk)
http://localhost:9003/mcp      (exec)
```

注意是 `/mcp` 不是 `/mcp-method`。

### JSON-RPC 模板

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "id": 1,
  "params": {
    "name": "tool_name",
    "arguments": {}
  }
}
```

---

## 全量工具健康检查（2026-06-08）

| Server | 工具 | 状态 |
|--------|------|------|
| intel | query_data, fetch_hot_signals, get_watchlist, is_trading_day, screen_stocks, trading_sessions, wencai_search | ✅ |
| intel | fetch_kline | ✅ 新浪API，30/60分钟线正常 |
| intel | search_news | ⚠️ 经常超时，空结果常见 |
| intel | update_watchlist | ❌ Bug |
| intel | webx_search | ❌ `No module named 'bs4'` |
| risk | batch_check, check_intent, daily_pnl, get_blacklist | ✅ |
| exec | get_balance, get_orders, get_positions, place_order, cancel_order, sync_position, register_approved_intent | ✅ |

---

## 8. MCP 服务进程崩溃 + systemd 服务文件路径回归

### 问题描述

三个 MCP server（intel:9001, risk:9002, exec:9003）以独立 Python 进程运行，崩溃后 systemd 服务无法恢复。

### 根因

两个叠加问题：

1. **systemd template 路径回归**：`pup-mcp@.service` 的 `ExecStart` 偶尔会变回 `%i_server/main.py`（项目更新或手动编辑导致），产生 `intel_server_server/main.py` 双重后缀错误。正确值应为 `%i/main.py`。

2. **端口占用**：旧进程未完全退出，新进程启动时端口被占用 → `Address already in use`。

### 恢复流程（完整）

```bash
# 1. 检查 systemd 服务状态
systemctl --user status pup-mcp@intel_server.service

# 2. 如果路径错误，修复 service file
# 编辑 /home/ubuntu/.config/systemd/user/pup-mcp@.service
# ExecStart 必须为: %i/main.py（不要 %i_server/main.py）

# 3. 停止所有服务 + 清理残留进程
systemctl --user stop pup-mcp@intel_server.service pup-mcp@risk_server.service pup-mcp@exec_server.service
pkill -f 'pup-mcp/.*_server/main.py'
sleep 2

# 4. 确认端口释放
lsof -i :9001 -i :9002 -i :9003  # 应为空

# 5. daemon-reload + 重启
systemctl --user daemon-reload
systemctl --user start pup-mcp@intel_server.service pup-mcp@risk_server.service pup-mcp@exec_server.service

# 6. 等待启动 + 验证
sleep 5
systemctl --user status pup-mcp@intel_server.service pup-mcp@risk_server.service pup-mcp@exec_server.service

# 7. 验证 MCP 工具可用
hermes mcp test intel  # 应显示 Connected + tools
hermes mcp test risk
hermes mcp test exec
```

### 当前会话 MCP 工具断连的恢复

MCP server 恢复后，当前 agent session 的 MCP 客户端连接仍是 stale 的：

- **症状**：`hermes mcp test` 成功，但 session 内调用 `mcp_intel_*` 返回 `"MCP server 'X' is not connected"` 或 `"unreachable after N consecutive failures"`
- **根因**：Gateway 启动时建立的连接未自动重建，circuit breaker 进入冷却期（~60s）
- **临时方案**：用 curl 直接调用 MCP 端点（见下方 JSON-RPC 模板）
- **彻底方案**：等 ~60s circuit breaker 冷却后重试，或 `hermes gateway restart`

### JSON-RPC curl 直调模板（MCP 工具不可用时的 fallback）

```bash
curl -s -X POST "http://localhost:9001/mcp" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"fetch_market_health","arguments":{}}}'
```

响应解析：`result.content[0].text` 包含 JSON 数据。

### 预防

确保 MCP 服务开机自启 + 崩溃自恢复：
```bash
systemctl --user enable pup-mcp@intel_server.service pup-mcp@risk_server.service pup-mcp@exec_server.service
```
Service file 已配置 `Restart=always`，但 `enabled=disabled` 时 reboot 不自动拉起。

---

## 9. `mcp_intel_fetch_kline` — 死代码修复 + 数据源切换 ✅ 已解决

### 问题 1：方法存在但未注册到 MCP（已修复 2026-06-06）

`fetch_kline(symbol, period, count)` 已写好但**未注册到 MCP 工具列表**也未加路由分发。

**Pitfall：MCP 工具双注册** — 任何新 MCP 工具必须在**两处**注册才可调用：
1. `tools/list` 响应中的工具描述 JSON
2. `tools/call` 路由中的 `elif name ==` 分发

只写方法不注册 = 死代码。

### 问题 2：东财 API 海外 IP 被封（已解决 2026-06-06）

东财 `push2his.eastmoney.com` 对海外 IP 返回 `Empty reply from server`（curl exit 52）。

**解决方案**：切换至新浪财经 API `quotes.sina.cn`（HTTPS，JSONP 格式）：
- URL: `https://quotes.sina.cn/cn/api/jsonp_v2.php/=/CN_MarketDataService.getKLineData?symbol={prefix}{code}&scale={period}&ma=no&datalen={count}`
- prefix 映射: SH→sh, SZ→sz, BJ→bj
- 支持周期: 5/15/30/60 分钟线
- 已验证: 上交所、深市、科创板均正常

### 调用方式

```
mcp_intel_fetch_kline(symbol="600460.SH", period="30", count=100)
```

返回字段: time, open, close, high, low, volume, amount

---

*文档更新时间: 2026-06-08*

---

## 10. `mcp_intel_query_data` 股票代码映射错误

### 问题描述

`query_data` 直接按 symbol 查 tencent 行情源，**不做名称校验**。如果用户口头报股票名而 agent 猜错了代码，整个分析就建立在错误标的上。

### 已知案例

| 猜测代码 | 返回名称 | 实际对应 | 大中矿业正确代码 |
|---------|---------|---------|-----------------|
| 001208 | 华菱线缆 | 华菱线缆 | 001203 |
| 000980 | 众泰汽车 | 众泰汽车 | 001203 |

### 硬规则

对用户口头报的股票名（非代码），**必须先用 `wencai_search("股票名")` 确认代码**，再调用 query_data。不要靠记忆猜测代码。

### 验证命令

```
mcp_intel_wencai_search("大中矿业") → 返回: 股票代码: 001203.SZ, 股票简称: 大中矿业
```

---

## 11. `mcp_intel_webx_search` 依赖缺失

### 问题

无论 google 还是 ddg 引擎，都报 `No module named 'bs4'`。intel MCP server 缺少 `beautifulsoup4` 依赖。

### 绕过

用 `wencai_search` 和 `fetch_hot_signals` 替代搜索功能。这是 A 股分析的主要数据源。
