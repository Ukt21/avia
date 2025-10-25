# arzonuching/app/main.py
from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import List, Dict, Tuple

import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

# =========================
# Конфигурация из ENV
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
TP_API_TOKEN = os.getenv("TP_API_TOKEN", "").strip()   # если работаешь через API
TP_MARKER = os.getenv("TP_MARKER", "").strip()         # для deeplink ссылок

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN не задан в переменных окружения")

# =========================
# Инициализация бота
# =========================
bot = Bot(token=BOT_TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher()


# =========================
# Помощники форматирования
# =========================
def build_ticket_card(result: Dict) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Превращает один результат рейса в текст + inline-кнопку.
    Ссылка скрыта под кнопкой.
    """
    airline = result.get("airline", "Авиакомпания")
    origin = result.get("origin", "")
    destination = result.get("destination", "")
    depart_date = result.get("depart_date", "")
    return_date = result.get("return_date", "")
    price = result.get("price", "Цена не найдена")
    ticket_url = result.get("url") or "https://aviasales.com"

    text = (
        f"✈️ <b>{origin}</b> → <b>{destination}</b>\n"
        f"🛫 Авиакомпания: {airline}\n"
        f"📅 Даты: {depart_date} — {return_date}\n"
        f"💰 Цена: <b>от {price} сум</b>"
    )

    button = InlineKeyboardButton(text="Посмотреть билеты 🔎", url=ticket_url)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[button]])
    return text, keyboard


def build_deeplink_url(origin: str, destination: str, depart_date: str, return_date: str) -> str:
    """
    Универсальная deeplink-ссылка Travelpayouts/Aviasales без видимой URL в тексте.
    Работает даже если у тебя нет прямого API-запроса к ценам.
    """
    marker = TP_MARKER or "000000"  # на крайний случай
    # Валюта UZS, 1 взрослый, без детей
    url = (
        "https://tp.media/r"
        f"?marker={marker}"
        "&campaign_id=100"
        "&trs=chatbot"
        "&search_type=front"
        "&service=airtickets"
        "&adults=1&children=0&infants=0"
        "&currency=uzs"
        f"&origin={origin.upper()}"
        f"&destination={destination.upper()}"
        f"&depart_date={depart_date}"
        f"&return_date={return_date}"
    )
    return url


# =========================
# Демо-загрузчик результатов
# =========================
async def fetch_travelpayouts(origin: str,
                              destination: str,
                              depart_date: str,
                              return_date: str,
                              limit: int = 5) -> List[Dict]:
    """
    Вариант №1: если используешь только deeplink (без цен с API).
    Мы вернем список "псевдо-результатов" с 1-2 карточками, где ссылка — deeplink.
    Это безопасно и стабильно. Позже можно заменить на реальный API-ответ.
    """
    deeplink = build_deeplink_url(origin, destination, depart_date, return_date)

    # Пример 2 карточек. Можешь оставить одну — решай сам.
    demo = [
        {
            "airline": "Turkish Airlines",
            "origin": origin.upper(),
            "destination": destination.upper(),
            "depart_date": depart_date,
            "return_date": return_date,
            "price": "—",  # без API точной цены нет, покажем прочерк
            "url": deeplink,
        },
        {
            "airline": "Uzbekistan Airways",
            "origin": origin.upper(),
            "destination": destination.upper(),
            "depart_date": depart_date,
            "return_date": return_date,
            "price": "—",
            "url": deeplink,
        },
    ]
    return demo[:max(1, min(limit, len(demo)))]

    # Вариант №2 (расскомментируй и подставь правильный endpoint, если у тебя есть API):
    # if not TP_API_TOKEN:
    #     return demo[:1]
    #
    # api_url = "https://api.travelpayouts.com/..."  # твой реальный эндпоинт
    # headers = {"X-Access-Token": TP_API_TOKEN}
    # params = {...}
    # async with aiohttp.ClientSession(headers=headers) as s:
    #     async with s.get(api_url, params=params, timeout=20) as r:
    #         if r.status != 200:
    #             return demo[:1]
    #         data = await r.json()
    #         # Сконвертируй data в список dict с ключами, которые ждёт build_ticket_card()
    #         results = [...]
    #         return results


# =========================
# Хендлеры
# =========================
@dp.message(Command("start"))
async def on_start(message: Message) -> None:
    text = (
        "Привет! Я помогу найти авиабилеты.\n\n"
        "Формат команды для быстрого поиска:\n"
        "<code>/tickets TAS IST 2025-11-01 2025-11-10</code>\n\n"
        "Где:\n"
        "• <b>TAS</b> — город вылета (IATA)\n"
        "• <b>IST</b> — город прибытия (IATA)\n"
        "• даты — в формате <code>YYYY-MM-DD</code>\n\n"
        "Ссылки будут скрыты в кнопке «Посмотреть билеты»."
    )
    await message.answer(text)


@dp.message(Command("tickets"))
async def tickets_cmd(message: Message) -> None:
    """
    Пример: /tickets TAS IST 2025-11-01 2025-11-10
    """
    parts = message.text.split()
    if len(parts) != 6:
        await message.answer(
            "Нужно так:\n"
            "<code>/tickets TAS IST 2025-11-01 2025-11-10</code>"
        )
        return

    _, origin, destination, depart_date, return_date = parts[:5+1][0], parts[1], parts[2], parts[3], parts[4]

    # Валидация дат
    for d in (depart_date, return_date):
        try:
            datetime.strptime(d, "%Y-%m-%d")
        except ValueError:
            await message.answer("Неверный формат даты. Используй YYYY-MM-DD.")
            return

    # Получаем результаты
    try:
        results = await fetch_travelpayouts(origin, destination, depart_date, return_date, limit=5)
    except Exception as e:
        await message.answer(f"Ошибка поиска: {e}")
        return

    if not results:
        await message.answer("Билетов не найдено.")
        return

    # Рассылаем карточки с кнопкой (ссылка не видна)
    for result in results:
        text, keyboard = build_ticket_card(result)
        await message.answer(text, reply_markup=keyboard)


# =========================
# Точка входа
# =========================
async def main() -> None:
    # На Render работаем в режиме polling
    # Убедись, что у тебя удалён webhook у бота (у тебя уже удален)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass



   
