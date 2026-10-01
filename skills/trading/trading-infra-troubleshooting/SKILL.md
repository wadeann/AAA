---
name: trading-infra-troubleshooting
description: 交易系统基础设施故障排查与恢复：exec/risk/intel MCP 服务调试、DB 修复、账户重置、服务重启。
---

# 交易系统基础设施故障排查

> TDX 通达信数据源（工具列表、K线周期映射、代码解析规则、能力对比）详见 `references/tdx-mcp-data-source.md`。
>
> 新浪/腾讯/东方财富/同花顺实时行情接入、多源价格共识、异常源隔离与 MCP 健康检查详见 `references/multi-source-market-data-mcp.md`。用户纠正关键行情后，必须先多源重拉并核验，再解释市场或修改策略。该参考还规定了“公开行情高频通用数据 + 问财低频语义细节”的职责分层、逐源 TTL、失败负缓存、熔断和 SingleFlight 验证方法。

## Broker 持仓接口返回空但用户声称有持仓（故障频率：中，严重度：高）

### 症状
- `get_positions` 返回 `[]`（空列表）
- `get_balance` 显示 `market_value: 0`，总资产=可用现金（100%现金）
- Playbook 输出"账户持仓接口返回空列表"，防守卡为空
- 用户反驳说自己持有 10+ 支股票，且已在历史对话中多次确认

### 根因诊断
exec MCP 仍在监听（port 9003 可连通），`get_balance` 也能返回正确总资产。但：

1. **券商账户未连接**：exec MCP 后端连接的券商账户可能未持有这些股票（如演示账户/模拟账户/不同资金账户）
2. **手动持仓不在系统内**：用户在券商之外通过其他方式买了股票，broker API 自然看不到
3. **已清仓而用户记忆偏差**：前一日收盘复盘确认为空仓

### 三行诊断
```bash
# 1. 确认 exec MCP 是否在线
ss -tlnp | grep 9003

# 2. 拉持仓和余额
timeout 10 python3 -c "
import json, urllib.request
for tool in ['get_positions','get_balance','get_today_trades']:
    payload = json.dumps({'jsonrpc':'2.0','method':'tools/call','id':1,'params':{'name':tool,'arguments':{}}}).encode()
    req = urllib.request.Request('http://localhost:9003/mcp', data=payload, headers={'Content-Type':'application/json'})
    try:
        resp = json.loads(urllib.request.urlopen(req,timeout=10).read())
        text = resp.get('result',{}).get('content',[{}])[0].get('text','{}')
        print(f'=== {tool} ===\n{text[:500]}')
    except Exception as e:
        print(f'=== {tool} ===\nERROR: {e}')
"

# 3. 对比前一日收盘复盘
cat ~/.hermes/trading/reviews/review_$(date -d 'yesterday' +%Y-%m-%d).md | grep -E "持仓|现金|总资产|空仓"
```

典型输出：
```
=== get_positions ===
[]
=== get_balance ===
{"cash": 598247.92, "available_balance": 598247.92, "market_value": 0, ...}
```
昨日复盘：**持仓标的数：0** + **可用现金：598,247.92 元**

### 修复/应对方案（分场景）

#### 场景 A：用户声称的持仓是真实存在的（优先怀疑 broker 连接了错误账户）
1. 检查 exec MCP 启动命令和配置，确认 `account_id` / `broker_url` 指向正确的券商账户
2. 若无法修复（账户权限/券商 MCP 限制），**建立手动仓位覆盖机制**：
   - 用户报持仓后，立即更新 `memory` 中的持仓记录
   - 立即构建自定义 alert plan（`alert_plan_YYYY-MM-DD.json`），写入所有用户声明的标的及止损位
   - alert plan 会被 `close_session_scan.py`（14:15/14:30/14:45）等盘中监控脚本读取
   - 告知用户：系统后端看不到这些仓位，盘中防守靠的是手动 alert plan 而非 broker 实时仓位

