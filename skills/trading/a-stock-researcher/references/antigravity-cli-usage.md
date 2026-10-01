# Antigravity CLI 使用指南

## 概述

Antigravity（agy）是部署在主机上的 LLM CLI 客户端。通过裸调 `agy`，可以绕过股票分析脚本的限制，进行大盘分析、市场研判等任何自定义分析任务。

## 安装位置

```
~/.local/bin/agy
```

## 基础用法

```bash
# 单次分析（最常用）
~/.local/bin/agy -p "你的问题" --dangerously-skip-permissions

# 连续对话
~/.local/bin/agy -c -p "你的问题" --dangerously-skip-permissions
```

- `-p`：prompt 内容（所有分析指令放在这里）
- `--dangerously-skip-permissions`：跳过确认（必须加，否则会中断等待输入）
- `-c`：连续对话模式（可选，后续调用 `agy -c` 继续上下文）

## 分析顺序优先级

1. **Antigravity CLI 裸调**（`agy -p "..." --dangerously-skip-permissions` 用于大盘/自定义分析）
2. **analyze_stock_with_antigravity.py 脚本**（适用于单只个股分析，会自动拉 MCP 数据拼 prompt）
3. **手动分析**（前两者都失败时）

## 适用场景

| 场景 | 推荐方式 | 原因 |
|------|---------|------|
| **个股深度分析** | `analyze_stock_with_antigravity.py 代码` | 脚本自动拉 MCP 行情+K线+新闻+缠论引擎数据拼 prompt |
| **大盘/指数分析** | `agy -p "大盘分析..."` 裸调 | 脚本只支持单只股票，大盘需要自定义 prompt |
| **自定义问题** | `agy -p "你的问题"` 裸调 | 不受脚本模板限制 |
| **分析多个标的比较** | `agy -p "比较XX和YY"` 裸调 | 脚本一次只能分析一个 |

## Python Bridge 接口

```python
from antigravity_bridge import ask_antigravity

# 简单调用
response = ask_antigravity("你的prompt", timeout=240)

# 连续对话
response = ask_antigravity("新的问题", timeout=240, continue_session=True)
```

## 注意事项

- 超时默认 240 秒
- 返回 stdout，如果是 JSON 模式用 `ask_antigravity_json()` 自动解析
- 返回 `[ANTIGRAVITY_ERROR]: ...` 表示失败，此时回退到手动分析
- `analyze_stock_with_antigravity.py` 脚本在 `/home/ubuntu/.hermes/scripts/analyze_stock_with_antigravity.py`
- `antigravity_bridge.py` 在 `/home/ubuntu/.hermes/scripts/antigravity_bridge.py`
