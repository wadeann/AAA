# a-stock-short-horizon-sniper-playbooks — A-Share Short-Horizon Sniper Strategy Library

Strategy library for short-cycle sniper systems: candidate generation, call-auction confirmation, intraday theme resonance, first-board detonation, overnight arbitrage, T+1 exit, backtesting, and audit. Covers the full "candidate pool → auction confirm → intraday trigger → position entry → T+1 exit → backtest/audit" lifecycle.

## Unified Lifecycle

1. **T-1/Premarket candidate generation**: Use only available data. Record data date, source, unit, degradation path.
2. **09:25 Auction confirmation**: Batch real-time snapshot for change, volume, turnover, sector linkage. Don't rely on unrefreshed "today's limit-up" broad table.
3. **Intraday trigger**: Cover morning, lunch news window, afternoon/close. Don't mistake 09:30-10:00 for the whole day.
4. **Cut first, record later**: Top-N cutoff before position recording. Same-day same-symbol idempotency required.
5. **Exit management**: A-share T+0 sell-protection; T+1 execute stop-profit/stop-loss by strategy.
6. **Verification closure**: Syntax check + offline fixtures + real data small-sample + state file readback + trade流水 reconciliation + worst-case time budget.

## General Data & Engineering Iron Rules

- Normalize units (shares/lots, yuan/10K-yuan, ratio/percentage, cumulative/daily PnL) before scoring
- Time point determines available data: premarket cannot query today's domestic futures. 09:25 cannot treat empty today's broad table as real zero
- External API empty: distinguish no-candidate, quota-exhausted, data-not-refreshed, MCP-error, parse-failure
- Use `tmp + replace` atomic writes for config/positions/state. JSON-RPC: check both `error` and empty `content`
- Compute worst-case total time for retries + timeouts, ensure < parent cron timeout
- After multi-round auto code modification: check duplicate functions, imports, old implementation residue, and call sites

## Playbook A: First-Board Detonation & Auction Decisive (Ignition)

For near-breakout, volume-active candidates from T-1 full market pool, confirmed at T 09:25 by auction change, volume ratio, turnover, sector linkage, and theme heat.

**Key discipline**:
- Unify historical and auction volume to shares
- Tiered config for postmarket score, auction score, market condition params
- Top-N cutoff before `record_position()`. Prevent duplicate opening
- Unify sell流水 price field — no `current_price`/`price` key mismatch
- Backtest date: first > scan day by K-line ascending. Wencai: Chinese month-day format

References: `references/ignition-v1-playbook.md`, `references/ignition-v1-agy-session-2026-09-09.md`

## Playbook B: Low-Position Theme Overnight Arbitrage

For non-mainline themes with overseas mapping, seasonality, prior-day K-line penetration, sentiment rotation, or lunch catalyst, confirmed by same-theme multi-stock auction/intraday resonance.

**Key discipline**:
- Overseas mapping: use already-closed instruments or traceable news. Fallback labeled
- Resonance requires >= 2 independent stocks
- Engine covers 09:30-11:30, 13:00-14:50 with separate lunch and close-session modes
- Excessive gap-up: don't chase. Exit by T+1 discipline, no long-term hold
- Cron: use `no_agent` with correct `workdir`, verify by actual execution

References: `references/overnight-theme-arbitrage-playbook.md`, `references/overnight-theme-arbitrage-implementation-details.md`

## Playbook C: Call Auction Selection Method (Premarket Strong Stocks)

For screening strong stocks during 09:15-09:30 call auction via volume-price behavior.

### Three Auction Time Segments

| Period | Rules | Characteristics |
|--------|-------|-----------------|
| 9:15-9:20 | Can place & cancel orders | Virtual auction, possible deception |
| 9:20-9:25 | Can place, cannot cancel | Real auction, reflects true intent |
| 9:25-9:30 | Cannot place or cancel | Selection time — key 5 minutes (orders queued in broker system) |

### Four-Step Process
1. Open gain ranking (type `60` in TongDaxin)
2. Sort volume high-to-low (volume = capital attention)
3. Filter gain **1%-4%** from top 30 by volume. Prefer high turnover + volume ratio
4. Form filter: stocks breaking platform resistance, bullish MA alignment, or at theme风口

### Dark Horse Selection (Premarket Limit-Up Method)
**Core conditions**: Volume ratio > 5, bottom-start form (near recent low, prev drop > 50%), price < 50 yuan, gain > 3%, circulating cap < 1B shares / < 2B yuan. Best buy at 3%-4% gain.

**Steps**: Sort by volume ratio, pick top 20 with ratio > 5. Remove gain > 7% (limited upside) and < 3% (not strong). Remove ST stocks.

**Trading principle**: Strong stocks need limit-up price buy order for priority execution (price priority > time priority).

## Playbook D: Step-by-Step Lotus (BuBuLianHua)

For screening first/second-board strong stocks postmarket, using limit-up next-day gap +实体 form for sniper.

### 7 Morphology Rules
1. **Limit-up base**: Requires limit-up stock with bullish MA alignment
2. **Gap-up open**: Next day gaps up, forms small yang or bald实体 yang line ("lotus")
3. **Gap unfilled**: After lotus forms, low open doesn't fill gap-up → buy opportunity
4. **Volume support**: Pre-lotus必须有 volume accumulation, lotus can shrink but prior volume must exist
5. **Best entry**: Next day大幅低开 below lotus实体 → optimal buy timing
6. **Board limit**: Best at 1st or 2nd board (early stage), reserving upside potential
7. **Entity standard**: Limit-up K must be实体 yang. Lotus can be limit-up yang, but lotus实体 only half of limit-up K's实体

### Buy/Sell/Stop
- **Buy**: Large low-open below lotus实体 = entry. If large gap-up no pullback, enter 10% position at close
- **Sell**: Fixed 5%-7% profit. If strong uptrend → hold along MA5 until broken
- **Stop**: At limit-up K's midline. If gap > 3%, only 10% position above gap, wider stop

**Selection**: `ZRZT` (yesterday's limit-up) list, look for today's yang with gap.

**Board strength**: 3 boards = minor demon, 5 boards = major demon, 7 boards = god-tier.

## New Playbook Archiving Standard

Add `## Playbook X` section here. Stable rules → main SKILL.md. Parameters/samples/audit → `references/`. Configs → `templates/`. Scripts → `scripts/`. Only standalone skill for completely different lifecycle/risk/toolchain.

## Verification Checklist

- [ ] Data time point and source verifiable
- [ ] Code, exchange, price-limit thresholds normalized
- [ ] All quantities and percentages unified
- [ ] Top-N cutoff before position recording
- [ ] Same-day same-symbol write idempotent
- [ ] T+0 protection and T+1 exit rules have tests
- [ ] State file atomically written and readable
- [ ] Cron timezone, workdir, timeout, run mode verified by actual execution
- [ ] Backtest states sample source, coverage, statistical limitations
- [ ] After auto code mod: syntax, duplicate definition, full-mode verification
