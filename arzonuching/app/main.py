from __future__ import annotations
import os
import asyncio
import calendar
import logging
from dataclasses import dataclass, field
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
# LOGGING
# =============================
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("avia-bot")

# =============================
# ENV
# =============================
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
TP_API_TOKEN = os.getenv("TP_API_TOKEN", "")      # Travelpayouts token
AVS_API_TOKEN = os.getenv("AVS_API_TOKEN", "")    # Aviasales token (optional)
CURRENCY = os.getenv("CURRENCY", "uzs").lower()   # uzs, usd, rub, etc.
# Партнёрская ссылка.
# Пример: REF_LINK_TEMPLATE="https://example.com/buy?o={origin}&d={destination}&dt={date}&subid={subid}"
REF_LINK_TEMPLATE = os.getenv("REF_LINK_TEMPLATE", "")
REF_SUBID = os.getenv("REF_SUBID", "")
MANAGERS_CHAT_ID = int(os.getenv("MANAGERS_CHAT_ID", "0"))

if not BOT_TOKEN:
    raise SystemExit("Please set BOT_TOKEN env var.")
if not TP_API_TOKEN:
    log.warning("TP_API_TOKEN not set. Real price search will not work.")

# =============================
# STATIC DATA
# =============================
COUNTRIES: Dict[str, List[Tuple[str, str]]] = {
    "🇺🇿 Узбекистан": [("Tashkent", "TAS")],
    "🇹🇷 Турция": [("Istanbul", "IST"), ("Antalya", "AYT"), ("Ankara", "ESB")],
    "🇦🇪 ОАЭ": [("Dubai", "DXB"), ("Abu Dhabi", "AUH")],
    "🇷🇺 Россия": [("Moscow", "MOW"), ("Saint‑Petersburg", "LED"), ("Kazan", "KZN")],
    "🇬🇪 Грузия": [("Tbilisi", "TBS")],
    "🇰🇿 Казахстан": [("Almaty", "ALA"), ("Astana", "NQZ")],
}

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
    return_date: Optional[date] = None
    results: List[dict] = field(default_factory=list)
    page: int = 0
    selected_idx: Optional[int] = None
    adding_return: bool = False

user_state: Dict[int, QueryState] = {}

# =============================
# HELPERS
# =============================

def flag_for_iata(iata: Optional[str]) -> str:
    if not iata:
        return "✈️"
    for country, cities in COUNTRIES.items():
        for _city, code in cities:
            if code == iata:
                # country like "🇹🇷 Турция" → take first token
                return country.split()[0]
    return "✈️"

# =============================
# KEYBOARDS
# =============================

def countries_kb(stage: str, exclude_iata: Optional[str] = None) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []
    for country, cities in COUNTRIES.items():
        for city, iata in cities:
            if exclude_iata and iata == exclude_iata:
                continue
            text = f"{country}: {city} ({iata})"
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
            weeks.append(row); row = []
    if row:
        while len(row) < 7:
            row.append(None)
        weeks.append(row)
    return weeks


