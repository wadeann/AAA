# 情绪周期引擎 - 每日盘前策略参数初始化

## 设计目标
在AGY审计修复完代码bug后，系统需要从"写代码"层进入"用参数"层——即每日09:25竞价前自动初始化情绪阶段，让交易闸门按市场温度自动调仓。

## 文件位置
scripts/strategy_params_init.py — 写入 ~/.hermes/trading/strategy_params.json
morning_master_orchestrator.py Phase0.5 — 每日09:25自动触发

## 情绪5阶段参数
| 阶段 | 仓位乘数 | 触发条件 | 策略行为 |
|:---:|:--------:|----------|----------|
| ice（冰点） | 0.30 | 涨停<20家 | 只做冰点首板 |
| warmup（启动） | 0.40 | 涨停20-50家 | 做1进2试探 |
| hot（高潮） | 0.80 | 涨停50-100家 | 全量信号放开 |
| euphoria（狂热） | 1.00 | 涨停>100,连板>7 | 全仓但防退潮 |
| cooldown（退潮） | 0.30 | 涨停骤降,跌停多 | 只卖不买 |

## 读取路径
trade_gate（run_autonomous_trades.py）在仓位计算时：
```python
strategy_params = load_strategy_params()
sent_multiplier = strategy_params.get("sentiment", {}).get("multiplier", 1.0)
adj_pct = adj_pct * sent_multiplier
```

## 黑名单策略
从strategy-feedback.md读取胜率<40%的策略自动暂停开仓。
强制加入 `technical_breakout` 策略（AGY历史审计结论：胜率<40%需硬熔断）。

## 2026-09-02 初始值
当前情绪阶段: warmup（启动期,仓位乘数0.4）
黑名单: ["technical_breakout"]
