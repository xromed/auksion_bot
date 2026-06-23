import requests
import json
import os
import re
import time
import argparse
import schedule
from datetime import datetime, date
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

import gspread
from google.oauth2.service_account import Credentials

# ============================================================
#  НАСТРОЙКИ
# ============================================================
GOOGLE_CREDS_FILE = os.environ.get("GOOGLE_CREDS_FILE", "google_creds.json")

# В GitHub Actions (CI=true) пропускаем запрос координат — слишком долго для 1000+ лотов
SKIP_COORDS = os.environ.get("CI", "").lower() == "true"
GOOGLE_SHEET_NAME = "E-Auksion Лоты"
REPORT_TIME       = "10:00"
MAX_PRICE         = 1_000_000_000
# ============================================================

DATA_DIR     = Path("data")
LOTS_FILE    = DATA_DIR / "lots.json"
HISTORY_FILE = DATA_DIR / "history.json"
SEEN_FILE    = "seen_lots.json"  # оставляем для совместимости

API_URL   = "https://e-auksion.uz/api/front/lots"
CBU_URL   = "https://cbu.uz/oz/arkhiv-kursov-valyut/json/USD/"

GROUPS = {
    1:  "🏠 Недвижимость",
    2:  "🚗 Автотранспорт",
    15: "⚖️ Банкротство",
}
REGION_ID = 1
PER_PAGE  = 50

# Статусы активные / закрытые
ACTIVE_STATUSES    = {1, 2, 6, 7, 32, 50}
CLOSED_STATUSES    = {3, 4, 10, 30, 40}

STATUS = {
    1:  "Новый",
    2:  "Активный",
    3:  "Завершён",
    4:  "Отменён",
    5:  "Приостановлен",
    6:  "Ожидает",
    7:  "На рассмотрении",
    10: "Завершён",
    30: "Отменён",
    31: "Приостановлен",
    32: "Ожидает",
    40: "Завершён",
    50: "Активный",
}

# category_id для вкладки Банкротство
BANKRUPTCY_ALLOWED_CATEGORIES = {
    1, 2, 3, 4, 5, 6, 7, 8, 11, 12, 13, 14, 15, 16,
}

COLOR_GREEN  = {"red": 0.71, "green": 0.96, "blue": 0.71}
COLOR_WHITE  = {"red": 1.0,  "green": 1.0,  "blue": 1.0}
COLOR_GRAY   = {"red": 0.85, "green": 0.85, "blue": 0.85}
COLOR_RED    = {"red": 0.96, "green": 0.49, "blue": 0.49}
COLOR_YELLOW = {"red": 1.0,  "green": 0.93, "blue": 0.53}
COLOR_ACTIVE = {"red": 0.71, "green": 0.96, "blue": 0.71}
COLOR_DUPE   = {"red": 0.95, "green": 0.95, "blue": 0.80}  # дублирующие лоты

STATUS_COLORS = {
    "Активный":      COLOR_ACTIVE,
    "Новый":         COLOR_ACTIVE,
    "Завершён":      COLOR_RED,
    "Отменён":       COLOR_RED,
    "Приостановлен": COLOR_YELLOW,
    "Ожидает":       COLOR_YELLOW,
}

HEADERS_REALTY = [
    "ID лота", "Тип недвижимости", "Название", "Адрес", "Ссылка на карту",
    "Статус", "Тип аукциона",
    "Нач. цена (сум)", "Нач. цена ($)",
    "Оцен. цена (сум)", "Оцен. цена ($)",
    "Залог (сум)", "Залог %",
    "Дата аукциона", "Дедлайн заявки",
    "Кол-во заявок", "Просмотры",
    "Ссылка на лот", "Добавлен",
]
HEADERS_AUTO = [
    "ID лота", "Марка/Модель", "Название (оригинал)", "Адрес", "Ссылка на карту",
    "Статус", "Тип аукциона",
    "Нач. цена (сум)", "Нач. цена ($)",
    "Оцен. цена (сум)", "Оцен. цена ($)",
    "Залог (сум)", "Залог %",
    "Дата аукциона", "Дедлайн заявки",
    "Кол-во заявок", "Просмотры",
    "Ссылка на лот", "Добавлен",
]
HEADERS_BANKRUPTCY = [
    "ID лота", "Тип", "Название", "Адрес", "Ссылка на карту",
    "Статус", "Тип аукциона",
    "Нач. цена (сум)", "Нач. цена ($)",
    "Оцен. цена (сум)", "Оцен. цена ($)",
    "Залог (сум)", "Залог %",
    "Дата аукциона", "Дедлайн заявки",
    "Кол-во заявок", "Просмотры",
    "Ссылка на лот", "Добавлен",
]


