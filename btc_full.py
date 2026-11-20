# -*- coding: utf-8 -*-
"""BTC: полный анализ по стратегии «Уровень + поток» v2.
Добавлено к v1: недельные уровни + каскады, 4h-закреп, фандинг, OI,
перекос розницы, taker-flow (1h/1d), стакан (стены), DXY/NQ-корреляции,
опционы Deribit (OI по страйкам, max pain). Выход: btc_full.json + btc_full.png
"""
import os
import io, json, sys, time, urllib.request, csv
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
UA = {"User-Agent": "Mozilla/5.0 (analysis)"}
OUT = os.environ.get("BTC_REPORT_DIR") or os.path.dirname(os.path.abspath(__file__))

def get(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")

def jget(url):
    return json.loads(get(url))

res = {"errors": []}
MANIFEST = {}  # аудит запросов (паттерн Astra): url, время, попытки, статус

def jget_m(url, name, timeout=25):
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8", errors="replace"))
            MANIFEST[name] = {"url": url, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                              "status": "OK", "attempts": attempt}
            return data
        except Exception as e:
            if attempt == 3:
                MANIFEST[name] = {"url": url, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                  "status": "ERROR", "attempts": attempt, "error": str(e)[:120]}
            raise

# ================= 1. СВЕЧИ D1 =================
def _okx_d():
    # 1Dutc: дневная свеча по UTC-границе (обычный 1D у OKX — другая граница суток).
    # Берём только ПОДТВЕРЖДЁННЫЕ свечи (confirm=1): неполная свеча в движок не попадает.
    d = jget("https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1Dutc&limit=300")["data"]
    rows = [(int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5]))
            for x in d if str(x[8]) == "1"][::-1]
    return rows, "OKX (1Dutc)"

def _bin_d():
    d = jget("https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1d&limit=300")
    now_ms = int(time.time() * 1000)
    return [(int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5]))
            for x in d if int(x[6]) <= now_ms], "Binance"

def _byb_d():
    d = jget("https://api.bybit.com/v5/market/kline?category=spot&symbol=BTCUSDT&interval=D&limit=300")["result"]["list"]
    now_ms = int(time.time() * 1000)
    return [(int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5]))
            for x in d[::-1] if int(x[0]) + 86400000 <= now_ms], "Bybit"

candles, src = None, None
for attempt in range(3):  # ретраи: OKX иногда отдаёт пусто/лимит после серии запросов
    for fn in (_okx_d, _bin_d, _byb_d):
        try:
            rows_, src_ = fn()
            if len(rows_) > 60:
                candles, src = rows_, src_
                break
        except Exception as e:
            print("fetch fail:", fn.__name__, str(e)[:80])
    if candles:
        break
    time.sleep(4)

if not candles:
    print("NO DATA"); sys.exit(1)
res["source"] = src
n = len(candles)
ts = [r[0] / 1000 for r in candles]
o = [r[1] for r in candles]; h = [r[2] for r in candles]; l = [r[3] for r in candles]
c = [r[4] for r in candles]; v = [r[5] for r in candles]

# живая цена — с тикера (все свечи в массиве теперь закрытые, c[-1] — не «сейчас»)
try:
    _tk = jget_m("https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT", "ticker")["data"][0]
    price = float(_tk["last"])
    res["price_source"] = "OKX ticker"
except Exception:
    price = c[-1]
    res["price_source"] = "последняя закрытая свеча"
res["last_date"] = time.strftime("%d.%m.%Y %H:%M UTC", time.gmtime(ts[-1]))
res["price"] = round(price, 1)

trs = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1])) for i in range(1, n)]
ATR = sum(trs[-14:]) / 14
res["atr_pct"] = round(100 * ATR / price, 2)
vma20 = [sum(v[max(0, i-19):i+1]) / len(v[max(0, i-19):i+1]) for i in range(n)]

