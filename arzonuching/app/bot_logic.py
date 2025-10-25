
from __future__ import annotations
import os, asyncio, aiohttp
from datetime import datetime
from typing import Dict, Any, List

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .aviasales import fetch_cheapest
from .payments import create_service_fee_invoice

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CURRENCY = os.getenv("CURRENCY", "UZS")

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

UZ_ORIGINS = [
    {"city":"Ташкент", "code":"TAS"},
    {"city":"Самарканд", "code":"SKD"},
    {"city":"Андижан", "code":"AZN"},
]
RU_DESTS = [
    {"city":"Москва (все аэропорты)", "codes":["SVO","DME","VKO"]},
    {"city":"Санкт-Петербург (LED)", "codes":["LED"]},
]
UAE_DESTS = [
    {"city":"Дубай (DXB/DWC)", "codes":["DXB","DWC"]},
    {"city":"Шарджа (SHJ)", "codes":["SHJ"]},
]
TR_DESTS = [
    {"city":"Стамбул (IST/SAW)", "codes":["IST","SAW"]},
    {"city":"Анкара (ESB)", "codes":["ESB"]},
]

USER_STATE: Dict[int, Dict[str,Any]] = {}

def route_keyboard() -> InlineKeyboardBuilder:
    kb = InlineKeyboardBuilder()
    kb.button(text="🇷🇺 Узбекистан → Россия", callback_data="dir:ru")
    kb.button(text="🇦🇪 Узбекистан → Дубай/ОАЭ", callback_data="dir:uae")
    kb.button(text="🇹🇷 Узбекистан → Турция", callback_data="dir:tr")
    kb.adjust(1,1,1)
    return kb

def city_keyboard(origins, dest_groups, tag):
    kb = InlineKeyboardBuilder()
    for o in origins:
        kb.button(text=f"🛫 {o['city']}", callback_data=f"orig:{tag}:{o['code']}")
    kb.adjust(2)
    kb.row()
    for g in dest_groups:
        kb.button(text=f"🛬 {g['city']}", callback_data=f"destgrp:{tag}:{g['city']}")
    kb.adjust(2)
    kb.button(text="⬅️ Назад", callback_data="back:menu")
    return kb

def date_keyboard():
    kb = InlineKeyboardBuilder()
    kb.button(text="Сегодня", callback_data="date:today")
    kb.button(text="Завтра", callback_data="date:tomorrow")
    kb.button(text="🗓 Ввести дату", callback_data="date:manual")
    kb.button(text="⬅️ Назад", callback_data="back:routes")
    kb.adjust(2,2)
    return kb

def format_card(x: Dict[str,Any]) -> str:
    dt = datetime.fromisoformat(x["departure_at"].replace("Z",""))
    tr = "без пересадок" if (x.get("transfers") or 0) == 0 else f"{x.get('transfers')} перес."
    return (
        f"💸 <b>{x['price']} {CURRENCY}</b> • {tr}\n"
        f"🛫 {x['origin']} → {x['destination']} • {dt.strftime('%d.%m %H:%M')}\n"
        f"✈️ {x.get('airline','')} {x.get('flight_number','')}\n"
        f"🔗 <a href='{x['link']}'>Открыть на сайте</a>"
    )

@dp.message(Command("start"))
async def start_cmd(m: Message):
    await m.answer(
        "Привет! Я ArzonUching — найду самые дешёвые авиабилеты по твоим направлениям.\n"
        "Сначала покажу ТОП‑3 бесплатно. Больше вариантов — за сервисный сбор 50 000 сум.",
        reply_markup=route_keyboard().as_markup()
    )

@dp.callback_query(F.data.startswith("dir:"))
async def pick_dir(c: CallbackQuery):
    tag = c.data.split(":")[1]
    await c.answer()
    if tag == "ru":
        kb = city_keyboard(UZ_ORIGINS, RU_DESTS, tag)
        txt = "Выбери вылет из Узбекистана и группу направлений в Россию:"
    elif tag == "uae":
        kb = city_keyboard(UZ_ORIGINS, UAE_DESTS, tag)
        txt = "Выбери вылет из Узбекистана и направление в ОАЭ:"
    else:
        kb = city_keyboard(UZ_ORIGINS, TR_DESTS, tag)
        txt = "Выбери вылет из Узбекистана и направление в Турцию:"
    await c.message.edit_text(txt, reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("orig:"))
