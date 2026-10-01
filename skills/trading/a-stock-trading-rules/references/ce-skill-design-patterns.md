# CE 方法论技能设计模式（从 compound-engineering-plugin 提炼）

> 2026-08-03 从 Every Inc 的 compound-engineering-plugin（23.7K⭐）仓库分析提炼。
> 本文档作为 A 股交易系统 skill 迭代时的设计参考，非运行时加载项。

## 背景

CE 的 32 个 skill 解决了"一次写作，多平台分发"的问题。其方法论直接适用于我们的多 skill 交易系统。

## 核心模式

### 1. 结果脊柱优先 (Outcome Spine First)

写 skill 前先定四要素，放在所有流程之前：
- **产出物**：skill 必须产出什么
- **下一个消费者**：谁用这个产出（用户/另一个skill/系统）
- **完成条件**：可观察的完成标志
- **非明显意图**：只在能改变执行方式时才加，否则跳过

```
正确："产出 TradeIntent JSON → 策略员消费 → 无空值必填字段即完成"
错误：先写一大堆"be thorough"、"produce high quality work"
```

### 2. 协议 vs 判断分离 (Protocol / Judgment Split)

| 协议（保留，显式） | 判断（删或压缩到最小） |
|---|---|
| 输出路径、字段、枚举 | 长篇推理方向菜单 |
| 顺序、状态转移、门控 | 举例证明同一观点多次 |
| 计数、阈值、范围量词 | 清晰规则后的多段动机解释 |
| 权限和变更边界 | 通用质量鼓励 |
| 覆盖分类要求 | 无实证的重复 |

关键问题：**"删掉这句话，会不会产生错误路径/状态/数量/字段？"**
- 是 → 协议，保留
- 否 → 判断，压缩为最小原则或删除

### 3. 本地作用域 (Local Scope)

量词紧挨被限制的动作，不放全局开头：
```
错误：开头写"每只持仓都要查新闻"→ 后面18步解释其他东西
正确：在 Step 0.5.B 直接写"每只持仓并行：mcp_intel_search_news(symbol)"
```

### 4. 脚本优先架构 (Script-First)

当 skill 处理 >50 项数据或需要确定性分类时，用 Python 脚本代替模型在内存处理：
- 脚本做：解析、分类、正则匹配、查表、排序
- 模型做：呈现结果、策略判断、决策推理
- 实测节省 60-75% token
- 脚本的输出格式改为 JSON，不可被模型重新分类

### 5. 沉淀闭环 (Compound / Learning Loop)

每次交易/操作后记录结构化学习：
```
目录: ~/.hermes/trading/learnings/
格式: YAML frontmatter (module, tags, problem_type) + 正文
消费者: 下次 brainstorm/plan/research 时自动读取作为 grounding
```

### 6. 多级加载 (Tiered Loading)

```
SKILL.md (内联)        → 核心协议、路由、门控（始终在上下文）
references/*.md         → 条件触发的大块内容（>20% skill体积时提取）
scripts/*.py            → 数据处理、验证脚本
```

引用时必须带"加载失败会怎样"的声明，让加载变成结构必要。

### 7. 子代理并发 + 独立性验证

审查类 skill：
- 多个 reviewer persona 并发运行
- 每个只从一个透镜看（安全/性能/正确性）
- independence 是执行上下文的属性：两个 persona 在同一个上下文 = 两个视角，不等于两个独立证人
- 合成阶段合并 + 去重 + 置信度排序

### 8. 管道/非交互模式

几乎所有 skill 支持 `mode:pipeline` 或 `mode:non-interactive`：
- 被其他 skill 编排时，不打断用户
- 元编排器（如 lfg）无人值守跑完整流程
- 对应我们的 orchestrator→cron 场景

## 应用于 A 股系统

| CE 模式 | 现有问题 | 改进方向 |
|---------|---------|---------|
| 结果脊柱 | orchestrator 882行，头重脚轻 | 四要素前置，砍冗余 |
| 协议/判断分离 | trading-rules 大量"be thorough"类措辞 | 改为可观察规则 |
| 脚本优先 | K线分析、板块扫描全由模型在内存做 | 创建 scripts/data/ 下 Python 工具 |
| 沉淀闭环 | 只有 memory，无结构化学习系统 | 创建 learnings/ 目录 |
| 管道模式 | intraday-eval 无 mode:pipeline 支持 | 添加无人值守模式 |

## 何时不用这些模式

- 技能核心价值就是模型判断（如浪型判定、催化剂真伪）→ 不套脚本
- 输入是非结构化自然语言
- 数据集很小，处理成本可忽略
