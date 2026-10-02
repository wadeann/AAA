# Code Map — Astock 完整代码结构

## 项目概览

```
astock/
├── __init__.py
├── condition_evaluator.py      # 盘口条件求值引擎 (R36)
├── mcp_client.py               # MCP JSON-RPC 客户端单例
├── config/
│   ├── __init__.py              # 配置加载器 (YAML/JSON/env)
│   └── strategy_params.json     # 策略参数中心 (运行时状态)
├── core/
│   ├── analyzer.py              # 分析器
│   ├── chanlun_engine.py        # 缠论引擎 (分型/笔/线段/中枢/背驰/买卖点)
│   ├── market_regime.py         # 市场体制检测 (基于指数涨幅)
│   ├── market_regime_check.py   # AGY 铁律门禁 + 盘中动态熔断
│   ├── market_resonance_engine.py # 市场共振引擎
│   ├── sentiment_engine.py      # 情绪引擎
│   ├── strategy.py              # 共享策略模块 (指标/评分/卖出规则/过滤)
│   └── strategy_profiles.py     # 11 个策略档案 (momentum_v5 等)
├── data/
│   └── __init__.py              # 数据管理器 (JSONL账本/状态文件)
├── defense/
│   ├── close_session_defense.py # 尾盘平仓防御
│   └── explode_monitor.py       # 炸板监控
├── discovery/
│   ├── auction_scanner.py       # 竞价扫描
│   ├── full_market_discovery.py # 全市场宽发现 (5路问财搜索)
│   ├── leader_monitor.py        # 龙头监控
│   ├── limitup_scanner.py       # 涨停扫描
│   └── theme_trigger.py         # 题材触发
├── evolution/
│   ├── performance_reporter.py  # 绩效报告
│   └── strategy_audit.py        # 策略审计
├── execution/
│   ├── active_portfolio_cleaner.py # 持仓清理
│   ├── auction_kill_switch.py     # 竞价熔断
│   ├── batch_trade_gate.py        # 批量交易门
│   ├── call_auction_scanner.py    # 集合竞价扫描
│   ├── direct_executor.py         # 即时执行器 (主入口, cron)
│   ├── dragon_screener_engine.py  # 龙头筛选引擎
│   ├── limit_up_scanner.py        # 涨停扫描器
│   ├── market_regime.py           # 执行层市况
│   ├── pipeline.py                # 流水线 (候选处理/风控/下单)
│   ├── position_guard.py          # 持仓止损守卫
│   └── strategy_params_init.py    # 策略参数初始化
├── intelligence/
│   ├── agy_bridge.py           # AGY 桥接
│   ├── agy_prompts.py          # AGY 提示词
│   ├── feishu_notifier.py      # 飞书通知
│   └── sector_flow.py          # 板块资金流
├── orchestrator/
│   ├── morning_master.py       # 早盘总管
│   └── watchdog.py             # 监控守护
├── risk/
│   └── risk_manager.py         # 13 层风控管理器
├── scripts/
│   ├── auto_iterate.py         # 自动迭代引擎
│   ├── backtest_2yr.py         # 2 年全市场回测 (主引擎)
│   ├── backtest_engine.py      # 缠论策略回测 v3
│   ├── backtest_v4.py          # 旧版回测
│   ├── backtest_v5.py          # 旧版回测
│   ├── backtest_v6.py          # 旧版回测
│   ├── backtest_ignition.py    # 点火模式回测
│   ├── backtest_3m.py          # 3月回测 (旧版)
│   ├── backtest_3m_v2.py       # 3月回测 v2 (修正版)
│   ├── check_system.py         # 系统检查
│   ├── market_analysis.py      # 大盘分析
│   ├── mcp_tunnel.py           # MCP 隧道
│   ├── run_intraday.py         # 盘中运行入口
│   ├── run_postmarket.py       # 盘后运行入口
│   ├── run_premarket.py        # 盘前运行入口
│   ├── scheduler.py            # 调度器
│   └── stock_universe_full.py  # 全市场股票池生成
├── tests/
│   ├── test_chanlun.py
│   ├── test_condition_evaluator.py
│   ├── test_market_regime_check.py
│   ├── test_mcp_client.py
│   ├── test_pipeline.py
│   └── test_risk_manager.py
└── utils/
    ├── broken_guard.py         # 炸板/假修复防护
    ├── chip.py                 # 筹码分析
    ├── fund_flow.py            # 资金流
    ├── leader_universe_filter.py # 龙头池过滤
    ├── market.py               # 市场工具
    └── strategy_circuit_breaker.py # 策略熔断器
```

