# A股备选数据源（Jin10 MCP 不支持个股时使用）

## 问题

Jin10 MCP (`mcp_jin10_get_quote`, `mcp_jin10_get_kline`) 不支持 A 股个股代码（如 300161、600487）。返回 `"不支持该品种"`。

## 回退方案

### 1. 新浪实时行情

```
GET https://hq.sinajs.cn/list=sz300161
Header: Referer: https://finance.sina.com.cn
```

返回 GBK 编码，格式：
```
var hq_str_sz300161="华中数控,30.370,昨收,29.560,开盘,29.900,最高,31.680,最低,29.660,...,2026-08-17,14:04:12,00";
```

字段顺序（逗号分隔）：name, 今开, 昨收, 当前价, 最高, 最低, 竞买价, 竞卖价, 成交量, 成交额, ...

### 2. 新浪 K 线

```
GET https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sz300161&scale=30&ma=no&datalen=100
Header: Referer: https://finance.sina.com.cn
```

scale 参数：30=30分钟, 60=60分钟, 240=日线, 5=5分钟

返回 JSON 数组：
```json
[{"day": "2026-08-17 14:30:00", "open": "29.880", "high": "29.940", "low": "29.870", "close": "29.920", "volume": "73500"}]
```

### 3. Symbol 格式

- 深交所：`sz` + 代码 → `sz300161`
- 上交所：`sh` + 代码 → `sh600487`

## 不可用的数据源

- **东财 push2/push2his**（push2.eastmoney.com）：海外 IP 下 502/连接拒绝
- **腾讯 ifzq**（web.ifzq.gtimg.cn）：DNS 解析可能失败（腾讯云 IAS 代理不稳定）
- **东财 quote**：同样 502

## 提取数据的 Python 示例

```python
import urllib.request, json

# K线
url = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sz300161&scale=30&ma=no&datalen=100'
req = urllib.request.Request(url, headers={'Referer': 'https://finance.sina.com.cn'})
with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read().decode('utf-8'))
bars = [(float(b['open']), float(b['high']), float(b['low']), float(b['close']), int(b['volume'])) for b in data]
```

## 注意事项

- 新浪接口无需 API Key
- 需设置 Referer header
- 实时行情是 GBK 编码，K 线是 UTF-8
- 120 根 K 线请求通常足够覆盖近一周的 30 分钟级别数据
