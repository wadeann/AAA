1|---
2|name: overnight-theme-arbitrage
3|title: 隔日题材套利 (Overnight Theme Arbitrage)
4|description: 捕捉"非主线但异动题材"的隔夜套利策略系统——盘前08:30四维扫描锁靶→09:25竞价共振确认→09:30-10:00起爆点狙击→次日T+1强制出局。专做低风险隔夜补涨套利，绝不恋战。
5|category: trading
6|trigger: 用户要求"盘中提前发现非主线异动题材"、"隔日套利"、"明天冲高卖"或涉及糖业/化工/贵金属/有色金属等商品期货映射题材时
7|tags: [overnight-arbitrage, theme-detection, premarket-scan, auction-resonance, t1-exit]
8|---
9|
10|# 隔日题材套利 (Overnight Theme Arbitrage)
11|
12|## 系统概述
13|
14|30年游资总舵主设计的隔夜套利自动化闭环，核心打法是 **"不追主线高位，提前埋伏低位异动题材，吃隔夜溢价"**。
15|
16|### 时间线 (2026-09-08 终版)
17|```
18|09:10 ─► 盘前四维唯真扫描 ──► premarket_pool.json
19|        (隔夜外盘+前日K线+日历+昨日连板天梯)
20|09:25 ─► 集合竞价共振确认 ──► active_triggers.json + 飞书弹窗
21|09:30-11:30, 13:00-14:50 ──► 盘中起爆点引擎(每10分钟) ──► intraday_signals.json
22|13:00 ──► 午间题材驱动扫描 ──► premarket_pool.json (覆盖午间消息催化)
23|14:00/14:15/14:30 ──► 尾盘拉板/偷袭共振检查 ──► 午后二龙补涨信号
24|次日 09:25-10:00 ──► T+1套利出局检测 ──► positions.json → 自动止盈
25|```
26|
27|## 核心脚本
28|
29|| 脚本 | 文件 | 运行模式 |
30||------|------|----------|
31|| 盘前题材预判扫描器 | `scripts/theme_arbitrage_scanner.py` | `--mode premarket` (08:30) / `--mode midday` (13:00) |
32|| 竞价共振/起爆/尾盘引擎 | `scripts/intraday_theme_trigger.py` | `--mode auction` / `--mode intraday` / `--mode tail` |
33|| 飞书推送 | `scripts/feishu_notifier.py` | 被以上脚本调用 |
34|| 盘中出击卡集成 | `scripts/intraday_hot_sector_sniper.py` | 09:35/10:15/11:15/14:15 (含隔日套利雷达模块) |
35|
36|数据目录: `~/.hermes/trading/theme_arbitrage/`
37|
38|## 四大扫描信号 (08:30 盘前)
39|
40|### 1. 隔夜外盘商品映射 (Overnight Commodity Mapping)
41|**⚠️ 08:30国内期货日盘未开盘，严禁查"今日涨幅"伪数据！**
42|- 用隔夜外盘收盘数据：ICE原糖、LME铜、WTI原油、COMEX金银
43|- 通过 `webx_search` 检索隔夜涨跌幅新闻 + 硬编码备选fallback值
44|- 内置映射库: 糖业(ICE原糖)、有色金属(LME铜)、贵金属(COMEX)、石油石化(WTI)、农林牧渔(CBOT)、基础化工(海外化工指数)
45|- 评分: 基础10分 + max(0, 涨幅) × 6, 上限25分
46|
47|### 2. 季节日历 (Seasonal Calendar)
48|- 8-10月: 双节备货 → 糖业 + 食品饮料
49|- 1-2月: 春节年货 → 预制菜/商贸零售
50|- 3月: 两会 → 新质生产力/高端制造
51|- 评分: 9月糖业25/食品18/其他15-23
52|
53|### 3. 前日K线异动 (K-line Infiltration)
54|- 同概念多只标的出现"缩量止跌阳线"或"尾盘抢筹企稳"
55|- 判断标准: 阳线 + 成交量比前日≤1.2(或涨幅>0且量比≤1.5)
56|- 通过 `fetch_kline(symbol, count=5, period="D")` 获取已收盘日线
57|- 评分: 基础10分 + 异动阳线数 × 3.5, 上限25分
58|
59|### 4. 主线情绪周期 (Mainline Sentiment)
60|- **禁止用 `get_mainline_lanes` 判断高低切**（那是盘中实时数据，08:30不可用）
61|- 改用昨日已收盘的 `get_limitup_ladder` 获取连板天梯最高板高度
62|- ≥4板 = 高标分歧期 → 资金高低切外溢(overflow_score=22)
63|- <4板 = 弱势震荡(overflow_score=15)
64|
65|## 打分模型 (满分100)
66|- 隔夜外盘: ≤25分
67|- 季节日历: ≤25分
68|- 情绪周期: ≤22分
69|- K线异动: ≤25分
70|
71|## 13:00 午间驱动扫描 (--mode midday)
72|下午题材可能由于午间消息突发催化，在13:00后"睡醒拉板"。
73|- 用 `search_news("午间 突发 利好 A股")` 检索午间催化
74|- 内置下午高爆发概率题材池（医药生物/糖业/超跌赛道）
75|- 评分从上午实际走势数据计算
76|- 输出覆盖 premarket_pool.json，供下午尾盘共振检查使用
77|
78|## 竞价共振门槛 (09:25)
79|同题材 ≥**2只** 同时触发:
80|- 竞价金额比 >**昨全天成交额8%**
81|- 高开 **+2% ~ +5%**
82|- 或一字涨停封板(金额比≥5%)
83|
84|## 盘中起爆战法 (全时段 09:30-11:30 + 13:00-14:50)
85|
86|### 战法A: 首板封死·二龙补涨
87|龙头涨停封死后，同题材第二只涨 +4%~+6%未封板 → 立即推送补涨买入
88|
89|### 战法B: 放量突破前高
90|开盘放量突破昨日前高 + 量比>2 + 换手>3% → 确认起爆买点
91|
92|推荐仓位: 15%~20% 机动仓位
93|止损: 买入价 -3.5% 硬止损
94|
95|## 午后/尾盘共振检查 (--mode afternoon / --mode tail, 13:00-14:50)
96|**⚠️ BUG 2026-09-08 发现并修复: 原设计09:30-10:00后关机，遗漏下午和尾盘涨跌！**
97|
98|主力拉板块不限于上午:
99|- 13:00-14:00: 经典"午觉醒来偷袭拉板块"窗口
100|- 14:30-14:50: 游资最小成本偷袭板/高举高打周期
101|
102|午后/尾盘共振触发条件:
103|- 同题材 ≥2 只个股异动（涨幅+3.5%~+7.0%或封死涨停）
104|- 首板封死 → 第二只+4%~+6%未封板 → 立即推送尾盘补涨买入
105|- 信号类型: `AFTERNOON_LAGGARD_SNIPER` / `AFTERNOON_RESONANCE_BREAKOUT`
106|- 仓位: 15% (尾盘偷袭机动仓，严控回撤)
107|
108|## T+1出局军规
109|- 竞价高开 >5%: 开盘直接挂单卖出1/2
110|- 盘中冲高回落(距最高回撤>2%) 或封板失败: 全部出清
111|- 隔夜套利绝不恋战! 平均持仓: 1夜
112|
113|## Cron Jobs (全24小时覆盖 - 实际通过Hermes cronjob注册)
114|```bash
115|# 09:10 → 盘前唯真扫描 (隔夜外盘+前日K线+日历+昨日连板天梯) — 用户要求09:10
116|10 9 * * 1-5 cd /home/ubuntu/.hermes/scripts && python3 theme_arbitrage_scanner.py --feishu
117|
118|# 09:25 → 竞价共振确认
119|25 9 * * 1-5 cd /home/ubuntu/.hermes/scripts && python3 intraday_theme_trigger.py --mode auction --feishu
120|
121|# 09:30-14:50 盘中起爆 (每10分钟)
122|*/10 9-11,13-14 * * 1-5 cd /home/ubuntu/.hermes/scripts && python3 intraday_theme_trigger.py --mode intraday --feishu
123|
124|# 13:00 → 午间驱动扫描
125|0 13 * * 1-5 cd /home/ubuntu/.hermes/scripts && python3 theme_arbitrage_scanner.py --mode midday --feishu
126|
127|# 14:00/14:15/14:30 → 尾盘拉板/偷袭共振专用扫描
128|0,15,30 14 * * 1-5 cd /home/ubuntu/.hermes/scripts && python3 intraday_theme_trigger.py --mode tail --feishu
129|```
130|
131|## Pitfalls
132|- 非交易日不能跑竞价相关脚本（MCP会返回空数据）
133|- 竞价金额比>8%门槛在日成交额极低(<3000万)的标的需要放宽至5%
134|- **⚠️ 08:30严禁查国内期货"今日涨幅"(日盘09:00才开盘)**——必须用`OVERNIGHT_COMMODITY_MAP`(隔夜外盘)+`webx_search`+硬编码fallback
135|- **⚠️ 起爆引擎必须覆盖全天交易时段(09:30-11:30 + 13:00-14:50)**——下午/尾盘是主力经典拉板块窗口
136|- **⚠️ 别忘了13:00午间扫描**——午间消息催化是下午异动的关键触发器
137|- 非交易日做验证时，用硬编码fallback值跑通即可，不需要真数据
138|- 题材池需在08:30-09:25之间持续有效，过了09:30不再使用盘前数据
139|- ST股票不可做标的，scanner里用*ST广糖做题材锚没问题但实际下单排除
140|- 高开>5%的标的不能追（利润空间不足，且可能是高开低走）
141|- `--mode auto` 模式按当前时间自动选择: 09:20-09:29走auction, 13:00-14:50走tail, 其余走intraday
142|- **⚠️ cron `no_agent`+`workdir` 必设**：注册cron时必须设 `--no-agent` 和 `--workdir /home/ubuntu/.hermes/scripts`。`no_agent=false`模式下script字段的Python脚本不是直接执行，而是作为LLM prompt上下文，agent可能找不到文件报"脚本未找到"。修复：`hermes cron update job_id --no-agent --workdir /home/ubuntu/.hermes/scripts`。验证：`hermes cron run job_id` 检查stdout是否脚本原样输出。
143|- **⚠️ 审计发现的AGY编码BUG** (2026-09-08): AGY多轮写入可能导致重复函数定义(`run_afternoon_resonance_check`和`format_afternoon_alarm`各定义两次)和重复`import`语句。修改代码后务必执行`python3 -m py_compile`全量语法检查+运行验证