# ================= 2. УРОВНИ D1 (как в v1) =================
K = 5
piv = [(h[i], "hi", i) for i in range(K, n-K) if h[i] == max(h[i-K:i+K+1])]
piv += [(l[i], "lo", i) for i in range(K, n-K) if l[i] == min(l[i-K:i+K+1])]
piv.sort()
tol = max(0.006 * price, 0.4 * ATR)
clu = []
for p, kind, i in piv:
    if clu and abs(p - clu[-1]["p"][-1]) <= tol:
        clu[-1]["p"].append(p); clu[-1]["it"].append(i)
    else:
        clu.append({"p": [p], "it": [i]})
d1_levels = []
for cl in clu:
    lp = sum(cl["p"]) / len(cl["p"])
    binv = sum(v[j] for j in range(max(0, n-120), n)
               if abs((h[j]+l[j]+c[j])/3 - lp) <= tol)
    vsh = binv / sum(v[max(0, n-120):])
    d1_levels.append({"price": round(lp, 0), "touches": len(cl["p"]),
                      "age_days": n-1-max(cl["it"]), "vol_share": round(vsh, 3),
                      "type": "res" if lp > price else "sup"})
d1_levels = [L for L in d1_levels
             if not (L["type"] == "res" and sum(1 for j in range(n-5, n) if c[j] > L["price"]) >= 3)
             and not (L["type"] == "sup" and sum(1 for j in range(n-5, n) if c[j] < L["price"]) >= 3)]
res_d1 = sorted([L for L in d1_levels if L["type"] == "res"], key=lambda x: x["price"])
sup_d1 = sorted([L for L in d1_levels if L["type"] == "sup"], key=lambda x: -x["price"])

# ================= 3. НЕДЕЛЬНЫЕ УРОВНИ =================
wk = defaultdict(lambda: {"h": -1e18, "l": 1e18, "c": None, "v": 0})
for i in range(n):
    key = time.strftime("%G-%V", time.gmtime(ts[i]))
    wk[key]["h"] = max(wk[key]["h"], h[i]); wk[key]["l"] = min(wk[key]["l"], l[i])
    wk[key]["c"] = c[i]; wk[key]["v"] += v[i]
wk_keys = sorted(wk.keys())
W = [wk[k] for k in wk_keys]
nw = len(W)
w_piv = []
for i in range(2, nw - 2):
    if W[i]["h"] == max([w["h"] for w in W[i-2:i+3]]):
        w_piv.append(W[i]["h"])
    if W[i]["l"] == min([w["l"] for w in W[i-2:i+3]]):
        w_piv.append(W[i]["l"])
w_tol = max(0.012 * price, 2.0 * ATR)
w_levels = sorted(w_piv)
w_clu = []
for p in w_levels:
    if w_clu and abs(p - w_clu[-1][-1]) <= w_tol:
        w_clu[-1].append(p)
    else:
        w_clu.append([p])
w_lev = [round(sum(g)/len(g), 0) for g in w_clu]
res["weekly_levels"] = [x for x in w_lev if abs(x - price)/price < 0.25]

# каскады: D1-уровень с W1-уровнем в пределах 0.8*ATR
cascades = []
for L in res_d1[:3] + sup_d1[:3]:
    for w in w_lev:
        if abs(w - L["price"]) <= 0.8 * ATR:
            cascades.append({"d1": L["price"], "w1": w, "side": L["type"]})
res["cascades"] = cascades

R1 = res_d1[0]["price"] if res_d1 else None
R2 = res_d1[1]["price"] if len(res_d1) > 1 else None
S1 = sup_d1[0]["price"] if sup_d1 else None
S2 = sup_d1[1]["price"] if len(sup_d1) > 1 else None

# сжатие
r10 = (max(h[-10:]) - min(l[-10:])) / ATR
vol_5_20 = (sum(v[-5:]) / 5) / (sum(v[-25:-5]) / 20)
res["squeeze"] = {"range10_ATR": round(r10, 2), "vol_5_20": round(vol_5_20, 2),
                  "active": bool(r10 < 3.2 and vol_5_20 < 0.9)}
res["levels"] = {"R1": R1, "R2": R2, "S1": S1, "S2": S2,
                 "res_extra": [x["price"] for x in res_d1[2:5]],
                 "sup_extra": [x["price"] for x in sup_d1[2:5]]}

