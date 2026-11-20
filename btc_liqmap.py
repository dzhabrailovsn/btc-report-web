# -*- coding: utf-8 -*-
"""Модель карты ликвидаций BTC: кластеры стоп-аутов по часовому ΔOI и taker-потоку.
Плечи 10x/25x/50x, равные веса. Выход: liq_map.json + liq_map.png"""
import os
import io, sys, json, time, urllib.request
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
OUT = os.environ.get("BTC_REPORT_DIR") or os.path.dirname(os.path.abspath(__file__))

def _jget(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))

def _load_or_fetch(name, url, transform):
    try:
        data = transform(_jget(url))
        json.dump(data, open(OUT + "/" + name, "w"))
        return data
    except Exception:
        try:
            return json.load(open(OUT + "/" + name))
        except Exception:
            return None

_now = int(time.time() * 1000)
_beg = _now - 21 * 86400000
oi = _load_or_fetch("oi_1h.json",
    "https://www.okx.com/api/v5/rubik/stat/contracts/open-interest-volume?ccy=BTC&period=1H&begin=" + str(_beg) + "&end=" + str(_now),
    lambda d: d["data"])
def _fetch_k1h():
    seen = {}
    after = None
    for _ in range(3):  # пагинация: OKX отдаёт <=300 свечей за страницу
        u = "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1H&limit=300"
        if after:
            u += "&after=" + str(after)
        d = _jget(u)["data"]
        if not d:
            break
        for x in d:
            if str(x[8]) == "1":
                seen[int(x[0])] = [int(x[0])] + [float(v) for v in x[1:6]]
        after = min(int(x[0]) for x in d)
        time.sleep(0.4)
    return [seen[k] for k in sorted(seen)][-600:]  # последние ~25 дней
try:
    k1 = _fetch_k1h()
    json.dump(k1, open(OUT + "/k1h.json", "w"))
except Exception:
    try:
        k1 = json.load(open(OUT + "/k1h.json"))
    except Exception:
        k1 = None
tk = _load_or_fetch("taker_1h_500.json",
    "https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy=BTC&instType=CONTRACTS&period=1H",
    lambda d: d["data"])
if not (oi and k1 and tk):
    _out = {"disabled": True, "note": "карта ликвидаций: нет часовых данных (сеть/источник)"}
    json.dump(_out, open(OUT + "/liq_map.json", "w", encoding="utf-8"), ensure_ascii=False)
    print(json.dumps(_out, ensure_ascii=False))
    sys.exit(0)

oi_map = {int(x[0]): float(x[1]) for x in oi}  # OKX rubik: [ts, oiUSD, volUSD]
tk_map = {}
for x in tk:  # OKX rubik taker: [ts, buyVol, sellVol] -> ratio
    try:
        b, s = float(x[1]), float(x[2])
        tk_map[int(x[0])] = b / (b + s) if (b + s) > 0 else 1.0
    except Exception:
        pass

price_now = float(k1[-1][4])
long_liq = defaultdict(float)   # цена -> $ ликвидаций лонгов (ниже)
short_liq = defaultdict(float)  # цена -> $ ликвидаций шортов (выше)
tiers = [(10, 0.095), (25, 0.035), (50, 0.015)]  # (плечо, ~дистанция до ликвидации)

prev = None
for k in k1:
    ts0 = k[0]
    if ts0 not in oi_map: continue
    oi_v = oi_map[ts0]
    if prev is not None and oi_v > prev:
        d_oi = oi_v - prev          # новые открытые позиции, $
        ratio = tk_map.get(ts0, 1.0)
        buy_share = ratio / (1 + ratio)
        entry = float(k[4])         # close часа = оценка входа
        for _, dist in tiers:
            w = d_oi * (1 / len(tiers))
            long_liq[entry * (1 - dist)] += w * buy_share
            short_liq[entry * (1 + dist)] += w * (1 - buy_share)
    prev = oi_v

BIN = 250  # бин $250
def binned(d):
    b = defaultdict(float)
    for p, usd in d.items():
        b[round(p / BIN) * BIN] += usd
    return b

lb, sb = binned(long_liq), binned(short_liq)
below = sorted([(p, u) for p, u in lb.items() if p < price_now * 0.995], key=lambda x: -x[1])[:8]
above = sorted([(p, u) for p, u in sb.items() if p > price_now * 1.005], key=lambda x: -x[1])[:8]

