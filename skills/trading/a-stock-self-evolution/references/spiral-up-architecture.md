# 螺旋上升架构改造记录 2026-08-28

## 背景

进化审计→执行闭环断裂：16条P0/P1 action_items，10天仅执行1条（6.25%执行率）。
系统进入"审计空转 + 样本饥饿死锁"状态：
- is_trade_ready 堆叠10+一票否决条件 → 通过率归零 → 0交易 → 0样本 → 进化引擎熄火
- 违规后门穿透：08-21尾盘无候选买入金山办公（浮亏）
- 08-27/28 进化审计输出为空（outcome_samples=0）

## 改造1：策略动态参数状态机

### 文件
- `~/.hermes/trading/config/strategy_params.json` — 存储各 catalyst_type 的 enabled/cooldown/win_rate

### 架构
evolution_audit.py → 写入 JSON 补丁到 strategy_params.json（代替纯文本 action_items）
autonomous_trade_pipeline.py → load_strategy_params() + is_catalyst_enabled() 热加载
run_autonomous_trades.py → 闸门运行时引用 strategy_params 动态阈值

### 状态机迁移规则
- 样本≥5 且 胜率<40% → enabled=false + cooldown=7天后
- 样本≥5 且 胜率≥60% → enabled=true + cooldown=null
- 样本<5 → 不调整（观察状态）

**首次初始化注意事项**：AGY 创建的 strategy_params.json 全部 `win_rate: null, sample_count: 0`。
需要人工补录已知历史数据：
- technical_breakout: n=8, wr=0.25, enabled=false, cooldown="2026-09-05"
- sector_rotation: n=6, wr=0.667, enabled=true, cooldown=null

### 运行时验证（2026-08-28）
```python
params = load_strategy_params()
is_catalyst_enabled("technical_breakout", params)  # → False（冷却中）
is_catalyst_enabled("sector_rotation", params)      # → True
```

## 改造2：影子追踪管道（Shadow Pipeline）

### 目的
破解"0交易→0样本→审计熄火"死锁。解耦信号层与实盘下单层。

### 架构
```
宽松信号（缠论买点+量确认） → shadow_candidate（record_type写入JSONL）
                                       ↓
                                  收盘后虚拟盈亏计算
                                       ↓
                                  evolution_audit 消费影子样本
```

### 关键函数（autonomous_trade_pipeline.py）
- `is_shadow_ready(candidate)` — 宽松判定：只要缠论买点+量确认即可
- `record_shadow_candidate(candidate)` — 写入 shadow_candidate 到 JSONL
- `load_shadow_candidates(date)` — 加载历史影子候选

### 运行机制
- run_autonomous_trades.py 在逐候选循环中，先检查 is_shadow_ready → 自动写 shadow_candidate（无论实盘闸门是否通过）
- evolution_audit.py 的 read_outcomes() 同时读取 candidate_outcome + shadow_outcome + shadow_candidate

### 运行时验证（2026-08-28）
```python
is_shadow_ready({
    'direction': 'buy', 'symbol': '000001.SZ', 'price': 10.0,
    'chan_buy_point': '二买', 'chan_confirmed': True, 'volume_confirmed': True
})  # → True
```

## 改造3：分层归因体系 + 网关硬防线

### 分层归因
- **Level 1（催化大类）**：catalyst_type → 控制策略大类开闭
- **Level 2（形态细粒度）**：chan_buy_point + volume_state → 控制细粒度打分
- 样本<10 时用 Empirical Bayes Shrinkage（先验收缩），防止小样本极端波动

### 网关硬防线
- risk_check_and_execute 底层：无 candidate_id 的 intent 直接拦截（gateway hard invariant），文件第440-442行
- run_autonomous_trades.py：sell_only_mode 激活时拦截所有买入 intent
- is_catalyst_enabled() 检查：禁用或冷却中的催化剂类型买入直接过滤

