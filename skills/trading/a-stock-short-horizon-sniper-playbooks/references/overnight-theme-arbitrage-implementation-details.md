1|# 隔日题材套利系统 - 实现参考
2|
3|## AGY设计的完整架构 (2026-09-08)
4|
5|### 三次迭代修复记录
6|
7|**V1 (初始版)**: 含三大BUG
8|- BUG1: 08:30 用wencai_search查期货"今日涨幅"(国内日盘09:00才开)
9|- BUG2: 起爆引擎只在09:30-10:00运行
10|- BUG3: 无下午/尾盘共振检查
11|
12|**V2 (修复版, 2026-09-08)**:
13|- ✅ 08:30 → 隔夜外盘 + 前日K线 + 日历 + `get_limitup_ladder` 连板天梯
14|- ✅ 起爆引擎覆盖 09:30-11:30 + 13:00-14:50
15|- ✅ 新增 `--mode midday` 午间驱动、`--mode tail` 尾盘共振
16|
17|### 数据流
18|```\n盘前08:30 (隔夜外盘+K线+日历+连板天梯) ──┐
19|季节日历 ─────────────────────────────┤──► theme_arbitrage_scanner.py ──► premarket_pool.json
20|前日K线异动 ───────────────────────────┤       (--mode premarket 08:30)
21|                                        │       (--mode midday 13:00)
22|午间13:00 (新闻催化+上午异动数据) ────┘
23|                        │
24|                    query_batch_data ──► intraday_theme_trigger.py ──► active_triggers.json
25|                                           (09:25 --mode auction)
26|                        │
27|                    query_batch_data ──► intraday_theme_trigger.py ──► intraday_signals.json
28|                    fetch_kline             (09:30-11:30 + 13:00-14:50 --mode intraday)
29|                        │
30|                    query_batch_data ──► intraday_theme_trigger.py ──► positions.json
31|                                           (14:00/14:15/14:30 --mode tail)
32|                        │
33|                    check_t1_exit_signals() ──► T+1套利出局
34|```
35|
36|### MCP调用模式
37|所有脚本使用标准原生MCP调用函数:
38|```python
39|def mcp_call(tool, arguments, port=9001, timeout=15):\n    payload = json.dumps({\n        \"jsonrpc\": \"2.0\", \"method\": \"tools/call\", \"id\": 1,\n        \"params\": {\"name\": tool, \"arguments\": arguments}\n    }).encode()\n    req = urllib.request.Request(\n        f\"http://localhost:{port}/mcp\", data=payload,\n        headers={\"Content-Type\": \"application/json\"}\n    )\n    resp = json.loads(urllib.request.urlopen(req, timeout=timeout).read())\n    text = resp[\"result\"][\"content\"][0][\"text\"]\n    return json.loads(text)\n```\n\n### 隔夜外盘商品映射库 (OVERNIGHT_COMMODITY_MAP)
40|```python\nOVERNIGHT_COMMODITY_MAP = [\n    {\"keywords\": [\"糖\",\"白糖\",\"原糖\",\"ICE原糖\"], \"theme\": \"糖业\",\n     \"symbols\": [\"000523.SZ\",\"000833.SZ\",\"600737.SH\",\"000911.SZ\",\"600191.SH\",\"002286.SZ\"],\n     \"fallback_chg\": 2.41},\n    {\"keywords\": [\"铜\",\"伦铜\",\"LME铜\"], \"theme\": \"有色金属\",\n     \"symbols\": [\"601899.SH\",\"600362.SH\",\"000807.SZ\",\"000878.SZ\"],\n     \"fallback_chg\": 1.25},\n    {\"keywords\": [\"金\",\"银\",\"COMEX黄金\"], \"theme\": \"贵金属\",\n     \"symbols\": [\"600988.SH\",\"600547.SH\",\"002155.SZ\",\"600489.SH\"],\n     \"fallback_chg\": 0.85},\n    {\"keywords\": [\"原油\",\"WTI原油\",\"布伦特原油\"], \"theme\": \"石油石化\",\n     \"symbols\": [\"601872.SH\",\"600026.SH\",\"002207.SZ\",\"600938.SH\"],\n     \"fallback_chg\": 1.15},\n    {\"keywords\": [\"甲醇\",\"纯碱\",\"尿素\",\"海外化工\"], \"theme\": \"基础化工\",\n     \"symbols\": [\"002470.SZ\",\"000912.SZ\",\"002312.SZ\",\"600227.SH\",\"000830.SZ\"],\n     \"fallback_chg\": 0.70},\n    {\"keywords\": [\"大豆\",\"玉米\",\"美豆\",\"生猪\"], \"theme\": \"农林牧渔\",\n     \"symbols\": [\"002714.SZ\",\"300498.SZ\",\"603477.SH\",\"000735.SZ\"],\n     \"fallback_chg\": 0.65},\n]\n\n# 08:30扫描方法：通过webx_search检索隔夜新闻，匹配涨幅关键词；无数据时用fallback_chg\n```\n\n### 实际运行验证 (2026-09-08 17:41 非交易日测试，修复版)
41|```\n盘前锁定第一隔日套利靶向：【糖业】 (总分96.5分)\n  隔夜外盘: 24.5/25  |  季节日历: 25.0/25\n  情绪周期: 22.0/22  |  K线异动: 25.0/25\n\n候选标的: 红棉股份(领涨龙), 粤桂股份(补涨), 中粮糖业(领涨龙),\n          *ST广糖(中军), 华资实业(补涨), 保龄宝(中军)\n\n注: 降ve1由于隔夜外盘fallback使用ICE原糖+2.41%的硬编码备选值，\n结合9月双节+连板天梯4板+前日缩量阳线，总分比V1提高8.8分\n```\n\n### 审计发现与修复记录 (2026-09-08 第二轮)
42|
43|**审计项1: 重复import**
44|- `theme_arbitrage_scanner.py` 中 `import re` 被写了两次 (line 31 和 line 65)
45|- 修复: 删除 line 65 的重复导入，`re` 已在头部导入
46|
47|**审计项2: 重复函数定义**
48|- `intraday_theme_trigger.py` 中 `run_afternoon_resonance_check` 和 `format_afternoon_alarm` 各定义两次
49|- 第一次定义 (lines 497-632): 手动patch进去的初版，缺少 prior_high 前高突破判断
50|- 第二次定义 (lines 681-849): AGY后续直接写入的进阶版，有完整前高突破逻辑
51|- 修复: 删除初版定义，保留进阶版 + docstring更新
52|
53|**审计项3: 时间调整**
54|- 盘前扫描时间: 08:30 → 09:10 (用户要求)
55|- 盘中起爆轮询: 每5分钟 → 每10分钟 (减少飞书推送频率)
56|
57|**Root cause**: AGY多轮 --print 写入会导致旧代码+新版本共存。修改AGY编码后必须:
58|1. 执行 `python3 -m py_compile <file>` 语法检查
59|2. 使用 `grep "^def " <file>` 检查是否有重复函数定义
60|3. 完整测试所有 --mode
61|```bash\n# 午后共振检查\npython3 intraday_theme_trigger.py --mode tail\n\n# 午间驱动扫描\npython3 theme_arbitrage_scanner.py --mode midday\n```\n\n### 已知问题\n- ASCII艺术边框在飞书富文本中显示正常（等宽字符对齐）\n- 飞书Webhook URL从环境变量 `FEISHU_WEBHOOK_URL` 读取\n- `--feishu` 开关交给各脚本main()解析\n- 非交易日盘后运行scanner时，隔夜外盘数据用fallback硬编码值\n- 旧版FUTURES_THEME_MAP已废弃，不可再用\n- 旧版`run_premarket_theme_scan()`已替换为分mode调用",
62|