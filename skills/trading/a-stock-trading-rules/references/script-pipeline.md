# 脚本管道 (Script-First Pipeline)

CE 方法论「脚本优先架构」的具体实现。三个 Python 脚本替换模型在内存中做确定性计算，输出 JSON 供模型判断。

## 脚本清单

| 脚本 | 路径 | 输入 | 输出 |
|------|------|------|------|
| K线分析 | `trading/scripts/data/kline_analyze.py` | MCP fetch_kline 的 klines JSON | MA/EMA/MACD/趋势/量价/流动性信号 |
| 板块扫描 | `trading/scripts/data/sector_scanner.py` | `{"sectors":[...], "holdings":[...]}` | 板块排名 + 共振检测 + 催化溯源建议 |
| 风控预检 | `trading/scripts/data/risk_precheck.py` | MCP get_positions + intents | 止损/止盈/T+1/行业集中度/日亏熔断 |
| 教训归档 | `trading/scripts/compound_learnings.py` | learnings/*.md 目录 | 索引 JSON，支持 --search/--tags/--problem/--recent/--stats |

## 使用方式

```bash
# K线分析：从 MCP 获取数据后 pipe
python3 ~/.hermes/trading/scripts/data/kline_analyze.py < kline_data.json

# 板块扫描：构造 sectors 输入
echo '{"sectors":[...], "holdings":[...]}' | python3 ~/.hermes/trading/scripts/data/sector_scanner.py

# 风控预检：从 MCP positions 直接 pipe
mcp_exec_get_positions 的输出 | python3 ~/.hermes/trading/scripts/data/risk_precheck.py

# 教训索引
python3 ~/.hermes/trading/scripts/compound_learnings.py --recent 7
python3 ~/.hermes/trading/scripts/compound_learnings.py --stats
python3 ~/.hermes/trading/scripts/compound_learnings.py --search 止损
```

## 设计约束

- 脚本只做**确定性计算**（算术、排序、字段提取、阈值比较）
- 模型仍负责**判断**（浪型判定、催化剂真伪、三分类归属）
- 输出格式为纯 JSON，宿主无关，不与任何特定 MCP 或其他工具耦合
- 脚本不保存 API 密钥或凭证

## 预期节省

K线分析场景：85-115k token → 预估 35k token（节省 60-75%）