#### 场景 B：用户记忆偏差——昨日确已清仓
1. 展示昨日收盘复盘证据（持仓0、可用现金=总资产）
2. 按用户最新声明的标的建立价格观察 alert plan（不做持仓级别止损，做条件触发级别的价格提醒）
3. 更新 memory 中的持仓信息

### 构建 alert plan 的规范

当 broker API 空仓但用户声明持仓时，按以下标准构建：

```python
plans = []
for symbol, name, price, stop_loss, thesis in holdings:
    plans.append({
        "symbol": symbol,           # 带后缀：688798.SH
        "name": name,
        "source": "portfolio_holding",
        "plan_date": today,
        "direction": "sell",
        "thesis": thesis,
        "sell_alert": {"below": stop_loss, "condition": f"跌破{stop_loss:.2f}防守线"},
        "buy_alert": {},
        "status": "armed",
        "leader_score": 60,
        "leader_class": "portfolio_defense",
        "catalyst_type": "holding_defense",
        "exit_rule": {"stop_loss_structural": stop_loss}
    })
```

每个标的的止损价选择原则：
- **优先用前一日最低价**（跌破前日低点=短线确认走弱）
- **次选筹码成本 × 0.97**（跌破筹码成本=主力全线亏损）
- **大阳线/涨停股**：用大阳线底部（涨停首板开盘价或当日最低点）
- **强势反弹股**：用移动止盈（成本+5%/+10%/+14%阶梯）

验证：
```bash
python3 -c "
import json; p=json.load(open('/home/ubuntu/.hermes/trading/alert_plans/alert_plan_$(date +%Y-%m-%d).json'))
for x in p['plans']:
    a = x.get('sell_alert',{})
    print(f'  {x[\"name\"]:10s} {x[\"symbol\"]:12s} 止损:{a.get(\"below\",\"-\")}')
"
```

## 市场状态机卡死：昨日恐慌状态未复位（故障频率：中，严重度：高）

### 症状
所有买入候选被 `iron_rule_gate` 阻断，返回 `铁律熔断 AGY-01: 市场处于【退潮·恐慌杀跌】期` 或 `【极寒】状态`，但实际当日市场正常（涨停40+，指数平盘，无恐慌）。

**误判表现**：用户或 LLM session 内判断今日"无买点"——不是真的没有，而是系统底层把门关死了。

### 根因
`market_regime.json` 中的状态机在收盘时进入 `regime=极寒/panic_ebb, sell_only_mode=true` 后没有任何"次日开盘自然复位"机制。即使次日市场恢复正常，`get_market_regime()` 和 `iron_rule_gate()` 仍读取昨天写入的状态，阻断所有开仓。

叠加效应：`get_market_regime()` 在盘中重新运行时若某些数据源（median_change/limitdown_count）不可用，会触发 Fail-Closed 防御态，进一步锁定。

### 快速诊断（三行命令）

```bash
# 1. 检查 market_regime.json 的时间戳——如果日期不是今天，大概率卡死
grep -E '"updated_at"|"source_date"' ~/.hermes/trading/config/market_regime.json

# 2. 检查 strategy_params.json 的 sentiment 相位
grep -E '"phase"|"multiplier"' ~/.hermes/trading/config/strategy_params.json

# 3. 对照实际市场健康度
python3 -c "import urllib.request, json; \
data=json.loads(urllib.request.urlopen(urllib.request.Request('http://localhost:9001/mcp', \
data=json.dumps({'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'fetch_market_health','arguments':{}}}).encode(), \
headers={'Content-Type':'application/json'}), timeout=10).read()); \
d=json.loads(data['result']['content'][0]['text']); \
print(f'健康分:{d[\"score\"]}, 摘要:{d[\"summary\"]}')"
```

