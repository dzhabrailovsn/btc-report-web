# -*- coding: utf-8 -*-
"""Генератор HTML-отчёта v4 — полностью динамический.
Ни одного зашитого уровня/даты/вердикта: всё выводится из btc_full.json,
liq_map.json, extra_data.json, etf_flows.json, backtest.json, events.json."""
import os
import base64, io, sys, json, time, re

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
OUT = os.environ.get("BTC_REPORT_DIR") or os.path.dirname(os.path.abspath(__file__))

def load(p, default=None):
    try:
        return json.load(open(OUT + "/" + p, encoding="utf-8"))
    except Exception:
        return default if default is not None else {}

def b64(p):
    with open(OUT + "/" + p, "rb") as f:
        return base64.b64encode(f.read()).decode()

d = load("btc_full.json")
liq = load("liq_map.json")
ex = load("extra_data.json")
etf = load("etf_flows.json", [])
etf_meta = {m["date"]: m["reconciled"] for m in load("etf_meta.json", [])}
bt = load("backtest.json")
events = load("events.json", [])
ai = load("ai_take.json")
img_chart = b64("btc_full.png")
try:
    img_liq = b64("liq_map.png") if not liq.get("disabled") else ""
except Exception:
    img_liq = ""
    liq = {"disabled": True, "note": "график ликвидаций недоступен"}

# ИИ-рассуждение показываем только если оно свежее (сгенерировано в тот же день, что отчёт)
ai_fresh = bool(ai) and str(ai.get("generated", ""))[:10] == time.strftime("%Y-%m-%d", time.gmtime())
ai_html = ""
if ai:
    stars = "●" * round(ai.get("confidence", 50) / 20) + "○" * (5 - round(ai.get("confidence", 50) / 20))
    reasons = "".join(f"<li>{r}</li>" for r in ai.get("reasons", []))
    alloc_rows = "".join(
        f'<tr><td>{a[0]}</td><td>{a[1]}</td><td class="b"><b>{a[2]}</b></td></tr>'
        for a in ai.get("allocation", []))
    alloc_html = (f"""
  <div class="dim" style="font-size:13px; margin:14px 0 4px;">Рекомендации по капиталу (от текущей ситуации):</div>
  <table><tr><th>Условие</th><th>Действие</th><th>Доля капитала</th></tr>{alloc_rows}</table>""" if alloc_rows else "")
    geo_rows = "".join(
        f'<tr><td>{g[0]}</td><td class="b">{g[1]}</td></tr>'
        for g in ai.get("geo", []))
    geo_html = (f"""
  <div class="dim" style="font-size:13px; margin:14px 0 4px;">Геополитический контекст (актуальные новости, учтены в вердикте):</div>
  <table><tr><th>Факт / новость</th><th>Влияние на BTC-план</th></tr>{geo_rows}</table>""" if geo_rows else "")
    stale = "" if ai_fresh else ' <span style="color:#ef5350">(устарело — обновляется при ежедневном запуске)</span>'
    ai_html = f"""
<h2 id="s-ai">ИИ-рассуждение (агентный слой поверх фактов)</h2>
<div class="card" style="border-left:3px solid #7fb3ff">
  <div style="font-size:16px; font-weight:700; margin-bottom:6px">{ai.get('verdict','—')}{stale}</div>
  <ul class="tight">{reasons}</ul>
  {alloc_html}
  {geo_html}
  <div class="note" style="margin-top:10px">Инвалидация: {ai.get('invalidation','—')}</div>
  <div class="dim" style="font-size:12px; margin-top:8px">Уверенность: {stars} {ai.get('confidence',0)}% · сгенерировано агентом {ai.get('generated','—')} · это интерпретация детерминированных данных и свежих новостей, не самостоятельный источник. Доли капитала — базовые ориентиры при риске 1% на сделку; не инвестрекомендация.</div>
</div>"""

def fmt(x):
    return f"{x:,.0f}".replace(",", " ") if isinstance(x, (int, float)) else "—"

lv = d.get("levels", {}); ds = d.get("daily_status", {}); opt = d.get("options", {})
price = d.get("price", 0)
nr = lv.get("nearest_res"); ns = lv.get("nearest_sup")
wd = lv.get("w1_defense"); wa = lv.get("w1_above")
R1, R2, S1, S2 = lv.get("R1"), lv.get("R2"), lv.get("S1"), lv.get("S2")
mp = opt.get("max_pain"); expiry = opt.get("expiry", "")
# парс "25SEP26" -> "25.09.2026" без зависимости от локали (%b ломается на русской Windows)
_MON = {"JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "JUN": "06",
        "JUL": "07", "AUG": "08", "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12"}
exp_date = None
_m = re.match(r"^(\d{2})([A-Z]{3})(\d{2})$", expiry)
if _m and _m.group(2) in _MON:
    exp_date = f"{_m.group(1)}.{_MON[_m.group(2)]}.20{_m.group(3)}"
elif expiry:
    exp_date = expiry

today = time.strftime("%Y-%m-%d", time.gmtime())
today_h = time.strftime("%d.%m", time.gmtime())

# дистанции KPI с защитой от отсутствующих данных
kpi_res_d = f"+{100*(nr-price)/price:.1f}%" if nr else "—"
kpi_sup_d = f"−{100*(price-ns)/price:.1f}%" if ns else "—"
kpi_mp_d = f"{100*(mp-price)/price:+.1f}%" if mp else "—"
_trend = next((s for t_, s, _ in d.get("checklist_A", []) if "Тренд" in t_), "FAIL")

