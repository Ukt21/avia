import asyncio, os, re, logging, datetime as dt
from typing import Optional, List, Dict, Any

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.client.bot import DefaultBotProperties
from dotenv import load_dotenv
import aiohttp

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
API_TOKEN = os.getenv("AVIASALES_API_KEY") or os.getenv("TRAVELPAYOUTS_TOKEN")
MARKER = os.getenv("AVIASALES_MARKER", "")
SUBID = os.getenv("SUBID", "")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment")

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# простая карта город -> IATA
CITY2IATA = {
    # Узбекистан/ЦА
    "ташкент":"TAS","tashkent":"TAS","ташькент":"TAS",
    "самарканд":"SKD","samarkand":"SKD","бухара":"BHK","bukhara":"BHK",
    "нукус":"NCU","фергана":"FEG","ферган":"FEG","наманган":"NMA",
    # Популярные
    "стамбул":"IST","istanbul":"IST",
    "алматы":"ALA","alma-ata":"ALA","almaata":"ALA",
    "дубай":"DXB","dubai":"DXB",
    "москва":"MOW","moscow":"MOW",
    "санкт-петербург":"LED","питер":"LED","spb":"LED",
    "анкара":"ESB","анталья":"AYT",
}

ROUTE_HINT = "Введи маршрут и дату в одном сообщении. Примеры:\n" \
             "• <code>TAS IST 2025-11-05</code>\n" \
             "• <code>Ташкент — Стамбул 2025-11-05</code>"

def _normalize_city(token: str) -> str:
    t = token.lower().strip()
    if len(t) == 3 and t.isalpha():
        return t.upper()
    return CITY2IATA.get(t, "")

def parse_query(text: str) -> Optional[Dict[str, str]]:
    # Примеры: "TAS IST 2025-11-05", "Ташкент-Стамбул 2025-11-05", "Ташкент Стамбул 2025-11-05"
    text = re.sub(r"[–—>-]", " ", text)  # разделители в пробел
    parts = [p for p in text.split() if p]
    if len(parts) < 3:
        return None
    # возьмём первые два как города, последний как дату
    date = parts[-1]
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        return None
    orig = _normalize_city(parts[0])
    dest = _normalize_city(parts[1])
    if not orig or not dest or orig == dest:
        return None
    return {"origin": orig, "destination": dest, "date": date}

async def fetch_prices(session: aiohttp.ClientSession, origin: str, destination: str, date: str) -> List[Dict[str, Any]]:
    """
    Запрос к Travelpayouts Aviasales v3 prices_for_dates.
    Документация может отличаться, поэтому делаем максимально совместимо.
    """
    if not API_TOKEN:
        return []

    url = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"
    params = {
        "origin": origin,
        "destination": destination,
        "departure_at": date,
        "sorting": "price",
        "direct": False,
        "currency": "usd",
        "limit": 5,
        "page": 1,
        "token": API_TOKEN,
    }
    try:
        async with session.get(url, params=params, timeout=20) as resp:
            if resp.status != 200:
                logging.warning("API status %s: %s", resp.status, await resp.text())
                return []
            data = await resp.json()
            # ожидаем формат {"data":[{...}, ...]}
            return data.get("data", []) if isinstance(data, dict) else []
    except Exception as e:
        logging.exception("API error: %s", e)
        return []

def format_price_item(it: Dict[str, Any], origin: str, destination: str) -> str:
    price = it.get("price") or it.get("value")
    airline = it.get("airline", "") or it.get("airlines") or ""
    depart = it.get("departure_at") or it.get("departure_date") or ""
    transfers = it.get("transfers")
    transfers_txt = "без пересадок" if transfers == 0 else "с пересадкой" if transfers == 1 else "с пересадками"
    # Партнёрская ссылка если прилетит из API; иначе общая с маркером
    link = it.get("link") or ""
    if not link and MARKER:
        link = f"https://www.aviasales.com/?marker={MARKER}&utm_source=bot&sub_id={SUBID}&origin={origin}&destination={destination}&date={depart[:10]}"
    line = f"• {origin}→{destination} {depart[:10]} — <b>${price}</b> ({transfers_txt})"
    if airline:
        line += f" | {airline}"
    if link:
        line += f"\n<a href='{link}'>Открыть</a>"
    return line

@dp.message(CommandStart())
async def start(m: Message):
    await m.answer("Я на связи ✅\n" + ROUTE_HINT)

@dp.message(F.text)
async def handle_text(m: Message):
    q = parse_query(m.text)
    if not q:
        await m.answer("Не распознал запрос.\n" + ROUTE_HINT)
        return

    origin, destination, date = q["origin"], q["destination"], q["date"]
    await m.answer(f"Ищу самые дешёвые: <b>{origin} → {destination}</b> на {date}…")

    async with aiohttp.ClientSession() as session:
        items = await fetch_prices(session, origin, destination, date)

    if not items:
        await m.answer("Ничего не нашёл на эту дату. Попробуй соседние дни или другой маршрут.\n" + ROUTE_HINT)
        return

    lines = [format_price_item(it, origin, destination) for it in items]
    await m.answer("\n\n".join(lines), disable_web_page_preview=True)

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("✅ Webhook удалён. Запускаю polling…")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

   
            
   
