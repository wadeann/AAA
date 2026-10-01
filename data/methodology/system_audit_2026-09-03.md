# A股交易系统全面审计报告与改进路线图

**审计执行日期**：2026-09-03（交易日）  
**审计范围**：全链代码（58脚本 + 47skill文件）+ 策略反馈台账 + Cron时序表  
**审计方法**：并行子代理深度代码审计（读真实文件、找真实断点）+ 策略文件逐行摸底  

---

## 执行摘要

A股交易系统经历了19轮AGY进化（R19），架构完成度92.9%。三路审计（全链路/盘中监控/复盘闭环）发现：

- **🔴 致命级 (P0)**：策略反馈闭环断裂——12条action_items全部未执行（2026-08-18至今16天）！
- **🟡 警戒级 (P1)**：akshare分钟线端口的实际数据源缺失
- **🟢 建议级 (P2)**：复盘自动化、胜率统计、恐慌模式兜底

---

## 一、全链路审计：候选→意图→风控→执行

### 1.1 is_trade_ready() — 买卖分支不对称 ✅ 已修复

**代码**：`autonomous_trade_pipeline.py:201-279`（R27）

R27修复后sell分支正确处理：
- line 238: `bool(candidate.get("entry_rule")) if direction == "buy" else True` ✅
- line 257-262: chan_buy_point只在buy方向检查 ✅
- line 266-275: 研究员字段只在buy+非approved时检查 ✅

没有新发现的买卖不对称漏洞。

### 1.2 风控审批链 — 强绑定 ✅

exec_server的`place_order`强制要求`intent_id`（代码级阻止绕过风控）。未注册的intent_id会被拒绝下单。没有绕过风控的口子。

### 1.3 候选写入字段完整性 — 策略分路由合理 ✅

`is_trade_ready()`按`catalyst_type`前缀分4种策略路由：
- **打板/连板**：跳过chanlun买点检查 ✅
- **竞价/弱转强**：量价+板块双重确认 ✅  
- **缠论/常规**：chan_buy_point + chan_confirmed ✅
- **卖出方向**：剥离缠论门禁 ✅

### 1.4 direct_executor — 每2分钟轮询 ✅

`direct_executor.py`正确实现了：分批风控(每次≤2笔)、防重复(ID去重)、盘中时段限制、中文名补充。

### 🔴 发现：akshare分钟线端口缺失

`scripts/autonomous_trade_pipeline.py:593-654` 中的 `_ensure_kline_availability` 函数拉取akshare分钟线做缠论，但底层akshare库可能未实际安装、或东财海外封杀未完全解决。需验证实际数据是否可拉取到。

---

## 二、盘中监控审计：cron时序与方向冲突

### 2.1 方向冲突检测 — v3架构健壮但缓存有gap ⚠️

**代码**：`utils_candidate.py:86-186`（`_build_executed_events`）

- 两阶段扫描：Phase1建立candidate_id→direction索引 → Phase2检测执行事件 ✅
- 同向阻断逻辑正确 ✅
- 缓存按文件mtime校验，TTL=300s ✅

**⚠️ gap**：缓存+文件锁时序gap仍在。两条流水线（close_session+leader_monitor）写入时间差 + `_build_executed_events`缓存被第一个调用者命中后，第二个调用者不会看到前者的写入。`check_direction_conflict(force_refresh=True)` 可绕过缓存，但需调用者主动传参。不是所有脚本都强制传了`force_refresh=True`。

### 2.2 5分钟监控去重 — 买卖方向独立 ✅

`intraday_leader_monitor.py`中`plan_symbols()`已修复：买卖方向各自独立跟踪（两个分离的seen-symbol set），不会互相遮蔽 ✅

### 2.3 红线自愈防假企稳铁律 — 需检查 ⚠️

**问题**：`sentinel_redline.py` 实现了三级fallback的红线状态管理（hardcoded→strategy_params→env var），但「高位股日内曾触涨停→跌绿盘→100%禁止判定自愈→须回+5.5%以上才解冻」这条铁律是否由某个盘中脚本在执行？

