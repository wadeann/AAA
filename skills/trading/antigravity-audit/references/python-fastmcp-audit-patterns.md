# Python FastMCP 服务审计常见模式库（pup-mcp 审计实战记录）

> 基于 2026-09-07 pup-mcp 服务层（exec_server/intel_server/risk_server）两轮 AGY 审计实战。10项验证全部闭环通过。

---

## 🔴 致命模式（Critical）

### 1. 明文 API Key 硬编码

```python
# 🚨 错误模式
import os
OpenAI(api_key="sk-or-v1-xxxxx3e48")  # 明文硬编码，git泄露风险

# ✅ 修复：环境变量注入
api_key = os.environ.get("OPENROUTER_KEY", "")
if not api_key:
    raise ValueError("OPENROUTER_KEY not set")
OpenAI(api_key=api_key)
```

**排查**：`grep -rn 'sk-[a-zA-Z0-9]\{20,\}' *.py` — 找所有 20+ 字符的 sk- 模式。

---

### 2. SQL 注入 via f-string 拼接 LIKE

```python
# 🚨 错误模式
query = f"SELECT * FROM news WHERE title LIKE '%{keyword}%'"  # f-string直接拼接

# ✅ 修复：参数化查询
cursor.execute(
    "SELECT * FROM news WHERE title LIKE ?",
    (f"%{keyword}%",)
)
```

**排查**：`grep -n 'f".*LIKE\|f'\''.*LIKE\|\.execute(f' *.py` — 找所有 f-string 拼接的 execute 调用。

---

### 3. 撤单不恢复持仓/成本（状态丢失）

exec_server 中最容易出错的地方。撤单不是简单"取消订单"——如果部分成交过（T+1限制），或全撤但已记录持仓变动，必须回滚：

```python
# 🚨 错误模式：只撤单，不恢复 state
def cancel_order(self, order_id):
    # 只标注订单 CANCELLED，不碰持仓
    conn.execute("UPDATE orders SET status='CANCELLED' WHERE order_id=?", (order_id,))

# ✅ 修复：根据 direction 回滚持仓
def cancel_order(self, order_id):
    with self._lock:
        conn = self.db_session()
        order = conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone()
        if not order or order.status != "PENDING":
            return {"error": "not found or not pending"}
        
        if order.direction == "BUY":
            # BUY撤单：恢复冻结资金，减少持仓
            conn.execute("UPDATE positions SET quantity = quantity - ?, cost_price = ? WHERE symbol=?",
                        (order.order_quantity, orig_cost, order.symbol))
            conn.execute("UPDATE balances SET cash = cash + ?", (order.order_price * order.order_quantity,))
        elif order.direction == "SELL":
            # SELL撤单：恢复股票数量
            conn.execute("UPDATE positions SET quantity = quantity + ? WHERE symbol=?",
                        (order.order_quantity, order.symbol))
        
        conn.execute("UPDATE orders SET status='CANCELLED' WHERE order_id=?", (order_id,))
```

**排查**：检查撤单路径 → 是否更新了 positions/balances 表。

---

### 4. Intent 核销时序错误（双花攻击）

```python
# 🚨 错误模式：先执行下单，再核销 intent
def place_order(self, intent_id, symbol, direction, quantity, price):
    order_id = self.execute_order(symbol, direction, quantity, price)  # 先执行
    self.consume_intent(intent_id, quantity)  # 后核销 ← 如果中间崩溃，intent永不消耗

# ✅ 修复：先检查→核销→再执行（原子化）
def place_order(self, intent_id, symbol, direction, quantity, price):
    with self._lock:
        # 1. 检查 intent 可用额度
        affected = conn.execute(
            "UPDATE intents SET max_quantity = max_quantity - ? WHERE intent_id = ? AND max_quantity >= ?",
            (quantity, intent_id, quantity)
        ).rowcount
        if affected == 0:
            return {"error": "intent exhausted"}
        
        # 2. 清理全量消耗的intent
        conn.execute("DELETE FROM intents WHERE intent_id = ? AND max_quantity <= 0", (intent_id,))
        
        # 3. 再执行下单
        order_id = self.execute_order(symbol, direction, quantity, price)
```

**关键**：`WHERE max_quantity >= ?` 是原子检查锁——防止并发时多次消费同一 intent。

---

## 🟡 中危模式（Medium）

### 5. 并发锁只覆盖部分事务

```python
# 🚨 错误模式：锁覆盖不全
self._lock = threading.Lock()
def place_order(self, ...):
    with self._lock:
        conn = connect()  # 创建连接
        # ...事务逻辑
    conn.close()  # 锁释放后才关闭 ← 此时可能有其他线程用了同一个连接

# ✅ 修复：锁覆盖完整连接生命周期
def place_order(self, ...):
    with self._lock:
        conn = connect()
        try:
            # ...事务逻辑
        finally:
            conn.close()  # 锁内关闭
```