# ──────────────────────────────────────────────
#  КЛАССИФИКАЦИЯ НЕДВИЖИМОСТИ
# ──────────────────────────────────────────────

REALTY_KEYWORDS = [
    (["xonadon", "квартира", "ko`p qavatli", "ko'p qavatli"], "Квартира"),
    (["uy", "hovli", "turar-joy", "turar joy", "жилой дом", "cottage", "котедж"], "Жилой дом"),
    (["do'kon", "do`kon", "магазин", "savdo"], "Магазин"),
    (["noturar", "нежилое", "офис", "ofis", "bino", "здание"], "Нежилое помещение"),
    (["yer uchastkasi", "yer", "земельный", "участок"], "Земельный участок"),
    (["omborxona", "склад", "ombor"], "Склад"),
    (["zavod", "завод", "ishlab chiqarish", "производство"], "Производство"),
    (["issiqxona", "теплица"], "Теплица"),
    (["restoran", "ресторан", "cafe", "кафе"], "Общепит"),
    (["avtoturargoh", "парковка", "garaj", "гараж"], "Гараж/Парковка"),
]

def classify_realty(name: str) -> str:
    name_lower = name.lower()
    for keywords, label in REALTY_KEYWORDS:
        if any(kw in name_lower for kw in keywords):
            return label
    return "Другое"


# ──────────────────────────────────────────────
#  НОРМАЛИЗАЦИЯ МАРКИ/МОДЕЛИ АВТО
# ──────────────────────────────────────────────

CAR_BRANDS = [
    "Chevrolet", "Cobalt", "Nexia", "Matiz", "Lacetti", "Spark", "Malibu",
    "Equinox", "Tracker", "Captiva", "Cruze", "Aveo",
    "Daewoo", "Toyota", "Hyundai", "Kia", "BMW", "Mercedes", "Audi",
    "Volkswagen", "Lada", "VAZ", "Nissan", "Honda", "Mitsubishi",
    "Lexus", "Land Rover", "Jeep", "Ford", "Opel", "Peugeot", "Renault",
    "Skoda", "Subaru", "Suzuki", "Mazda", "Isuzu", "Kamaz", "GAZ",
    "ZIL", "UAZ", "Traktor", "Moto", "MMVZ", "Ilon", "BYD",
    "Haval", "Chery", "Geely", "JAC", "FAW", "DFSK", "Masada",
]

