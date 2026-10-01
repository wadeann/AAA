# a-stock-self-evolution — A-Share Self Evolution & Strategy Learning Loop

Automated evolution loop: candidate generation → forward recording → outcome attribution → statistical down-weighting → rule upgrade. The goal is not daily forced trading, but letting the screening system iterate with verifiable results.

## 100-Round Evolution (2026-09-01 Correction)

User clarified: **100 rounds ≠ fixing 100 bugs**. Each round = prove improvement over previous with data support.

```
Baseline → AGY audit finds gap → Fix code/strategy → Backtest verifies improvement → Baseline (loop)
```

**Round accounting**:
- First 10 rounds (infrastructure: close-session/position/screen/gate) = one-time construction, not real "rounds"
- Real rounds start from R11 when backtest framework came online: each modification runs comparison
- Wencai historical backtesting allows dozens of rounds per week

**August baseline**: R0 real -167 yuan → R1-R11 backtest +159,071 yuan (+33.4%/month)
**AGY R13 correction**: Backtest has survivorship bias + future function + no negative samples → credibility score **35/100**
**Revised real expectation**: 12-18%/month (normalized), 45-50% (peak period, requires P1-P2 completion)

## Evolution Types

### Type A: Strategy-Level Paradigm Shift
**Trigger**: User expresses fundamental dissatisfaction with system (e.g., "not a single limit-up stock caught")
**Response**: Stop current fixes → AGY strategic audit → 10-round evolution per audit

### Type B: Parameter/Rule Tuning
**Trigger**: AGY audit finds P0/P1 bug, or strategy-feedback has action_item
**Response**: Standard 3-round AGY cycle (audit → fix → verify)

## 1. Daily Candidate Generation

- Read `~/.hermes/trading/strategy-feedback.md` + last 5 review files before premarket
- Check 4 indices real-time, then sector 5/10-day persistence, capital flow, ladder, catalyst sources
- Candidates must satisfy: real-time quote + 100 30-min K-lines + sector resonance + news/announcement verify + fundamental evidence
- Fundamental priority: real orders/mass production > revenue/profit delivery > operating cash flow improvement > pure concept
- Industry exposure hard cap 40%; candidate pool ≠ positions, observe first

## 2. Candidate Discovery & Forward Recording (Must Separate)

Daily premarket scan is primary entry discovery window. Flow must show:

`market/sector scan → sector catalyst + fundamental screening → 100 30-min K-lines per stock → Chan buy point → volume/sector/news evidence → write candidate JSON → trade gate`

`candidate_snapshot.py` is archival validator only, not screener. Each trading day, verify research output actually writes at least one `record_type: candidate` — otherwise report as "scan completed but no structured candidate formed".

Append to `~/.hermes/trading/feedback/candidates_YYYY-MM-DD.jsonl`.

## 3. Outcome Attribution

Close review updates each candidate: triggered? filled? MFE/MAE? holding period result? exit reason? B-wave grade? Data/judgment/execution/system root cause? Record zero-signal days too (survivorship bias prevention).

### Discovery success ≠ Trading success

Must split into 5 layers: discovery quality, price plan, buy execution, sell execution, actual PnL. No broker trade record → "research success, execution failure, actual PnL = 0".

- Unfilled signals → `shadow_candidate` / `SIGNAL_ONLY`, never `HOLDING`
- Real holding requires `order_id` + `filled_price` + `quantity > 0`
- Backtest must use original signal's entry/stop/target, not post-hoc pick best prices
- Single success case = "pending validation template"; require 5+ pre-recorded samples (including negatives) before solidifying

## 4. Statistics & Down-Weighting

- By `catalyst_type`, `entry_rule`, confidence band, industry: sample count, win rate, avg R/R, max drawdown
- Sample < 5: display only, no hard conclusion
- Sample >= 5 and win rate < 40%: next round confidence -0.10. Two consecutive rounds < 40%: pause rule
- 3 consecutive B-wave C-grade → rule review. 3 consecutive A-grade → solidify

### Strategy Parameter State Machine

Since 2026-08-28, `evolution_audit.py` **automatically writes** `~/.hermes/trading/config/strategy_params.json` after audit:

| Condition | Action |
|:----------|:-------|
| Sample >= 5 and win rate < 40% | `enabled=false`, `cooldown_until=7 days` |
| Sample >= 5 and win rate >= 60% | `enabled=true`, `cooldown_until=null` |
| Sample < 5 | No change |

**Hot reload**: `autonomous_trade_pipeline.py` reads config at gate runtime — no cron/agent restart needed.

### Shadow Tracking Pipeline (Sample Starvation Deadlock Fix)

Since 2026-08-28: shadow tracking resolves "gate too strict → 0 trades → 0 samples → audit stalls":
1. Loose signal judgment (`is_shadow_ready`): Chan buy point + basic volume confirm
2. Auto-write `shadow_candidate` to JSONL regardless of real gate pass/fail
3. Audit engine consumes both real + shadow outcomes

