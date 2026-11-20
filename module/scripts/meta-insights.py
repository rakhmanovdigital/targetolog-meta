#!/usr/bin/env python3
"""Цифры рекламного кабинета Meta — только чтение (ads_read).

Ключ НЕ передаётся аргументом и не печатается: скрипт берёт его из .env в корне офиса
по имени переменной (имя записано в конфиге охранника, поле token_var, напр. META_TOKEN).
Сначала смотрит переменную окружения с этим именем, потом файл <корень офиса>/.env, строка вида
  META_TOKEN=EAAB...   (кавычки вокруг значения можно, пробелы вокруг «=» можно).

Запуск:
  python3 scripts/meta-insights.py <ПЕРЕМЕННАЯ_КЛЮЧА> <act_id> [период] [уровень]
    период: today | yesterday | last_7d | maximum ... (date_preset Meta), по умолчанию today
    уровень: campaign | adset | ad, по умолчанию adset
  Необязательные фильтры (для общего кабинета, где есть чужие кампании):
    --prefix=MY_          только кампании, чьё имя начинается с приставки
    --since=2026-01-10    ничего раньше этой даты (период не может начаться раньше)
    --day=2026-01-20      ровно один день (часовой пояс кабинета), вместо периода
    --breakdown=country   разбивка (country | publisher_platform | age …)
    --actions             показать все типы действий как есть (отладка событий пикселя)
Пример:
  python3 scripts/meta-insights.py META_TOKEN <номер кабинета без act_> today adset
  python3 scripts/meta-insights.py META_TOKEN <номер кабинета> maximum ad --prefix=MY_ --since=2026-01-10
  python3 scripts/meta-insights.py --names   — диагностика .env: только имена переменных, без значений
Вывод — JSON со строками по группам/объявлениям.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

OFFICE_ROOT = Path(__file__).resolve().parent.parent
API = "https://graph.facebook.com/v23.0"
FIELDS = ",".join([
    "campaign_name", "adset_name", "ad_name", "spend", "impressions", "reach",
    "clicks", "unique_clicks", "inline_link_clicks", "cpc", "ctr", "actions", "cost_per_action_type",
])


def token(var):
    v = os.environ.get(var, "").strip()
    if v:
        return v
    env = OFFICE_ROOT / ".env"
    if env.exists():
        # ищем в любом месте: строку могли вклеить в конец предыдущей без переноса
        m = re.search(re.escape(var) + r"\s*=\s*[\"']?([A-Za-z0-9_\-]+)", env.read_text(encoding="utf-8", errors="ignore"))
        if m:
            return m.group(1)
    sys.exit(f"нет ключа {var} в .env (корень офиса)")


def get(path, params):
    url = f"{API}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        err = json.loads(e.read() or b"{}").get("error", {})
        sys.exit(f"Meta API ошибка {e.code}: {err.get('message', '')} (code {err.get('code')})")


def names():
    """Диагностика: только ИМЕНА переменных из .env (значения не печатаются)."""
    text = (OFFICE_ROOT / ".env").read_text(encoding="utf-8", errors="ignore")
    for i, line in enumerate(text.splitlines(), 1):
        name = line.split("=", 1)[0].strip() if "=" in line else "(строка без «=»)"
        print(f"{i}: {name[:40]}  [длина строки {len(line)}]")


def main():
    if sys.argv[1:2] == ["--names"]:
        return names()
    opts = {a[2:].split("=", 1)[0]: a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--") and "=" in a}
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) < 2:
        sys.exit(__doc__)
    var, act = args[0], args[1].removeprefix("act_")
    preset = args[2] if len(args) > 2 else "today"
    level = args[3] if len(args) > 3 else "adset"
    prefix, since = opts.get("prefix"), opts.get("since")
    t = token(var)
    acc = get(f"act_{act}", {"fields": "name,account_status,currency,timezone_name", "access_token": t})
    rows, params = [], {"fields": FIELDS, "level": level, "date_preset": preset, "limit": 200, "access_token": t}
    if opts.get("breakdown"):  # напр. --breakdown=publisher_platform (Instagram / Facebook / Audience Network)
        params["breakdowns"] = opts["breakdown"]
    if since:
        # общий кабинет: период режем снизу датой старта работы (дни в часовом поясе кабинета)
        today = get(f"act_{act}/insights", {"fields": "spend", "date_preset": "today", "access_token": t}).get("data") or [{}]
        until = today[0].get("date_stop") or __import__("datetime").date.today().isoformat()
        if preset in ("maximum", "lifetime") or preset.startswith("last_") or preset.startswith("this_"):
            params.pop("date_preset")
            params["time_range"] = json.dumps({"since": since, "until": until})
    if opts.get("day"):  # --day=2026-01-20: ровно один календарный день в часовом поясе кабинета
        params.pop("date_preset", None)
        params["time_range"] = json.dumps({"since": opts["day"], "until": opts["day"]})
    page = get(f"act_{act}/insights", params)
    while True:
        rows += page.get("data", [])
        nxt = page.get("paging", {}).get("next")
        if not nxt:
            break
        with urllib.request.urlopen(nxt, timeout=60) as r:
            page = json.load(r)
    if prefix:
        # русские и английские буквы-двойники (Т/T, А/A…) считаем одинаковыми, регистр не важен
        twins = str.maketrans("АВЕКМНОРСТУХаеорсух", "ABEKMHOPCTYXaeopcyx")
        norm = lambda x: str(x).translate(twins).upper()
        rows = [r for r in rows if norm(r.get("campaign_name", "")).startswith(norm(prefix))]
    if since:
        rows = [r for r in rows if r.get("date_start", since) >= since]
    for r in rows:
        acts = {a["action_type"]: a["value"] for a in r.pop("actions", []) or []}
        if "--actions" in sys.argv:  # все типы действий как есть — для отладки событий пикселя
            r["actions_raw"] = acts
        r["landing_page_views"] = acts.get("landing_page_view", "0")
        r["leads"] = acts.get("offsite_conversion.fb_pixel_lead", acts.get("lead", "0"))
        r["contacts"] = acts.get("offsite_conversion.fb_pixel_contact", acts.get("contact", "0"))
        cpa = {a["action_type"]: a["value"] for a in r.pop("cost_per_action_type", []) or []}
        r["cost_per_lead"] = cpa.get("offsite_conversion.fb_pixel_lead", cpa.get("lead"))
    print(json.dumps({"account": acc, "period": params.get("time_range", preset), "level": level,
                      "filter": {"prefix": prefix, "since": since}, "rows": rows}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