**排查**：搜索 `with self._lock:` → 检查 `conn.close()` 是否在锁内。

---

### 6. 订单 ID 重复（毫秒级精度不足）

```python
# 🚨 错误模式：毫秒级时间戳
order_id = f"ORD{int(time() * 1000)}"  # 同一毫秒内重复

# ✅ 修复：时间戳 + 随机后缀
import uuid
order_id = f"ORD{int(time() * 1000)}_{uuid.uuid4().hex[:6]}"
```

---

### 7. N+1 查询 for 持仓名称补全

```python
# 🚨 错误模式：每个持仓独立 HTTP 请求
for pos in positions:
    data = requests.get(f"{API}/query_data?symbol={pos.symbol}").json()
    pos.name = data.get("name")

# ✅ 修复：批量查询
symbols = [p["symbol"] for p in positions]
batch = self._call_intel("query_batch_data", {"symbols": symbols})
name_map = {item["symbol"]: item.get("name", "") for item in batch.get("data", [])}
for pos in positions:
    pos.name = name_map.get(pos.symbol, pos.symbol)
```

**排查**：`grep -n 'query_data.*symbol' *.py` — 找循环中逐个调用 query_data 的模式。

---

### 8. 涨跌停阈值硬编码

```python
# 🚨 错误模式：硬编码 10%
if price > prev_close * 1.10:
    return {"error": "reached limit up"}

# ✅ 修复：根据板块动态计算
def _get_limit_rates(self, symbol):
    if symbol.startswith("688") or symbol.startswith("300"):
        return 0.20  # 科创/创业 20%
    if symbol.startswith("920"):
        return 0.30  # 北交所 30%
    return 0.10  # 主板 10%

limit = prev_close * (1 + self._get_limit_rates(symbol))
```

---

### 9. 敏感端点未从 tools/list 隐藏

```python
# 🚨 错误模式：内部端点暴露给所有客户端
@server.tool()
async def register_approved_intent(...):
    pass  # 这个端点应仅 risk_server 调用

# ✅ 修复：从 tools/list 移除，保留 tools/call 路由
# FastMCP: 从 tools 列表移除
# REST: 不注册到 openapi 文档，但保留路由处理
```

**排查**：在 `@server.tool()` 列表中寻找管理类/内部类端点 → 评估是否应暴露。

---

### 10. HTTP DELETE 端点未移除

许多 FastMCP 服务会从旧 REST 框架迁移，残留不必要的 DELETE 端点：

```python
# 🚨 错误模式：无用 DELETE 端点
@server.tool()
async def delete_something(id: str):
    # 实际上由 POST 覆盖
    pass  # 保留无意义

# ✅ 修复：移除
```

**排查**：`grep -n 'DELETE\|\.delete\b' *.py`。

---

## 🔵 低危模式（Low）

### 11. API Key 为空时引发异常

当 LLM 分析功能依赖环境变量 API Key 时，不应在 import 时崩溃：

```python
# ✅ 优雅降级
try:
    self.client = OpenAI(api_key=os.environ.get("OPENROUTER_KEY", ""))
    if not self.client.api_key:
        self.enabled = False
except Exception:
    self.enabled = False

def analyze(self, text):
    if not self.enabled:
        return {"summary": "LLM disabled (no API key)"}
```

---

### 12. Accept-Encoding: gzip 但未解压

Python `urllib.request` + 自定义 `Accept-Encoding` 头时，需要手动解压：

```python
# ✅ 修复
import gzip, io

resp = urlopen(req)
content = resp.read()
if resp.headers.get("Content-Encoding") == "gzip":
    content = gzip.decompress(content)
```

---

### 13. 北交所代码前缀变更

北交所代码 2026 年全量迁移至 `920` 前缀。老的 `43xxx`/`83xxx`/`87xxx` 映射需更新：

```python
# ✅ 修复：优先匹配 920 前缀
if code.startswith("920"):
    return f"bj{code}"
if code.startswith(("43", "83", "87", "82")):
    return f"bj{code}"
```

**排查**：`grep -n 'startswith.*\"43\"\|startswith.*\"83\"' *.py`。

---

## AGY 审计流程（Python 服务版）

### 首轮审计清单

