# 子agent审计17模块模式 (2026-09-14)

## 背景
AGY二进制在长任务(读代码+修复)时无声死锁——进程running但output_preview永远为空。短prompt("hi")秒回。
改用 delegate_task 子agent取代AGY完成全量审计。

## 参数模板

```python
delegate_task(
    goal="从剩余模块选1个审计。已审完可跳过:[列表] 选1个。读代码、找P0/P1 Bug、用patch修、py_compile、git commit。输出报告。",
    context="自动化审计Agent。shell+文件读写。直接修+git commit。不用确认。",
    toolsets=['terminal', 'file']
)
```

## 关键参数
- toolsets: ['terminal', 'file'] — 子agent需要有shell(运行py_compile/git)和文件读写
- goal: 包含"已审完可跳过列表" + "选1个" + "读代码、找Bug、patch修、py_compile、git commit、输出报告"
- context: 简短(50 chars以内)，描述子agent的行为模式
- goal中的已审完列表要逐轮更新

## 性能数据
- 17个模块总耗时: ~ 75分钟
- 平均每个模块: ~ 4.5分钟
- 最快: tdx_pullback_scanner (154s, 2个Bug)
- 最慢: direct_executor / sector_action_matrix / close_session_scan (~530s, 含多个复杂Bug)
- 超时: 仅1个(morning_master_orchestrator 600s超时, 但在超时前已完成git commit)
- 总计修复Bug: 31+个(P0 * 十几个 + P1 * 十几个)

## 子agent审计发现的关键Bug类型
1. P0 import缺失 → 安全守卫静默失败（整个执行层零保护）
2. P0 评分天花板<及格门槛（数学上永远不及格）
3. P0 字段名不统一（ladder vs ladders, 复数丢失映射）
4. P0 死代码（配置了参数但从未被执行）
5. P0 falsy陷阱（0 or -1 = 封板股票永远判为未封板）
6. P0 回退调用参数完全错误（cancel_order调成place_order参数）
7. P1 单位换算虚高10倍（cap_mult=15 vs 1.5）
8. P1 涨停判度阈值静态绝对值（高价太紧密低价太松）
9. P1 数据缺失静默放行（无数据时默认通过而非否决）
10. P1 MCP重复调用（每次持仓查两次query_data）