def normalize_car_name(name: str) -> str:
    clean = re.sub(r'\b\d{2,4}\b', '', name)
    clean = re.sub(r'\([^)]*\)', '', clean)
    clean = re.sub(r'\b[A-Z0-9]{5,}\b', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    found = []
    name_upper = name.upper()
    for brand in CAR_BRANDS:
        if brand.upper() in name_upper:
            found.append(brand)
    if found:
        return " ".join(dict.fromkeys(found))
    words = clean.split()
    return " ".join(words[:2]) if words else name


# ──────────────────────────────────────────────
#  КООРДИНАТЫ — с retry и без параллелизма
# ──────────────────────────────────────────────

LOT_VIEW_API = "https://e-auksion.uz/api/front/lot-info"

def fetch_lot_coords(lot_id) -> tuple:
    """Запрашивает координаты лота. Возвращает (lat, lng) или (None, None)."""
    for attempt in range(4):
        try:
            r = requests.get(
                LOT_VIEW_API,
                params={"lot_id": lot_id},
                headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120"},
                timeout=10,
            )
            if r.status_code == 429:
                wait = 30 * (attempt + 1)
                print(f"  ⏳ 429 лот {lot_id}, жду {wait}с...")
                time.sleep(wait)
                continue
            if r.status_code == 404:
                return None, None
            r.raise_for_status()
            data = r.json()
            lat = data.get("lat")
            lng = data.get("lng")
            if lat and lng:
                return str(lat), str(lng)
            return None, None
        except requests.exceptions.HTTPError as e:
            if e.response.status_code != 404:
                print(f"  [ОШИБКА] Координаты лота {lot_id}: {e}")
            return None, None
        except Exception as e:
            print(f"  [ОШИБКА] Координаты лота {lot_id}: {e}")
            return None, None
    return None, None


def fetch_coords_bulk(lot_ids: list, skip_if_cancelled: set = None) -> dict:
    """
    Получает координаты последовательно с паузами.
    skip_if_cancelled — set статусов ID лотов которые уже закрыты (не нужны).
    """
    if not lot_ids:
        return {}

    results = {}
    skip_if_cancelled = skip_if_cancelled or set()

    # Фильтруем: не запрашиваем координаты для закрытых лотов
    active_ids = [lid for lid in lot_ids if lid not in skip_if_cancelled]
    skipped = len(lot_ids) - len(active_ids)
    if skipped:
        print(f"  ⏭ Пропускаю координаты для {skipped} закрытых лотов")
    if not active_ids:
        return results

    print(f"  📍 Получаю координаты для {len(active_ids)} лотов (по одному, ~{len(active_ids)*1.5:.0f}с)...")

    for i, lid in enumerate(active_ids):
        results[str(lid)] = fetch_lot_coords(lid)
        # Пауза: каждые 5 запросов немного дольше
        if (i + 1) % 5 == 0:
            time.sleep(2.5)
        else:
            time.sleep(1.2)

    return results


def make_map_link(lat, lng, address: str) -> str:
    if lat and lng:
        return f"https://yandex.uz/maps/?ll={lng},{lat}&z=17&pt={lng},{lat},pm2rdm"
    if address:
        query = requests.utils.quote(address)
        return f"https://yandex.uz/maps/?text={query}"
    return ""


# ──────────────────────────────────────────────
#  КУРС ДОЛЛАРА ЦБ
# ──────────────────────────────────────────────

def get_usd_rate() -> float:
    try:
        r = requests.get(CBU_URL, timeout=10)
        r.raise_for_status()
        rate = float(r.json()[0]["Rate"])
        print(f"  💱 Курс ЦБ: 1 USD = {rate:,.0f} сум")
        return rate
    except Exception as e:
        print(f"  [ОШИБКА] Курс ЦБ: {e}. Резервный курс 12700.")
        return 12700.0

def to_usd(amount, rate: float) -> str:
    try:
        return str(round(float(amount) / rate))
    except:
        return "—"

def format_price(price) -> str:
    try:
        return f"{int(float(price)):,}".replace(",", " ")
    except:
        return str(price)

def lot_url(lot_id) -> str:
    return f"https://e-auksion.uz/lot-view?lot_id={lot_id}"

def get_status(status_id) -> str:
    return STATUS.get(int(status_id) if status_id else 0, f"Статус {status_id}")

def safe_int(val, default=0) -> int:
    """Конвертирует значение в int, убирая '+'  и другие символы (напр. '1+' → 1)."""
    try:
        return int(re.sub(r'[^\d]', '', str(val or default)) or default)
    except:
        return default

def is_closed_status(status_id) -> bool:
    return int(status_id or 0) in CLOSED_STATUSES


# ──────────────────────────────────────────────
#  ДЕДУПЛИКАЦИЯ
# ──────────────────────────────────────────────

def dedup_key(lot: dict) -> str:
    """Ключ для определения дублей: нормализованное название + адрес."""
    name = re.sub(r'\s+', ' ', (lot.get("name") or "").lower().strip())
    addr = re.sub(r'\s+', ' ', (lot.get("full_address") or "").lower().strip())
    return f"{name}||{addr}"


def detect_duplicates(lots: list) -> dict:
    """
    Принимает список лотов одной группы.
    Возвращает {lot_id: True/False} — True если это дубль (старая копия).
    Из дублей оставляем лот с максимальным ID (самый новый).
    """
    groups: dict[str, list] = {}
    for lot in lots:
        key = dedup_key(lot)
        lot_id = str(lot.get("id", ""))
        groups.setdefault(key, []).append(lot_id)

    is_duplicate = {}
    dupe_count = 0
    for key, ids in groups.items():
        if len(ids) > 1:
            # Максимальный ID — новейший лот
            try:
                newest = str(max(ids, key=lambda x: int(x)))
            except:
                newest = ids[-1]
            for lid in ids:
                is_duplicate[lid] = (lid != newest)
                if lid != newest:
                    dupe_count += 1
        else:
            is_duplicate[ids[0]] = False

    if dupe_count:
        print(f"  🔄 Найдено дублей: {dupe_count} (оставляем новейшие)")
    return is_duplicate


# ──────────────────────────────────────────────
#  JSON ХРАНИЛИЩЕ (lots.json + history.json)
# ──────────────────────────────────────────────

def load_lots_data() -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    if LOTS_FILE.exists():
        try:
            return json.loads(LOTS_FILE.read_text("utf-8"))
        except:
            pass
    return {"updated_at": "", "usd_rate": 0, "lots": {}}


def save_lots_data(data: dict):
    DATA_DIR.mkdir(exist_ok=True)
    LOTS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


def load_history() -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    if HISTORY_FILE.exists():
        try:
            return json.loads(HISTORY_FILE.read_text("utf-8"))
        except:
            pass
    return {"daily": {}}


def save_history(history: dict):
    DATA_DIR.mkdir(exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), "utf-8")


