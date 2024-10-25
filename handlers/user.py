# handlers/user.py

from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.filters import Command, BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # Для работы с часовыми поясами
from database import async_session
from models import User, Commission, PaymentDetails, Application
from utils.captcha import generate_captcha, verify_captcha
from config import (
    CAPTCHA_TIMEOUT,
    COMMISSION_RATE,
    ADMIN_USERNAME,
    ADMIN_IDS,  # Добавляем список администраторов
    WORKER_ID,
    BOT_TOKEN,
)
from utils.crypto_rate import get_crypto_rate
import re
from decimal import Decimal

user_router = Router()

# Состояния для капчи и основного меню
class CaptchaStates(StatesGroup):
    WaitingForCaptcha = State()
    MainMenu = State()

# Состояния для процесса покупки криптовалюты
class BuyCryptoStates(StatesGroup):
    ChooseCrypto = State()
    EnterAmount = State()
    ChoosePaymentMethod = State()
    EnterWalletAddress = State()
    ConfirmPayment = State()

# Кастомный фильтр для проверки, что пользователь не заблокирован
class IsNotBlocked(BaseFilter):
    async def __call__(self, message: Message):
        telegram_id = message.from_user.id
        async with async_session() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == telegram_id)
            )
            user = result.scalar_one_or_none()
            if user and user.is_blocked:
                await message.answer("⛔ Ваш доступ к боту заблокирован.")
                return False
            return True

# Функция для создания Inline-кнопки "Отмена" с динамическим callback_data
def cancel_inline_keyboard(callback_data: str):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚫 Отмена", callback_data=callback_data)],
    ])
    return keyboard

# Функция для удаления кнопок с предыдущего сообщения
async def remove_buttons(bot: Bot, chat_id: int, message_id: int):
    try:
        await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id, reply_markup=None)
    except Exception:
        pass  # Игнорируем ошибки при удалении кнопок

# Функция для удаления сообщения
async def delete_message(bot: Bot, chat_id: int, message_id: int):
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass  # Игнорируем ошибки при удалении сообщения

# Хендлер для команды /start
@user_router.message(Command('start'))
async def user_start(message: Message, state: FSMContext):
    telegram_id = message.from_user.id
    first_name = message.from_user.first_name
    username = message.from_user.username
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            # Новый пользователь
            user = User(telegram_id=telegram_id, first_name=first_name, username=username)
            session.add(user)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                await message.answer("❌ Произошла ошибка при регистрации. Попробуйте снова позже.")
                return
        else:
            # Обновляем данные пользователя
            user.first_name = first_name
            user.username = username
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                await message.answer("❌ Произошла ошибка. Попробуйте снова позже.")
                return

        if user.is_blocked:
            await message.answer("⛔ Ваш доступ к боту заблокирован.")
            return

        await message.answer("👋 Добро пожаловать в обменник криптовалют!")

        now = datetime.utcnow()
        last_action = (
            user.last_action
            if user.last_action
            else now - timedelta(minutes=CAPTCHA_TIMEOUT + 1)
        )

        if now - last_action > timedelta(minutes=CAPTCHA_TIMEOUT):
            # Генерируем капчу
            captcha_code = await generate_captcha()
            user.captcha_code = captcha_code
            user.captcha_expiration = now + timedelta(minutes=CAPTCHA_TIMEOUT)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                await message.answer("❌ Произошла ошибка. Попробуйте снова позже.")
                return

            sent_message = await message.answer(
                f"🔒 Пожалуйста, введите капчу для подтверждения:\n\n**{captcha_code}**",
                parse_mode="Markdown"
            )
            await state.update_data(last_message_id=sent_message.message_id)
            await state.set_state(CaptchaStates.WaitingForCaptcha)
        else:
            # Продолжаем работу
            user.last_action = now
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                await message.answer("❌ Произошла ошибка. Попробуйте снова позже.")
                return
            await main_menu(message, state)

