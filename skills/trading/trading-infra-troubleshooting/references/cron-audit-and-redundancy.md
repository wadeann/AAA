# Cron 存废判断与冗余诊断

用于需要评估一个 cron job 是否存在价值、是否应该保留/删除的场景。

## 触发信号

- 用户问“这个 cron 有没有必要存在？”
- 一个 cron 长期（数周）未产生过可执行的买卖信号
- 多个 cron 使用同一脚本、相近时间、向同一飞书频道 deliver
- 用户表示从未在飞书看到某 cron 的有效推送

## 六步诊断法

### 1. 确认 cron 元信息

```bash
cronjob action=list
```

关注：
- `name`：描述是否精确（`午间题材驱动扫描` vs `盘中起爆点引擎`）
- `schedule`：是否在合理交易时段（如 13:00 CST = 05:00 UTC 合理；但 21:00 CST 跑盘中扫描就有问题）
- `deliver`：`local`（本地）还是 `feishu:...`（推送到用户）—— 推飞书却从未产出有效信号是最高优先级嫌疑
- `script`：用的哪个脚本
- `no_agent`：是否纯脚本（True=过滤掉 LLM 推理的确定性任务）
- 多个 cron 引用同一脚本且 schedule 相近 → **冗余可能性高**

### 2. 检查历史输出

```bash
ls -la ~/.hermes/cron/output/$JOB_ID/
cat ~/.hermes/cron/output/$JOB_ID/$(ls -t ~/.hermes/cron/output/$JOB_ID/ | head -1)
```

不是只看最近一次——要看**连续多日的输出模式**：
- 是否每次都是同一个模板输出（如"无及格题材/空仓防守"的防守空话）？
- 是否今日有信号但明日就无，还是长期无信号？
- 输出内容是否包含具体可操作的买卖指令？
- 输出是否为`Status: silent (empty output)` —— 飞书推送但无内容=信号全被过滤

### 3. 判断信号类型：用户面向 vs 基础设施

用户面向 cron deliver 到飞书，产生的是**人直接可以操作的东西**（买入/卖出/持仓报告/天梯看板）。

基础设施 cron deliver=local，产出的是**供其他脚本消费的数据文件**。需要检查：
- 输出文件被哪些脚本引用：`grep -rn "文件名\|关键字段" ~/.hermes/scripts/*.py`
- 是否唯一的生成者（只有它写这个文件，且至少一个消费者依赖它）
- 依赖者是否本身就产生用户可见的输出（如 sector_action_matrix 用 enhanced ladder 做板块分析）

基础设施 cron 即使从不直接产生买卖信号，也不应随意删除。

### 4. 检查脚本的内部逻辑

打开脚本，检查其核心判断路径：

```bash
# 看评分/过滤条件，判断是否有真实的输出可能性
grep -n "score\|score\|60\|门禁\|过滤\|skip\|pass\|return\|exit\|--mode" $SCRIPT.py | head -20
```

关键问题：
- 是否有过高的门槛（如 60 分及格线），且在可预见行情下几乎无法达到？
- **是否有"数据源白名单门禁"**：如 `get_buyable_candidates()` 要求 `data_source_used == "wencai"` 才返回候选，否则无条件 `return []`。当主数据源（问财）容灾到备用源（akshare_em/tdx_screener）时，候选生成被静默关闭 → 长期只输出防守看板。详见 `references/intraday-hot-sector-sniper-candidate-bug.md`。这类 bug 的特征是：脚本仍保留候选分支，但候选恒为空，用户只看到防守模板。
- 退潮期是否只是输出"空仓防守/严禁买入"的防守空话——这些内容已经被 sentiment-redline-monitor 或盘中看板覆盖？
- 脚本是否与相同时间段的另一 cron 覆盖同一个集合？

### 5. 排查冗余覆盖

A股交易 cron 常见冗余模式：

