# handlers/worker.py

from aiogram import Router, F
from aiogram.types import Message
from config import WORKER_ID, EXTEND_WORK_TIME, IS_BOT_ACTIVE
from datetime import datetime, timedelta
import logging

worker_router = Router()
logger = logging.getLogger(__name__)

# Флаг для отслеживания времени продления
extend_time = None

@worker_router.message(F.from_user.id == WORKER_ID)
async def worker_response(message: Message):
    global IS_BOT_ACTIVE, extend_time
    if message.text == "Ок":
        # Рабочий подтверждает закрытие
        await message.answer("Бот будет закрыт.")
    elif message.text == "Продлить на 30 минут":
        # Рабочий продлевает работу
        extend_time = datetime.now() + timedelta(minutes=EXTEND_WORK_TIME)
        IS_BOT_ACTIVE = True
        await message.answer(f"Работа бота продлена на {EXTEND_WORK_TIME} минут.")
        logger.info(f"Рабочий продлил работу бота до {extend_time}.")
    else:
        await message.answer("Пожалуйста, выберите действие из меню.")

# Функция для проверки продления рабочего времени
async def check_extend_time():
    global IS_BOT_ACTIVE, extend_time
    if extend_time and datetime.now() >= extend_time:
        IS_BOT_ACTIVE = False
        extend_time = None
        logger.info("Время продления истекло. Бот приостановлен.")