# Хендлер для обработки капчи
@user_router.message(CaptchaStates.WaitingForCaptcha)
async def process_captcha(message: Message, state: FSMContext):
    telegram_id = message.from_user.id
    user_data = await state.get_data()
    last_message_id = user_data.get('last_message_id')

    # Удаляем кнопки с предыдущего сообщения
    if last_message_id:
        await remove_buttons(message.bot, message.chat.id, last_message_id)

    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()

        if not user or not user.captcha_code:
            sent_message = await message.answer("❌ Капча не найдена. Пожалуйста, начните снова командой /start.")
            await state.update_data(last_message_id=sent_message.message_id)
            return

        now = datetime.utcnow()

        if now > user.captcha_expiration:
            # Капча истекла
            captcha_code = await generate_captcha()
            user.captcha_code = captcha_code
            user.captcha_expiration = now + timedelta(minutes=CAPTCHA_TIMEOUT)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                await message.answer("❌ Произошла ошибка. Попробуйте снова позже.")
                return

            sent_message = await message.answer(
                f"⏰ Капча истекла. Пожалуйста, введите новую капчу:\n\n**{captcha_code}**",
                parse_mode="Markdown"
            )
            await state.update_data(last_message_id=sent_message.message_id)
            return

        if verify_captcha(message.text, user.captcha_code):
            # Капча верна
            user.captcha_code = None
            user.captcha_expiration = None
            user.last_action = now
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                await message.answer("❌ Произошла ошибка. Попробуйте снова позже.")
                return
            await message.answer("✅ Капча введена верно! Добро пожаловать.")
            await main_menu(message, state)
        else:
            sent_message = await message.answer("❌ Неверная капча. Пожалуйста, попробуйте снова.")
            await state.update_data(last_message_id=sent_message.message_id)

# Функция для отображения главного меню
async def main_menu(message: Message, state: FSMContext):
    user_data = await state.get_data()
    last_message_id = user_data.get('last_message_id')

    # Удаляем сообщение с предыдущими кнопками
    if last_message_id:
        await delete_message(message.bot, message.chat.id, last_message_id)

    await state.set_state(CaptchaStates.MainMenu)
    sent_message = await message.answer("🗂 Выберите действие:", reply_markup=main_menu_inline_keyboard())
    await state.update_data(last_message_id=sent_message.message_id)

# Инлайн-клавиатура главного меню
def main_menu_inline_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Купить криптовалюту", callback_data="menu_buy_crypto")],
        [InlineKeyboardButton(text="📈 Профиль", callback_data="menu_profile")],
        [InlineKeyboardButton(text="📞 Связь с нами", url=f"https://t.me/{ADMIN_USERNAME}")]
    ])
    return keyboard

# Хендлер для выбора действия в главном меню
@user_router.callback_query(CaptchaStates.MainMenu, IsNotBlocked())
async def main_menu_selection_callback(callback_query: CallbackQuery, state: FSMContext):
    data = callback_query.data
    await callback_query.answer()

    # Удаляем сообщение с предыдущими кнопками
    user_data = await state.get_data()
    last_message_id = user_data.get('last_message_id')
    if last_message_id:
        await delete_message(callback_query.message.bot, callback_query.message.chat.id, last_message_id)

    if data == "menu_buy_crypto":
        await buy_crypto_start(callback_query.message, state)
    elif data == "menu_profile":
        await personal_account(callback_query.message, state)
    else:
        # Если действие неизвестно, возвращаем в главное меню
        await main_menu(callback_query.message, state)

# Хендлер для кнопки "Купить криптовалюту"
async def buy_crypto_start(message: Message, state: FSMContext):
    await state.set_state(BuyCryptoStates.ChooseCrypto)
    sent_message = await message.answer("🔍 Выберите криптовалюту:", reply_markup=crypto_inline_keyboard())
    await state.update_data(last_message_id=sent_message.message_id)

# Инлайн-клавиатура выбора криптовалюты
def crypto_inline_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Bitcoin (BTC)", callback_data="crypto_BTC")],
        [InlineKeyboardButton(text="Litecoin (LTC)", callback_data="crypto_LTC")]
    ])
    return keyboard

# Хендлер для выбора криптовалюты
@user_router.callback_query(BuyCryptoStates.ChooseCrypto)
async def choose_crypto_callback(callback_query: CallbackQuery, state: FSMContext):
    data = callback_query.data
    await callback_query.answer()

    # Удаляем сообщение с предыдущими кнопками
    user_data = await state.get_data()
    last_message_id = user_data.get('last_message_id')
    if last_message_id:
        await delete_message(callback_query.message.bot, callback_query.message.chat.id, last_message_id)

    if data == "crypto_BTC":
        crypto = "BTC"
    elif data == "crypto_LTC":
        crypto = "LTC"
    else:
        sent_message = await callback_query.message.answer("❌ Пожалуйста, выберите криптовалюту из списка.")
        await state.update_data(last_message_id=sent_message.message_id)
        return
    await state.update_data(crypto=crypto)
    sent_message = await callback_query.message.answer(
        "💰 Введите нужную сумму:\n"
        "- Введите сумму в криптовалюте (например, 0.00041 BTC)\n"
        "- Или в рублях (например, 1000 ₽)",
        reply_markup=cancel_inline_keyboard(callback_data="cancel_choose_crypto"),
    )
    await state.update_data(last_message_id=sent_message.message_id)
    await state.set_state(BuyCryptoStates.EnterAmount)

