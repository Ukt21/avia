from __future__ import annotations
import os
import asyncio
import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
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

if not BOT_TOKEN:
    raise SystemExit("Please set BOT_TOKEN env var.")
if not TP_API_TOKEN:
    print("[WARN] TP_API_TOKEN not set. Real price search will not work.")

# =============================
# STATIC DATA
# =============================
# Popular directions (A Variant): countries mapped to primary city/airport IATA
COUNTRIES: Dict[str, List[Tuple[str, str]]] = {
    "🇺🇿 Узбекистан": [("Tashkent", "TAS")],
    "🇹🇷 Турция": [("Istanbul", "IST")],
    "🇦🇪 ОАЭ": [("Dubai", "DXB")],
    "🇷🇺 Россия": [("Moscow", "MOW")],  # city IATA for multiple airports
    "🇬🇪 Грузия": [("Tbilisi", "TBS")],
    "🇰🇿 Казахстан": [("Almaty", "ALA"), ("Astana", "NQZ")],
}

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
    row: List[InlineKeyboardButton] = []
    for country, cities in COUNTRIES.items():
        for city, iata in cities:
            if exclude_iata and iata == exclude_iata:
                continue
            text = f"{country} ({iata})"
            cb = f"pick:{stage}:{iata}:{city}"
            row.append(InlineKeyboardButton(text=text, callback_data=cb))
            if len(row) == 1:
                buttons.append(row)
                row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def month_days(year: int, month: int) -> List[List[Optional[int]]]:
    cal = calendar.Calendar(firstweekday=0)
    weeks: List[List[Optional[int]]] = []
    row: List[Optional[int]] = []
    for d in cal.itermonthdays(year, month):
        if d == 0:
            row.append(None)
        else:
            row.append(d)
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
    rows.append([InlineKeyboardButton(text="◀️", callback_data=f"cal:prev:{prev_mon.isoformat()}"),
                 header,
                 InlineKeyboardButton(text="▶️", callback_data=f"cal:next:{next_mon.isoformat()}")])
    # Weekday labels
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


def results_more_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Показать ещё", callback_data="res:more")],
        [InlineKeyboardButton(text="Новый поиск", callback_data="reset")],
    ])

# =============================
# API CLIENTS
# =============================

async def fetch_travelpayouts(origin: str, destination: str, depart: date, limit: int = 5) -> List[dict]:
    if not TP_API_TOKEN:
        return []
   from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

airline = result.get("airline", "Авиакомпания")
origin = result.get("origin", "")
destination = result.get("destination", "")
depart_date = result.get("depart_date", "")
return_date = result.get("return_date", "")
price = result.get("price", "Цена не найдена")
ticket_url = result.get("url")

text = (
    f"✈️ {origin} → {destination}\n"
    f"🛫 Авиакомпания: {airline}\n"
    f"📅 Даты: {depart_date} — {return_date}\n"
    f"💰 Цена: от {price} сум"
)

button = InlineKeyboardButton(
    text="Посмотреть билеты 🔎",
    url=ticket_url
)

keyboard = InlineKeyboardMarkup(inline_keyboard=[[button]])

await message.answer(text, reply_markup=keyboard)

    async with aiohttp.ClientSession() as s:
        async with s.get(url, timeout=20) as r:
            if r.status != 200:
                return []
            data = await r.json()
            return data.get("data", [])


async def fetch_aviasales(origin: str, destination: str, depart: date, limit: int = 5) -> List[dict]:
    """
    Optional second provider. If AVS_API_TOKEN is not set, returns empty.
    This endpoint may differ depending on your Aviasales agreement.
    Placeholder uses the same Travelpayouts-compatible structure if available.
    """
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
                # Try to align to the same schema
                return data.get("data", [])
    except Exception:
        return []