# --- анти-лаг: пивотам K=5 нужно 5 будущих баров, поэтому последние 5 дней невидимы.
# Временные (prov.) уровни — экстремумы последних 5 баров, до подтверждения пивотом.
prov_res = round(max(h[-5:]), 0) if max(h[-5:]) > price else None
prov_sup = round(min(l[-5:]), 0) if min(l[-5:]) < price else None
_wsorted = sorted([w for w in w_lev if w < price], reverse=True)
w_below = _wsorted[0] if _wsorted else None
w_below_far = _wsorted[1] if len(_wsorted) > 1 else None
w_above = min([w for w in w_lev if w > price], default=None)
_cand_res = [x for x in (R1, prov_res) if x]
_cand_sup = [x for x in (S1, prov_sup) if x]
res["levels"].update({
    "R1_prov": prov_res, "S1_prov": prov_sup,
    "nearest_res": round(min(_cand_res), 0) if _cand_res else None,
    "nearest_sup": round(max(_cand_sup), 0) if _cand_sup else None,
    "w1_defense": round(w_below, 0) if w_below else None,
    "w1_defense_far": round(w_below_far, 0) if w_below_far else None,
    "w1_above": round(w_above, 0) if w_above else None,
})

# --- ПРИЧИННОСТЬ (фикс lookahead из аудита Astra): для вердикта уровни считаются
# только по барам ДО проверяемой свечи: bars[:-1] для закрепа/обороны, bars[:-3] для ловушки.
def _levels_upto(end):
    """компактный причинный срез: (ближ.сопротивление, W1-оборона) известные к бару end-1"""
    if end < 60:
        return None, None
    _w = trs[max(0, end - 14):end]
    A = sum(_w) / len(_w)
    tol = max(0.006 * c[end - 1], 0.4 * A)
    tw = max(0.012 * c[end - 1], 2 * A)
    piv = []
    for i in range(5, end - 5):
        if h[i] == max(h[i - 5:i + 6]):
            piv.append(h[i])
        if l[i] == min(l[i - 5:i + 6]):
            piv.append(l[i])
    piv.sort()
    cl = []
    for p in piv:
        if cl and abs(p - cl[-1][-1]) <= tol:
            cl[-1].append(p)
        else:
            cl.append([p])
    lev = [sum(g) / len(g) for g in cl]
    lev += [x for x in (max(h[end - 5:end]), min(l[end - 5:end]))]
    ref = c[end - 1]
    nr_ = min([x for x in lev if x > ref], default=None)
    # недельные (только полные недели до end, пивоты K=2)
    wk_ = {}
    for i in range(end):
        key = time.strftime("%G-%V", time.gmtime(ts[i]))
        g = wk_.setdefault(key, {"h": -1e18, "l": 1e18})
        g["h"] = max(g["h"], h[i]); g["l"] = min(g["l"], l[i])
    wl = [v_ for k in sorted(wk_) for v_ in (wk_[k],)]
    wp = []
    for i in range(2, len(wl) - 2):
        if wl[i]["h"] == max(x["h"] for x in wl[i - 2:i + 3]):
            wp.append(wl[i]["h"])
        if wl[i]["l"] == min(x["l"] for x in wl[i - 2:i + 3]):
            wp.append(wl[i]["l"])
    wp.sort()
    wc = []
    for p in wp:
        if wc and abs(p - wc[-1][-1]) <= tw:
            wc[-1].append(p)
        else:
            wc.append([p])
    ws_lev = [sum(g) / len(g) for g in wc]
    wd_ = max([x for x in ws_lev if x < ref], default=None)
    return nr_, wd_

_nr_prior, _wd_prior = _levels_upto(n - 1)   # уровень, известный ДО последней закрытой
_nr_prior3, _ = _levels_upto(n - 3)          # уровень до 3-дневного окна ловушки

