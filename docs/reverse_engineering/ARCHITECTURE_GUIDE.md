# Astock Architecture Guide

## Autonomous A-Share Quantitative Trading System

**Complete reverse-engineered architecture documentation. Last updated: 2026-10-02.**

---

## SECTION 1: Project Overview

### What Is Astock?

Astock is an autonomous quantitative trading system for the Chinese A-share market. It operates independently of any external CLI agent, communicating directly with three backend MCP (Model Context Protocol) JSON-RPC servers (intel/risk/exec) via the `httpx` HTTP library. The project spans backtesting, live trading, strategy optimization, risk management, market discovery, and self-evolution.

### Key Capabilities

1. **Two-Year Full-Market Backtesting** -- Simulates 2+ years of daily trading on ~2500+ A-shares using momentum scoring, technical pattern recognition, and transaction cost modeling
2. **Live Intraday Trading** -- Scheduled via APScheduler with premarket (09:00), intraday (every 5 min), and postmarket (15:15+) phases; runs autonomously once started
3. **Strategy Optimization** -- `auto_iterate.py` performs 100+ rounds of randomized parameter search, running full backtests per candidate and keeping best configs
4. **13-Layer Risk Management** -- Comprehensive risk checks including symbol validation, weekend blocking, position caps, market crash detection, sector concentration, T+1 compliance, ST blacklisting, tail-chase prevention, and freeze periods
5. **Degraded Mode (FAIL-CLOSED)** -- When the Risk MCP server is unreachable, the system falls back to local risk checks using available data; unverifiable checks are SKIPPED and intents are NOT auto-approved
6. **AGY (Antigravity) AI Audit** -- Delegates qualitative analysis to Google Antigravity CLI with automatic fallback to Gemini 3.7 Flash
7. **Defense Systems** -- Close-session sell defense, explode (炸板) monitoring, trailing stops, and position guard
8. **Self-Evolution** -- Daily strategy audit with Empirical Bayes win-rate smoothing, automatic blacklisting of low-performing strategies
9. **Feishu Notifications** -- 7-layer audit gate before sending trade alerts to Feishu groups

---

## SECTION 2: Directory Map

### Top-Level Files

| File | Purpose |
|------|---------|
| `__init__.py` | Package root; declares version 1.0.0 |
| `pyproject.toml` | Project metadata, deps: httpx, pyyaml, apscheduler |
| `.env` | MCP connection mode, iWenCai API Keys (x5), TDX API Key, SSH tunnel config, dry-run flags |
| `.gitignore` | Ignores: `__pycache__`, `.venv`, `.env`, `.log`, `data/state`, `kline_cache.json`, `.zip` |
| `mcp_client.py` | Singleton MCP JSON-RPC client (httpx). Routes tools to 3 ports: intel:9001, risk:9002, exec:9003 |
| `condition_evaluator.py` | Micro-timing condition evaluation engine (R36): auction check, intraday check, dependency check, chip/fund-flow safety, trailing profit, scale-out, index meltdown, sector deviation, speed filter, auction amount filter |

### `config/`

| File | Purpose |
|------|---------|
| `__init__.py` | Config loader: `load_yaml()`, `load_json()`, `save_json()`, `get_env()`. Defines `ASTOCK_ROOT`, `DATA_DIR`, `STATE_DIR`, `LEDGER_DIR`, `MEMORY_DIR` |
| `settings.yaml` | MCP server ports (9001-intel, 9002-risk, 9003-exec), trading timezone/schedule, risk limits, Feishu/AGY settings |
| `strategy_params.json` | Dynamic strategy parameters: catalyst_types (22 types with win-rates and cooldowns), global_guards, sentiment, blacklist, position_limits, stop_loss, redline_state, blocked_sectors, regime_map, score_weights, sell_rules, backtest_results |

### `core/`

| File | Purpose |
|------|---------|
| `__init__.py` | Empty |
| `strategy.py` | **Shared strategy module.** SMA/RSI/ATR, 8-factor momentum scoring (`score_momentum_core`), candidate screening (`screen_candidates`), regime detection (`get_regime`), `REGIME_MAP`, parameterized `SellRules` engine (6 rules), config loading with override injection |
| `strategy_profiles.py` | **22 strategy profiles** with registered `StrategyProfile` dataclasses. Multi-strategy allocator (`MultiStrategyAllocator`) for portfolio blending. Sources from notes/skills |
| `chanlun_engine.py` | 缠论 (Chan Theory) analysis: bar normalization, inclusion processing, fractal detection, stroke computation, segment analysis, pivot detection, divergence detection, buy/sell point classification (一买/二买/三买), breakout signals. Pure computational model |
| `market_regime.py` | `MarketRegime` class: detects market state (euphoria/hot/warmup/cooldown/ice) from 4-index data, computes regime multipliers, saves/loads from `market_regime.json` |
| `market_regime_check.py` | AGY iron-rule gate: intraday dynamic circuit breaker checking limit-down count (>=20), broken-seal rate (>=45%), index meltdown, sector trips. Uses `utils/strategy_circuit_breaker` and `utils/leader_universe_filter` |
| `market_resonance_engine.py` | Analyzes sector resonance: queries mainline lanes, determines role (primary_attack/secondary_attack/rotation/lagging) |
| `sentiment_engine.py` | Sentiment cycle engine: computes phase/multiplier from 4-index changes or candidate counts. Auto-blacklists strategies with win-rate < 40% and >= 5 samples |
| `cost_model.py` | Real transaction cost model: brokerage 0.025% (min 5 RMB), stamp duty 0.1% (sell only), transfer fee 0.002% (SH only) |
| `analyzer.py` | `MarketAnalyzer` class: orchestrates chanlun analysis, sentiment, regime into unified market context |