# Хендлер для ввода суммы
@user_router.message(BuyCryptoStates.EnterAmount)
async def enter_amount(message: Message, state: FSMContext):
    user_input = message.text.strip()
    user_data = await state.get_data()
    last_message_id = user_data.get('last_message_id')

    # Удаляем кнопки с предыдущего сообщения
    if last_message_id:
        await remove_buttons(message.bot, message.chat.id, last_message_id)

    # Разделение суммы и валюты
    match = re.match(r'^(\d+(\.\d+)?)\s*(BTC|LTC|₽)?$', user_input, re.IGNORECASE)
    if not match:
        sent_message = await message.answer("❌ Пожалуйста, введите корректную сумму.\nНапример: 0.00041 BTC или 1000 ₽")
        await state.update_data(last_message_id=sent_message.message_id)
        return

    amount = float(match.group(1))
    currency = match.group(3).upper() if match.group(3) else None

    if amount <= 0:
        sent_message = await message.answer("❌ Сумма должна быть положительной.")
        await state.update_data(last_message_id=sent_message.message_id)
        return

    user_data = await state.get_data()
    crypto = user_data.get('crypto', 'BTC')  # По умолчанию BTC, если не указано

    try:
        # Получаем курс выбранной криптовалюты к RUB
        crypto_rub_rate = await get_crypto_rate(crypto)
    except Exception:
        sent_message = await message.answer("⚠️ Не удалось получить курс криптовалюты. Попробуйте позже.")
        await state.update_data(last_message_id=sent_message.message_id)
        return

    # Получаем комиссию из базы данных
    async with async_session() as session:
        result = await session.execute(
            select(Commission).order_by(Commission.id.desc())
        )
        commission_entry = result.scalar_one_or_none()
        if commission_entry:
            commission_rate = commission_entry.rate
        else:
            commission_rate = COMMISSION_RATE  # Значение по умолчанию из config.py

    commission_rate_percent = commission_rate / 100

    if currency == "₽":
        # Пользователь ввёл сумму в RUB
        amount_rub = amount
        commission = amount_rub * commission_rate_percent
        amount_to_pay = amount_rub + commission  # Добавляем комиссию к сумме оплаты
        amount_crypto = amount_rub / crypto_rub_rate
        is_rub = True
    elif currency in ["BTC", "LTC"]:
        # Пользователь ввёл сумму в криптовалюте
        amount_crypto = amount
        amount_rub_before_commission = amount_crypto * crypto_rub_rate
        commission = amount_rub_before_commission * commission_rate_percent
        amount_to_pay = amount_rub_before_commission + commission  # Добавляем комиссию к сумме оплаты
        amount_rub = amount_to_pay
        is_rub = False
    else:
        # Пользователь не указал валюту, предполагаем рубли, если сумма >=1
        if amount >= 1:
            amount_rub = amount
            commission = amount_rub * commission_rate_percent
            amount_to_pay = amount_rub + commission
            amount_crypto = amount_rub / crypto_rub_rate
            is_rub = True
        else:
            amount_crypto = amount
            amount_rub_before_commission = amount_crypto * crypto_rub_rate
            commission = amount_rub_before_commission * commission_rate_percent
            amount_to_pay = amount_rub_before_commission + commission
            amount_rub = amount_to_pay
            is_rub = False

    # Сохраняем данные в состоянии
    await state.update_data(
        amount_crypto=amount_crypto,
        amount_rub=amount_rub,
        commission=commission,
        amount_to_pay=amount_to_pay,
        crypto_rub_rate=crypto_rub_rate,
        is_rub=is_rub,
    )

    # Формирование красиво отформатированного сообщения
    message_text = (
        f"💰 **Вы получите:** `{amount_crypto:.8f} {crypto}`\n"
        f"💵 **К оплате:** `{amount_to_pay:.2f} ₽`"
    )

    # Получаем доступные способы оплаты
    try:
        payment_methods = await get_payment_methods()
    except Exception:
        sent_message = await message.answer("⚠️ Не удалось получить способы оплаты. Попробуйте позже.")
        await state.update_data(last_message_id=sent_message.message_id)
        return

    sent_message = await message.answer(
        f"{message_text}\n\n🔗 **Выберите способ оплаты:**",
        reply_markup=payment_methods_inline_keyboard(payment_methods),
        parse_mode="Markdown"
    )

    await state.set_state(BuyCryptoStates.ChoosePaymentMethod)
    await state.update_data(last_message_id=sent_message.message_id)

