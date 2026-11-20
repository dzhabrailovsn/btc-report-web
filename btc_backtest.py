# -*- coding: utf-8 -*-
"""Бэктест уровневого ядра, строгий протокол (по аудиту Astra):
- свечи 1Dutc, только подтверждённые (без подглядывания в неполные)
- сигнал по закрытию, вход по OPEN следующей свечи
- одна позиция; стоп = W1-оборона (причинная) − 0.1 ATR; цель 2R; таймаут 10 баров (выход по close)
- гэп через стоп/цель исполняется по open; издержки 0.1% на сторону
- незавершённые сделки не считаются
Выход: backtest.json (метрики + чувствительность порогов)."""
import os
import io, sys, json, time, urllib.request
from collections import defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
UA = {"User-Agent": "Mozilla/5.0"}
OUT = os.environ.get("BTC_REPORT_DIR") or os.path.dirname(os.path.abspath(__file__))
DAY = 86400000

def jget(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

# --- история: только подтверждённые 1Dutc ---
rows = []
after = None
for _ in range(8):
    u = "https://www.okx.com/api/v5/market/history-candles?instId=BTC-USDT&bar=1Dutc&limit=100"
    if after:
        u += f"&after={after}"
    batch = None
    for attempt in range(2):
        try:
            batch = [x for x in jget(u)["data"] if str(x[8]) == "1"]
            break
        except Exception:
            time.sleep(3)
    if not batch:
        break
    rows += [(int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])) for x in batch]
    after = batch[-1][0]
    time.sleep(0.5)
    if len(rows) >= 420:
        break
# фолбэк: рабочие свечи постранично
if len(rows) < 200:
    rows = []
    after = None
    for _ in range(5):
        u = "https://www.okx.com/api/v5/market/candles?instId=BTC-USDT&bar=1Dutc&limit=100"
        if after:
            u += f"&after={after}"
        try:
            batch = [x for x in jget(u)["data"] if str(x[8]) == "1"]
        except Exception:
            time.sleep(3)
            try:
                batch = [x for x in jget(u)["data"] if str(x[8]) == "1"]
            except Exception:
                break
        if not batch:
            break
        rows += [(int(x[0]), float(x[1]), float(x[2]), float(x[3]), float(x[4]), float(x[5])) for x in batch]
        after = batch[-1][0]
        time.sleep(0.5)

seen = {}
for r in rows:
    seen[r[0]] = r
rows = sorted(seen.values())
n = len(rows)
if n < 200:
    print(f"мало истории: {n}")
    json.dump({"error": f"мало истории: {n}"}, open(OUT + "/backtest.json", "w", encoding="utf-8"))
    sys.exit(1)
ts = [r[0] / 1000 for r in rows]
o = [r[1] for r in rows]; h = [r[2] for r in rows]; l = [r[3] for r in rows]
c = [r[4] for r in rows]; v = [r[5] for r in rows]

trs = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, n)]
atr = [sum(trs[max(0, i - 13):i + 1]) / len(trs[max(0, i - 13):i + 1]) for i in range(n)]

def ema_series(arr, p):
    k = 2 / (p + 1); e = [arr[0]]
    for x in arr[1:]:
        e.append(x * k + e[-1] * (1 - k))
    return e
e20, e50 = ema_series(c, 20), ema_series(c, 50)

K = 5
piv_conf = []  # (confirm_idx, price)
for i in range(K, n - K):
    if h[i] == max(h[i - K:i + K + 1]):
        piv_conf.append((i + K, h[i]))
    if l[i] == min(l[i - K:i + K + 1]):
        piv_conf.append((i + K, l[i]))

