# Intent 审批链 — 代码级强制执行

> 2026-06-05 实现：exec_server + risk_server 联动，从代码层面杜绝绕过风控下单

## 背景

本周复盘发现 4 笔建仓全部绕过了风控审批链（研究员→策略员→风控员→执行员），`~/.hermes/trading/intents/` 目录为空。行业集中度接近 70%，远超 40% 红线。

根本原因：`place_order` 没有任何前置校验，任何人/流程都可以直接下单。

## 实现方案

### exec_server 改动 (`/home/ubuntu/ai/pup-mcp/exec_server/main.py`)

1. **新增 `approved_intents` 表**：
   ```sql
   CREATE TABLE IF NOT EXISTS approved_intents (
       intent_id TEXT PRIMARY KEY,
       symbol TEXT NOT NULL,
       direction TEXT NOT NULL,
       max_quantity INTEGER NOT NULL,
       approved_at TEXT NOT NULL,
       expires_at TEXT NOT NULL,
       risk_status TEXT NOT NULL DEFAULT 'approved'
   )
   ```

2. **新增 `register_approved_intent()` 方法**：注册已审批 intent，供 risk_server 调用

3. **新增 `verify_approved_intent()` 方法**：
   - 清理过期 intent
   - 查询 intent_id 是否存在且状态为 approved
   - 校验方向匹配、数量不超限

4. **`place_order()` 增加强制校验**：
   - `intent_id` 改为必填参数
   - 不传 → 返回 `MISSING_INTENT_ID`
   - 未注册 → 返回 `INTENT_NOT_REGISTERED`
   - 状态不对 → 返回 `INTENT_NOT_APPROVED`
   - 方向不匹配 → 返回 `DIRECTION_MISMATCH`
   - 数量超限 → 返回 `QUANTITY_EXCEEDS_LIMIT`

5. **`place_order()` 签名变更**：
   ```python
   # 旧
   def place_order(self, symbol, side, qty, price):
   # 新
   def place_order(self, symbol, side, qty, price, intent_id=None, reason=""):
   ```

6. **MCP tools/list 变更**：
   - 新增 `register_approved_intent` 工具
   - `place_order` 的 `intent_id` 改为 required 参数

### risk_server 改动 (`/home/ubuntu/ai/pup-mcp/risk_server/main.py`)

1. **`batch_check()` 自动注册**：审批通过后自动生成 `INTENT-{uuid12}` 并 HTTP 调用 exec_server 注册
2. **`_register_to_exec()` 方法**：通过 `urllib3` POST 到 exec_server `register_approved_intent`
3. **行业集中度阈值修正**：从 30% 改为 40%，对齐全局风控规则第5条

### 审批链完整流程

```
研究员 → 策略员 → 风控员调用 batch_check
                         ↓
                  check_intent() 审批
                         ↓ approved=True
                  生成 intent_id (INTENT-xxxxxxxxxxxx)
                         ↓
                  _register_to_exec() → exec_server register_approved_intent
                         ↓
                  返回 {approved:True, intent_id, exec_registered:True}
                         ↓
执行员 place_order(intent_id=...) → verify_approved_intent() → 通过 → 下单
```

## 验证清单

- [ ] 不带 intent_id 下单被拒绝
- [ ] 带未注册 intent_id 下单被拒绝
- [ ] batch_check approved 后自动注册成功
- [ ] 带有效 intent_id 下单成功
- [ ] 过期 intent_id 被自动清理