# Функция для получения способов оплаты
async def get_payment_methods():
    async with async_session() as session:
        result = await session.execute(select(PaymentDetails.bank_name).distinct())
        methods = [row[0] for row in result.fetchall()]
        return methods

# Инлайн-клавиатура выбора способов оплаты
def payment_methods_inline_keyboard(methods):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=method, callback_data=f"payment_method_{method.replace(' ', '_')}")]
            for method in methods
        ]
    )
    # Добавляем кнопку "Назад"
    keyboard.inline_keyboard.append(
        [InlineKeyboardButton(text="🔙 Назад", callback_data="cancel_choose_crypto")]
    )
    return keyboard

# Хендлер для выбора способа оплаты
@user_router.callback_query(BuyCryptoStates.ChoosePaymentMethod)
async def choose_payment_method_callback(callback_query: CallbackQuery, state: FSMContext):
    data = callback_query.data
    await callback_query.answer()

    # Удаляем кнопки с предыдущего сообщения
    user_data = await state.get_data()
    last_message_id = user_data.get('last_message_id')
    if last_message_id:
        await remove_buttons(callback_query.message.bot, callback_query.message.chat.id, last_message_id)

    if data.startswith("payment_method_"):
        payment_method = data[len("payment_method_"):].replace('_', ' ')
        # Проверяем, что способ оплаты доступен
        payment_methods = await get_payment_methods()
        if payment_method not in payment_methods:
            sent_message = await callback_query.message.answer("❌ Пожалуйста, выберите способ оплаты из списка.")
            await state.update_data(last_message_id=sent_message.message_id)
            return
    elif data == "cancel_choose_crypto":
        # Возвращаемся к выбору криптовалюты
        await buy_crypto_start(callback_query.message, state)
        return
    else:
        sent_message = await callback_query.message.answer("❌ Пожалуйста, выберите способ оплаты из списка.")
        await state.update_data(last_message_id=sent_message.message_id)
        return

    await state.update_data(payment_method=payment_method)
    user_data = await state.get_data()
    amount_to_pay = user_data['amount_to_pay']
    crypto = user_data['crypto']
    sent_message = await callback_query.message.answer(
        f"🔑 Для получения `{user_data['amount_crypto']:.8f} {crypto}`\n"
        f"🖥 Укажите адрес вашего `{crypto}` кошелька, куда будут направлены средства:",
        reply_markup=cancel_inline_keyboard(callback_data="cancel_choose_payment_method"),
        parse_mode="Markdown"
    )
    await state.update_data(last_message_id=sent_message.message_id)
    await state.set_state(BuyCryptoStates.EnterWalletAddress)

# Хендлер для ввода адреса кошелька
@user_router.message(BuyCryptoStates.EnterWalletAddress)
async def enter_wallet_address(message: Message, state: FSMContext):
    wallet_address = message.text.strip()
    user_data = await state.get_data()
    last_message_id = user_data.get('last_message_id')

    # Удаляем кнопки с предыдущего сообщения
    if last_message_id:
        await remove_buttons(message.bot, message.chat.id, last_message_id)

    crypto = user_data['crypto']

    # Проверка валидности адреса кошелька
    if not validate_wallet_address(wallet_address, crypto):
        sent_message = await message.answer(
            f"❌ Некорректный `{crypto}` адрес, попробуйте еще раз.",
            reply_markup=cancel_inline_keyboard(callback_data="cancel_enter_wallet_address_error"),
            parse_mode="Markdown"
        )
        await state.update_data(last_message_id=sent_message.message_id)
        return

    await state.update_data(wallet_address=wallet_address)

    # Получаем реквизиты оплаты
    payment_method = user_data['payment_method']
    payment_details = await get_payment_details(payment_method)
    amount_to_pay = user_data['amount_to_pay']

    if not payment_details:
        sent_message = await message.answer("⚠️ Реквизиты не найдены. Обратитесь к администратору.")
        await state.update_data(last_message_id=sent_message.message_id)
        return

    # Сохраняем payment_details в состоянии
    await state.update_data(payment_details=payment_details)

    # Формирование красиво отформатированного сообщения с реквизитами оплаты
    payment_message = (
        f"🏦 **Реквизиты для оплаты:**\n\n"
        f"**Банк получатель:** {payment_details['bank_name']}\n"
        f"**ФИО получателя:** {payment_details['recipient_name']}\n"
        f"**Номер карты:** `{payment_details['card_number']}`\n"
        f"💵 **К оплате:** `{amount_to_pay:.2f} ₽`"
    )

    sent_message = await message.answer(
        payment_message,
        reply_markup=payment_confirmation_inline_keyboard(),
        parse_mode="Markdown"
    )
    await state.update_data(last_message_id=sent_message.message_id)
    await state.set_state(BuyCryptoStates.ConfirmPayment)

