# Execution Flow — 交易执行流程

## 完整执行流水线

```
                    ┌─────────────────────────┐
                    │  Discovery Modules      │
                    │  (full_market_discovery │
                    │   leader_monitor        │
                    │   auction_scanner       │
                    │   dragon_screener)      │
                    └───────────┬─────────────┘
                                │ candidates_{date}.jsonl
                                ▼
                    ┌─────────────────────────┐
                    │  direct_executor.py     │ ← cron: * * * * 1-5
                    │  main()                 │
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │  1. reconcile_pending   │
                    │     _orders()           │ R37: 超时撤单+成交确认
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │  2. load_candidates()   │
                    │     load_processed_ids()│ JSONL 候选去重
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │  3. Filter pipeline     │
                    │    ├─ is_catalyst_enabled│
                    │    ├─ _check_direction   │
                    │    │   _conflict (T+1)   │
                    │    ├─ sell_only_mode     │
                    │    │   gate               │
                    │    ├─ sentiment filter   │
                    │    │   (cooldown/ice)     │
                    │    └─ blocked_sectors    │
                    └───────────┬─────────────┘
                                │ ready candidates (max 2/batch)
                                ▼
                    ┌─────────────────────────┐
                    │  4. For each candidate  │
                    │    ├─ query_data (MCP)  │
                    │    ├─ iron_rule_gate()  │ AGY 铁律 4 道门禁
                    │    ├─ cond_eval()       │ 条件求值器 (R36)
                    │    └─ position sizing   │ 仓位计算
                    └───────────┬─────────────┘
                                │ normalized intent
                                ▼
                    ┌─────────────────────────┐
                    │  5. risk_check_and_exec │
                    │     _ute()              │ pipeline.py
                    └───────────┬─────────────┘
                                │ intent list
                                ▼
                    ┌─────────────────────────┐
                    │  6. RiskManager         │
                    │     batch_check()       │ 13 层风控 + 注册
                    └───────────┬─────────────┘
                                │ approved/rejected
                                ▼
                    ┌─────────────────────────┐
                    │  7. Snapshot check      │
                    │    ├─ cash sufficiency  │
                    │    ├─ position limit    │
                    │    └─ T+1 sell check    │
                    └───────────┬─────────────┘
                                │ approved intents
                                ▼
                    ┌─────────────────────────┐
                    │  8. Execute             │
                    │    ├─ register_approved  │
                    │    │   _intent() (MCP)   │
                    │    └─ place_order()     │
                    │       (MCP exec:9003)   │
                    └───────────┬─────────────┘
                                │ order result
                                ▼
                    ┌─────────────────────────┐
                    │  9. Post-execution      │
                    │    ├─ write JSONL event │
                    │    ├─ Feishu notify     │
                    │    └─ shadow candidate  │
                    └─────────────────────────┘
```

---

## 各步骤详情

### Step 1: reconcile_pending_orders()
- **File**: `execution/direct_executor.py:299`
- **What**: R37 挂单管理
  - 09:29:55 竞价未撮合撤单
  - 价格偏离 > 1.5% 撤单
  - 挂单超 5 分钟撤单
  - 今日成交回报写入 JSONL

### Step 2: load_candidates()
- **File**: `data/__init__.py:78`
- **What**: 从 `candidates_{today}.jsonl` 读取候选
  - 合并 candidate + llm_review 更新记录

### Step 3: Filter Pipeline
- **File**: `execution/direct_executor.py:446-566`
- **What**: 多层过滤
  - 已处理 ID 去重
  - AGY/LLM 审核状态检查
  - 催化剂冷却检查
  - T+1 方向冲突
  - sell_only_mode 硬卡口
  - 情绪周期 cooldown/ice 精细化防守
  - 板块级定向隔离

### Step 4: Per-Candidate Processing
- **File**: `execution/direct_executor.py:587-740`
- **What**:
  - 实时行情获取 (query_data MCP 9001)
  - AGY 铁律门禁 (`core/market_regime_check.py:iron_rule_gate`)
  - 条件求值器 (`condition_evaluator.evaluate_all`)
  - 仓位计算 (position sizing)
  - normalize_intent → TradeIntent

### Step 5: risk_check_and_execute()
- **File**: `execution/pipeline.py:298`
- **What**: 风险检查 + 执行入口
  1. 交易时段检查 (MCP get_trading_sessions)
  2. RiskManager.batch_check (MCP 9002)
  3. AGY fallback (风险服务器不可用时)
  4. 账户快照检查 (现金/持仓)
  5. 注册 → 下单 → 飞书通知

### Step 6: RiskManager.batch_check()
- **File**: `risk/risk_manager.py:461`
- **What**: 13 层风控 + 注册
  - 详见 `risk_tree.md`
  - 通过后自动注册到 exec MCP

### Step 7: Snapshot Check
- **File**: `execution/pipeline.py:406-456`
- **What**: 实时快照校验
  - 现金充足性 (cost vs available_cash)
  - 持仓数量限制 (max 5)
  - T+1 卖出可用股数

### Step 8: Execute
- **File**: `execution/pipeline.py:460-499`
- **What**:
  1. `client.register_approved_intent()` (MCP 9003)
  2. `client.place_order()` (MCP 9003)
  3. 写入 order result

### Step 9: Post-execution
- **File**: `execution/direct_executor.py:781-796`
- **What**:
  1. JSONL event 记录 (executed/risk_blocked/position_limit_rejected)
  2. Feishu trade notification
  3. Shadow candidate tracking

---

## 异常处理

| 异常场景 | 处理方式 | 位置 |
|----------|----------|------|
| 风险服务器超时 | 重试 4 次 (1/2/4s backoff) → AGY fallback | pipeline.py:322-346 |
| 非交易时段 | AGY approved 候选可执行 | pipeline.py:314 |
| 注册失败 | skipped 列表 | pipeline.py:475 |
| 下单异常 | execution_status = failed | pipeline.py:489 |
| 飞书通知失败 | logging.error (不阻断) | pipeline.py:502-514 |
| 可用股数不足 | temporary_insufficient_shares | direct_executor.py:681 |
| 仓位配额不足 | position_limit_rejected | direct_executor.py:711 |