| 冗余模式 | 案例 | 诊断方法 |
|---------|------|---------|
| **同一脚本多 mode** | `theme_arbitrage_scanner.py` 同时有 `--mode premarket` (09:10) 和 `--mode midday` (13:00) | 检查 midday 模式是否真的用午间新数据（新闻+上午资金流向），还是只重复了 premarket 已有的信息 |
| **信号覆盖** | 多个 cron 都产出"退潮期空仓防守" | sentiment-redline-monitor 和 intraday-hot-sector-sniper 已有盘中防守信号；午后防守若只是重复→冗余 |
| **时间窗口无用** | 13:00 午间驱动扫描：A股午休 11:30-13:00，13:00 刚开盘，午间新闻在 09:10 盘前扫描已经覆盖过 | 嫌疑：迟到的信息 |
| **通知重叠** | 同一脚本在不同 cron 中递送相同信息 | 检查它们的 output 内容是否一致 |

### 6. 判定与执行

| 判定 | 行动 |
|------|------|
| **冗余**：与另一 cron 信号重叠，且从未产出独立价值 | `cronjob action=remove job_id=$ID` |
| **基础设施**：被下游多引擎依赖，即使不推用户也需保留 | 保持 `deliver=local` 不动，确认下游无替代源 |
| **低效但非冗余**：逻辑正确但门槛过高导致长期零输出 | 调低门槛（如 60→40 分）或合并到上游 cron |
| **僵尸**：脚本已停用/爬虫被封/数据源不可用 | 移除 cron，清理相关代码 |

## 实战案例

### 案例1：午间题材驱动扫描（2026-09-23，c0d0d451844f）

**诊断**：脚本 `theme_arbitrage_scanner.py --mode midday`，13:00 CST 运行，deliver=feishu。

历史输出分析（连续11个交易日）：
- 退潮期日子：列 5 只观察标的但每只标"严禁买入，仓位0%"——防守空话
- 非退潮日子：评分<60，输出"无及格题材"——同样是空话
- 从未产出过一个有效的买入信号

**冗余判断**：与 09:10 盘前版共享同一脚本但 midday 模式无独立数据源（13:00 的上午资金流向数据在 12:00 即可获得）；防守内容已被盘中看板覆盖。

**结论**：删除。✅

### 案例2：隔日题材套利盘前雷达（2026-09-23，695559af50ea）

**诊断**：脚本 `theme_arbitrage_scanner.py --mode premarket`，09:10 CST 运行，deliver=feishu。

历史输出分析（连续11个交易日）：
- 推荐题材（糖业96.5分/半导体69.5分/化学制药69.5分/文化传媒69.5分）在当天都**没有实质爆发**
- 推荐标的（新华制药/博通集成/中粮糖业等）**没有联动触发到买入执行环节**
- 退潮期输出一堆标的但每只标"严禁买入，仓位0%"——防守空话
- premarket_pool.json 被下游 intraday_theme_trigger.py 消费，但后者在盘中同样没有产出过有效信号（盘中起爆点引擎 fa763ca049ba 每天都是 silent）

**冗余判断**：推荐题材未能转化为实际爆发，系统中已有 morning-master-orchestrator (09:24)、竞价确认 (09:25)、盘中起爆引擎 (10:30-14:50 每5分) 覆盖更实时的同任务。09:10 的盘前预判过于提前，实际行情偏差大。

**结论**：待评估（可能冗余）——暂未删除，需观察。`premarket_pool.json` 被其他脚本依赖，删除该 cron 需同时检查下游退路。

### 案例3：连板天梯增强构建（2026-09-23，ladder-enhanced-builder）

输出分析：纯结构化 JSON 数据写入 `trading/data/ladder_enhanced_{date}.json`。从不推飞书。

**依赖链**：`intraday_hot_sector_sniper.py`（盘中天梯看板）、`sector_action_matrix.py`（板块战术矩阵）、`dragon_screener_engine.py`（真龙引擎）、`call_auction_scanner.py`（早盘竞价扫描器）都依赖这个 JSON 文件。无此数据，下游看板和引擎全部降级。

**结论**：基础设施，保留。✅
