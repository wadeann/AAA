# 风控决策树 (Risk Decision Tree)

Three-tier risk architecture: **Primary (13-layer RiskManager) -> Secondary (AGY Iron Rule Gate) -> Tertiary (Pipeline is_trade_ready)**

---

## Tier 1: RiskManager (13 layers)

**Source:** `/home/wade/workspace/ai/Astock/risk/risk_manager.py`

The order of execution differs by direction. For SELL, checks 1, 2, 10, 9, 13 run (in that order). For BUY, all 13 run.

### Execution Order

```
BUY:  symbol -> weekend -> st_blacklist -> position_cap -> market_crash -> outflow -> sentiment -> sector_conc -> total_exp -> avg_down -> tail_chase -> t1_rule -> freeze

SELL: symbol -> weekend -> st_blacklist -> t1_rule -> freeze
```

### Layer-by-layer

---

#### Layer 1: symbol -- Symbol Format Check

```
input: symbol (str)
        |
        +-- symbol is empty or not a string?
        |       YES -> BLOCK (symbol为空或非法)
        |
        +-- suffix missing (.SH / .SZ / .BJ / SH / SZ)?
        |       YES -> BLOCK (标的代码格式异常)
        |
        +-- numeric part not 6-digit?
        |       YES -> BLOCK (标的代码数字部分异常)
        |
        PASS
```

---

#### Layer 2: weekend -- Weekend + Holiday Check

```
input: (none, uses server time CST)
        |
        +-- weekday() >= 5 (Saturday/Sunday)?
        |       YES -> BLOCK (周末非交易日)
        |
        +-- _is_trading_day() returns False?
        |   (first tries MCP get_trading_sessions, 
        |    falls back to weekday < 5)
        |       YES -> BLOCK (非交易日/节假日)
        |
        PASS
```

---

#### Layer 3: position_cap -- Single Position <= 30%

```
input: symbol, direction, quantity, price
        |
        +-- direction != "buy"?
        |       YES -> PASS (sell skipped)
        |
        +-- total_assets <= 0?
        |       YES -> PASS (cannot check, pass through)
        |
        +-- (current_position_value + quantity * price) / total_assets > 0.30?
        |       YES -> BLOCK (单标仓位 > 30% 上限)
        |
        PASS
```

---

#### Layer 4: market_crash -- Market Health Score < 30

```
input: (none, fetches from MCP)
        |
        +-- health_score < 30?
        |       YES -> BLOCK (市场健康度 < 30, 触发大盘熔断)
        |
        +-- fetch fails?
        |       YES -> PASS (pass through)
        |
        PASS
```

---

#### Layer 5: outflow -- Main Capital Outflow < -800亿

```
input: (none, fetches 000001.SH fund flow)
        |
        +-- net_outflow < -80,000,000,000 (-800亿)?
        |       YES -> BLOCK (主力净流出 < -800亿, 拦截买入)
        |
        +-- fetch fails?
        |       YES -> PASS (pass through)
        |
        PASS
```

---

#### Layer 6: sentiment -- Sentiment Phase Check

```
input: (none, reads strategy_params.json)
        |
        +-- phase in ("ice", "cooldown") AND multiplier <= 0.3?
        |       YES -> BLOCK (情绪周期/系数过低, 禁止新开买入)
        |
        +-- load fails?
        |       YES -> PASS (pass through)
        |
        PASS
```

---

#### Layer 7: sector_conc -- Sector Concentration <= 40%

```
input: symbol, quantity, price
        |
        +-- sector info unavailable?
        |       YES -> PASS (放行)
        |
        +-- total_assets <= 0?
        |       YES -> PASS (放行)
        |
        +-- (sector_value + new_value) / total_assets > sector_max_concentration?
        |   (default 40%, loaded from strategy_params.json global_guards)
        |       YES -> BLOCK (板块集中度 > 上限)
        |
        PASS
```

---

#### Layer 8: total_exp -- Total Exposure <= 80%

