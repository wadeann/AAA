# 盘中连板天梯看板（intraday-hot-sector-sniper）候选为空 Bug 根因

## 症状

`intraday-hot-sector-sniper` 长期只输出"防守静默看板"（全部只卖不买/空仓观望），从未产生过可执行买入信号。但代码本身有 `candidates` 分支（09-07/09-08 曾产出过供销大集等带具体买点的信号），分支并未被删除。

## 根因

### 数据源白名单门禁（第 409 行）

```python
def get_buyable_candidates(top_sectors, data_source_used):
    if not top_sectors or data_source_used != "wencai":
        return []  # ← 无条件返回空！
```

当 `data_source_used != "wencai"` 时，候选列表**无条件直接返回空**，导致永远输出防守看板。

### 实际数据源路径

`fetch_intraday_ladder()` 有三条数据源路径（L144-220）：

| 优先级 | 数据源 | `data_source_used` | 条件 |
|--------|--------|-------------------|------|
| 1 | 问财（wencai） | `"wencai"` | 问财接口返回有数据 → 白名单通过 ✅ |
| 2 | 东方财富/akshare | `"akshare_em"` | 问财失败时容灾 → 门禁拦截 ❌ |
| 3 | 通达信 tdx_screener | `"tdx_screener"` | 前两者都失败 → 门禁拦截 ❌ |

**问题场景**：盘中问财接口偶尔失效（超时/余额不足/返回空），自动容灾到 akshare_em 或 tdx_screener → `data_source_used` 变成非 wencai → `get_buyable_candidates` 返回空 → 永远只输出防守看板。

候选生成过程与数据源选择是正交的——只要数据真实、标的满足量化条件（涨幅1.5%~6%、量比>1.1、换手率2%~15%等），数据源来自问财或东方财富不应影响是否能产生买入候选。

## 修复（2026-09-23 已确认应用并通过验证）

### 修复 1 — 核心候选门禁（第 409 行）

将 `data_source_used != "wencai"` 检查删除：

```python
# Before：问财天梯容灾到 akshare/tdx 时误杀全部候选
if not top_sectors or data_source_used != "wencai":
    return []

# After：只检查 top_sectors 是否有效
if not top_sectors:
    return []
```

**关键洞察**：`get_buyable_candidates` 内部的候选筛选**始终独立调用 `wencai_search`**（L420），与涨停天梯由哪个数据源提供无关。`data_source_used` 仅描述"涨停天梯"由哪个容灾通道生成。故候选筛选的可用性与天梯数据源正交——天梯数据真实、标的满足量化条件即可产候选，不应因容灾源不同而屏蔽买入信号。**这正是"数据源白名单门禁"类 bug 的核心判别**：判断函数内部是否自己获取数据，若是，则外部传入的 source 参数不应成为短路条件。

### 修复 2 — 行业资金流白名单门禁（第 342 行，同类 bug 第二处）

`fetch_hot_sectors_and_ladder()` 中原有：

```python
if not ladder_info or ladder_info.get("data_source_used") == "wencai":
    flow_res = mcp_call(9001, "wencai_search", {"query": "今日二级行业 资金净流入额前25名 ..."})
```

天梯非 wencai 时连行业资金流也不查 → `flow_map` 空 → 所有板块 `fund_flow_status: "missing"`、`norm_inflow=0` → 板块排序丢失资金流维度，排序质量下降。

修复：行业资金流与天梯源无关，始终独立查询（try/except 静默兜底）：
```python
flow_map = {}
try:
    flow_res = mcp_call(9001, "wencai_search", {"query": "今日二级行业 资金净流入额前25名 ..."}, timeout=8)
    flow_datas = flow_res.get("datas", []) if isinstance(flow_res, dict) else []
except Exception:
    flow_datas = []
for d in flow_datas:
    ...
```

**排查模式**：发现一个"数据源白名单门禁"bug 后，应全脚本 grep 同类 `data_source_used == "wencai"` / `data_source_used != "wencai"` 的条件，逐一判定是"该函数自己取数"还是"依赖外部源"。自己取数的函数，source 参数不能作短路门禁。本脚本共 2 处（L409 候选 + L342 行业资金流），均已修复。

### 验证方法

单元验证门禁层是否仍短路：monkeypatch `mcp_call` 使其记录调用并返回空，传入 `data_source_used="akshare_em"`，断言 `mcp_call` 被真实调用（而非提前 `return []`）：

```python
calls = {'hit': False}
def fake_mcp_call(port, api, payload, timeout=None):
    calls['hit'] = True
    return {'datas': []}
ns['mcp_call'] = fake_mcp_call
result = fn(fake_sectors, 'akshare_em')
assert calls['hit'], 'FAIL: 仍被门禁短路'
```

**风险说明**（原稿保留）：若数据源非 wencai 时 top_sectors 字段结构不同（如 `leader` 键名不一致），`sec_info["leader"]["name"]` 会 KeyError。但实际三级源路径生成的 `cand_meta` 已统一为 `{"name","sector","streak"}` 结构（L156-172/L184-193/L213-226），字段名一致，无 KeyError 风险。

## 相关文件

- `~/.hermes/scripts/intraday_hot_sector_sniper.py`
- 核心分支：L140-220（三级数据源）、L407-499（get_buyable_candidates）、L702-703（ds_used 传入）