# Функция для проверки валидности адреса кошелька
def validate_wallet_address(address, crypto):
    # Улучшенная валидация с использованием регулярных выражений
    patterns = {
        "BTC": r'^(1|3|bc1)[a-zA-Z0-9]{25,39}$',
        "LTC": r'^(L|M|ltc1)[a-zA-Z0-9]{25,39}$',
    }
    pattern = patterns.get(crypto)
    if not pattern:
        return False
    return re.match(pattern, address) is not None

# Функция для получения реквизитов оплаты
async def get_payment_details(payment_method):
    async with async_session() as session:
        result = await session.execute(
            select(PaymentDetails).where(PaymentDetails.bank_name == payment_method)
        )
        payment_detail = result.scalar_one_or_none()
        if payment_detail:
            return {
                'bank_name': payment_detail.bank_name,
                'card_number': payment_detail.card_number,
                'recipient_name': payment_detail.recipient_name,
            }
        else:
            return None

# Функция для создания Inline-клавиатуры подтверждения оплаты
def payment_confirmation_inline_keyboard():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Оплатил", callback_data="payment_confirmed"),
            InlineKeyboardButton(text="❌ Отказаться", callback_data="payment_cancelled"),
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="cancel_enter_wallet_address")
        ]
    ])
    return keyboard

# Хендлер для кнопки "Оплатил"
@user_router.callback_query(F.data == "payment_confirmed")
async def payment_confirmed(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    user_data = await state.get_data()
    amount_to_pay = user_data['amount_to_pay']
    payment_details = user_data['payment_details']
    bank_name = payment_details['bank_name']
    card_number = payment_details['card_number']
    recipient_name = payment_details['recipient_name']

    # Удаляем кнопки с предыдущего сообщения
    last_message_id = user_data.get('last_message_id')
    if last_message_id:
        await remove_buttons(callback_query.message.bot, callback_query.message.chat.id, last_message_id)

    # Получаем текущее время в часовом поясе Москвы
    moscow_tz = ZoneInfo('Europe/Moscow')
    current_time = datetime.now(moscow_tz).strftime('%H:%M')

    # Формируем красиво отформатированное сообщение
    new_message_text = (
        f"✅ **Оплата получена:** `{amount_to_pay:.2f} ₽` в {current_time} по МСК\n\n"
        f"**🏦 Банк получатель:** {bank_name}\n"
        f"**ФИО получателя:** {recipient_name}\n"
        f"**Номер карты:** `{card_number}`\n\n"
        f"📩 **Дождитесь подтверждения оплаты.**\n"
        f"В случае задержки свяжитесь с администратором."
    )

    # Кнопка "Связаться с администратором"
    contact_admin_inline_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📞 Связаться с администратором", url=f"https://t.me/{ADMIN_USERNAME}")
        ]
    ])

    sent_message = await callback_query.message.answer(
        new_message_text,
        reply_markup=contact_admin_inline_keyboard,
        parse_mode="Markdown"
    )
    await state.update_data(last_message_id=sent_message.message_id)

    # Сохраняем информацию о заявке в базе данных
    await confirm_payment(callback_query.message, state)

    await state.clear()