# --- статусы по ЗАВЕРШЁННОМУ D1 (все свечи в массиве закрыты по confirm-флагу) ---
nr_ = res["levels"]["nearest_res"]; wd_ = res["levels"]["w1_defense"]
_nr_prior = _nr_prior if _nr_prior is not None else nr_
_nr_prior3 = _nr_prior3 if _nr_prior3 is not None else _nr_prior
_wd_prior = _wd_prior if _wd_prior is not None else wd_
res["daily_status"] = {
    "last_completed_close": round(c[-1], 1),
    "tested_res_prior": round(_nr_prior, 0),
    "trap_res_prior": round(_nr_prior3, 0),
    "last_close_above_nearest_res": bool(c[-1] > _nr_prior),
    "closes_above_res_prior3d": sum(1 for x in c[-3:] if x > _nr_prior3),
    "close_below_w1_defense": bool(_wd_prior and c[-1] < _wd_prior),
}

# --- событийный день (сегодня/завтра) из events.json: в такие дни метрики потока искажены ---
try:
    _evs = json.load(open(OUT + "/events.json", encoding="utf-8"))
    _today = time.strftime("%Y-%m-%d", time.gmtime(ts[-1]))
    _tom = time.strftime("%Y-%m-%d", time.gmtime(ts[-1] + 86400))
    res["events_flag"] = [e for e in _evs if e["date"] in (_today, _tom)]
except Exception:
    res["events_flag"] = []

# ================= 4. 4H-ЗАКРЕП =================
try:
    h4 = jget("https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=4H&limit=120")["data"]
    h4 = [(int(x[0]), float(x[4])) for x in h4][::-1]
    closes4 = [x[1] for x in h4]
    res["h4"] = {"last_time": time.strftime("%d.%m %H:%M", time.gmtime(h4[-1][0]/1000)),
                 "closes_above_nearest_res_24h": (sum(1 for x in closes4[-6:] if nr_ and x > nr_)),
                 "last_close": closes4[-1],
                 "max4h_3d": max(x[1] for x in h4[-18:])}
except Exception as e:
    res["errors"].append(f"h4: {e}")

# ================= 5. ПРОИЗВОДНЫЕ (Binance -> OKX fallback: гео-блок 451) =================
res["deriv_source"] = "okx"
try:
    pi = jget_m("https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP", "funding")
    res["funding_now"] = round(float(pi["data"][0]["fundingRate"]) * 100, 4)
except Exception as e:
    try:
        pi = jget("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=BTCUSDT")
        res["funding_now"] = round(float(pi["lastFundingRate"]) * 100, 4)
        res["deriv_source"] = "binance"
    except Exception as e2:
        res["errors"].append(f"funding: okx={e}; bin={e2}")

try:
    oi_hist = jget_m("https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume?ccy=BTC&period=1D", "oi_d")["data"]
    oi_vals = [(int(r[0]), float(r[1]) / 1e9) for r in oi_hist]
    oi_vals.sort()
    oi_v = [v for _, v in oi_vals[-14:]]
    res["oi_b"] = [round(x, 2) for x in oi_v]
    res["oi_trend_3d_pct"] = round(100 * (oi_v[-1] - oi_v[-4]) / oi_v[-4], 2) if len(oi_v) >= 4 else None
    res["oi_note"] = "OKX свопы (не вся биржа)"
except Exception as e:
    try:
        oi = jget("https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1d&limit=14")
        oi_v = [float(x["sumOpenInterestValue"]) / 1e9 for x in oi]
        res["oi_b"] = [round(x, 2) for x in oi_v]
        res["oi_trend_3d_pct"] = round(100 * (oi_v[-1] - oi_v[-4]) / oi_v[-4], 2)
        res["deriv_source"] = "binance"
    except Exception as e2:
        res["errors"].append(f"oi: okx={e}; bin={e2}")

try:
    ls = jget_m("https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy=BTC&period=1D", "ls")["data"]
    ls_rows = sorted((int(r[0]), float(r[1])) for r in ls)
    res["ls_accounts"] = [round(x, 2) for _, x in ls_rows[-7:]]
except Exception as e:
    try:
        ls = jget("https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=1d&limit=7")
        res["ls_accounts"] = [round(float(x["longShortRatio"]), 2) for x in ls]
    except Exception as e2:
        res["errors"].append(f"ls: okx={e}; bin={e2}")

