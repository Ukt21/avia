# main.py
# Aiogram v3 — поиск авиабилетов-агрегатор: ТОП-3 бесплатно, остальные по подписке.
# Кнопки вместо «голых» ссылок. Структура для реальной интеграции с Travelpayouts/Aviasales, Kiwi (Tequila), Skyscanner.
# Авторежим: long-polling.

import os
import asyncio
import hashlib
from dataclasses import dataclass
from datetime import date, timedelta, datetime
from typing import List, Optional, Tuple

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

# ============ ENV ============
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
TP_MARKER = os.getenv("TP_MARKER", "").strip()            # Travelpayouts Partner ID (marker)  :contentReference[oaicite:1]{index=1}
TP_SUBID_DEFAULT = os.getenv("TP_SUBID_DEFAULT", "bot")   # дефолтный SubID (можно переопределять динамически)  :contentReference[oaicite:2]{index=2}

if not BOT_TOKEN:
    raise RuntimeError("Укажи BOT_TOKEN в .env")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

# ============ ПАМЯТЬ ПОДПИСОК (демо) ============
# Для продакшена замени на БД (Postgres). Здесь — in-memory.
SUBSCRIBERS = set()  # tg_id пользователей с активной подпиской

# ============ МОДЕЛИ ============
@dataclass
class FlightOption:
    provider: str        # "aviasales" | "kiwi" | "skyscanner" | ...
    price: int           # в условной валюте (например, UZS или RUB)
    currency: str
    duration_min: int
    stops: int
    dep_time: str        # "2025-11-01 09:40"
    arr_time: str        # "2025-11-01 13:10"
    deep_link: str       # целевой URL (на стороне поставщика/партнёра)

@dataclass
class SearchParams:
    origin: str
    destination: str
    depart: date

# ============ УТИЛИТЫ ============
def human_duration(minutes: int) -> str:
    h = minutes // 60
    m = minutes % 60
    return f"{h} ч {m:02d} мин" if h else f"{m} мин"

def hash_params(p: SearchParams) -> str:
    raw = f"{p.origin}-{p.destination}-{p.depart.isoformat()}"
    return hashlib.md5(raw.encode()).hexdigest()[:8]

def make_subid(user_id: int, p: SearchParams) -> str:
    # Пример: subID для статистики кампаний и пользователей (Travelpayouts поддерживает SubID)  :contentReference[oaicite:3]{index=3}
    return f"{TP_SUBID_DEFAULT}_{user_id}_{hash_params(p)}"

# ============ АФФИЛИАТНЫЕ ШАБЛОНЫ ССЫЛОК ============
# Важно: чтобы не ошибиться в параметрах партнёрских ссылок,
# сгенерируй короткую партнёрскую ссылку в личном кабинете Travelpayouts и подставляй сюда шаблон.  :contentReference[oaicite:4]{index=4}
AFFILIATE_TEMPLATES = {
    # Aviasales через Travelpayouts:
    # Рекомендуется использовать короткие tp.media ссылки с marker и динамическим subid (создаётся в кабинете)  :contentReference[oaicite:5]{index=5}
    "aviasales": "https://tp.media/r?marker={marker}&subid={subid}&redirect=true&url={encoded_search_url}",

    # Kiwi (пример deeplink структуры поиска; для партнёрки см. инструкции Kiwi/Travelpayouts)  :contentReference[oaicite:6]{index=6}
    "kiwi": "https://www.kiwi.com/deep?from={orig}&to={dest}&departure={depart}",

    # Skyscanner реферал (Affiliate Link API; нужен mediaPartnerId)  :contentReference[oaicite:7]{index=7}
    "skyscanner": "https://www.skyscanner.net/g/referrals/v1/flights/search?mediaPartnerId={partner_id}&origin={orig}&destination={dest}&outboundDate={depart}",
}

import urllib.parse

def build_affiliate_link(opt: FlightOption, p: SearchParams, user_id: int) -> str:
    subid = make_subid(user_id, p)
    if opt.provider == "aviasales":
        # Здесь encoded_search_url должен вести на нужную страницу Aviasales (или готовую короткую tp.media link).
        # Для начала используем универсальный поиск по направлению и дате:
        avia_search_url = f"https://aviasales.com/search/{p.origin}{p.depart.strftime('%d%m')}{p.destination}1"
        return AFFILIATE_TEMPLATES["aviasales"].format(
            marker=urllib.parse.quote(TP_MARKER or "YOUR_MARKER"),
            subid=urllib.parse.quote(subid),
            encoded_search_url=urllib.parse.quote(avia_search_url, safe="")
        )
    elif opt.provider == "kiwi":
        return AFFILIATE_TEMPLATES["kiwi"].format(
            orig=p.origin, dest=p.destination, depart=p.depart.isoformat()
        )
    elif opt.provider == "skyscanner":
        return AFFILIATE_TEMPLATES["skyscanner"].format(
            partner_id=urllib.parse.quote(TP_MARKER or "YOUR_PARTNER_ID"),
            orig=p.origin, dest=p.destination, depart=p.depart.isoformat()
        )
    # запасной вариант — отдать то, что пришло от источника
    return opt.deep_link

