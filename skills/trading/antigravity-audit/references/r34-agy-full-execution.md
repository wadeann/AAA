# AGY R34全栈执行 — 2026-09-02 session记录

## 背景
用户要求AGY一次性完成P0-P2全部任务（P0三修+P1四改+P2三改），从分析模式切换为执行模式。

## 调用方式
```python
from antigravity_bridge import ask_antigravity

# 必须传全量系统状态给AGY才能独立做代码修改
prompt = f"""
# AGY全栈执行任务

## 系统状态
策略参数: {json.dumps(strategy_params, indent=2)[:1500]}

## 关键文件内容（节选核心段）
- direct_executor.py 第197-209行
- pipeline.py 第218-233行（is_trade_ready）
- pipeline.py 第555-558行（仓位上限）
"""

# timeout=600（10分钟），因为AGY要做多文件修改
result = ask_antigravity(prompt, timeout=600)
```

## 输入要求
AGY做代码执行需要知道的上下文：
1. 策略参数（strategy_params.json完整内容）
2. 待修改文件的关键代码段（直接贴代码给AGY看，不要只给路径）
3. 当前持仓（让AGY知道系统状态）
4. P0/P1/P2完整任务描述（代码级精确要求）

## 关键教训
- timeout=600是必须的（单次AGY调用做代码生成需要5-10分钟）
- 用background模式跑（否则终端600s超时限制）
- 如果AGY不需要读文件（任务明确已知），直接一次性给全量上下文比分多次调用更好
- 不要在terminal的heredoc里塞太复杂的Python——这会导致审核被拒

## 对应AGY审计报告
见 `references/agy-strategy-architecture-review.md`

## R34已做P0修复清单
1. direct_executor.py: 删除is_strong_leader特权后门（第197-209行改为direction分支）
2. pipeline.py is_trade_ready: cooldown+buy直接return False（删除特权放行）
3. pipeline.py 缠论分支: 卖出方向剥离chan_sell_point/chan_confirmed校验
4. pipeline.py risk_check_and_execute: 仓位上限删除is_super_leader特权