### `risk/`

| File | Purpose |
|------|---------|
| `__init__.py` | Empty |
| `risk_manager.py` | **`RiskManager` class**: 13-layer sequential risk check. `check_intent()` for single intent, `batch_check()` for batch + auto-registration to exec server |

### `execution/`

| File | Purpose |
|------|---------|
| `__init__.py` | Empty |
| `pipeline.py` | **Trade pipeline core**: `is_trade_ready()`, `normalize_intent()`, `degraded_risk_check()` (FAIL-CLOSED), `risk_check_and_execute()` (full flow). Catalyst enablement, shadow candidate management, hierarchical attribution, Empirical Bayes win-rate computation |
| `direct_executor.py` | **Live intraday executor** (cron: `* * * * 1-5`). Processes 2 candidates per run. Trading session check, de-duplication, account snapshot, market regime ratio, call-auction unmatched cancel (09:29:55), condition evaluation, risk check + execution |
| `batch_trade_gate.py` | **Batch trade gate** (10:55 + 14:55). Promotes shadow candidates to trade-ready intents, LLM readiness check, direction conflict resolution, batch risk check, execution |
| `position_guard.py` | Pre-market position guard: hard stop (-6%), trailing stop (-6%), time exit (>20 days). Generates sell candidates |
| `active_portfolio_cleaner.py` | Early-exit evaluation: trailing stop from peak, time exit (>20 days) |
| `auction_kill_switch.py` | Auction kill switch: cancels orders before market open if conditions violated |
| `call_auction_scanner.py` | Thin wrapper invoking call auction scanner |
| `limit_up_scanner.py` | Thin wrapper invoking limit-up scanner |
| `dragon_screener_engine.py` | Dragon tier grading: iron_dragon (>=5 boards), dragon (2-3), candidate (1), watch. `screen_dragons()` for ranked results |
| `market_regime.py` | Thin wrapper for market regime detection |
| `strategy_params_init.py` | Thin wrapper for strategy param initialization |

### `defense/`

| File | Purpose |
|------|---------|
| `__init__.py` | Empty |
| `close_session_defense.py` | **Close-session defense** (14:15/14:30/14:45). Triple scan: (1) sell positions with chan sell points or divergence, (2) panic bottom-fishing when Shanghai drops >1.5% with bottom divergence, (3) write candidates to ledger + trigger gate execution |
| `explode_monitor.py` | **Explode (炸板) monitor** (10:00-14:30). Detects touched-limit-then-dropped stocks. If >15 min not re-sealed, writes sell candidates. T+1 compliant |

### `discovery/`

| File | Purpose |
|------|---------|
| `__init__.py` | Empty |
| `full_market_discovery.py` | **5-strategy parallel wencai discovery**: momentum breakout, N-shaped reversal, volume-explosion first board, platform breakout, dragon-return. ThreadPoolExecutor concurrency, dedup by symbol |
| `limitup_scanner.py` | `get_ladder()`: fetches limit-up ladder, grades seal strength (iron/strong/weak), scores by boards + order book quality |
| `auction_scanner.py` | `scan_auction()`: gap-up (3-7.5%) + volume explosion candidates at 09:25. Inverted-V scoring for gap %, volume ratio, market cap |
| `theme_trigger.py` | `trigger_themes()`: consumes discovery snapshot, ranks themes, deep-screens top themes with 5 parallel wencai queries (涨停梯队/竞价异动/资金流入/平台突破/低位首板) |
| `leader_monitor.py` | `monitor_leaders()`: tracks limit-up ladder leaders + positions, checks exit triggers (break-seal, trailing stop) |

### `orchestrator/`

| File | Purpose |
|------|---------|
| `__init__.py` | Empty |
| `morning_master.py` | **09:25 premarket orchestrator**: 6-phase sequential pipeline (MCP warmup -> call_auction_scanner -> limit_up_scanner -> batch risk control -> autonomous-trade-gate -> market open auto-submit). Non-buy notice to Feishu |
| `watchdog.py` | **Trading session watchdog** (every 15 min): checks if tasks ran today, auto-retriggers missed runs. Reads `jobs.json` for dynamic task discovery |

### `intelligence/`

| File | Purpose |
|------|---------|
| `__init__.py` | Empty |
| `agy_bridge.py` | **Antigravity bridge**: `ask_antigravity()` for AI analysis via AGY CLI. Automatic fallback to Gemini 3.7 Flash. `ask_antigravity_json()` for structured responses |
| `agy_prompts.py` | Prompt templates for AGY analysis tasks |
| `feishu_notifier.py` | Feishu message push. **7-layer audit gate** before sending: ST risk veto, concept mismatch, low-score junk, underwater breakout, empty codes, stale dates, notional value limits. `notify_trade_executed()` for trade confirmations |
| `sector_flow.py` | Post-market sector capital flow analysis via AGY. Falls back to wencai queries and candidate ledger mining |

### `evolution/`

| File | Purpose |
|------|---------|
| `__init__.py` | Empty |
| `strategy_audit.py` | **Daily strategy audit**: reads outcome records from JSONL ledgers, computes Empirical Bayes shrunk win-rates, generates P1 action items for low-performing strategies (< 40% with >= 5 samples). Adaptive confidence/position scaling |
| `performance_reporter.py` | **Account performance reporter**: persists daily snapshots (`account_snapshots.jsonl`), computes MDD, weekly/monthly returns. `main()` returns report dict |

### `scripts/`