def calendar_kb(target: date, selected: Optional[date] = None) -> InlineKeyboardMarkup:
    today = date.today()
    y, m = target.year, target.month
    weeks = month_days(y, m)
    header = InlineKeyboardButton(text=f"{MONTHS_RU[m-1]} {y}", callback_data="noop")
    prev_mon = (target.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_mon = (target.replace(day=28) + timedelta(days=4)).replace(day=1)

    rows: List[List[InlineKeyboardButton]] = []
    rows.append([
        InlineKeyboardButton(text="◀️", callback_data=f"cal:prev:{prev_mon.isoformat()}"),
        header,
        InlineKeyboardButton(text="▶️", callback_data=f"cal:next:{next_mon.isoformat()}")
    ])
    rows.append([InlineKeyboardButton(text=t, callback_data="noop") for t in WEEKDAYS_RU])

    for w in weeks:
        row: List[InlineKeyboardButton] = []
        for d in w:
            if d is None:
                row.append(InlineKeyboardButton(text=" ", callback_data="noop"))
            else:
                dt = date(y, m, d)
                if dt < today:
                    row.append(InlineKeyboardButton(text="·", callback_data="noop"))
                    continue
                label = f"[{d}]" if selected and dt == selected else str(d)
                row.append(InlineKeyboardButton(text=label, callback_data=f"cal:set:{dt.isoformat()}"))
        rows.append(row)

    rows.append([InlineKeyboardButton(text="🔥 Ближайшие дешёвые даты", callback_data="cal:near:7")])
    rows.append([InlineKeyboardButton(text="↩️ Назад", callback_data="back:dest")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def results_kb(visible: int, start_index: int, has_more: bool, can_add_return: bool = True) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for i in range(visible):
        idx = start_index + i
        rows.append([InlineKeyboardButton(text=f"Купить #{idx+1} 💳", callback_data=f"buy:{idx}")])
    nav = []
    if has_more:
        nav.append(InlineKeyboardButton(text="Показать ещё", callback_data="res:more"))
    if can_add_return:
        nav.append(InlineKeyboardButton(text="Добавить обратный билет ↩️", callback_data="ret:add"))
    nav.append(InlineKeyboardButton(text="Новый поиск", callback_data="reset"))
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
        link = item.get("link") or item.get("deeplink") or ""  # храним, не показываем
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
    # Заголовок с флагами стран (Вариант B)
    head_lines = [
        f"{flag_for_iata(q.origin)} {q.origin or '?'} → {flag_for_iata(q.destination)} {q.destination or '?'}",
        f"📅 {q.depart_date.strftime('%d.%m.%Y') if q.depart_date else '—'}",
    ]
    if q.return_date:
        head_lines.append(f"↩️ Обратно: {q.return_date.strftime('%d.%m.%Y')}")
    head_lines.append("")  # пустая строка

    if not q.results:
        return "
".join(head_lines + ["Пока нет результатов. Попробуйте другую дату или направление."])

    start = q.page * PAGE_SIZE
    chunk = q.results[start:start + PAGE_SIZE]
    if not chunk:
        return "
".join(head_lines + ["Все варианты показаны."])

    lines: List[str] = []
    for i, r in enumerate(chunk, start=start + 1):
        dt = r.get("departure_at")
        d_show, t_show = "—", "—"
        if isinstance(dt, str) and len(dt) >= 16 and "-" in dt and "T" in dt:
            _y, m, d = dt[:10].split("-")
            d_show = f"{d}.{m}"
            t_show = dt[11:16]
        airline = r.get("airline", "")
        price = fmt_price(r.get("price"))
        lines.append(
            f"{i}) 💸 {price}
"
            f"✈️ {airline}
"
            f"⏰ Вылет: {d_show} • {t_show}"
        )

    return "
".join(head_lines + lines) + "
"

# =============================
# BOT
# =============================
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

@dp.message(CommandStart())
async def on_start(m: Message):
    user_state[m.from_user.id] = QueryState()
    await m.answer("Привет! Выбери страну вылета:", reply_markup=countries_kb(stage="origin"))

@dp.message(F.text == "/ping")
async def ping(m: Message):
    await m.answer("pong")

@dp.message(F.text)
async def any_text(m: Message):
    if m.from_user.id not in user_state or not user_state[m.from_user.id].origin:
        await m.answer("Нажмите /start, чтобы выбрать направление и дату ✈️")
    else:
        await m.answer("Используйте кнопки выше или /start для нового поиска.")

@dp.callback_query(F.data.startswith("pick:origin:"))
async def pick_origin(c: CallbackQuery):
    _, _, iata, city = c.data.split(":", 3)
    st = user_state.setdefault(c.from_user.id, QueryState())
    st.origin = iata; st.origin_label = city
    await c.message.edit_text(
        f"Вылет: {iata}
Теперь выбери страну/город прибытия:",
        reply_markup=countries_kb(stage="dest", exclude_iata=iata),
    )
    await c.answer()

@dp.callback_query(F.data.startswith("pick:dest:"))
async def pick_dest(c: CallbackQuery):
    _, _, iata, city = c.data.split(":", 3)
    st = user_state.setdefault(c.from_user.id, QueryState())
    st.destination = iata; st.destination_label = city
    today = date.today()
    start = today if today.day <= 25 else (today.replace(day=28) + timedelta(days=4)).replace(day=1)
    await c.message.edit_text(
        f"Маршрут: {st.origin} → {st.destination}
Выбери дату вылета:",
        reply_markup=calendar_kb(start, selected=st.depart_date),
    )
    await c.answer()

@dp.callback_query(F.data.startswith("cal:prev:"))
async def cal_prev(c: CallbackQuery):
    iso = c.data.split(":", 2)[2]
    target = date.fromisoformat(iso)
    st = user_state.setdefault(c.from_user.id, QueryState())
    await c.message.edit_reply_markup(reply_markup=calendar_kb(target, selected=st.depart_date))
    await c.answer()

@dp.callback_query(F.data.startswith("cal:next:"))
async def cal_next(c: CallbackQuery):
    iso = c.data.split(":", 2)[2]
    target = date.fromisoformat(iso)
    st = user_state.setdefault(c.from_user.id, QueryState())
    await c.message.edit_reply_markup(reply_markup=calendar_kb(target, selected=st.depart_date))
    await c.answer()

@dp.callback_query(F.data.startswith("cal:set:"))
async def cal_set(c: CallbackQuery):
    iso = c.data.split(":", 2)[2]
    chosen = date.fromisoformat(iso)
    st = user_state.setdefault(c.from_user.id, QueryState())
    if st.adding_return:
        st.return_date = chosen
        st.adding_return = False
        await c.answer("Дата обратного вылета выбрана")
        text = build_results_text(st)
        start_idx = st.page * PAGE_SIZE
        has_more = len(st.results) > start_idx + PAGE_SIZE
        kb = results_kb(
            visible=min(PAGE_SIZE, len(st.results) - start_idx),
            start_index=start_idx,
            has_more=has_more,
            can_add_return=st.return_date is None,
        )
        await c.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
        return

    st.depart_date = chosen; st.page = 0
    await c.message.edit_text(
        "Запрос: {} → {} | {}
Ищу варианты...".format(
            st.origin, st.destination, st.depart_date.strftime("%d.%m.%Y")
        )
    )
    await c.answer("Ищу билеты…")

    tp_task = fetch_travelpayouts(st.origin, st.destination, st.depart_date, limit=20)
    avs_task = fetch_aviasales(st.origin, st.destination, st.depart_date, limit=20)
    tp_res, avs_res = await asyncio.gather(tp_task, avs_task)

    st.results = merge_results(tp_res, avs_res, limit=40)
    text = build_results_text(st)
    start_idx = st.page * PAGE_SIZE
    has_more = len(st.results) > start_idx + PAGE_SIZE
    kb = results_kb(
        visible=min(PAGE_SIZE, len(st.results) - start_idx),
        start_index=start_idx,
        has_more=has_more,
        can_add_return=st.return_date is None,
    )
    await c.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)

@dp.callback_query(F.data == "res:more")
async def res_more(c: CallbackQuery):
    st = user_state.get(c.from_user.id)
    if not st or not st.results:
        await c.answer("Сначала выберите маршрут и дату", show_alert=True)
        return
    st.page += 1
    text = build_results_text(st)
    if text == c.message.text:
        await c.answer("Больше результатов нет", show_alert=True)
        return
    start_idx = st.page * PAGE_SIZE
    has_more = len(st.results) > start_idx + PAGE_SIZE
    kb = results_kb(
        visible=min(PAGE_SIZE, max(0, len(st.results) - start_idx)),
        start_index=start_idx,
        has_more=has_more,
        can_add_return=st.return_date is None,
    )
    await c.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    await c.answer()

@dp.callback_query(F.data.startswith("buy:"))
async def buy_ticket(c: CallbackQuery):
    idx = int(c.data.split(":", 1)[1])
    st = user_state.get(c.from_user.id)
    if not st or not st.results or idx >= len(st.results):
        await c.answer("Элемент не найден", show_alert=True); return
    st.selected_idx = idx
    choice = st.results[idx]
    dt = choice.get("departure_at")
    dt_str = dt[:16].replace("T", " ") if isinstance(dt, str) else "—"

    # Сборка реф‑ссылки
    def build_ref_link() -> Optional[str]:
        if choice.get("link"):
            return choice.get("link")
        if REF_LINK_TEMPLATE:
            dt_out = (st.depart_date or date.today()).strftime("%Y-%m-%d")
            try:
                return REF_LINK_TEMPLATE.format(
                    origin=st.origin, destination=st.destination, date=dt_out, subid=REF_SUBID
                )
            except Exception:
                return None
        return None

    ref_url = build_ref_link()

    txt = (
        f"Вы выбрали вариант #{idx + 1}:
"
        f"Цена: {fmt_price(choice.get('price'))}
"
        f"Авиакомпания: {choice.get('airline', '')}
"
        f"Вылет: {dt_str}

"
        "Отправьте номер телефона для оформления покупки."
    )
    kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="Поделиться номером", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await c.message.answer(txt, reply_markup=kb)
    if ref_url:
        await c.message.answer(
            "Готово к оплате:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Купить на сайте", url=ref_url)]]
            ),
        )
    await c.answer()