try:
    tv = jget_m("https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=CONTRACTS&period=1D", "taker_d")["data"]
    tv_rows = sorted((int(r[0]), float(r[1]) / (float(r[2]) or 1)) for r in tv)
    res["taker_1d"] = [round(x, 2) for _, x in tv_rows[-5:]]
    tv1h = jget_m("https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=CONTRACTS&period=1H", "taker_h")["data"]
    tv1h_rows = sorted((int(r[0]), float(r[1]) / (float(r[2]) or 1)) for r in tv1h)
    tv_r = [x for _, x in tv1h_rows[-48:]]
    res["taker_1h_last12"] = [round(x, 2) for x in tv_r[-12:]]
    res["taker_1h_avg48"] = round(sum(tv_r) / len(tv_r), 3) if tv_r else None
except Exception as e:
    try:
        tv = jget("https://fapi.binance.com/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=1h&limit=48")
        tv_r = [float(x["buySellRatio"]) for x in tv]
        res["taker_1h_last12"] = [round(x, 2) for x in tv_r[-12:]]
        res["taker_1h_avg48"] = round(sum(tv_r) / len(tv_r), 3)
        res["taker_1d"] = [round(float(x["buySellRatio"]), 2)
                           for x in jget("https://fapi.binance.com/futures/data/takerlongshortRatio?symbol=BTCUSDT&period=1d&limit=5")]
    except Exception as e2:
        res["errors"].append(f"taker: okx={e}; bin={e2}")

# ================= 6. СТАКАН (OKX -> Binance fallback) =================
try:
    d_ = jget_m("https://www.okx.com/api/v5/market/books?instId=BTC-USDT&sz=400", "books")["data"][0]
    bids = [(float(p), float(q)) for p, q, *_ in d_["bids"]]
    asks = [(float(p), float(q)) for p, q, *_ in d_["asks"]]
    _src = "okx"
except Exception as e:
    try:
        d_ = jget("https://api.binance.com/api/v3/depth?symbol=BTCUSDT&limit=1000")
        bids = [(float(p), float(q)) for p, q in d_["bids"]]
        asks = [(float(p), float(q)) for p, q in d_["asks"]]
        _src = "binance"
    except Exception as e2:
        res["errors"].append(f"book: okx={e}; bin={e2}")
        bids = asks = []
if bids:
    def wall(side, lo_p, hi_p):
        vals = [(p, p * q) for p, q in side if lo_p <= p <= hi_p]
        tot = sum(x[1] for x in vals)
        mx = max(vals, key=lambda x: x[1]) if vals else (0, 0)
        return {"sum_USD_m": round(tot / 1e6, 1), "top_wall": [round(mx[0], 0), round(mx[1] / 1e6, 2)]}
    res["book"] = {
        "source": _src,
        "bids_pm1.5%": wall(bids, price * 0.985, price),
        "asks_to_R1x1.01": wall(asks, price, (nr_ or R1 or price) * 1.01),
        "asks_R1_to_R1x1.02": wall(asks, (nr_ or R1 or price) * 0.999, (nr_ or R1 or price) * 1.02),
    }

# ================= 7. МАКРО (Stooq) =================
def stooq(sym):
    try:
        txt = get(f"https://stooq.com/q/d/l/?s={sym}&i=d")
        r = list(csv.DictReader(txt.strip().splitlines()))
        return [(row["Date"], float(row["Close"])) for row in r[-120:]]
    except Exception as e:
        res["errors"].append(f"stooq {sym}: {e}"); return []

def corr(a, b):
    la = [__import__("math").log(a[i]/a[i-1]) for i in range(1, len(a))]
    lb = [__import__("math").log(b[i]/b[i-1]) for i in range(1, len(b))]
    m = min(len(la), len(lb)); la, lb = la[-m:], lb[-m:]
    ma_, mb_ = sum(la)/m, sum(lb)/m
    cov = sum((x-ma_)*(y-mb_) for x, y in zip(la, lb)) / m
    sa = (sum((x-ma_)**2 for x in la)/m) ** 0.5
    sb = (sum((y-mb_)**2 for y in lb)/m) ** 0.5
    return round(cov / (sa * sb), 2) if sa and sb else None

