# -*- coding: utf-8 -*-
"""Оркестратор ежедневного обновления отчёта BTC.
Цепочка: btc_full.py -> btc_liqmap.py -> btc_fetch_extra.py -> btc_report_html.py
Сбойный этап не останавливает цепочку (кроме фатальных), итог пишется в report_run.log."""
import os
import io, sys, subprocess, time, os

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
OUT = os.environ.get("BTC_REPORT_DIR") or os.path.dirname(os.path.abspath(__file__))
STEPS = ["btc_fetch_extra.py", "btc_full.py", "btc_liqmap.py", "btc_backtest.py", "btc_report_html.py"]

log = [f"=== запуск {time.strftime('%d.%m.%Y %H:%M:%S')} ==="]
overall = "OK"
for step in STEPS:
    try:
        r = subprocess.run([sys.executable, os.path.join(OUT, step)],
                           capture_output=True, timeout=420, cwd=OUT)
        ok = r.returncode == 0
        log.append(f"[{'OK' if ok else 'ERR'}] {step} ({r.stdout.decode(errors='replace').strip().splitlines()[-1] if r.stdout else ''})")
        if not ok:
            overall = "PARTIAL"
            log.append("    stderr: " + r.stderr.decode(errors='replace').strip()[-300:])
    except subprocess.TimeoutExpired:
        overall = "PARTIAL"
        log.append(f"[TIMEOUT] {step}")
    except Exception as e:
        overall = "PARTIAL"
        log.append(f"[ERR] {step}: {e}")

html = os.path.join(OUT, "btc_report.html")
if os.path.exists(html):
    age = time.time() - os.path.getmtime(html)
    log.append(f"btc_report.html обновлён {time.strftime('%d.%m %H:%M', time.localtime(os.path.getmtime(html)))} ({age:.0f}с назад, {os.path.getsize(html)//1024} KB)")
    if age > 600:
        overall = "STALE"
else:
    overall = "FAIL"

log.append(f"=== итог: {overall} ===")
with open(os.path.join(OUT, "report_run.log"), "a", encoding="utf-8") as f:
    f.write("\n".join(log) + "\n")
print("\n".join(log))
sys.exit(0 if overall == "OK" else 1)
