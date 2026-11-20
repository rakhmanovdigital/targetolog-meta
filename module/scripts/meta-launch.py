#!/usr/bin/env python3
"""Охранник рекламы Meta — единственный путь записи в рекламный кабинет (Facebook / Instagram).

ИИ-помощник сам в Meta не ходит: он пишет план (JSON) и запускает этот скрипт. Скрипт держит замки:
  - новая кампания создаётся ТОЛЬКО на паузе (PAUSED); группы и объявления внутри — включёнными (ACTIVE).
    Пока кампания на паузе, ничего не крутится и деньги не тратятся. Включает кампанию сам человек вручную —
    в Ads Manager или в приложении Meta Ads. Включать кампании и удалять что-либо охранник НЕ умеет.
    Единственное исключение: addsets добавляет группы в уже работающую кампанию — такие группы PAUSED, кампанию не трогает;
  - запуск на завтра (конфиг "start_next_day": true): если у группы нет start_time, охранник сам ставит
    старт завтра в 00:00 по времени рекламного кабинета и печатает это. Зачем: все объявления успевают пройти модерацию,
    а показ начинается с начала суток — алгоритм оптимизации стартует ровно;
  - дневной потолок: сумма дневных бюджетов активных групп + новых ≤ daily_ceiling_usd из конфига;
  - потолки объёма в день (кампании / группы / объявления / записи) — из конфига;
  - за один запуск ≤ campaigns_per_launch кампаний, в группе ≤ ads_per_adset креативов (потолок-предохранитель; сколько ставить — решает выбранная стратегия);
  - имена только с приставкой из конфига ("prefix") — чужие кампании кабинета не трогаем;
  - работа только в рабочие часы (work_hours) по часовому поясу рекламного кабинета:
    "tz" в конфиге = пояс кабинета (команда status показывает его как «пояс»). Нет tz — команды с сетью
    берут пояс из кабинета сами; check (без сети) без tz останавливается и просит вписать. tz конфига ≠ пояс
    кабинета → стоп до записи;
  - паузы между записями (pace), перерыв между кампаниями;
  - НИКАКИХ автоповторов: ошибка → стоп и отчёт. Лимит Meta (код 4/17/613 с подкодом/800xx) → одно
    ожидание и одна попытка; 613 без подкода, 190, 10/200/294, 1404163, отклонение — стоп сразу;
  - после каждой записи — чтение обратно (кампания PAUSED, группа/объявление ACTIVE, бюджет в центах); не совпало → стоп;
  - стоп-слова в текстах (обещания дохода, «гарантия», «вылечим», «до/после», «100%») — check не пропустит;
  - каждое действие — строка в журнале (JSONL, путь в конфиге "journal").
Ключ не печатается: берётся из .env в корне офиса по имени переменной из конфига ("token_var").
Любая запись (live, addsets, ads, newform) — только если в плане стоит "approved_by_owner" (кто и когда сказал «да»).

КОМАНДЫ (запуск из корня офиса):
  Подключение (конфига ещё нет; в Meta ничего не пишут):
  python3 scripts/meta-launch.py ids  --token-var META_TOKEN
       — что видит ключ: кто он, права (granted/declined), рекламные кабинеты (act без «act_», имя, статус, валюта,
         пояс tz, способ оплаты, лимит), пиксели и Instagram кабинетов, страницы и их Instagram, бизнес-портфели
  python3 scripts/meta-launch.py init --token-var META_TOKEN --act <id> --page <id> [--ig <id>] [--pixel <id>]
                                      --prefix MY_ --ceiling <usd в день> --out projects/<проект>/targetolog/config.json
       — собирает конфиг из шаблона, tz берёт из кабинета, журнал кладёт рядом с конфигом; файл уже есть — не перезаписывает

  Только чтение (ничего не меняют):
  python3 scripts/meta-launch.py status  <конфиг.json>
       — кабинет, статус, оплата, лимит расходов, активные бюджеты, нагрузка Meta, записей сегодня
  python3 scripts/meta-launch.py check   <конфиг.json> <план.json>
       — проверка плана БЕЗ Meta и без сети: замки, поля, правила; подставляет start_time «завтра 00:00»
  python3 scripts/meta-launch.py names   <конфиг.json> <план.json>
       — каждый код языка/гео/интереса плана → название по Meta (показать владельцу); не совпало → ошибка
  python3 scripts/meta-launch.py geo     <конфиг.json> <название> [city|region|country] [код страны]
       — найти key города/региона для плана, напр.: geo cfg.json Berlin city DE · geo cfg.json Bavaria region DE
  python3 scripts/meta-launch.py devices <конфиг.json> [запрос]
       — названия устройств Meta для user_device (по умолчанию iPhone)
  python3 scripts/meta-launch.py forms   <конфиг.json>
       — мгновенные формы страницы (id для lead_form_id)
  python3 scripts/meta-launch.py form    <конфиг.json> <id формы>
       — устройство одной формы: вопросы, тип, экраны, политика, число заявок
  python3 scripts/meta-launch.py perms   <конфиг.json>
       — какие права выданы ключу (granted / declined); для форм нужны pages_manage_ads + leads_retrieval
  python3 scripts/meta-launch.py wa      <конфиг.json>
       — поля WhatsApp страницы; ключ может их не получить (null ≠ «нет»). Точно проверяет только
         addsets --validate-only группы WHATSAPP: чужой номер Meta отвергает кодом 100/1487246
  python3 scripts/meta-launch.py show    <конфиг.json> <ID группы>
       — группа и её объявления как в кабинете (только группы этого кабинета)

  Запись (только с "approved_by_owner" в плане):
  python3 scripts/meta-launch.py live    <конфиг.json> <план.json> [--validate-only]
       — создаёт кампании НА ПАУЗЕ, группы и объявления внутри. Включает кампанию человек вручную.
         --validate-only: Meta проверяет кампанию и первые креативы особых видов, ничего не создаёт («да» не нужно).
  python3 scripts/meta-launch.py addsets <конфиг.json> <план.json> --campaign <ID> [--check] [--validate-only]
       — новые группы в СУЩЕСТВУЮЩУЮ кампанию любого статуса (работающую на паузу не ставим).
         Кампанию и старые группы НЕ трогает. Новые группы — PAUSED (ни цента не тратится), объявления в них — ACTIVE;
         у каждой группы нужен start_time (при start_next_day подставится сам); включает группы человек.
         В плане ровно одна кампания, её existing_id = --campaign. До записи — снимок кампании и групп,
         после — сверка: новые группы PAUSED, остальное без изменений; не сошлось → стоп.
         --check: только чтение и проверки. --validate-only: Meta проверяет группу, креатив Direct/WhatsApp и
         показывает размер аудитории; ничего не создаётся (видео и обложка Direct грузятся по-настоящему).
         Для плана только из групп WhatsApp --validate-only не требует approved_by_owner.
  python3 scripts/meta-launch.py ads     <конфиг.json> <план.json> --adset <ID> [--check]
       — объявления в СУЩЕСТВУЮЩУЮ нашу группу (кампания на паузе), без дубля группы; группу и кампанию не меняет.
         В плане одна кампания с existing_id и одна группа с existing_adset_id = --adset. Только картинка или видео.
  python3 scripts/meta-launch.py newform <конфиг.json> <план-формы.json> [--check]
       — создать мгновенную форму на странице. --check: проверка без создания.
         Форму в Meta не исправить — только новая. Формат — team/agents/targetolog/templates/form.example.json
  python3 scripts/meta-launch.py pause   <конфиг.json> adset|ad <ID> [<ID> ...] --why "<решение владельца, дата>" [--dry]
       — ТОЛЬКО пауза групп или объявлений. Включать, удалять, менять бюджет/таргетинг и трогать кампании — нельзя.
         Только наши объекты (этот кабинет, кампания с приставкой). Все ID сверяются до первой записи,
         после — чтение обратно. --dry: показать, что будет выключено, ничего не писать.
  python3 scripts/meta-launch.py pauseset <конфиг.json> <ID группы> --reason "<решение владельца, дата>"
       — одна группа на паузу (то же, что pause adset, с чтением до и после; бюджет и кампания не меняются)

ПЛАН (подробный пример — team/agents/targetolog/templates/plan.example.json):
  верх плана: "name", "approved_by_owner" (кто и когда сказал «да», его словами),
    "niche" ("real_estate" включает замки HOUSING), "instagram_user_id" (если нет в конфиге),
    "creative_features_opt_out": [...] — выключить авто-улучшения креатива Meta по списку функций.
  кампания: "name" (с приставкой), "objective" (OUTCOME_LEADS по умолчанию; OUTCOME_ENGAGEMENT — Direct;
    OUTCOME_TRAFFIC — профиль), "special_ad_category" (напр. "HOUSING" или null),
    "existing_id" — добавить группы в готовую нашу кампанию на паузе (имя = плану);
    "existing_housing": true — готовая кампания обязана быть HOUSING (сверяется с Meta);
    "create_only": true — создать только кампанию на паузе, без групп.
  группа:
    "name" (с приставкой), "daily_budget_usd", "age_min"/"age_max", "genders" ([1] муж, [2] жен),
    гео: "countries": ["DE"] и/или "regions": [{"key","name","country"}], "cities": [{"key","name","country","radius_km"}]
      (страны из never_whole_country конфига целиком нельзя — только регионы/города; key ищется командой geo);
    язык: "locales": [код] + "locale_names": ["Название"] — у каждого кода название рядом, live сверяет с Meta;
      "audience_lang": "en" — англоязычная группа: обязательный язык конфига её не держит (язык не задаём или только английский);
    "start_time": "2026-01-15T00:00:00+03:00" — с поясом; нет поля и start_next_day = true → завтра 00:00;
    "lead_form_id": "<id>" — лид-форма: цель LEAD_GENERATION, ON_AD, ссылка в объявлении не нужна;
    "event": "LEAD" — событие пикселя для сайта (по умолчанию LEAD); "optimization_goal", "destination_type" — вручную, если нужно;
    "destination": "INSTAGRAM_DIRECT" — сообщения в директ: CONVERSATIONS, кнопка INSTAGRAM_MESSAGE, размещения только
      instagram; "direct_wide_placements": true — Instagram + Facebook без Audience Network;
    "destination": "INSTAGRAM_PROFILE" — посещения профиля: только из существующей публикации, кампания OUTCOME_TRAFFIC;
    "destination": "WHATSAPP" + "whatsapp_number": "+<код страны><номер>" — сообщения в WhatsApp
      (кампания OUTCOME_LEADS или OUTCOME_ENGAGEMENT; номер всегда явно — к странице бывает привязано несколько);
    "interests": [{"id","name"}], "user_device": ["iPhone 15", ...], "user_os": ["iOS"], "device_platforms": ["mobile"],
    "location_types": ["home"] — только живущие в гео, "advantage_audience": 0|1;
    "placements": {"publisher_platforms": ["facebook","instagram"], "facebook_positions": [...], "instagram_positions": [...]}
      — ручные размещения, только FB/IG; "no_audience_network": true — FB/IG/Messenger, позиции авто;
    "housing_override": "<решение владельца, дата>" — недвижимость на ЕС/UK/CH/US/CA без HOUSING (иначе стоп);
    "dsa_beneficiary" + "dsa_payor" — для ЕС: кто выгодоприобретатель и кто платит (видно в Библиотеке рекламы);
      только парой, после создания читаются обратно; без полей Meta берёт значения кабинета по умолчанию;
    Таиланд: "regional_regulated_categories": ["THAILAND_UNIVERSAL"] + "regional_regulation_identities":
      {"universal_beneficiary": "<id>", "universal_payer": "<id>"} — id подтверждённого рекламодателя; проще — один раз
      в конфиге "verified_advertiser" (охранник подставит сам). Таиланд с языком — age_min от 20 (требование Meta).
  объявление:
    "name" (латиница/цифры/_), "primary_text" (≤125), "headline" (≤40), "description", "link" (https), "cta";
    картинка: "image": "<путь от корня офиса>"; видео: "video": "<путь.mp4>" + "thumb": "<кадр.jpg>";
    два формата: + "video_feed": "<4x5.mp4>" + "thumb_feed" — 9:16 в сторис/рилс, 4:5 в ленту (только сайт);
      первый такой креатив читается обратно, печатаются ссылки предпросмотра;
    карусель: "carousel": [{"image", "headline" ≤40, "description" ≤30}, ...] — 2–10 карточек вместо "image"
      (лид-форма, сайт или WhatsApp; live и addsets), порядок фиксирован, после создания читается обратно;
    "welcome_message": {"autofill": "текст в поле ввода", "greeting": "приветствие"} — заготовленное сообщение Direct/WhatsApp;
    WhatsApp: "code_word": "СЛОВО" (+ "code_word_latin" для кириллицы) — своё слово на каждый креатив,
      оно есть в autofill и в имени объявления (по нему видно, с какого объявления пришёл человек);
    "source_instagram_media_id": "<id>" — существующая публикация вместо файла (только Direct и профиль),
      для профиля ещё "profile_link": "https://instagram.com/<ник>".
  Файлы (видео/картинки) грузятся один раз на весь запуск.
Формат конфига и плана — team/agents/targetolog/templates/ (там же у каждого поля пояснение).
"""
import base64
import datetime as dt
import importlib.util
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

OFFICE = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("mi", OFFICE / "scripts" / "meta-insights.py")
_mi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mi)
API = _mi.API

HOUSING_COUNTRIES = {  # США, Канада, ЕС/ЕЭЗ+UK+CH — для недвижимости категория HOUSING обязательна (правила Meta)
    "US", "CA", "GB", "CH", "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE", "IS", "LI", "NO"}
ZERO_DECIMAL = {"JPY", "KRW", "VND", "CLP", "ISK", "HUF", "TWD", "COP", "IDR", "PYG"}  # проверять по кабинету
STOP_CODES = {190, 10, 200, 294, 100, 1404163}
WAIT_CODES = {4, 17, 80000, 80003, 80004, 80014}
# код 1 «Please reduce the amount of data» — плавающий сбой Meta на креативах asset_feed_spec (тот же запрос то ошибка, то ок) → одно ожидание 60 с и одна попытка
TRANSIENT_CODES = {1}
PLACEMENT_KEYS = {"publisher_platforms", "facebook_positions", "instagram_positions"}  # ручные размещения группы
# стоп-слова (часть слова, без регистра): обещания дохода и результата, «до/после» — частые причины отклонения Meta
FORBIDDEN_WORDS = ["гарантир", "доход", "заработ", "миллион", "пассивн", "окупаем", "%годовых", "% годовых",
                   "до/после", "до и после", "вылечим", "вылечит", "100%", "100 %"]


class Stop(Exception):
    pass


def tz_of(cfg):
    """Часовой пояс рекламного кабинета: tz из конфига или (если его нет) прочитанный из кабинета ensure_tz."""
    name = cfg.get("tz")
    if not name:
        raise Stop("в конфиге нет \"tz\" (часовой пояс рекламного кабинета). Запусти `meta-launch.py status <конфиг>`, "
                   "возьми строку «пояс» и впиши в конфиг, напр. \"tz\": \"Europe/Moscow\"")
    try:
        return ZoneInfo(name)
    except Exception:
        raise Stop(f"tz «{name}» — не название часового пояса (нужно вида Europe/Moscow, America/New_York)")


def now_local(cfg):
    return dt.datetime.now(tz_of(cfg))


def ensure_tz(cfg, tok, acc_tz=None):
    """Пояс берём у кабинета: нет tz в конфиге → ставим timezone_name кабинета; tz конфига другой → стоп
    (иначе «завтра 00:00» и рабочие часы посчитаются не по времени кабинета)."""
    if acc_tz is None:
        acc_tz = call(cfg, "GET", f"act_{cfg['act']}", {"fields": "timezone_name"}, tok)[0].get("timezone_name")
    if not cfg.get("tz"):
        if not acc_tz:
            raise Stop("Meta не отдала пояс кабинета, а в конфиге нет tz — впиши tz вручную")
        cfg["tz"] = acc_tz
        print(f"… пояс взял из кабинета: {acc_tz} (лучше вписать в конфиг \"tz\": \"{acc_tz}\")")
    elif acc_tz and acc_tz != cfg["tz"]:
        raise Stop(f"tz конфига «{cfg['tz']}» ≠ пояс кабинета «{acc_tz}» — исправь tz в конфиге на «{acc_tz}»")
    tz_of(cfg)


def approved(plan):
    """«Да» владельца в плане: approved_by_owner."""
    return plan.get("approved_by_owner")


