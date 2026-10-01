# 涨停观察池实施参考

## 最小机器契约

观察记录至少包含：

- `record_type: observation`
- `observation_id: YYYY-MM-DD:SYMBOL`
- `date`, `symbol`, `name`, `sector`
- `limit_up_days`, `limit_up_reason`, `close_price`, `turnover_amount`
- `mainline_confirmed`
- `status: awaiting_open_confirmation`
- `technical_confirmed: false`
- `fundamental_confirmed: false`
- `chan_buy_point: null`

升级为候选时必须补齐：

- `record_type: candidate`
- 稳定 `candidate_id`
- `direction`, `price`, `quantity`, `confidence`
- `thesis`, `entry_rule`
- `chan_buy_point`, `volume_confirmed`, `sector_confirmed`
- `fundamental_confirmed`, `realtime_confirmed`
- `valid_until` 和失效条件

## 运行顺序

1. 收盘脚本抓取涨停与板块数据，写 observation，不下单。
2. 次日开盘脚本读取 observation，查询实时行情和 5 分钟 K 线。
3. 只有完整证据通过才写 candidate；过滤也要写 candidate_event。
4. 统一交易闸门读取 candidate，先研究闸门，再 risk_batch_check；默认 dry-run。
5. 每个阶段必须检查实际退出码、产物存在、JSONL 可解析和记录数量，不能只看 cron 的 last_status=ok。

## 写入失败处理

大段文本写入被中断时，不要声称文件已经创建，也不要连续重复同一写入调用。先用只读检查确认目标文件是否存在，再缩小变更或使用补丁/标准文件接口；成功标准是文件 stat/readback、语法检查和实际 dry-run 输出全部可见。