def update_history(new_counts: dict):
    """new_counts = {"realty": N, "auto": N, "bankruptcy": N}"""
    today = date.today().isoformat()
    history = load_history()
    history["daily"][today] = {
        "realty":     new_counts.get("realty", 0),
        "auto":       new_counts.get("auto", 0),
        "bankruptcy": new_counts.get("bankruptcy", 0),
        "total":      sum(new_counts.values()),
    }
    save_history(history)


# ──────────────────────────────────────────────
#  ХРАНЕНИЕ seen_lots.json (совместимость)
# ──────────────────────────────────────────────

def load_seen() -> dict:
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_seen(seen: dict):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(seen, f, ensure_ascii=False)


# ──────────────────────────────────────────────
#  ПОЛУЧЕНИЕ ЛОТОВ С API
# ──────────────────────────────────────────────

def fetch_lots(group_id: int) -> list:
    headers = {
        "Content-Type": "application/json",
        "Origin": "https://e-auksion.uz",
        "Referer": "https://e-auksion.uz/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120",
    }
    payload = {
        "sort_type": 1,
        "confiscant_groups_id": group_id,
        "confiscant_categories_id": None,
        "regions_id": REGION_ID,
        "areas_id": None,
        "mahallas_id": None,
        "current_page": 1,
        "per_page": PER_PAGE,
        "address": "",
        "auction_type": 0,
        "bank_id": None,
        "date_from": None,
        "date_to": None,
        "dynamic_filters": [],
        "exec_order_type": 0,
        "filtered_auction_status": 0,
        "finished_auction_status": 0,
        "hashtag": "",
        "is_ownership": -1,
        "is_term_order": -1,
        "lot_number": "",
        "lot_type": 0,
        "orderby_": 0,
        "zz_md5": "0de584bbd778e9e0eab5aa9d74c13f40",
    }
    all_lots = []
    page = 1
    while True:
        payload["current_page"] = page
        try:
            resp = requests.post(API_URL, json=payload, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  [ОШИБКА] API группа {group_id} стр.{page}: {e}")
            break
        all_lots.extend(data.get("rows", []))
        if page >= data.get("totalPages", 1):
            break
        page += 1
        time.sleep(0.5)
    return all_lots


# ──────────────────────────────────────────────
#  GOOGLE SHEETS
# ──────────────────────────────────────────────

def sheets_available() -> bool:
    return os.path.exists(GOOGLE_CREDS_FILE)

def sheets_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(GOOGLE_CREDS_FILE, scopes=scopes)
    return gspread.authorize(creds)


def get_or_create_worksheet(spreadsheet, title: str, headers: list):
    try:
        ws = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=title, rows=2000, cols=len(headers))

    first = ws.cell(1, 1).value
    if first != headers[0]:
        ws.clear()
        ws.append_row(headers)
        ws.format(f"A1:{chr(64+len(headers))}1", {
            "textFormat": {"bold": True},
            "backgroundColor": COLOR_GRAY
        })
        spreadsheet.batch_update({"requests": [{
            "updateSheetProperties": {
                "properties": {
                    "sheetId": ws.id,
                    "gridProperties": {"frozenRowCount": 1}
                },
                "fields": "gridProperties.frozenRowCount"
            }
        }]})
    return ws