| File | Purpose |
|------|---------|
| `scheduler.py` | **APScheduler-based daily trading scheduler**. Starts blocking scheduler with 15+ cron jobs covering premarket, intraday (every 5 min), trade gate (10:55/14:55), defense (14:15/14:30/14:45), postmarket |
| `backtest_2yr.py` | **Main backtest**: 2-year full-market simulation on ~2500+ stocks. Supports `--profile` for strategy selection (default: momentum_v5), multi-strategy allocator mode (`--profile multi`). Cash/position management, transaction costs, regime-aware position sizing |
| `backtest_engine.py` | **Chanlun-specific backtest engine v3**: multi-period confirmation (weekly trend filter), signal scoring (0-100), market regime fusion, differential position sizing. Uses `core/chanlun_engine` |
| `auto_iterate.py` | **Parameter optimization engine**: 100+ rounds of randomized parameter search. Each round: sample parameters -> run backtest -> compare metrics -> keep/revert. Supports `--profile`, `--fast`, `--rounds`. Persists `iteration_progress.json` |
| `backtest_3m.py` | 3-month backtest variant |
| `backtest_3m_v2.py` | 3-month backtest v2 variant |
| `backtest_v4/v5/v6.py` | Backtest version variants |
| `backtest_ignition.py` | Ignition/breakout-specific backtest |
| `backtest_ma_strategies.py` | MA-based strategy backtesting |
| `backtest_notes_strategies.py` | Notes-mined strategy backtesting |
| `stock_universe_full.py` | **2537 A-share stock universe** with industry classification. Functions: `get_industry()`, `get_universe_size()`, `get_industry_distribution()` |
| `expand_kline_cache.py` | K-line cache expansion script |
| `market_analysis.py` | Standalone market analysis script |
| `mcp_tunnel.py` | SSH tunnel setup for MCP forwarding |
| `check_system.py` | System health check |
| `run_premarket.py` | Premarket pipeline: sentiment + regime detection |
| `run_intraday.py` | Intraday pipeline: discovery + theme trigger + execution loop |
| `run_postmarket.py` | Postmarket pipeline stub |
| `optimize_notes_strategies.py` | Notes strategy optimization script |
| `survivorship_bias_analysis.py` | Survivorship bias analysis |

### `utils/`

| File | Purpose |
|------|---------|
| `__init__.py` | Empty |
| `broken_guard.py` | Exploded/unsealed + fake healing detection (`check_broken_and_fake_healing`, `compute_limit_pct`) |
| `chip.py` | Chip (筹码) distribution safety evaluation (`evaluate_chip_safety`) |
| `fund_flow.py` | Fund flow safety evaluation (`evaluate_fund_flow_safety`) |
| `leader_universe_filter.py` | Leader universe filter for AGY gate |
| `market.py` | Market utilities: `get_stock_market_type()` |
| `strategy_circuit_breaker.py` | Strategy circuit breaker |

### `data/`

| File | Purpose |
|------|---------|
| `__init__.py` | **`DataManager` class**: thread-safe JSONL ledger, state files, atomic writes. `append_jsonl()` (fcntl.flock), `read_jsonl()`, `load_state()`, `save_state()`, `load_candidates()` |
| `kline_cache.json` | ~270MB K-line data cache (~280M+ bytes) for all stocks |
| `full_universe.json` | Stock universe listing |
| `full_universe_raw.json` | Raw stock universe data |
| `ma_strategy_results.json` | Cached MA strategy backtest results |
| `notes_mining_results.json` | Cached notes mining backtest results |
| `cache/` | Additional cache directory |
| `ledger/` | Daily JSONL trade ledgers (`candidates_YYYY-MM-DD.jsonl`) |
| `learnings/` | Strategy learnings |
| `memory/` | Persistent memory (strategy feedback) |
| `methodology/` | Methodology documents |
| `state/` | Runtime state files (strategy_params.json, market_regime.json, sentiment.json, freeze_state.json, watchdog-runs.json, jobs.json, reviews/, etc.) |

### `results/`

Contains backtest output files, iteration logs, best_config JSONs, and archived results.

### `tests/`

| File | Purpose |
|------|---------|
| `test_backtest_integrity.py` | Backtest integrity unit tests |
| `test_chanlun.py` | Chanlun engine unit tests |
| `test_condition_evaluator.py` | Condition evaluator unit tests |
| `test_market_regime_check.py` | Market regime check unit tests |
| `test_mcp_client.py` | MCP client unit tests |
| `test_pipeline.py` | Pipeline unit tests |
| `test_risk_manager.py` | Risk manager unit tests |

---

## SECTION 3: Data Flow Diagram

```
                               +-----------------------------+
                               |    External MCP Servers      |
                               |  Intel(9001) Risk(9002)      |
                               |  Exec(9003) via httpx/JSON-RPC|
                               +-------------+---------------+
                                             |
                                     +-------+-------+
                                     |  mcp_client.py |
                                     |  (Singleton)   |
                                     +-------+-------+
                                             |
         +---------------+------------------+------------------+------------------+
         |               |                  |                  |                  |
  +------v------+  +-----v-----+  +--------v-------+  +------v------+  +------v------+
  |  Discovery   |  |   Core    |  |    Execution   |  |   Defense   |  | Intelligence |
  |  Layer       |  |  Layer    |  |    Layer       |  |   Layer     |  |   Layer      |
  |              |  |           |  |                |  |             |  |              |
  | • full_mar-  |  | • strategy|  | • pipeline.py  |  | • close_ses |  | • agy_bridge |
  |   ket_dis-   |  | • chanlun |  | • direct_exec |  |   sion_def- |  | • feishu_no- |
  |   covery     |  | • regime  |  | • batch_trade |  |   ense      |  |   tifier     |
  | • auction_   |  | • senti-  |  |   _gate       |  | • explode_  |  | • sector_fl- |
  |   scanner    |  |   ment    |  | • position_   |  |   monitor   |  |   ow         |
  | • limitup_   |  | • profi-  |  |   guard       |  +------+------+  +------+-------+
  |   scanner    |  |   les     |  | • dragon_scr- |         |                |
  | • theme_tr-  |  | • resona- |  |   ener        |         |                |
  |   igger      |  |   nce     |  | • auction_ki- |         |                |
  | • leader_m-  |  | • cost_m- |  |   ll_switch   |         |                |
  |   onitor     |  |   odel    |  +-------+-------+         |                |
  +------+-------+  +-----+-----+          |                 |                |
         |                |                |                 |                |
         +----------------+----------------+-----------------+----------------+
                          |                                       |
                  +-------v-------+                        +------v------+
                  |  Data Layer   |                        |   Results   |
                  |  (DataManager)|                        |  (output)   |
                  |               |                        |             |
                  | • JSONL ledger|                        | • backtest_ |
                  | • State files |                        |   reports   |
                  | • Kline cache |                        | • best_conf-|
                  +-------+-------+                        |   ig.json   |
                          |                                | • iteration_|
                          v                                |   logs      |
                   Ledger / State / Cache                   +-------------+
                   (Persistent Storage)
```

