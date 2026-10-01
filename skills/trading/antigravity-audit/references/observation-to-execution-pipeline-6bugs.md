# 观察型脚本 → 实战执行管道改造的 6 个复现性 Bug（AGY 审计 2026-09-23）

## 场景
把只推送看板的盘中脚本（intraday_hot_sector_sniper.py）升级为"识别买点→写入候选池→风控→真实下单"的实战执行引擎时，AGY 审计 4 轮闭环，发现 6 个复现性 P0/P1 bug。这些是"观察→执行"改造的通用陷阱，任何同类脚本升级都应预扫。

## 审计轮次
- Round 1：发现 P0-1 双执行、P0-2 穿透去重、P0-3 死仓、P1-1 字段误杀
- Round 2：4 项修复全部通过
- Round 3：发现 P1-2 量纲错、P1-3 并发写
- Round 4：2 项通过 + AGY 签署验收

## 6 个 Bug 清单（每项含判别模式）

### P0-1 双执行（最危险）
**症状**：脚本自调 `risk_check_and_execute(dry_run=False)` 真实下单，同时定时执行器 `direct_executor` 每 2 分钟扫同一 `candidates.jsonl` 再次下单 → 同一信号下两次单。
**根因**：报单权分散在两处。脚本既投递候选又自己执行。
**修复**：**只写候选到 JSONL，自调下单逻辑彻底删除**。报单权完全收敛交给统一执行器（direct_executor）。
**判别**：grep 脚本里是否有 `risk_check_and_execute` / `place_order` 调用——有则检查是否与常驻执行器重叠。

### P0-2 穿透去重（candidate_id 时间戳）
**症状**：`candidate_id` 用 `HHMMSS` 时间戳，同一天同标的 5 分钟内两次扫描生成不同 ID，穿透 `dedup_append` 的实体主键去重 → 重复生成候选。
**修复**：改为**稳定 ID** `iss-{symbol}-{date}`，同一天同标的只有一条，配合 `utils_candidate.dedup_append` 防重。
**判别**：`candidate_id` 若含 `strftime('%H%M%S')` 或 `timestamp` → 必是穿透漏洞。稳定 ID 必须 = 业务主键（symbol+date+direction）。

### P0-3 硬编码 quantity=100 死仓
**症状**：`quantity: 100` 硬编码。执行器对买单只做现金/持仓上限校验、**不重算股数** → 100 股死仓，白白消耗一个持仓名额（系统上限 5 只），20% 目标仓位完全失效。
**修复**：写候选前先拉 `get_balance`/`get_positions`（Exec MCP 9003）算 `total_assets`，`qty = total_assets*0.20/price` 百股向下取整。
**关键**：**风险校验只校验不重算**——不能依赖执行器修正 quantity，写候选时就要算对。
**判别**：candidate dict 里 `quantity` 是否为字面量 100 / 是否未从账户快照推导。

### P1-1 字段缺失 kill-all（资金过滤误杀）
**症状**：`main_net = float(flow['data'].get('MainNetFlow', 0) or 0)`，若接口返回结构无 `data` 或无 `MainNetFlow`，`main_net=0` → `if main_net > 0` 全部过滤 → 候选被误杀清零。
**修复**：**Fail-Open（降级放行）**。引入显式 `got_data` 布尔：仅当 `MainNetFlow` 有效解析出且确属净流出时才拦截；字段缺失/解析异常/接口不可用时 `got_data=False` → 保留候选不过滤。
**判别**：`if X > 0: keep else: filter`，当 X 来自可能缺失的外部字段时，默认 0 会走 filter 分支 → 误杀。字段缺失时应 Fail-Open，数据确认净流出才过滤。

### P1-2 量纲错误（round 后归零）
**症状**：`amount_yi = cur_p * 10000 / 1e8 = cur_p/10000`，对 10 元股 = 0.001，`round(...,2)` 后 = 0.00 → 按成交额排序彻底失效，退化为仅按量比排序。
**修复**：取数据源返回的真实成交额字段（万元），无数据时用量比×价格×500万估算，`amt_w / 1e4` 转亿。
**判别**：`round(值, 2)` 前反算值域——若分母/乘数导致结果恒 < 0.005 则 round 后必为 0。单位换算：万→亿 = ÷1e4（不是 ÷1e8）。

### P1-3 并发写坏（非原子写入）
**症状**：`out_file.write_text(...)` 直接覆盖。多进程并发或下游读取时，写入先截断文件 → 读到 0 字节或残缺 JSON → 崩溃。
**修复**：**tmp + os.replace 原子写入**：
```python
tmp_file = out_file.with_suffix(".json.tmp")
tmp_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
tmp_file.replace(out_file)  # POSIX os.replace 原子重命名
```
**判别**：全脚本 grep `\.write_text(`——若未配 `.tmp` + `.replace` → P1 并发隐患（尤其是 cron 多次触发的脚本）。

## 排查清单（观察→执行改造时逐项过）
1. grep `risk_check_and_execute|place_order` → 与常驻执行器是否重叠（双执行）
2. `candidate_id` 是否含时间戳 → 是否穿透去重
3. `quantity` 是否从账户快照推导 → 是否死仓
4. 外部字段缺失时默认值是否触发误杀分支 → 应 Fail-Open
5. `round(x,2)` 前反算值域 → 是否量纲归零
6. `write_text` 是否原子写入 → 是否并发写坏

## 验证方式
- `python3 -m py_compile file.py` 语法通过
- 构造候选调用 `emit_candidates_and_execute`，确认稳定 ID、正确 quantity、只写不执行
- `--force` 非交易时段跑全脚本，确认防守看板无回归