```
1. 安全审计
   [ ] 明文 API Key / Token
   [ ] SQL 注入（f-string/format拼接）
   [ ] 命令注入
   [ ] 敏感端点暴露

2. 并发审计
   [ ] 锁覆盖线程安全状态
   [ ] 原子读-改-写
   [ ] intent双花攻击

3. 状态一致性
   [ ] 撤单回滚持仓 + 成本
   [ ] 订单 ID 唯一性
   [ ] 部分成交 + T+1 约束

4. 性能
   [ ] N+1 查询
   [ ] 无缓存热点
   [ ] 超时控制

5. 业务规则
   [ ] 涨跌停动态计算
   [ ] 北交所代码映射
   [ ] 板块/市场类型区分
```

### Before/After 对比验证

每项 P0/P1 修复后，提供：

```bash
# 1. 语法验证
python3 -c "compile(open('exec_server/main.py').read(), 'exec_server/main.py', 'exec'); print('OK')"

# 2. 专项检查脚本输出变化
grep -c 'WHERE max_quantity>=' exec_server/main.py  # 确保原子消费

# 3. 功能运行
python3 -c "from exec_server.main import app; print('import OK')"
```

---

## 参考

- `antigravity-audit` skill 的 `SKILL.md`：AGY 审计全流程
- `references/rust-security-audit-patterns.md`：Rust 安全模式（路径穿越、SSRF 等 CWE）
---

## 第三轮审计新增模式 (2026-09-08)

以下4种模式来自pup-mcp intel深层模块第3轮AGY审计。72.2%修复通过率后AGY发现的新一批可重复模式。

### 19. 回退字典缓存无maxsize淘汰（OOM风险）

`cachetools` 可选依赖但回退到普通 `dict` 时，必须实现容量上限淘汰：

```python
# 🚨 错误模式：可选依赖回退后无界增长
try:
    from cachetools import TTLCache
    HAS_CACHETOOLS = True
except ImportError:
    HAS_CACHETOOLS = False
    # 回退到普通 dict，无容量限制 ← 长期运行OOM
def _set_cache(self, key, val, ttl):
    if HAS_CACHETOOLS:
        self._cache[key] = val  # 非线程安全
    else:
        with self._lock:
            self._cache[key] = (time.time() + ttl, val)  # 无界

# ✅ 修复：回退路径实现maxsize淘汰 + 全局锁
CACHE_MAXSIZE = 1000
def _set_cache(self, key, val, ttl):
    if HAS_CACHETOOLS:
        with self._lock:
            self._cache[key] = val
    else:
        with self._lock:
            if len(self._cache) >= CACHE_MAXSIZE:
                sorted_items = sorted(self._cache.items(), key=lambda it: it[1][0])
                for k, _ in sorted_items[:max(1, len(sorted_items) // 3)]:
                    del self._cache[k]
            self._cache[key] = (time.time() + ttl, val)
```

**排查**：`grep -n 'except ImportError' *.py` 检查每个 `TTLCache` fallback。

### 20. SSE流式数据缓冲区覆盖与单行JSON解析

多个 `data:` 事件必须独立累积，且格式化JSON跨行时需按完整事件块解析：

```python
# 🚨 SSE事件覆盖+单行解析
# 解析时逐行尝试（格式化JSON跨行必失败）
for line in sse_text.splitlines():
    try:
        parsed = json.loads(line)  # 多行JSON → JSONDecodeError
    except Exception:
        continue

# ✅ 按完整SSE事件分块
def _accumulate_sse(self, resp):
    events = []
    current_event = ""
    for chunk in resp.iter_lines():
        if not chunk: continue
        line = chunk.strip()
        if line.startswith("data:"):
            if current_event: events.append(current_event)
            current_event = line[5:].strip()
        else:
            current_event += "\n" + line
    if current_event: events.append(current_event)
    return events
```

### 21. SingleFlight超时后多线程惊群并发重试

先行线程超时后N个等待线程必须互斥，否则同时执行fetch打垮后端：

```python
# 🚨 超时后所有线程同时执行 fetch
if wait:
    event.wait(timeout=18.0)
    del self._inflight[key]
    result = fetch_func(...)  # N线程同时进入

# ✅ fallback_lock互斥
self._fallback_lock = threading.Lock()
if wait:
    event.wait(timeout=18.0)
    del self._inflight[key]
    with self._fallback_lock:
        # 二次校验
        if key in self._cache: return self._cache[key]
        result = fetch_func(...)
        self._cache[key] = (result, time.time() + ttl)
```

### 22. 页面类型不同的表格解析器不可复用

同花顺个股资金流 vs 板块概念/行业页面列结构完全不同：

```python
# 🚨 个股解析器用于板块页面 → float('5.59%') ValueError → 全行丢弃
# ✅ 分离解析器：_parse_stock_table() + _parse_sector_table()
```

**排查**：搜索 `10jqka.com.cn/funds/gnzjl/` → 检查调用的解析函数是否兼容。