### Complete Flow: Discovery -> Strategy -> Risk -> Execution -> Monitoring

```
[Premarket 09:00]
  sentiment_engine.compute_sentiment()
  market_regime.detect()
  morning_master (09:25): auction_scanner -> limitup_scanner -> dragon_screener -> batch risk

[Intraday every 5 min, 09:30-14:55]
  market_regime refresh
  full_market_discovery (5 parallel wencai queries -> wide pool)
  theme_trigger (rank themes -> deep screen seeds -> write candidates)
  leader_monitor (track ladder + positions)
  direct_executor (2 candidates/run: condition_eval -> is_trade_ready -> risk_check_and_execute)
  watchdog (every 15 min: check for missed runs)

[Trade Gate 10:55 & 14:55]
  batch_trade_gate: load shadow candidates -> is_llm_ready -> direction conflict -> risk check -> execute

[Defense 14:15 / 14:30 / 14:45]
  close_session_defense: hold positions check -> chanlun sell signal -> panic fishing -> gate execution
  explode_monitor (10:00-14:30): detect touched-limit drops -> write sell candidates

[Postmarket 15:15+]
  performance_reporter: account snapshot + MDD + weekly/monthly returns
  sector_flow: AGY sector rotation analysis
  strategy_audit: Bayesian win-rate smoothing + action items
```

---

## SECTION 4: Execution Flows

### A) Backtest Flow (scripts/backtest_2yr.py)

```
1. CONFIG LOADING
   - load_strategy_config() from config/strategy_params.json
   - If --profile specified: get_profile(profile_name)
   - PARAM_OVERRIDES injection (for auto_iterate)
   - Load SellRules from config or profile defaults
   - Load REGIME_MAP from config or shared defaults

2. DATA LOADING
   - Load kline_cache.json (270MB local cache)
   - For each symbol in STOCK_UNIVERSE (2537 stocks):
     - Fetch klines (500 bars) via MCP intel:9001 -> cache
   - Fetch index klines (000001.SH) for regime detection
   - Generate trading date list from index bars

3. DAILY LOOP (for each trading date):
   a. Regime Detection:
      - get_regime(index_bars, date) -> euphoria/hot/warmup/cooldown/ice
      - Derive min_score, max_positions, cap_pct from REGIME_MAP

   b. Sell Execution (D+1 from D-day signals):
      - Execute pending sell signals at next day's open price
      - Apply sell_cost() transaction fees
      - Log P&L with attribution (regime, score, hold days, reason)

   c. Sell Detection (D-day):
      - Update max price (mp) for each position
      - SellRules.evaluate() -> (should_sell, exit_price, reason)
      - 6 rules checked: profit target, trailing stop, hard stop, breakeven, weak exit, time exit
      - Store as pending_sells (executed D+1)

   d. Buy Detection:
      - screen_candidates() -> 5 hard filters (min bars, min close, min volume, volume ratio, MA position)
      - For each candidate: score_fn(bars) -> {score, grade, name, target_pct, stop_pct}
      - Filter by regime min_score threshold
      - Sort by score descending
      - Buy cap_pct% of capital (regime-adjusted) at next day's open price
      - Apply buy_cost() transaction fees

4. P&L COMPUTATION
   - Track equity curve (daily cash + position market value)
   - Compute: total return, win rate, average P&L per trade, Sharpe, max drawdown
   - Per-regime statistics
   - Write detailed backtest report

5. MULTI-STRATEGY MODE (--profile multi)
   - MultiStrategyAllocator distributes positions across sub-profiles
   - Resonance bonus: +30% position for each additional strategy confirming
   - Budget enforcement per sub-strategy
```

### B) Live Trading Flow

