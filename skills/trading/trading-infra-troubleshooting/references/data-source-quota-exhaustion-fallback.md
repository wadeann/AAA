# 数据源额度耗尽 + 腾讯直连三级容灾

## 问题模式

`intraday_hot_sector_sniper.py` 的 `get_buyable_candidates()` 依赖两级数据源：

| 层级 | 数据源 | 典型失败模式 |
|------|--------|-------------|
| 1级 | `wencai_search` (port 9001) | "所有 API Key 均已失效或达到上限" |
| 2级 | `tdx_screener` (port 9001) | "Your usage quota has been reached" |

两级的 quota 相互独立，但**都可能在同一天中被多个 cron 轮询耗尽**（全天十几个 cron 共享同一个 key pool）。

## 症状

- 连板天梯正常输出（6板/4板/3板/2板...完整梯队）
- 但打法卡始终输出"无可立即执行买点，现阶段不下单"
- `get_buyable_candidates` 返回空列表
- 调试日志无 `[三级容灾]` 字样（说明未触发腾讯容灾—可能 quota 已恢复）

## 三级容灾：只使用有语义依据的候选池

当 wencai 和 TDX 都无数据返回时，可以继续使用腾讯直连做**行情验证**，但候选证券集合必须来自有依据的行业/题材成分数据，例如：

1. 已持久化的板块成分股缓存；
2. 权威行业或概念板块成分接口；
3. 盘前已经核验并落盘的观察池；
4. 其他不依赖问财额度的正式证券分类源。

**禁止用证券代码相邻关系代替行业关系。** 股票代码 ±30 与行业、题材没有可靠对应关系，会把无关股票伪装成“同行业候选”，这种降级比返回空池更危险。

正确职责划分：

- 板块成分数据负责生成候选集合；
- 腾讯/新浪/同花顺等实时行情接口负责验证价格、涨幅、成交额、盘口；
- 如果成分数据不可用，只输出已有的可验证条件预案，并明确标记候选数据源不可用，不得猜测。

多源行情 MCP 的完整实现与验证见 `multi-source-market-data-mcp.md`。

### 腾讯接口字段解析

```python
parts = line.split("~")
code_short = parts[2]      # 股票代码（6位，如 600825）
name = parts[1]            # 股票简称（如 "新华传媒"，可能乱码需 decode gbk）
cur = float(parts[3])      # 当前价
prev = float(parts[4])     # 昨收
chg = float(parts[32])     # 涨跌幅（%）
amt_wan = float(parts[37]) # 成交额（万元）
vr_v = float(parts[39])    # 量比
limit_up = float(parts[47]) # 涨停价
limit_down = float(parts[48]) # 跌停价
ask1_v = int(parts[20])    # 卖一量（=0 且价≥涨停价=封死）
bid1_v = int(parts[10])    # 买一量
```

### 代码前缀规则

```python
fmt_codes = [
    ("sh" + c) if c.startswith(("6", "9", "5")) else ("sz" + c)
    for c in scan_codes
]
```

- `6xxxxx` → `sh6xxxxx`（沪市主板）
- `9xxxxx`/`5xxxxx` → `sh9xxxxx`/`sh5xxxxx`
- 其余（0xxxxx, 3xxxxx, 002xxx, 301xxx等）→ `szxxxxxx`

### 多源直连行情的局限性

- 腾讯、新浪、同花顺等报价接口解决的是实时价格与盘口核验，不负责可靠的行业归属；
- 行业成分、连板身位、题材纯度仍须由独立结构化来源或昨日底表提供；
- 当分类数据缺失时必须降低结论置信度，而不是用代码区间、名称相似等启发式方法补造分类；
- 关键价格应使用多源共识与异常源隔离，详见 `multi-source-market-data-mcp.md`。

## MCP 工具 `get_limitup_ladder` 数据偏差警示

**发现**（2026-09-29）：MCP 工具 `mcp_intel_get_limitup_ladder()` 返回 `max_height: 1, ladder: {1: [...]}`（全部标的标为首板），但 playbook 脚本 `print_playbook.py` 和 intraday 脚本自建的天梯引擎均正确显示新华传媒 6 板、雪龙集团 4 板等完整梯队。

**结论**：`mcp_intel_get_limitup_ladder` 可能返回降级/缓存数据，**不要以此作为盘中连板判断的唯一依据**。正确的连板天梯数据应以以下之一为准：

- `print_playbook.py` 脚本输出（自建天梯引擎，三源容灾：wencai → akshare → TDX + 腾讯直连逐只核验封板）
- `intraday_hot_sector_sniper.py` 的 `fetch_intraday_ladder()`（同样自建天梯）
- `build_ladder.py` 的 `ladder_enhanced_{date}.json`（本地持久化）

## 问财宽条件搜索参数（2026-09-29 放宽后）

原始条件过严（涨幅0.5%~8%、现价≤60元、量比>1.0、换手率1.5%~18%、成交额>0.5亿），修改后的参数：

| 字段 | 原值 | 修改后 |
|------|------|--------|
| 涨幅 | 0.5%~8.0% | **0.2%~13.0%** |
| 量比 | >1.0 | **>0.8** |
| 换手率 | 1.5%~18% | **1.0%~25%** |
| 成交额 | >0.5亿 | **>0.3亿** |
| 现价 | ≤60元 | **≤200元**（实际从查询中去掉，用代码层过滤） |
| 价格过滤 | `price > 60.0 → continue` | `price > 200.0 → continue` |

对应的代码位置：
- 问财条件字符串：`intraday_hot_sector_sniper.py` L428-430
- 循环内过滤：L497（price check）、L533（live quote verify）、L567-569（TDX fallback）

## 候选集合的数据结构建议

板块候选集合必须保存明确的数据来源和分类证据，例如：

```python
sector_members: Dict[str, list[dict]] = {
    "出版": [
        {"symbol": "601949.SH", "source": "sector_component_cache", "as_of": "2026-09-29"}
    ]
}
```

不得只保存代码集合而丢失 `source/as_of`，否则无法判断分类是否过期或是否来自猜测。
