
from __future__ import annotations
import os, asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from dotenv import load_dotenv

from .bot_logic import bot, dp
from .payments import SERVICE_FEE_AMOUNT

# --- вставить В НАЧАЛЕ файла, рядом с другими import ---
import os, aiohttp
from datetime import datetime

TP_TOKEN = os.getenv("TP_TOKEN", "")
MARKER   = os.getenv("MARKER", "")
SUB_ID   = os.getenv("SUB_ID", "")

def build_dates(user_text: str):
    dt = datetime.strptime(user_text.strip(), "%Y-%m-%d")   # формат 2025-10-28
    api_date = dt.strftime("%Y-%m-%d")                      # 2025-10-28
    link_date = dt.strftime("%d%m")                         # 2810
    return api_date, link_date

def clean_iata(code: str) -> str:
    code = (code or "").strip().upper()
    if len(code) != 3:
        raise ValueError("IATA должен быть из 3 букв, например TAS")
    return code

async def find_tickets(origin, destination, user_date):
    origin = clean_iata(origin)
    destination = clean_iata(destination)
    api_date, link_date = build_dates(user_date)

    # 1) API Travelpayouts
    url = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
    params = {
        "origin": origin,
        "destination": destination,
        "depart_date": api_date,
        "one_way": True,
        "direct": False,
        "limit": 10,
        "sorting": "price",
        "currency": "usd",
        "token": TP_TOKEN
    }

    results = []
    async with aiohttp.ClientSession() as s:
        async with s.get(url, params=params, timeout=15) as r:
            data = await r.json()
            if data.get("data"):
                results = data["data"]

    # 2) Всегда готовим рабочую ссылку на сайт
    search_path = f"{origin}{link_date}{destination}1"     # ORIG DDMM DEST 1
    avia_direct = f"https://www.aviasales.com/search/{search_path}"
    from aiohttp.helpers import quote
    deeplink = (
        "https://tp.media/r"
        f"?marker={MARKER}"
        f"&sub_id={SUB_ID}"
        f"&search_url={quote(avia_direct, safe='')}"
    )

    # для проверки в логах
    print("DEEPLINK:", deeplink, flush=True)
    return results, deeplink

async def reply_tickets(message, origin, destination, date_text):
    try:
        results, link = await find_tickets(origin, destination, date_text)
    except Exception as e:
        await message.answer(f"Ошибка в параметрах: {e}\nНапример так: 2025-11-15")
        return

    if results:
        lines = []
        for r in results[:5]:
            price = r.get("price")
            airline = r.get("airline") or "—"
            dep = (r.get("departure_at","")[:16]).replace("T"," ")
            lines.append(f"• {airline} {dep} — от {price} USD")
        await message.answer("\n".join(lines))
        await message.answer(f"Все варианты: {link}")
    else:
        await message.answer("По API ничего не пришло. Открой полный поиск, билеты есть:")
        await message.answer(link)


load_dotenv()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "change_me")
AFFILIATE_URL = os.getenv("AFFILIATE_URL", "")


app = FastAPI(title="ArzonUching")

@app.get("/healthz")
async def healthz():
    return {"status": "ok", "service_fee": SERVICE_FEE_AMOUNT}

@app.post(f"/bot/{{secret}}")
async def telegram_webhook(secret: str, request: Request):
    if secret != WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="forbidden")
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return PlainTextResponse("ok")

# Payme webhook (заглушка, настройте проверку подписи и статусов по докам Payme)
@app.post("/payme/webhook")
async def payme_webhook(request: Request):
    payload = await request.json()
    # TODO: проверить подпись / X-Auth согласно документации Payme (developer.help.paycom.uz)
    # В демо просто отвечаем 200 OK
    return {"result": "accepted"}
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.filters import Command

@dp.message(Command("tickets"))
async def tickets_cmd(message: Message):
    if not AFFILIATE_URL:
        await message.answer("Ссылка временно недоступна.")
        return
    
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Найти билеты ✈️", url=AFFILIATE_URL)]
        ]
    )
    
    await message.answer(
        "Перейдите по ссылке, чтобы найти авиабилеты:",
        reply_markup=kb
    )