典型诊断输出 when stuck（日期跨天 + phase=ice + 实际市场正常）：
```
market_regime: updated_at=2026-09-28T14:55:30  ← 昨天的日期！
sentiment: phase="ice", multiplier=0.0         ← 冻结态
market_health: 健康分 54.5, 摘要=资金震荡盘整      ← 实际正常
```

### 修复：强制复位

```python
import json, datetime as dt
from pathlib import Path

now = dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))

# 1. 复位 market_regime.json
regime_data = {
    "regime": "震荡",
    "standard_regime": "oscillating",
    "regime_multiplier": 0.40,
    "max_regime_ratio": 0.50,
    "sell_only_mode": False,
    "description": f"盘前复位：正常震荡市",
    "updated_at": now.isoformat(),
    "source_date": now.strftime("%Y-%m-%d"),
    "ttl_seconds": 900,
    "data_fresh": True,
    "fail_closed": False,
}
regime_path = Path("~/.hermes/trading/config/market_regime.json").expanduser()
tmp = regime_path.with_suffix(".tmp")
tmp.write_text(json.dumps(regime_data, ensure_ascii=False, indent=2))
tmp.replace(regime_path)

# 2. 复位 strategy_params.json sentiment
sp_path = Path("~/.hermes/trading/config/strategy_params.json").expanduser()
sp = json.loads(sp_path.read_text(encoding="utf-8"))
sp["sell_only_mode"] = False
sp["sentiment"] = {
    "phase": "oscillating",
    "multiplier": 0.40,
    "description": "盘前复位：震荡盘整市",
    "cand_count": sp.get("sentiment", {}).get("cand_count", 0),
    "updated_at": now.isoformat(),
}
sp["global_guards"]["sell_only_mode"] = False
tmp2 = sp_path.with_suffix(".tmp")
tmp2.write_text(json.dumps(sp, ensure_ascii=False, indent=2))
tmp2.replace(sp_path)
```

### 事前预防
若想从根上杜绝此问题，可以创建一个凌晨 08:30 运行的 Hermes cron job，在开盘前强制刷新 `market_regime` 状态为当日基准：

```
cronjob(action="create", schedule="30 08 * * 1-5", name="market-regime-morning-reset",
  no_agent=True,
  script="~/.hermes/scripts/_morning_reset_market_regime.py",
  enabled_toolsets=["terminal"])
```

该脚本只需：拉取 `fetch_market_health` 和 `is_trading_day` → 若健康分≥50且is_trading_day=true → 写入标准震荡态。无信号不发通知。

### Pitfall：复位后被 `get_market_regime()` 再次覆盖

手动复位后，若盘中 cron 或代理调用 `get_market_regime()` 且该函数遭遇数据源不可用（median_change=null, limitdown_count=null），会再次触发 Fail-Closed → 重新冻结。必须同步排查数据源健康：

```bash
python3 ~/.hermes/scripts/market_regime.py --verbose 2>&1 | grep -E "Fail|缺失|异常|警告"
```

若常见缺失是 median_change（全A中位数），可以在 `market_regime.py` 中将其从必选降级为可选——缺失时使用其他可用信号（涨停家数、指数涨跌）做 fallback，而不是直接 Fail-Closed。

## MCP 服务断联排查标准流程

症状：Hermes 工具列表缺少特定 `mcp_*` 工具（如 `mcp_intel_*` 全部消失）。

排查步骤：

```
1. ss -tlnp | grep -E "9001|9002|9003"     # 确认后端进程是否在监听
2. grep "intel\|mcp.*fail\|Failed to connect" agent.log | tail -5  # 查断联原因
3. curl -s http://localhost:$PORT/mcp -X POST ... # 直接验证后端是否响应
```

典型断联根因：

### A. 时序竞争（Race Condition，最常见）
Hermes gateway 启动时按 config 顺序依次连接 mcp_servers。如果目标端口当时还没监听，3 次尝试后标记为永久 failed。