# ============ ИМИТАЦИЯ ПОИСКА (заглушка) ============
# В продакшене здесь делай параллельные запросы к API:
# - Aviasales/Travelpayouts Flights Search API (marker обязателен)  :contentReference[oaicite:8]{index=8}
# - Kiwi Tequila /search  :contentReference[oaicite:9]{index=9}
# - Skyscanner Affiliates Link API для рефералов  :contentReference[oaicite:10]{index=10}
import random

def search_flights(params: SearchParams) -> List[FlightOption]:
    # Генерируем 8 «похожих» результатов
    random.seed(hash_params(params))
    base_price = random.randint(800000, 1800000)  # пример цены в суммах/рублях — подстрой под свою валюту
    results: List[FlightOption] = []
    providers = ["aviasales", "kiwi", "skyscanner"]
    base_time = datetime.combine(params.depart, datetime.min.time()).replace(hour=8, minute=0)
    for i in range(8):
        provider = providers[i % len(providers)]
        price = max(100000, int(base_price * (0.9 + i*0.03)))
        duration = random.randint(100, 480)
        stops = random.choice([0, 1, 1, 2])
        dep_dt = base_time + timedelta(minutes=random.randint(0, 720))
        arr_dt = dep_dt + timedelta(minutes=duration)
        results.append(FlightOption(
            provider=provider,
            price=price,
            currency="UZS",
            duration_min=duration,
            stops=stops,
            dep_time=dep_dt.strftime("%Y-%m-%d %H:%M"),
            arr_time=arr_dt.strftime("%Y-%m-%d %H:%M"),
            deep_link="",
        ))
    # Простая сортировка по цене, затем по длительности
    results.sort(key=lambda x: (x.price, x.duration_min, x.stops))
    return results

# ============ FSM ============
class Flow(StatesGroup):
    selecting_origin = State()
    selecting_destination = State()
    selecting_date = State()

# Небольшой справочник популярных IATA (можно расширить)
POPULAR_IATA = [
    ("TAS", "Ташкент"), ("DXB", "Дубай"), ("IST", "Стамбул"),
    ("ALA", "Алматы"), ("MOW", "Москва (любой)"), ("LED", "Санкт-Петербург"),
    ("DEL", "Дели"), ("FRA", "Франкфурт"), ("DOH", "Доха"),
]