### 运行时验证（2026-08-28）
```python
# 分层归因
extract_attribution_layers({
    'catalyst_type': 'technical_breakout', 'chan_buy_point': '二买',
    'volume_confirmed': True, 'confidence': 0.75
})
# → {'level_1_catalyst': 'technical_breakout', 'level_2_pattern': '二买/vol_confirmed', 'confidence_band': '0.70-0.80'}

# 先验平滑
compute_empirical_bayes_win_rate(wins=1, sample_count=3, prior_win_rate=0.50, prior_weight=5.0)
# → 0.4375（原始33.3%向50%先验收缩）

# 分层聚合
hierarchical_attribution([
    {'catalyst_type': 'tech', 'chan_buy_point': '一买', 'volume_confirmed': True, 'outcome': 'win'},
    {'catalyst_type': 'tech', 'chan_buy_point': '二买', 'volume_confirmed': False, 'outcome': 'loss'},
    {'catalyst_type': 'sector', 'chan_buy_point': '二买', 'volume_confirmed': True, 'outcome': 'win'},
])
# → level_1: {tech: …, sector: …}, level_2: {tech::一买/vol_confirmed: …, …}
```

## 完整闸门验证（2026-08-28）

```python
from autonomous_trade_pipeline import is_trade_ready, is_catalyst_enabled

base_cand = {
    'direction': 'buy', 'symbol': '000001.SZ', 'price': 10.0, 'quantity': 100,
    'entry_rule': '中枢突破', 'thesis': '[缺口逻辑]技术突破形态确认',
    'chan_buy_point': '二买', 'chan_confirmed': True, 'volume_confirmed': True,
    'confidence': 0.70, 'leader_score': 60,
    'sector_confirmed': True, 'fundamental_confirmed': True,
    'realtime_confirmed': True, 'news_confirmed': True,
    'risk_approved': True,
}

# sector_rotation 正常放行
is_trade_ready(dict(base_cand, catalyst_type='sector_rotation'))     # → True ✅

# technical_breakout 被冷却拦截（enabled=false, cooldown 7天）
is_trade_ready(dict(base_cand, catalyst_type='technical_breakout'))  # → False ✅
```

## is_trade_ready 调试备忘

`is_trade_ready` 返回 False 时，最常见的遗漏字段（按排查优先级）：

| 优先级 | 字段 | 预期值 | 备注 |
|:--|:--|:--|:--|
| P0 | `risk_approved` | `True` | require_risk 默认 True |
| P0 | `thesis` | `"[缺口逻辑]" + 至少12字符` | 或 `llm_approved=True` 跳过 |
| P0 | `direction` | `"buy"` / `"sell"` | 大小写敏感 |
| P1 | `volume_confirmed` | `True` | 仅买入强制 |
| P1 | `quantity` | ≥100 | 整数 |
| P1 | `entry_rule` | 非空字符串 | 如 "中枢突破" |
| P1 | `sector_confirmed` | `True` | 仅买入 |
| P2 | `catalyst_type` | 存在的策略名 | `"default"` 保底 |

闸门检查是17项 ALL AND：10项基础 + 6项买入额外 + 1项风险。任何一项 False 都返回 False。

## 文件完整性总结

| 文件 | 行数 | 关键函数 |
|:--|:--|:--|
| `autonomous_trade_pipeline.py` | 492 | load_strategy_params, is_catalyst_enabled, is_shadow_ready, record_shadow_candidate, load_shadow_candidates, extract_attribution_layers, compute_empirical_bayes_win_rate, hierarchical_attribution, risk_check_and_execute(candidate_id硬防线) |
| `evolution_audit.py` | 175 | read_outcomes(含shadow), main(写入strategy_params.json) |
| `run_autonomous_trades.py` | 213 | is_shadow_ready调用, sell_only_mode, catalyst_enabled检查 |
| `strategy_params.json` | 82行 | 10个catalyst_types + global_guards |

## 未完成项 / 后续迭代

- `compute_shadow_outcomes()` 函数仅标记了基础信息，需要接入 MCP 实时行情来算真实虚拟盈亏
- 参数状态机的 cold_start 手动补历史数据问题需要自动化（evolution_audit 在无 outcome 时不更新配置，需手动 initial sync）
- AGY 通过 bash heredoc 注入代码的可靠性问题（见 SKILL.md 的 AGY 验证协议）