```
input: direction, quantity, price
        |
        +-- direction != "buy"?
        |       YES -> PASS (sell skipped)
        |
        +-- total_assets <= 0?
        |       YES -> PASS (放行)
        |
        +-- (current_exposure + new_value) / total_assets > total_exposure_limit?
        |   (default 80%, loaded from strategy_params.json global_guards)
        |       YES -> BLOCK (总敞口 > 上限)
        |
        PASS
```

---

#### Layer 9: t1_rule -- T+1 Direction Conflict

```
input: symbol, direction
        |
        +-- symbol or direction missing?
        |       YES -> BLOCK (symbol/direction缺失)
        |
        Reads today's candidate_event records from JSONL
        Looks for last event(symbol) with status in
        (executed, submitted, submitted_unverified)
        |
        +-- no prior record for this symbol today?
        |       YES -> PASS
        |
        +-- last_dir == direction (same direction repeated)?
        |       YES -> BLOCK (T+1冲突: 今日已有同方向执行记录)
        |
        +-- direction == "sell"?
        |       +-- available_quantity > 0?
        |       |       YES -> PASS (有可用持仓, 允许卖出)
        |       |       NO  -> BLOCK (T+1冲突: 无可用持仓卖出)
        |
        +-- direction == "buy" (last_dir was "sell")?
        |       +-- has existing position?
        |       |       YES -> BLOCK (T+1冲突: 已有持仓禁止当日买入)
        |       |       NO  -> PASS (已卖完, 允许反手)
        |
        PASS
```

---

#### Layer 10: st_blacklist -- ST / *ST / 退市 / Blacklist

```
input: symbol, name
        |
        +-- name contains ST/*ST/退市/S*ST/SST?
        |       YES -> BLOCK (ST标的禁止交易)
        |
        +-- symbol in MCP blacklist?
        |       YES -> BLOCK (标的在黑名单中)
        |
        PASS
```

---

#### Layer 11: avg_down -- No Averaging Down

```
input: symbol, direction
        |
        +-- direction != "buy"?
        |       YES -> PASS (sell skipped)
        |
        +-- existing position with quantity > 0?
        |       YES -> BLOCK (禁止摊平: 已有持仓)
        |
        PASS
```

---

#### Layer 12: tail_chase -- No Chasing After 14:35

```
input: (none, uses server time CST)
        |
        +-- now_time >= time(14, 35)?
        |       YES -> BLOCK (尾盘追高拦截)
        |
        PASS
```

---

#### Layer 13: freeze -- Cooldown / Freeze Check

```
input: symbol
        |
        Reads freeze_state.json
        |
        +-- symbol in freeze dict AND today < frozen_until date?
        |       YES -> BLOCK (冻结至 <date>)
        |
        +-- load fails?
        |       YES -> PASS (pass through)
        |
        PASS
```

---

### BUY vs SELL Summary

| Layer | BUY | SELL |
|-------|-----|------|
| 1  symbol            | RUN | RUN |
| 2  weekend           | RUN | RUN |
| 3  position_cap      | RUN | SKIP |
| 4  market_crash      | RUN | SKIP |
| 5  outflow           | RUN | SKIP |
| 6  sentiment         | RUN | SKIP |
| 7  sector_conc       | RUN | SKIP |
| 8  total_exp         | RUN | SKIP |
| 9  t1_rule           | RUN | RUN  |
| 10 st_blacklist      | RUN | RUN  |
| 11 avg_down          | RUN | SKIP |
| 12 tail_chase        | RUN | SKIP |
| 13 freeze            | RUN | RUN  |

---

## Tier 2: iron_rule_gate (AGY铁律)

**Source:** `/home/wade/workspace/ai/Astock/core/market_regime_check.py`

Sell direction is **fully exempted** (returns PASS immediately).

Four gates, evaluated in sequence:

```
iron_rule_gate(candidate)
    |
    +-- direction == "sell"?
    |       YES -> PASS (卖出方向豁免铁律)
    |
    +-- Gate 1: intraday_dynamic_check (P0-02 盘中实时动态熔断器)
    |       |
    |       +-- TRIPPED?   -> BLOCK (铁律熔断: ...)
    |       +-- symbol market type in blocked_market_types (STAR)?
    |               -> BLOCK (科创板隔离)
    |
    +-- Gate 2: Streak Validation (连板深度核验)
    |   [only for direction == "buy"]
    |       |
    |       +-- board_height/streak >= 3?
    |           +-- is_dragon AND has_sector_support AND dragon_score >= 10?
    |           |       PASS
    |           +-- is_dragon AND NOT has_sector_support?
    |           |       BLOCK (铁律熔断: N板但无梯队助攻/光杆司令)
    |           +-- else?
    |                   BLOCK (铁律熔断: N板且非优质真龙)
    |
    +-- Gate 3: Strategy Circuit Breaker (策略熔断器)
    |       |
    |       check_strategy(catalyst_type)
    |       +-- BLOCKED?  -> BLOCK (铁律熔断 [策略]: ...)
    |       +-- else      -> PASS
    |
    +-- Gate 4: Market State Machine (市场状态机)
            |
            Reads market_regime.json
            |
            +-- data_fresh == False?
            |       BLOCK (市场状态缓存陈旧)
            |
            +-- regime in ("非交易日", "极寒", "freezing") OR standard_regime == "freezing"?
            |       BLOCK (市场极寒状态)
            |
            +-- fail_closed == True?
            |       BLOCK (Fail-Closed 防御熔断)
            |
            +-- regime == "退潮" / "panic_ebb" OR standard_regime == "panic_ebb"?
            |       |
            |       +-- ebb_subtype == "panic_ebb"?
            |       |       BLOCK (恐慌杀跌期, 禁止一切开仓)
            |       |
            |       +-- ebb_subtype == "exhaustion_ebb"?
            |       |       |
            |       |       +-- streak > 1?
            |       |       |       BLOCK (衰竭冰点仅允许首板)
            |       |       +-- is_chasing (change_pct >= 1.5%)?
            |       |       |       BLOCK (衰竭冰点严禁追高)
            |       |       +-- else -> set exhaustion_first_board = True, continue
            |       |
            |       +-- NOT is_sector_leader?
            |       |       BLOCK (退潮期非身位第一龙头, 严禁买入跟风杂毛)
            |       |
            |       +-- is_chasing AND NOT (is_dragon AND dragon_score>=10 AND has_sector_support)?
            |               BLOCK (退潮期龙头追高)
            |
            +-- garbage time (10:00 <= cur_time <= 14:30)?
                    |
                    +-- NOT is_sector_leader AND NOT exhaustion_first_board?
                    |       BLOCK (垃圾时间非龙头)
                    +-- is_chasing AND NOT is_true_dragon (dragon+score>=10+support)?
                            BLOCK (垃圾时间追涨)
                    +-- else -> PASS
            |
            PASS
```

### Gate 1 Detail: intraday_dynamic_check

```
input: quotes, market_metrics (optional)
        |
        +-- limitdown_count >= 20?
        |       TRIPPED (全市场跌停 >= 20)
        |
        +-- broken_seal_rate >= 45%?
        |       TRIPPED (炸板率 >= 45%)
        |
        +-- broad index (000001.SH / 399001.SZ / 399006.SZ) change <= -2%?
        |       TRIPPED (宽基暴跌)
        |
        +-- STAR50 (000688.SH) change <= -2%?
        |       +-- isolated (broad indices > -1%, limitdown < 20, broken < 45)?
        |       |       BLOCK STAR only, writes diverging regime, multiplier=0.25
        |       +-- not isolated?
        |               TRIPPED (科创50暴跌且宽基情绪恶化)
        |
        +-- limitdown == 0 AND broad_index_crash?
        |       TRIPPED (数据失真 Fail-Closed)
        |
        When tripped (GLOBAL scope):
          - Writes panic_ebb regime to market_regime.json
          - Sets sell_only_mode = True
          - Sets sentiment phase = "ice", multiplier = 0.0
          - Sets regime_multiplier = 0.0, max_regime_ratio = 0.0
```

---

## Tier 3: pipeline.py is_trade_ready()

**Source:** `/home/wade/workspace/ai/Astock/execution/pipeline.py`, line 170

