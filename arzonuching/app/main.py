from __future__ import annotations
import os
import asyncio
import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.filters import CommandStart
from aiogram.client.bot import DefaultBotProperties
from aiogram.enums import ParseMode

# =============================
# ENV
# =============================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TP_API_TOKEN = os.getenv("TP_API_TOKEN", "")  # Travelpayouts token
AVS_API_TOKEN = os.getenv("AVS_API_TOKEN", "")  # Aviasales API token (optional)
CURRENCY = os.getenv("CURRENCY", "uzs").lower()  # uzs, usd, rub, etc.
MANAGERS_CHAT_ID = int(os.getenv("MANAGERS_CHAT_ID", "0"))  # Групповой чат для заявок

if not BOT_TOKEN:
    raise SystemExit("Please set BOT_TOKEN env var.")
if not TP_API_TOKEN:
    print("[WARN] TP_API_TOKEN not set. Real price search will not work.")

# =============================
# STATIC DATA
# =============================
# Popular directions (Variant A): countries mapped to primary city/airport IATA
COUNTRIES: Dict[str, List[Tuple[str, str]]] = {
    "🇺🇿 Узбекистан": [("Tashkent", "TAS")],
    "🇹🇷 Турция": [("Istanbul", "IST")],
    "🇦🇪 ОАЭ": [("Dubai", "DXB")],
    "🇷🇺 Россия": [("Moscow", "MOW")],  # city IATA for multiple airports
    "🇬🇪 Грузия": [("Tbilisi", "TBS")],
    "🇰🇿 Казахстан": [("Almaty", "ALA"), ("Astana", "NQZ")],
}

# Русские названия месяцев и дней недели
MONTHS_RU = [
    "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"
]
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

PAGE_SIZE = 5

# =============================
# STATE
# =============================
@dataclass
class QueryState:
    origin: Optional[str] = None
    origin_label: Optional[str] = None
    destination: Optional[str] = None
    destination_label: Optional[str] = None
    depart_date: Optional[date] = None
    results: List[dict] = None
    page: int = 0
    selected_idx: Optional[int] = None

user_state: Dict[int, QueryState] = {}

# =============================
# KEYBOARDS
# =============================