macro = {}
for name, sym in (("DXY", "dx.f"), ("NASDAQ100", "nq.f")):
    s = stooq(sym)
    if s:
        closes_m = [x[1] for x in s]
        e20 = sum(closes_m[-20:]) / 20; e50 = sum(closes_m[-50:]) / 50
        macro[name] = {"last": closes_m[-1], "vs_EMA20": "выше" if closes_m[-1] > e20 else "ниже",
                       "vs_EMA50": "выше" if closes_m[-1] > e50 else "ниже",
                       "corr30_BTC": corr(c[-31:], closes_m[-31:]),
                       "last_date": s[-1][0]}
res["macro"] = macro

# ================= 8. ОПЦИОНЫ DERIBIT (max pain) =================
try:
    opt = jget_m("https://www.deribit.com/api/v2/public/get_book_summary_by_currency?currency=BTC&kind=option", "options")
    by_exp = defaultdict(lambda: defaultdict(lambda: {"C": 0.0, "P": 0.0}))
    for it in opt["result"]:
        nm = it["instrument_name"].split("-")  # BTC-26SEP26-85000-C
        if len(nm) != 4: continue
        exp, strike, typ = nm[1], float(nm[2]), nm[3]
        by_exp[exp][strike][typ] += (it.get("open_interest") or 0)
    # берём ближайшую экспиру с суммарным OI > 20k BTC
    best_exp, best_oi = None, -1
    for exp, strikes in by_exp.items():
        tot = sum(s["C"] + s["P"] for s in strikes.values())
        if tot > best_oi: best_exp, best_oi = exp, tot
    strikes = by_exp[best_exp]
    grid = range(int(price * 0.6), int(price * 1.4), 500)
    pain = {}
    for S in grid:
        p = sum(oi["C"] * max(0, S - K) + oi["P"] * max(0, K - S) for K, oi in strikes.items())
        pain[S] = p
    max_pain = min(pain, key=pain.get)
    top_calls = sorted(strikes.items(), key=lambda kv: -kv[1]["C"])[:3]
    top_puts = sorted(strikes.items(), key=lambda kv: -kv[1]["P"])[:3]
    res["options"] = {"expiry": best_exp, "total_oi_btc": round(best_oi, 0),
                      "max_pain": max_pain,
                      "top_call_walls": [[int(k), round(x["C"]/1000, 1)] for k, x in top_calls],
                      "top_put_walls": [[int(k), round(x["P"]/1000, 1)] for k, x in top_puts]}
except Exception as e:
    res["errors"].append(f"options: {e}")

# ================= 9. ЧЕК-ЛИСТ СЦЕНАРИЯ А =================
chk = []
chk.append(("Сжатие/поджатие у уровня", "PASS" if res["squeeze"]["active"] else "FAIL",
            f'диапазон10д/ATR={r10:.1f}, объём 5/20={vol_5_20:.2f}'))
chk.append(("Близость к ближ. сопротивлению (<2.5%)", "PASS" if nr_ and (nr_ - price)/price < 0.025 else "FAIL",
            (f"уровень {nr_:,.0f}, дистанция {100*(nr_-price)/price:.2f}%" + (" (prov.)" if prov_res and nr_ == prov_res else "")) if nr_ else "-"))
chk.append(("Тренд D1 вверх (EMA20>EMA50)", "PASS" if sum(c[-20:])/20 > sum(c[-50:])/50 else "FAIL", ""))
chk.append(("Каскад D1+W1 на сопротивлении", "PASS" if any(c_["side"] == "res" for c_ in cascades) else "FAIL/NEUTRAL",
            str([c_ for c_ in cascades if c_["side"] == "res"])))
chk.append(("Фандинг не перегрет (<0.01%/8ч)", "PASS" if abs(res.get("funding_now", 0)) < 0.01 else "FAIL",
            f'{res.get("funding_now")}%'))
chk.append(("OI растёт (деньги заходят)", "PASS" if res.get("oi_trend_3d_pct", 0) > 1 else "FAIL",
            f'{res.get("oi_trend_3d_pct")}% за 3д'))
chk.append(("Taker-агрессия покупателей (>1.05)", "PASS" if res.get("taker_1h_avg48", 0) > 1.05 else "FAIL",
            f'avg48h={res.get("taker_1h_avg48")}'))
