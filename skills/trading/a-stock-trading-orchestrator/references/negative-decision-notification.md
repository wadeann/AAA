# 09:25 非买入通知：诊断与验收

## 适用场景

09:25 已完成竞价和风控决策，但用户没有收到“非买入/禁止新增买入”通知。常见业务结论包括持仓数量达到上限、情绪熔断、只卖不买、候选未通过门禁。

## 典型断链

```text
早盘调度器得出 blocked
  -> 跳过买入扫描
  -> 主任务 deliver=local，仅写日志
  -> 辅助竞价任务无买点时输出 wakeAgent=false
  -> watchdog 补跑辅助任务，但仍进入静默分支
  -> cron 均显示 ok，用户仍未收到消息
```

核心判断：`decision_ok != delivery_ok`，`watchdog_retriggered != user_notified`。

## 排查顺序

1. 查权威早盘调度器日志，确认实际决策与量化原因。
2. 查该任务的 `deliver` 目标；`local` 不会送达飞书。
3. 查辅助脚本无信号分支，识别空 stdout、`wakeAgent=false` 或仅在 actionable 时发送。
4. 查 watchdog：它补跑了哪个任务，补跑任务是否仍会静默。
5. 查通知函数返回值或平台 API 结果，不能以函数被调用代替发送成功。

## 修复模式

在权威09:25调度器中增加确定性 fallback：

```python
if guard_blocked:
    reason = parsed_guard_reason
    message = build_non_buy_notice(reason, position_names)
    ok = send_feishu_message(message)
    print(message)  # 审计留痕
```

不要把 fallback 放在“只负责发现买点”的辅助任务中。辅助任务天然可能对非 actionable 结果保持静默。

## 消息格式

最多3行：

```text
📊竞价09:25
📌非买入：持仓上限3只已满
✅持有 华瓷股份(001216)、华纺股份(600448)、新宏泽(002836)
```

必须包含明确结论和原因；有持仓时带中文名和代码。不要只发“无信号”，因为用户需要知道系统完成了决策，而不是任务没运行。

## 验收证据

至少同时具备：

- 单元测试：blocked 分支调用通知器，消息包含“非买入”和原因。
- 格式测试：不超过3行，中文名与代码可读。
- 真实发送：通知器/OpenAPI 返回成功。
- 审计日志：stdout 留存同一消息。
- 次日自然调度验证：09:25 实际分支触发时能送达。

## Before / After 表述

- Before：风控阻断 -> 仅本地日志/静默标记 -> 用户无通知。
- After：风控阻断 -> 权威调度器即时直发 -> stdout留痕 -> API成功回执。