def countries_kb(stage: str, exclude_iata: Optional[str] = None) -> InlineKeyboardMarkup:
    """
    stage: "origin" or "dest"
    exclude_iata: if provided, hide options having this IATA
    """
    buttons: List[List[InlineKeyboardButton]] = []
    for country, cities in COUNTRIES.items():
        for city, iata in cities:
            if exclude_iata and iata == exclude_iata:
                continue
            text = f"{country} ({iata})"
            cb = f"pick:{stage}:{iata}:{city}"
            buttons.append([InlineKeyboardButton(text=text, callback_data=cb)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def month_days(year: int, month: int) -> List[List[Optional[int]]]:
    cal = calendar.Calendar(firstweekday=0)
    weeks: List[List[Optional[int]]] = []
    row: List[Optional[int]] = []
    for d in cal.itermonthdays(year, month):
        row.append(None if d == 0 else d)
        if len(row) == 7:
            weeks.append(row)
            row = []
    if row:
        while len(row) < 7:
            row.append(None)
        weeks.append(row)
    return weeks


def calendar_kb(target: date, selected: Optional[date] = None) -> InlineKeyboardMarkup:
    today = date.today()
    y, m = target.year, target.month
    weeks = month_days(y, m)
    # Заголовок на русском
    header = InlineKeyboardButton(text=f"{MONTHS_RU[m-1]} {y}", callback_data="noop")
    prev_mon = (target.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_mon = (target.replace(day=28) + timedelta(days=4)).replace(day=1)

    rows: List[List[InlineKeyboardButton]] = []
    rows.append([
        InlineKeyboardButton(text="◀️", callback_data=f"cal:prev:{prev_mon.isoformat()}"),
        header,
        InlineKeyboardButton(text="▶️", callback_data=f"cal:next:{next_mon.isoformat()}")
    ])
    # Дни недели на русском
    rows.append([InlineKeyboardButton(text=t, callback_data="noop") for t in WEEKDAYS_RU])

    for w in weeks:
        row: List[InlineKeyboardButton] = []
        for d in w:
            if d is None:
                row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
            else:
                dt = date(y, m, d)
                # Не даём выбирать прошедшие даты
                if dt < today:
                    row.append(InlineKeyboardButton(text="·", callback_data="noop"))
                    continue
                # Подсветка выбранной даты (скобками)
                label = f"[{d}]" if selected and dt == selected else str(d)
                row.append(InlineKeyboardButton(text=label, callback_data=f"cal:set:{dt.isoformat()}"))
        rows.append(row)

    # Быстрый выбор ближайших дат
    rows.append([InlineKeyboardButton(text="🔥 Ближайшие дешёвые даты", callback_data="cal:near:7")])
    rows.append([InlineKeyboardButton(text="↩️ Назад", callback_data="back:dest")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def results_kb(visible: int, start_index: int, has_more: bool) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for i in range(visible):
        idx = start_index + i
        rows.append([InlineKeyboardButton(text=f"Купить #{idx+1} 💳", callback_data=f"buy:{idx}")])
    nav: List[InlineKeyboardButton] = [InlineKeyboardButton(text="Новый поиск", callback_data="reset")]
    if has_more:
        nav.insert(0, InlineKeyboardButton(text="Показать ещё", callback_data="res:more"))
    rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows)

# =============================
# API CLIENTS
# =============================

async def fetch_travelpayouts(origin: str, destination: str, depart: date, limit: int = 10) -> List[dict]:
    if not TP_API_TOKEN:
        return []
    url = (
        "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
        f"?origin={origin}&destination={destination}&departure_at={depart.strftime('%Y-%m-%d')}"
        f"&currency={CURRENCY}&limit={limit}&page=1&sorting=price&direct=false&unique=false&one_way=true"
        f"&token={TP_API_TOKEN}"
    )
    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=20) as r:
            if r.status != 200:
                return []
            data = await r.json()
            return data.get("data", [])


async def fetch_aviasales(origin: str, destination: str, depart: date, limit: int = 10) -> List[dict]:
    if not AVS_API_TOKEN:
        return []
    # Example placeholder URL; replace with your official Aviasales endpoint
    url = (
        "https://api.aviasales.com/v3/prices_for_dates"
        f"?origin={origin}&destination={destination}&departure_at={depart.strftime('%Y-%m-%d')}"
        f"&currency={CURRENCY}&limit={limit}&sorting=price&one_way=true"
    )
    headers = {"X-Access-Token": AVS_API_TOKEN}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers, timeout=20) as r:
                if r.status != 200:
                    return []
                data = await r.json()
                return data.get("data", [])
    except Exception:
        return []


def merge_results(*lists: List[dict], limit: int = 20) -> List[dict]:
    pool: List[dict] = []
    for lst in lists:
        pool.extend(lst)
    normalized: List[dict] = []
    for item in pool:
        price = item.get("price") or item.get("value")
        airline = item.get("airline") or item.get("gate") or ""
        depart_at = item.get("departure_at") or item.get("departure_at_iso") or ""
        flight_number = item.get("flight_number") or ""
        link = item.get("link") or item.get("deeplink") or ""  # не показываем, но сохраняем
        normalized.append({
            "price": int(price) if str(price).isdigit() else price,
            "airline": airline,
            "link": link,
            "departure_at": depart_at,
            "flight_number": flight_number,
        })
    normalized.sort(key=lambda x: (x["price"] if isinstance(x["price"], int) else 10**12))
    seen = set()
    unique: List[dict] = []
    for n in normalized:
        k = (n.get("airline"), n.get("departure_at"))
        if k in seen:
            continue
        seen.add(k)
        unique.append(n)
        if len(unique) >= limit:
            break
    return unique

# =============================
# RENDERING
# =============================

def fmt_price(v: Optional[int]) -> str:
    if v is None:
        return "—"
    return f"{v:,}".replace(",", " ") + f" {CURRENCY.upper()}"


def build_results_text(q: QueryState) -> str:
    head = (
        "✈️ <b>{} → {}</b>\n📅 {}\n\n".format(
            q.origin or "?",
            q.destination or "?",
            q.depart_date.strftime("%d.%m.%Y") if q.depart_date else "—",
        )
    )

    if not q.results:
        return head + "Пока нет результатов. Попробуйте другую дату или направление."

    start = q.page * PAGE_SIZE
    chunk = q.results[start:start + PAGE_SIZE]
    if not chunk:
        return head + "Все варианты показаны."

    lines = []
    for i, r in enumerate(chunk, start=start + 1):
        dt = r.get("departure_at")
        dt_str = dt[:16].replace("T", " ") if isinstance(dt, str) else "—"
        lines.append(
            f"{i}. {fmt_price(r.get('price'))} • {r.get('airline','')}\n"
            f"   Вылет: {dt_str}"
        )

    return head + "\n".join(lines)

    if not q.results:
        return head + "Пока нет результатов. Попробуйте другую дату или направление."
    start = q.page * PAGE_SIZE
    chunk = q.results[start:start + PAGE_SIZE]
    if not chunk:
        return head + "Все варианты показаны."
    lines = []
    for i, r in enumerate(chunk, start=start + 1):
        dt = r.get("departure_at")
        dt_str = dt[:16].replace('T', ' ') if isinstance(dt, str) else "—"
        lines.append(
            f"{i}. {fmt_price(r.get('price'))} • {r.get('airline','')}
"
            f"   Вылет: {dt_str}"
        )
    return head + "
".join(lines)
    start = q.page * PAGE_SIZE
    chunk = q.results[start:start + PAGE_SIZE]
    if not chunk:
        return head + "Все варианты показаны."
    lines = []
    for i, r in enumerate(chunk, start=start + 1):
        dt = r.get("departure_at")
        dt_str = dt[:16].replace('T', ' ') if isinstance(dt, str) else "—"
        lines.append(
            f"{i}. {fmt_price(r.get('price'))} • {r.get('airline','')}
"
            f"   Вылет: {dt_str}"
        )
    return head + "
".join(lines)
