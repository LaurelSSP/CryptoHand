# app.py

import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from config import BOT_TOKEN
from handlers.user import user_router
from handlers.admin import admin_router
# from handlers.worker import worker_router  

async def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Регистрация роутеров
    dp.include_router(admin_router)
    dp.include_router(user_router)
    # dp.include_router(worker_router)  

    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
