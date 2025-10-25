
from __future__ import annotations
import os, asyncio
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from dotenv import load_dotenv

from .bot_logic import bot, dp
from .payments import SERVICE_FEE_AMOUNT

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