def iata_keyboard(step: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for code, name in POPULAR_IATA:
        kb.button(text=f"{name} ({code})", callback_data=f"{step}:{code}")
    kb.button(text="Другое (ввести)", callback_data=f"{step}:other")
    kb.adjust(2)
    return kb.as_markup()

def dates_keyboard(start: date, days: int = 21) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i in range(days):
        d = start + timedelta(days=i)
        label = d.strftime("%d %b (%a)")
        kb.button(text=label, callback_data=f"date:{d.isoformat()}")
    kb.adjust(3)
    return kb.as_markup()

# ============ ХЕНДЛЕРЫ ============
@dp.message(CommandStart())
async def on_start(m: Message, state: FSMContext):
    await state.clear()
    await m.answer(
        "✈️ Привет! Я подберу лучшие билеты.\n"
        "Выбери город вылета:",
        reply_markup=iata_keyboard("orig")
    )
    await state.set_state(Flow.selecting_origin)

@dp.callback_query(F.data.startswith("orig:"))
async def pick_origin(cq: CallbackQuery, state: FSMContext):
    _, code = cq.data.split(":")
    if code == "other":
        await cq.message.answer("Введи IATA код города вылета (например, TAS):")
        await state.set_state(Flow.selecting_origin)
        await cq.answer()
        return
    await state.update_data(origin=code)
    await cq.message.edit_text(f"Вылет: {code}\nТеперь выбери город прилёта:")
    await cq.message.edit_reply_markup(reply_markup=iata_keyboard("dest"))
    await state.set_state(Flow.selecting_destination)
    await cq.answer()

@dp.message(Flow.selecting_origin)
async def origin_manual(m: Message, state: FSMContext):
    code = m.text.strip().upper()[:3]
    await state.update_data(origin=code)
    await m.answer(f"Вылет: {code}\nТеперь выбери город прилёта:", reply_markup=iata_keyboard("dest"))
    await state.set_state(Flow.selecting_destination)

@dp.callback_query(F.data.startswith("dest:"))
async def pick_dest(cq: CallbackQuery, state: FSMContext):
    _, code = cq.data.split(":")
    if code == "other":
        await cq.message.answer("Введи IATA код города прилёта (например, IST):")
        await state.set_state(Flow.selecting_destination)
        await cq.answer()
        return
    await state.update_data(destination=code)
    await cq.message.edit_text(
        f"Направление: { (await state.get_data()).get('origin') } → {code}\nВыбери дату вылета:"
    )
    today = date.today()
    await cq.message.edit_reply_markup(reply_markup=dates_keyboard(today))
    await state.set_state(Flow.selecting_date)
    await cq.answer()

@dp.message(Flow.selecting_destination)
async def dest_manual(m: Message, state: FSMContext):
    code = m.text.strip().upper()[:3]
    data = await state.get_data()
    origin = data.get("origin", "???")
    await state.update_data(destination=code)
    await m.answer(f"Направление: {origin} → {code}\nВыбери дату вылета:", reply_markup=dates_keyboard(date.today()))
    await state.set_state(Flow.selecting_date)

@dp.callback_query(F.data.startswith("date:"))
async def pick_date(cq: CallbackQuery, state: FSMContext):
    _, dstr = cq.data.split(":")
    data = await state.get_data()
    p = SearchParams(
        origin=data["origin"],
        destination=data["destination"],
        depart=date.fromisoformat(dstr)
    )
    results = search_flights(p)

    # ТОП-3 бесплатно
    free = results[:3]
    paid = results[3:]

    kb = InlineKeyboardBuilder()
    text_lines = ["🧭 Результаты (ТОП-3 бесплатно):\n"]
    for idx, opt in enumerate(free, start=1):
        link = build_affiliate_link(opt, p, cq.from_user.id)
        label = f"Купить — {opt.price} {opt.currency}"
        # Показываем только кнопку; сырой линк не отображается
        kb.row(InlineKeyboardButton(text=label, url=link))
        card = (
            f"{idx}) {opt.provider.title()} • {opt.price} {opt.currency}\n"
            f"   Вылет: {opt.dep_time}  Прилёт: {opt.arr_time}\n"
            f"   В пути: {human_duration(opt.duration_min)}  Пересадок: {opt.stops}\n"
        )
        text_lines.append(card)

    if paid:
        if cq.from_user.id in SUBSCRIBERS:
            text_lines.append(f"\n🔓 Подписка активна — показываю ещё {len(paid)} вариантов:")
            for opt in paid:
                link = build_affiliate_link(opt, p, cq.from_user.id)
                label = f"Купить — {opt.price} {opt.currency}"
                kb.row(InlineKeyboardButton(text=label, url=link))
        else:
            text_lines.append(
                f"\n🔒 Ещё {len(paid)} вариантов доступны по подписке 50 000/мес."
            )
            kb.row(InlineKeyboardButton(text="Подписка — 50 000/мес", callback_data=f"subscribe:{hash_params(p)}"))

    kb.row(InlineKeyboardButton(text="Новый поиск", callback_data="newsearch"))
    await cq.message.edit_text("\n".join(text_lines))
    await cq.message.edit_reply_markup(kb.as_markup())
    await state.clear()
    await cq.answer()

@dp.callback_query(F.data == "newsearch")
async def new_search(cq: CallbackQuery, state: FSMContext):
    await state.clear()
    await cq.message.edit_text("Выбери город вылета:", reply_markup=iata_keyboard("orig"))
    await state.set_state(Flow.selecting_origin)
    await cq.answer()

# Подписка (демо): переключатель. В проде подключи Telegram Payments или локальный провайдер.
@dp.callback_query(F.data.startswith("subscribe:"))
async def subscribe_flow(cq: CallbackQuery):
    uid = cq.from_user.id
    if uid in SUBSCRIBERS:
        SUBSCRIBERS.remove(uid)
        await cq.answer("Подписка выключена (демо). Подключи оплату в проде.", show_alert=True)
    else:
        SUBSCRIBERS.add(uid)
        await cq.answer("Подписка активирована (демо). Теперь доступны все результаты.", show_alert=True)

@dp.message(Command("subscribe"))
async def subscribe_cmd(m: Message):
    uid = m.from_user.id
    if uid in SUBSCRIBERS:
        await m.answer("У тебя уже активна подписка (демо).")
    else:
        SUBSCRIBERS.add(uid)
        await m.answer("Подписка активирована (демо). Для продакшена подключи реальную оплату.")

@dp.message(Command("status"))
async def status_cmd(m: Message):
    uid = m.from_user.id
    is_sub = "активна" if uid in SUBSCRIBERS else "не активна"
    await m.answer(f"Статус подписки: {is_sub}.")

# Команда помощи
@dp.message(Command("help"))
async def help_cmd(m: Message):
    await m.answer(
        "Как это работает:\n"
        "1) Выбираешь вылет, прилёт и дату.\n"
        "2) Получаешь 3 лучших варианта бесплатно.\n"
        "3) Остальные — по подписке 50 000/мес.\n\n"
        "Ссылки показываю только кнопками «Купить» без отображения URL.\n"
        "Поддерживаются партнёрские маркеры/SubID (Travelpayouts)."
    )

# ============ Точка входа ============
async def main():
    print("Bot started.")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
