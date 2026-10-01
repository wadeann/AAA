# 全A盘中多入口宽发现架构

## 诞生背景

**问题**：`intraday_theme_trigger.py` 的 `--mode intraday` 仅消费盘前 `premarket_pool.json` 中的单一
`target_theme`（低于60分直接静默返回）。盘中爆发的新题材（盘前未预见）完全看不见，
产生系统性"今日无买点"误报。

**AGY审计（2026-09-30）确认**：系统中存在大量问财涨停扫描、放量异动扫描、涨速扫描能力，
但入口层缺少统一宽发现层（wide discovery layer）。各策略各自上游截断：
- `intraday_theme_trigger` — 仅看一个盘前题材
- `intraday_hot_sector_sniper` — 每天仅跑3次
- `limit_up_scanner` — 发现首板但不进入候选写入链
- `ignition_v1_sniper` — 主要是盘后静态池

## 架构图

```text
┌────────────────────────────────────────────────┐
│  full_market_intraday_discovery.py (每5分钟)     │
│                                                  │
│  momentum ──── 涨幅>2% 非ST                      │
│  volume ────── 量比>1.5 成交额>5000万             │
│  breakout ──── 突破昨日前高                       │
│  limitup ───── 涨停或触及涨停                      │
│  reversal ──── 昨日涨停今日>0%                     │
│         ↓ (并行问财, 去重合并)                     │
│  250只候选 → theme_groups聚类 (过滤非主题标签)      │
│         ↓                                         │
│  intraday_latest.json snapshot                    │
└────────────────────────────────────────────────┘
         ↓ (每5分钟, 2min offset)
┌────────────────────────────────────────────────┐
│  intraday_theme_trigger.py --mode intraday      │
│                                                  │
│  load_full_market_theme_groups() ← 消费快照      │
│  Top 8题材 × 各8只种子 = 64只进入深筛              │
│    ↓                                              │
│  expand_live_sector_candidates(theme, seeds)      │
│  run_intraday_detonation_engine()                 │
│  封板确认→分时回撤→流动性→布林阻力→补涨/突破      │
│  铁律闸门 → buy_signals/exit_signals              │
└────────────────────────────────────────────────┘
```

## Cron 时序

| cron job ID | 名称 | 表达式(CST) | 先后 | 输出 |
|------------|------|------------|------|------|
| `3186985bc23d` | 全A宽发现器 | 09:31-14:51 每5min (:01开始) | 先运行 | `intraday_latest.json` |
| `fa763ca049ba` | 起爆引擎 | 09:33-14:53 每5min (:03开始) | 后运行 | 飞书推送+候选写入 |

偏移2分钟确保发现快照在起爆引擎读取之前就已写完。

## 发现文件结构

`~/.hermes/trading/discovery/intraday_latest.json`:

```json
{
  "as_of": "2026-09-30T10:38:48+08:00",
  "market_scope": "ALL_A",
  "candidate_count": 250,
  "candidates": [
    {
      "symbol": "002074.SZ",
      "name": "国轩高科",
      "sources": ["breakout", "momentum", "reversal", "volume"],
      "source_evidence": { "momentum": { ...原始问财行 } },
      "change_pct": 2.54,
      "amount": 2.48e9,
      "volume_ratio": 7.9,
      "matched_sectors": ["动力电池回收", "锂电池概念", "固态电池" ...],
      "discovery_score": 88.4
    }
  ],
  "source_stats": { "momentum": { "status": "ok", "row_count": 168 } },
  "theme_groups": [  // 去重聚类，每题材最多8只
    { "theme": "国企改革", "member_count": 8, "candidates": [...] },
    { "theme": "医药生物", "member_count": 8, "candidates": [...] },
    ...
  ],
  "degraded_sources": []
}
```

## 问财查询配置

5个并行入口，每个支持分页配置：

| 入口 | 查询条件 | 默认参数 |
|------|---------|---------|
| momentum | 今日涨幅大于2% 非ST ... | page_size=100, max_pages=2 |
| volume | 今日量比大于1.5 非ST 成交额大于5000万元 ... | page_size=100, max_pages=2 |
| breakout | 今日突破昨日最高价 非ST 涨幅大于1% ... | page_size=100, max_pages=2 |
| limitup_ecosystem | 今日涨停或炸板或触及涨停 非ST ... | page_size=50, max_pages=1 |
| reversal | 昨日涨停今日涨幅大于0% 非ST ... | page_size=50, max_pages=1 |

### 素材写入模式（not a screener）

发现器 `full_market_intraday_discovery.py` 是纯"宽进"脚本，**不做**买入/卖出决策。
它只负责发现、合并、留痕。发现的候选不写 `candidates.jsonl`（那是交易闸门的输入），
而是写入独立 `discovery/intraday_latest.json` 快照供下游策略消费。

`save_snapshot()` 使用原子写入（`.tmp` → rename 替代），避免并发读取损坏。

## 关键设计决策

### 为什么选问财作盘中查询
- 问财是唯一支持"同花顺行业+概念"双维度全市场查询的源
- 分页支持（page参数）可覆盖500+只候选
- TDX/MCP `screen_stocks` 额度有限且不支持概念字段
- **只用于"发现层宽进"**，后面有严格的铁律闸门兜底

### 非主题标签过滤
在 `build_theme_groups()` 中过滤掉不构成交易主题的标签：
```
融资融券, 深股通, 沪股通, MSCI概念, 证金持股, 汇金持股,
基金重仓, 机构重仓, 高股息精选, 2026中报预增, 2026中报预减, ...
```

### 跨题材去重（`select_theme_groups_budget`）
同一只股票可能同时被多个题材命中（如国轩高科同时属于"电池"和"新能源汽车"）。
去重规则：**先出现者持有，后出现的其他题材跳过该标的**。确保同一只股票不会
被多个策略组同时深筛。

### 涨停判定自动适配
在 `intraday_theme_trigger.py` 中，封板判定从硬编码 `chg >= 9.8` 改为
`is_quote_limit_up()`，调用 `utils_market.is_limit_up_price()` 按板块制度
自动适配：主板4.8%/9.8%、双创19.2%、北交所28.5%。

## 回测试运行

2026-09-30 盘中试跑结果：
```
🔭全A宽发现 10:59 | 候选250只 | 来源5/5全部正常
主板117只 / 创业板121只 / 北交所12只
Top 8: 国企改革(8) 医药生物(8) 机器人概念(8)
        新能源汽车(8) 人工智能(8) 创新药(8)
        华为概念(8) 储能(8)
```

## 关联脚本

- `scripts/full_market_intraday_discovery.py` — 发现器
- `scripts/intraday_theme_trigger.py` — 起爆引擎（消费发现快照）
- `tests/test_full_market_intraday_discovery.py` — 25个测试覆盖
- `utils_market.py` — `is_limit_up_price()` / `normalize_stock_symbol()`
