# AGY全系统闭环审计模式（R37 实战记录）

> 本文件记录2026-09-07全系统闭环审计的四轮迭代经验，作为后续系统级审计的模板。

## 审计范围（六大流水线环节）

任何全系统闭环审计必须覆盖以下六个环节的**数据流完整性**——不是检查代码有没有，而是检查数据是否真实从前一环节流到后一环节：

| 序号 | 环节 | 核心问题 |
|:---:|:---|:---|
| 1 | **盘前扫描/候选生成** | 是否真实读取市场数据→生成candidate jsonl？candidate是否包含完整字段？ |
| 2 | **风控拦截（盘中）** | position_guard是否真的在买入前拦截？情绪周期(cooldown/ice)是否真正限制开仓？sell_only_mode是否真实触发？ |
| 3 | **下单执行** | 候选→intent注册→place_order链路是否完整？竞价核按钮是否独立触发？ |
| 4 | **成交确认与反馈** | 下单后是否确认FILLED？未成交挂单是否有清理机制？ |
| 5 | **收盘复盘与止损** | 是否读取候选+成交→生成复盘？是否处理未触及止盈止损的持仓？ |
| 6 | **每日策略参数自适应** | 胜率是否回写到params？黑名单是否每日更新？ |

## 评级标准

每个环节回答：
- 🔴 **断链**：环节不存在或关键步骤缺失
- 🟡 **弱链**：环节存在但数据流断裂（如生成candidate但没人下单）
- 🟢 **闭环**：数据流向下一环节

## 常见断链类型（来自R37审计实战）

### P0级致命断链

1. **孤魂脚本**：代码写得很好但没挂载到任何cron/调度器
   - 案例：`auction_kill_switch.py` 有一个完整的游资核按钮实现，但crontab和jobs.json中都没有它的条目，09:25黄金窗口完全失控
   
2. **审批死锁**：候选生成脚本硬编码`llm_approved: False`但系统没有配置LLM二审任务
   - 案例：`limit_up_scanner.py` 的连板候选全部被`is_llm_ready()`一票否决，连板战法100%哑火

3. **关键数据源端口混用**：query_data属于Intel MCP(9001)，但代码从Exec MCP(9003)调取
   - 后果：`cur_price`恒为0，价格偏离撤单完全瘫痪

4. **时序倒挂**：脚本在时间守卫开启前被调用
   - 案例：Phase0.9在09:24:53调`auction_kill_switch`，但它内部时间守卫设09:25:05，静默return 0

5. **假阻断**：风控打印了blocked但实际没有阻断后续执行流程
   - 案例：`position_guard`的blocked结果只被`print`，Phase1/2的买入扫描在else外面照跑不误

6. **字段名猜错**：`o.get("created_at")` 但实际MCP返回字段名是 `timestamp`
   - 案例：挂单超时5分钟的撤单逻辑因字段名错误永久失效

7. **数据格式未解包**：Intel MCP返回`{tables: [{columns: [...], rows: [[...]]}]}`表格格式，但代码直接用`.get("price")`
   - 后果：`q_data.get("price")`恒为None，现价取不到

8. **去重主键退化**：`dedup_append`按`symbol+type`去重导致多笔成交被覆盖
   - 案例：`candidate_id=""`时同一股票两次撤单/两笔成交互相吞噬

### P1级严重断链

9. **死代码**：脚本存在但全局没有任何代码调用它
   - 案例：`position_guard.py` 存在但无任何调度系统/执行脚本引用

10. **退潮期不拦截**：cooldown/ice阶段只在sent_multiplier缩仓但不硬阻断开仓
    - 案例：`direct_executor.py` 在cooldown阶段只是把仓位乘以multiplier，继续买入

11. **写死路径**：`CANDIDATES_DIR / "strategy-feedback.md"` 但真实文件在 `TRADING_ROOT / "strategy-feedback.md"`
    - 后果：黑名单自适应永远为False，低胜率策略无法自动熔断

12. **数据基准错误**：低开预警用成本价而非今日收盘价计算
    - 游资实战：低开永远是 (次日开盘价 - 昨日收盘价) / 昨日收盘价

