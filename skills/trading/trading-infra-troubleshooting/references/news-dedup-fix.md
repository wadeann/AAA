# 新闻跨源去重修复 (2026-06-14)

## 问题

`search_news` 返回的 8 条新闻中有多条重复，新浪和东财报的是同一条快讯，只是来源字段不同。

**重复样例**:
- `创新药概念震荡反弹 荣昌生物涨超10%` (eastmoney) vs `【创新药概念震荡反弹 荣昌生物涨超10%】午后...` (sina)
- `创新药概念震荡拉升 常山药业涨超13%` (eastmoney) vs `【创新药概念震荡拉升 常山药业涨超13%】创新药...` (sina)
- `荣昌生物：泰它西普治疗IgA肾病适应症获附条件上市批准` (eastmoney) vs `【荣昌生物：泰它西普治疗IgA肾病适应症附条件获批上市】...` (sina)

## DB 层现状

DB 的 UNIQUE 约束是 `(title, source)`，sina 和 eastmoney 的 title 不同（sina 带【】括号且包含正文前100字），所以 DB 层认为它们是不同的记录，INSERT OR IGNORE 不冲突。**DB 不需要改**。

## 修复方案

在 `search_news` 返回前（第4步）加内容级去重：

```python
def _short_title(t):
    # 去标点+括号后取前20字符作为比较基准
    t = t.replace("【", "").replace("】", "").replace("[", "").replace("]", "")
    t = re.sub(r'[，、；：！？,.]', ' ', t)
    return t.strip()[:20]

def _title_sim(a, b):
    sa, sb = _short_title(a), _short_title(b)
    if sa == sb: return 1.0
    if sa in sb or sb in sa: return 0.9  # 包含关系
    s_a, s_b = set(sa), set(sb)
    if not s_a or not s_b: return 0.0
    return len(s_a & s_b) / len(s_a | s_b)
```

**为什么用短标题而不是全标题**:
- 新浪 title 格式: `【标题】正文...`（前100字）
- 东财 title 格式: `标题`（短标题）
- 全标题 Jaccard 相似度只有 0.475（短标题字符集被长标题稀释）
- 短标题（前20字）相似度 0.9，正确识别为同一条

## 合并策略

相似度过 0.75 时判定为重复：
- source 优先级: eastmoney > sina > web_search
- 优先保留 impact 更高的
- 如果被合并项的 content 更长，用它的 content 替代

## 效果

| 股票 | 去重前 | 去重后 | 合并对数 |
|------|--------|--------|----------|
| 688331 | 8条 | 5条 | 3对 |

## 修改位置

`intel_server/main.py` L823-L862，search_news 分支第4步