@dp.message(F.contact)
async def got_contact(m: Message):
    st = user_state.get(m.from_user.id)
    if not st or st.selected_idx is None or not st.results:
        await m.answer("Спасибо! Мы свяжемся с вами."); return
    choice = st.results[st.selected_idx]
    phone = m.contact.phone_number
    dt = choice.get("departure_at")
    dt_str = dt[:16].replace("T", " ") if isinstance(dt, str) else "—"
    text = (
        "🧾 Заявка на покупку билета
"
        f"Маршрут: {st.origin} → {st.destination}
"
        f"Дата: {st.depart_date.strftime('%d.%m.%Y') if st.depart_date else '—'}
"
        f"Вариант: #{st.selected_idx + 1}
"
        f"Цена: {fmt_price(choice.get('price'))}
"
        f"Авиакомпания: {choice.get('airline', '')}
"
        f"Вылет: {dt_str}
"
        f"Телефон клиента: {phone}
"
        f"Пользователь: @{m.from_user.username or '-'} | {m.from_user.full_name}"
    )
    if MANAGERS_CHAT_ID:
        try:
            await bot.send_message(MANAGERS_CHAT_ID, text)
        except Exception as e:
            log.error(f"Send to managers failed: {e}")
            await m.answer("⚠️ Заявка создана, но не удалось отправить в менеджерский чат. Проверьте права бота в группе.")
            return
    await m.answer("Спасибо! Наш менеджер свяжется с вами в ближайшее время.")

