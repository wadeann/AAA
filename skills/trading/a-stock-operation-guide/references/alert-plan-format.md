# Alert Plan 格式规范

## 用途
为已有持仓或重点关注的个股设置盘中警戒条件，由 `intraday-leader-monitor` 每5分钟统一扫描，自动触发缠论复核+风控+下单。**不要为单只个股新建独立 cron。**

## 文件位置
`~/.hermes/trading/alert_plans/alert_plan_YYYY-MM-DD.json`

## 完整 JSON 结构

```json
{
  "plan_date": "2026-08-14",
  "plans": [
    {
      "symbol": "600487.SH",
      "name": "亨通光电",
      "direction": "sell",
      "plan_date": "2026-08-14",
      "position_class": "trend",
      "thesis": "成本60元1000股，c段涨停赶顶中，等待背驰信号",
      "entry_rule": "日线上升通道未破坏前持筹",
      "exit_rule": {
        "type": "chan_structure",
        "sell_signals": ["一卖顶背驰", "三卖跌破中枢B下沿56.4"],
        "stop_loss_structural": 56.4,
        "trailing_stop": "成本+3%动态跟踪"
      },
      "sell_alert": {
        "below": 59.5,
        "reason": "跌破60成本线预警区"
      },
      "leader_score": 72,
      "catalyst_type": "technical_breakout"
    }
  ]
}
```

## 字段说明

| 字段 | 说明 |
|------|------|
| `symbol` | 股票代码，如 `600487.SH` |
| `direction` | `"buy"` 或 `"sell"` |
| `position_class` | 持仓分类：`trend`/`swing`/`event` |
| `thesis` | 持仓逻辑简述 |
| `sell_alert` / `buy_alert` | `{"below": 价格}` 或 `{"above": 价格}`，命中后触发复核 |
| `exit_rule` | 缠论结构止损条件 |
| `leader_score` | 龙头评分，55-99 |

## 运行机制

1. `intraday-leader-monitor` 每5分钟读取最新的 `alert_plan_*.json`
2. 当实时价格触及 `sell_alert.below` 或 `buy_alert.above` 时触发
3. 执行缠论复核（100根30分钟K线）+ 基本面核验 + 新闻核验
4. 三要素全部通过 → 写入 `candidates_YYYY-MM-DD.jsonl`
5. `run_autonomous_trades.py`（统一交易闸门）读取 candidate → 走风控 → 下单
6. 同一事件只触发一次（由 `leader-monitor-state.json` 去重）

## 常用配置模板

**持仓保护性止损：**
```json
{
  "direction": "sell",
  "sell_alert": {"below": 59.5},
  "exit_rule": {"stop_loss_structural": 56.4}
}
```

**突破买入警戒：**
```json
{
  "direction": "buy",
  "buy_alert": {"above": 63.0},
  "entry_rule": "突破后回踩不破中枢上沿确认三买"
}
```