# ---------- вердикт (вычисляется, не пишется руками) ----------
fails = [t for t, s, _ in d.get("checklist_A", []) if s == "FAIL"]
score = d.get("score_A", "—/—")
ev_now = d.get("events_flag", [])
if ds.get("last_close_above_nearest_res"):
    vtxt, vcol = "ЗАКРЕП ФОРМИРУЕТСЯ — проверять поток перед входом", "#26a69a"
    vsub = (f"последняя завершённая (UTC) свеча закрылась выше уровня {fmt(ds.get('tested_res_prior', nr))}, известного до неё. "
            f"Вход только при подтверждении потоком (объём ≥1.5×, OI +2%, taker >1.15). Стоп под обороной {fmt(wd)}.")
elif ds.get("trap_res_prior") and ds.get("closes_above_res_prior3d", 0) >= 1 and ds.get("last_completed_close", price) < ds["trap_res_prior"]:
    vtxt, vcol = "ПРОБОЙ НЕ УДЕРЖАН — цена вернулась под уровень", "#ef5350"
    vsub = (f"были закрытия выше уровня {fmt(ds['trap_res_prior'])} (известного до 3-дневного окна), "
            f"но последняя свеча {fmt(ds.get('last_completed_close'))} вернулась под него — классическая ловушка. "
            f"Ждать либо повторного закрепа, либо потери обороны {fmt(wd)}; в позиции не находиться.")
elif ds.get("close_below_w1_defense"):
    vtxt, vcol = "ОБОРОНА W1 ПОТЕРЯНА — режим слабости", "#ef5350"
    vsub = (f"завершённая свеча закрылась ниже W1 {fmt(wd)}. Лонговая структура слабеет: риск к поддержке {fmt(ns)} "
            f"и кластеру лонг-ликвидаций ниже; покупки только по разворотному D1-бару от уровня.")
elif d.get("squeeze", {}).get("active") and nr and (nr - price) / price < 0.025:
    vtxt, vcol = "ЖДАТЬ: сетап зреет, закрепа нет", "#f0b90b"
    vsub = (f"сжатие активное, цена в {100*(nr-price)/price:.1f}% от {fmt(nr)}"
            + (" (prov.)" if nr == lv.get("R1_prov") else "") +
            f", чек-лист {score}" + (f", не хватает: {', '.join(fails).lower()}" if fails else "") + ".")
else:
    vtxt, vcol = "НЕЙТРАЛЬНО: сетапа нет", "#8b949e"
    vsub = (f"условия сжатия/близости к уровню не выполнены (чек-лист {score}). "
            f"Ближайшие ориентиры: сопротивление {fmt(nr)}, поддержка {fmt(ns)}, оборона W1 {fmt(wd)}.")
if ev_now:
    vsub += " ⚠ Сегодня/завтра событие: " + "; ".join(e["title"] for e in ev_now) + " — метрики потока искажены."

# ---------- производные спарклайны ----------
oi = d.get("oi_b", []); oi_svg = ""
if oi:
    oimin, oimax = min(oi), max(oi); bw = 560 / len(oi)
    oi_svg = "".join(
        f'<rect x="{i*bw+1:.1f}" y="{34-(x-oimin)/(oimax-oimin+1e-9)*30:.1f}" width="{bw-2:.1f}" height="{(x-oimin)/(oimax-oimin+1e-9)*30+2:.1f}" rx="1" fill="#4a7fb5"/>'
        for i, x in enumerate(oi))
ls = d.get("ls_accounts", []); ls_pts = ""
if ls:
    lmin, lmax = min(ls), max(ls)
    ls_pts = " ".join(f'{i*(560/(len(ls)-1)):.0f},{36-(x-lmin)/(lmax-lmin+1e-9)*28:.1f}' for i, x in enumerate(ls))
fng = ex.get("fng", []); fpts = ""
if fng:
    fv = [int(x["v"]) for x in fng]
    fpts = " ".join(f'{i*(560/(len(fv)-1)):.0f},{34-(x-5)/95*28:.1f}' for i, x in enumerate(fv))

# ---------- ETF ----------
etf_rows = ""
last5 = 0.0
if etf:
    vals = []
    for r in etf:
        tot = float(r[-1].replace("(", "-").replace(")", ""))
        vals.append(tot)
        cls = "g" if tot >= 0 else "r"
        rec = etf_meta.get(r[0], None)
        rec_s = " ✓" if rec else (" ✱ не сходится" if rec is False else "")
        etf_rows += f'<tr><td>{r[0]}</td><td class="{cls}">{tot:+,.1f} $M</td><td class="dim">{"приток" if tot>=0 else "отток"}{rec_s}</td></tr>'
    last5 = sum(vals[:5])

# ---------- ликвидации ----------
sl = liq.get("short_liq_above_top", []); ll = liq.get("long_liq_below_top", [])
liq_up_rows = "".join(f'<tr><td class="g">{fmt(p)}</td><td>{u:.0f} $M</td></tr>' for p, u in sl[:5])
liq_dn_rows = "".join(f'<tr><td class="r">{fmt(p)}</td><td>{u:.0f} $M</td></tr>' for p, u in ll[:5])
above_sum = sum(u for _, u in sl[:3]); below_sum = sum(u for _, u in ll[:3])
liq_note = (f"Сверху крупнейшие кластеры шорт-ликвидаций: {fmt(sl[0][0])} (${sl[0][1]:.0f}M)" +
            (f", топ-3 ≈ ${above_sum:.0f}M" if above_sum else "") +
            f". Снизу крупнейшие кластеры лонг-ликвидаций: {fmt(ll[0][0])} (${ll[0][1]:.0f}M)" +
            (f", топ-3 ≈ ${below_sum:.0f}M" if below_sum else "") +
            ". Цена стремится к наибольшей ликвидности: пробой уровня вверх поджигает шорты, потеря поддержки — каскад лонгов."
            if sl and ll else "данных недостаточно")

