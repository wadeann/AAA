# MCP 调用超时排查与修复

> **问题**: 盘中龙头监控脚本(`intraday_leader_monitor.py`)在 cron 中连续 120s 超时。
> **根因**: `search_news` MCP 接口挂了，每次调用阻塞 15s 才返回超时。旧版 `mcp_call()` 是写死 `timeout=15` 的，多支股触发后累计冲向 120s 自然超时。
> **知识: 2026-08-27**

## 症状

- Cron job 显示 `Script timed out after 120s`（或 `N` 秒，取决于 cron 的 `timeout` 配置）
- 脚本运行时间远长于正常值
- 在 cron 超时后，部分结果可能已经写入 state/candidates 文件（脚本在超时前写到哪算哪）

## 标准排查流程

### 1. 阅读脚本，列出所有 MCP 调用及时间开销

每个 `mcp_call(port, tool, arguments)` 就是一个可能阻塞的点。按脚本执行顺序列出所有调用：

```
trading_sessions（1次）→ get_watchlist（1次）→ query_batch_data（1次）→ [for each stock] query_data（1次）+ fetch_kline（2次）+ search_news（1次）+ wencai_search（1次）
```

### 2. 单独测试每个 MCP 调用的实际耗时

用 `timeout` + `python3 -c` 模拟工具封装，只测一个工具调用的耗时：

```python
import json, time, urllib.request

def mcp_call(port, tool, arguments, timeout=5):
    payload = json.dumps({'jsonrpc':'2.0','method':'tools/call','id':1,
        'params':{'name':tool,'arguments':arguments}}).encode()
    req = urllib.request.Request(f'http://localhost:{port}/mcp', data=payload,
        headers={'Content-Type':'application/json'})
    t0 = time.time()
    try:
        response = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
        text = response.get('result',{}).get('content',[{}])[0].get('text','{}')
        elapsed = time.time() - t0
        return json.loads(text), elapsed
    except Exception as e:
        elapsed = time.time() - t0
        return {'error': str(e)}, elapsed

res, t = mcp_call(9001, 'search_news', {'symbol': '600362.SH'})
print(f'{t:.1f}s', 'TIMEOUT' if 'error' in res else 'OK')
```

### 3. 对每个可疑的 MCP 工具，测试多只股票

当某工具的调用时间 > 5s 时，它就是 bottleneck：

```python
for sym in ['600362.SH', '002963.SZ', '601212.SH']:
    res, t = mcp_call(9001, 'search_news', {'symbol': sym})
    print(f'  {sym}: {t:.1f}s', 'TIMEOUT' if isinstance(res, dict) and 'error' in res else 'OK')
```

### 4. 计算最坏情况下的总时间

用每个 MCP 调用的耗时 × 调用次数，加上循环次数，估算脚本总时间。如果超过 cron 的 `timeout` 限制（通常 120s），这就是根因。

## 修复模式

### 修复 1：给每个 MCP 调用独立的短超时

将 `mcp_call` 函数改为接受可配置的 `timeout` 参数：

```python
def mcp_call(port: int, tool: str, arguments: dict[str, Any], timeout: int = 5) -> Any:
    try:
        payload = json.dumps(...).encode()
        req = urllib.request.Request(f'http://localhost:{port}/mcp', data=payload,
            headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ...
    except Exception:
        return {}
```

然后对每个工具使用不同的超时（根据其历史表现）：

```python
# 通常很快的调用 - 2s 足够
quote = mcp_call(9001, "query_data", {"symbol": symbol}, timeout=2)
# 大盘健康度也很快
sessions = mcp_call(9001, "trading_sessions", {}, timeout=3)
# 自选股拉取
wl = mcp_call(9001, "get_watchlist", {}, timeout=3)
# fetch_kline 需要稍多一点时间（数据量较大）
raw = mcp_call(9001, "fetch_kline", {"symbol": symbol, "period": "30", "count": 100}, timeout=3)
# 新闻可能超时（Intell MCP 后端 LLM 调用不稳定）
news = mcp_call(9001, "search_news", {"symbol": symbol}, timeout=2)
# wencai_search 通常在 1-3s
research = mcp_call(9001, "wencai_search", {"query": f"{symbol} ..."}, timeout=5)
```

### 修复 2：限制循环中耗时的深度处理次数

如果多个股票同时触发，每个都会跑完整的 `quick_evaluate()`（含 5 个 MCP 调用），很容易超时。加硬限制：

```python
processed_count = 0
for plan in plans:
    if processed_count >= 3:  # 单次最多深度处理 3 只
        break
    result = quick_evaluate(plan, live_price)
    if result:
        processed_count += 1
        ...
```

### 修复 3：用批量调用替代串行逐个调用

`query_batch_data` 比串行 `query_data` 快得多（1s 查 22 只 vs 每只 0.1s + 网络开销）：

```python
prices = mcp_call(9001, "query_batch_data", {"symbols": symbols}, timeout=5)
```

## 已知容易超时的 MCP 工具

| MCP 工具 | 典型耗时 | 建议超时 | 备注 |
|----------|---------|---------|------|
| `trading_sessions` | < 0.05s | 3s | 极快，本地计算 |
| `query_data` | 0.1-0.5s | 2s | 单只行情 |
| `query_batch_data` | 1-2s（22 只） | 5s | 批量查询 |
| `fetch_kline` | 1-4s | 3s | 东财 API 海外 IP 不稳定 |
| `search_news` | **2-10s（常超时）** | **2s** | **LLM 情绪分析后端不稳定，最常见超时源** |
| `wencai_search` | 1-3s | 5s | 问财接口通常稳定 |
| `get_watchlist` | 0.5-8s | 3s | MCP 实时 vs 本地文件落差大 |

## 验证修复

改完后手动跑一次脚本，确认总时间在限制内：

```bash
timeout 30 python3 /path/to/script.py
```

预期输出应在 15-20s 内完成（22 只股票 + 1-3 只深度处理）。