def get_spreadsheet():
    client = sheets_client()
    try:
        sh = client.open(GOOGLE_SHEET_NAME)
    except gspread.SpreadsheetNotFound:
        sh = client.create(GOOGLE_SHEET_NAME)
        sh.share(None, perm_type="anyone", role="reader")
    return sh


def get_lot_ids_in_sheet(ws) -> dict:
    try:
        col = ws.col_values(1)
    except:
        return {}
    return {str(v): i for i, v in enumerate(col[1:], start=2) if v}


def update_statuses_in_sheet(ws, lots: list, existing: dict, usd_rate: float):
    if not lots or not existing:
        return
    try:
        headers = ws.row_values(1)
        def col(name):
            return headers.index(name) + 1 if name in headers else None

        status_col    = col("Статус")
        orders_col    = col("Кол-во заявок")
        views_col     = col("Просмотры")
        price_col     = col("Нач. цена (сум)")
        price_usd_col = col("Нач. цена ($)")
        date_col      = col("Дата аукциона")
        deadline_col  = col("Дедлайн заявки")
    except:
        return

    value_updates = []
    color_requests = []
    updated = 0

    for lot in lots:
        lot_id = str(lot.get("id", ""))
        if lot_id not in existing:
            continue
        row_num    = existing[lot_id]
        new_status = get_status(lot.get("lot_statuses_id", 0))
        sp         = lot.get("start_price", 0)

        def add(c, val):
            if c:
                value_updates.append({
                    "range": gspread.utils.rowcol_to_a1(row_num, c),
                    "values": [[val]]
                })

        add(status_col,    new_status)
        add(orders_col,    str(safe_int(lot.get("user_order_cnt", 0))))
        add(views_col,     str(safe_int(lot.get("view_count", 0))))
        add(price_col,     format_price(sp))
        add(price_usd_col, to_usd(sp, usd_rate))
        add(date_col,      lot.get("auction_date_str", ""))
        add(deadline_col,  lot.get("order_end_time_str", ""))

        if status_col:
            cell_color = STATUS_COLORS.get(new_status, COLOR_WHITE)
            color_requests.append({
                "repeatCell": {
                    "range": {
                        "sheetId": ws.id,
                        "startRowIndex": row_num - 1,
                        "endRowIndex": row_num,
                        "startColumnIndex": status_col - 1,
                        "endColumnIndex": status_col,
                    },
                    "cell": {"userEnteredFormat": {"backgroundColor": cell_color}},
                    "fields": "userEnteredFormat.backgroundColor"
                }
            })
        updated += 1

    try:
        if value_updates:
            ws.batch_update(value_updates)
        if color_requests:
            ws.spreadsheet.batch_update({"requests": color_requests})
        print(f"     Обновлено лотов: {updated}")
    except Exception as e:
        print(f"  [ОШИБКА] Обновление: {e}")


def remove_green(ws):
    try:
        last = len(ws.col_values(1))
        if last >= 2:
            ws.format(f"A2:{chr(64+len(ws.row_values(1)))+str(last)}",
                      {"backgroundColor": COLOR_WHITE})
    except Exception as e:
        print(f"  [ОШИБКА] Снятие подсветки: {e}")


def highlight_rows_green(ws, rows: list, col_count: int):
    if not rows:
        return
    try:
        reqs = [{
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": r - 1, "endRowIndex": r,
                    "startColumnIndex": 0,  "endColumnIndex": col_count,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_GREEN}},
                "fields": "userEnteredFormat.backgroundColor"
            }
        } for r in rows]
        ws.spreadsheet.batch_update({"requests": reqs})
    except Exception as e:
        print(f"  [ОШИБКА] Подсветка: {e}")