chk.append(("Розница не перекошена в лонг (<1.4)", "PASS" if res.get("ls_accounts", [9])[-1] < 1.4 else "FAIL",
            f'{res.get("ls_accounts", [None])[-1]}'))
chk.append(("Нет стены продавца над уровнем", "INFO",
            str(res.get("book", {}).get("asks_R1_to_R1x1.02"))))
chk.append(("Закреп выше сопротивления (D1 close)", "WAIT — триггер",
            f'{res["daily_status"]["closes_above_res_prior3d"]} закрытий D1 из 3 выше {nr_:,.0f}' if nr_ else "-"))
# событийный день: метрики потока искажены — переводим их в INFO
if res.get("events_flag"):
    _evn = "; ".join(e["title"] for e in res["events_flag"])
    chk = [(t, ("INFO (событийный день)" if ("OI" in t or "Taker" in t or "стены" in t) else s),
            (f_ + " | искажено событием" if ("OI" in t or "Taker" in t or "стены" in t) else f_))
           for t, s, f_ in chk]
res["checklist_A"] = chk

passed = sum(1 for _, s, _ in chk if s == "PASS")
res["score_A"] = f"{passed}/{sum(1 for _, s, _ in chk if s in ('PASS','FAIL'))}"

json.dump({"asof": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "sources": MANIFEST},
          open(OUT + "/manifest_engine.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
with open(OUT + "/btc_full.json", "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
print("=== JSON saved ===")

# ================= ГРАФИК =================
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

N = 150; s0 = n - N
fig, (ax, axv, axd) = plt.subplots(3, 1, figsize=(13.5, 11), dpi=150,
                                   gridspec_kw={"height_ratios": [3.1, 1, 1.1]}, sharex=True)
for a_ in (ax, axv, axd):
    a_.set_facecolor("#0e1117")
fig.patch.set_facecolor("#0e1117")
up, dn = "#26a69a", "#ef5350"

for i in range(s0, n):
    col = up if c[i] >= o[i] else dn
    ax.plot([i, i], [l[i], h[i]], color=col, lw=0.8, zorder=2)
    ax.add_patch(Rectangle((i-0.36, min(o[i], c[i])), 0.72,
                           max(abs(c[i]-o[i]), price*1e-5), facecolor=col, edgecolor=col, lw=0.4, zorder=3))
    axv.bar(i, v[i], width=0.72, color=col, alpha=0.75)
    if v[i] > 2.2 * vma20[i]:
        axv.bar(i, v[i], width=0.72, color="#ffb300", alpha=0.95)
axv.plot(range(s0, n), vma20[s0:n], color="#f0b90b", lw=1.1, label="MA20 объёма")
axv.set_ylabel("Объём", color="#c9d1d9", fontsize=9)
axv.legend(loc="upper left", fontsize=8, facecolor="#0e1117", labelcolor="#c9d1d9")
axv.tick_params(colors="#8b949e"); axv.grid(alpha=0.12)

# производные панель: OI (bars) + taker (line, twinx)
try:
    ois = res["oi_b"]; k = len(ois)
    axd.bar(range(n-k, n), ois, width=0.8, color="#4a7fb5", alpha=0.8, label="OI, $ млрд")
    axd.set_ylabel("Open Interest, $ млрд", color="#7fb3ff", fontsize=8.5)
    axd.tick_params(colors="#8b949e", labelsize=7.5); axd.grid(alpha=0.12)
    axd2 = axd.twinx(); axd2.set_facecolor("none")
    tvd = res.get("taker_1d", [])
    if tvd:
        axd2.plot(range(n-len(tvd), n), tvd, color="#ffb300", lw=1.4, marker="o", ms=2.5,
                  label="taker buy/sell (1d)")
        axd2.axhline(1.0, color="#8b949e", lw=0.6, ls=":")
    axd2.set_ylabel("Taker buy/sell", color="#ffb300", fontsize=8.5)
    axd2.tick_params(colors="#8b949e", labelsize=7.5)
    l1, lb1 = axd.get_legend_handles_labels(); l2, lb2 = axd2.get_legend_handles_labels()
    axd.legend(l1+l2, lb1+lb2, loc="upper left", fontsize=7.5, facecolor="#0e1117", labelcolor="#c9d1d9")
except Exception as e:
    axd.text(0.5, 0.5, f"нет данных производных: {e}", color="#8b949e", transform=axd.transAxes, ha="center")

def line(p, col, lbl, ls="--", lw=1.4):
    ax.axhline(p, color=col, ls=ls, lw=lw, alpha=0.9)
    ax.text(n+1.5, p, f"{lbl}\n{p:,.0f}".replace(",", " "), color=col, fontsize=8.5,
            va="center", ha="left", fontweight="bold")

ymin, ymax = min(l[s0:]) * 0.985, max(h[s0:]) * 1.015
if R2 and R1: ax.fill_between(range(s0, n), R1, R2, color="#26a69a", alpha=0.10, zorder=1)
if S1 and S2: ax.fill_between(range(s0, n), S2, S1, color="#ef5350", alpha=0.10, zorder=1)
if R2: line(R2, "#1e8e5a", "R2 · цель пробоя R1")
if R1: line(R1, "#ef5350", "R1 · сопротивление")
if S1: line(S1, "#26a69a", "S1 · поддержка")
if S2: line(S2, "#8e3039", "S2 · зона риска")
for w in res.get("weekly_levels", []):
    if abs(w - price) / price < 0.12 and not any(abs(w - x) < 0.5*ATR for x in [R1, R2, S1, S2] if x):
        line(w, "#c77dff", "W1-уровень", ls=(0, (6, 3)), lw=1.1)
if res.get("cascades"):
    for cc in res["cascades"]:
        if cc["side"] == "res" and R1 and abs(cc["d1"] - R1) < 1:
            ax.text(s0+1, R1 + 0.35*ATR, "КАСКАД D1+W1 — зона усиленная", color="#c77dff", fontsize=8, fontweight="bold")
ax.axhline(price, color="#e6edf3", lw=0.8, alpha=0.6)
ax.text(n+1.5, price, f"сейчас\n{price:,.0f}".replace(",", " "), color="#e6edf3", fontsize=8.5, va="center", ha="left")

sq = "ЕСТЬ" if res["squeeze"]["active"] else "нет"
info = (f'сжатие: {sq} (диап/ATR {r10:.1f}, об.5/20 {vol_5_20:.2f})\n'
        f'фандинг: {res.get("funding_now","—")}%/8ч   OI 3д: {res.get("oi_trend_3d_pct","—")}%\n'
        f'taker buy/sell 48ч: {res.get("taker_1h_avg48","—")}   розница L/S: {res.get("ls_accounts",[None])[-1]}\n'
        f'чек-лист А: {res["score_A"]} PASS   закреп выше R1: НЕТ (ждать D1 close > {R1:,.0f})'.replace(",", " "))
ax.text(0.012, 0.975, info, transform=ax.transAxes, color="#c9d1d9", fontsize=8.6, va="top", ha="left",
        bbox=dict(facecolor="#161b22", edgecolor="#30363d", alpha=0.92))

ticks = list(range(s0, n, 12))
ax.set_xticks(ticks)
ax.set_xticklabels([time.strftime("%d.%m", time.gmtime(ts[i])) for i in ticks])
ax.set_xlim(s0-1, n+16); ax.set_ylim(ymin, ymax)
ax.tick_params(colors="#8b949e"); ax.grid(alpha=0.12)
for a_ in (ax, axv, axd):
    for sp in a_.spines.values(): sp.set_color("#30363d")
ax.set_title(f"BTC/USDT · D1 · {src} · «Уровень + поток» v2 (уровни+каскады+производные) · {res['last_date']}",
             color="#e6edf3", fontsize=12, pad=10)
fig.text(0.995, 0.005, "реконструкция стратегии из чата; не инвестрекомендация", color="#8b949e", fontsize=7, ha="right")
plt.tight_layout()
plt.savefig(OUT + "/btc_full.png", facecolor=fig.get_facecolor(), bbox_inches="tight")
print("PNG saved")
