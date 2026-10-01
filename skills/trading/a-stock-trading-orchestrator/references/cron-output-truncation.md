# 飞书输出规则 v5.0（2026-08-03 全面改造）

## 核心转变

**旧模式**：飞书 = 报告通道（复盘报告20-35KB → 截断 → 任务失败）

**新模式**：飞书 = 交易指令通道

## 为什么改

用户原话："用最精简的报告内容提示买入哪个股票卖出哪个股票，股价多少要多少手，比一份复杂的报告有用。需要问到具体股票再详细分析。"

## 飞书输出铁律（所有 cron job 通用）

1. **最多3行**
2. **格式模板**：
   ```
   [emoji 窗口] | 大盘XXXX +/-X% | 账户XXXX
   BUY/SELL 股票名 代码 方向 单价 手数 | 止损XX
   （无操作写"无信号"/"空仓无事"）
   ```
3. **空信号 = 最简**："无信号" / "空仓无事" / "无狙击信号"
4. **有操作时**：精确到股票名、代码、方向、价格、手数、止损位。不需要理由
5. **不要**：大盘分析、板块分析、浪型判定、情绪描述、B浪验证表、8维度持仓分析
6. **完整报告**写文件，飞书不提路径（用户需要时会问）
7. **需要详细分析时**用户会追问，那时再展开

## 各窗口具体格式

| 窗口 | emoji | 有信号 | 无信号 |
|------|-------|--------|--------|
| 盘前扫描 | 🌅 | BUY/SELL X股 XX元 X手 | "盘前无信号" |
| 开盘狙击 | 🔫 | BUY X股 XX元 X手 \| 目标/止损 | "无狙击信号" |
| 盘中上午 | ⏰10:00 | BUY/SELL X股 XX元 X手 \| 止损XX | "无信号" |
| 盘中下午开 | ⏰13:30 | 同上 | "无信号" |
| 盘中尾盘 | ⏰14:15 | 同上 + T+1提醒 | "无信号" |
| 收盘复盘 | 📊 | BUY/SELL + 账户 + 盈亏 | "空仓无事" |
| 资金流向 | 💰 | 流入TOP3/流出TOP3 | 就1行 |
| 周度维护 | 📋 | 保留N新增N移除N | "自选无变化" |

## 历史问题

### 2026-06-24 收盘复盘（首次截断）
- 问题：31KB 复盘报告直接推飞书 → `RuntimeError: Response remained truncated after 3 continuation attempts`
- 根因：cron skills 引用了不存在的 `a-stock-daily-review`，subagent 加载失败后仍尝试完成复盘
- 修复：skills → `["a-stock-trading-rules", "a-stock-trading-orchestrator"]`

### 2026-08-03 全面改造
- 所有7个交易 cron 的 prompt 全部重写，飞书输出从"报告摘要≤1800字"改为"指令≤3行"
- `a-stock-intraday-eval` 和 `a-stock-trading-orchestrator` 的 skill 输出格式章节同步更新
- 不再有截断风险——消息不超过80字

## no_agent=True 脚本常见输出bug修复记录

收盘复盘使用 `no_agent=True` + Python 脚本模式（`~/.hermes/scripts/cron_close_review.py`）。
脚本 stdout = 飞书投递内容。以下bug会导致飞书输出格式崩坏，触发用户"格式不合格"反馈。

### 常见格式bug清单

| # | 症状 | 根因 | 修复 |
|---|------|------|------|
| 1 | 代码和价格连在一起（`30050372.09`） | f-string `{sym_short}{now_price}` 无分隔符 | `{sym_short} {now_price}` |
| 2 | 显示现金而非总资产 | `bal_data.get("total_asset")` key 拼错，实际 key 是 `total_assets` | 加回退链：`total_assets` → `total_asset` → `total` → `cash` |
| 3 | 缠论状态截断 | `chan['state'][:30]` 截断到30字符，丢失中枢区间信息 | 移除截断，输出完整 state |
| 4 | 涨跌幅显示多余符号 | f-string 括号不配对 | 逐字符检查 f-string 花括号配对 |
| 5 | change_pct 为0时不显示涨跌幅 | `if change_pct else ""` 将 float(0.0) 视为 falsy | 应判断 `if change_pct is not None` |

### 调试方法

修复后终端验证：
```bash
cd ~/.hermes && python3 scripts/cron_close_review.py
```
输出应 ≤3 行，每行完整可读，代码与价格之间有空格。

### no_agent 模式自查清单（写/改脚本后用）

- [ ] 每只持仓：`代码 价格(+涨跌幅)` 有空格分隔？
- [ ] 总资产字段 key 匹配 `get_balance` 返回的 JSON key？
- [ ] 缠论状态未截断？
- [ ] f-string 括号配对正确？
- [ ] `change_pct` 的 falsy 判断不会吞掉 0%？