```
1. SCHEDULER STARTUP
   - scheduler.py launches APScheduler (BlockingScheduler, Asia/Shanghai)
   - 15+ cron jobs registered for premarket/intraday/postmarket
   - watchdog runs every 15 min as fail-safe

2. PREMARKET (09:00-09:26)
   - 09:10: theme_arbitrage_scanner (隔日主题套利盘前雷达)
   - 09:20: run_premarket (sentiment + regime detection)
   - 09:25: morning_master orchestrator
     Phase 1: MCP warmup
     Phase 2: call_auction_scanner (gap-up high-volume)
     Phase 3: limit_up_scanner (yesterday weak-to-strong)
     Phase 4: dragon_screener_engine (dragon tier grading)
     Phase 5: batch risk control + dynamic position calculation
     Phase 6: trade gate pending order prep
     Phase 7: auction_kill_switch (cancel if conditions violated at 09:29:55)
   - 09:26-09:30: position_guard checks existing holdings

3. INTRADAY (every 5 min, 09:30-14:55)
   For each 5-minute tick:
   a. refresh_market_regime(): MarketRegime.detect() -> save to state
   b. direct_executor():
      - Check trading session active
      - Load processed IDs (skip already executed/rejected)
      - Get account snapshot (total_assets, available_cash, current_market_val)
      - Load today's candidates from JSONL ledger
      - For each unprocessed candidate (max 2 per run):
        - Parse candidate fields
        - condition_evaluator.evaluate_all() (auction + intraday + dependency + index + chip + fund flow)
        - is_catalyst_enabled() check (cooldown, sentiment protection)
        - is_trade_ready() check (all confirmations required)
        - normalize_intent() (position sizing with regime constraint)
        - risk_check_and_execute() (13-layer risk -> place_order)
        - Record result to ledger
   c. full_market_discovery(): 5 parallel wencai queries -> wide pool
   d. leader_monitor(): ladder snapshot + position exit checks

4. TRADE GATE (10:55 & 14:55)
   - batch_trade_gate:
     - Load shadow_candidates from ledger
     - Filter by is_llm_ready (not awaiting review, not rejected)
     - Check direction conflicts with today's executed trades
     - is_trade_ready() gate check
     - normalize_intent() position sizing
     - risk_check_and_execute() batch execution

5. DEFENSE SCANS (14:15 / 14:30 / 14:45)
   - close_session_defense:
     Scan 1: Check each holding for chan sell points / divergence -> sell
     Scan 2: If Shanghai drops >1.5%, search for panic bottom-fishing candidates
     Scan 3: Write all candidates to ledger + trigger gate
   - explode_monitor (10:00-14:30):
     Detect touched-limit-then-dropped stocks -> write sell candidates

6. POSTMARKET (15:15+)
   - 15:15: sector_flow (AGY sector rotation analysis)
   - 15:30: performance_reporter (daily P&L + MDD + returns)
   - 15:55: strategy_audit (Bayesian win-rate update + action items)

7. DEGRADED MODE (when Risk MCP is down)
   - FAIL-CLOSED: risk_check_and_execute() detects Risk MCP timeout
   - Falls back to degraded_risk_check() with 9 local-only checks
   - T+1 rule, position cap, cash availability, price sanity, session, ST list, freeze, avg-down
   - Checks requiring MCP data (market crash, sentiment, sector, outflow) are SKIPPED
   - All intents are NOT auto-approved; must pass degraded checks
```

### C) Strategy Optimization Flow (scripts/auto_iterate.py)

```
1. PARAMETER SPACE DEFINITION
   - Shared params (hard_filters: min_vr, min_rs, ma_pct; screens: min_vr, min_close; max_pos_pct)
   - Profile-specific params (from default_params, ±20%/±40% candidates)
   - Sell rules params (from profile.sell_rules, ±step candidates)
   - Score weights (volume, dh, ma, rsi, chg, vol_bonus, new_high_bonus, pullback_bonus)

2. ITERATION LOOP (default 100 rounds)
   For each round:
   a. SAMPLE: Randomly select 1-3 params to modify, pick random candidate values
   b. OVERRIDE: set_param_overrides(new_config)
   c. BACKTEST: import backtest_2yr, run_backtest(config_override=new_config)
   d. EVALUATE: Compute composite_score from metrics:
      - ret (total return), surv_ret (survivorship-adjusted), sharpe, mdd, win_rate, trades
   e. COMPARE: Against best config; if composite_score improves -> keep, else revert
   f. PERSIST: Write to iteration_log.txt, update iteration_progress.json

3. RESULT
   - Best config saved to results/best_config.json (and profile-specific variants)
   - Strategy_params.json updated with best config's backtest_results
   - Supports --resume for crash recovery via iteration_progress.json
```

---

## SECTION 5: Strategy Architecture

### Strategy Definitions (Profiles)

22 registered `StrategyProfile` dataclasses in `core/strategy_profiles.py`:

| # | Profile Name | Strategy Type | Source |
|---|-------------|---------------|--------|
| 1 | `momentum_v5` | 8-factor momentum (volume/DH/MA/RSI/chg/vol/new_high/pullback) | backtest_2yr baseline |
| 2 | `single_yang` | 单阳不破: big yang bar + retracement above midpoint | stock-selection-methods |
| 3 | `ma5_monster` | MA5 捉妖: consecutive highs + MA5 pullback + volume shrink | ma-system-strategies |
| 4 | `old_duck` | 老鸭头: MA5 death-cross to golden-cross + MA30 support | trend-and-limitup |
| 5 | `fairy_guide` | 仙人指路: long upper shadow probe + confirmation | candlestick-patterns |
| 6 | `massive_volume` | 巨量突破: massive volume + price breakout | volume-price-analysis |
| 7 | `golden_cross` | 金叉共振: MACD zero-axis golden cross | trend-and-limitup |
| 8 | `lotus` | 出水芙蓉: price crossing multiple MAs with volume | candlestick-patterns |
| 9 | `momentum_breakout` | 动量突破: multi-timeframe trend confirmation | backtest_2yr |
| 10 | `ensemble_top3` | Top 3 ensemble: momentum_v5 + single_yang + momentum_breakout | multi-strategy blending |
| 11 | `multi` | Multi-strategy allocator: momentum_v5(60%)+single_yang(20%)+lotus(20%) | strategy_profiles |
| 12 | `limitup_pullback` | 涨停回调狙击: limit-up day + 3-day retracement + MA support | trend-and-limitup |
| 13 | `t1_swing` | T+1 swing: prev day breakout + today opening confirmation | stock-selection-methods |
| 14 | `gap_proof` | 缺口战法: upward gap + no-fill confirmation | candlestick-patterns |
| 15 | `gap_proof_v2` | Gap-proof v2: enhanced gap logic | candlestick-patterns |
| 16 | `long_yang_seven` | 长阳七星: 7-bar yang sequence pattern | ma-system-strategies |
| 17 | `fake_yin` | 假阴真阳: fake yin (actually yang) pattern | candlestick-patterns |
| 18 | `divine_explorer` | 神探: deep pattern exploration | candlestick-patterns |
| 19 | `three_horse` | 三马: three-horse pattern | trend-and-limitup |
| 20 | `island_reversal` | 岛形反转: gap-down island + gap-up recovery | trend-and-limitup |
| 21 | `volume_floor` | 地量买入: volume floor + support + small yang | volume-price-analysis |
| 22 | `notes_ensemble` | Notes ensemble: ma5_monster + single_yang + island_reversal | notes-mining results |