Even with zero real positions, audit engine produces continuous statistics.

### Physical Breaker vs Evolution Audit

`strategy_circuit_breaker.py` is physical blocking loop (n>=2 threshold), `evolution_audit.py` is statistical tool:

| Breaker Rule | Threshold | Cooldown |
|:-------------|:----------|:---------|
| Consecutive loss | Same strategy last 2 consecutive losses | 7 days |
| Heavy loss | Same strategy single loss > 5% | 14 days |

Key differences from evolution_audit:
- Sample threshold n>=2 (not n>=5) — consecutive loss = breaker, don't wait for samples
- Breaker state written to `breaker_state.json` (not JSONL text)
- `market_regime_check.py` iron_rule_gate physically blocks before order placement
- Supports `--sync` to import trade history from feedback JSONL

### Physical Breaker Learning Boundary (2026-09-19)

Strategy stats and physical breaker must be layered: `evolution_audit.py` can study both real and shadow samples, but `strategy_circuit_breaker.py` only learns from real `candidate_outcome + direction=buy`. `shadow_outcome` has no real capital exposure — must not freeze strategies.

- MAE in ledger is negative return (e.g., -11.81%). Heavy loss judgment must use `mae <= -6.0`, not `>= 6.0`.
- Normalize decimal vs percentage consistently.
- For BUY entry quality: `effective_pnl = min(close_pnl, mae)` prevents "deep intraday dip but recovered at close" from escaping breaker.
- Catalyst cooldown/blacklist only blocks BUY risk; SELL stop-loss, take-profit, emergency exit unconditionally allowed.

## 5. Trade Gate

Only pass when: 一买/二买/三买 structure + volume-price confirm + sector resonance + fundamental evidence + real-time quote + risk approval all pass. Any missing → output observe/no-signal.

## 6. Archiving Contract

- Machine data: `~/.hermes/trading/feedback/*.jsonl`
- Detailed review: `~/.hermes/trading/reviews/review_YYYY-MM-DD.md`
- Strategy summary: append to `~/.hermes/trading/strategy-feedback.md` only
- Action items must include: priority, owner, specific fields/steps, effective window, verification method, status
- Every trading day (even zero candidates/trades): append `run_marker` + review start/complete record

## 7. Two-Stage Limit-Up Research Loop

1. Close stage: real MCP for non-ST limit-ups, ladder days, sector, reason, volume/turnover. Write `record_type: observation`, status=`awaiting_open_confirmation`
2. Next day premarket/09:35: re-read observation pool, query real-time + auction + first 5-min K-line. Weak open / volume stagnation / no sector resonance / missing evidence → terminate observation. Only when Chan buy point + volume + sector + fundamentals + risk all pass → upgrade to `record_type: candidate`

Standard state flow: `limitup_research → observation → open_confirmation → candidate_or_filtered → risk_approved_or_rejected → dry_run_or_execution → outcome`

## 8. Cron Closure & Scheduling Reliability

### Action Item Execution Death Spiral Fix

strategy-feedback.md accumulated 16 P0/P1 action items; only 1 executed in 10 days. Fix rules:

1. **P0 auto-execute**: P0 items auto-enter Step 0 on next trading day's first cron/conversation
2. **P0 failure must be reported**: If blocked, specify reason + alternative plan — no silent skip
3. **Deadlines**: P0 ≤ 5 trading days, P1 ≤ 10. Expired → auto-upgrade or mark blocked
4. **Execution evidence**: Append `[executed YYYY-MM-DD: brief evidence]` after original item
5. **Weekly blockage report**: Every Friday close check all unexecuted items
6. **AGY code modification verification**: After AGY CLI modification, do 3-layer check — syntax (`py_compile`) → function test (`grep` key functions exist) → integration test (`is_trade_ready` correct behavior)
7. **No satisfaction from generating items**: Execution is the last step, not the report

### Key Cron Reliability Rules
- croniter multi-segment expressions NOT supported — use single-segment coarse cron + script-level window filtering
- No two cron jobs at same minute → queue blocking
- HTTP 429 cascade avalanche: don't load self-evolution (large skill) into intraday agent
- P0 auto-execution rule applies: don't skip P0 items due to "it's P0 but I won't execute"
- Watchdog recovery: deterministic script execution, not model interpreting CLI

## References
- `references/forward-strategy-validation.md` — Forward observation window setup
- `references/spiral-up-architecture.md` — Strategy param state machine + shadow tracking
- `references/strategy-learning-breaker-contract.md` — Strategy learning & physical breaker contract
- `references/signal-discovery-to-realized-pnl-contract.md` — Signal discovery to realized PnL
- `references/cron-reliability-debugging.md` — Cron reliability debugging
- `references/llm-review-threshold-calibration.md` — LLM review threshold calibration
- `references/sentiment-engine.md` — Sentiment cycle engine