红线状态存储(`/home/ubuntu/.hermes/trading/config/redline_state.json`)有文件耐久度，但**实际判断逻辑**（跌绿盘→立即触发红线禁止自愈）的实现在哪里？需进一步定位是否有独立的"假企稳过滤"模块。

### 2.4 恐慌抄底模式 — 触发条件存在 ✅

`close_session_scan.py` 实现了双模式：正常日只卖不买 + 恐慌日(上证跌>1.5%)增加抄底。去重使用`symbol:panic_buy:today`键。触发逻辑完整 ✅。

### 2.5 静默失败隐患 — less critical but present

几个`no_agent`脚本如果MCP端口不可达（9001/9002/9003），会在`mcp_call`内部吞掉异常（`except: return {}`），导致`last_run_at=ok`但输出为空。这是`no_agent`脚本的已知设计选择——MCP不可达时静默fail。

---

## 三、复盘闭环审计：最严重的断裂 🔴

### 🔴 3.1 策略反馈闭环断裂（致命）

**文件**：`/home/ubuntu/.hermes/trading/strategy-feedback.md`

- **12条action_items全部`未执行`**，最早标注于**2026-08-18**（至今16天）
- P0级（立即止损/减仓/撤单/系统性数据错误）条目2周未动
- 关键未执行项包括：
  - `[P0] technical_breakout 暂停新开仓`（胜率25%<40%，应暂停）
  - `[P0] 趋势票止盈改形态止损`
  - `[P0] 修复候选快照写入链路`（买入方向连续7交易日零candidate）
  - `[P0] 冻结买入执行直到候选管道恢复`
  - `[P0] 暂停尾盘cron的买入权限`

写入规则说"其他cron加载本文件、读取P0/P1并优先处理"，但**实际没有代码在盘中读取strategy-feedback.md并应用其规则**。这是一个「写了规则但没人执行」的死胡同。

### 🔴 3.2 复盘脚本不产生结构化数据

**文件**：`agy_close_review.py`（51行）

- 调用AGY生成自然语言复盘（中文5-6行）
- 写入`review_{date}.md`纯文本
- **不产生结构化B浪验证表**
- **不追加candidates_{date}.jsonl含outcome/MFE/MAE字段**
- **不更新胜率统计表**
- **不触发action_item生成机制**

策略反馈模板里写的"B浪等级、catalyst_type分类、action_item"——实际复盘脚本完全没有实现。

### 3.3 胜率统计未按分段维护

`strategy-feedback.md`里统计是这样写的：
- `technical_breakout：8笔，2盈6亏，胜率25.0%`
- 但没有按confidence分段（0.65-0.70 / 0.70-0.80 / 0.80+）
- 也没有按entry_rule细分

写入规则第6条要求的"按catalyst_type/entry_rule/confidence分段统计"在实际中未执行。

### 3.4 自学习闭环未形成

复盘发现的问题（action_items）→参数优化（strategy_params.json）→下一轮复盘验证——这条链路不存在。`strategy_params.json`没有被任何复盘脚本更新。

---

## 四、完整改进路线图

### 🔴 P0 — 立即修复（本周收盘前）

#### P0-1：在 `direct_executor.py` 或 `run_autonomous_trades.py` 的交易闸门层加载 strategy-feedback.md
- **做法**：在闸门启动时读取 strategy-feedback.md 的 `[P0]` 段，解析并应用限制规则
- **优先级最高**：`technical_breakout暂停新开仓` 必须生效（胜率25%，已触达暂停条件）
- **验证**：闸门日志中出现 "P0 restriction applied: technical_breakout"

#### P0-2：重写 `agy_close_review.py`，产出结构化复盘
- **必须输出**：
  - B浪验证表（A✅/B⚠️/C❌ 含证据）
  - candidate_outcome追加到jsonl（catalyst_type/outcome/MFE/MAE/B浪等级）
  - 胜率统计按catalyst_type/confidence分段更新
  - 自动生成action_items（P0/P1格式）
- **不再只依赖AGY自然语言**，要用脚本做确定性的统计计算