def highlight_rows_dupe(ws, rows: list, col_count: int):
    """Жёлтоватый фон для дублей."""
    if not rows:
        return
    try:
        reqs = [{
            "repeatCell": {
                "range": {
                    "sheetId": ws.id,
                    "startRowIndex": r - 1, "endRowIndex": r,
                    "startColumnIndex": 0,  "endColumnIndex": col_count,
                },
                "cell": {"userEnteredFormat": {"backgroundColor": COLOR_DUPE}},
                "fields": "userEnteredFormat.backgroundColor"
            }
        } for r in rows]
        ws.spreadsheet.batch_update({"requests": reqs})
    except Exception as e:
        print(f"  [ОШИБКА] Подсветка дублей: {e}")


def batch_append_rows(ws, rows: list, retries=5) -> list:
    if not rows:
        return []
    for attempt in range(retries):
        try:
            start_row = len(ws.col_values(1)) + 1
            ws.append_rows(rows, value_input_option="USER_ENTERED")
            return list(range(start_row, start_row + len(rows)))
        except gspread.exceptions.APIError as e:
            if "429" in str(e):
                wait = 20 * (attempt + 1)
                print(f"  ⏳ Лимит Google Sheets, жду {wait} сек...")
                time.sleep(wait)
            else:
                print(f"  [ОШИБКА] Sheets: {e}")
                return []
    return []


# ──────────────────────────────────────────────
#  ПОСТРОЕНИЕ СТРОК ДЛЯ SHEETS / JSON
# ──────────────────────────────────────────────

def _lot_display_type(group_id: int, lot: dict) -> str:
    name = lot.get("name", "")
    if group_id == 1:
        return classify_realty(name)
    elif group_id == 2:
        return normalize_car_name(name)
    else:
        cat = lot.get("confiscant_categories_name", name)
        if any(k in cat.lower() for k in ["avto", "transport", "mashina", "авто"]):
            return "🚗 Авто"
        elif any(k in cat.lower() for k in ["yer", "земл", "участок"]):
            return "🌍 Земля"
        return "🏠 Недвижимость"


def build_lot_dict(group_id: int, lot: dict, usd_rate: float, coords: dict,
                   added_date: str, is_duplicate: bool = False) -> dict:
    """Строит словарь лота для lots.json."""
    lot_id   = str(lot.get("id", ""))
    name     = lot.get("name", "")
    address  = lot.get("full_address", "")
    status_id = int(lot.get("lot_statuses_id", 0) or 0)
    sp       = lot.get("start_price", 0)
    ep       = lot.get("baholangan_narx", 0)
    lat, lng = coords.get(lot_id, (None, None))

    return {
        "id":               lot_id,
        "group_id":         group_id,
        "group_name":       GROUPS[group_id],
        "display_type":     _lot_display_type(group_id, lot),
        "name":             name,
        "address":          address,
        "map_url":          make_map_link(lat, lng, address),
        "status":           get_status(status_id),
        "status_id":        status_id,
        "is_closed":        is_closed_status(status_id),
        "auction_type":     "🔴↓ Понижение" if lot.get("is_descending_auction") else "🟢↑ Повышение",
        "start_price":      int(float(sp or 0)),
        "start_price_fmt":  format_price(sp),
        "start_price_usd":  to_usd(sp, usd_rate),
        "eval_price":       int(float(ep or 0)),
        "eval_price_fmt":   format_price(ep),
        "eval_price_usd":   to_usd(ep, usd_rate),
        "deposit_sum":      format_price(lot.get("zaklad_summa", "")),
        "deposit_pct":      str(lot.get("zaklad_percent", "")),
        "auction_date":     lot.get("auction_date_str", ""),
        "deadline":         lot.get("order_end_time_str", ""),
        "orders":           safe_int(lot.get("user_order_cnt", 0)),
        "views":            safe_int(lot.get("view_count", 0)),
        "url":              lot_url(lot_id),
        "added_date":       added_date,
        "is_duplicate":     is_duplicate,
    }