Each `StrategyProfile` contains:
- `score_fn`: (bars, params) -> {score, grade, name, target_pct, stop_pct, hold_days, atr_pct}
- `screen_fn`: optional custom screening function
- `regime_fn`: optional custom regime detection
- `sell_rules`: dictionary with trail_trigger, trail rates, breakeven thresholds, max_hold
- `default_params`: strategy-specific parameters

### Scoring Model

The baseline `score_momentum_core` (momentum_v5) uses 8 factors weighted 0-100:

1. **Volume (25 pts)**: volume ratio tiers (VR > 3.0: 25, > 2.0: 20, > 1.5: 15, > 1.2: 10, > 1.0: 6, else 3)
2. **Distance from 10d high (20 pts)**: dh < 1%: 20, < 3%: 16, < 5%: 12, < 8%: 7, < 12%: 4
3. **MA alignment (20 pts)**: close > MA5 > MA10 > MA20: 20, close > MA5 > MA20: 14, close > MA20: 10, else 2
4. **RSI zone (15 pts)**: 45-65: 15, 65-75: 10, 35-45: 8, >75: 4, else 2
5. **Daily change (15 pts)**: chg > 7%: 15, > 5%: 13, > 3%: 10, > 1.5%: 7, > 0.5%: 4, else 1
6. **Volatility bonus (5 pts)**: range > 5%: 5, > 3%: 3
7. **New high bonus (5 pts)**: 10d high >= 99% of 20d high: 5
8. **Pullback bonus (10 pts)**: prev-10d max gain > 5% + VR < 0.9: 10

Grades: A (>=65), B (>=50), C (>=35), D (<35). Hard filters reject D/C grades.

### Sell Rules Engine

`SellRules` class in `core/strategy.py` with 6 configurable rules:

| Rule | Parameter | Default | Description |
|------|-----------|---------|-------------|
| Profit Target | tp (target_pct) | 8% | Close position when return reaches target |
| Trailing Stop | trail_trigger, trail_high_rate, trail_low_rate | 3%, 0.30/0.40 | Sell when drawdown from high-water mark exceeds threshold |
| Hard Stop | sp (stop_pct) | -2.8% | Stop loss at fixed percentage |
| Breakeven | breakeven_peak, breakeven_thresh | 3%, 0.5% | Lock profit when position was profitable but falls back |
| Weak Exit | weak_hold, weak_thresh | 2d, -0.5% | Exit when held N days with negative return |
| Time Exit | max_hold | 5d | Exit when maximum hold period exceeded |

Additional condition_evaluator sell rules (live only):
- **触板破位铁律**: touched limit-up then dropped > 4% or turned negative -> immediate sell_all
- **Tier 2 核心锁利**: high watermark > 9% + drawdown > 3% -> sell_all
- **Tier 1 分批止盈**: high watermark > 6% + drawdown > 2.5% -> scale_out_50%
- **Tier 0 保本锁**: high watermark > 3% + price drops to breakeven -> sell_all

### Position Sizing Model

```
Regime-adjusted cap:
  euphoria: 35% per position, 2 max positions
  hot:      20%, 1 max position
  warmup:   30%, 5 max positions
  cooldown: 28%, 3 max positions
  ice:      15%, 1 max position (sell-only in practice)

Score-based tiering:
  score >= 80: cap_pct + 5% (overweight)
  score >= 70: cap_pct (normal)
  score >= 60: cap_pct * 0.8 (reduced)
  score < 60:  cap_pct * 0.6 (light)

Position sizing = min(cash * alloc_pct, INITIAL_CAPITAL * max_pos_pct)
Quantity = max(100, int(amount / price / 100) * 100)  # lot-size aligned
```

### Market Regime Integration

Five regimes drive position sizing, minimum score thresholds, and whether buying is allowed:

| Regime | CN Name | Index 5d Change | min_score | max_pos | cap_pct | Behavior |
|--------|---------|-----------------|-----------|---------|---------|----------|
| euphoria | 高潮 | > +3% + all MAs up | 65 | 2 | 0.35 | Aggressive but capped |
| hot | 走强 | +1% to +3% | 70 | 1 | 0.20 | Selective high-conviction |
| warmup | 震荡 | -1.5% to +1% | 60 | 5 | 0.30 | Normal operations |
| cooldown | 退潮 | -3% to -1.5% | 60 | 3 | 0.28 | Conservative buying |
| ice | 极寒 | < -3% | 70 | 1 | 0.15 | Only top conviction |

Sentiment multiplier additionally scales confidence thresholds. When multiplier <= 0.3 with ice/cooldown phase, new buys are blocked entirely.

---

## SECTION 6: Risk Architecture