日志特征：
```
WARNING tools.mcp_tool: MCP server 'intel' initial connection failed (attempt 3/3)
WARNING tools.mcp_tool: MCP server 'intel' failed initial connection after 3 attempts
WARNING tools.mcp_tool: Failed to connect to MCP server 'intel': [Errno 111] Connect call failed
INFO  tools.mcp_tool: MCP: registered 22 tool(s) from 3 server(s) (1 failed)
```

修复：确认端口监听后，打 `/restart` 让 Hermes 重新加载 MCP 服务器。

### B. 后端进程崩溃
日志无连接错误，但 `ss` 显示端口未监听。

排查：`ps aux | grep main.py` 看进程是否存在
修复：重启对应服务（`cd pup-mcp && .venv/bin/python3 -u intel_server/main.py`）

### C. Jin10 keepalive 频繁失联（已知行为）
日志特征：`MCP server 'jin10' keepalive failed, triggering reconnect`。
不影响其他 MCP 服务器，自动恢复。

## MCP 端口布局

| 端口 | 服务 | 工具数 | 目录 |
|:---|:---|:---:|:---|
| 9001 | Intel（行情/资金/技术/选股/News） | 26 | `ai/pup-mcp/intel_server/` |
| 9002 | Risk（风控审批） | 4 | `ai/pup-mcp/risk_server/` |
| 9003 | Exec（下单/持仓/成交） | 8 | `ai/pup-mcp/exec_server/` |

## 维护命令

```bash
# 检查端口
ss -tlnp | grep -E "9001|9002|9003"

# 重启 Intel
pkill -f "intel_server/main.py"
cd /home/ubuntu/ai/pup-mcp && .venv/bin/python3 -u intel_server/main.py > intel.log 2>&1 &

# 检查日志
tail -30 ~/.hermes/logs/agent.log | grep "mcp\|intel"

# 直接验证 MCP 响应
curl -s -X POST http://localhost:9001/mcp -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## no_agent 脚本时序陷阱（高频故障模式）

`no_agent=True` 脚本由 cron 调度器直接 `subprocess.run` 执行，**不进 LLM 代理循环**。

## Cron 存废判断与冗余诊断

当用户问"这个 cron 有没有必要存在"、"为什么长期没信号"、"删掉它"时，按 `references/cron-audit-and-redundancy.md` 执行六步诊断：确认元信息 → 检查连续多日历史输出 → 区分用户面向信号 cron vs 纯数据管道 cron → 检查脚本内部门槛 → 排查与其他 cron 的冗余覆盖 → 判定删除/保留/调门槛。核心区分：**用户面向 cron 从不产买卖信号 = 冗余嫌疑；数据管道 cron 被下游引擎依赖 = 基础设施不可删**。若脚本保留候选分支但候选恒为空，优先查"数据源白名单门禁"类 bug：函数内部若自己 `mcp_call(wencai_search)` 取数，则外部传入的 `data_source_used` 参数**不得**成为短路条件——这正是 `intraday_hot_sector_sniper.get_buyable_candidates`（已修复，第409行）与 `fetch_hot_sectors_and_ladder`（已修复，第342行）的根因，详见 `references/intraday-hot-sector-sniper-candidate-bug.md`。判别标准：**自己取数的函数，source 参数只作信息不作门禁**；发现一处后全脚本 grep 同类 `data_source_used ==/!= "wencai"` 逐一判定，避免漏网之鱼。

## 文件原子写入审计（2026-09-15 R2 新增）

### 背景
本系统有 27 个 cron job 和多个常驻进程并行读写 JSON/JSONL 文件。非原子写入（直接 `write_text`/`open().write()`）在进程崩溃时导致文件截断/损坏，后续读取 `json.loads` 崩溃。

### 审计清单

快速扫描命令：
```bash
cd ~/.hermes/scripts
# 扫描所有直接 write_text（非 tmp+replace）
grep -rn "\.write_text(" *.py | grep -v ".with_suffix\|\.tmp\|\.replace\|__pycache__"
# 扫描所有直接 open(..., "w")
grep -rn "open.*\"w\"\|open.*'w'" *.py | grep -v "__pycache__\|\.tmp"
```

### 修复模式

对状态文件/配置文件/运行数据文件，必须使用 **tmp+replace 原子写入**：

```python
# BAD — 直接写入，崩溃=文件截断
CONFIG_FILE.write_text(content, encoding="utf-8")