@dp.callback_query(F.data == "back:dest")
async def back_to_dest(c: CallbackQuery):
    st = user_state.setdefault(c.from_user.id, QueryState())
    await c.message.edit_text(
        f"Вылет: {st.origin}
Выбери страну/город прибытия:",
        reply_markup=countries_kb(stage="dest", exclude_iata=st.origin),
    )
    await c.answer()

@dp.callback_query(F.data == "reset")
async def reset_flow(c: CallbackQuery):
    user_state[c.from_user.id] = QueryState()
    await c.message.edit_text("Новый поиск. Выбери страну вылета:", reply_markup=countries_kb(stage="origin"))
    await c.answer()

@dp.callback_query(F.data == "cal:near:7")
async def cal_near_7(c: CallbackQuery):
    st = user_state.get(c.from_user.id)
    if not st or not st.origin or not st.destination:
        await c.answer("Сначала выберите маршрут", show_alert=True); return
    base = st.depart_date or (date.today() + timedelta(days=1))
    days = [base + timedelta(days=i) for i in range(7)]
    tasks = [fetch_travelpayouts(st.origin, st.destination, d, limit=1) for d in days]
    results = await asyncio.gather(*tasks)
    lines = ["🔥 Ближайшие 7 дат:"]
    for d, r in zip(days, results):
        price = r[0].get("price") if r else None
        lines.append(f"• {d.strftime('%d.%m.%Y')} — {fmt_price(price) if price else '—'}")
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ Назад к календарю", callback_data=f"cal:back:{base.replace(day=1).isoformat()}")]])
    await c.message.edit_text("
".join(lines), reply_markup=kb)
    await c.answer()

@dp.callback_query(F.data.startswith("cal:back:"))
async def cal_back(c: CallbackQuery):
    iso = c.data.split(":", 2)[2]
    target = date.fromisoformat(iso)
    st = user_state.setdefault(c.from_user.id, QueryState())
    await c.message.edit_text(
        f"Маршрут: {st.origin} → {st.destination}
Выбери дату вылета:",
        reply_markup=calendar_kb(target, selected=st.depart_date),
    )
    await c.answer()

# =============================
# RUN
# =============================
async def main() -> None:
    log.info("Booting…")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        log.info("Webhook deleted (drop_pending_updates=True)")
    except Exception as e:
        log.warning(f"delete_webhook failed: {e}")
    me = await bot.get_me()
    log.info(f"Started as @{me.username} ({me.id})")
    try:
        if MANAGERS_CHAT_ID:
            await bot.send_message(MANAGERS_CHAT_ID, "✅ Бот запущен и готов принимать заявки.")
    except Exception as e:
        log.warning(f"Managers notify failed: {e}")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"]) 

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Bot stopped")
