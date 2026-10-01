#!/home/ubuntu/.hermes/hermes-agent/venv/bin/python3
"""
开盘观察池复核脚本 — 每交易日 09:35 触发（no_agent cron）。
从 ~/.hermes/trading/watchlist.json 读取观察池股票，拉实时行情，按涨跌幅分类输出。

重建背景 (2026-08-18): jobs.json 引用此脚本但文件丢失 → cron 静默空跑
(输出 watch_count=0 不报错)。此份为 skill 备份，文件丢失时从此复制。

输出 JSON → cron 框架自动投递飞书。必须带股票中文名（用户要求）。
"""
import json, os, sys
from datetime import datetime

HERMES_HOME = os.path.expanduser("~/.hermes")
WATCHLIST_PATH = os.path.join(HERMES_HOME, "trading", "watchlist.json")

def load_watchlist():
    if not os.path.exists(WATCHLIST_PATH):
        return []
    with open(WATCHLIST_PATH) as f:
        data = json.load(f)
    return data.get("watchlist", [])

def fetch_quotes(stocks):
    """新浪 hq.sinajs.cn 批量行情，支持 sh/sz/bj 前缀，GBK 编码。
    ⚠️ 必须带 Referer 头否则被拒。东财 API 海外 IP 可能 502，优先新浪。"""
    import urllib.request, ssl, time

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    results = []
    for item in stocks:
        sym = item["symbol"]
        code = sym.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        if sym.endswith(".SH"):
            prefix = "sh"
        elif sym.endswith(".SZ"):
            prefix = "sz"
        elif sym.endswith(".BJ"):
            prefix = "bj"
        else:
            continue

        try:
            url = f"https://hq.sinajs.cn/list={prefix}{code}"
            req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn"})
            with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
                raw = resp.read().decode("gbk")
            if '=""' in raw:
                continue
            parts = raw.split('"')[1].split(",")
            price = float(parts[3])
            prev_close = float(parts[2])
            chg_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0
            volume = int(parts[8])
            results.append({
                "symbol": sym,
                "name": item["name"],
                "price": price,
                "prev_close": prev_close,
                "chg_pct": chg_pct,
                "volume": volume,
                "reason": item.get("reason", ""),
            })
        except Exception as e:
            results.append({
                "symbol": sym,
                "name": item["name"],
                "error": str(e)[:80],
            })
        time.sleep(0.08)
    return results

def main():
    stocks = load_watchlist()
    if not stocks:
        print(json.dumps({"status": "empty", "reason": "watchlist_empty"}))
        return

    quotes = fetch_quotes(stocks)

    # 分类
    surge = [q for q in quotes if q.get("chg_pct", 0) >= 5]
    rally = [q for q in quotes if 2 <= q.get("chg_pct", 0) < 5]
    plunge = [q for q in quotes if q.get("chg_pct", 0) <= -5]
    decline = [q for q in quotes if -5 < q.get("chg_pct", 0) <= -2]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output = {
        "status": "ok",
        "run_time": now,
        "total": len(quotes),
        "surge_5pct_plus": [{"name": q["name"], "symbol": q["symbol"], "chg": q["chg_pct"]} for q in surge],
        "rally_2to5": [{"name": q["name"], "symbol": q["symbol"], "chg": q["chg_pct"]} for q in rally],
        "plunge_5pct_minus": [{"name": q["name"], "symbol": q["symbol"], "chg": q["chg_pct"]} for q in plunge],
        "decline_2to5": [{"name": q["name"], "symbol": q["symbol"], "chg": q["chg_pct"]} for q in decline],
        "all": [{"name": q.get("name", "?"), "symbol": q.get("symbol", "?"),
                 "price": q.get("price"), "chg_pct": q.get("chg_pct")} for q in quotes],
    }

    print(json.dumps(output, ensure_ascii=False))

if __name__ == "__main__":
    main()