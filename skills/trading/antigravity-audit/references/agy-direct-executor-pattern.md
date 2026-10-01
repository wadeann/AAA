# 即时响应执行器（Direct Executor）模式

## 动机
传统交易系统依赖固定闸门（如10:55、14:50定时触发），候选产生后等待闸门轮次才能执行，延迟高达45分钟。这对打板和追涨是致命的。

## 设计
direct_executor.py 作为**cron守护**运行（每2分钟），盘中轮询候选池的AGY approval候选并立即执行。

## 数据流
```
候选写入 candidate_{date}.jsonl
    ↓
direct_executor (每2分钟 cron)
    ↓
1. load_processed_ids() → 读取已执行event，防重复
2. 过滤 AGY approved + 未处理 + 通过T1方向冲突
3. 分批取前2笔 → normalize_intent → risk_check_and_execute
4. 写入candidate_event记录（executed/risk_blocked/t1_conflict）
```

## 关键参数
- **BATCH_SIZE = 2**: 每次最多2笔，防风控接口阻塞导致全部瘫痪
- **盘中时段**: 09:30-11:30 / 13:00-14:50
- **防重复机制**: 从candidate.jsonl读取所有candidate_event记录，对executed/risk_blocked/t1_conflict状态的候选跳过

## cron配置
```
*/2 * * * 1-5 cd /home/ubuntu/.hermes/scripts && python3 direct_executor.py >> /tmp/direct_executor.log 2>&1
```

## 边界条件
1. **卖出候选**: `entry_rule`为空字符串导致is_trade_ready拒绝 → 修复在R27: `if direction == "buy"`条件化
2. **name字段空**: call_auction_scanner生成候选时name为空 → mediator方案：运行时调用query_batch_data补全
3. **候选池满**: 多cron同时写入候选，direct_executor读取时可能看到局部状态 → 每次重新加载candidates文件
4. **风控慢**: risk_check对某些候选(如江西铜业)卡住 → 分批策略防止全局阻塞
5. **同标的重复买入**: 同一candidate_id被两个cron同时处理 → 基于candidate_event的事后标记 vs 信号量如RR(需要一个全局锁)——当前方案是写event后再次加载processed_ids，下次cron轮次跳过