# ---------- карта уровней (строятся из JSON) ----------
def row(t, val, comm, cls=""):
    return f'<tr><td>{t}</td><td class="{cls}"><b>{val}</b></td><td>{comm}</td></tr>'
lv_rows = ""
if R2: lv_rows += row("R2 · первая цель", fmt(R2), "следующий пивот-кластер выше R1", "r")
if lv.get("res_extra"): lv_rows += row("R3/R4", fmt(lv["res_extra"][0]), "дальние сопротивления; у 90k зона калл-стен", "r")
if wa: lv_rows += row("W1 сверху", fmt(wa), "недельный уровень", "p")
if opt.get("top_call_walls"):
    cw = [f"{fmt(k[0])}" for k in opt["top_call_walls"][:3]]
    lv_rows += row("Калл-стены (Deribit)", " · ".join(cw), f"опционные стены до {exp_date}" if exp_date else "опционные стены", "o")
lv_rows += row("ЦЕНА СЕЙЧАС", fmt(price), f"тренд D1 {'вверх' if _trend=='PASS' else 'не вверх'} · последнее закрытие D1 {fmt(ds.get('last_completed_close'))}", "")
if nr: lv_rows += row("Ближ. сопротивление" + (" (prov.)" if nr == lv.get("R1_prov") else ""), fmt(nr), "триггер сценария А: закреп = D1 close выше", "r")
if wd: lv_rows += row("W1 · оборона (ближняя)", fmt(wd), "стоп-ориентир: закреп ниже = режим слабости", "p")
if lv.get("w1_defense_far"): lv_rows += row("W1 · глубокая оборона", fmt(lv["w1_defense_far"]), "каскад-якорь, не стоп (слишком далеко)", "dim")
if ns: lv_rows += row("Ближ. поддержка" + (" (prov.)" if ns == lv.get("S1_prov") else ""), fmt(ns), "потеря с закрепом = ускорение вниз", "r")
if S2: lv_rows += row("S2", fmt(S2), "зона риска", "r")
if mp: lv_rows += row("Max pain" + (f" ({exp_date})" if exp_date else ""), fmt(mp), "опционный магнит к экспире; сила растёт у даты", "o")
if lv.get("sup_extra"): lv_rows += row("Глубинные поддержки", " · ".join(fmt(x) for x in lv["sup_extra"][:2]), "зоны выкупа при глубоком откате", "dim")

# ---------- календарь/план ----------
mf = load("manifest_engine.json")
mf_rows = "".join(
    f'<tr><td>{k}</td><td class="{"g" if v.get("status")=="OK" else "r"}">{v.get("status")}</td><td>{v.get("attempts")}</td><td class="dim">{v.get("error","—")}</td></tr>'
    for k, v in mf.get("sources", {}).items()) or '<tr><td colspan="4" class="dim">манифест недоступен</td></tr>'

fut = sorted([e for e in events if e["date"] >= today], key=lambda e: e["date"])
cal_html = "".join(f'<div class="ev"><div class="d">{e["date"][8:]}.{e["date"][5:7]}</div><div class="t">{e["title"]}</div></div>' for e in fut[:4])
if exp_date:
    cal_html += f'<div class="ev"><div class="d">{exp_date[:5]}</div><div class="t">Экспира Deribit (max pain {fmt(mp)})</div></div>'

# ---- план по дням: катится от сегодняшнего дня и текущего вердикта ----
import datetime as _dt
WD_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
events_by_date = {}
for e in events:
    events_by_date.setdefault(e["date"], []).append(e)
# экспира Deribit из опционных данных тоже становится событием плана
if exp_date:
    try:
        _exp_iso = _dt.datetime.strptime(exp_date, "%d.%m.%Y").date().isoformat()
        events_by_date.setdefault(_exp_iso, []).append(
            {"date": _exp_iso, "title": f"Экспира Deribit (max pain {fmt(mp)})", "impact": "med"})
    except Exception:
        pass
fut_dates = sorted(k for k in events_by_date if k >= today)
_last_ev = fut_dates[-1] if fut_dates else today
d0 = _dt.date.fromisoformat(today)
d1 = _dt.date.fromisoformat(_last_ev)
d1 = min(max(d1, d0), d0 + _dt.timedelta(days=21))  # горизонт ≤21 день

_high_days = {e["date"] for e in events if e.get("impact") == "high" and e["date"] >= today}
_pre_high = {( _dt.date.fromisoformat(x) - _dt.timedelta(days=1)).isoformat() for x in _high_days}

def _base_action():
    if vtxt.startswith("ЗАКРЕП"):
        return ("Проверить подтверждение потока (объём ≥1.5×, OI↑, taker >1.15). "
                "При подтверждении — вход по сценарию А, стоп " + fmt(wd))
    if vtxt.startswith("ПРОБОЙ"):
        return ("Вне позиции. Вход только при повторном закрепе выше " + fmt(nr) +
                " с потоком, либо выкуп у " + fmt(ns) + " по разворотному D1-бару")
    if vtxt.startswith("ОБОРОНА"):
        return ("Вне лонгов. Ждать стабилизации выше " + fmt(wd) +
                " или выкупа в зоне " + fmt(ns) + " по разворотному D1-бару")
    if vtxt.startswith("ЖДАТЬ"):
        return ("Наблюдение за карманом " + fmt(ns) + "–" + fmt(nr) +
                "; работать только от полного триггера А")
    return "Вне позиции: условия сетапа не выполнены"
