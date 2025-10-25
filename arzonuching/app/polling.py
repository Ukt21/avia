
from __future__ import annotations
import asyncio
from .bot_logic import dp, bot

if __name__ == "__main__":
    asyncio.run(dp.start_polling(bot))