# недельные бары (полные недели) с индексом последнего дня недели
wk_groups = defaultdict(list)
for i in range(n):
    wk_groups[ts[i] // 604800].append(i)
wk_bars = []
for k in sorted(wk_groups):
    g = wk_groups[k]
    if len(g) != 7 or ts[g[-1]] - ts[g[0]] != 6 * 86400:
        continue
    wk_bars.append({"last_i": g[-1], "h": max(h[i] for i in g), "l": min(l[i] for i in g)})
wp_conf = []  # (confirm_last_i, price)
for j in range(2, len(wk_bars) - 2):
    win = wk_bars[j - 2:j + 3]
    if wk_bars[j]["h"] == max(x["h"] for x in win):
        wp_conf.append((win[-1]["last_i"], wk_bars[j]["h"]))
    if wk_bars[j]["l"] == min(x["l"] for x in win):
        wp_conf.append((win[-1]["last_i"], wk_bars[j]["l"]))

def levels_at(t):
    """причинный срез на конец дня t: (R1, W1-оборона, ATR, сжатие, тренд)"""
    A = atr[t]
    tol = max(0.006 * c[t], 0.4 * A)
    tw = max(0.012 * c[t], 2 * A)
    act = sorted(p for ci, p in piv_conf if ci <= t)
    cl = []
    for p in act:
        if cl and abs(p - cl[-1][-1]) <= tol:
            cl[-1].append(p)
        else:
            cl.append([p])
    lev = [sum(g) / len(g) for g in cl]
    lev += [x for x in (max(h[t - 4:t + 1]), min(l[t - 4:t + 1]))]
    r1 = min([x for x in lev if x > c[t]], default=None)
    wpt = sorted(p for ci, p in wp_conf if ci <= t)
    wcl = []
    for p in wpt:
        if wcl and abs(p - wcl[-1][-1]) <= tw:
            wcl[-1].append(p)
        else:
            wcl.append([p])
    wlev = [sum(g) / len(g) for g in wcl]
    wd = max([x for x in wlev if x < c[t]], default=None)
    vr = (sum(v[t - 4:t + 1]) / 5) / (sum(v[t - 19:t + 1]) / 20)
    rng = (max(h[t - 9:t + 1]) - min(l[t - 9:t + 1])) / A
    trend = e20[t] > e50[t] and c[t] > e20[t]
    return r1, wd, A, rng, vr, trend

def run(sq_thr, dist_thr, hold=10, stop_buf=0.1, tgt_r=2.0, fee=0.001, warmup=120):
    trades, signals = [], 0
    i = warmup
    while i < n - 2:
        r1, wd, A, rng, vr, trend = levels_at(i)
        prev_c = c[i]
        if not (r1 and wd):
            i += 1; continue
        if not (rng < sq_thr and vr < 0.9 and trend and (r1 - prev_c) / prev_c < dist_thr):
            i += 1; continue
        # сигнал: закрытие i выше R1, известного до свечи i
        sig_r1, _, _, _, _, _ = levels_at(i - 1)
        if not (sig_r1 and c[i] > sig_r1):
            i += 1; continue
        signals += 1
        entry = o[i + 1]
        stop = wd - stop_buf * A
        risk = entry - stop
        if risk <= 0:
            i += 1; continue
        target = entry + tgt_r * risk
        end = min(i + 1 + hold, n - 1)
        exit_px = reason = None
        j = i + 1
        while j <= end:
            if o[j] <= stop:
                exit_px, reason = o[j], "gap stop"; break
            if l[j] <= stop:
                exit_px, reason = stop, "stop"; break
            if o[j] >= target:
                exit_px, reason = o[j], "gap target"; break
            if h[j] >= target:
                exit_px, reason = target, f"{tgt_r:.0f}R target"; break
            if j == end:
                exit_px, reason = c[j], "timeout"; break
            j += 1
        if exit_px is None:
            i = end + 1; continue
        net = (exit_px - entry - fee * (entry + exit_px)) / risk
        trades.append({"signal": time.strftime("%d.%m.%y", time.gmtime(ts[i])),
                       "entry": round(entry, 0), "stop": round(stop, 0), "exit": round(exit_px, 0),
                       "R": round(net, 2), "reason": reason})
        i = j + 1
    rs = [t["R"] for t in trades]
    return {"signals": signals, "n": len(rs),
            "win_rate": round(100 * sum(r > 0 for r in rs) / len(rs), 0) if rs else 0,
            "avg_R": round(sum(rs) / len(rs), 2) if rs else 0,
            "sum_R": round(sum(rs), 1) if rs else 0,
            "trades": trades[-12:]}

base = run(3.2, 0.025)
sens = []
for sq in (2.5, 3.2, 4.0):
    for dist in (0.015, 0.025, 0.035):
        r = run(sq, dist)
        sens.append([sq, dist, r["signals"], r["n"], r["win_rate"], r["avg_R"]])

out = {"period": f"{time.strftime('%d.%m.%y', time.gmtime(ts[0]))} — {time.strftime('%d.%m.%y', time.gmtime(ts[-1]))}",
       "bars": n, "protocol": "1Dutc подтверждённые; вход open следующей; стоп W1−0.1ATR; цель 2R/10 баров; издержки 0.1%/сторона; гэпы по open; одна позиция",
       "base": {k: base[k] for k in ("signals", "n", "win_rate", "avg_R", "sum_R")},
       "last_trades": base["trades"],
       "sensitivity": sens,
       "caveat": "строгий протокол с издержками; выборка мала; потоковые фильтры (OI/taker/стакан) не бэктестятся — бесплатной годовой истории нет"}
json.dump(out, open(OUT + "/backtest.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({k: out[k] for k in ("period", "bars", "base")}, ensure_ascii=False))
for s in sens:
    print("  sq<%.1f dist<%.1f%% -> сигналов %d, сделок %d, win %s%%, avgR %s" % (s[0], s[1] * 100, s[2], s[3], s[4], s[5]))