def build_sheet_row(group_id: int, lot_dict: dict) -> list:
    """Строит строку для Google Sheets из lot_dict."""
    return [
        lot_dict["id"],
        lot_dict["display_type"],
        lot_dict["name"],
        lot_dict["address"],
        lot_dict["map_url"],
        lot_dict["status"],
        lot_dict["auction_type"],
        lot_dict["start_price_fmt"],
        lot_dict["start_price_usd"],
        lot_dict["eval_price_fmt"],
        lot_dict["eval_price_usd"],
        lot_dict["deposit_sum"],
        lot_dict["deposit_pct"],
        lot_dict["auction_date"],
        lot_dict["deadline"],
        str(lot_dict["orders"]),
        str(lot_dict["views"]),
        lot_dict["url"],
        lot_dict["added_date"],
    ]


# ──────────────────────────────────────────────
#  ОСНОВНАЯ ЛОГИКА
# ──────────────────────────────────────────────

def check_and_notify():
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    today   = datetime.now().strftime("%d.%m.%Y")
    today_iso = date.today().isoformat()
    print(f"\n[{now_str}] Запускаю проверку лотов...")

    usd_rate  = get_usd_rate()
    seen      = load_seen()
    lots_data = load_lots_data()
    stored_lots = lots_data.get("lots", {})

    # Открываем Google Sheets (если настроен)
    sheets_ok  = False
    sheets_map = {}
    if sheets_available():
        try:
            sh = get_spreadsheet()
            ws_realty     = get_or_create_worksheet(sh, "🏠 Недвижимость", HEADERS_REALTY)
            ws_auto       = get_or_create_worksheet(sh, "🚗 Авто",         HEADERS_AUTO)
            ws_bankruptcy = get_or_create_worksheet(sh, "⚖️ Банкротство",  HEADERS_BANKRUPTCY)
            sheets_map = {
                1:  (ws_realty,     get_lot_ids_in_sheet(ws_realty)),
                2:  (ws_auto,       get_lot_ids_in_sheet(ws_auto)),
                15: (ws_bankruptcy, get_lot_ids_in_sheet(ws_bankruptcy)),
            }
            for ws, _ in sheets_map.values():
                remove_green(ws)
            sheets_ok = True
        except Exception as e:
            print(f"  [ОШИБКА] Google Sheets: {e}")

    summary  = {}
    new_rows = {1: [], 2: [], 15: []}
    new_counts = {"realty": 0, "auto": 0, "bankruptcy": 0}
    count_key  = {1: "realty", 2: "auto", 15: "bankruptcy"}

    for group_id, label in GROUPS.items():
        print(f"  → {label}...")
        lots = fetch_lots(group_id)
        print(f"     Получено: {len(lots)}")

        # Дедупликация
        is_duplicate = detect_duplicates(lots)

        # Находим новые лоты (не в seen)
        new_lot_ids_raw = [
            str(lot.get("id", "")) for lot in lots
            if str(lot.get("id", "")) not in seen
            and float(lot.get("start_price", 0) or 0) <= MAX_PRICE
        ]
        # Фильтруем закрытые для запроса координат
        closed_new = {
            str(lot.get("id", "")) for lot in lots
            if str(lot.get("id", "")) in new_lot_ids_raw
            and is_closed_status(lot.get("lot_statuses_id", 0))
        }
        if new_lot_ids_raw and not SKIP_COORDS:
            coords_map = fetch_coords_bulk(new_lot_ids_raw, skip_if_cancelled=closed_new)
        else:
            if SKIP_COORDS and new_lot_ids_raw:
                print(f"  ⏭ CI режим: координаты пропускаем ({len(new_lot_ids_raw)} лотов)")
            coords_map = {}

        # Обновляем существующие лоты в Sheets
        if sheets_ok:
            ws, existing = sheets_map[group_id]
            update_statuses_in_sheet(ws, lots, existing, usd_rate)

        new_count = active_count = cancelled_count = skipped = 0
        rows_to_insert = []
        dupe_rows_in_sheet = []

        for lot in lots:
            lot_id    = str(lot.get("id", ""))
            status_id = int(lot.get("lot_statuses_id", 0) or 0)
            price     = float(lot.get("start_price", 0) or 0)
            cat_id    = lot.get("category_id", 0)

            if status_id in ACTIVE_STATUSES:
                active_count += 1
            elif status_id in CLOSED_STATUSES:
                cancelled_count += 1

            if price > MAX_PRICE:
                skipped += 1
                continue
            if group_id == 15 and cat_id not in BANKRUPTCY_ALLOWED_CATEGORIES:
                continue

            # Обновляем статус в JSON хранилище если лот уже есть
            if lot_id in stored_lots:
                stored_lots[lot_id]["status"]    = get_status(status_id)
                stored_lots[lot_id]["status_id"] = status_id
                stored_lots[lot_id]["is_closed"] = is_closed_status(status_id)
                stored_lots[lot_id]["orders"]    = int(lot.get("user_order_cnt", 0) or 0)
                stored_lots[lot_id]["views"]     = int(lot.get("view_count", 0) or 0)
                stored_lots[lot_id]["auction_date"] = lot.get("auction_date_str", "")
                stored_lots[lot_id]["deadline"]     = lot.get("order_end_time_str", "")
                stored_lots[lot_id]["is_duplicate"] = is_duplicate.get(lot_id, False)

            if lot_id not in seen:
                seen[lot_id] = today
                new_count += 1
                is_dupe = is_duplicate.get(lot_id, False)
                lot_dict = build_lot_dict(group_id, lot, usd_rate, coords_map, today_iso, is_dupe)
                stored_lots[lot_id] = lot_dict

                if sheets_ok:
                    ws, existing = sheets_map[group_id]
                    if lot_id not in existing:
                        rows_to_insert.append((lot_dict, is_dupe))

        # Batch запись в Sheets
        if sheets_ok and rows_to_insert:
            ws, _ = sheets_map[group_id]
            print(f"     Записываю {len(rows_to_insert)} лотов в таблицу...")
            plain_rows = [build_sheet_row(group_id, d) for d, _ in rows_to_insert]
            inserted_rows = batch_append_rows(ws, plain_rows)
            # Разделяем новые и дублирующие строки
            new_highlight = [r for r, (_, is_d) in zip(inserted_rows, rows_to_insert) if not is_d]
            dupe_highlight = [r for r, (_, is_d) in zip(inserted_rows, rows_to_insert) if is_d]
            new_rows[group_id].extend(inserted_rows)
            dupe_rows_in_sheet = dupe_highlight

        summary[label] = {
            "new": new_count,
            "active": active_count,
            "cancelled": cancelled_count,
            "skipped": skipped,
        }
        new_counts[count_key[group_id]] = new_count
        print(f"     Новых: {new_count} | Активных: {active_count} | Пропущено >1млрд: {skipped}")

    # Подсвечиваем строки в Sheets
    if sheets_ok:
        col_counts = {1: len(HEADERS_REALTY), 2: len(HEADERS_AUTO), 15: len(HEADERS_BANKRUPTCY)}
        for group_id, rows in new_rows.items():
            if rows:
                ws, _ = sheets_map[group_id]
                highlight_rows_green(ws, rows, col_counts[group_id])

    # Сохраняем данные
    save_seen(seen)
    lots_data["updated_at"] = datetime.now().isoformat()
    lots_data["usd_rate"]   = usd_rate
    lots_data["lots"]       = stored_lots
    save_lots_data(lots_data)
    update_history(new_counts)

    total_new = sum(v["new"] for v in summary.values())
    print(f"\n  ✅ Готово. Новых лотов: {total_new}.")


# ──────────────────────────────────────────────
#  ЗАПУСК
# ──────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="E-Auksion Bot")
    parser.add_argument("--no-schedule", action="store_true",
                        help="Запустить один раз без планировщика (для GitHub Actions)")
    args = parser.parse_args()

    print("=" * 55)
    print("  E-Auksion Bot — г. Ташкент")
    print("  Недвижимость / Авто / Банкротство")
    print(f"  Лимит: до 1 000 000 000 сум")
    if not args.no_schedule:
        print(f"  Сводка в Telegram в {REPORT_TIME}")
    print("=" * 55)

    check_and_notify()

    if not args.no_schedule:
        schedule.every().day.at(REPORT_TIME).do(check_and_notify)
        print(f"\n⏰ Бот работает. Следующая проверка в {REPORT_TIME}.")
        print("   Остановить: Ctrl+C\n")
        while True:
            schedule.run_pending()
            time.sleep(60)