## 1. 数据入口

| 文件 | 路径 | 作用 |
|------|------|------|
| `data/__init__.py` | DataManager | JSONL 账本 + 状态文件管理 |
| `config/__init__.py` | load_yaml/load_json | 配置加载 |
| `mcp_client.py` | MCPClient | 外部数据唯一入口 (3 个 MCP 服务) |

**MCP 三服务架构:**
- Intel (9001): K线/行情/问财/新闻/资金流
- Risk (9002): 风控检查/黑名单
- Exec (9003): 账户/持仓/下单

## 2. 股票池生成

| 模块 | 生成方式 |
|------|----------|
| `scripts/stock_universe_full.py` | 全市场 ~4000+只 (预设列表) |
| `discovery/full_market_discovery.py` | 5 路问财并发搜索 → 合并去重 |
| `discovery/limitup_scanner.py` | 涨停板扫描 |
| `discovery/auction_scanner.py` | 竞价扫描 |
| `discovery/leader_monitor.py` | 连板龙头追踪 |
| `discovery/theme_trigger.py` | 题材事件触发 |
| `execution/dragon_screener_engine.py` | 真龙筛选 |

## 3. Discovery (发现)

- `full_market_discovery.py`: 5 条策略并行问财搜索 (动量突破/N字反包/倍量首板/平台突破/龙回头)
- `leader_monitor.py`: 获取连板梯队 + 持仓退出信号检查
- `limitup_scanner.py`: 盘中涨停板扫描
- `auction_scanner.py`: 集合竞价扫描
- `theme_trigger.py`: 题材催化触发

## 4. Intelligence (智能)

- `agy_bridge.py`: AGY (Anti-Gravity) 外部 LLM 桥接
- `agy_prompts.py`: AGY 提示词模板
- `feishu_notifier.py`: 飞书交易通知
- `sector_flow.py`: 板块资金流向分析

## 5. Chanlun (缠论)

`core/chanlun_engine.py`:
- normalize_bars → inclusion_process → fractals → strokes → segments → pivots → divergence → buy/sell points
- `analyze_chanlun()` 主入口
- `trend_breakout_signal()` 平台突破/回踩确认
- `leader_score()` 连板龙头评分

## 6. Signal (信号)

- `core/strategy.py` → `score_momentum_core()` 8 因子评分
- `core/strategy_profiles.py` → 11 个策略 profile
- `core/chanlun_engine.py` → 缠论买卖点
- `execution/dragon_screener_engine.py` → 龙头信号
- `execution/direct_executor.py` → AGY 批准信号

## 7. Score (评分)

- `score_momentum_core()`: 8 因子 (Volume/DH/MA/RSI/Chg/Volatility/NewHigh/Pullback)
- `compute_signal_score()`: 缠论信号 5 因子评分 (趋势/买点/量/RSI/情绪)
- `leader_score()`: 连板龙头 0-100 评分

## 8. Position Sizing (仓位)

- `execution/pipeline.py` → `normalize_intent()`: total_assets * adjusted_pct
- `execution/direct_executor.py`: adj_pct * sentiment_multiplier → target_value → shares
- `core/strategy_profiles.py` → `MultiStrategyAllocator.get_alloc_pct()`: score-based
- `scripts/backtest_2yr.py`: regime_cap based on regime

## 9. Risk (风控)

`risk/risk_manager.py`: 13 层逐级检查:
1. symbol → 2. weekend → 3. position_cap → 4. market_crash → 5. outflow → 6. sentiment → 7. sector_conc → 8. total_exp → 9. t1_rule → 10. st_blacklist → 11. avg_down → 12. tail_chase → 13. freeze

## 10. Execution (执行)

`execution/direct_executor.py` (cron入口) → `execution/pipeline.py` (risk_check_and_execute) → `mcp_client.py` (MCP exec server 9003)

## 11. Backtest (回测)

- `scripts/backtest_2yr.py`: 全市场动量回测 (2348 只, 485 天)
- `scripts/backtest_engine.py`: 缠论策略回测 v3

## 12. Results / Journal (结果/日志)

- `data/ledger/candidates_{date}.jsonl`: 全部候选事件日志
- `data/state/`: 状态文件 (strategy_params.json, market_regime.json 等)
- `results/`: 回测结果文件

## 13. Evolution / Optimization (进化/优化)

- `scripts/auto_iterate.py`: 100+ 轮自动参数迭代
- `evolution/performance_reporter.py`: 绩效报告
- `evolution/strategy_audit.py`: 策略审计