# GOOD — 原子写入，崩溃=临时文件残留，原文件不变
tmp = CONFIG_FILE.with_suffix(".tmp")
tmp.write_text(content, encoding="utf-8")
tmp.replace(CONFIG_FILE)
```

### 例外规则

| 文件类型 | 是否需原子写入 | 理由 |
|---------|--------------|------|
| 配置/状态文件 | ✅ 必须 | 崩溃导致整个系统不可读 |
| 运行数据文件 | ✅ 推荐 | 当日数据丢失不影响次日 |
| 归档/日志文件 | ❌ 可选 | 丢失当条日志不影响运行 |
| JSONL 追加行 | ❌ 不适用 | append 模式，不截断 |

### 本系统已修复的实例

| 文件 | 原写法 | 修复 | 修复轮次 |
|------|--------|------|---------|
| `sentiment_redline_monitor.py:save_config()` | 双写两路径 + 直接 write_text | 单写 + tmp+replace | R2 |
| `ignition_v1_sniper.py:record_position()` | active_positions.json 直接 write_text | tmp+replace | R2 |
| `agy_evolution_audit.py` | evolution_{today}.json 直接 write_text | tmp+replace | R2 |

### 已确认正确使用 tmp+replace 的模块

| 模块 | 文件 | 确认方式 |
|------|------|---------|
| `market_regime.py` | market_regime.json | L373-375 已用 tmp+replace ✅ |
| `close_session_scan.py` | close-session-state.json | L79-81 已用 tmp+replace ✅ |
| `leader_universe_filter.py` | leader_universe.json | L254-256 已用 tmp+replace ✅ |
| `sentiment_redline_monitor.py` (修复后) | strategy_params.json | 已用 tmp+replace ✅ |

### 陷阱1：`now` 冻结导致等待秒数计算错误

```python
# ❌ 错误：main()开头的 now 被冻结，Phase 等待秒数永远基于启动时间
now = datetime.now()  # 假设 09:24:50
# ... 经过多个Phase耗时 15s ...
target = now.replace(hour=9, minute=25, second=5)
sleep_sec = (target - now).total_seconds()  # 永远 15s，实际只需要 0s！
```

**修复**：使用实时时间函数 `now_cst()`，每次计算等待秒数时重新获取当前时间。

### 陷阱2：retry 退避击穿上层 timeout

在早盘竞价等高时效场景中，MCP 调用的 retry 策略必须与父级 timeout 匹配：

```python
# ❌ 错误：恒定 timeout + 长 sleep 退避
# 8s + 5s + 8s + 10s + 8s ≈ 39s 击穿父级 30s 限制
for attempt in range(3):
    urlopen(req, timeout=8)  # 恒定
    time.sleep((attempt+1)*5)  # 5s, 10s

# ✅ 正确：递增 timeout + 快速退避
for attempt in range(3):
    cur_timeout = 8 + attempt * 4  # 8s → 12s → 16s
    urlopen(req, timeout=cur_timeout)
    time.sleep(attempt + 1)  # 1s, 2s
