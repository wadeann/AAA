# fetch_market_health 缓存中毒完整记录

## 故障时间线

- **2026-06-15 01:29**: 东财接口最后一次成功返回 → `market_cache.json` 写入（上证 4053.58, 科创50 1687.67, 全市场主力 +13.26亿）
- **2026-06-15 ~ 06-24**: 东财 push2 API 持续 502/空返回 → `GLOBAL_MARKET_CACHE["data"]` 保持 06-15 的旧数据
- **2026-06-24 盘中**: 用户发现 `market_health` 指数严重偏离（上证差 57 点, 科创50 差 302 点），修复代码 + 删缓存 + 重启 intel_server 解决

## 代码位置

- **文件**: `/home/ubuntu/ai/pup-mcp/intel_server/main.py`
- **类**: `ImprovedMacroEngine`
- **方法**: `get_market_context()` (行 107-290)
- **缓存文件**: `/home/ubuntu/ai/pup-mcp/intel_server/market_cache.json`

## 数据流（修复前）

```
get_market_context()
  ├── 1. indices = fetch from qt.gtimg.cn ← ✅ 腾讯接口正常
  ├── 2. pool = fetch_sector_flows from push2.eastmoney.com ← ❌ 502/空
  ├── 3. total_market_flow = wencai or industry_sum or dynamic_backtrack ← ⚠️ 海外数据延迟
  ├── 4. wencai_pool = 问财备用 ← ⚠️ 能返回但也是昨日数据
  └── 5. IF pool is empty AND total_market_flow == 0:
         return GLOBAL_MARKET_CACHE["data"]  ← ❌ 返回 06-15 旧数据，覆盖 indices
```

## 为什么缓存永远不会更新

```python
# main.py 286-288: 只有抓取成功时才更新缓存
if abs(total_market_flow) > 0.1:
    GLOBAL_MARKET_CACHE["data"] = result
    save_cache(result)
```

东财接口永远失败 → `total_market_flow == 0` → 条件不满足 → 缓存永远是上次成功时的数据。

## 为什么删缓存文件也不够

```python
# main.py 62-66: 服务启动时从磁盘加载
cached_obj = load_cache()
GLOBAL_MARKET_CACHE = {
    "data": cached_obj["data"] if cached_obj else None,
    "last_success": cached_obj["timestamp"] if cached_obj else 0
}
```

删除 `market_cache.json` + 重启才能清空内存缓存。只删文件进程仍用旧内存缓存。

## 完整修复流程

```bash
# Step 1: 修改 main.py（patch 已应用，v13.1）
# Step 2: 删除缓存文件
rm -f /home/ubuntu/ai/pup-mcp/intel_server/market_cache.json
# Step 3: 重启 intel_server
kill $(ps aux | grep 'intel_server/main.py' | grep -v grep | awk '{print $2}')
cd /home/ubuntu/ai/pup-mcp && .venv/bin/python3 intel_server/main.py &
# Step 4: 验证
sleep 3 && curl -s http://localhost:9001/health
# 调用 mcp_intel_fetch_market_health 对比 query_data
```

## 预防

1. `market_cache.json` 应加 TTL（如超过 1 小时强制过期）
2. 降级逻辑不应完全覆盖 `indices`（腾讯接口是独立的）
3. 缓存降级时 delete cache file + clear memory cache（已在 v13.1 实现）

## 修复后仍存在的局限

- `score` / `summary` / `top_inflows` / `top_outflows` / `total_market_flow` 在海外 IP 下仍然不可靠（依赖东财接口）
- 板块资金流向仍然可能为空或延迟
- 大盘分析应优先用 `query_data` 获取指数，`market_health` 仅作辅助
