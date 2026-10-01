# 盘中 no_agent 脚本参考（v2 改造，2026-08-22）

## 概述

盘中 10:00/13:30/14:15 三个窗口已从 LLM agent 转为 no_agent Python 脚本。脚本自身通过 HTTP POST 直连 MCP 端口，不依赖 LLM 推理，延迟从 15-30 分钟降到 1-2 分钟。

## 脚本文件

- `~/.hermes/scripts/intraday_scan.py` — 盘中通用扫描（10:00 和 13:30 共用）
- `~/.hermes/scripts/close_session_scan.py` — 尾盘专用（14:15，只卖不买）
- `~/.hermes/scripts/intraday_leader_monitor.py` — 每5分钟龙头突破监控（alert_plan 驱动）
- `~/.hermes/scripts/chanlun_engine.py` — 共享缠论引擎（analyze_chanlun + leader_score）

## 执行闭环

```
脚本触发（cron schedule）
  ↓
检查交易窗口（in_monitor_window() / in_close_window()）
  ↓
检查交易日（mcp_call trading_sessions）
  ↓
拉持仓（mcp_call get_positions, port 9003）
  ↓
逐只持仓：
  → 拉30分钟K线（mcp_call fetch_kline, port 9001）
  → 缠论分析（analyze_chanlun, chanlun_engine.py）
  → 识买卖点（一买/二买/三买 / 一卖/二卖/三卖）
  → 拉实时价（mcp_call query_data）
  → 写结构化candidate JSONL
  ↓
触达统一交易闸门（run_autonomous_trades.py）
  ↓
飞书通知（stdout → 最多3行）
```

## 尾盘特殊规则（close_session_scan.py）

1. **T+1 锁定**：今日买入的持仓不可卖出，脚本自动分类 `can_sell` / `locked_t1`
2. **上升通道保护**：30分钟+60分钟均在上升通道时禁止卖出
3. **只卖不买**：尾盘脚本不含买入逻辑
4. **多周期复核**：同时拉30分钟和60分钟K线交叉验证

## cron schedule 兼容性

- croniter 不支持多段表达式，如 `31-59/5 1 * * 1-5,*/5 2-3 * * 1-5`
- 改为粗粒度 cron + 脚本内精确时间门控
- 5分钟监控的 schedule: `*/5 1-3,5-6 * * 1-5`（UTC）
- 脚本内 `in_monitor_window()` 精确过滤至 09:31-11:35 / 13:00-14:57（CST）

## MCP 调用模式：批量重试（2026-09-07 实践）

no_agent 脚本中批量 MCP 调用（如 `query_batch_data`、`fetch_kline` 多只股票并行）易因网络抖动/后端瞬时繁忙偶发超时，导致整批数据丢失。采用**每调用级别加 retries 参数**的指数退避模式：

```python
def mcp_call(port, tool, args=None, retries=0, init_timeout=10):
    """带可选指数退避重试的 MCP 调用"""
    if args is None: args = {}
    last_exc = None
    for attempt in range(1 + retries):
        try:
            timeout = init_timeout + attempt * 5  # 10→15→20
            data = json.dumps({
                "jsonrpc": "2.0", "method": "tools/call", "id": 1,
                "params": {"name": tool, "arguments": args}
            }).encode()
            req = urllib.request.Request(
                f"http://localhost:{port}/mcp",
                data=data, headers={"Content-Type": "application/json"}
            )
            resp = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
            return json.loads(resp["result"]["content"][0]["text"])
        except Exception as e:
            last_exc = e
            if attempt < retries:
                time.sleep(1 + attempt * 2)  # 指数退避
    raise last_exc
```

**规则**：
- `retries=0`（默认）：向下兼容旧调用方，一次尝试不重试
- 批量数据采集（fetch_batch_quotes、wencai 多页）：传递 `retries=2`
- 单次调用（query_data、get_positions）：`retries=0` 即可（失败概率低，失败可整体重跑）
- 调用方必须 runtime 决定是否传 retries，不要改 mcp_call 的默认签名

**例（build_ladder.py）**：`fetch_batch_quotes()` 内部调 `mcp_call(9001, "query_batch_data", {"symbols": [...], "fields": [...]}, retries=2)`。失败时仍保留 `cache_degraded` 降级日志。

## 多阶段脚本的计时与异常隔离（2026-09-07 实践）

盘中早盘调度器 (`morning_master_orchestrator.py`) 依次执行 Phase0→Phase1→Phase2→Phase3，任一阶段卡死会导致后续全部阻塞且无法定位卡死点。

**标准模式**：

```python
import time, subprocess

def elapsed():
    return f"elapsed={time.time()-t0:.1f}s"

t0 = time.time()
print(f"[MORNING] Phase0 warming MCP... {elapsed()}")

# 每个子脚本独立捕获 TimeoutExpired，精确定位卡死点
for phase_name, script_path in [
    ("Phase1 call_auction", "call_auction_scanner.py"),
    ("Phase2 limit_up", "limit_up_scanner.py"),
    ("Phase3 risk_gate", "run_autonomous_trades.py"),
]:
    try:
        subprocess.run(
            ["/home/ubuntu/.hermes/hermes-agent/venv/bin/python3",
             script_path],
            capture_output=True, text=True, timeout=90
        )
        print(f"[MORNING] {phase_name} done {elapsed()}")
    except subprocess.TimeoutExpired:
        print(f"[MORNING] ⛔ {phase_name} TIMEOUT {elapsed()}")
    except Exception as e:
        print(f"[MORNING] ⛔ {phase_name} FAILED: {e} {elapsed()}")
```

**好处**：
- 即使 Phase1 超时，Phase2 和 Phase3 继续执行（互不依赖时可独立运行）
- 日志中 `elapsed=XX.Xs` 显示每个阶段的精确耗时，替代猜测
- 子脚本的 `capture_output=True` 不丢失子脚本自身的 stdout
- 比整脚本用一个 `signal.alarm()` 兜底更精细