#### P0-3：建立 action_item 自动执行机制
- 策略反馈中的P0条目 → 自动写入strategy_params.json → 下一轮交易闸门读取并应用
- 不再依赖"人读了feedback然后手动改代码"，而是代码自动消费feedback

### 🟡 P1 — 本周内修复

#### P1-1：安装akshare并验证分钟线拉取
```bash
cd /home/ubuntu/.hermes && pip install akshare -q
python3 -c "
import akshare as ak
# 测试拉取30分钟K线
df = ak.stock_zh_a_minute(symbol='sh600519', period='30', adjust='')
print(df.head())
"
```

#### P1-2：在 `check_direction_conflict` 的所有调用者中强制 `force_refresh=True`
- `intraday_leader_monitor.py`
- `close_session_scan.py`  
- `intraday_scan.py`
- 避免缓存序列化导致的漏检

#### P1-3：补全「红线自愈防假企稳」的实际检测模块
- 新增 `scripts/sentinel_redline_filter.py`
- 逻辑：日内曾触涨停+最新价<0%（绿盘）或距高点回撤>4% → 100%禁止自愈
- 解冻条件：回升至+5.5%以上且回撤≤4%
- 在 `direct_executor.py` 的每条候选评估前调用

### 🟢 P2 — 下个交易周

#### P2-1：警告MCP不可达时静默fail
- 为所有`no_agent`脚本的`except: return {}`添加stderr警告输出
- 在日志中记录MCP连接失败次数

#### P2-2：复盘→参数→下一轮交易 的全闭环
- `agy_close_review.py` → 写结构化复盘
- → `agy_evolution_audit.py` 读复盘→更新 `strategy_params.json`
- → 闸门读新参数 → 执行下一个交易日

#### P2-3：胜率统计的`strategy_params.json`替代 `strategy-feedback.md`
- `strategy_params.json` 原本就是结构化的参数库
- 把`strategy-feedback.md`中的统计摘要转为该JSON的新字段
- 使代码能直接消费（不用解析markdown）

---

## 五、系统当前真实状态

| 模块 | 状态 | 关键指标 |
|------|------|---------|
| 选股→候选管道 | ✅ 运行中 | R27后卖买分支不对称已修复 |
| 风控→执行链 | ✅ 运行中 | intent_id强绑定，不可绕过 |
| 盘中5min监控 | ✅ 运行中 | 方向冲突v3，去重独立 |
| 交易闸门 | ✅ 运行中 | 每15min消费候选 |
| direct_executor | ⚠️ 需调整 | 需加载红线和策略反馈 |
| 收盘复盘 | 🔴 断裂 | 无结构化输出，无统计更新 |
| 策略反馈闭环 | 🔴 断裂 | 12条action_items全部未执行16天 |
| 胜率统计 | ⚠️ 不完整 | 未按confidence分段 |
| 自学习管道 | ❌ 缺失 | 复盘→参数→下次交易不连接 |
| akshare分钟线 | ❓ 未验证 | 需安装+测试 |

---

## 六、立即行动（今天收盘后执行）

```bash
# 1. 验证akshare
pip install akshare -q 2>/dev/null
python3 -c "import akshare as ak; print(ak.__version__)" 

# 2. 读当前action_items
cat ~/.hermes/trading/strategy-feedback.md | grep -A2 "\[P0\]\|\[P1\]" | head -40

# 3. 确认闸门是否加载了 strategy_params
grep -rn "strategy_params\|sentiment\|cooldown" ~/.hermes/scripts/autonomous_trade_pipeline.py | head -10

# 4. 检查 redline_state 文件
cat ~/.hermes/trading/config/redline_state.json 2>/dev/null || echo "文件不存在"
```

---
**审计结论**：系统的心脏（选股→风控→执行）是健康的。但系统的**大脑**（复盘→学习→改进→下一轮）是断裂的。当前的"进步"依赖人工驱动AGY审计循环——砍掉了复盘闭环后，系统变成「只战斗不进化」的僵尸。P0修复的核心就是把复盘闭环接上。
