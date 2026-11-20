# -*- coding: utf-8 -*-
"""Сбор внешних данных для отчёта: сентимент, доминация, премиум, корреляция,
стейблкоины, ETF-потоки. Толерантен к сбоям: недоступный источник не роняет отчёт."""
import os
import io, sys, json, time, math, re, urllib.request
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
OUT = os.environ.get("BTC_REPORT_DIR") or os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

def jget(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def wget(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

ex, ok, fail = {}, [], []

# 1) Fear & Greed
try:
    fng = jget("https://api.alternative.me/fng/?limit=7")["data"]
    ex["fng"] = [{"d": time.strftime("%d.%m", time.gmtime(int(x["timestamp"]))),
                  "v": x["value"], "c": x["value_classification"]} for x in fng]
    ok.append("fng")
except Exception as e:
    fail.append(f"fng: {e}")

# 2) CoinGecko global: доминация, капитализация
try:
    g = jget("https://api.coingecko.com/api/v3/global")["data"]
    ex["dom_btc"] = round(g["market_cap_percentage"]["btc"], 1)
    ex["dom_eth"] = round(g["market_cap_percentage"]["eth"], 1)
    ex["mcap_btc_b"] = round(g["total_market_cap"]["usd"] / 1e12, 2)
    ex["mcap_chg_24h"] = round(g["market_cap_change_percentage_24h_usd"], 2)
    ok.append("global")
except Exception as e:
    fail.append(f"global: {e}")

# 3) Премиум Coinbase
try:
    cb = float(jget("https://api.coinbase.com/v2/prices/BTC-USD/spot")["data"]["amount"])
    bn = float(jget("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT")["price"])
    ex["coinbase_prem_pct"] = round(100 * (cb - bn) / bn, 3)
    ok.append("premium")
except Exception as e:
    fail.append(f"premium: {e}")

# 4) Корреляция ETH и реализованная волатильность
def okx_closes(inst):
    d = jget(f"https://www.okx.com/api/v5/market/candles?instId={inst}&bar=1D&limit=120")["data"]
    return [float(x[4]) for x in d][::-1]
try:
    btc_c, eth_c = okx_closes("BTC-USDT"), okx_closes("ETH-USDT")
    la = [math.log(btc_c[i] / btc_c[i - 1]) for i in range(1, len(btc_c))]
    lb = [math.log(eth_c[i] / eth_c[i - 1]) for i in range(1, len(eth_c))]
    m = min(len(la), len(lb)); la, lb = la[-m:], lb[-m:]
    ma, mb = sum(la) / m, sum(lb) / m
    cov = sum((x - ma) * (y - mb) for x, y in zip(la, lb)) / m
    sa = (sum((x - ma) ** 2 for x in la) / m) ** .5
    sb = (sum((y - mb) ** 2 for y in lb) / m) ** .5
    ex["eth_corr30"] = round(cov / (sa * sb), 2)
    ex["eth_btc_ratio"] = round(eth_c[-1] / btc_c[-1], 5)
    ex["rv30_pct"] = round((sum(x * x for x in la[-30:]) / 30) ** .5 * math.sqrt(365) * 100, 1)
    ok.append("corr/rv")
except Exception as e:
    fail.append(f"corr: {e}")

# 5) Стейблкоины: капитализация + тренд 30д
try:
    mkt = jget("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd"
               "&ids=tether,usd-coin,dai,first-digital-usd&price_change_percentage=7d")
    st = {"total_b": round(sum(x["market_cap"] for x in mkt) / 1e9, 1), "items": []}
    for x in mkt:
        st["items"].append({"sym": x["symbol"].upper(), "cap_b": round(x["market_cap"] / 1e9, 1)})
    tr = {}
    for cid, nm in (("tether", "USDT"), ("usd-coin", "USDC")):
        try:
            d = jget(f"https://api.coingecko.com/api/v3/coins/{cid}/market_chart"
                     "?vs_currency=usd&days=30&interval=daily")["market_caps"]
            tr[nm] = round(100 * (d[-1][1] - d[0][1]) / d[0][1], 2)
            time.sleep(2)  # лимит бесплатного API
        except Exception:
            tr[nm] = None
    st["trend30_pct"] = tr
    ex["stables"] = st
    ok.append("stables")
except Exception as e:
    fail.append(f"stables: {e}")

# 6) ETF-потоки (Farside) — при сбое сохраняем старый файл; сверяем сумму фондов с total
try:
    html = wget("https://farside.co.uk/btc/", 30)
    rows = []
    meta = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        cells = [re.sub(r"<[^>]+>", "", c).strip()
                 for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S)]
        if cells and re.match(r"\d{1,2} \w{3} \d{4}", cells[0]):
            rows.append(cells)
            try:
                total = float(cells[-1].replace("(", "-").replace(")", "").replace(",", ""))
                funds = sum(float(x.replace("(", "-").replace(")", "").replace(",", "") or 0)
                            for x in cells[1:-1])
                rec_ok = abs(funds - total) <= max(1.0, abs(total) * 0.02)
            except Exception:
                rec_ok = None
            meta.append({"date": cells[0], "reconciled": rec_ok})
    if rows:
        with open(OUT + "/etf_flows.json", "w", encoding="utf-8") as f:
            json.dump(rows[:30], f)
        with open(OUT + "/etf_meta.json", "w", encoding="utf-8") as f:
            json.dump(meta[:30], f, ensure_ascii=False)
        ok.append(f"etf ({len(rows)} сессий, сверено {sum(1 for m in meta if m['reconciled'])})")
    else:
        fail.append("etf: пустой парс, оставлен прежний файл")
except Exception as e:
    fail.append(f"etf: {e} (оставлен прежний файл)")

# 7) Макро-ориентиры: DXY и NASDAQ-100 (Yahoo)
for nm, sym in (("dxy", "DX-Y.NYB"), ("ndx", "^NDX")):
    try:
        ch = jget(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=6mo&interval=1d")["chart"]["result"][0]
        cl = [x for x in ch["indicators"]["quote"][0]["close"] if x]
        e20 = sum(cl[-20:]) / 20; e50 = sum(cl[-50:]) / 50
        ex[nm] = {"last": round(cl[-1], 1),
                  "vs_e20": "выше" if cl[-1] > e20 else "ниже",
                  "vs_e50": "выше" if cl[-1] > e50 else "ниже"}
        ok.append(nm)
    except Exception as e:
        fail.append(f"{nm}: {e}")

ex["updated"] = time.strftime("%d.%m.%Y %H:%M UTC", time.gmtime())
with open(OUT + "/extra_data.json", "w", encoding="utf-8") as f:
    json.dump(ex, f, ensure_ascii=False, indent=1)

print("OK:", ", ".join(ok) if ok else "-")
print("FAIL:", "; ".join(fail) if fail else "-")