### P2级

13. **防守卡缺失**：收盘复盘不输出隔夜持仓的量化防守位
14. **环境变量不统一**：`HERMES_MCP_DRY_RUN` vs `HERMES_DRY_RUN`

## 审计轮次迭代节奏

| 轮次 | 评分区间 | 典型发现的断链数 | 结论 |
|:----:|:--------:|:----------------:|:-----|
| R1初审 | 40-58 | 4-6个P0 + 3-5个P1 | 系统骨架优秀但多处断链 |
| R2复审 | 58-62 | 2-4个P0（新炸弹） | 浅层修复后暴露深层bug |
| R3三审 | 60-65 | 1-2个P0（缩进/格式/端口） | 核心逻辑没问题但工程细节炸 |
| R4终审 | 待定 | 视修复质量 | AGY签署或无P0残留 |

**关键发现**：每轮修复后AGY会从新的角度发现不同层面的问题——第一轮是架构断链，第二轮是时序和端口，第三轮是缩进和数据格式。这不是"修复不彻底"，而是AGY从不同深度逐步检查系统的自然过程。

## 时序修复模式（来自R37）

### 竞价核按钮正确调度模式

```python
# Phase 0.85: 等待竞价撮合
target = now_cst().replace(hour=9, minute=25, second=5)
sleep_sec = (target - now_cst()).total_seconds()
if sleep_sec > 0:
    time.sleep(sleep_sec)

# Phase 0.9: 核按钮带--force
subprocess.run([sys.executable, "auction_kill_switch.py", "--force"])

# Phase 0.95: 风控真阻断
p = subprocess.run([sys.executable, "position_guard.py"], capture_output=True, text=True)
guard_blocked = '"blocked": true' in p.stdout.lower()
if guard_blocked:
    # ⛔ 跳过Phase1/Phase2买入扫描
    ...
else:
    # Phase 1: 竞价扫描
    # Phase 2: 连板扫描
```

### 挂单撤单正确实现

```python
# 1. 从Exec MCP(9003)查挂单
orders = mcp_call_raw(9003, "get_orders", {})

# 2. 从Intel MCP(9001)查现价——绝不能混端口！
q_data = mcp_call_raw(9001, "query_data", {"symbol": sym})
q_flat = parse_mcp_quote(q_data)  # 解包表格协议
cur_price = float(q_flat.get("price", 0))

# 3. 字段名兼容
ts_str = o.get("timestamp") or o.get("created_at") or o.get("time") or ""

# 4. 预定义变量防UnboundLocalError
should_cancel = False
cancel_reason = ""
deviation = 0.0

# 5. UTC时区对齐
now_utc = dt.datetime.now(dt.timezone.utc)
ot = dt.datetime.fromisoformat(ts_str)
if ot.tzinfo is None:
    ot = ot.replace(tzinfo=dt.timezone.utc)

# 6. 唯一主键
"candidate_id": f"cancel-{sym}-{oid}"
"candidate_id": f"trade-{sym}-{dir}-{price}-{timestamp}"
```

## Intel MCP表格协议解析

```python
def parse_mcp_quote(q_data: dict) -> dict:
    """解包 Intel MCP query_data 表格格式 -> 平铺 dict"""
    if isinstance(q_data, dict) and "tables" in q_data:
        try:
            tbl = q_data["tables"][0]
            return dict(zip(tbl["columns"], tbl["rows"][0]))
        except (IndexError, KeyError):
            return {}
    return q_data if isinstance(q_data, dict) else {}
```

## sell_only_mode 三重检查模式

```python
sell_only = (
    strategy_params.get("sell_only_mode") is True  # 顶级键
    or strategy_params.get("global_guards", {}).get("sell_only_mode") is True  # 二级键
)
if not sell_only:
    rl_path = Path("~/.hermes/trading/config/redline_state.json")
    if rl_path.exists():
        rl = json.loads(rl_path.read_text(encoding="utf-8"))
        sell_only = rl.get("tripped") is True  # 红线状态
```
