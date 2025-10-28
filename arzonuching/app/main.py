from __future__ import annotations
import os
import asyncio
import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
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
MANAGERS_CHAT_ID = int(os.getenv("MANAGERS_CHAT_ID", "0"))  # Group chat for leads

if not BOT_TOKEN:
    raise SystemExit("Please set BOT_TOKEN env var.")
if not TP_API_TOKEN:
    print("[WARN] TP_API_TOKEN not set. Real price search will not work.")

# =============================
# STATIC DATA
# =============================
# Variant A: countries mapped to main cities/airports
COUNTRIES: Dict[str, List[Tuple[str, str]]] = {
    "🇺🇿 Узбекистан": [("Tashkent", "TAS")],
    "🇹🇷 Турция": [("Istanbul", "IST")],
    "🇦🇪 ОАЭ": [("Dubai", "DXB")],
    "🇷🇺 Россия": [("Moscow", "MOW")],
    "🇬🇪 Грузия": [("Tbilisi", "TBS")],
    "🇰🇿 Казахстан": [("Almaty", "ALA"), ("Astana", "NQZ")],
}

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
    """Show countries list. stage is 'origin' or 'dest'."""
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


def calendar_kb(target: date) -> InlineKeyboardMarkup:
    y, m = target.year, target.month
    weeks = month_days(y, m)
    header = InlineKeyboardButton(text=target.strftime("%B %Y"), callback_data="noop")
    prev_mon = (target.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_mon = (target.replace(day=28) + timedelta(days=4)).replace(day=1)

    rows: List[List[InlineKeyboardButton]] = []
    rows.append([
        InlineKeyboardButton(text="◀️", callback_data=f"cal:prev:{prev_mon.isoformat()}"),
        header,
        InlineKeyboardButton(text="▶️", callback_data=f"cal:next:{next_mon.isoformat()}")
    ])
    rows.append([InlineKeyboardButton(text=t, callback_data="noop") for t in ["Mo","Tu","We","Th","Fr","Sa","Su"]])

    for w in weeks:
        row: List[InlineKeyboardButton] = []
        for d in w:
            if d is None:
                row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
            else:
                dt = date(y, m, d)
                row.append(InlineKeyboardButton(text=str(d), callback_data=f"cal:set:{dt.isoformat()}"))
        rows.append(row)

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

async def fetch_travelpayouts(origin: str, destination: str, depart: date, limit: int = 20) -> List[dict]:
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


async def fetch_aviasales(origin: str, destination: str, depart: date, limit: int = 20) -> List[dict]:
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


def merge_results(*lists: List[dict], limit: int = 40) -> List[dict]:
    pool: List[dict] = []
    for lst in lists:
        pool.extend(lst)
    normalized: List[dict] = []
    for item in pool:
        price = item.get("price") or item.get("value")
        airline = item.get("airline") or item.get("gate") or ""
        depart_at = item.get("departure_at") or item.get("departure_at_iso") or ""
        flight_number = item.get("flight_number") or ""
        link = item.get("link") or item.get("deeplink") or ""  # keep internally, never show
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
    # Use .format to avoid any f-string issues on some environments
    head = "✈️ <b>{} → {}</b>\n📅 {}\n\n".format(
        q.origin or "?",
        q.destination or "?",
        q.depart_date.strftime('%d.%m.%Y') if q.depart_date else "—",
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
        dt_str = dt[:16].replace('T', ' ') if isinstance(dt, str) else "—"
        lines.append(
            f"{i}. {fmt_price(r.get('price'))} • {r.get('airline','')}\n"
            f"   Вылет: {dt_str}"
        )
    return head + "\n".join(lines)

# =============================
# BOT
# =============================

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


@dp.message(CommandStart())
async def on_start(m: Message):
    user_state[m.from_user.id] = QueryState()
    await m.answer(
        "Привет! Выбери <b>страну вылета</b>:",
        reply_markup=countries_kb(stage="origin"),
    )


@dp.callback_query(F.data.startswith("pick:origin:"))
async def pick_origin(c: CallbackQuery):
    _, _, iata, city = c.data.split(":", 3)
    st = user_state.setdefault(c.from_user.id, QueryState())
    st.origin = iata
    st.origin_label = city
    await c.message.edit_text(
        f"Вылет: <b>{iata}</b>\nТеперь выбери <b>страну прибытия</b>:",
        reply_markup=countries_kb(stage="dest", exclude_iata=iata),
    )
    await c.answer()


@dp.callback_query(F.data.startswith("pick:dest:"))
async def pick_dest(c: CallbackQuery):
    _, _, iata, city = c.data.split(":", 3)
    st = user_state.setdefault(c.from_user.id, QueryState())
    st.destination = iata
    st.destination_label = city
    today = date.today()
    start = today if today.day <= 25 else (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    await c.message.edit_text(
        f"Маршрут: <b>{st.origin} → {st.destination}</b>\nВыбери дату вылета:",
        reply_markup=calendar_kb(start),
    )
    await c.answer()


@dp.callback_query(F.data.startswith("cal:prev:"))
async def cal_prev(c: CallbackQuery):
    iso = c.data.split(":", 2)[2]
    target = date.fromisoformat(iso)
    await c.message.edit_reply_markup(reply_markup=calendar_kb(target))
    await c.answer()


@dp.callback_query(F.data.startswith("cal:next:"))
async def cal_next(c: CallbackQuery):
    iso = c.data.split(":", 2)[2]
    target = date.fromisoformat(iso)
    await c.message.edit_reply_markup(reply_markup=calendar_kb(target))
    await c.answer()


@dp.callback_query(F.data.startswith("cal:set:"))
async def cal_set(c: CallbackQuery):
    iso = c.data.split(":", 2)[2]
    chosen = date.fromisoformat(iso)
    st = user_state.setdefault(c.from_user.id, QueryState())
    st.depart_date = chosen
    st.page = 0
    await c.message.edit_text(
        "Запрос: <b>{} → {}</b> | {}\nИщу варианты...".format(
            st.origin, st.destination, st.depart_date.strftime('%d.%m.%Y')
        )
    )
    await c.answer("Ищу билеты…")

    tp_task = fetch_travelpayouts(st.origin, st.destination, st.depart_date, limit=20)
    avs_task = fetch_aviasales(st.origin, st.destination, st.depart_date, limit=20)
    tp_res, avs_res = await asyncio.gather(tp_task, avs_task)

    st.results = merge_results(tp_res, avs_res, limit=40)
    text = build_results_text(st)
    start = st.page * PAGE_SIZE
    has_more = len(st.results) > start + PAGE_SIZE
    kb = results_kb(visible=min(PAGE_SIZE, len(st.results) - start), start_index=start, has_more=has_more)
    await c.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)


@dp.callback_query(F.data == "res:more")
async def res_more(c: CallbackQuery):
    st = user_state.get(c.from_user.id)
    if not st or not st.origin or not st.destination or not st.depart_date or not st.results:
        await c.answer("Сначала выберите маршрут и дату", show_alert=True)
        return
    st.page += 1
    text = build_results_text(st)
    if text == c.message.text:
        await c.answer("Больше результатов нет", show_alert=True)
        return
    start = st.page * PAGE_SIZE
    has_more = len(st.results) > start + PAGE_SIZE
    kb = results_kb(visible=min(PAGE_SIZE, max(0, len(st.results) - start)), start_index=start, has_more=has_more)
    await c.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    await c.answer()


@dp.callback_query(F.data.startswith("buy:"))
async def buy_ticket(c: CallbackQuery):
    idx = int(c.data.split(":", 1)[1])
    st = user_state.get(c.from_user.id)
    if not st or not st.results or idx >= len(st.results):
        await c.answer("Элемент не найден", show_alert=True)
        return
    st.selected_idx = idx
    choice = st.results[idx]
    dt = choice.get("departure_at")
    dt_str = dt[:16].replace('T', ' ') if isinstance(dt, str) else "—"
    txt = (
        "Вы выбрали вариант #{}:\nЦена: {}\nАвиакомпания: {}\nВылет: {}\n\n"
        "Отправьте номер телефона для оформления покупки.".format(
            idx + 1, fmt_price(choice.get('price')), choice.get('airline', ''), dt_str
        )
    )
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await c.message.answer(txt, reply_markup=kb)
    await c.answer()


@dp.message(F.contact)
async def got_contact(m: Message):
    st = user_state.get(m.from_user.id)
    if not st or st.selected_idx is None or not st.results:
        await m.answer("Спасибо! Мы свяжемся с вами.")
        return
    choice = st.results[st.selected_idx]
    phone = m.contact.phone_number
    dt = choice.get("departure_at")
    dt_str = dt[:16].replace('T', ' ') if isinstance(dt, str) else "—"
    text = (
        "🧾 Заявка на покупку билета\n"
        "Маршрут: {} → {}\n"
        "Дата: {}\n"
        "Вариант: #{}\n"
        "Цена: {}\n")