```

同时必须捕获 MCP JSON-RPC error 字段（`resp.get("error")`），否则服务端错误不会被 except 捕获。

#### ⚠️ 迭代修复陷阱（2026-09-07 实战教训）：
第一轮修复只把恒定 timeout 改为递增（8→12→16）并缩短退避（5→1, 10→2），但 retries=2（3次调用）总耗时仍然是 8+1+12+2+16 = **39s**，一秒钟没减少 → AGY 第二轮审计立刻戳穿并重新计算发现没解决本质问题。

正确做法：**同时降低 timeout 基数和 retries 次数**。最终方案：timeout=5, retries=1（2次调用），递增+3s（5s→8s），1s退避 → 最坏 5+1+8 = **14s**。

**⚠️ 综合迭代修复铁律（AGY多轮审计模式下）**：
当 AGY 指出一类问题（如"重试39s击穿父级30s"）而你改完后数值没变时，AGY会在下一轮立刻戳穿。为避免这种反复：
1. 修前先精确计算当前最坏耗时
2. 修后立即重新计算，确认数值确实变了，而不是"感觉上修了"
3. **调参时要同时调整多个维度**——只改退避不改基数（或只改基数不改retries次数）往往数值不变

**验证方法**（每次改完必须自己算一遍，等AGY戳穿就晚了）：
```python
attempts = retries + 1  # retries次重试=attempts次调用
timeouts = [base + i * increment for i in range(attempts)]
sleeps = [sleep_func(i) for i in range(retries)] + [0]
worst = sum(timeouts) + sum(sleeps)
assert worst < PARENT_TIMEOUT, f"最坏耗时{worst}s > 父级限制{PARENT_TIMEOUT}s"
```

### 陷阱3：cron 全局 timeout < 脚本实际生命周期

For scripts with `time.sleep()` waiting for a specific wall-clock time (e.g., wait until 09:29:55), the total lifecycle can exceed the cron scheduler's `script_timeout_seconds` (default 300s in config.yaml `cron.script_timeout_seconds`).

**诊断**：cron 日志 `"Script timed out after 300s"` + 脚本内部无异常捕获（因为进程被 SIGKILL）。

**修复**：
- 计算精确时间线并验证是否 ≤ `script_timeout_seconds`
- 必要时在 `config.yaml` 中 `cron.script_timeout_seconds` 从 300 改为 480+

**morning_master_orchestrator.py 时间线实例**（09:24:50 → 09:31:55 ≈ 425s）：
```
Phase0 (MCP预热): ~3s
Phase0.5 (策略参数): ~5s
Phase0.8 (调仓腾槽): ~5s  → 09:25:03
Phase1 (竞价扫描): 等09:25:05(~2s) + 30s → 09:25:35
Phase2 (弱转强扫描): sleep 5s + 30s → 09:26:10
Phase3 (闸门): 等09:29:55(~225s) + 120s → 09:31:55
总耗时: 425s > 300s ❌
```

### 陷阱4：`except: pass` 吞掉 JSON-RPC 服务端错误

```python
# ❌ 错误：只捕获网络异常，不检查 MCP 返回的错误
resp = json.loads(urlopen(req).read())
text = resp["result"]["content"][0]["text"]  # 若 resp 有 error 字段则 KeyError

# ✅ 正确：显式检查 error 字段
resp = json.loads(urlopen(req).read())
if "error" in resp:
    raise RuntimeError(f"MCP RPC Error: {resp['error']}")
```

### 陷阱4b：MCP response content 空列表 IndexError

即使 `resp` 没有 error 字段，`result.content` 也可能为空列表。`[{}]` 默认值在 `"content"` 键存在时不会被触发：

```python
# ❌ 错误：假设 content 至少有一个元素
text = resp.get("result", {}).get("content", [{}])[0].get("text", "{}")
# 当 content = [] 时，.get("content", [{}]) 返回 []（因为 "content" 键存在），然后 [0] → IndexError

