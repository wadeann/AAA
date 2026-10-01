# MCP自主交易闭环参考

## 目标

区分“盘中通知”和“可执行候选”。突破预警不应直接下单；回踩确认且新闻、基本面和账户条件齐全后，才生成 `candidate` 并进入交易闸门。

## 推荐顺序

`trading_sessions -> risk_batch_check -> get_balance/get_positions -> register_approved_intent -> place_order -> get_orders`

风控全部拒绝时，直接返回，不查询账户、不下单。账户或持仓快照失败时 fail closed。

## 幂等

用候选ID和intent ID建立执行台账。以下终态必须阻止重复执行：`submitted`、`submitted_unverified`、`failed`、`execution_skipped`、`simulated`。

## 状态与通知

- `alert`: 放量突破中枢，通知“等待回踩”，不进入交易候选。
- `confirmed`: 二买/三买回踩确认，补查新闻与基本面，证据齐全才写候选。
- 过期信号只用于复盘，不得重新生成当前候选。

## 回测与测试

按逐根30分钟K线截断回测，禁止使用未来K线。必须分别验证：突破预警时间、确认时间、信号年龄、重复轮询去重。Mock MCP执行链应验证风控、余额/持仓、intent注册、下单和订单回查的调用顺序。

## 收益

日终快照写入JSONL；周/月收益以区间起始快照和当前快照计算。当前累计盈亏不能替代区间收益。