```
is_trade_ready(candidate, require_risk=True)
    |
    +-- agy_approved == False OR llm_approved == False?
    |       YES -> return False (explicit rejection)
    |
    +-- [if BUY] sentiment phase cooldown + multiplier <= 0.3?
    |       YES -> return False
    |
    ==== REQUIRED FIELDS (both BUY and SELL) ====
    |
    +-- symbol truthy?                                          required
    +-- direction in {"buy", "sell"}?                           required
    +-- quantity >= 100?                                        required
    +-- price > 0?                                              required
    +-- [if BUY] entry_rule truthy?                             required
    +-- [if BUY] catalyst is enabled via is_catalyst_enabled?   required
    +-- confidence >= 0.65 (unless llm_approved or agy_approved)?  required
    |
    ==== BUY-SPECIFIC FIELDS ====
    |
    +-- realtime_confirmed truthy?                              required
    +-- volume_confirmed truthy?                                required
    +-- sector_confirmed truthy?                                required
    +-- fundamental_confirmed truthy?                           required
    +-- news_confirmed truthy?                                  required
    |
    ==== CATALYST-SPECIFIC SUB-CHECKS ====
    |
    Catalyst type detection:
    - limit_up catalyst    -> starts with "limit_up"
    - call_auction catalyst -> starts with "call_auction"/"1to2"/"opening_sniper"
    - chanlun (default)    -> everything else
    |
    +-- limit_up OR breakout?
    |       +-- breakout_confirmed?             required
    |       +-- volume_confirmed?               required
    |
    +-- call_auction (and variants)?
    |       +-- volume_confirmed?               required
    |       +-- [if NOT approved] sector_confirmed?  required
    |
    +-- chanlun (default) [and BUY]?
    |       +-- chan_buy_point in {"一买", "二买", "三买"}?  required
    |       +-- chan_confirmed?                            required
    |       +-- [if NOT approved] volume_confirmed?        required
    |
    ==== NON-APPROVED, NON-LIMIT_UP, NON-BREAKOUT, NON-AUCTION (chanlun only) ====
    [Only when: NOT sell AND NOT approved AND NOT limit_up AND NOT breakout AND NOT auction]
    |
    +-- leader_score >= 55?                    required
    +-- sector_confirmed?                      required
    +-- fundamental_confirmed?                 required
    +-- realtime_confirmed?                    required
    +-- news_confirmed?                       required
    +-- thesis starts with one of:
    |   [缺口逻辑] / [缠论] / [尾盘] / [首板] / [连板] / [竞价]?  required
    |
    ==== RISK APPROVAL ====
    |
    +-- [if require_risk (default True)]
    |       risk_approved truthy?              required
    |
    all(required) -> PASS / BLOCK
```

---

## Complete Decision Flow: Signal to Execution

```
                     +---------------------+
                     |  Candidate Signal   |
                     +---------------------+
                              |
                              v
                 +-------------------------+
                 | Tier 1: RiskManager     |
                 | 13-layer check_intent   |
                 +-------------------------+
                    |               |
              BLOCK(PASS)      BLOCK(REJECT)
                    |               |
                    v               v
                 [REJECTED]    [REGISTERED]
                    |               |
                    v               v
                 +-------------------------+
                 | Tier 2: iron_rule_gate  |
                 | AGY铁律 (4 gates)       |
                 +-------------------------+
                    |               |
                BLOCK            PASS
                    |               |
                    v               v
                 [REJECTED]    +-------------------------+
                               | Tier 3: is_trade_ready |
                               | Pipeline readiness      |
                               +-------------------------+
                                  |               |
                              BLOCK            PASS
                                  |               |
                                  v               v
                               [REJECTED]    [EXECUTABLE]
                                               |
                                               v
                                        normalize_intent()
                                               |
                                               v
                                        risk_check_and_execute()
```

### Notes

- **Tier 1 RiskManager** runs first in `risk_check_and_execute()`. Approved intents get registered to the exec server.
- **Tier 2 iron_rule_gate** is called by the candidate generation pipeline (prior to risk check), as a pre-filter on generated candidates. Candidates that pass are marked `agy_approved = True`.
- **Tier 3 is_trade_ready** is used in `prepare_trade_intents()` to validate a candidate is fully ready before it becomes a `TradeIntent`.
- The three tiers are independent gates; a signal must pass ALL three to reach execution.