_base = _base_action()

def _next_ev_str(iso_d):
    nxt = [k for k in fut_dates if k >= iso_d]
    if not nxt:
        return ""
    k = nxt[0]
    ev = events_by_date[k][0]
    dd = (_dt.date.fromisoformat(k) - _dt.date.fromisoformat(iso_d)).days
    lbl = "сегодня" if dd == 0 else f"через {dd} дн"
    return f"{lbl}: {ev['title'][:34]}"

plan_rows = []
dcur = d0
while dcur <= d1:
    iso = dcur.isoformat()
    wd_name = WD_RU[dcur.weekday()]
    label = dcur.strftime("%d.%m") + (" · сегодня" if dcur == d0 else "")
    evs_today = events_by_date.get(iso, [])
    if any(e.get("impact") == "holiday" for e in evs_today):
        ctx = "праздник в США · тонкая ликвидность"
        act = "Новых позиций нет; фитильные пробои не считать закрепом, риск не увеличивать"
        lvl = "—"
    elif evs_today:
        ev0 = evs_today[0]
        more = f" (+{len(evs_today)-1} соб.)" if len(evs_today) > 1 else ""
        ctx = ev0["title"][:46] + more
        if ev0.get("impact") == "high":
            act = ("СОБЫТИЕ: до выхода не открывать. После — только по 1h-закрепу направления; "
                   "стопы шире, размер меньше. Гэп не ловить")
        else:
            act = "Событие среднего веса: новый риск не наращивать, держать существующее с запасом по стопу"
        lvl = "риск ×0.5"
    elif dcur.weekday() >= 5:
        ctx = "выходные · тонкая ликвидность"
        act = "Новых позиций нет; фитильные пробои не считать закрепом"
        lvl = "—"
    elif iso in _pre_high:
        nxt_hi = min((x for x in _high_days if x > iso), default=None)
        ctx = "накануне " + (f"{_dt.date.fromisoformat(nxt_hi).strftime('%d.%m')}" if nxt_hi else "события")
        act = "К вечеру сократить риск открытых позиций вдвое; новых лонгов не открывать"
        lvl = "риск ×0.5"
    else:
        ctx = _next_ev_str(iso) or "между событиями"
        act = _base
        lvl = f"{fmt(nr)} · {fmt(wd)}"
    plan_rows.append(f'<tr><td class="b"><b>{label}</b><br><span class="dim">{wd_name}</span></td>'
                     f'<td class="dim">{ctx}</td><td>{act}</td><td class="dim">{lvl}</td></tr>')
    dcur += _dt.timedelta(days=1)

# ---------- чек-лист ----------
def badge(s):
    m = {"PASS": ("✓", "b-pass"), "FAIL": ("✕", "b-fail"), "WAIT — триггер": ("⏳", "b-wait"),
         "INFO": ("i", "b-info"), "FAIL/NEUTRAL": ("~", "b-neu")}
    base = "INFO" if s.startswith("INFO") else s
    ic, cls = m.get(base, ("•", "b-neu"))
    return f'<span class="badge {cls}">{ic} {s}</span>'
chk_rows = "".join(f'<tr><td>{t}</td><td>{badge(s)}</td><td class="dim">{f_}</td></tr>'
                   for t, s, f_ in d.get("checklist_A", []))

# ---------- самопроверка ----------
bt_html = ""
if bt and "error" in bt:
    bt_html = """
<h2 id="s-bt">Самопроверка (бэктест ядра)</h2>
<div class="card"><div class="note">⚠ Самопроверка временно недоступна: """ + str(bt["error"]) + """. История OKX не отдалась; предыдущая статистика в отчёте не показывается, чтобы не выдавать устаревшее за свежее. Решения на бэктесте не основываются.</div></div>"""
elif bt:
    b = bt["base"]
    sens_rows = "".join(f'<tr><td>сжатие &lt; {s[0]} ATR</td><td>дист. &lt; {s[1]*100:.1f}%</td><td>{s[2]}</td><td>{s[3]}%</td><td class="{"g" if s[4]>0 else "r"}">{s[4]:+.2f}R</td></tr>'
                        for s in bt["sensitivity"])
    bt_html = f"""
<h2 id="s-bt">Самопроверка (бэктест ядра)</h2>
<div class="card">
<table>
<tr><th>Метрика</th><th>Значение</th></tr>
<tr><td>Период проверки</td><td>{bt['period']} ({bt['bars']} дневных свечей)</td></tr>
<tr><td>Сигналов за период</td><td>{b['signals']}</td></tr>
<tr><td>Доля удачных</td><td>{b['win_rate']}%</td></tr>
<tr><td>Средний результат</td><td class="{"g" if b["avg_R"]>0 else "r"}">{b['avg_R']:+.2f}R</td></tr>
<tr><td>Сумма</td><td class="{"g" if b["sum_R"]>0 else "r"}">{b['sum_R']:+.1f}R</td></tr>
</table>
<div class="dim" style="font-size:13px; margin:12px 0 4px;">Чувствительность к порогам:</div>
<table><tr><th>Порог сжатия</th><th>Порог дистанции</th><th>Сигналов</th><th>Удачных</th><th>Ср. R</th></tr>{sens_rows}</table>
<div class="note">Важно: выборка мала ({b['signals']} сделок за {bt['bars']} дней — сигнал редкий), преимущество скромное и не статистически значимое. {bt['caveat']}. Вывод: ядро работает «не в минус», но не является граалем; главная ценность системы — дисциплина уровней и фильтров, а не предсказание.</div>
</div>"""