# страховка покрытия (паттерн Astra): <400 часов истории — модель отключается
coverage_h = round((k1[-1][0] - k1[0][0]) / 3600000, 0)
if coverage_h < 400:
    out = {"disabled": True, "coverage_h": coverage_h,
           "note": "модель ликвидаций отключена: недостаточное покрытие часовых данных (<400ч)"}
    json.dump(out, open(OUT + "/liq_map.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0)

out = {"price": price_now,
       "time": time.strftime("%d.%m %H:%M UTC", time.gmtime(k1[-1][0] / 1000)),
       "coverage_h": coverage_h,
       "long_liq_below_top": [[round(p), round(u / 1e6, 1)] for p, u in below],
       "short_liq_above_top": [[round(p), round(u / 1e6, 1)] for p, u in above],
       "sum_long_below_m": round(sum(u for lp_, u in lb.items() if lp_ < price_now) / 1e6, 0),
       "note": "модель (НЕ наблюдаемые ликвидации): ΔOI(1h)×направление(taker)×плечи 10/25/50x"}
json.dump(out, open(OUT + "/liq_map.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))

# ============ ГРАФИК liq_map.png ============
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

fig, ax = plt.subplots(figsize=(11.5, 7.2), dpi=150)
fig.patch.set_facecolor("#0e1117"); ax.set_facecolor("#0e1117")

lo_p, hi_p = price_now * 0.87, price_now * 1.13
allp = sorted(set(list(lb.keys()) + list(sb.keys())))
rows = [p for p in allp if lo_p <= p <= hi_p]
vals_l = np.array([lb.get(p, 0) / 1e6 for p in rows])
vals_s = np.array([sb.get(p, 0) / 1e6 for p in rows])

y = np.arange(len(rows))
ax.barh(y, -vals_l, color="#ef5350", alpha=0.85, height=0.8, label="ликвидации ЛОНГОВ (топливо вниз)")
ax.barh(y, vals_s, color="#26a69a", alpha=0.85, height=0.8, label="ликвидации ШОРТОВ (топливо вверх)")
ax.set_yticks(y)
ax.set_yticklabels([f"{p:,.0f}".replace(",", " ") for p in rows], fontsize=6.5, color="#c9d1d9")

# уровни-ориентиры берём из свежего btc_full.json (не константы!)
try:
    _d2 = json.load(open(OUT + "/btc_full.json", encoding="utf-8"))
    _lv = _d2.get("levels", {}); _opt = _d2.get("options", {})
    _marks = [(_lv.get("nearest_res") or _lv.get("R1"), "ближ. сопротивление", "#ef5350", "--"),
              (_lv.get("w1_defense"), "W1 · оборона", "#c77dff", "--"),
              (_lv.get("S1"), "S1 · поддержка", "#26a69a", "--"),
              (_opt.get("max_pain"), "max pain", "#ffb300", ":")]
except Exception:
    _marks = []
for p, lbl, col, ls in _marks:
    if p and lo_p <= p <= hi_p:
        idx = min(range(len(rows)), key=lambda i: abs(rows[i] - p))
        ax.axhline(idx, color=col, ls=ls, lw=1.2, alpha=0.8)
        ax.text(ax.get_xlim()[1] * 0.62, idx, f"{lbl} {p:,.0f}".replace(",", " "), color=col, fontsize=8.5, va="bottom", fontweight="bold")

idx_now = min(range(len(rows)), key=lambda i: abs(rows[i] - price_now))
ax.axhline(idx_now, color="#e6edf3", lw=1.4)
ax.text(ax.get_xlim()[1] * 0.62, idx_now, f"ЦЕНА {price_now:,.0f}".replace(",", " "), color="#e6edf3",
        fontsize=9, va="bottom", fontweight="bold")

ax.axvline(0, color="#8b949e", lw=0.8)
ax.set_xlabel("Оценка ликвидаций, $ млн (модель ΔOI × taker × плечи 10/25/50x)", color="#c9d1d9", fontsize=9)
ax.tick_params(colors="#8b949e")
ax.grid(alpha=0.12, axis="x")
for sp in ax.spines.values(): sp.set_color("#30363d")
ax.legend(loc="lower right", facecolor="#0e1117", labelcolor="#c9d1d9", fontsize=8.5)
ax.set_title(f"BTC/USDT · карта ликвидаций (модель, 20 дней истории 1h) · {out['time']}",
             color="#e6edf3", fontsize=11.5, pad=10)
fig.text(0.995, 0.005, "оценка, не оригинал Coinglass; не инвестрекомендация", color="#8b949e", fontsize=7, ha="right")
plt.tight_layout()
plt.savefig(OUT + "/liq_map.png", facecolor=fig.get_facecolor(), bbox_inches="tight")
print("liq_map.png saved")