def merge_results(*lists: List[dict], limit: int = 10) -> List[dict]:
    pool: List[dict] = []
    for lst in lists:
        for x in lst:
            pool.append(x)
    # Normalize and sort by price
    normalized: List[dict] = []
    for item in pool:
        price = item.get("price") or item.get("value")
        airline = item.get("airline") or item.get("gate") or ""
        link = item.get("link") or item.get("deeplink") or ""
        depart_at = item.get("departure_at") or item.get("departure_at_iso") or ""
        flight_number = item.get("flight_number") or ""
        normalized.append({
            "price": int(price) if str(price).isdigit() else price,
            "airline": airline,
            "link": link,
            "departure_at": depart_at,
            "flight_number": flight_number,
        })
    normalized.sort(key=lambda x: (x["price"] if isinstance(x["price"], int) else 10**12))
    # de-duplicate by link + departure time
    seen = set()
    unique: List[dict] = []
    for n in normalized:
        k = (n.get("link"), n.get("departure_at"))
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


def build_results_text(q: QueryState, results: List[dict]) -> str:
    head = (
        f"✈️ <b>{q.origin} → {q.destination}</b>\n"
        f"📅 {q.depart_date.strftime('%d.%m.%Y')}\n\n"
    )
    if not results:
        return head + "Пока нет результатов. Попробуйте другую дату или направление."
    lines = []
    for i, r in enumerate(results, 1):
        dt = r.get("departure_at")
        dt_str = dt[:16].replace('T', ' ') if isinstance(dt, str) else "—"
        lines.append(
            f"{i}. {fmt_price(r.get('price'))} • {r.get('airline','')}\n"
            f"   Вылет: {dt_str}\n"
            f"   {('Ссылка: ' + r['link']) if r.get('link') else ''}"
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
    # Open calendar for current month or next available day
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
    await c.message.edit_text(
        f"Запрос: <b>{st.origin} → {st.destination}</b> | {st.depart_date.strftime('%d.%m.%Y')}\n"
        f"Ищу варианты...",
    )
    await c.answer("Ищу билеты…")

    # Query providers in parallel
    tp_task = fetch_travelpayouts(st.origin, st.destination, st.depart_date, limit=5)
    avs_task = fetch_aviasales(st.origin, st.destination, st.depart_date, limit=5)
    tp_res, avs_res = await asyncio.gather(tp_task, avs_task)

    merged = merge_results(tp_res, avs_res, limit=10)
    text = build_results_text(st, merged)
    await c.message.edit_text(text, reply_markup=results_more_kb(), disable_web_page_preview=True)


@dp.callback_query(F.data == "res:more")
async def res_more(c: CallbackQuery):
    st = user_state.get(c.from_user.id)
    if not st or not st.origin or not st.destination or not st.depart_date:
        await c.answer("Сначала выберите маршрут и дату", show_alert=True)
        return
    tp_task = fetch_travelpayouts(st.origin, st.destination, st.depart_date, limit=10)
    avs_task = fetch_aviasales(st.origin, st.destination, st.depart_date, limit=10)
    tp_res, avs_res = await asyncio.gather(tp_task, avs_task)
    merged = merge_results(tp_res, avs_res, limit=20)
    text = build_results_text(st, merged)
    await c.message.edit_text(text, reply_markup=results_more_kb(), disable_web_page_preview=True)
    await c.answer()


@dp.callback_query(F.data == "back:dest")
async def back_to_dest(c: CallbackQuery):
    st = user_state.setdefault(c.from_user.id, QueryState())
    await c.message.edit_text(
        f"Вылет: <b>{st.origin}</b>\nВыбери <b>страну прибытия</b>:",
        reply_markup=countries_kb(stage="dest", exclude_iata=st.origin),
    )
    await c.answer()


@dp.callback_query(F.data == "reset")
async def reset_flow(c: CallbackQuery):
    user_state[c.from_user.id] = QueryState()
    await c.message.edit_text("Новый поиск. Выбери <b>страну вылета</b>:", reply_markup=countries_kb(stage="origin"))
    await c.answer()


async def main() -> None:
    print("Bot is running in polling mode…")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"]) 


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped")


  


   