def apply_start_next_day(cfg, plan):
    """Запуск на завтра (конфиг "start_next_day", по умолчанию true): группе без start_time ставим завтра 00:00
    по времени кабинета. Все объявления успевают пройти модерацию, показ стартует с начала суток — оптимизация идёт ровно.
    Группы, которые уже есть в кабинете (existing_adset_id), не трогаем."""
    if not cfg.get("start_next_day", True):
        return plan
    tz = tz_of(cfg)
    tomorrow = (dt.datetime.now(tz) + dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    st = tomorrow.isoformat(timespec="seconds")
    for c in plan.get("campaigns", []):
        for a in c.get("adsets", []):
            if not a.get("start_time") and not a.get("existing_adset_id"):
                a["start_time"] = st
                print(f"… группа «{a.get('name')}»: start_time не задан → завтра {st} ({cfg['tz']}, start_next_day)")
    return plan


def journal_path(cfg):
    p = OFFICE / cfg["journal"]
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def log(cfg, **row):
    try:
        ts = now_local(cfg)
    except Stop:  # пояс ещё не известен — пишем по UTC, журнал не теряем
        ts = dt.datetime.now(dt.timezone.utc)
    row = {"ts": ts.isoformat(timespec="seconds"), **row}
    with journal_path(cfg).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def writes_today(cfg):
    p, today, n = journal_path(cfg), now_local(cfg).date().isoformat(), {"write": 0, "campaign": 0, "adset": 0, "ad": 0}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if r.get("ts", "").startswith(today) and r.get("result") == "ok" and r.get("kind") == "write":
                n["write"] += 1
                n[r.get("object", "")] = n.get(r.get("object", ""), 0) + 1
    return n


def call(cfg, method, path, params, tok, attempt=1):
    params = {**params, "access_token": tok}
    data = urllib.parse.urlencode({k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()}).encode()
    url = f"{API}/{path}"
    req = urllib.request.Request(url + ("?" + data.decode() if method == "GET" else ""), data=None if method == "GET" else data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            usage = r.headers.get("X-Business-Use-Case-Usage") or r.headers.get("X-Ad-Account-Usage")
            return json.load(r), usage
    except urllib.error.HTTPError as e:
        err = json.loads(e.read() or b"{}").get("error", {})
        code, sub = err.get("code"), err.get("error_subcode")
        msg = f"Meta {code}/{sub}: {err.get('error_user_msg') or err.get('message')}"
        if code in WAIT_CODES or code in TRANSIENT_CODES or (code == 613 and sub):
            if attempt == 1:
                log(cfg, kind="wait", path=path, error=msg)
                time.sleep(60 if code in TRANSIENT_CODES else 300)
                return call(cfg, method, path, {k: v for k, v in params.items() if k != "access_token"}, tok, attempt=2)
            raise Stop(f"лимит Meta повторился после ожидания — стоп. {msg}")
        raise Stop(msg)


def busy_check(cfg, usage):
    if not usage:
        return
    try:
        data = json.loads(usage)
        vals = []
        for v in (data.values() if isinstance(data, dict) else []):
            for item in (v if isinstance(v, list) else [v]):
                if isinstance(item, dict):
                    vals += [x for k, x in item.items() if k in ("call_count", "total_cputime", "total_time", "acc_id_util_pct") and isinstance(x, (int, float))]
        if vals and max(vals) > cfg.get("busy_pct", 50):
            log(cfg, kind="busy", usage=max(vals))
            print(f"… нагрузка Meta {max(vals)}% > {cfg.get('busy_pct', 50)}% — жду 10 мин")
            time.sleep(600)
    except (ValueError, TypeError):
        pass


def geo_countries(a):
    """Все страны группы: целые страны + страны её регионов и городов."""
    return set(a.get("countries", [])) | {g["country"] for g in a.get("regions", []) + a.get("cities", []) if g.get("country")}


def geo_locations(a):
    """geo_locations для Meta: страны, регионы (key), города (key + радиус в км)."""
    geo = {}
    if a.get("countries"):
        geo["countries"] = a["countries"]
    if a.get("regions"):
        geo["regions"] = [{"key": str(r["key"])} for r in a["regions"]]
    if a.get("cities"):
        geo["cities"] = [{"key": str(c["key"]), "radius": c.get("radius_km", 25), "distance_unit": "kilometer"} for c in a["cities"]]
    if a.get("location_types"):
        geo["location_types"] = a["location_types"]  # флаг группы: ["home"] — только живущие там; без флага — по умолчанию Meta
    return geo


def money_offset(currency):
    return 1 if currency in ZERO_DECIMAL else 100


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def apply_verified_advertiser(cfg, plan):
    """Подтверждённый рекламодатель из конфига (verified_advertiser): группе со страной из его categories
    (TH → THAILAND_UNIVERSAL) сам ставит категорию + бенефициара и плательщика = id, если в плане их нет."""
    va = cfg.get("verified_advertiser") or {}
    if not va.get("id") or not va.get("categories"):
        return plan
    for c in plan.get("campaigns", []):
        for a in c.get("adsets", []):
            cats = sorted({va["categories"][k] for k in geo_countries(a) if k in va["categories"]})
            if cats and not a.get("regional_regulation_identities"):
                a["regional_regulated_categories"] = cats
                a["regional_regulation_identities"] = {"universal_beneficiary": str(va["id"]), "universal_payer": str(va["id"])}
    return plan


def is_direct(a):
    """Группа плана на сообщения в директ Instagram. Без флага — обычная группа."""
    return a.get("destination") == "INSTAGRAM_DIRECT"


def is_profile(a):
    """Группа плана на посещения профиля Instagram. Без флага — обычная группа."""
    return a.get("destination") == "INSTAGRAM_PROFILE"


def is_whatsapp(a):
    """Группа плана на сообщения в WhatsApp. Без флага — обычная группа."""
    return a.get("destination") == "WHATSAPP"


def ig_user(cfg, plan):
    return plan.get("instagram_user_id") or cfg.get("instagram_user_id")


def welcome_message(ad):
    """Заготовленное сообщение для директа и WhatsApp: autofill_message (текст, который уже стоит в поле ввода) + приветствие."""
    wm = ad.get("welcome_message") or {}
    if not wm.get("autofill"):
        return None
    return json.dumps({"type": "VISUAL_EDITOR", "version": 2, "landing_screen_type": "welcome_message", "media_type": "text",
                       "text_format": {"customer_action_type": "autofill_message",
                                       "message": {"autofill_message": {"content": wm["autofill"]}, "text": wm.get("greeting", "")}},
                       "user_edit": True, "surface": "visual_editor_new"}, ensure_ascii=False)


def check_whatsapp_ad(a, ad, words):
    """Замки объявления WhatsApp: своё кодовое слово на каждый креатив — метка, по которой менеджер видит, с какого объявления пришёл человек."""
    errs = []
    word = str(ad.get("code_word", "")).strip()
    autofill = (ad.get("welcome_message") or {}).get("autofill", "")
    if not word:
        errs.append(f"«{ad['name']}»: WhatsApp — нужно кодовое слово code_word (своё на каждый креатив)")
    else:
        if not word.replace("-", "").isalnum():
            errs.append(f"«{ad['name']}»: кодовое слово «{word}» — одно слово, без пробелов и знаков")
        if word.lower() not in autofill.lower():
            errs.append(f"«{ad['name']}»: кодового слова «{word}» нет в заготовленном сообщении welcome_message.autofill")
        in_name = word if word.isascii() else str(ad.get("code_word_latin", "")).strip()  # имя объявления только латиницей: для кириллицы — code_word_latin
        if not in_name:
            errs.append(f"«{ad['name']}»: слово «{word}» кириллицей — нужен code_word_latin, он ставится в имя объявления")
        elif in_name.lower() not in ad["name"].lower():
            errs.append(f"«{ad['name']}»: кодового слова «{in_name}» нет в имени объявления (слово и есть метка)")
        key = word.lower()
        ident = ad.get("image", ad.get("video")) or "|".join(c.get("image", "") for c in ad.get("carousel") or [])
        if key in words and words[key] != ident:
            errs.append(f"«{ad['name']}»: кодовое слово «{word}» уже стоит на другом креативе ({words[key]}) — у каждого своё")
        words.setdefault(key, ident)
    if len(autofill) > 300:
        errs.append(f"«{ad['name']}»: заготовленное сообщение длиннее 300 символов")
    if ad.get("video_feed"):
        errs.append(f"«{ad['name']}»: WhatsApp — пока один формат (video или image), без video_feed")
    if ad.get("source_instagram_media_id"):
        errs.append(f"«{ad['name']}»: WhatsApp — только файл, существующая публикация пока не поддержана")
    if a.get("lead_form_id"):
        errs.append(f"группа «{a['name']}»: WhatsApp и лид-форма вместе нельзя")
    return errs


CAROUSEL_CARD_KEYS = {"image", "headline", "description"}


def check_carousel(a, ad):
    """Карусель: "carousel": [{"image", "headline", "description"}] — 2–10 карточек-картинок,
    для лид-формы, сайта и WhatsApp (Direct, профиль, видео, два формата — нет). Без поля — обычное объявление."""
    errs, cards = [], ad.get("carousel")
    if not isinstance(cards, list) or not 2 <= len(cards) <= 10:
        return [f"«{ad['name']}»: карусель — список из 2–10 карточек"]
    if is_direct(a) or is_profile(a):
        errs.append(f"«{ad['name']}»: карусель — только лид-форма, сайт или WhatsApp")
    for k in ("image", "video", "thumb", "video_feed", "thumb_feed", "source_instagram_media_id"):
        if ad.get(k):
            errs.append(f"«{ad['name']}»: карусель — без {k} (картинки только в карточках)")
    for i, card in enumerate(cards, 1):
        if not isinstance(card, dict) or set(card) - CAROUSEL_CARD_KEYS:
            errs.append(f"«{ad['name']}» карточка {i}: только ключи {sorted(CAROUSEL_CARD_KEYS)}")
            continue
        if not card.get("image"):
            errs.append(f"«{ad['name']}» карточка {i}: нет image")
        elif not (OFFICE / card["image"]).exists():
            errs.append(f"нет файла карточки {card['image']}")
        if not card.get("headline"):
            errs.append(f"«{ad['name']}» карточка {i}: нет headline")
        elif len(card["headline"]) > 40:
            errs.append(f"«{ad['name']}» карточка {i}: заголовок длиннее 40 символов")
        if len(card.get("description", "")) > 30:
            errs.append(f"«{ad['name']}» карточка {i}: описание длиннее 30 символов (обрежется)")
    return errs


# ---------- проверка плана без Meta ----------
def check_plan(cfg, plan, active_daily=0.0):
    errs, warn = [], []
    pref = cfg["prefix"]
    camps = plan.get("campaigns", [])
    n_adsets = sum(len(c.get("adsets", [])) for c in camps)
    n_ads = sum(len(a.get("ads", [])) for c in camps for a in c.get("adsets", []))
    lim = cfg["limits"]
    done = writes_today(cfg)
    if len(camps) > lim.get("campaigns_per_launch", 3):
        errs.append(f"кампаний за один запуск {len(camps)} > потолка {lim.get('campaigns_per_launch', 3)} (остальное — следующим запуском)")
    if len(camps) + done["campaign"] > lim["campaigns_per_day"]:
        errs.append(f"кампаний за день {len(camps) + done['campaign']} > потолка {lim['campaigns_per_day']} (поднять — только владелец, в конфиге)")
    if n_adsets + done["adset"] > lim["adsets_per_day"]:
        errs.append(f"групп за день {n_adsets + done['adset']} > потолка {lim['adsets_per_day']}")
    if n_ads + done["ad"] > lim["ads_per_day"]:
        errs.append(f"объявлений за день {n_ads + done['ad']} > потолка {lim['ads_per_day']}")
    # загрузки файлов: каждое видео/картинка/обложка — один раз на весь запуск (кэш общий для кампаний)
    est_writes = len(camps) + n_adsets + 2 * n_ads + len({ad.get(k) for c in camps for a in c.get("adsets", []) for ad in a.get("ads", [])
                                                          for k in ("image", "video", "thumb", "video_feed", "thumb_feed") if ad.get(k)}
                                                         | {card.get("image") for c in camps for a in c.get("adsets", []) for ad in a.get("ads", [])
                                                            for card in ad.get("carousel") or []})
    if est_writes + done["write"] > lim["writes_per_day"]:
        errs.append(f"записей за день ~{est_writes + done['write']} > потолка {lim['writes_per_day']}")
    new_daily = sum(float(a["daily_budget_usd"]) for c in camps for a in c.get("adsets", []))
    if active_daily + new_daily > cfg["daily_ceiling_usd"]:
        errs.append(f"дневные бюджеты: активные ${active_daily:.0f} + новые ${new_daily:.0f} > потолка клиента ${cfg['daily_ceiling_usd']}")
    wa_words = {}  # кодовое слово → креатив: одно слово на креатив во всём плане
    for c in camps:
        if not c["name"].startswith(pref):
            errs.append(f"кампания «{c['name']}» без приставки {pref}")
        # группы в готовую кампанию: existing_id — кампания этого кабинета на паузе; имя сверяется в live
        if c.get("existing_id") is not None:
            if not str(c["existing_id"]).isdigit():
                errs.append(f"кампания «{c['name']}»: existing_id — только цифры ID кампании")
            if c.get("special_ad_category"):
                errs.append(f"кампания «{c['name']}»: у готовой кампании категорию не меняем — убери special_ad_category из плана")
        elif c.get("existing_housing"):
            errs.append(f"кампания «{c['name']}»: existing_housing — только вместе с existing_id")
        # готовая кампания HOUSING: флаг плана, addsets и live сверяют категорию с Meta; не совпало → стоп
        housing = c.get("special_ad_category") == "HOUSING" or bool(c.get("existing_housing"))
        for a in c.get("adsets", []):
            if not a["name"].startswith(pref):
                errs.append(f"группа «{a['name']}» без приставки {pref}")
            countries = geo_countries(a)
            if not countries:
                errs.append(f"группа «{a['name']}»: нет гео (countries / regions / cities)")
            banned = set(a.get("countries", [])) & set(cfg.get("never_whole_country", []))
            if banned:
                errs.append(f"группа «{a['name']}»: страну {sorted(banned)} целиком не берём (правило конфига never_whole_country) — только регионы/города")
            for g in a.get("regions", []) + a.get("cities", []):
                if not g.get("key") or not g.get("country"):
                    errs.append(f"группа «{a['name']}»: у региона/города «{g.get('name')}» нет key или country — найди через `meta-launch.py geo`")
            for city in a.get("cities", []):
                if housing and city.get("radius_km", 0) < 15:
                    errs.append(f"группа «{a['name']}»: при HOUSING радиус города «{city.get('name')}» ≥ 15 км")
            if plan.get("niche") == "real_estate" and countries & HOUSING_COUNTRIES and not housing:
                # исключение — только явным флагом группы с решением владельца (housing_override)
                if str(a.get("housing_override", "")).strip():
                    warn.append(f"группа «{a['name']}»: гео {sorted(countries & HOUSING_COUNTRIES)} БЕЗ HOUSING — housing_override: {a['housing_override']}")
                else:
                    errs.append(f"кампания «{c['name']}»: гео {sorted(countries & HOUSING_COUNTRIES)} → нужна категория HOUSING (отдельная кампания)")
            if housing and (a.get("age_min", 18) != 18 or a.get("age_max", 65) != 65 or a.get("genders")):
                errs.append(f"группа «{a['name']}»: при HOUSING — возраст 18–65+, все полы")
            if a.get("start_time"):
                try:
                    st = dt.datetime.fromisoformat(a["start_time"])
                    if st.tzinfo is None:
                        errs.append(f"группа «{a['name']}»: start_time без часового пояса (напр. 2026-10-13T00:20:00+06:00)")
                    elif st < dt.datetime.now(dt.timezone.utc):
                        errs.append(f"группа «{a['name']}»: start_time в прошлом")
                except ValueError:
                    errs.append(f"группа «{a['name']}»: start_time не ISO-дата")
            # язык аудитории — замок конфига require_locales (без него реклама может уйти не на ту языковую аудиторию)
            # исключение: англоязычный креатив → "audience_lang": "en" — язык не задаём или только английские коды;
            # замок языка для остальных групп действует как обычно
            if a.get("audience_lang") == "en":
                if a.get("locales") and set(a["locales"]) - set(cfg.get("english_locales", [6, 24])):
                    errs.append(f"группа «{a['name']}»: audience_lang en — язык не задаём или только английские коды {cfg.get('english_locales', [6, 24])}")
                warn.append(f"группа «{a['name']}»: англоязычная аудитория (audience_lang en) — креатив и форма должны быть на английском")
            elif cfg.get("require_locales") and a.get("locales") != cfg["require_locales"]:
                errs.append(f"группа «{a['name']}»: язык {a.get('locales')} ≠ обязательного {cfg['require_locales']} {cfg.get('require_locale_names', '')} — так требует конфиг (require_locales)")
            # коды Meta — только с названием рядом (по памяти легко перепутать: «24» — это English UK, а не русский)
            if a.get("locales") and len(a.get("locale_names", [])) != len(a["locales"]):
                errs.append(f"группа «{a['name']}»: у каждого кода языка нужно название рядом — \"locale_names\": [\"Русский\"] (код найди поиском, не по памяти)")
            for g in a.get("regions", []) + a.get("cities", []):
                if not g.get("name"):
                    errs.append(f"группа «{a['name']}»: у гео-кода {g.get('key')} нет названия (name)")
            # интересы и устройства: интересы — id + name (name сверяем с Meta), устройства — названия Meta
            for it in a.get("interests", []):
                if not str(it.get("id", "")).isdigit() or not it.get("name"):
                    errs.append(f"группа «{a['name']}»: интерес {it} — нужны id (цифры) и name")
            if a.get("user_device") is not None:
                if not isinstance(a["user_device"], list) or not a["user_device"] or not all(isinstance(d, str) and d for d in a["user_device"]):
                    errs.append(f"группа «{a['name']}»: user_device — непустой список названий устройств Meta")
            if a.get("user_os") is not None and (not isinstance(a["user_os"], list) or not a["user_os"]):
                errs.append(f"группа «{a['name']}»: user_os — непустой список (напр. [\"iOS\"])")
            # Таиланд (требование Meta, код 3858634): категория THAILAND_UNIVERSAL + бенефициар и плательщик — id подтверждённого рекламодателя
            if "TH" in countries and a.get("locales") and a.get("age_min", 18) < 20:
                # Meta 100/1870249: в Таиланде с любым таргетингом кроме места и возраста — только от 20 лет; в HOUSING так нельзя (18–65) → Таиланд отдельной кампанией
                errs.append(f"группа «{a['name']}»: Таиланд с языком — age_min от 20 (Meta 100/1870249); в HOUSING-кампании Таиланд не ставим")
            if "TH" in countries:
                ids = a.get("regional_regulation_identities") or {}
                if a.get("regional_regulated_categories") != ["THAILAND_UNIVERSAL"] or not all(
                        str(ids.get(k, "")).isdigit() for k in ("universal_beneficiary", "universal_payer")):
                    errs.append(f"группа «{a['name']}»: гео Таиланд — нужны \"regional_regulated_categories\": [\"THAILAND_UNIVERSAL\"] и "
                                f"\"regional_regulation_identities\": {{\"universal_beneficiary\": id, \"universal_payer\": id}} (id подтверждённого рекламодателя, цифры)")
            # ЕС/DSA: бенефициар и плательщик — только парой, непустой текст; после создания читаются обратно
            dsa = [str(a.get(k, "")).strip() for k in ("dsa_beneficiary", "dsa_payor")]
            if any(dsa) and not all(dsa):
                errs.append(f"группа «{a['name']}»: dsa_beneficiary и dsa_payor — только вместе")
            if any(len(x) > 200 for x in dsa):
                errs.append(f"группа «{a['name']}»: dsa_beneficiary/dsa_payor длиннее 200 символов")
            pl = a.get("placements")
            if pl:
                if set(pl) - PLACEMENT_KEYS:
                    errs.append(f"группа «{a['name']}»: размещения — только ключи {sorted(PLACEMENT_KEYS)}")
                if "explore" in (pl.get("instagram_positions") or []):
                    errs.append(f"группа «{a['name']}»: instagram_positions explore («Интересное») Meta больше не принимает (100/2490589) — убери")
                if not pl.get("publisher_platforms") or set(pl["publisher_platforms"]) - {"facebook", "instagram"}:
                    errs.append(f"группа «{a['name']}»: ручные размещения — только facebook/instagram (Audience Network никогда, Messenger выкл)")
            if float(a["daily_budget_usd"]) < cfg.get("min_adset_usd", 3):
                warn.append(f"группа «{a['name']}»: бюджет ${a['daily_budget_usd']}/день — очень мало")
            # правило: в группе 1–2 креатива; больше — клоны группы (те же настройки), общий бюджет делим, не растёт
            if len(a.get("ads", [])) > lim.get("ads_per_adset", 2):
                errs.append(f"группа «{a['name']}»: {len(a['ads'])} креативов > {lim.get('ads_per_adset', 2)} (потолок конфига) — разбей на дубли групп или подними потолок решением владельца")
            for ad in a.get("ads", []):
                for key in ("image", "video", "thumb", "video_feed", "thumb_feed"):
                    if ad.get(key) and not (OFFICE / ad[key]).exists():
                        errs.append(f"нет файла {key} {ad[key]}")
                post = ad.get("source_instagram_media_id")
                if post and not str(post).isdigit():
                    errs.append(f"«{ad['name']}»: source_instagram_media_id — только цифры")
                if post and not (is_direct(a) or is_profile(a)):
                    errs.append(f"«{ad['name']}»: существующая публикация — только в группах Direct и профиля")
                if post and (ad.get("image") or ad.get("video")):
                    errs.append(f"«{ad['name']}»: либо публикация, либо файл, не вместе")
                if is_profile(a) and not post:
                    errs.append(f"«{ad['name']}»: группа профиля собирается только из существующей публикации")
                if is_profile(a) and not str(ad.get("profile_link", "")).startswith("https://"):
                    errs.append(f"«{ad['name']}»: группа профиля — нужен profile_link https://")
                if ad.get("carousel") is not None:
                    errs += check_carousel(a, ad)
                elif not ad.get("image") and not ad.get("video") and not post:
                    errs.append(f"«{ad['name']}»: нужен image или video")
                if ad.get("video") and not ad.get("thumb"):
                    errs.append(f"«{ad['name']}»: у видео нужна обложка thumb (кадр jpg)")
                # два формата в одном объявлении: video = 9:16 сторис/рилс, video_feed = 4:5 лента и остальное
                if ad.get("video_feed"):
                    if not ad.get("video"):
                        errs.append(f"«{ad['name']}»: video_feed (4:5) только вместе с video (9:16)")
                    if not ad.get("thumb_feed"):
                        errs.append(f"«{ad['name']}»: у video_feed нужна своя обложка thumb_feed (кадр 4:5)")
                    if a.get("lead_form_id"):
                        errs.append(f"«{ad['name']}»: два формата по плейсментам — пока только для сайта, не для лид-формы")
                for key in ("video", "video_feed"):
                    if ad.get(key) and (OFFICE / ad[key]).exists() and (OFFICE / ad[key]).stat().st_size > 900 * 2**20:
                        errs.append(f"«{ad['name']}»: видео {key} > 900 МБ — сожми ffmpeg")
                if not ad["name"].replace("_", "").isalnum() or not ad["name"].isascii():
                    errs.append(f"имя объявления «{ad['name']}»: только латиница/цифры/_ (это ключ метки)")
                if len(ad.get("primary_text", "")) > 125:
                    warn.append(f"«{ad['name']}»: основной текст > 125 символов (обрежется)")
                if len(ad.get("headline", "")) > 40:
                    warn.append(f"«{ad['name']}»: заголовок > 40 символов")
                low = (ad.get("primary_text", "") + " " + ad.get("headline", "") + " " + ad.get("description", "") + " " +
                       " ".join(str(card.get(k, "")) for card in ad.get("carousel") or [] for k in ("headline", "description"))).lower()
                bad = [w for w in FORBIDDEN_WORDS if w in low]
                if bad:
                    errs.append(f"«{ad['name']}»: стоп-слова {bad} (обещания дохода/результата — правила Meta). Перепиши текст")
                if is_direct(a):
                    if ad.get("video_feed"):
                        errs.append(f"«{ad['name']}»: Direct — пока один формат (video или image), без video_feed")
                    continue
                if is_profile(a):
                    continue
                if is_whatsapp(a):
                    errs += check_whatsapp_ad(a, ad, wa_words)
                    continue
                if not a.get("lead_form_id") and not ad.get("link", "").startswith("https://"):
                    errs.append(f"«{ad['name']}»: ссылка должна быть https://")
            # сообщения в директ Instagram: только флагом группы destination=INSTAGRAM_DIRECT
            if is_direct(a):
                if not ig_user(cfg, plan):
                    errs.append(f"группа «{a['name']}»: Direct — нужен instagram_user_id (конфиг или план)")
                if a.get("lead_form_id"):
                    errs.append(f"группа «{a['name']}»: Direct и лид-форма вместе нельзя")
                plats = (a.get("placements") or {}).get("publisher_platforms")
                # флаг "direct_wide_placements": true — Instagram + Facebook без Audience Network; без флага только Instagram
                wide_ok = a.get("direct_wide_placements") and plats and "instagram" in plats and not set(plats) - {"facebook", "instagram"}
                if plats != ["instagram"] and not wide_ok:
                    errs.append(f"группа «{a['name']}»: Direct — размещения только Instagram (placements.publisher_platforms = [\"instagram\"])")
            if is_profile(a):
                if not ig_user(cfg, plan):
                    errs.append(f"группа «{a['name']}»: профиль — нужен instagram_user_id (конфиг или план)")
                if (a.get("placements") or {}).get("publisher_platforms") != ["instagram"]:
                    errs.append(f"группа «{a['name']}»: профиль — размещения только Instagram")
                if c.get("objective") != "OUTCOME_TRAFFIC":
                    errs.append(f"группа «{a['name']}»: профиль — в кампании objective OUTCOME_TRAFFIC")
            if is_whatsapp(a):
                if c.get("objective") not in ("OUTCOME_LEADS", "OUTCOME_ENGAGEMENT"):
                    errs.append(f"группа «{a['name']}»: WhatsApp — в кампании objective OUTCOME_LEADS или OUTCOME_ENGAGEMENT (сейчас {c.get('objective')})")
                # к странице может быть привязано несколько номеров: без явного номера заявки уйдут на тот, что Meta считает основным
                wa_num = str(a.get("whatsapp_number", ""))
                if not (wa_num.startswith("+") and wa_num[1:].isdigit()):
                    errs.append(f"группа «{a['name']}»: whatsapp_number обязателен, международный формат +<код страны><номер>, без пробелов")
            if not (a.get("lead_form_id") or is_direct(a) or is_profile(a) or is_whatsapp(a)) and not cfg.get("pixel_id"):
                errs.append(f"группа «{a['name']}»: реклама на сайт — нужен pixel_id в конфиге (или lead_form_id / destination в группе)")
            if a.get("location_types") and set(a["location_types"]) - {"home", "recent", "travel_in"}:
                errs.append(f"группа «{a['name']}»: location_types — только home/recent/travel_in")
            if a.get("device_platforms") and set(a["device_platforms"]) - {"mobile", "desktop"}:
                errs.append(f"группа «{a['name']}»: device_platforms — только mobile/desktop")
    return errs, warn, {"campaigns": len(camps), "adsets": n_adsets, "ads": n_ads, "new_daily_usd": new_daily, "est_writes": est_writes}


def active_daily_usd(cfg, tok, offset):
    # своё = кампания с приставкой из конфига (имена групп бывают без приставки — если их ставили вручную)
    res, _ = call(cfg, "GET", f"act_{cfg['act']}/adsets", {"fields": "name,daily_budget,effective_status,campaign{name}", "limit": 500,
                  "filtering": [{"field": "effective_status", "operator": "IN", "value": ["ACTIVE"]}]}, tok)
    total = sum(int(a.get("daily_budget") or 0) / offset for a in res.get("data", []) if a["campaign"]["name"].startswith(cfg["prefix"]))
    # бюджет на кампании (CBO): у групп его нет — считаем по кампаниям
    res, _ = call(cfg, "GET", f"act_{cfg['act']}/campaigns", {"fields": "name,daily_budget,effective_status", "limit": 200,
                  "filtering": [{"field": "effective_status", "operator": "IN", "value": ["ACTIVE"]}]}, tok)
    return total + sum(int(c.get("daily_budget") or 0) / offset for c in res.get("data", []) if c["name"].startswith(cfg["prefix"]))


# ---------- команды ----------
def cmd_status(cfg):
    tok = _mi.token(cfg["token_var"])
    acc, usage = call(cfg, "GET", f"act_{cfg['act']}", {"fields": "name,account_status,disable_reason,currency,timezone_name,spend_cap,amount_spent,balance,funding_source_details"}, tok)
    tz_note = "совпадает с tz конфига" if cfg.get("tz") == acc.get("timezone_name") else (
        f"⚠ в конфиге tz «{cfg['tz']}» — исправь на «{acc.get('timezone_name')}»" if cfg.get("tz") else
        f"⚠ в конфиге нет tz — впиши \"tz\": \"{acc.get('timezone_name')}\"")
    if not cfg.get("tz"):
        cfg["tz"] = acc.get("timezone_name")
    off = money_offset(acc["currency"])
    out = {
        "кабинет": acc["name"], "статус": {1: "активен"}.get(acc["account_status"], f"⚠ {acc['account_status']}"),
        "причина_блока": acc.get("disable_reason"), "валюта": acc["currency"], "пояс": acc["timezone_name"], "пояс_и_конфиг": tz_note,
        "лимит_расходов_аккаунта": "НЕ СТОИТ" if acc.get("spend_cap") in (None, "0") else f"${int(acc['spend_cap']) / off:.0f}",
        "потрачено_с_установки_лимита": f"${int(acc['amount_spent']) / off:.2f}",
        "осталось_до_лимита": None if acc.get("spend_cap") in (None, "0") else (
            lambda left: f"${left:.0f}" + (" ⚠ меньше $100 — напомнить владельцу сбросить лимит" if left < 100 else ""))(
            (int(acc["spend_cap"]) - int(acc["amount_spent"])) / off),
        "к_оплате_сейчас": f"${int(acc.get('balance') or 0) / off:.2f}",
        "способ_оплаты": (acc.get("funding_source_details") or {}).get("display_string", "нет данных"),
        "активные_дневные_бюджеты_с_приставкой": f"${active_daily_usd(cfg, tok, off):.0f} из потолка ${cfg['daily_ceiling_usd']}",
        "нагрузка_Meta": usage, "записей_сегодня": writes_today(cfg),
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_geo(cfg, query, kind="city", country=None):
    """Только чтение: найти key региона/города для плана (поиск гео Meta)."""
    tok = _mi.token(cfg["token_var"])
    params = {"type": "adgeolocation", "q": query, "location_types": [kind], "limit": 50}
    res, _ = call(cfg, "GET", "search", params, tok)
    rows = [{"key": r.get("key"), "name": r.get("name"), "type": r.get("type"), "region": r.get("region"),
             "country": r.get("country_code")} for r in res.get("data", [])
            if r.get("type") == kind and (not country or r.get("country_code") == country)]
    print(json.dumps(rows, ensure_ascii=False, indent=1))


def resolve_names(cfg, tok, plan):
    """Только чтение: каждый код языка/региона/города плана → название по поиску Meta.
    Код не найден под своим названием → ошибка (живой запуск не идёт). Возвращает (ошибки, строки для владельца)."""
    errs, rows, cache = [], [], {}

    def found(kind, name, key, country=None):
        if (kind, name) not in cache:
            p = ({"type": "adlocale", "q": name} if kind == "locale" else
                 {"type": "adinterest", "q": name, "limit": 50} if kind == "interest" else
                 {"type": "adgeolocation", "q": name, "location_types": [kind], "limit": 50})
            cache[(kind, name)] = call(cfg, "GET", "search", p, tok)[0].get("data", [])
        return [r for r in cache[(kind, name)] if str(r.get("key", r.get("id"))) == str(key) and (not country or r.get("country_code") == country)]

    for c in plan.get("campaigns", []):
        for a in c.get("adsets", []):
            for key, name in zip(a.get("locales", []), a.get("locale_names", [])):
                hit = found("locale", name, key)
                rows.append(f"{a['name']}: язык {key} = {hit[0]['name'] if hit else '?'}")
                if not hit:
                    errs.append(f"группа «{a['name']}»: язык {key} в Meta не «{name}» — найди код поиском")
            for kind, items in (("region", a.get("regions", [])), ("city", a.get("cities", []))):
                for g in items:
                    hit = found(kind, g["name"], g["key"], g.get("country"))
                    rows.append(f"{a['name']}: {kind} {g['key']} = {hit[0]['name'] + ', ' + hit[0].get('country_code', '') if hit else '?'}")
                    if not hit:
                        errs.append(f"группа «{a['name']}»: {kind} {g['key']} в Meta не «{g['name']}» ({g.get('country')}) — найди через geo")
            for it in a.get("interests", []):
                hit = [r for r in found("interest", it["name"], it["id"])]
                rows.append(f"{a['name']}: интерес {it['id']} = {hit[0]['name'] if hit else '?'}")
                if not hit:
                    errs.append(f"группа «{a['name']}»: интерес {it['id']} в Meta не «{it['name']}» — найди поиском adinterest")
    return errs, rows


def cmd_names(cfg, plan):
    errs, rows = resolve_names(cfg, _mi.token(cfg["token_var"]), plan)
    print(json.dumps({"коды_по_Meta": rows, "ошибки": errs}, ensure_ascii=False, indent=1))
    sys.exit(1 if errs else 0)


def cmd_check(cfg, plan):
    tz_of(cfg)  # check без сети: пояс кабинета берём только из конфига
    plan = apply_start_next_day(cfg, plan)
    errs, warn, stats = check_plan(cfg, plan)
    stats["start_time_групп"] = {a["name"]: a.get("start_time") for c in plan.get("campaigns", []) for a in c.get("adsets", [])}
    print(json.dumps({"план": stats, "ошибки": errs, "предупреждения": warn}, ensure_ascii=False, indent=1))
    sys.exit(1 if errs else 0)


def pause(cfg, a=None, b=None):
    lo, hi = cfg["pace"]["write_pause_sec"] if a is None else (a, b)
    time.sleep(random.uniform(lo, hi))


def write(cfg, tok, path, params, obj, name):
    res, usage = call(cfg, "POST", path, params, tok)
    log(cfg, kind="write", object=obj, name=name, path=path, result="ok", id=res.get("id") or res.get("images"))
    busy_check(cfg, usage)
    return res


def upload_video(cfg, tok, act, rel):
    """Видео в кабинет одним запросом (multipart) → ждём обработку Meta (только чтение, до 10 мин)."""
    raw, boundary = (OFFICE / rel).read_bytes(), "----metalaunch" + str(random.randint(10**8, 10**9))
    body = b"".join([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"access_token\"\r\n\r\n{tok}\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"name\"\r\n\r\n{Path(rel).name}\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"source\"; filename=\"{Path(rel).name}\"\r\n"
        "Content-Type: application/octet-stream\r\n\r\n".encode(), raw, f"\r\n--{boundary}--\r\n".encode()])
    req = urllib.request.Request(f"{API.replace('graph.facebook', 'graph-video.facebook')}/{act}/advideos", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            vid = json.load(r)["id"]
    except urllib.error.HTTPError as e:
        err = json.loads(e.read() or b"{}").get("error", {})
        raise Stop(f"видео не загрузилось: Meta {err.get('code')}/{err.get('error_subcode')}: {err.get('error_user_msg') or err.get('message')}")
    log(cfg, kind="write", object="video", name=rel, path=f"{act}/advideos", result="ok", id=vid)
    for _ in range(40):
        st, _ = call(cfg, "GET", vid, {"fields": "status"}, tok)
        s = (st.get("status") or {}).get("video_status")
        if s == "ready":
            return vid
        if s == "error":
            raise Stop(f"видео {vid}: Meta не смогла обработать — стоп")
        time.sleep(15)
    raise Stop(f"видео {vid} не обработалось за 10 мин — стоп, проверить в кабинете")


def page_token(cfg, tok):
    r, _ = call(cfg, "GET", cfg["page_id"], {"fields": "access_token"}, tok)
    return r.get("access_token") or tok


def cmd_forms(cfg):
    """Только чтение: мгновенные формы страницы (id, имя, статус) — id ставится в план как lead_form_id."""
    tok = _mi.token(cfg["token_var"])
    res, _ = call(cfg, "GET", f"{cfg['page_id']}/leadgen_forms", {"fields": "id,name,status,locale,created_time", "limit": 50}, page_token(cfg, tok))
    print(json.dumps(res.get("data", []), ensure_ascii=False, indent=1))


def cmd_form(cfg, form_id):
    """Только чтение: устройство одной мгновенной формы (вопросы, тип, экраны, политика, число заявок)."""
    tok = _mi.token(cfg["token_var"])
    fields = ("id,name,status,locale,created_time,leads_count,is_optimized_for_quality,questions,context_card,"
              "thank_you_page,privacy_policy_url,legal_content,follow_up_action_url,block_display_for_non_targeted_viewer,question_page_custom_headline")
    res, _ = call(cfg, "GET", form_id, {"fields": fields}, page_token(cfg, tok))
    print(json.dumps(res, ensure_ascii=False, indent=1))


def cmd_wa(cfg):
    """Только чтение: подключён ли WhatsApp к странице. Номер печатается как отдала Meta."""
    tok = _mi.token(cfg["token_var"])
    fields = "name,whatsapp_number,has_whatsapp_number,has_whatsapp_business_number"
    res, _ = call(cfg, "GET", cfg["page_id"], {"fields": fields}, page_token(cfg, tok))
    print(json.dumps({k: res.get(k) for k in fields.split(",")}, ensure_ascii=False, indent=1))
    if res.get("whatsapp_number") or res.get("has_whatsapp_number"):
        print("WhatsApp на странице: есть")
    elif res.get("has_whatsapp_number") is False:
        print("WhatsApp на странице: Meta ответила, что не подключён")
    else:
        print("WhatsApp на странице: Meta не отдала поля. Это НЕ ответ «нет»: точно проверяет только addsets --validate-only группы WHATSAPP")


def cmd_perms(cfg):
    """Только чтение: какие права (scopes) выданы ключу — granted / declined. Для форм нужны pages_manage_ads + leads_retrieval."""
    tok = _mi.token(cfg["token_var"])
    res, _ = call(cfg, "GET", "me/permissions", {}, tok)
    print(json.dumps(res.get("data", []), ensure_ascii=False, indent=1))


# ---------- мгновенная форма ----------
FORM_QTYPES = {"CUSTOM", "FULL_NAME", "FIRST_NAME", "PHONE", "WHATSAPP_NUMBER", "EMAIL", "CITY", "COUNTRY"}


def check_form(cfg, f):
    """Проверка плана формы без Meta. Форму в Meta не исправить — ошибка ловится здесь, до создания."""
    errs = []
    if not f.get("name", "").startswith(cfg["prefix"]):
        errs.append(f"имя формы без приставки {cfg['prefix']}")
    qs = f.get("questions") or []
    types = [q.get("type") for q in qs]
    errs += [f"вопрос «{q.get('label', q.get('type'))}»: тип {q.get('type')} охранник не знает" for q in qs if q.get("type") not in FORM_QTYPES]
    if "WHATSAPP_NUMBER" not in types and "PHONE" not in types:
        errs.append("нет контакта: нужен WHATSAPP_NUMBER или PHONE")
    if "FULL_NAME" not in types and "FIRST_NAME" not in types:
        errs.append("нет имени (FULL_NAME)")
    for q in qs:
        if q.get("type") == "CUSTOM" and (not q.get("label") or not q.get("key") or len(q.get("options") or []) < 2):
            errs.append(f"свой вопрос «{q.get('label')}»: нужны label, key и ≥2 варианта")
    if not str((f.get("privacy_policy") or {}).get("url", "")).startswith("https://"):
        errs.append("нет политики конфиденциальности (privacy_policy.url, https)")
    ty = f.get("thank_you_page") or {}
    if not ty.get("title") or not ty.get("button_text"):
        errs.append("экран «спасибо»: нужны title и button_text")
    if ty.get("button_type") == "VIEW_WEBSITE" and not str(ty.get("website_url", "")).startswith("https://"):
        errs.append("экран «спасибо»: VIEW_WEBSITE без https-ссылки")
    if "is_optimized_for_quality" not in f:
        errs.append("тип формы не указан (is_optimized_for_quality: true = «Высокое намерение», false = «Больше объёма») — решается под запуск")
    text = json.dumps(f, ensure_ascii=False).lower().replace(" ", "")
    errs += [f"стоп-слово «{w}»" for w in FORBIDDEN_WORDS if w.replace(" ", "") in text]
    return errs


def cmd_newform(cfg, plan, check_only=False):
    """Создать мгновенную форму на странице. Только после «да» владельца (approved_by_owner). Повторов нет."""
    f = {k: v for k, v in plan["form"].items() if not k.startswith("_")}
    errs = check_form(cfg, f)
    tok = _mi.token(cfg["token_var"])
    ptok = page_token(cfg, tok)
    have, _ = call(cfg, "GET", f"{cfg['page_id']}/leadgen_forms", {"fields": "id,name", "limit": 100}, ptok)
    if any(x["name"] == f["name"] for x in have.get("data", [])):
        errs.append(f"форма «{f['name']}» уже есть на странице — дубль не создаю")
    if errs:
        raise Stop("план формы не прошёл проверку: " + "; ".join(errs))
    if check_only:
        print(f"✓ план формы «{f['name']}» прошёл проверку (в Meta ничего не создано)")
        return
    if not approved(plan):
        raise Stop("в плане нет «да» владельца (approved_by_owner) — не создаю")
    log(cfg, kind="start", plan=plan.get("name"), object="leadgen_form")
    res = write(cfg, ptok, f"{cfg['page_id']}/leadgen_forms", f, "leadgen_form", f["name"])
    fid = res["id"]
    got, _ = call(cfg, "GET", fid, {"fields": "name,status,locale,is_optimized_for_quality,questions,thank_you_page,privacy_policy_url,block_display_for_non_targeted_viewer"}, ptok)
    diffs = []
    if got.get("name") != f["name"]:
        diffs.append("имя")
    if bool(got.get("is_optimized_for_quality")) != bool(f["is_optimized_for_quality"]):
        diffs.append("тип формы")
    if [q.get("type") for q in got.get("questions", [])] != [q["type"] for q in f["questions"]]:
        diffs.append("вопросы")
    if (got.get("thank_you_page") or {}).get("title") != f["thank_you_page"]["title"]:
        diffs.append("экран «спасибо»")
    if diffs:
        raise Stop(f"форма {fid} создана, но прочитана не так, как отправлена: {', '.join(diffs)} — не подключать, показать владельцу (архивирует он в Ads Manager)")
    log(cfg, kind="done", plan=plan.get("name"), created=[{"leadgen_form": fid}])
    print(json.dumps({"форма_создана": fid, "имя": got["name"], "статус": got.get("status"), "lead_form_id_для_плана": fid}, ensure_ascii=False, indent=1))


def verify(cfg, tok, oid, budget_cents=None, expect="PAUSED"):
    r, _ = call(cfg, "GET", oid, {"fields": "status" + (",daily_budget" if budget_cents is not None else "")}, tok)
    if r.get("status") != expect:
        raise Stop(f"{oid}: статус {r.get('status')} вместо {expect} — стоп, нужен владелец")
    if budget_cents is not None and int(r.get("daily_budget", -1)) != budget_cents:
        raise Stop(f"{oid}: бюджет {r.get('daily_budget')} ≠ {budget_cents} центов — стоп (ошибка единиц?)")


# ---------- два формата в одном объявлении (Placement Asset Customization) ----------
# Документация Meta: marketing-api/dynamic-creative/placement-asset-customization — asset_feed_spec: videos с adlabels,
# asset_customization_rules (customization_spec + video_label), ad_formats SINGLE_VIDEO, optimization_type PLACEMENT, ≥ 2 правил.
PAC_VERTICAL = {"publisher_platforms": ["facebook", "instagram", "messenger"],
                "facebook_positions": ["story", "facebook_reels"], "instagram_positions": ["story", "reels"],
                "messenger_positions": ["story"]}
PAC_FEED = {"publisher_platforms": ["facebook", "instagram", "audience_network"],
            "facebook_positions": ["feed", "video_feeds", "marketplace", "search"],
            "instagram_positions": ["stream", "explore", "profile_feed", "ig_search"],
            "audience_network_positions": ["classic"]}


def pac_creative(cfg, ad, vid_916, thumb_916, vid_45, thumb_45):
    """Креатив: video (9:16) → сторис/рилс, video_feed (4:5) → лента и остальное. Текст/заголовок/описание/ссылка — те же поля плана."""
    feed = {"videos": [{"video_id": vid_916, "thumbnail_hash": thumb_916, "adlabels": [{"name": "v916"}]},
                       {"video_id": vid_45, "thumbnail_hash": thumb_45, "adlabels": [{"name": "v45"}]}],
            "bodies": [{"text": ad.get("primary_text", "")}], "titles": [{"text": ad.get("headline", "")}],
            "link_urls": [{"website_url": ad["link"]}], "call_to_action_types": [ad.get("cta", "LEARN_MORE")],
            "ad_formats": ["SINGLE_VIDEO"], "optimization_type": "PLACEMENT",
            "asset_customization_rules": [{"customization_spec": PAC_VERTICAL, "video_label": {"name": "v916"}},
                                          {"customization_spec": PAC_FEED, "video_label": {"name": "v45"}}]}
    if ad.get("description"):
        feed["descriptions"] = [{"text": ad["description"]}]
    story = {"page_id": cfg["page_id"]}
    if cfg.get("instagram_user_id"):
        story["instagram_user_id"] = cfg["instagram_user_id"]
    return {"name": ad["name"], "object_story_spec": story, "asset_feed_spec": feed, "url_tags": cfg["url_tags"]}


def verify_pac(cfg, tok, cr_id, sent):
    """Чтение обратно первого креатива: два видео, правила плейсментов, текст и ссылка — как отправили. Нет → стоп."""
    r, _ = call(cfg, "GET", cr_id, {"fields": "asset_feed_spec,url_tags"}, tok)
    got, want = r.get("asset_feed_spec") or {}, sent["asset_feed_spec"]
    errs = []
    # Meta копирует видео креатива под новыми id (отправили одни, прочитали другие) — id не сравниваем.
    # Сверяем по метке: тот же файл (название видео в кабинете), та же обложка и формат кадра (9:16 вертикаль / 4:5).
    if len(got.get("videos", [])) != len(want["videos"]):
        errs.append(f"видео в креативе {len(got.get('videos', []))} ≠ {len(want['videos'])}")
    for w in want["videos"]:
        lab = w["adlabels"][0]["name"]
        g = next((x for x in got.get("videos", []) if any(l.get("name") == lab for l in x.get("adlabels", []))), None)
        if not g:
            errs.append(f"нет видео с меткой {lab}")
            continue
        if g.get("thumbnail_hash") != w["thumbnail_hash"]:
            errs.append(f"{lab}: обложка {g.get('thumbnail_hash')} ≠ {w['thumbnail_hash']}")
        sent_v, _ = call(cfg, "GET", w["video_id"], {"fields": "title"}, tok)
        got_v, _ = call(cfg, "GET", g["video_id"], {"fields": "title,format"}, tok)
        if got_v.get("title") != sent_v.get("title"):
            errs.append(f"{lab}: видео «{got_v.get('title')}» ≠ «{sent_v.get('title')}»")
        fm = next((f for f in got_v.get("format", []) if f.get("width") and f.get("height")), None)
        ratio = fm["height"] / fm["width"] if fm else 0
        if lab == "v916" and not 1.6 < ratio < 1.9:
            errs.append(f"{lab}: кадр {fm and (fm['width'], fm['height'])} — не 9:16")
        if lab == "v45" and not 1.15 < ratio < 1.35:
            errs.append(f"{lab}: кадр {fm and (fm['width'], fm['height'])} — не 4:5")
    rules = got.get("asset_customization_rules", [])
    if len(rules) != len(want["asset_customization_rules"]):
        errs.append(f"правил плейсментов {len(rules)} ≠ {len(want['asset_customization_rules'])}")
    for w in want["asset_customization_rules"]:
        g = next((x for x in rules if (x.get("video_label") or {}).get("name") == w["video_label"]["name"]), None)
        if not g:
            errs.append(f"нет правила для {w['video_label']['name']}")
            continue
        for k, v in w["customization_spec"].items():
            if sorted(g.get("customization_spec", {}).get(k, [])) != sorted(v):
                errs.append(f"{w['video_label']['name']}.{k}: {g.get('customization_spec', {}).get(k)} ≠ {v}")
    if [b.get("text") for b in got.get("bodies", [])] != [b["text"] for b in want["bodies"]]:
        errs.append("основной текст ≠ плану")
    if [b.get("text") for b in got.get("titles", [])] != [b["text"] for b in want["titles"]]:
        errs.append("заголовок ≠ плану")
    if [u.get("website_url", "").rstrip("/") for u in got.get("link_urls", [])] != [u["website_url"].rstrip("/") for u in want["link_urls"]]:
        errs.append(f"ссылка {[u.get('website_url') for u in got.get('link_urls', [])]} ≠ {[u['website_url'] for u in want['link_urls']]}")
    log(cfg, kind="pac_check", creative=cr_id, ok=not errs, errors=errs)
    if errs:
        raise Stop(f"креатив {cr_id} с двумя форматами прочитан не так, как отправлен: " + "; ".join(errs))
    print(f"✓ креатив {cr_id}: 2 видео, правила 9:16 → сторис/рилс и 4:5 → лента на месте, текст и ссылка совпали")


def pac_previews(cfg, tok, ad_id):
    """Только чтение: ссылки предпросмотра первого объявления (лента 4:5, сторис/рилс 9:16). Не получилось — не стоп."""
    out = {}
    try:
        r, _ = call(cfg, "GET", ad_id, {"fields": "preview_shareable_link"}, tok)
        out["общая"] = r.get("preview_shareable_link")
    except Stop as e:
        out["общая"] = f"нет: {e}"
    for fmt in ("MOBILE_FEED_STANDARD", "INSTAGRAM_STANDARD", "INSTAGRAM_STORY", "INSTAGRAM_REELS", "FACEBOOK_STORY_MOBILE"):
        try:
            r, _ = call(cfg, "GET", f"{ad_id}/previews", {"ad_format": fmt}, tok)
            body = (r.get("data") or [{}])[0].get("body", "")
            src = body.split('src="', 1)[1].split('"', 1)[0].replace("&amp;", "&") if 'src="' in body else ""
            out[fmt] = src or "пусто"
        except Stop as e:
            out[fmt] = f"нет: {e}"
    log(cfg, kind="pac_previews", ad=ad_id, previews=out)
    print("Предпросмотр первого объявления:\n  " + "\n  ".join(f"{k}: {v}" for k, v in out.items()))


def adset_params(cfg, a, campaign_id, cents, status):
    """Параметры группы + ЕС/DSA: "dsa_beneficiary" / "dsa_payor" группы плана уходят в Meta как есть.
    Без полей Meta берёт значения кабинета по умолчанию."""
    p = _adset_params_base(cfg, a, campaign_id, cents, status)
    for k in ("dsa_beneficiary", "dsa_payor"):
        if str(a.get(k, "")).strip():
            p[k] = str(a[k]).strip()
    return p


def verify_dsa(cfg, tok, adset_id, a):
    """Чтение обратно: бенефициар и плательщик ЕС в группе как в плане. Не совпало → стоп до объявлений."""
    want = {k: str(a[k]).strip() for k in ("dsa_beneficiary", "dsa_payor") if str(a.get(k, "")).strip()}
    if not want:
        return
    r, _ = call(cfg, "GET", adset_id, {"fields": "dsa_beneficiary,dsa_payor"}, tok)
    errs = [f"{k}: «{r.get(k)}» ≠ «{v}»" for k, v in want.items() if r.get(k) != v]
    log(cfg, kind="dsa_check", adset=adset_id, ok=not errs, got={k: r.get(k) for k in want}, errors=errs)
    if errs:
        raise Stop(f"группа {adset_id}: ЕС-бенефициар/плательщик прочитаны не так, как отправлены: " + "; ".join(errs))
    print(f"✓ группа {adset_id}: бенефициар «{r.get('dsa_beneficiary')}», плательщик «{r.get('dsa_payor')}» (прочитано обратно)")


def _adset_params_base(cfg, a, campaign_id, cents, status):
    """Параметры группы для Meta из группы плана (общие для live и addsets)."""
    targeting = {"geo_locations": geo_locations(a), "age_min": a.get("age_min", 18), "age_max": a.get("age_max", 65)}
    if a.get("locales"):
        targeting["locales"] = a["locales"]
    if a.get("genders"):
        targeting["genders"] = a["genders"]
    if a.get("no_audience_network"):
        # Audience Network часто даёт дешёвые случайные клики — оставляем FB/IG/Messenger, позиции внутри — авто
        targeting["publisher_platforms"] = ["facebook", "instagram", "messenger"]
    if a.get("placements"):
        # ручные размещения: только FB/IG, позиции списком; AN и Messenger check_plan не пропускает
        targeting.pop("publisher_platforms", None)
        targeting.update({k: v for k, v in a["placements"].items() if k in PLACEMENT_KEYS})
    if a.get("interests"):
        targeting["flexible_spec"] = [{"interests": [{"id": str(i["id"]), "name": i["name"]} for i in a["interests"]]}]
    if a.get("user_device"):
        targeting["user_device"] = a["user_device"]  # И с интересами: Meta требует оба условия
    if a.get("user_os"):
        targeting["user_os"] = a["user_os"]
    if a.get("device_platforms"):
        targeting["device_platforms"] = a["device_platforms"]
    if a.get("advantage_audience") is not None:
        targeting["targeting_automation"] = {"advantage_audience": int(a["advantage_audience"])}
    form = a.get("lead_form_id")
    if is_profile(a):
        reg = {"regional_regulated_categories": a["regional_regulated_categories"],
               "regional_regulation_identities": a["regional_regulation_identities"]} if a.get("regional_regulation_identities") else {}
        return {**reg, "name": a["name"], "campaign_id": campaign_id, "status": status, "daily_budget": cents,
                "billing_event": "IMPRESSIONS", "optimization_goal": "PROFILE_VISIT", "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                "destination_type": "INSTAGRAM_PROFILE", "promoted_object": {"page_id": cfg["page_id"]},
                "targeting": targeting, **({"start_time": a["start_time"]} if a.get("start_time") else {})}
    if is_direct(a):
        reg = {"regional_regulated_categories": a["regional_regulated_categories"],
               "regional_regulation_identities": a["regional_regulation_identities"]} if a.get("regional_regulation_identities") else {}
        return {**reg, "name": a["name"], "campaign_id": campaign_id, "status": status, "daily_budget": cents,
                "billing_event": "IMPRESSIONS", "optimization_goal": "CONVERSATIONS", "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                "destination_type": "INSTAGRAM_DIRECT", "promoted_object": {"page_id": cfg["page_id"]},
                "targeting": targeting, **({"start_time": a["start_time"]} if a.get("start_time") else {})}
    if is_whatsapp(a):
        reg = {"regional_regulated_categories": a["regional_regulated_categories"],
               "regional_regulation_identities": a["regional_regulation_identities"]} if a.get("regional_regulation_identities") else {}
        promoted = {"page_id": cfg["page_id"], "whatsapp_phone_number": a["whatsapp_number"]}
        return {**reg, "name": a["name"], "campaign_id": campaign_id, "status": status, "daily_budget": cents,
                "billing_event": "IMPRESSIONS", "optimization_goal": "CONVERSATIONS", "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
                "destination_type": "WHATSAPP", "promoted_object": promoted,
                "targeting": targeting, **({"start_time": a["start_time"]} if a.get("start_time") else {})}
    # подтверждённый рекламодатель (Meta: новая группа на Таиланд без него — код 100/3858634)
    reg = {"regional_regulated_categories": a["regional_regulated_categories"],
           "regional_regulation_identities": a["regional_regulation_identities"]} if a.get("regional_regulation_identities") else {}
    return {**reg,
        "name": a["name"], "campaign_id": campaign_id, "status": status, "daily_budget": cents,
        "billing_event": "IMPRESSIONS",
        "optimization_goal": a.get("optimization_goal", "LEAD_GENERATION" if form else "OFFSITE_CONVERSIONS"),
        "bid_strategy": "LOWEST_COST_WITHOUT_CAP", "destination_type": a.get("destination_type", "ON_AD" if form else "WEBSITE"),
        "promoted_object": {"page_id": cfg["page_id"]} if form else {"pixel_id": cfg["pixel_id"], "custom_event_type": a.get("event", "LEAD")},
        "targeting": targeting, **({"start_time": a["start_time"]} if a.get("start_time") else {})}


def direct_creative_params(cfg, plan, ad, image_hash, video_id=None):
    """Креатив «сообщение в директ Instagram»: кнопка INSTAGRAM_MESSAGE, заготовленное сообщение, без ссылки."""
    cta = {"type": "INSTAGRAM_MESSAGE", "value": {"app_destination": "INSTAGRAM_DIRECT"}}
    wm = welcome_message(ad)
    if video_id:
        body = {"video_id": video_id, "image_hash": image_hash, "message": ad.get("primary_text", ""),
                "title": ad.get("headline", ""), "call_to_action": cta}
        if wm:
            body["page_welcome_message"] = wm
        story = {"page_id": cfg["page_id"], "instagram_user_id": ig_user(cfg, plan), "video_data": body}
    else:
        body = {"image_hash": image_hash, "link": "https://www.instagram.com/", "message": ad.get("primary_text", ""),
                "name": ad.get("headline", ""), "call_to_action": cta}
        if wm:
            body["page_welcome_message"] = wm
        story = {"page_id": cfg["page_id"], "instagram_user_id": ig_user(cfg, plan), "link_data": body}
    cr_params = {"name": ad["name"], "object_story_spec": story}
    if plan.get("creative_features_opt_out"):
        cr_params["degrees_of_freedom_spec"] = {"creative_features_spec": {f: {"enroll_status": "OPT_OUT"} for f in plan["creative_features_opt_out"]}}
    return cr_params


def whatsapp_creative_params(cfg, plan, ad, image_hash, video_id=None):
    """Креатив «написать в WhatsApp» (документация Meta: click-to-whatsapp): кнопка WHATSAPP_MESSAGE, заготовка с кодовым словом, ссылки на сайт нет."""
    if ad.get("carousel"):  # карусель WhatsApp; в проверках validate_only — одна картинка кабинета на всех карточках
        return carousel_creative_params(cfg, plan, ad, None, [image_hash] * len(ad["carousel"]), whatsapp=True)
    cta = {"type": "WHATSAPP_MESSAGE", "value": {"app_destination": "WHATSAPP"}}
    wm = welcome_message(ad)
    if video_id:
        body = {"video_id": video_id, "image_hash": image_hash, "message": ad.get("primary_text", ""),
                "title": ad.get("headline", ""), "call_to_action": cta}
        key = "video_data"
    else:
        body = {"image_hash": image_hash, "link": "https://api.whatsapp.com/send", "message": ad.get("primary_text", ""),
                "name": ad.get("headline", ""), "call_to_action": cta}
        if ad.get("description"):
            body["description"] = ad["description"]
        key = "link_data"
    if wm:
        body["page_welcome_message"] = wm
    story = {"page_id": cfg["page_id"], key: body}
    if ig_user(cfg, plan):
        story["instagram_user_id"] = ig_user(cfg, plan)
    cr_params = {"name": ad["name"], "object_story_spec": story}
    if plan.get("creative_features_opt_out"):
        cr_params["degrees_of_freedom_spec"] = {"creative_features_spec": {f: {"enroll_status": "OPT_OUT"} for f in plan["creative_features_opt_out"]}}
    return cr_params


def digits(x):
    return "".join(ch for ch in str(x) if ch.isdigit())


def verify_whatsapp_adset(cfg, tok, adset_id, a):
    """Чтение обратно группы WhatsApp: destination и номер как в плане. Не совпало → стоп до объявлений."""
    r, _ = call(cfg, "GET", adset_id, {"fields": "destination_type,optimization_goal,promoted_object"}, tok)
    got = (r.get("promoted_object") or {}).get("whatsapp_phone_number")
    errs = []
    if r.get("destination_type") != "WHATSAPP":
        errs.append(f"destination {r.get('destination_type')}")
    if r.get("optimization_goal") != "CONVERSATIONS":
        errs.append(f"цель оптимизации {r.get('optimization_goal')}")
    # Meta при чтении promoted_object номер может не отдать (в Ads Manager он стоит) —
    # пустой номер = предупреждение «проверить глазами»; другой номер — по-прежнему стоп
    number_unread = not digits(got)
    if not number_unread and digits(got) != digits(a["whatsapp_number"]):
        errs.append(f"номер {got} ≠ {a['whatsapp_number']}")
    log(cfg, kind="whatsapp_adset_check", adset=adset_id, ok=not errs, errors=errs, number_unread=number_unread)
    if errs:
        raise Stop(f"группа WhatsApp {adset_id} прочитана не так, как отправлена: " + "; ".join(errs))
    if number_unread:
        print(f"⚠ группа {adset_id}: Meta не отдала номер WhatsApp при чтении — проверить глазами в Ads Manager ({a['whatsapp_number']})")


def verify_whatsapp_creative(cfg, tok, cr_id, ad):
    """Чтение обратно креатива WhatsApp: кнопка строго; кодовое слово сверяем, если Meta отдала заготовку. Кнопка не та или слово другое → стоп до объявления."""
    r, _ = call(cfg, "GET", cr_id, {"fields": "call_to_action_type,object_story_spec"}, tok)
    spec = json.dumps(r.get("object_story_spec") or {}, ensure_ascii=False)
    errs = []
    if r.get("call_to_action_type") != "WHATSAPP_MESSAGE":
        errs.append(f"кнопка {r.get('call_to_action_type')}")
    has_wm = "autofill_message" in spec
    if has_wm and str(ad["code_word"]).lower() not in spec.lower():
        errs.append(f"в заготовке нет слова {ad['code_word']}")
    log(cfg, kind="whatsapp_creative_check", creative=cr_id, ok=not errs, errors=errs, welcome_read=has_wm)
    if errs:
        raise Stop(f"креатив WhatsApp {cr_id} прочитан не так, как отправлен: " + "; ".join(errs))
    print(f"✓ креатив {cr_id}: кнопка WhatsApp, заготовка: " + (f"слово {ad['code_word']} на месте" if has_wm else "Meta не отдала, проверить превью глазами"))


def account_image_hash(cfg, tok, act):
    """Только чтение: hash картинки, которая уже лежит в кабинете, — чтобы проверить креатив через validate_only, ничего не загружая."""
    res, _ = call(cfg, "GET", f"{act}/adimages", {"fields": "hash", "limit": 1}, tok)
    if not res.get("data"):
        raise Stop("в кабинете нет ни одной картинки — проверить креатив без загрузки нельзя")
    return res["data"][0]["hash"]


def account_video_id(cfg, tok, act):
    """Только чтение: id видео, которое уже лежит в кабинете, — для проверки видео-креатива через validate_only."""
    res, _ = call(cfg, "GET", f"{act}/advideos", {"fields": "id", "limit": 1}, tok)
    if not res.get("data"):
        raise Stop("в кабинете нет ни одного видео — проверить видео-креатив без загрузки нельзя")
    return res["data"][0]["id"]


def post_creative_params(cfg, plan, ad, direct):
    """Креатив из существующей публикации Instagram: Direct или профиль. Подпись и видео — самой публикации."""
    if direct:
        cta = {"type": "INSTAGRAM_MESSAGE", "value": {"app_destination": "INSTAGRAM_DIRECT", "link": "https://www.instagram.com"}}  # Meta 100/2061015: без link не принимает
    else:
        cta = {"type": "VIEW_INSTAGRAM_PROFILE", "value": {"link": ad["profile_link"]}}
    params = {"name": ad["name"], "object_id": cfg["page_id"], "instagram_user_id": ig_user(cfg, plan),
              "source_instagram_media_id": str(ad["source_instagram_media_id"]), "call_to_action": cta}
    wm = welcome_message(ad) if direct else None
    if wm:
        params["page_welcome_message"] = wm
    if plan.get("creative_features_opt_out"):
        params["degrees_of_freedom_spec"] = {"creative_features_spec": {f: {"enroll_status": "OPT_OUT"} for f in plan["creative_features_opt_out"]}}
    return params


def verify_post_creative(cfg, tok, cr_id, ad, direct):
    """Чтение обратно: та же публикация и та же кнопка. Не совпало → стоп до объявления."""
    r, _ = call(cfg, "GET", cr_id, {"fields": "source_instagram_media_id,instagram_user_id,call_to_action_type,instagram_permalink_url,page_welcome_message"}, tok)
    want_cta = "INSTAGRAM_MESSAGE" if direct else "VIEW_INSTAGRAM_PROFILE"
    errs = []
    if str(r.get("source_instagram_media_id")) != str(ad["source_instagram_media_id"]):
        errs.append(f"публикация {r.get('source_instagram_media_id')}")
    if r.get("call_to_action_type") != want_cta:
        errs.append(f"кнопка {r.get('call_to_action_type')}")
    log(cfg, kind="post_creative_check", creative=cr_id, ok=not errs, errors=errs, permalink=r.get("instagram_permalink_url"),
        welcome=bool(r.get("page_welcome_message")))
    if errs:
        raise Stop(f"креатив {cr_id} прочитан не так, как отправлен: " + "; ".join(errs))
    print(f"✓ креатив {cr_id}: {r.get('instagram_permalink_url')}, кнопка {r.get('call_to_action_type')}, заготовка: {'есть' if r.get('page_welcome_message') else 'нет'}")


def carousel_creative_params(cfg, plan, ad, form, card_hashes, whatsapp=False):
    """Карусель: link_data.child_attachments, порядок карточек как в плане (multi_share_optimized false),
    без авто-карточки в конце; у каждой карточки та же кнопка (лид-форма, ссылка или WhatsApp с заготовкой)."""
    if whatsapp:
        link = "https://api.whatsapp.com/send"
        cta = {"type": "WHATSAPP_MESSAGE", "value": {"app_destination": "WHATSAPP"}}
    else:
        link = ad.get("link") or "http://fb.me/"
        cta_value = {"lead_gen_form_id": form} if form else {"link": link}
        if form and ad.get("link"):
            cta_value["link"] = ad["link"]
        cta = {"type": ad.get("cta", "SIGN_UP" if form else "LEARN_MORE"), "value": cta_value}
    cards = []
    for card, h in zip(ad["carousel"], card_hashes):
        ch = {"link": link, "image_hash": h, "name": card["headline"], "call_to_action": cta}
        if card.get("description"):
            ch["description"] = card["description"]
        cards.append(ch)
    link_data = {"link": link, "message": ad.get("primary_text", ""), "child_attachments": cards,
                 "multi_share_optimized": False, "multi_share_end_card": False, "call_to_action": cta}
    if ad.get("headline"):
        link_data["name"] = ad["headline"]
    if whatsapp and welcome_message(ad):
        link_data["page_welcome_message"] = welcome_message(ad)
    story = {"page_id": cfg["page_id"], "link_data": link_data}
    if cfg.get("instagram_user_id"):
        story["instagram_user_id"] = cfg["instagram_user_id"]
    cr_params = {"name": ad["name"], "object_story_spec": story}
    if not whatsapp:
        cr_params["url_tags"] = cfg["url_tags"]
    if plan.get("creative_features_opt_out"):
        cr_params["degrees_of_freedom_spec"] = {"creative_features_spec": {f: {"enroll_status": "OPT_OUT"} for f in plan["creative_features_opt_out"]}}
    return cr_params


def verify_carousel(cfg, tok, cr_id, ad, form):
    """Чтение обратно карусели: число и порядок карточек (заголовки), картинки по hash, форма у каждой карточки. Не совпало → стоп до объявления."""
    r, _ = call(cfg, "GET", cr_id, {"fields": "object_story_spec,call_to_action_type"}, tok)
    got = ((r.get("object_story_spec") or {}).get("link_data") or {}).get("child_attachments") or []
    errs = []
    if [c.get("name") for c in got] != [c["headline"] for c in ad["carousel"]]:
        errs.append(f"карточки {[c.get('name') for c in got]}")
    if form:
        bad = [i + 1 for i, c in enumerate(got) if str(((c.get("call_to_action") or {}).get("value") or {}).get("lead_gen_form_id")) != str(form)]
        if bad:
            errs.append(f"форма не та в карточках {bad}")
    log(cfg, kind="carousel_check", creative=cr_id, ok=not errs, errors=errs, cards=len(got))
    if errs:
        raise Stop(f"карусель {cr_id} прочитана не так, как отправлена: " + "; ".join(errs))
    print(f"✓ карусель {cr_id}: {len(got)} карточек по порядку" + (f", форма {form} у каждой" if form else ""))


def creative_params(cfg, plan, ad, form, image_hash, video_id=None, direct=False, whatsapp=False):
    """Креатив одного формата (картинка или видео) для Meta из объявления плана (общий для live и addsets)."""
    if whatsapp:
        return whatsapp_creative_params(cfg, plan, ad, image_hash, video_id)
    if direct:
        return direct_creative_params(cfg, plan, ad, image_hash, video_id)
    cta_value = {"lead_gen_form_id": form} if form else {"link": ad["link"]}
    if form and ad.get("link"):
        cta_value["link"] = ad["link"]
    cta = {"type": ad.get("cta", "SIGN_UP" if form else "LEARN_MORE"), "value": cta_value}
    if video_id:
        vd = {"video_id": video_id, "image_hash": image_hash, "message": ad.get("primary_text", ""),
              "title": ad.get("headline", ""), "call_to_action": cta}
        if ad.get("description"):
            vd["link_description"] = ad["description"]
        story = {"page_id": cfg["page_id"], "video_data": vd}
    else:
        link_data = {"image_hash": image_hash, "link": ad.get("link") or "http://fb.me/", "message": ad.get("primary_text", ""),
                     "name": ad.get("headline", ""), "call_to_action": cta}
        if ad.get("description"):
            link_data["description"] = ad["description"]
        story = {"page_id": cfg["page_id"], "link_data": link_data}
    if cfg.get("instagram_user_id"):
        story["instagram_user_id"] = cfg["instagram_user_id"]
    cr_params = {"name": ad["name"], "object_story_spec": story, "url_tags": cfg["url_tags"]}
    if plan.get("creative_features_opt_out"):
        cr_params["degrees_of_freedom_spec"] = {"creative_features_spec": {f: {"enroll_status": "OPT_OUT"} for f in plan["creative_features_opt_out"]}}
    return cr_params


def work_hours_check(cfg):
    h = now_local(cfg).hour
    start, end = cfg["work_hours"]
    if not (start <= h < end):
        raise Stop(f"сейчас {h}:00 ({cfg.get('tz')}) — работаю только {start}–{end}")


def cmd_live(cfg, plan, validate_only):
    if not validate_only and not approved(plan):
        raise Stop("в плане нет «да» владельца (approved_by_owner) — не создаю")
    tok = _mi.token(cfg["token_var"])
    acc, _ = call(cfg, "GET", f"act_{cfg['act']}", {"fields": "currency,account_status,timezone_name"}, tok)
    ensure_tz(cfg, tok, acc.get("timezone_name"))
    work_hours_check(cfg)
    plan = apply_start_next_day(cfg, apply_verified_advertiser(cfg, plan))
    if acc["account_status"] != 1:
        raise Stop(f"кабинет не активен (статус {acc['account_status']}) — стоп, нужен владелец")
    off = money_offset(acc["currency"])
    errs, warn, stats = check_plan(cfg, plan, active_daily_usd(cfg, tok, off))
    if errs:
        raise Stop("план не прошёл проверку: " + "; ".join(errs))
    name_errs, name_rows = resolve_names(cfg, tok, plan)
    print("Коды по Meta:\n  " + "\n  ".join(name_rows))
    if name_errs:
        raise Stop("коды не совпали с названиями: " + "; ".join(name_errs))
    act = f"act_{cfg['act']}"
    log(cfg, kind="start", plan=plan.get("name"), validate_only=validate_only, stats=stats)
    created = []
    images, videos = {}, {}  # файлы кабинета общие для всех кампаний — каждый грузим один раз за запуск
    pac_gate_done = False     # первое объявление с двумя форматами — читаем обратно и сверяем до остальных

    def img(pic):
        if pic not in images:
            raw = (OFFICE / pic).read_bytes()
            up = write(cfg, tok, f"{act}/adimages", {"bytes": base64.b64encode(raw).decode()}, "image", pic)
            images[pic] = next(iter(up["images"].values()))["hash"]
            pause(cfg)
        return images[pic]

    def vid(rel):
        if rel not in videos:
            videos[rel] = upload_video(cfg, tok, act, rel)
            pause(cfg)
        return videos[rel]

    if validate_only:
        # креатив с двумя форматами Meta проверяет через validate_only (видео и обложки при этом грузятся по-настоящему —
        # в кабинет, без показа; кампаний/групп/объявлений не создаётся)
        sample = next((ad for c in plan["campaigns"] for a in c["adsets"] for ad in a["ads"] if ad.get("video_feed")), None)
        if sample:
            spec = pac_creative(cfg, sample, vid(sample["video"]), img(sample["thumb"]), vid(sample["video_feed"]), img(sample["thumb_feed"]))
            write(cfg, tok, f"{act}/adcreatives", {**spec, "execution_options": ["validate_only"]}, "validate", sample["name"])
            print(f"✓ Meta приняла креатив с двумя форматами «{sample['name']}» (validate_only, креатив не создан)")
        # существующая публикация: по одному креативу на вид группы, файлы не грузятся
        for test in (is_direct, is_profile):
            psample = next(((a, ad) for c in plan["campaigns"] for a in c["adsets"] if test(a) for ad in a["ads"] if ad.get("source_instagram_media_id")), None)
            if psample:
                write(cfg, tok, f"{act}/adcreatives", {**post_creative_params(cfg, plan, psample[1], is_direct(psample[0])), "execution_options": ["validate_only"]}, "validate", psample[1]["name"])
                print(f"✓ Meta приняла креатив из публикации «{psample[1]['name']}» (validate_only, креатив не создан)")
        # Direct: первый креатив Meta проверяет с instagram_user_id и кнопкой директа (видео/обложка грузятся по-настоящему)
        dsample = next(((a, ad) for c in plan["campaigns"] for a in c["adsets"] if is_direct(a) for ad in a["ads"] if not ad.get("source_instagram_media_id")), None)
        if dsample:
            a0, ad0 = dsample
            pic0 = ad0.get("thumb") if ad0.get("video") else ad0["image"]
            spec = creative_params(cfg, plan, ad0, None, img(pic0), vid(ad0["video"]) if ad0.get("video") else None, direct=True)
            write(cfg, tok, f"{act}/adcreatives", {**spec, "execution_options": ["validate_only"]}, "validate", ad0["name"])
            print(f"✓ Meta приняла креатив Direct «{ad0['name']}» (validate_only, креатив не создан)")
        # карусель: первый креатив-карусель Meta проверяет без загрузки — hash уже лежащей в кабинете картинки на всех карточках
        csample = next(((a, ad) for c in plan["campaigns"] for a in c["adsets"] if not is_whatsapp(a) for ad in a["ads"] if ad.get("carousel")), None)
        if csample:
            h0 = account_image_hash(cfg, tok, act)
            form0 = csample[0].get("lead_form_id")
            if form0 and not str(form0).isdigit():
                print("… карусель: lead_form_id ещё заглушка — креатив карусели проверю после создания формы")
            else:
                spec = carousel_creative_params(cfg, plan, csample[1], form0, [h0] * len(csample[1]["carousel"]))
                write(cfg, tok, f"{act}/adcreatives", {**spec, "execution_options": ["validate_only"]}, "validate", csample[1]["name"])
                print(f"✓ Meta приняла карусель «{csample[1]['name']}» (validate_only, креатив не создан)")
        # WhatsApp: первый креатив картинкой, ничего не грузим — hash уже лежащей в кабинете картинки
        wsample = next((ad for c in plan["campaigns"] for a in c["adsets"] if is_whatsapp(a) for ad in a["ads"]), None)
        if wsample:
            spec = whatsapp_creative_params(cfg, plan, wsample, account_image_hash(cfg, tok, act))
            write(cfg, tok, f"{act}/adcreatives", {**spec, "execution_options": ["validate_only"]}, "validate", wsample["name"])
            print(f"✓ Meta приняла креатив WhatsApp «{wsample['name']}» (validate_only, креатив не создан)")
    for ci, c in enumerate(plan["campaigns"]):
        cparams = {"name": c["name"], "objective": c.get("objective", "OUTCOME_LEADS"), "status": "PAUSED",
                   "buying_type": "AUCTION", "special_ad_categories": [c["special_ad_category"]] if c.get("special_ad_category") else [],
                   "is_adset_budget_sharing_enabled": "false"}
        if c.get("special_ad_category"):
            cparams["special_ad_category_country"] = sorted(set().union(*(geo_countries(a) for a in c["adsets"])))
        if c.get("existing_id"):
            # группы в готовую кампанию: только наша, этого кабинета, на паузе, имя совпадает с планом
            ex, _ = call(cfg, "GET", str(c["existing_id"]), {"fields": "name,status,account_id,special_ad_categories"}, tok)
            if c.get("existing_housing") and "HOUSING" not in (ex.get("special_ad_categories") or []):
                raise Stop(f"кампания {c['existing_id']}: в плане existing_housing, в Meta категории {ex.get('special_ad_categories')} — стоп")
            if str(ex.get("account_id")) != str(cfg["act"]) or ex.get("name") != c["name"] or not ex.get("name", "").startswith(cfg["prefix"]):
                raise Stop(f"кампания {c['existing_id']}: «{ex.get('name')}» / кабинет {ex.get('account_id')} не совпадает с планом «{c['name']}» / act_{cfg['act']}")
            if ex.get("status") != "PAUSED":
                raise Stop(f"кампания {c['existing_id']} не на паузе ({ex.get('status')}) — в работающую кампанию не добавляю")
            if validate_only:
                print(f"✓ готовая кампания «{c['name']}» {c['existing_id']} найдена, на паузе (validate_only, ничего не создано)")
                continue
            camp = {"id": str(c["existing_id"])}
        else:
            if validate_only:
                write(cfg, tok, f"{act}/campaigns", {**cparams, "execution_options": ["validate_only"]}, "validate", c["name"])
                print(f"✓ Meta приняла кампанию «{c['name']}» (validate_only, ничего не создано)")
                continue
            camp = write(cfg, tok, f"{act}/campaigns", cparams, "campaign", c["name"])
            verify(cfg, tok, camp["id"])
            created.append(("campaign", camp["id"], c["name"]))
            pause(cfg)
            if c.get("create_only"):
                # только кампания на паузе (страны HOUSING — из групп плана), группы потом addsets --validate-only по одной и live с existing_id
                print(f"✓ кампания «{c['name']}» {camp['id']} создана на паузе (create_only: групп не создаю)")
                continue
        for a in c["adsets"]:
            cents = int(round(float(a["daily_budget_usd"]) * off))
            form = a.get("lead_form_id")  # мгновенная форма Meta: заявка внутри Facebook/Instagram, без сайта
            aset = write(cfg, tok, f"{act}/adsets", adset_params(cfg, a, camp["id"], cents, "ACTIVE"), "adset", a["name"])
            verify(cfg, tok, aset["id"], cents, expect="ACTIVE")
            created.append(("adset", aset["id"], a["name"]))
            verify_dsa(cfg, tok, aset["id"], a)
            if is_whatsapp(a):
                verify_whatsapp_adset(cfg, tok, aset["id"], a)
            pause(cfg)
            for ad in a["ads"]:
                if ad.get("video_feed"):
                    # два формата в одном объявлении: 9:16 → сторис/рилс, 4:5 → лента и остальное
                    cr_params = pac_creative(cfg, ad, vid(ad["video"]), img(ad["thumb"]), vid(ad["video_feed"]), img(ad["thumb_feed"]))
                    if plan.get("creative_features_opt_out"):
                        cr_params["degrees_of_freedom_spec"] = {"creative_features_spec": {f: {"enroll_status": "OPT_OUT"} for f in plan["creative_features_opt_out"]}}
                    cr = write(cfg, tok, f"{act}/adcreatives", cr_params, "creative", ad["name"])
                    if not pac_gate_done:
                        verify_pac(cfg, tok, cr["id"], cr_params)  # не совпало → стоп ДО остальных объявлений
                    pause(cfg)
                    adr = write(cfg, tok, f"{act}/ads", {"name": ad["name"], "adset_id": aset["id"], "creative": {"creative_id": cr["id"]}, "status": "ACTIVE"}, "ad", ad["name"])
                    verify(cfg, tok, adr["id"], expect="ACTIVE")
                    created.append(("ad", adr["id"], ad["name"]))
                    if not pac_gate_done:
                        pac_previews(cfg, tok, adr["id"])
                        pac_gate_done = True
                    pause(cfg)
                    continue
                if ad.get("source_instagram_media_id"):
                    cr = write(cfg, tok, f"{act}/adcreatives", post_creative_params(cfg, plan, ad, is_direct(a)), "creative", ad["name"])
                    verify_post_creative(cfg, tok, cr["id"], ad, is_direct(a))
                    pause(cfg)
                    adr = write(cfg, tok, f"{act}/ads", {"name": ad["name"], "adset_id": aset["id"], "creative": {"creative_id": cr["id"]}, "status": "ACTIVE"}, "ad", ad["name"])
                    verify(cfg, tok, adr["id"], expect="ACTIVE")
                    created.append(("ad", adr["id"], ad["name"]))
                    pause(cfg)
                    continue
                if ad.get("carousel"):
                    # карусель: картинки карточек грузятся один раз на запуск, креатив читается обратно до объявления
                    cr_params = carousel_creative_params(cfg, plan, ad, form, [img(card["image"]) for card in ad["carousel"]], whatsapp=is_whatsapp(a))
                    cr = write(cfg, tok, f"{act}/adcreatives", cr_params, "creative", ad["name"])
                    verify_carousel(cfg, tok, cr["id"], ad, form)
                    if is_whatsapp(a):
                        verify_whatsapp_creative(cfg, tok, cr["id"], ad)
                    pause(cfg)
                    adr = write(cfg, tok, f"{act}/ads", {"name": ad["name"], "adset_id": aset["id"], "creative": {"creative_id": cr["id"]}, "status": "ACTIVE"}, "ad", ad["name"])
                    verify(cfg, tok, adr["id"], expect="ACTIVE")
                    created.append(("ad", adr["id"], ad["name"]))
                    pause(cfg)
                    continue
                pic = ad.get("thumb") if ad.get("video") else ad["image"]
                img(pic)
                cr_params = creative_params(cfg, plan, ad, form, images[pic], vid(ad["video"]) if ad.get("video") else None, direct=is_direct(a), whatsapp=is_whatsapp(a))
                cr = write(cfg, tok, f"{act}/adcreatives", cr_params, "creative", ad["name"])
                if is_whatsapp(a):
                    verify_whatsapp_creative(cfg, tok, cr["id"], ad)
                pause(cfg)
                adr = write(cfg, tok, f"{act}/ads", {"name": ad["name"], "adset_id": aset["id"], "creative": {"creative_id": cr["id"]}, "status": "ACTIVE"}, "ad", ad["name"])
                verify(cfg, tok, adr["id"], expect="ACTIVE")
                created.append(("ad", adr["id"], ad["name"]))
                pause(cfg)
        verify(cfg, tok, camp["id"])  # группы/объявления включены — кампания обязана остаться на паузе
        if ci < len(plan["campaigns"]) - 1:
            pause(cfg, *cfg["pace"]["between_campaigns_sec"])
    log(cfg, kind="done", plan=plan.get("name"), created=created)
    print(json.dumps({"готово_на_паузе": created, "предупреждения": warn}, ensure_ascii=False, indent=1))


# ---------- группы в существующую кампанию любого статуса ----------
# Кампанию НЕ трогаем (ни статус, ни бюджет, ни настройки), старые группы НЕ трогаем.
# Новые группы — PAUSED (ни цента не тратится), объявления внутри — ACTIVE; включает группы человек сам, старт — start_time.
CAMP_FIELDS = "name,account_id,status,objective,daily_budget,lifetime_budget,spend_cap,bid_strategy,special_ad_categories,start_time,stop_time,updated_time"
CAMP_KEEP = ("name", "status", "objective", "daily_budget", "lifetime_budget", "spend_cap", "bid_strategy", "special_ad_categories", "start_time", "stop_time")
ADSET_FIELDS = "id,name,status,daily_budget,lifetime_budget,start_time,end_time,updated_time,targeting,optimization_goal,bid_strategy"


def snapshot(cfg, tok, camp_id):
    """Только чтение: кампания + все её группы + статусы их объявлений — для сверки «до/после»."""
    camp, _ = call(cfg, "GET", camp_id, {"fields": CAMP_FIELDS}, tok)
    sets, _ = call(cfg, "GET", f"{camp_id}/adsets", {"fields": ADSET_FIELDS, "limit": 200}, tok)
    ads, _ = call(cfg, "GET", f"{camp_id}/ads", {"fields": "id,adset_id,status,updated_time", "limit": 500}, tok)
    return ({k: camp.get(k) for k in CAMP_KEEP} | {"account_id": camp.get("account_id"), "id": camp_id},
            {s["id"]: s for s in sets.get("data", [])},
            {x["id"]: x for x in ads.get("data", [])})


def cmd_devices(cfg, query="iPhone"):
    """Только чтение: названия устройств из поиска Meta (user_device) для плана."""
    res, _ = call(cfg, "GET", "search", {"type": "adTargetingCategory", "class": "user_device", "q": query, "limit": 500}, _mi.token(cfg["token_var"]))
    rows = sorted({r.get("name", "") for r in res.get("data", []) if query.lower() in r.get("name", "").lower()})
    print(json.dumps(rows, ensure_ascii=False, indent=0))


def cmd_show(cfg, adset_id):
    """Только чтение: группа и её объявления как в кабинете — статусы, гео, язык, возраст, бюджет, destination, текст."""
    tok = _mi.token(cfg["token_var"])
    aset, _ = call(cfg, "GET", adset_id, {"fields": "name,account_id,status,effective_status,daily_budget,destination_type,optimization_goal,"
                                          "start_time,targeting,promoted_object,regional_regulated_categories,campaign{name,status,effective_status}"}, tok)
    if str(aset.get("account_id")) != str(cfg["act"]):
        raise Stop(f"группа {adset_id} не из кабинета act_{cfg['act']} — не показываю")
    ads, _ = call(cfg, "GET", f"{adset_id}/ads", {"fields": "id,name,status,effective_status,creative{id,body,object_story_spec,call_to_action_type,instagram_user_id}", "limit": 50}, tok)
    print(json.dumps({"группа": aset, "объявления": ads.get("data", [])}, ensure_ascii=False, indent=1))


def cmd_pauseset(cfg, adset_id, reason):
    """Группу — на паузу. Только status=PAUSED: включать, менять бюджет, удалять эта команда не умеет.
    Только наша группа (приставка конфига) этого кабинета; до записи — чтение имени и статуса, после — чтение обратно, не PAUSED → стоп."""
    if not adset_id or not str(adset_id).isdigit():
        raise Stop("pauseset: нужен ID группы (только цифры)")
    if not reason or not reason.strip():
        raise Stop("pauseset: нужен --reason \"<решение владельца, дата>\"")
    tok = _mi.token(cfg["token_var"])
    ensure_tz(cfg, tok)
    if writes_today(cfg)["write"] + 1 > cfg["limits"]["writes_per_day"]:
        raise Stop(f"записей за день больше потолка {cfg['limits']['writes_per_day']}")
    fields = "name,account_id,status,effective_status,daily_budget,campaign{id,name,status}"
    before, _ = call(cfg, "GET", str(adset_id), {"fields": fields}, tok)
    camp = before.get("campaign") or {}
    if str(before.get("account_id")) != str(cfg["act"]):
        raise Stop(f"группа {adset_id} не из кабинета act_{cfg['act']} — не трогаю")
    if not str(before.get("name", "")).startswith(cfg["prefix"]) or not str(camp.get("name", "")).startswith(cfg["prefix"]):
        raise Stop(f"группа «{before.get('name')}» / кампания «{camp.get('name')}» без приставки {cfg['prefix']} — не трогаю")
    print(f"До: группа «{before['name']}» {adset_id} status {before.get('status')}, effective {before.get('effective_status')}, "
          f"бюджет {before.get('daily_budget')}, кампания «{camp.get('name')}» {camp.get('status')}")
    if before.get("status") == "PAUSED":
        log(cfg, kind="adset_pause_skip", adset=str(adset_id), name=before["name"], reason=reason, note="уже PAUSED, записи нет")
        print("Группа уже на паузе — записи нет")
        return
    res, usage = call(cfg, "POST", str(adset_id), {"status": "PAUSED"}, tok)
    if not res.get("success"):
        raise Stop(f"Meta не подтвердила запись: {res}")
    log(cfg, kind="write", object="adset_pause", name=before["name"], path=str(adset_id), result="ok", id=str(adset_id),
        reason=reason, status_before=before.get("status"))
    busy_check(cfg, usage)
    after = {}
    for _ in range(3):
        time.sleep(5)
        after, _ = call(cfg, "GET", str(adset_id), {"fields": fields}, tok)
        if after.get("status") == "PAUSED":
            break
    ok = (after.get("status") == "PAUSED" and after.get("daily_budget") == before.get("daily_budget")
          and (after.get("campaign") or {}).get("status") == camp.get("status"))
    log(cfg, kind="adset_pause_check", adset=str(adset_id), ok=ok, status=after.get("status"), effective_status=after.get("effective_status"),
        daily_budget=after.get("daily_budget"), campaign_status=(after.get("campaign") or {}).get("status"))
    if not ok:
        raise Stop(f"после записи группа {adset_id}: status {after.get('status')}, бюджет {after.get('daily_budget')}, "
                   f"кампания {(after.get('campaign') or {}).get('status')} — ждал PAUSED без других изменений")
    print(json.dumps({"группа_на_паузе": adset_id, "имя": after.get("name"), "status": after.get("status"),
                      "effective_status": after.get("effective_status"), "бюджет_не_тронут": after.get("daily_budget"),
                      "кампания": f"{camp.get('name')} {camp.get('status')} — не тронута"}, ensure_ascii=False, indent=1))


def cmd_addsets(cfg, plan, campaign_id, check_only, validate_only=False):
    """Добавить группы и объявления плана в СУЩЕСТВУЮЩУЮ кампанию (любой статус). Группы — PAUSED.
    Карусель — да: картинки карточек грузятся один раз, креатив читается обратно до объявления."""
    if not campaign_id or not str(campaign_id).isdigit():
        raise Stop("addsets: нужен --campaign <ID кампании> (только цифры)")
    camps = plan.get("campaigns", [])
    if len(camps) != 1 or str(camps[0].get("existing_id")) != str(campaign_id):
        raise Stop(f"addsets: в плане ровно одна кампания с existing_id = {campaign_id} (сейчас {[c.get('existing_id') for c in camps]})")
    c = camps[0]
    wa_validate = validate_only and all(is_whatsapp(a) for a in c["adsets"])  # файлы не грузятся, ничего не создаётся — «да» не нужно
    if not check_only and not wa_validate and not approved(plan):
        raise Stop("в плане нет «да» владельца (approved_by_owner) — не создаю")
    tok = _mi.token(cfg["token_var"])
    acc, _ = call(cfg, "GET", f"act_{cfg['act']}", {"fields": "currency,account_status,timezone_name"}, tok)
    ensure_tz(cfg, tok, acc.get("timezone_name"))
    plan = apply_start_next_day(cfg, plan)
    for a in c["adsets"]:
        if not a.get("start_time"):
            raise Stop(f"addsets: у группы «{a['name']}» нет start_time — в работающую кампанию только с расписанием (или включи start_next_day в конфиге)")
        for ad in a["ads"]:
            if ad.get("source_instagram_media_id"):
                raise Stop(f"addsets: «{ad['name']}» — существующую публикацию этим режимом не собираю, только live")
            if ad.get("video_feed"):
                raise Stop(f"addsets: «{ad['name']}» — два формата в одном объявлении этим режимом не собираю (только картинка/видео)")
    work_hours_check(cfg)
    if acc["account_status"] != 1:
        raise Stop(f"кабинет не активен (статус {acc['account_status']}) — стоп, нужен владелец")
    off = money_offset(acc["currency"])
    errs, warn, stats = check_plan(cfg, plan, active_daily_usd(cfg, tok, off))
    if errs:
        raise Stop("план не прошёл проверку: " + "; ".join(errs))
    name_errs, name_rows = resolve_names(cfg, tok, plan)
    print("Коды по Meta:\n  " + "\n  ".join(name_rows))
    if name_errs:
        raise Stop("коды не совпали с названиями: " + "; ".join(name_errs))
    camp0, sets0, ads0 = snapshot(cfg, tok, str(campaign_id))
    if str(camp0.get("account_id")) != str(cfg["act"]) or camp0.get("name") != c["name"] or not str(camp0.get("name", "")).startswith(cfg["prefix"]):
        raise Stop(f"кампания {campaign_id}: «{camp0.get('name')}» / кабинет {camp0.get('account_id')} не совпадает с планом «{c['name']}» / act_{cfg['act']}")
    if c.get("existing_housing") and "HOUSING" not in (camp0.get("special_ad_categories") or []):
        raise Stop(f"кампания {campaign_id}: в плане existing_housing, в Meta категории {camp0.get('special_ad_categories')} — стоп")
    dup = {a["name"] for a in c["adsets"]} & {s["name"] for s in sets0.values()}
    if dup:
        raise Stop(f"в кампании уже есть группы с такими именами: {sorted(dup)} — дубль не создаю")
    print(f"Кампания «{camp0['name']}» {campaign_id}: статус {camp0['status']} (не трогаю), групп сейчас {len(sets0)}, объявлений {len(ads0)}")
    if check_only:
        log(cfg, kind="addsets_check", plan=plan.get("name"), campaign=str(campaign_id), campaign_status=camp0["status"], old_adsets=len(sets0), stats=stats)
        print(json.dumps({"проверка": "ок, в Meta ничего не создано", "план": stats, "предупреждения": warn}, ensure_ascii=False, indent=1))
        return
    act = f"act_{cfg['act']}"
    if validate_only:
        # Direct в работающую кампанию: Meta проверяет группу и креатив, группа/креатив/объявление не создаются;
        # видео и обложка Direct грузятся по-настоящему (в кабинет, без показа). Плюс размер аудитории — чтение.
        for a in c["adsets"]:
            cents = int(round(float(a["daily_budget_usd"]) * off))
            spec = adset_params(cfg, a, str(campaign_id), cents, "PAUSED")
            write(cfg, tok, f"{act}/adsets", {**spec, "execution_options": ["validate_only"]}, "validate", a["name"])
            print(f"✓ Meta приняла группу «{a['name']}» (validate_only, ничего не создано)")
            try:
                est, _ = call(cfg, "GET", f"{act}/reachestimate", {"targeting_spec": spec["targeting"]}, tok)
                print("Размер аудитории по Meta: " + json.dumps(est.get("data"), ensure_ascii=False))
            except Stop as e:
                print(f"Размер аудитории Meta не отдала: {e}")
            if is_direct(a):
                for ad in a["ads"]:
                    pic = ad.get("thumb") if ad.get("video") else ad["image"]
                    up = write(cfg, tok, f"{act}/adimages", {"bytes": base64.b64encode((OFFICE / pic).read_bytes()).decode()}, "image", pic)
                    h_img = next(iter(up["images"].values()))["hash"]
                    video_id = upload_video(cfg, tok, act, ad["video"]) if ad.get("video") else None
                    cr = creative_params(cfg, plan, ad, None, h_img, video_id, direct=True)
                    write(cfg, tok, f"{act}/adcreatives", {**cr, "execution_options": ["validate_only"]}, "validate", ad["name"])
                    print(f"✓ Meta приняла креатив Direct «{ad['name']}» (validate_only, креатив не создан)")
            if is_whatsapp(a):
                h_img = account_image_hash(cfg, tok, act)
                for ad in a["ads"]:
                    vid0 = account_video_id(cfg, tok, act) if ad.get("video") else None
                    write(cfg, tok, f"{act}/adcreatives", {**whatsapp_creative_params(cfg, plan, ad, h_img, vid0), "execution_options": ["validate_only"]}, "validate", ad["name"])
                    print(f"✓ Meta приняла креатив WhatsApp «{ad['name']}» (validate_only, креатив не создан, картинка кабинета)")
        print(json.dumps({"проверка_Meta": "ок, группы и объявления не созданы", "план": stats, "предупреждения": warn}, ensure_ascii=False, indent=1))
        return
    log(cfg, kind="start", mode="addsets", plan=plan.get("name"), campaign=str(campaign_id), campaign_status=camp0["status"],
        old_adsets=sorted(sets0), stats=stats)
    created, images = [], {}
    for a in c["adsets"]:
        cents = int(round(float(a["daily_budget_usd"]) * off))
        form = a.get("lead_form_id")
        aset = write(cfg, tok, f"{act}/adsets", adset_params(cfg, a, str(campaign_id), cents, "PAUSED"), "adset", a["name"])
        verify(cfg, tok, aset["id"], cents, expect="PAUSED")
        created.append(("adset", aset["id"], a["name"]))
        verify_dsa(cfg, tok, aset["id"], a)
        if is_whatsapp(a):
            verify_whatsapp_adset(cfg, tok, aset["id"], a)
        pause(cfg)
        for ad in a["ads"]:
            if ad.get("carousel"):
                hashes = []
                for card in ad["carousel"]:
                    if card["image"] not in images:
                        up = write(cfg, tok, f"{act}/adimages", {"bytes": base64.b64encode((OFFICE / card["image"]).read_bytes()).decode()}, "image", card["image"])
                        images[card["image"]] = next(iter(up["images"].values()))["hash"]
                        pause(cfg)
                    hashes.append(images[card["image"]])
                cr = write(cfg, tok, f"{act}/adcreatives", carousel_creative_params(cfg, plan, ad, form, hashes, whatsapp=is_whatsapp(a)), "creative", ad["name"])
                verify_carousel(cfg, tok, cr["id"], ad, form)
                if is_whatsapp(a):
                    verify_whatsapp_creative(cfg, tok, cr["id"], ad)
                pause(cfg)
                adr = write(cfg, tok, f"{act}/ads", {"name": ad["name"], "adset_id": aset["id"], "creative": {"creative_id": cr["id"]}, "status": "ACTIVE"}, "ad", ad["name"])
                verify(cfg, tok, adr["id"], expect="ACTIVE")
                created.append(("ad", adr["id"], ad["name"]))
                pause(cfg)
                continue
            pic = ad.get("thumb") if ad.get("video") else ad["image"]
            if pic not in images:
                up = write(cfg, tok, f"{act}/adimages", {"bytes": base64.b64encode((OFFICE / pic).read_bytes()).decode()}, "image", pic)
                images[pic] = next(iter(up["images"].values()))["hash"]
                pause(cfg)
            video_id = upload_video(cfg, tok, act, ad["video"]) if ad.get("video") else None
            cr = write(cfg, tok, f"{act}/adcreatives", creative_params(cfg, plan, ad, form, images[pic], video_id, direct=is_direct(a), whatsapp=is_whatsapp(a)), "creative", ad["name"])
            if is_whatsapp(a):
                verify_whatsapp_creative(cfg, tok, cr["id"], ad)
            pause(cfg)
            adr = write(cfg, tok, f"{act}/ads", {"name": ad["name"], "adset_id": aset["id"], "creative": {"creative_id": cr["id"]}, "status": "ACTIVE"}, "ad", ad["name"])
            verify(cfg, tok, adr["id"], expect="ACTIVE")
            created.append(("ad", adr["id"], ad["name"]))
            pause(cfg)
        verify(cfg, tok, aset["id"], cents, expect="PAUSED")  # группа после объявлений — всё ещё на паузе
    # сверка «после»: кампания как была, старые группы и их объявления как были, новые группы PAUSED
    camp1, sets1, ads1 = snapshot(cfg, tok, str(campaign_id))
    diffs = [f"кампания.{k}: {camp0.get(k)} → {camp1.get(k)}" for k in CAMP_KEEP if camp0.get(k) != camp1.get(k)]
    for sid, s0 in sets0.items():
        s1 = sets1.get(sid)
        if not s1:
            diffs.append(f"старая группа {sid} пропала")
            continue
        diffs += [f"старая группа {s0['name']}.{k}: {s0.get(k)} → {s1.get(k)}" for k in ADSET_FIELDS.split(",") if k != "updated_time" and s0.get(k) != s1.get(k)]
        if s0.get("updated_time") != s1.get("updated_time"):
            diffs.append(f"старая группа {s0['name']}: updated_time {s0.get('updated_time')} → {s1.get('updated_time')}")
    for aid, x0 in ads0.items():
        x1 = ads1.get(aid) or {}
        if x0.get("status") != x1.get("status"):
            diffs.append(f"старое объявление {aid}: статус {x0.get('status')} → {x1.get('status')}")
    new_ids = {i for k, i, _ in created if k == "adset"}
    for sid in new_ids:
        if (sets1.get(sid) or {}).get("status") != "PAUSED":
            diffs.append(f"новая группа {sid}: статус {(sets1.get(sid) or {}).get('status')} вместо PAUSED")
    extra = set(sets1) - set(sets0) - new_ids
    if extra:
        diffs.append(f"в кампании появились группы не из этого запуска: {sorted(extra)}")
    log(cfg, kind="addsets_verify", campaign=str(campaign_id), ok=not diffs, diffs=diffs, campaign_status=camp1["status"],
        old_adsets_unchanged=len(sets0) if not diffs else None)
    if diffs:
        raise Stop("после записи не сошлось: " + "; ".join(diffs))
    log(cfg, kind="done", mode="addsets", plan=plan.get("name"), created=created)
    print(json.dumps({"добавлено_группы_PAUSED": created, "кампания": f"{camp1['name']} {campaign_id} статус {camp1['status']} — не тронута",
                      "старые_группы": f"{len(sets0)} шт. — без изменений", "предупреждения": warn}, ensure_ascii=False, indent=1))


# ---------- пауза группы / объявления ----------
# Только status=PAUSED для adset или ad. Включать, удалять, менять бюджет/таргетинг, трогать кампании — нельзя.
def cmd_pause(cfg, kind, ids, why, dry):
    if kind not in ("adset", "ad"):
        raise Stop("pause: только adset или ad (кампании этой командой не трогаем)")
    if not str(why or "").strip():
        raise Stop("pause: нужен --why «<решение владельца, дата>» — без него не выключаю")
    if not ids or not all(str(i).isdigit() for i in ids):
        raise Stop("pause: нужны ID (только цифры)")
    tok = _mi.token(cfg["token_var"])
    ensure_tz(cfg, tok)
    fields = "name,account_id,status,effective_status,daily_budget,campaign{id,name,status}" + (",adset{id,name}" if kind == "ad" else "")
    objs = []
    for i in ids:  # всё читаем и сверяем ДО первой записи: чужой объект в списке → стоп, ничего не выключено
        o, _ = call(cfg, "GET", str(i), {"fields": fields}, tok)
        camp = o.get("campaign") or {}
        if str(o.get("account_id")) != str(cfg["act"]):
            raise Stop(f"pause: {i} не из кабинета act_{cfg['act']} — не трогаю")
        if not str(camp.get("name", "")).startswith(cfg["prefix"]) or (kind == "adset" and not str(o.get("name", "")).startswith(cfg["prefix"])):
            raise Stop(f"pause: {i} «{o.get('name')}» в кампании «{camp.get('name')}» — не наш объект ({cfg['prefix']}), не трогаю")
        objs.append(o)
    rows = [f"{kind} {o['id']} «{o['name']}» статус {o['status']} ({o.get('effective_status')}), кампания «{o['campaign']['name']}» {o['campaign'].get('status')}"
            + (f", бюджет ${int(o['daily_budget']) / 100:.2f}" if o.get("daily_budget") else "") for o in objs]
    print("Будет выключено (PAUSED):\n  " + "\n  ".join(rows) + f"\nПочему: {why}")
    if dry:
        log(cfg, kind="pause_dry", object=kind, ids=[o["id"] for o in objs], why=why)
        print("--dry: ничего не записано")
        return
    log(cfg, kind="start", mode="pause", object=kind, ids=[o["id"] for o in objs], why=why)
    done = []
    for n, o in enumerate(objs):
        if o["status"] == "PAUSED":
            log(cfg, kind="pause_skip", object=kind, id=o["id"], reason="уже PAUSED")
            print(f"• {o['id']} уже PAUSED — пропускаю")
            continue
        write(cfg, tok, o["id"], {"status": "PAUSED"}, f"pause_{kind}", o["name"])
        verify(cfg, tok, o["id"], expect="PAUSED")  # чтение обратно: не PAUSED → стоп
        done.append(o["id"])
        print(f"✓ {o['id']} «{o['name']}» → PAUSED (прочитано обратно)")
        if n < len(objs) - 1:
            pause(cfg)
    log(cfg, kind="done", mode="pause", object=kind, paused=done, why=why)


# ---------- объявления в существующую группу (группа создана, объявления не успели — без дубля группы) ----------
def cmd_ads(cfg, plan, adset_id, check_only):
    """Добавить объявления плана в СУЩЕСТВУЮЩУЮ нашу группу (приставка конфига, этот кабинет, кампания на паузе). Группу и кампанию не меняет.
    В плане ровно одна кампания с existing_id и одна группа с existing_adset_id = --adset; настройки группы в плане — как в кабинете."""
    if any(ad.get("carousel") for c0 in plan.get("campaigns", []) for a0 in c0.get("adsets", []) for ad in a0.get("ads", [])):
        raise Stop("карусель пока собирается только командой live (новая кампания на паузе)")
    if not adset_id or not str(adset_id).isdigit():
        raise Stop("ads: нужен --adset <ID группы> (только цифры)")
    camps = plan.get("campaigns", [])
    if len(camps) != 1 or not camps[0].get("existing_id") or len(camps[0].get("adsets", [])) != 1 \
            or str(camps[0]["adsets"][0].get("existing_adset_id")) != str(adset_id):
        raise Stop(f"ads: в плане одна кампания с existing_id и одна группа с existing_adset_id = {adset_id}")
    c, a = camps[0], camps[0]["adsets"][0]
    for ad in a["ads"]:
        if ad.get("video_feed") or ad.get("source_instagram_media_id"):
            raise Stop(f"ads: «{ad['name']}» — только картинка или видео")
    if not check_only and not approved(plan):
        raise Stop("в плане нет «да» владельца (approved_by_owner) — не создаю")
    tok = _mi.token(cfg["token_var"])
    acc, _ = call(cfg, "GET", f"act_{cfg['act']}", {"fields": "currency,account_status,timezone_name"}, tok)
    ensure_tz(cfg, tok, acc.get("timezone_name"))
    if acc["account_status"] != 1:
        raise Stop(f"кабинет не активен (статус {acc['account_status']}) — стоп, нужен владелец")
    off = money_offset(acc["currency"])
    errs, warn, stats = check_plan(cfg, plan, active_daily_usd(cfg, tok, off))
    if errs:
        raise Stop("план не прошёл проверку: " + "; ".join(errs))
    aset, _ = call(cfg, "GET", str(adset_id), {"fields": "name,account_id,status,daily_budget,destination_type,campaign{id,name,status}"}, tok)
    camp = aset.get("campaign") or {}
    if str(aset.get("account_id")) != str(cfg["act"]) or aset.get("name") != a["name"] or not str(aset.get("name", "")).startswith(cfg["prefix"]):
        raise Stop(f"группа {adset_id}: «{aset.get('name')}» / кабинет {aset.get('account_id')} не совпадает с планом «{a['name']}»")
    if str(camp.get("id")) != str(c["existing_id"]) or camp.get("name") != c["name"]:
        raise Stop(f"группа {adset_id} в кампании {camp.get('id')} «{camp.get('name')}», в плане {c['existing_id']} «{c['name']}»")
    if camp.get("status") != "PAUSED":
        raise Stop(f"кампания {camp.get('id')} не на паузе ({camp.get('status')}) — объявления не добавляю")
    if is_whatsapp(a) and aset.get("destination_type") != "WHATSAPP":
        raise Stop(f"группа {adset_id}: destination {aset.get('destination_type')}, в плане WHATSAPP")
    have, _ = call(cfg, "GET", f"{adset_id}/ads", {"fields": "id,name,status", "limit": 50}, tok)
    old = have.get("data", [])
    if len(old) + len(a["ads"]) > cfg["limits"].get("ads_per_adset", 2):
        raise Stop(f"в группе уже {len(old)} объявл. + {len(a['ads'])} > {cfg['limits'].get('ads_per_adset', 2)}")
    dup = {x["name"] for x in old} & {ad["name"] for ad in a["ads"]}
    if dup:
        raise Stop(f"в группе уже есть объявления {sorted(dup)} — дубль не создаю")
    print(f"Группа «{aset['name']}» {adset_id}: статус {aset['status']} (не трогаю), кампания {camp['id']} {camp['status']}, объявлений сейчас {len(old)}")
    if check_only:
        print(json.dumps({"проверка": "ок, в Meta ничего не создано", "предупреждения": warn}, ensure_ascii=False, indent=1))
        return
    act = f"act_{cfg['act']}"
    log(cfg, kind="start", mode="ads", plan=plan.get("name"), adset=str(adset_id))
    created, images = [], {}
    for ad in a["ads"]:
        pic = ad.get("thumb") if ad.get("video") else ad["image"]
        if pic not in images:
            up = write(cfg, tok, f"{act}/adimages", {"bytes": base64.b64encode((OFFICE / pic).read_bytes()).decode()}, "image", pic)
            images[pic] = next(iter(up["images"].values()))["hash"]
            pause(cfg)
        video_id = upload_video(cfg, tok, act, ad["video"]) if ad.get("video") else None
        cr = write(cfg, tok, f"{act}/adcreatives", creative_params(cfg, plan, ad, a.get("lead_form_id"), images[pic], video_id,
                                                                   direct=is_direct(a), whatsapp=is_whatsapp(a)), "creative", ad["name"])
        if is_whatsapp(a):
            verify_whatsapp_creative(cfg, tok, cr["id"], ad)
        pause(cfg)
        adr = write(cfg, tok, f"{act}/ads", {"name": ad["name"], "adset_id": str(adset_id), "creative": {"creative_id": cr["id"]}, "status": "ACTIVE"}, "ad", ad["name"])
        verify(cfg, tok, adr["id"], expect="ACTIVE")
        created.append(("ad", adr["id"], ad["name"]))
        pause(cfg)
    after, _ = call(cfg, "GET", str(adset_id), {"fields": "status,daily_budget,campaign{status}"}, tok)
    if after.get("status") != aset.get("status") or after.get("daily_budget") != aset.get("daily_budget") or (after.get("campaign") or {}).get("status") != "PAUSED":
        raise Stop(f"после записи группа/кампания изменились: {after} — стоп, нужен владелец")
    log(cfg, kind="done", mode="ads", plan=plan.get("name"), created=created)
    print(json.dumps({"добавлено_объявлений": created, "группа": f"{aset['name']} {adset_id} статус {after['status']} — не тронута",
                      "кампания": "PAUSED", "предупреждения": warn}, ensure_ascii=False, indent=1))


# ---------- подключение: что видит ключ (ids) и сборка конфига (init) — без конфига ----------
def ro_get(path, params, tok):
    """Только чтение без конфига и журнала: один GET, без повторов. Ошибка → Stop с текстом Meta."""
    q = urllib.parse.urlencode({**{k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items()}, "access_token": tok})
    try:
        with urllib.request.urlopen(f"{API}/{path}?{q}", timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        err = json.loads(e.read() or b"{}").get("error", {})
        raise Stop(f"Meta {err.get('code')}/{err.get('error_subcode')}: {err.get('error_user_msg') or err.get('message')}")
    except urllib.error.URLError as e:
        raise Stop(f"нет связи с Meta: {e.reason}")


def try_get(path, params, tok):
    """То же, но ошибка не стоп: возвращает (данные, None) или (None, текст ошибки)."""
    try:
        return ro_get(path, params, tok), None
    except Stop as e:
        return None, str(e)


def flag(args, name):
    """Значение флага --name <значение> (или --name=значение); нет — None."""
    for j, x in enumerate(args):
        if x == name and j + 1 < len(args):
            return args[j + 1]
        if x.startswith(name + "="):
            return x.split("=", 1)[1]
    return None


ACC_STATUS = {1: "активен", 2: "отключён", 3: "есть долг (unsettled)", 7: "на проверке", 9: "льготный период", 100: "закрывается", 101: "закрыт"}


def cmd_ids(var):
    """Только чтение: всё, что видит ключ, — чтобы собрать конфиг. Ничего не пишет, журнал не ведёт."""
    if not var:
        raise Stop("ids: нужен --token-var <ИМЯ_ПЕРЕМЕННОЙ_В_.env>, напр. --token-var META_TOKEN")
    tok = _mi.token(var)
    out = {}
    me, err = try_get("me", {"fields": "id,name"}, tok)
    out["кто_ключ"] = me or f"нет: {err}"
    perms, err = try_get("me/permissions", {}, tok)
    out["права"] = ({"granted": sorted(p["permission"] for p in perms.get("data", []) if p.get("status") == "granted"),
                     "declined": sorted(p["permission"] for p in perms.get("data", []) if p.get("status") != "granted")}
                    if perms else f"нет: {err}")
    accs, err = try_get("me/adaccounts", {"fields": "account_id,name,account_status,currency,timezone_name,spend_cap,funding_source_details", "limit": 200}, tok)
    rows = []
    for a in (accs or {}).get("data", []):
        px, perr = try_get(f"act_{a['account_id']}/adspixels", {"fields": "id,name,last_fired_time", "limit": 50}, tok)
        ig, ierr = try_get(f"act_{a['account_id']}/connected_instagram_accounts", {"fields": "id,username", "limit": 50}, tok)
        rows.append({"act": a["account_id"], "имя": a.get("name"), "статус": ACC_STATUS.get(a.get("account_status"), a.get("account_status")),
                     "валюта": a.get("currency"), "пояс_tz": a.get("timezone_name"),
                     "способ_оплаты": "есть" if a.get("funding_source_details") else "не видно (нет или ключу не отдали)",
                     "лимит_расходов_spend_cap": None if a.get("spend_cap") in (None, "0") else a.get("spend_cap"),
                     "пиксели_наборы_данных": (px or {}).get("data", f"нет: {perr}") if px is not None else f"нет: {perr}",
                     "instagram_кабинета": (ig or {}).get("data") if ig is not None else f"нет: {ierr}"})
    out["рекламные_кабинеты"] = rows if accs is not None else f"нет: {err}"
    pages, err = try_get("me/accounts", {"fields": "id,name,access_token,instagram_business_account{id,username}", "limit": 200}, tok)
    prow = []
    for p in (pages or {}).get("data", []):
        row = {"page_id": p["id"], "имя": p.get("name"), "instagram": []}
        if p.get("instagram_business_account"):
            row["instagram"].append({**p["instagram_business_account"], "откуда": "instagram_business_account"})
        pb, _ = try_get(f"{p['id']}/page_backed_instagram_accounts", {"fields": "id,username"}, p.get("access_token") or tok)
        row["instagram"] += [{**x, "откуда": "page_backed_instagram_accounts"} for x in (pb or {}).get("data", [])]
        prow.append(row)
    out["страницы"] = prow if pages is not None else f"нет: {err}"
    biz, err = try_get("me/businesses", {"fields": "id,name", "limit": 50}, tok)
    brow = []
    for b in (biz or {}).get("data", []):
        row = {"business_id": b["id"], "имя": b.get("name")}
        for edge in ("owned_instagram_accounts", "client_instagram_assets", "instagram_accounts"):
            d, e = try_get(f"{b['id']}/{edge}", {"fields": "id,username", "limit": 50}, tok)
            row[edge] = d.get("data") if d is not None else f"нет: {e}"
        brow.append(row)
    out["бизнес_портфели"] = brow if biz is not None else f"нет: {err}"
    out["подсказка"] = ("для конфига: act — «act» кабинета, page_id — страница, instagram_user_id — id Instagram (любой источник), "
                        "pixel_id — пиксель кабинета; дальше: meta-launch.py init --token-var ... --act ... --page ... --prefix ... --ceiling ... --out ...")
    print(json.dumps(out, ensure_ascii=False, indent=1))


def cmd_init(args):
    """Собрать конфиг из шаблона (tz — из кабинета). Существующий файл не перезаписывает. В Meta ничего не пишет."""
    var, act, page = flag(args, "--token-var"), (flag(args, "--act") or "").removeprefix("act_"), flag(args, "--page")
    ig, pixel, prefix, ceiling, out = flag(args, "--ig"), flag(args, "--pixel"), flag(args, "--prefix"), flag(args, "--ceiling"), flag(args, "--out")
    miss = [n for n, v in (("--token-var", var), ("--act", act), ("--page", page), ("--prefix", prefix), ("--ceiling", ceiling), ("--out", out)) if not v]
    if miss:
        raise Stop("init: не хватает " + ", ".join(miss) + ". Пример: init --token-var META_TOKEN --act 1234567890 --page 1122334455 "
                   "--prefix MY_ --ceiling 30 --out projects/my-client/targetolog/config.json")
    if not act.isdigit() or not str(page).isdigit() or (ig and not ig.isdigit()) or (pixel and not pixel.isdigit()):
        raise Stop("init: --act, --page, --ig, --pixel — только цифры (act без «act_»)")
    if not (prefix.isascii() and prefix.replace("_", "").isalnum()):
        raise Stop("init: --prefix — латиница/цифры/_, напр. MY_")
    try:
        ceiling_usd = float(ceiling)
        assert ceiling_usd > 0
    except (ValueError, AssertionError):
        raise Stop("init: --ceiling — число долларов в день, напр. 30")
    dest = OFFICE / out
    if dest.exists():
        raise Stop(f"init: {out} уже есть — не перезаписываю (правь его руками или укажи другой --out)")
    tok = _mi.token(var)
    acc = ro_get(f"act_{act}", {"fields": "name,timezone_name,currency,account_status"}, tok)
    pg, perr = try_get(page, {"fields": "name"}, tok)
    tpl = load(OFFICE / "team" / "agents" / "targetolog" / "templates" / "config.example.json")
    cfg = {k: v for k, v in tpl.items() if not k.startswith("_")}
    parts = Path(out).parts
    cfg.update({"client": parts[1] if len(parts) > 2 and parts[0] == "projects" else Path(out).parent.name,
                "act": act, "token_var": var, "prefix": prefix, "page_id": str(page), "instagram_user_id": ig or None,
                "pixel_id": pixel or None, "daily_ceiling_usd": ceiling_usd if not ceiling_usd.is_integer() else int(ceiling_usd),
                "tz": acc.get("timezone_name"), "journal": str(Path(out).parent / "journal.jsonl")})
    cfg = {"_что": f"Конфиг охранника, собран командой init {dt.date.today().isoformat()}. Замки меняет только владелец. "
                   "Пояснения к полям — team/agents/targetolog/templates/config.example.json", **cfg}
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"конфиг_создан": out, "кабинет": f"{acc.get('name')} act_{act}, валюта {acc.get('currency')}, статус "
                      f"{ACC_STATUS.get(acc.get('account_status'), acc.get('account_status'))}",
                      "tz_из_кабинета": acc.get("timezone_name"), "страница": (pg or {}).get("name") or f"⚠ не прочиталась: {perr}",
                      "дальше": f"python3 scripts/meta-launch.py status {out}"}, ensure_ascii=False, indent=1))
    if not pixel:
        print("… pixel_id не задан — группы на сайт (без лид-формы) check не соберёт, пока не впишешь пиксель")


def main():
    if sys.argv[1:2] in (["ids"], ["init"]):  # подключение: конфига ещё нет, журнал не ведётся
        try:
            cmd_ids(flag(sys.argv[2:], "--token-var")) if sys.argv[1] == "ids" else cmd_init(sys.argv[2:])
        except Stop as e:
            print(f"⛔ СТОП: {e}")
            sys.exit(2)
        return
    if len(sys.argv) < 3 or sys.argv[1] not in ("status", "check", "live", "geo", "names", "forms", "perms", "form", "newform", "addsets", "show", "devices", "wa", "ads", "pauseset", "pause"):
        sys.exit(__doc__)
    cfg = load(sys.argv[2])
    for key in ("act", "token_var", "prefix", "page_id", "journal", "limits", "pace", "work_hours", "daily_ceiling_usd", "url_tags"):
        if key not in cfg:
            sys.exit(f"⛔ в конфиге нет поля «{key}» — сверь с team/agents/targetolog/templates/config.example.json")
    if not str(cfg["prefix"]).strip():
        sys.exit("⛔ в конфиге пустой prefix — приставка имён обязательна (напр. MY_)")
    try:
        if sys.argv[1] == "status":
            cmd_status(cfg)
        elif sys.argv[1] == "forms":
            cmd_forms(cfg)
        elif sys.argv[1] == "perms":
            cmd_perms(cfg)
        elif sys.argv[1] == "wa":
            cmd_wa(cfg)
        elif sys.argv[1] == "form":
            cmd_form(cfg, sys.argv[3])
        elif sys.argv[1] == "newform":
            cmd_newform(cfg, load(sys.argv[3]), "--check" in sys.argv)
        elif sys.argv[1] == "geo":
            cmd_geo(cfg, sys.argv[3], *(sys.argv[4:6]))
        elif sys.argv[1] == "names":
            cmd_names(cfg, load(sys.argv[3]))
        elif sys.argv[1] == "check":
            cmd_check(cfg, apply_verified_advertiser(cfg, load(sys.argv[3])))
        elif sys.argv[1] == "addsets":
            camp_id = sys.argv[sys.argv.index("--campaign") + 1] if "--campaign" in sys.argv[:-1] else None
            cmd_addsets(cfg, apply_verified_advertiser(cfg, load(sys.argv[3])), camp_id, "--check" in sys.argv, "--validate-only" in sys.argv)
        elif sys.argv[1] == "pause":
            args = sys.argv[3:]
            why = args[args.index("--why") + 1] if "--why" in args[:-1] else None
            rest = [x for j, x in enumerate(args) if x not in ("--why", "--dry") and not (j > 0 and args[j - 1] == "--why")]
            cmd_pause(cfg, rest[0] if rest else None, rest[1:], why, "--dry" in args)
        elif sys.argv[1] == "ads":
            adset_id = sys.argv[sys.argv.index("--adset") + 1] if "--adset" in sys.argv[:-1] else None
            cmd_ads(cfg, apply_verified_advertiser(cfg, load(sys.argv[3])), adset_id, "--check" in sys.argv)
        elif sys.argv[1] == "show":
            cmd_show(cfg, sys.argv[3])
        elif sys.argv[1] == "pauseset":
            reason = sys.argv[sys.argv.index("--reason") + 1] if "--reason" in sys.argv[:-1] else None
            cmd_pauseset(cfg, sys.argv[3] if len(sys.argv) > 3 else None, reason)
        elif sys.argv[1] == "devices":
            cmd_devices(cfg, *(sys.argv[3:4]))
        else:
            cmd_live(cfg, load(sys.argv[3]), "--validate-only" in sys.argv)
    except Stop as e:
        log(cfg, kind="stop", reason=str(e))
        print(f"⛔ СТОП: {e}\nНичего не повторяю. Что создано до стопа — в журнале {cfg.get('journal')}. Нужен владелец.")
        sys.exit(2)


if __name__ == "__main__":
    main()
