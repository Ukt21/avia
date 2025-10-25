import asyncio, os, logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.enums import ParseMode
from aiogram.client.bot import DefaultBotProperties
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set in environment")

logging.basicConfig(level=logging.INFO)

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

@dp.message(CommandStart())
async def on_start(message: Message):
    await message.answer("✅ Я на связи. Напиши маршрут и дату для поиска.")

@dp.message(F.text)
async def any_text(message: Message):
    await message.answer(f"Принял: {message.text}")

async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("✅ Webhook удалён. Запускаю polling...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


   
            
   