### 24. dict.get 占位符陷阱（key存在但值为'-'）

`dict.get('f62', 0)` 仅在key**不存在**时返回默认值。当东财API返回 `{'f62': '-'}` 时，`.get('f62', 0)` 返回 `'-'`，`float('-')` 抛出未捕获 `ValueError`：

```python
# 🚨 错误模式
float(data_list[0].get('f62', 0))
# 当 f62='-' 时：float('-') → ValueError

# ✅ 修复：安全转换辅助函数
def safe_float_div(val, divisor=1.0):
    if val is None or val == '' or val == '-':
        return 0.0
    try:
        return round(float(val) / divisor, 2)
    except (ValueError, TypeError):
        return 0.0
```

**排查**：搜索 `\.get\(.*, .*\).*float` — 所有通过 `.get()` 取值后直接 `float()` 转换的调用点。

### 25. 缓存"半对称锁"模式（read无锁/write有锁）

`_get_cache` 和 `_set_cache` 的锁保护不一致。最容易被AGY审计漏掉的模式是 `HAS_CACHETOOLS` 分支在 _get_cache 未加锁但 _set_cache 已加锁：

```python
# 🚨 错误模式：get未保护，set已保护
def _get_cache(self, key):
    if HAS_CACHETOOLS:
        return self._cache.get(key)  # 无锁！读TTLCache非线程安全
    with self._lock:
        ...

def _set_cache(self, key, val, ttl):
    if HAS_CACHETOOLS:
        with self._lock:
            self._cache[key] = val  # 有锁
    else:
        with self._lock:
            ...

# ✅ 修复：把with self._lock提到最外层
def _get_cache(self, key):
    with self._lock:
        if HAS_CACHETOOLS:
            return self._cache.get(key)
        ...
```

**排查**：找到所有 `HAS_CACHETOOLS` / `IMPORT_CACHE` fallback 模式 → 检查 `_get` 和 `_set` 的锁覆盖是否对称。

### 26. SSE修复的二次返回类型断裂模式（AGY审计可复现陷阱）

当AGY审计指出 `_accumulate_sse` 返回 `str` 但解析用了 `splitlines()` 时，修复者的第一反应是改成 `return "\n".join(events)` 但仍返回 `str`，调用方再用 `splitlines()` 打碎。**两阶段连环bug**：

阶段1（原始bug）：SSE多行JSON被跨行切割，单行json.loads失败
阶段2（R3修复但引入新bug）：`_accumulate_sse` 返回 `"\\n".join(events)`（仍是str），call_tool 用 `sse_text.splitlines()` 再次切分多行JSON → 跨行JSON块被切成碎片所有json.loads失败
阶段3（正确修复）：`_accumulate_sse` 返回 `List[str]`（每个元素是完整事件），直接迭代列表，禁用splitlines

**排查**：如果 `_accumulate_sse` 的调用方有 `.splitlines()` → 说明返回类型应该是 `List[str]` 而非 `str`。

### 27. 跨数据源网页解析器复用导致列索引灾难

同一个网站（同花顺）的个股资金流（ggzjl）和概念/行业资金流（gnzjl/hyzjl）表格列结构不同。复用 `_parse_table()` 后：

```python
# 个股表：code, name, price(%), change, turnover, inflow, outflow, net, amount
# 概念表：rank, name, index_price(点位), change_pct(%), inflow, outflow, net
#
# 🚨 个股解析器用在概念表上：
# clean_cells[3] = 涨跌幅百分比 '5.59%' 但被当作 'price'
# clean_cells[6] = 净额(亿) 但个股表里是第9列
# 结果：净流入被错误解析为涨跌幅数值的百分比之和！

# ✅ 修复：分离解析器，各自定义列的偏移量
def _parse_stock_table(html): ...
def _parse_sector_table(html): ...
```

**排查**：搜索 `10jqka.com.cn` 及其子路径 → 对 `ggzjl`（个股）和 `gnzjl`（概念）/ `hyzjl`（行业）分别检查调用的是哪个解析器。

### 23. 金额字符串隐式单位误判

表头已标"亿元"时，单元格纯数字不应再额外除以1亿：

```python
# ✅ 三元分支：亿→原值 万→/10000 纯数字小→原值 纯数字大→/1e8
def parse_amount(text):
    match = re.search(r'(-?\d+\.?\d*)', text)
    if match:
        num = float(match.group(1))
        if '亿' in text: return num
        elif '万' in text: return num / 10000
        return num / 100000000 if abs(num) >= 10000 else num
    return 0.0
```

**排查**：搜索 `parse_amount` 或 `100000000` → 确认有单位判断分支。
