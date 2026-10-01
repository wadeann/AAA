# 信号发现到实盘盈利的归因契约

## 目的

防止把“选对股票”“发出买入提示”“写入观察仓”误报为真实盈利。任何策略复盘必须分开评价：

1. **发现质量**：是否在上涨前预先识别标的与逻辑；
2. **计划质量**：是否同时给出入场、止损、减仓/止盈、仓位和弃买条件；
3. **执行质量**：是否形成结构化 candidate/TradeIntent、通过风控并产生真实订单；
4. **退出质量**：是否持续跟踪并按规则卖出；
5. **实际收益**：仅按券商成交记录计算。

发现成功但无真实成交时，结论必须写成：**“研究成功、执行失败、实际收益为0”**，不得使用“盈利”“抓住”“持仓获利”等措辞。

## 最小数据状态机

```text
signal_detected
  -> shadow_candidate
  -> candidate
  -> risk_approved / risk_rejected
  -> order_submitted
  -> order_filled
  -> holding_real
  -> exit_order_filled
  -> realized_outcome
```

- `signal_detected`、`shadow_candidate`：研究样本，不代表成交。
- `candidate`：具备完整价格计划，但仍不代表成交。
- `holding_real`：必须有 `order_id`、`filled_price`、`quantity > 0`。
- `realized_outcome`：必须由真实买卖成交配对计算。

禁止把推送信号直接写成 `HOLDING`。未成交跟踪记录统一使用：

```json
{
  "record_type": "shadow_position",
  "status": "SIGNAL_ONLY",
  "quantity": 0,
  "order_id": null,
  "filled_price": null
}
```

卖出监控只能消费满足以下全部条件的记录：

```text
status == HOLDING_REAL
order_id 非空
quantity > 0
```

## 单票回测模板

对预先记录的信号使用其当时生成的价格，不允许事后选择最优入场：

- `entry_price`：原始信号价或原始买入区间内预先规定的成交模型；
- `stop_price`：原始止损；
- `target_price`：原始第一减仓价；
- `MAE`：入场后、退出前最低价相对入场价；
- `MFE`：入场后、退出前最高价相对入场价；
- `R = entry_price - stop_price`；
- `MFE_R = (最高价-entry_price)/R`；
- 明确目标何时首次触发、止损是否先触发，避免只看最终涨幅。

如果没有真实成交：
- 结果记为 `shadow_outcome`；
- 实际收益固定为0；
- 不进入实盘胜率与物理熔断统计；
- 可进入研究层的影子样本统计。

## 可复用策略固化门槛

单个成功案例只能证明“存在前瞻有效性”，不能证明稳定可复用。固化前至少需要：

- 5个以上预先记录且无未来函数的同规则样本；
- 统一入场、止损、退出模型；
- 同时记录成功和失败样本；
- 输出胜率、平均盈亏比、最大MAE、期望值和样本数；
- 区分市场阶段与板块共振强度。

## 推送输出契约

每个可执行信号必须在同一条消息中展示：

- 股票名称与代码；
- 买入触发价/区间；
- 止损或清仓价；
- 第一减仓价；
- 初始仓位与总仓上限；
- 触发条件；
- 弃买条件；
- 执行状态：`仅计划/风控通过/已报单/已成交`。

禁止使用“按市价买入”“已经锁定利润”等文案，除非存在可核验订单或成交回报。

## 复盘根因分类

- `data`：行情、板块、订单证据缺失或错误；
- `judgment`：选股或买卖逻辑错误；
- `execution`：有计划但未下单、下单失败或成交偏差；
- `system`：状态机、候选写入、风控路由、成交回写断裂。

发现层正确而未盈利时，优先检查 `candidate -> risk -> order -> fill -> exit` 的断点，不应继续调选股参数掩盖执行问题。