### 13 Risk Layers (in order of execution)

| # | Layer | Check | Applicable To |
|---|-------|-------|---------------|
| 1 | `symbol` | Valid symbol format (6-digit code + .SH/.SZ/.BJ) | All |
| 2 | `weekend` | Not weekend/holiday + is trading day | All |
| 3 | `st_blacklist` | Not ST/*ST/退市, not in blacklist | All |
| 4 | `position_cap` | Single position <= 30% of total assets | Buy |
| 5 | `market_crash` | Market health score >= 30 | Buy |
| 6 | `outflow` | Main force net outflow >= -800 billion RMB | Buy |
| 7 | `sentiment` | Sentiment phase is not ice/cooldown with multiplier <= 0.3 | Buy |
| 8 | `sector_conc` | Sector concentration <= 40% (configurable) | Buy |
| 9 | `total_exp` | Total exposure <= 80% (configurable) | Buy |
| 10 | `avg_down` | No existing position in same symbol (no averaging down) | Buy |
| 11 | `tail_chase` | Current time < 14:35 CST (no late-day chasing) | Buy |
| 12 | `t1_rule` | T+1 direction: no same-direction trade today, has shares for sell | All |
| 13 | `freeze` | Symbol not in freeze list with active freeze period | All |

### Degraded Mode Operation (FAIL-CLOSED)

When Risk MCP (port 9002) is unavailable after 4 retries (backoff 1/2/4s):
- Applies degraded_risk_check() to ALL intents (AGY and non-AGY alike)
- 9 local checks: trading session, price sanity, ST blacklist, freeze, T+1, position cap, cash availability, max position count, avg-down
- 5 checks skipped: market crash, sentiment, sector concentration, outflow, tail chase (requires MCP data)
- Intents passing degraded checks are marked `approved_by: degraded_risk_check`

### AGY Approval Flow

1. Candidates requiring LLM review are marked `awaiting_llm_review = True`
2. `agy_bridge.ask_antigravity()` sends prompt to Google Antigravity CLI
3. On quota/rate-limit: automatic fallback to `Gemini 3.7 Flash (High)`
4. AGY-approved candidates get `agy_approved = True` and pass `is_llm_ready()` check
5. `agy_approved = False` is a hard rejection (cannot be overridden)

### Kill Switches and Defenses

| Defense | Trigger | Window | Action |
|---------|---------|--------|--------|
| `close_session_defense` | Chan sell point / divergence on holdings | 14:15/14:30/14:45 | Write sell candidates, trigger gate |
| `explode_monitor` | Touched limit-up then dropped > 0.02 from limit | 10:00-14:30 | Write sell candidates (T+1 aware) |
| `position_guard` | -6% from cost OR -6% from peak OR >20 days | Pre-market | Write sell candidates |
| `auction_kill_switch` | Call auction order unmatched at 09:29:55 | 09:29:55 | Cancel + prevent passive fills |
| `index_meltdown` (condition_evaluator) | 4 indices all <= -1%, or SH <= -2%, or CYB <= -3% | Intraday | Block new buys |
| `redline_state` | Per-symbol/sector tripwire | Persistent | Block specific symbols/sectors |
| `sell_only_mode` | Market regime defensive or sentiment multiplier == 0 | Persistent | Only execute sell orders |
| `tighten_stops` | Config flag | Persistent | Reduce trailing/breakeven thresholds |
| `sentiment auto-blacklist` | Win rate < 40% with >= 5 samples | Daily audit | Add strategy to blacklist |

---

## SECTION 7: Key Dependencies

### Internal Module Dependency Graph

```
mcp_client.py (foundation — all layers depend on it)
  |
  +-- data/__init__.py (DataManager — persists everything)
  +-- config/__init__.py (paths, env vars)
  |
  +-- core/strategy.py (shared: SMA, RSI, ATR, score_momentum_core, screen_candidates, get_regime, SellRules)
  |     |
  |     +-- core/strategy_profiles.py (22 profiles + MultiStrategyAllocator)
  |     +-- core/cost_model.py (buy_cost, sell_cost, round_trip_cost)
  |
  +-- core/chanlun_engine.py (standalone computational model)
  +-- core/market_regime.py (regime detection -> market_regime.json)
  +-- core/market_regime_check.py (AGY gate, uses utils/*)
  +-- core/market_resonance_engine.py (sector resonance)
  +-- core/sentiment_engine.py (sentiment phases)
  +-- core/analyzer.py (composes all core modules)
  |
  +-- condition_evaluator.py (uses utils/broken_guard, utils/chip, utils/fund_flow)
  |
  +-- risk/risk_manager.py (uses mcp_client + data/DataManager)
  |
  +-- execution/pipeline.py (uses data/DataManager + mcp_client)
  |     |
  |     +-- execution/direct_executor.py (uses pipeline + condition_evaluator)
  |     +-- execution/batch_trade_gate.py (uses pipeline)
  |     +-- execution/position_guard.py
  |     +-- execution/active_portfolio_cleaner.py
  |     +-- execution/auction_kill_switch.py
  |     +-- execution/dragon_screener_engine.py (uses discovery/limitup_scanner)
  |
  +-- defense/close_session_defense.py (uses chanlun_engine + pipeline)
  +-- defense/explode_monitor.py
  |
  +-- discovery/full_market_discovery.py -> theme_trigger.py
  +-- discovery/auction_scanner.py
  +-- discovery/limitup_scanner.py
  +-- discovery/leader_monitor.py
  |
  +-- orchestrator/morning_master.py (composes discovery + execution)
  +-- orchestrator/watchdog.py
  |
  +-- intelligence/agy_bridge.py
  +-- intelligence/feishu_notifier.py
  +-- intelligence/sector_flow.py
  |
  +-- evolution/strategy_audit.py (reads ledger, updates strategy_params)
  +-- evolution/performance_reporter.py (reads MCP balance, computes MDD)
  |
  +-- scripts/scheduler.py (composes ALL modules via APScheduler)
  +-- scripts/backtest_2yr.py (uses core/strategy + core/cost_model + profiles)
  +-- scripts/backtest_engine.py (uses core/chanlun_engine + core/cost_model)
  +-- scripts/auto_iterate.py (imports backtest_2yr.run_backtest dynamically)
```

### External Dependencies

| Dependency | Purpose | Connection |
|------------|---------|------------|
| **pup-mcp Intel (port 9001)** | Market data, klines, quotes, wencai search, limit-up ladder, mainline lanes, TDX adapter, AGY analysis | httpx JSON-RPC via SSH tunnel |
| **pup-mcp Risk (port 9002)** | Intent checking, batch checking, blacklist, daily P&L | httpx JSON-RPC via SSH tunnel |
| **pup-mcp Exec (port 9003)** | Balance, positions, orders, trades, order placement, approved intent registration | httpx JSON-RPC via SSH tunnel |
| **iWenCai API** | Stock screening queries (5 API keys for rotation) | HTTPS via pup-mcp Intel server |
| **TDX (通达信) API** | Stock quotes, klines, screener, F10 data, news | Via pup-mcp Intel server |
| **Google Antigravity (AGY)** | Qualitative AI analysis, strategy review | Subprocess CLI call |
| **Feishu (飞书) API** | Trade notifications, decision summaries | httpx via webhook URL |
| **SSH Tunnel** | MCP server access forwarding | System SSH with key-based auth |

### Configuration Dependencies

| Config File | Consumers | Key Fields |
|-------------|-----------|------------|
| `settings.yaml` | All modules (via config/__init__.py) | MCP ports, trading schedule, risk limits, Feishu/AGY creds |
| `strategy_params.json` | core/strategy, risk/risk_manager, execution/pipeline, scheduler | Catalyst types, global guards, sentiment, blacklist, regime_map, sell_rules |
| `.env` | mcp_client, config | MCP_MODE, API keys, dry-run flags, SSH config |
| `market_regime.json` | core/market_regime, core/sentiment_engine, risk_manager, direct_executor | regime, standard_regime, regime_multiplier, sell_only_mode |
| `sentiment.json` | core/sentiment_engine, pipeline | phase, multiplier |
| `freeze_state.json` | risk_manager | Per-symbol freeze dates |
| `jobs.json` | orchestrator/watchdog | Cron job definitions for watchdog |
| `watchdog-runs.json` | orchestrator/watchdog | Last run times for retrigger detection |

---

## SECTION 8: Quick Start

### How to Run a Backtest

```bash
# 2-year full-market momentum backtest (default: momentum_v5)
cd /home/wade/workspace/ai/Astock
python3 -m scripts.backtest_2yr

# With specific strategy profile
python3 -m scripts.backtest_2yr --profile single_yang

# With multi-strategy mode
python3 -m scripts.backtest_2yr --profile multi

# Chanlun-specific backtest
python3 -m scripts.backtest_engine --pool 50 --capital 400000

# With specific stock pool
python3 -m scripts.backtest_engine --symbols 000001.SH,600519.SH --start 2024-01-01 --end 2024-6-30

# 3-month backtest
python3 -m scripts.backtest_3m
```

### How to Optimize a Strategy

```bash
# Run 100 rounds of parameter optimization for momentum_v5
python3 -m scripts.auto_iterate --profile momentum_v5 --rounds 100

# With fast mode (reduced stock pool)
python3 -m scripts.auto_iterate --profile single_yang --rounds 50 --fast

# Resume interrupted run
python3 -m scripts.auto_iterate --profile momentum_v5 --resume

# Results saved to: results/best_config.json, results/iteration_log.txt
```

### How to Start Live Trading

```bash
# Start the scheduler (all cron jobs handled automatically)
python3 -m scripts.scheduler

# Or run individual phases manually:
python3 -m scripts.run_premarket        # sentiment + regime
python3 -m scripts.run_intraday         # discovery + execution
python3 -m scripts.run_postmarket       # postmarket tasks

# Check system health
python3 -m scripts.check_system

# Set DRY_RUN=0 in .env to enable real order placement
# Default is DRY_RUN=1 (simulation only)
```

### How to Add a New Strategy

1. Define a scoring function in `core/strategy_profiles.py`:
```python
def _score_my_strategy(bars, params=None):
    # Implement scoring logic
    return {"score": score, "grade": grade, "name": "my_strategy",
            "target_pct": 8, "stop_pct": -2.8, "hold_days": 3, "atr_pct": atr(bars)}

register_profile(StrategyProfile(
    name="my_strategy",
    description="My custom strategy",
    source="custom",
    score_fn=_score_my_strategy,
    screen_fn=screen_candidates,  # or custom
    regime_fn=get_regime,
    sell_rules=dict(trail_trigger=3.0, ...),
    default_params={"param1": 10, ...},
))
```

2. Add to `strategy_params.json` under `catalyst_types`:
```json
"my_strategy": {
  "enabled": true,
  "min_confidence": 0.65,
  "win_rate": null,
  "sample_count": 0,
  "cooldown_until": null
}
```

3. Run a backtest to validate:
```bash
python3 -m scripts.backtest_2yr --profile my_strategy
```

4. Optimize parameters:
```bash
python3 -m scripts.auto_iterate --profile my_strategy --rounds 100
```

---

**Document generated by reverse-engineering analysis of /home/wade/workspace/ai/Astock. All descriptions verified against actual source code.**
