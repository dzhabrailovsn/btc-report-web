# -*- coding: utf-8 -*-
"""Слияние найденных событий в events.json (безопасное пополнение календаря).
Использование: python events_update.py <файл с JSON-списком новых событий>
Формат элемента: {"date": "YYYY-MM-DD", "title": "...", "impact": "high|med|low", "time": "опционально"}
Правила: дедуп по date+началу title, сортировка по дате, бэкап events.json.bak."""
import os
import io, sys, json, os, re, shutil

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
OUT = os.environ.get("BTC_REPORT_DIR") or os.path.dirname(os.path.abspath(__file__))

if len(sys.argv) < 2:
    print("нет входного файла"); sys.exit(1)

new_raw = json.load(open(sys.argv[1], encoding="utf-8"))
if isinstance(new_raw, dict):
    new_raw = new_raw.get("events", [])

def norm(e):
    d = str(e.get("date", "")).strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
        return None
    t = str(e.get("title", "")).strip()[:120]
    imp = e.get("impact", "med")
    imp = imp if imp in ("high", "med", "low", "holiday") else "med"
    out = {"date": d, "title": t, "impact": imp}
    if e.get("time"):
        out["time"] = str(e["time"])[:40]
    out["source"] = e.get("source", "auto")
    return out if t else None

new = [x for x in (norm(e) for e in new_raw) if x]

path = OUT + "/events.json"
old = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
shutil.copy(path, path + ".bak") if os.path.exists(path) else None

def key(e):
    return (e["date"], e["title"][:20].lower())

merged = {key(e): e for e in old}
added = updated = 0
for e in new:
    k = key(e)
    if k in merged:
        old_e = merged[k]
        if e.get("time") and not old_e.get("time"):
            old_e["time"] = e["time"]; updated += 1
        if e.get("impact") != "med" and old_e.get("impact") == "med":
            old_e["impact"] = e["impact"]; updated += 1
    else:
        merged[k] = e; added += 1

result = sorted(merged.values(), key=lambda e: e["date"])
with open(path, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=1)
print(f"добавлено: {added}, обновлено: {updated}, всего в календаре: {len(result)}")
for e in result:
    print("  ", e["date"], f'[{e["impact"]}]', e["title"][:60], f'({e.get("source","manual")})')