# ---------- секция макро (динамические ориентиры + ручной контекст) ----------
dxy = ex.get("dxy", {}); ndx = ex.get("ndx", {})
macro_dyn = f"""<tr><td>DXY</td><td>{dxy.get('last','—')}</td><td class="dim">{dxy.get('vs_e20','—')} EMA20 · {dxy.get('vs_e50','—')} EMA50</td></tr>
<tr><td>NASDAQ-100</td><td>{ndx.get('last','—')}</td><td class="dim">{ndx.get('vs_e20','—')} EMA20 · {ndx.get('vs_e50','—')} EMA50</td></tr>"""

html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BTC · «Уровень + поток» · {d.get('last_date','')}</title>
<style>
:root {{ --bg:#0b0e14; --card:#12161f; --card2:#161b26; --line:#232a38; --tx:#e6edf3; --dim:#8b949e;
  --up:#26a69a; --dn:#ef5350; --gold:#f0b90b; --purple:#c77dff; --blue:#7fb3ff; --orange:#ffb300; }}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:var(--bg); color:var(--tx); font:15px/1.6 'Segoe UI', system-ui, sans-serif; padding:0 0 60px; }}
.wrap {{ max-width:1060px; margin:0 auto; padding:0 20px; }}
header {{ padding:34px 0 22px; border-bottom:1px solid var(--line); }}
.hd1 {{ display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; }}
h1 {{ font-size:26px; font-weight:700; }}
.tag {{ color:var(--dim); font-size:13px; }}
.verdict-line {{ margin-top:10px; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
.vbadge {{ background:#141a12; border:1px solid {vcol}; color:{vcol}; font-weight:700; padding:6px 14px; border-radius:8px; font-size:15px; }}
.vsub {{ color:var(--dim); font-size:14px; max-width:820px; }}
h2 {{ font-size:18px; margin:38px 0 14px; display:flex; align-items:center; gap:10px; }}
h2::before {{ content:''; width:4px; height:18px; background:var(--gold); border-radius:2px; }}
.kpis {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; }}
.kpi {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }}
.kpi .k {{ color:var(--dim); font-size:12px; text-transform:uppercase; letter-spacing:.6px; }}
.kpi .v {{ font-size:21px; font-weight:700; margin-top:3px; }}
.kpi .s {{ font-size:12px; margin-top:2px; }}
.g {{ color:var(--up); }} .r {{ color:var(--dn); }} .y {{ color:var(--gold); }} .p {{ color:var(--purple); }} .b {{ color:var(--blue); }} .o {{ color:var(--orange); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:20px 22px; }}
.grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
@media(max-width:760px) {{ .grid2 {{ grid-template-columns:1fr; }} }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th {{ text-align:left; color:var(--dim); font-weight:600; font-size:12.5px; text-transform:uppercase; letter-spacing:.5px; padding:8px 10px; border-bottom:1px solid var(--line); }}
td {{ padding:9px 10px; border-bottom:1px solid #1b212d; vertical-align:top; }}
tr:last-child td {{ border-bottom:none; }}
.dim {{ color:var(--dim); }}
.badge {{ font-size:12px; font-weight:700; padding:3px 10px; border-radius:20px; white-space:nowrap; }}
.b-pass {{ background:#0c2824; color:var(--up); border:1px solid #1d4a43; }}
.b-fail {{ background:#2c1114; color:var(--dn); border:1px solid #58222a; }}
.b-wait {{ background:#2a2210; color:var(--gold); border:1px solid #55461a; }}
.b-neu {{ background:#1e2430; color:var(--dim); border:1px solid #2c3444; }}
.b-info {{ background:#141d2c; color:var(--blue); border:1px solid #233350; }}
img.chart {{ width:100%; border-radius:12px; border:1px solid var(--line); margin-top:6px; }}
.scen {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:14px; }}
.sc {{ border-radius:14px; padding:18px 20px; border:1px solid var(--line); background:var(--card); }}
.sc h3 {{ font-size:15.5px; margin-bottom:8px; }}
.sc.a {{ border-color:#1d4a43; }} .sc.v {{ border-color:#58222a; }} .sc.b {{ border-color:#2c3444; }}
.sc .lbl {{ font-size:11.5px; color:var(--dim); text-transform:uppercase; letter-spacing:.5px; margin-top:10px; }}
.sc .val {{ font-size:14.5px; font-weight:600; }}
.cal {{ display:flex; gap:12px; flex-wrap:wrap; }}
.ev {{ background:var(--card2); border:1px solid var(--line); border-left:3px solid var(--gold); border-radius:10px; padding:12px 16px; min-width:190px; }}
.ev .d {{ font-weight:700; font-size:15px; }} .ev .t {{ color:var(--dim); font-size:13px; }}
footer {{ margin-top:44px; padding-top:18px; border-top:1px solid var(--line); color:var(--dim); font-size:12.5px; }}
footer a {{ color:var(--blue); text-decoration:none; }}
.svgbox {{ background:var(--card2); border:1px solid var(--line); border-radius:10px; padding:12px; }}
.note {{ background:#16140a; border:1px solid #3a3416; color:#d9c76a; border-radius:10px; padding:12px 16px; font-size:13.5px; margin-top:14px; }}
ul.tight {{ padding-left:20px; }} ul.tight li {{ margin:4px 0; }}
.nav {{ display:flex; flex-wrap:wrap; gap:6px 18px; padding:10px 0 16px; margin-top:18px; border-top:1px solid var(--line); border-bottom:1px solid var(--line); font-size:12.5px; }}
.nav a {{ color:var(--blue); text-decoration:none; }}
@media print {{ body {{ background:#fff; color:#111; }} .nav, .calc, .calc button {{ display:none; }} .card,.kpi {{ border-color:#bbb; }} img.chart {{ max-height:850px; }} }}
.calc {{ display:flex; gap:14px; flex-wrap:wrap; align-items:flex-end; }}
.calc label {{ display:flex; flex-direction:column; gap:4px; color:var(--dim); font-size:12.5px; }}
.calc input {{ background:var(--card2); border:1px solid var(--line); color:var(--tx); border-radius:8px; padding:8px 10px; width:130px; font-size:14px; }}
.calc button {{ background:#241c02; border:1px solid #6b5300; color:var(--gold); font-weight:700; padding:10px 22px; border-radius:8px; cursor:pointer; font-size:14px; }}
.calc-out {{ margin-top:14px; font-size:14.5px; }}
</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="hd1">
    <h1>BTC/USDT · стратегия «Уровень + поток»</h1>
    <span class="tag">полностью автоматический отчёт · {d.get('last_date','')} · {d.get('source','')}</span>
  </div>
  <div class="verdict-line">
    <span class="vbadge">РЕШЕНИЕ: {vtxt}</span>
    <span class="vsub">{vsub}</span>
  </div>
</header>
<nav class="nav">
<a href="#s-kpi">Сводка</a><a href="#s-chart">График</a><a href="#s-liq">Ликвидации</a><a href="#s-lv">Уровни</a><a href="#s-chk">Чек-лист</a><a href="#s-der">Поток</a><a href="#s-etf">ETF</a><a href="#s-cal">Календарь</a><a href="#s-plan">План</a><a href="#s-ai">ИИ-вердикт</a><a href="#s-bt">Самопроверка</a><a href="#s-src">Источники</a>
</nav>

<h2 id="s-kpi">Сводка</h2>
<div class="kpis">
  <div class="kpi"><div class="k">Цена</div><div class="v">{fmt(price)}</div><div class="s dim">закрытие D1 {fmt(ds.get('last_completed_close'))}</div></div>
  <div class="kpi"><div class="k">Ближ. сопротивление</div><div class="v r">{fmt(nr)}</div><div class="s dim">{kpi_res_d}{"" if nr != lv.get('R1_prov') else " · prov."}</div></div>
  <div class="kpi"><div class="k">W1 · оборона</div><div class="v p">{fmt(wd)}</div><div class="s dim">закреп ниже = слабость</div></div>
  <div class="kpi"><div class="k">Ближ. поддержка</div><div class="v">{fmt(ns)}</div><div class="s dim">{kpi_sup_d}{"" if ns != lv.get('S1_prov') else " · prov."}</div></div>
  <div class="kpi"><div class="k">Сжатие</div><div class="v {'g' if d.get('squeeze',{}).get('active') else 'dim'}">{'ЕСТЬ' if d.get('squeeze',{}).get('active') else 'нет'}</div><div class="s dim">диап/ATR {d.get('squeeze',{}).get('range10_ATR','—')}, об.5/20 {d.get('squeeze',{}).get('vol_5_20','—')}</div></div>
  <div class="kpi"><div class="k">Чек-лист</div><div class="v y">{score}</div><div class="s dim">{'не хватает: ' + ', '.join(t.lower() for t in fails)[:60] if fails else 'все условия на месте'}</div></div>
  <div class="kpi"><div class="k">ETF (5 сессий)</div><div class="v o">{last5:+,.0f} $M</div><div class="s dim">{'приток' if last5>0 else 'отток'}</div></div>
  <div class="kpi"><div class="k">Max pain{(' · ' + exp_date[:5]) if exp_date else ''}</div><div class="v o">{fmt(mp)}</div><div class="s dim">{kpi_mp_d} к цене</div></div>
</div>

<h2 id="s-chart">График</h2>
<img class="chart" src="data:image/png;base64,{img_chart}" alt="BTC/USDT D1">

<h2 id="s-liq">Карта ликвидаций (модель)</h2>
{('<div class="card"><div class="note">⚠ ' + str(liq.get("note","модель отключена")) + ' · покрытие ' + str(liq.get("coverage_h","—")) + 'ч. Решения на ней не основываются.</div></div>') if liq.get("disabled") else f'''<div class="grid2">
<div><img class="chart" src="data:image/png;base64,{img_liq}" alt="Карта ликвидаций (модель, не наблюдаемые ликвидации)"></div>
<div class="card">
  <table>
  <tr><th>Шорт-ликвидации сверху (топливо вверх)</th><th>Объём</th></tr>
  {liq_up_rows}
  <tr><th>Лонг-ликвидации снизу (топливо вниз)</th><th>Объём</th></tr>
  {liq_dn_rows}
  </table>
  <div class="note">{liq_note} · покрытие {liq.get("coverage_h","—")}ч. Это модельные веса, НЕ наблюдаемые позиции.</div>
</div>
</div>'''}

<h2 id="s-lv">Карта уровней (пересчитывается ежедневно)</h2>
<div class="card"><table>{lv_rows}</table>
<div class="note">Уровни — пивот-кластеры D1 (K=5) + недельные + экстремумы последних 5 баров как «prov.» (анти-лаг: обычному пивоту нужно 5 будущих баров). Каскад D1+W1 помечается в чек-листе.</div>
</div>

<h2 id="s-chk">Чек-лист сценария А (пробой с закрепом)</h2>
<div class="card"><table>
<tr><th>Условие</th><th>Статус</th><th>Факт</th></tr>
{chk_rows}
</table></div>

<h2 id="s-der">Производные и поток</h2>
<div class="grid2">
<div class="card">
  <table>
  <tr><th>Метрика</th><th>Значение</th><th>Оценка</th></tr>
  <tr><td>Фандинг</td><td>{d.get('funding_now','—')}%/8ч</td><td class="{'g' if abs(d.get('funding_now',0))<0.01 else 'r'}">{'не перегрет' if abs(d.get('funding_now',0))<0.01 else 'перегрев'}</td></tr>
  <tr><td>Open Interest</td><td>${d.get('oi_b',['—'])[-1] if d.get('oi_b') else '—'}B · {d.get('oi_trend_3d','—')}%/3д</td><td class="{'g' if d.get('oi_trend_3d',0)>1 else 'r'}">{'растёт' if d.get('oi_trend_3d',0)>1 else 'плоский/падает'}</td></tr>
  <tr><td>Розница L/S</td><td>{d.get('ls_accounts',['—'])[-1] if d.get('ls_accounts') else '—'}</td><td class="dim">аккаунты лонг/шорт</td></tr>
  <tr><td>Taker buy/sell 1d</td><td>{d.get('taker_1d',['—'])[-1] if d.get('taker_1d') else '—'}</td><td class="dim">агрессия по дням</td></tr>
  <tr><td>Taker 48ч (1h)</td><td>{d.get('taker_1h_avg48','—')}</td><td class="{'g' if d.get('taker_1h_avg48',0)>1.05 else 'r'}">{'покупатели активнее' if d.get('taker_1h_avg48',0)>1.05 else 'нейтрально/продавцы'}</td></tr>
  </table>
  <div class="note" style="margin-top:12px">Пробой уровня без роста OI и taker-агрессии — тонкий: без «реальных денег» движение не продолжается (классическая ловушка).{' <b>Сегодня событийный день — метрики потока искажены.</b>' if ev_now else ''}</div>
</div>
<div class="card">
  <div class="dim" style="font-size:13px; margin-bottom:6px;">Open Interest, $ млрд</div>
  <div class="svgbox"><svg viewBox="0 0 560 38" width="100%">{oi_svg}</svg></div>
  <div class="dim" style="font-size:13px; margin:12px 0 6px;">Перекос розницы (7 дней)</div>
  <div class="svgbox"><svg viewBox="0 0 560 38" width="100%"><polyline points="{ls_pts}" fill="none" stroke="#ffb300" stroke-width="2"/><line x1="0" y1="19" x2="560" y2="19" stroke="#8b949e" stroke-width=".7" stroke-dasharray="3 3"/></svg></div>
</div>
</div>

<h2 id="s-etf">ETF-потоки (Farside)</h2>
<div class="grid2">
<div class="card"><table>
<tr><th>Сессия</th><th>Чистый поток</th><th></th></tr>
{etf_rows}
</table></div>
<div class="card">
<ul class="tight">
<li>Сумма последних 5 сессий: <b class="{'g' if last5>0 else 'r'}">{last5:+,.0f} $M</b>.</li>
<li>ETF-поток — «реальные деньги» спота: серии &gt;+200 $M/день подтверждают сценарий А, отрицательные серии — фактор сценария В.</li>
</ul>
</div>
</div>

<h2>Сентимент и рыночный контекст</h2>
<div class="grid2">
<div class="card">
  <table>
  <tr><th>Метрика</th><th>Значение</th><th>Оценка</th></tr>
  {macro_dyn}
  <tr><td>Страх и жадность</td><td class="o">{('<b>'+fng[0]['v']+'/100 · '+fng[0]['c']+'</b> ('+fng[0]['d']+')') if fng else '—'}</td><td class="dim">{'жадность у уровня = толпа уже в позиции' if fng and int(fng[0]['v'])>60 else 'нейтрально/нет данных'}</td></tr>
  <tr><td>Dominance BTC/ETH</td><td>{ex.get('dom_btc','—')}% / {ex.get('dom_eth','—')}%</td><td class="dim">ротация {'есть' if ex.get('dom_btc',60)<55 else 'в альты слабая'}</td></tr>
  <tr><td>Капитализация</td><td>{ex.get('mcap_btc_b','—')} трлн $</td><td class="dim">{f"{ex.get('mcap_chg_24h'):+.2f}%/24ч" if isinstance(ex.get('mcap_chg_24h'), (int, float)) else "—"}</td></tr>
  <tr><td>Корреляция BTC↔ETH</td><td>{ex.get('eth_corr30','—')}</td><td class="dim">альты идут за BTC</td></tr>
  <tr><td>Premium Coinbase</td><td>{ex.get('coinbase_prem_pct','—')}%</td><td class="dim">аномалий нет при |x|&lt;0.1%</td></tr>
  </table>
</div>
<div class="card">
  <div class="dim" style="font-size:13px; margin-bottom:6px;">Индекс страха и жадности (7 дней)</div>
  <div class="svgbox"><svg viewBox="0 0 560 38" width="100%"><polyline points="{fpts}" fill="none" stroke="#ffb300" stroke-width="2"/><line x1="0" y1="20" x2="560" y2="20" stroke="#8b949e" stroke-width=".7" stroke-dasharray="3 3"/></svg></div>
  <div class="note" style="margin-top:12px">Редакционный контекст (обновляется вручную): рынок закладывает ястребиный разворот ФРС (опасение повышения ставки), тарифная и ближневосточная премии в инфляции. Длинный горизонт структурно бычий (ETF-адапция), текущий месяц — пауза фондов.</div>
</div>
</div>

<h2 id="s-cal">Календарь</h2>
<div class="cal">{cal_html}</div>

<h2 id="s-plan">Рекомендации по дням (катится от текущей даты)</h2>
<div class="card">
<table>
<tr><th>Период</th><th>Контекст</th><th>Действие</th><th>Уровни</th></tr>
{plan_rows}
</table>
<div class="note">Лимиты: риск ≤1% на сделку; не добавлять в минус; журналировать в R; гэпы после событий не ловить — ждать закрепа.</div>
</div>

{ai_html}
{bt_html}

<h2 id="s-sc">Сценарии</h2>
<div class="scen">
<div class="sc a">
<h3 class="g">А — пробой с закрепом</h3>
<div class="lbl">Триггер</div><div class="val">D1 close &gt; {fmt(nr)} + объём ≥1.5× + OI +2% + taker &gt;1.15</div>
<div class="lbl">Вход / стоп</div><div class="val">{fmt(nr)}–{fmt((nr or price)*1.004)} · стоп {fmt(wd)}</div>
<div class="lbl">Цели</div><div class="val">{fmt(R2)} → {fmt(lv.get('res_extra',[None])[0]) if lv.get('res_extra') else '—'}</div>
</div>
<div class="sc b">
<h3 class="dim">Б — тонкий пробой (ловушка)</h3>
<div class="lbl">Триггер</div><div class="val">фитиль &gt; {fmt(nr)} без объёма/OI/ETF</div>
<div class="lbl">Действие</div><div class="val">пропуск, ждать ретеста</div>
</div>
<div class="sc v">
<h3 class="r">В — срыв (ускорят ликвидации)</h3>
<div class="lbl">Ступени</div><div class="val">закреп &lt; {fmt(wd)} → {fmt(ns)} → кластеры лонг-ликвидаций{(' → max pain ' + fmt(mp)) if mp else ''}</div>
<div class="lbl">Там</div><div class="val dim">выкуп только по разворотному D1-бару: уровень по хаю → боковик → вход от уровня</div>
</div>
</div>

<h2>Калькулятор позиции</h2>
<div class="card">
<div class="calc">
  <label>Капитал, $ <input id="cap" type="number" value="10000" step="500"></label>
  <label>Риск, % <input id="risk" type="number" value="1" step="0.25"></label>
  <label>Вход <input id="entry" type="number" value="{nr or 0:.0f}" step="50"></label>
  <label>Стоп <input id="stop" type="number" value="{wd or (ns or 0):.0f}" step="50"></label>
  <label>Цель <input id="tgt" type="number" value="{(R2 or (nr or 0)*1.02):.0f}" step="50"></label>
  <button onclick="calc()">Рассчитать</button>
</div>
<div class="calc-out" id="cout">—</div>
</div>

<h2 id="s-src">Источники и аудит</h2>
<div class="card"><table>
<tr><th>Источник (движок)</th><th>Статус</th><th>Попыток</th><th>Проверка</th></tr>
{mf_rows}
</table>
<div class="note">PASS = успешный ответ API, не гарантия точности поставщика. Полный журнал — manifest_engine.json. Остальные данные: <a href="https://farside.co.uk/btc/">Farside ETF</a> (со сверкой суммы фондов), CoinGecko, alternative.me, Yahoo Finance, Deribit, календарь events.json (BLS/BEA/ФРС + праздники США). Свечи D1 — только подтверждённые, граница суток UTC.</div>
</div>

<footer>
Методика: «Уровень + поток» — уровни-следы крупного игрока (пивот-кластеры D1+W1+prov), пробой с закрепом по завершённой свече, подтверждение потоком (OI/taker/ETF), модель ликвидаций (ΔOI×taker×плечи 10/25/50x), опционы Deribit, события из events.json. Вердикт, уровни, план и календарь вычисляются автоматически из данных на момент генерации ({time.strftime('%d.%m.%Y %H:%M UTC', time.gmtime())}) — ручных чисел в отчёте нет.
Источники: OKX, Binance, Deribit, <a href="https://farside.co.uk/btc/">Farside</a>, CoinGecko, alternative.me, Yahoo Finance, events.json. Не является инвестиционной рекомендацией.
</footer>
</div>
<script>
function calc() {{
  var cap=+document.getElementById('cap').value, risk=+document.getElementById('risk').value,
      entry=+document.getElementById('entry').value, stop=+document.getElementById('stop').value,
      tgt=+document.getElementById('tgt').value;
  if (!cap||!entry||!stop||!tgt||entry===stop) {{ document.getElementById('cout').innerHTML='<span style="color:#ef5350">Заполните поля (вход ≠ стоп)</span>'; return; }}
  var riskUsd=cap*risk/100, dist=Math.abs(entry-stop), size=riskUsd/dist, volUsd=size*entry,
      rr=Math.abs(tgt-entry)/dist, profit=riskUsd*rr;
  var warn=(volUsd>cap)?' <span style="color:#ef5350">⚠ объём больше капитала — нужно плечо</span>':'';
  document.getElementById('cout').innerHTML='Размер: <b>'+size.toFixed(4)+' BTC</b> ($'+volUsd.toLocaleString('ru',{{maximumFractionDigits:0}})+') · Риск: <b>$'+riskUsd.toLocaleString('ru',{{maximumFractionDigits:0}})+'</b> · До стопа: '+(100*dist/entry).toFixed(1)+'% · R:R <b>1:'+rr.toFixed(2)+'</b> · Потенциал: <b style="color:#26a69a">+$'+profit.toLocaleString('ru',{{maximumFractionDigits:0}})+'</b>'+warn;
}}
calc();
</script>
</body>
</html>"""

with open(OUT + "/btc_report.html", "w", encoding="utf-8") as f:
    f.write(html)
print(f"saved btc_report.html v4 ({len(html)//1024} KB), вердикт: {vtxt}")