async def set_origin(c: CallbackQuery):
    _, tag, iata = c.data.split(":")
    st = USER_STATE.setdefault(c.from_user.id, {})
    st["tag"] = tag; st["origin"] = iata
    await c.answer("Город вылета установлен")
    # Попросим направление снова (кнопки уже есть на экране)

@dp.callback_query(F.data.startswith("destgrp:"))
async def set_dest_group(c: CallbackQuery):
    _, tag, name = c.data.split(":")
    st = USER_STATE.setdefault(c.from_user.id, {})
    st["tag"] = tag; st["dest_group"] = name
    await c.message.edit_text(
        "Ок, выбери дату или введи вручную (формат ГГГГ-ММ-ДД):",
        reply_markup=date_keyboard().as_markup()
    )

@dp.callback_query(F.data.startswith("date:"))
async def set_date(c: CallbackQuery):
    _, val = c.data.split(":")
    if val == "manual":
        await c.message.edit_text("Отправь дату сообщением: например 2025-11-15")
    else:
        if val == "today":
            dep = datetime.now().strftime("%Y-%m-%d")
        else:
            dep = (datetime.now()+__import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")
        await run_search(c, dep)

@dp.message(F.text.regexp(r"^\d{4}-\d{2}-\d{2}$"))
async def manual_date(m: Message):
    await run_search(m, m.text.strip())

async def run_search(ctx, dep_str: str):
    uid = ctx.from_user.id
    st = USER_STATE.get(uid, {})
    origin = st.get("origin"); tag = st.get("tag"); dest_group_name = st.get("dest_group")
    if not all([origin, tag, dest_group_name]):
        reply = ctx.message.reply if hasattr(ctx, 'message') else ctx.reply
        await reply("Не хватает данных запроса. Запусти заново: /start"); return

    dest_groups = RU_DESTS if tag=="ru" else UAE_DESTS if tag=="uae" else TR_DESTS
    grp = next((g for g in dest_groups if g["city"]==dest_group_name), None)
    if not grp:
        reply = ctx.message.reply if hasattr(ctx, 'message') else ctx.reply
        await reply("Не удалось определить направление. /start"); return

    dep_date = datetime.strptime(dep_str, "%Y-%m-%d")
    reply = ctx.message.reply if hasattr(ctx, 'message') else ctx.reply
    await reply("Ищу самые дешёвые…")

    all_offers: List[Dict[str,Any]] = []
    async with aiohttp.ClientSession() as session:
        for dest in grp["codes"]:
            offs = await fetch_cheapest(session, origin, dest, dep_date, days_flex=3, currency=CURRENCY)
            for o in offs:
                o["destination"] = dest
            all_offers.extend(offs)

    if not all_offers:
        await reply("Ничего не нашлось. Попробуй другую дату/направление."); return

    all_offers.sort(key=lambda z: z["price"] or 9e12)
    free = all_offers[:3]
    paid = all_offers[3:10]

    free_text = "\n\n".join([f"{i+1}) "+format_card(x) for i,x in enumerate(free)])
    msg = "🎯 <b>Самые дешёвые (бесплатно):</b>\n\n" + free_text

    if paid:
        inv = create_service_fee_invoice(uid)
        pay_link = inv.get("pay_link", "https://example.com/pay")  # fallback
        msg += ("\n\n— — —\n"
                "Чтобы открыть ещё 7+ вариантов, календарь цен и фильтры, оплати сервисный сбор 50 000 сум.\n"
                f"<a href='{pay_link}'>Оплатить сервисный сбор</a>")
    await reply(msg, disable_web_page_preview=True)
    # === Кнопка на любое сообщение ===
import os
from aiogram import F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

AFFILIATE_URL = os.getenv("AFFILIATE_URL", "")

@dp.message(F.text)
async def send_affiliate_on_any_text(message: Message):
    """
    Быстрый сценарий: на любой текст даём кнопку с партнёрской ссылкой.
    Так пользователь видит «есть билеты» на сайте-партнёре, а ты получаешь комиссию.
    """
    if not AFFILIATE_URL:
        await message.answer("Ссылка временно недоступна. Попробуйте позже.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Смотреть билеты ✈️", url=AFFILIATE_URL)]
        ]
    )
    await message.answer("Нажмите, чтобы посмотреть доступные варианты:", reply_markup=kb)