# Хендлер для кнопки "Отказаться"
@user_router.callback_query(F.data == "payment_cancelled")
async def payment_cancelled(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()

    # Удаляем кнопки с предыдущего сообщения
    user_data = await state.get_data()
    last_message_id = user_data.get('last_message_id')
    if last_message_id:
        await remove_buttons(callback_query.message.bot, callback_query.message.chat.id, last_message_id)

    # Улучшенное сообщение
    cancellation_message = (
        "❗️ **Отказ от оплаты**\n\n"
        "Пожалуйста, старайтесь не создавать заявки, которые не планируете оплачивать.\n"
        "При частых отменах заявок доступ к сервису может быть ограничен."
    )
    sent_message = await callback_query.message.answer(cancellation_message)
    await state.update_data(last_message_id=sent_message.message_id)
    # Отправляем главное меню
    await main_menu(callback_query.message, state)
    # Устанавливаем состояние в главное меню
    await state.set_state(CaptchaStates.MainMenu)

# Функция подтверждения платежа и уведомления воркера
async def confirm_payment(message: Message, state: FSMContext):
    user_data = await state.get_data()
    crypto = user_data['crypto']
    payment_method = user_data['payment_method']
    wallet_address = user_data['wallet_address']
    amount_to_pay = user_data['amount_to_pay']
    amount_crypto = user_data['amount_crypto']
    crypto_rub_rate = user_data['crypto_rub_rate']
    telegram_id = message.chat.id

    async with async_session() as session:
        # Получаем пользователя
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            # Регистрируем пользователя
            user = User(telegram_id=telegram_id, first_name=message.from_user.first_name, username=message.from_user.username)
            session.add(user)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                await message.answer("❌ Произошла ошибка при регистрации. Попробуйте снова позже.")
                return

        # Создаем заявку
        application = Application(
            user_id=user.id,
            crypto_type=crypto,
            amount=Decimal(amount_crypto),
            amount_rub=Decimal(amount_to_pay),
            crypto_rub_rate=Decimal(crypto_rub_rate),
            wallet_address=wallet_address,
            payment_method=payment_method,
            status='pending',
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(application)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            await message.answer("❌ Произошла ошибка при создании заявки. Попробуйте снова позже.")
            return

        # Уведомляем воркера
        await notify_worker(application)

    await message.answer("📩 Дождитесь подтверждения оплаты.\n🕒 В среднем до 15 минут.")
    await state.clear()

# Функция для уведомления воркера о новой заявке
async def notify_worker(application):
    bot = Bot(token=BOT_TOKEN)
    # Получаем данные пользователя
    async with async_session() as session:
        # Получаем пользователя, который создал заявку
        result = await session.execute(
            select(User).where(User.id == application.user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            username = "Unknown"
            total_apps = 0
            successful_apps = 0
        else:
            username = user.first_name or user.username or f"User {user.telegram_id}"
            # Получаем количество заявок и успешных заявок
            total_apps_result = await session.execute(
                select(func.count(Application.id)).where(Application.user_id == user.id)
            )
            total_apps = total_apps_result.scalar()
            successful_apps_result = await session.execute(
                select(func.count(Application.id)).where(
                    Application.user_id == user.id,
                    Application.status == 'completed'
                )
            )
            successful_apps = successful_apps_result.scalar()

    # Получаем реквизиты оплаты
    payment_details = await get_payment_details(application.payment_method)
    card_number = payment_details['card_number'] if payment_details else 'Unknown'
    recipient_name = payment_details['recipient_name'] if payment_details else 'Unknown'

    # Формируем красиво отформатированное сообщение с использованием Markdown
    message_text = (
        f"📄 **Заявка №{application.id}**\n\n"
        f"**👤 Имя:** {username}\n"
        f"**📈 Количество заявок:** {total_apps}\\{successful_apps}\n"
        f"**💰 Сумма:** `{application.amount:.8f} {application.crypto_type}`\n"
        f"**💳 Пользователь оплатил:** `{application.amount_rub:.2f} ₽`\n"
        f"**🏦 Способ оплаты:** {application.payment_method}\n"
        f"**💳 Номер карты:** `{card_number}`\n"
        f"**📝 ФИО получателя:** {recipient_name}\n\n"
        f"**🔑 Адрес кошелька:**\n"
        f"`{application.wallet_address}`"
    )

    # Создаем inline-кнопки
    inline_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Выполнено", callback_data=f"application_{application.id}_completed"),
            InlineKeyboardButton(text="❌ Отказать", callback_data=f"application_{application.id}_rejected"),
        ],
        [
            InlineKeyboardButton(text="🔒 Заблокировать пользователя", callback_data=f"application_{application.id}_block_user"),
        ]
    ])

    # Отправляем сообщение воркеру с поддержкой Markdown
    await bot.send_message(
        WORKER_ID,
        message_text,
        reply_markup=inline_kb,
        parse_mode="Markdown"
    )
    await bot.close()

# Хендлер для кнопки "Выполнено"
@user_router.callback_query(F.data.startswith('application_') & F.data.endswith('_completed'))
async def application_completed_callback(callback_query: CallbackQuery):
    data = callback_query.data
    # Извлекаем ID заявки
    try:
        parts = data.split('_')
        application_id = int(parts[1])
    except (IndexError, ValueError):
        await callback_query.answer("❌ Некорректные данные заявки.", show_alert=True)
        return
    await process_application_action(callback_query, application_id, 'completed')

# Хендлер для кнопки "Отказать"
@user_router.callback_query(F.data.startswith('application_') & F.data.endswith('_rejected'))
async def application_rejected_callback(callback_query: CallbackQuery):
    data = callback_query.data
    # Извлекаем ID заявки
    try:
        parts = data.split('_')
        application_id = int(parts[1])
    except (IndexError, ValueError):
        await callback_query.answer("❌ Некорректные данные заявки.", show_alert=True)
        return
    await process_application_action(callback_query, application_id, 'rejected')

# Хендлер для кнопки "Заблокировать пользователя"
@user_router.callback_query(F.data.startswith('application_') & F.data.endswith('_block_user'))
async def block_user_callback(callback_query: CallbackQuery):
    data = callback_query.data
    # Извлекаем ID заявки
    try:
        parts = data.split('_')
        application_id = int(parts[1])
    except (IndexError, ValueError):
        await callback_query.answer("❌ Некорректные данные заявки.", show_alert=True)
        return
    await block_user_action(callback_query, application_id)

async def process_application_action(callback_query: CallbackQuery, application_id: int, action: str):
    # Проверяем, что действие выполняет воркер
    if callback_query.from_user.id != WORKER_ID:
        await callback_query.answer("⚠️ Вы не можете выполнить это действие.", show_alert=True)
        return

    async with async_session() as session:
        # Получаем заявку
        result = await session.execute(
            select(Application).where(Application.id == application_id)
        )
        application = result.scalar_one_or_none()
        if not application:
            await callback_query.answer("❌ Заявка не найдена.", show_alert=True)
            return

        # Обновляем статус заявки
        application.status = action
        application.updated_at = datetime.utcnow()
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            await callback_query.answer("❌ Произошла ошибка при обновлении заявки.", show_alert=True)
            return

        # Уведомляем пользователя
        await notify_user(application, action)

        # Редактируем сообщение
        status_text = "✅ Выполнено" if action == 'completed' else "❌ Отказано"
        await callback_query.message.edit_text(
            f"📄 **Заявка №{application.id}** обработана.\n**Статус:** {status_text}",
            parse_mode="Markdown"
        )
        await callback_query.answer("✅ Действие выполнено.", show_alert=True)

async def notify_user(application: Application, action: str):
    bot = Bot(token=BOT_TOKEN)
    # Получаем telegram_id пользователя
    async with async_session() as session:
        result = await session.execute(
            select(User).where(User.id == application.user_id)
        )
        user = result.scalar_one_or_none()

    if user:
        if action == 'completed':
            message_text = f"✅ **Ваша заявка выполнена.** Спасибо за использование нашего сервиса!"
        elif action == 'rejected':
            message_text = f"❌ **Ваша заявка отклонена.** Пожалуйста, свяжитесь с администрацией для уточнения."
        else:
            message_text = f"ℹ️ **Обновлен статус вашей заявки №{application.id}:** {action}"

        try:
            await bot.send_message(
                user.telegram_id,
                message_text,
                parse_mode="Markdown"
            )
        except Exception:
            pass  # Игнорируем ошибки при отправке уведомления
    await bot.close()

async def block_user_action(callback_query: CallbackQuery, application_id: int):
    # Проверяем, что действие выполняет воркер
    if callback_query.from_user.id != WORKER_ID:
        await callback_query.answer("⚠️ Вы не можете выполнить это действие.", show_alert=True)
        return

    async with async_session() as session:
        # Получаем заявку
        result = await session.execute(
            select(Application).where(Application.id == application_id)
        )
        application = result.scalar_one_or_none()
        if not application:
            await callback_query.answer("❌ Заявка не найдена.", show_alert=True)
            return

        # Получаем пользователя
        result = await session.execute(
            select(User).where(User.id == application.user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            await callback_query.answer("❌ Пользователь не найден.", show_alert=True)
            return

        # Блокируем пользователя
        user.is_blocked = True
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            await callback_query.answer("❌ Произошла ошибка при блокировке пользователя.", show_alert=True)
            return

        # Редактируем сообщение
        blocked_message = (
            f"🚫 **Пользователь {user.first_name or user.username or user.telegram_id} заблокирован.**"
        )
        await callback_query.message.edit_text(blocked_message, parse_mode="Markdown")
        await callback_query.answer("✅ Пользователь заблокирован.", show_alert=True)

# Функция для получения личного кабинета пользователя
async def personal_account(message: Message, state: FSMContext):
    telegram_id = message.from_user.id
    user_data = await state.get_data()
    last_message_id = user_data.get('last_message_id')

    # Удаляем сообщение с предыдущими кнопками
    if last_message_id:
        await delete_message(message.bot, message.chat.id, last_message_id)

    async with async_session() as session:
        # Получаем пользователя
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            # Регистрируем пользователя
            user = User(telegram_id=telegram_id, first_name=message.from_user.first_name, username=message.from_user.username)
            session.add(user)
            try:
                await session.commit()
            except Exception:
                await session.rollback()
                await message.answer("❌ Произошла ошибка при регистрации. Попробуйте снова позже.")
                return

        # Получаем статистику пользователя
        stats_result = await session.execute(
            select(
                func.count(Application.id).label("total_exchanges"),
                func.coalesce(func.sum(Application.amount_rub), 0).label("total_amount")
            ).where(Application.user_id == user.id)
        )
        stats = stats_result.fetchone()
        total_exchanges = stats.total_exchanges
        total_amount = stats.total_amount

        if total_exchanges == 0:
            # Если у пользователя нет обменов
            profile_message = (
                "📊 **Ваш профиль**\n\n"
                "Вы пока не совершали обменов."
            )
            sent_message = await message.answer(
                profile_message,
                parse_mode="Markdown",
                reply_markup=main_menu_inline_keyboard()
            )
            await state.update_data(last_message_id=sent_message.message_id)
            return

        # Получаем последний обмен для получения последнего кошелька и курса
        last_exchange_result = await session.execute(
            select(Application).where(Application.user_id == user.id).order_by(Application.created_at.desc()).limit(1)
        )
        last_exchange = last_exchange_result.scalar_one_or_none()

        if last_exchange:
            last_wallet = last_exchange.wallet_address
            last_crypto = last_exchange.crypto_type
            last_rate = f"{last_exchange.crypto_rub_rate:.4f} ₽/{last_crypto}"
        else:
            last_wallet = "Неизвестно"
            last_crypto = "Неизвестно"
            last_rate = "Неизвестно"

        # Форматирование общей суммы с двумя знаками после запятой
        total_amount_formatted = f"{total_amount:.2f} ₽"

        # Формирование красиво отформатированного сообщения
        profile_message = (
            f"📊 **Ваш профиль**\n\n"
            f"**📈 Количество обменов:** {total_exchanges}\n"
            f"**💰 Общая сумма обменов:** {total_amount_formatted}\n"
            f"**🔑 Последний использованный кошелёк:** `{last_wallet}`\n"
            f"**💱 Последняя криптовалюта:** {last_crypto}\n"
            f"**📉 Курс обмена:** {last_rate}"
        )

        sent_message = await message.answer(
            profile_message,
            parse_mode="Markdown",
            reply_markup=main_menu_inline_keyboard()
        )
        await state.update_data(last_message_id=sent_message.message_id)

# Хендлер для кнопок "Отмена" и "Назад"
@user_router.callback_query(lambda c: c.data and c.data.startswith('cancel_'))
async def cancel_handler(callback_query: CallbackQuery, state: FSMContext):
    await callback_query.answer()
    user_data = await state.get_data()
    last_message_id = user_data.get('last_message_id')
    if last_message_id:
        # Удаляем сообщение с предыдущими кнопками
        await delete_message(callback_query.message.bot, callback_query.message.chat.id, last_message_id)
    # Отправляем главное меню
    await main_menu(callback_query.message, state)

# Обработчик неожиданных сообщений
@user_router.message()
async def unexpected_message_handler(message: Message, state: FSMContext):
    telegram_id = message.from_user.id
    # Проверяем, является ли сообщение командой и пользователь является администратором
    if message.text.startswith('/') and telegram_id in ADMIN_IDS:
        # Пропускаем обработку, чтобы команда была обработана другим хендлером
        return
    # Иначе, отправляем сообщение об ошибке и возвращаем в главное меню
    await message.answer("❌ Некорректный ввод. Пожалуйста, используйте меню для навигации.")
    await main_menu(message, state)