# ✅ 正确：安全解析
contents = resp.get("result", {}).get("content", [])
text = contents[0].get("text", "{}") if contents else "{}"
```

### 陷阱4c：stderr 空指针（AttributeError）

当 `subprocess.run(capture_output=True, text=True)` 返回的 `p.stderr` 在某些极端情况下为 `None` 时：

```python
# ❌ 错误：p.stderr 可能为 None
print(f"  [stderr] {p.stderr.strip()[:200]}")  # AttributeError: 'NoneType'...

# ✅ 正确：空指针防御
print(f"  [stderr] {(p.stderr or '').strip()[:200]}")
```

这个模式同样适用于 `p.stdout` 的安全处理。

### 陷阱5：单位修改变量但未使用（死代码）

定义 `t1 = time.time()` 等打点变量后必须实际用于输出，否则成了死代码。每个 Phase 完成后输出 `d1 = time.time() - t1` 并记录到 timeline。

## 常见故障

见 reference 文档：symbol 归一化、BSE 迁移、ghost positions、intent 审批链路、news dedup、dual cron collission、数据源额度耗尽与腾讯直连三级容灾（`references/data-source-quota-exhaustion-fallback.md`）等。

## 后台进程故障排查

### 自动交易每日闭环与常驻守护审计

当用户询问系统是否能自动发现买卖点、下单、飞书通知、为何盘中脚本常驻，或每日是否形成闭环时，按 `references/daily-auto-trading-closure-audit.md` 执行跨源核验。必须区分进程常驻与业务活跃、候选通知与报单/成交通知、主链跑通与全支路闭环；不得仅凭 cron `last_status=ok` 或服务 `running` 下结论。

### intraday_proactive_trader.py 静默崩溃（P0 潜在）

**症状**：盘中用户收不到持仓止盈止损推送，但 cron job 正常运行。该脚本通常由用户级 systemd 服务常驻，30秒循环；PID属于瞬时运行状态，不应写成持久规则。

**P0 崩溃点**：`check_positions_guard()` 中第231行：
```python
# f-string 中 res.get(order_id, 已提交) 将 order_id 当作变量名
# → NameError: name 'order_id' is not defined
# → while True 的 except Exception 捕获（L393）但整轮跳过
```
此崩溃导致：
- 该标的卖出推送丢失
- 该标的自动卖单不执行
- 后续所有标的的止盈止损检查跳过
- **静默——用户不会收到错误通知**

**防护措施**：
1. 在 f-string 中搜索所有 `res.get(` — 确认第一个参数是字符串 `"key"` 不是变量名
2. 日常检查：`tail -100 /tmp/intraday_proactive_trader.log 2>/dev/null | grep "Error"`
3. 进程监控：`ps aux | grep intraday_proactive_trader | grep -v grep`

**修复**：`patch` 工具替换为 `res.get("order_id", "已提交")` + py_compile 验证

**参考文件**：`references/intraday-proactive-trader-fstring-nameerror.md`（完整复现步骤+全系统扫描结果）

### 双调度系统冲突：传统 crontab + Hermes cron 时区碰撞

详见 `references/dual-cron-timezone-collision.md`。

**典型场景**：用户在非交易时段（如晚上9点）收到"午后预警"类推送。

**根因**：传统 crontab 的系统时区是 UTC，但所有定时的小时字段是按 CST 意图编写的。`0 13 * * 1-5` 在 UTC 13:00（CST 21:00）运行，导致本该中午跑的脚本在晚上9点启动。

**核心发现**：`cron_heartbeat.py` 是唯一需要在传统 crontab 中保留的行。所有交易策略调度（包括 `direct_executor.py`）应统一走 Hermes cron 系统（使用 CST 时区的 `schedule` 字段）。

### 时效型信号链路延迟：扫描超时、轮询排队与成交归因

当信号/推送/下单晚数分钟，但 MCP 与券商柜台健康时，按 `references/time-critical-signal-pipeline-latency.md` 还原四段时间线：调度阶段、扫描写入/推送、候选事件、券商委托成交。优先检查“逐票串行评估击穿父级 timeout → 后续独立 cron 才补出信号”模式。

### 盘中有效买点漏报：静态池、字段契约与开盘量门槛

若事后5分钟K线能定位有效突破买点，但实时引擎连续输出零信号，按 `references/intraday-buy-point-miss-static-universe.md` 排查：竞价档案缺少可选评分字段导致提前退出、盘中仍只扫描盘前静态名单、开盘累计成交额误套全天绝对门槛。报告必须区分“全天无买点”“当前不可追”与“系统漏报此前买点”，并用真实运行产物给出 Before / After。

修复原则：独立逐票评估做有界并发；扫描成功后立即调用执行器形成闭环；父级 timeout 只增加冗余而非单独充当修复；删除冗余午后新仓扫描并保留早盘入场窗口门禁。必须用并发基准、调用顺序测试、超时不执行测试、午后零注入测试和 live cron 列表给出 Before/After 证据。

### 09:25 通知缺失：调度器队首阻塞与负决策静默

若09:25候选提示缺失，不得只看 cron `last_status=ok`。必须对齐计划时间、真实 Run Time、上游脚本 sleep 时间线、扫描候选数、风控批准数和最终注入数。长任务内部等待到开盘可能阻塞同一调度器上的09:25/09:26任务；正常扫描得到0候选也必须发送明确“非买入”通知，不能输出空 stdout 或 `wakeAgent=false`。识别候选、风控批准、成功注入必须分层统计，只有成功注入大于0才可称为买入候选。完整排查与验证见 `references/auction-notification-and-cron-head-of-line-blocking.md`。

### 09:25 连板错误归零：不能查询“今日涨停”

集合竞价结束时可以从实时行情拿到 `open/price/prev_close`，但问财/条件选股的“今日涨停、今日涨幅榜、连板数”宽表通常尚未完成开盘后刷新。若 `limit_up_scanner` 在09:25直接查询“今日涨停”，会只返回零散数据甚至空表，进而把真实一字连板错误打印成“首板0、二板0、三板+0”。

正确口径：
1. 读取最近交易日的本地 `ladder_YYYY-MM-DD.json`，得到昨日涨停池及昨日身位；
2. 对该池调用 `query_batch_data` 获取09:25实时 `price/open/prev_close`；
3. 用板块自适应涨停价函数判断是否以涨停价完成竞价；
4. 今日身位 = 昨日身位 + 1，未封涨停者从今日连板阵列剔除；
5. 09:30后再切回“今日涨停/涨幅榜”全市场扫描。

验证必须使用已知昨日天梯 + 实时竞价快照做 Before/After：错误路径显示0只；正确合成路径应恢复真实2板/4板/6板阵列。空结果在09:25应解释为“昨日涨停池无标的以涨停价完成竞价”，不能误报“MCP离线”。

### 双调度冲突修复后的频率审计（2026-09-15 AGY审计）

删除传统 crontab 后，Hermes cron 的某些 job 频率可能低于原 crontab：

| 场景 | 原频率(crontab) | Hermes cron频率 | AGY审计结论 |
|------|----------------|----------------|-------------|
| 盘中题材起爆扫描 | `*/5` | `*/10` | ❌ 不够 → 改回 `*/5` |
| 龙头监控(pm) | disabled(被遗忘) | disabled(被遗忘) | ❌ 盲区 → 重新激活 + 偏移2分钟 |
| direct_executor | `*/2` | (未迁移) | ✅ 迁移到 Hermes cron `*/2` |

**修复标准**：盘中急拉封板通常在 3-5 分钟内完成 → 起爆/龙头监控类扫描必须 `*/5` 或更快。同 topic 的不同脚本必须错峰至少 2 分钟

详见 `references/dual-cron-timezone-collision.md`——包含 R1 问题定位和 R2 迭代修复（direct_executor 迁移、leader-monitor-pm 重新激活、频率影响判定）。
