# handlers/admin.py

from aiogram import Router, F, Bot
from aiogram.filters import Command, Filter
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, func
from datetime import datetime
from database import async_session
from models import Commission, PaymentDetails, AdminActionLog, Application, User
from config import ADMIN_IDS, BOT_TOKEN
import re  # Для регулярных выражений

admin_router = Router()

# --- Определение Фильтров ---

# Фильтр для проверки, что сообщение от администратора
class IsAdminMessageFilter(Filter):
    async def __call__(self, message: Message) -> bool:
        return message.from_user.id in ADMIN_IDS

# Фильтр для проверки, что CallbackQuery от администратора
class IsAdminCallbackQueryFilter(Filter):
    async def __call__(self, callback_query: CallbackQuery) -> bool:
        return callback_query.from_user.id in ADMIN_IDS

# --- Определение Состояний ---

class AdminStates(StatesGroup):
    MainMenu = State()
    SetCommission = State()
    AddPaymentDetails = State()

# --- Функции для Создания Inline Клавиатур ---

def admin_main_menu_kb():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚙️ Установить комиссию", callback_data="admin_set_commission")],
        [InlineKeyboardButton(text="➕ Добавить реквизиты", callback_data="admin_add_payment")],
        [InlineKeyboardButton(text="➖ Удалить реквизиты", callback_data="admin_delete_payment")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_statistics")],
        [InlineKeyboardButton(text="🚫 Заблокированные пользователи", callback_data="admin_view_blocked_users")],
    ])
    return keyboard

def admin_cancel_kb(action: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data=f"admin_cancel_{action}")]
    ])

def admin_delete_payment_kb(payment_details):
    buttons = [
        [
            InlineKeyboardButton(
                text=f"❌ Удалить: {detail.bank_name}, {detail.card_number}, {detail.recipient_name}",
                callback_data=f"delete_payment_{detail.id}"
            )
        ] for detail in payment_details
    ]
    # Добавляем кнопку "Назад"
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def stats_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_main_menu")]
    ])

def blocked_users_back_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back_main_menu")]
    ])

# --- Хендлеры ---

# Хендлер для команды /admin
@admin_router.message(Command("admin"), IsAdminMessageFilter())
async def admin_start(message: Message, state: FSMContext):
    await state.set_state(AdminStates.MainMenu)
    await message.answer("👨‍💼 Добро пожаловать в админ-панель.", reply_markup=admin_main_menu_kb())
    await log_admin_action(message.from_user.id, "Открыта админ-панель")

# Хендлер для обработки нажатий в главном меню
@admin_router.callback_query(F.data.startswith("admin_"), IsAdminCallbackQueryFilter())
async def admin_menu_handler(callback_query: CallbackQuery, state: FSMContext):
    data = callback_query.data

    if data == "admin_set_commission":
        await state.set_state(AdminStates.SetCommission)
        await callback_query.message.edit_text(
            "🛠 **Установка комиссии**\n\nВведите новую комиссию в процентах (например, `2.5`):",
            reply_markup=admin_cancel_kb("set_commission"),
            parse_mode="Markdown"
        )
        await callback_query.answer()
        await log_admin_action(callback_query.from_user.id, "Начато установление комиссии")

    elif data == "admin_add_payment":
        await state.set_state(AdminStates.AddPaymentDetails)
        await callback_query.message.edit_text(
            "➕ **Добавление реквизитов**\n\nВведите данные реквизитов в формате:\n\n"
            "Банк\n"
            "Номер карты\n"
            "ФИО получателя\n\n"
            "🔍 **Пример:**\n"
            "Банк А\n"
            "1234567890123456\n"
            "Иван Иванович С",
            reply_markup=admin_cancel_kb("add_payment"),
            parse_mode="Markdown"
        )
        await callback_query.answer()
        await log_admin_action(callback_query.from_user.id, "Начато добавление реквизитов")

    elif data == "admin_delete_payment":
        await delete_payment_details_menu(callback_query, state)
        await callback_query.answer()

    elif data == "admin_statistics":
        await show_statistics(callback_query, state)
        await callback_query.answer()

    elif data == "admin_view_blocked_users":
        await view_blocked_users(callback_query, state)
        await callback_query.answer()

    elif data.startswith("admin_cancel_"):
        action = data.split("_", 2)[-1]
        await state.set_state(AdminStates.MainMenu)
        await callback_query.message.edit_text("❌ **Действие отменено.**\n\nВыберите действие:", reply_markup=admin_main_menu_kb(), parse_mode="Markdown")
        await callback_query.answer()
        await log_admin_action(callback_query.from_user.id, f"Отмена действия: {action}")

    elif data == "admin_back_main_menu":
        await state.set_state(AdminStates.MainMenu)
        await callback_query.message.edit_text("🗂 **Выберите действие:**", reply_markup=admin_main_menu_kb(), parse_mode="Markdown")
        await callback_query.answer()
        await log_admin_action(callback_query.from_user.id, "Возврат в главное меню")

    else:
        await callback_query.answer("❓ Неизвестная команда.", show_alert=True)

# Хендлер для установки комиссии
@admin_router.message(AdminStates.SetCommission, IsAdminMessageFilter())
async def set_commission(message: Message, state: FSMContext):
    try:
        new_rate = float(message.text)
        if new_rate < 0:
            raise ValueError("Комиссия не может быть отрицательной.")
        async with async_session() as session:
            # Проверяем, есть ли запись комиссии
            result = await session.execute(select(Commission).order_by(Commission.id.desc()))
            commission = result.scalar_one_or_none()
            if not commission:
                # Если нет, создаем новую запись
                commission = Commission(rate=new_rate)
                session.add(commission)
            else:
                # Обновляем существующую запись
                commission.rate = new_rate
                commission.updated_at = datetime.utcnow()
            await session.commit()
            await message.answer(f"✅ Новая комиссия установлена: `{new_rate}%`", parse_mode="Markdown")
            await log_admin_action(message.from_user.id, f"Установлена комиссия: {new_rate}%")
    except ValueError:
        await message.answer("❌ Пожалуйста, введите корректное положительное число для комиссии.")
        return
    except Exception:
        await message.answer("⚠️ Произошла ошибка при установке комиссии. Попробуйте позже.")
    finally:
        await state.set_state(AdminStates.MainMenu)
        await message.answer("🗂 **Выберите действие:**", reply_markup=admin_main_menu_kb(), parse_mode="Markdown")

# Хендлер для добавления реквизитов
@admin_router.message(AdminStates.AddPaymentDetails, IsAdminMessageFilter())
async def add_payment_details(message: Message, state: FSMContext):
    content = message.text.strip()
    try:
        # Разбиваем сообщение на строки
        lines = content.split('\n')
        if len(lines) != 3:
            await message.answer(
                "❌ Пожалуйста, введите данные реквизитов в правильном формате:\n\n"
                "Банк\n"
                "Номер карты\n"
                "ФИО получателя\n\n"
                "🔍 **Пример:**\n"
                "Банк А\n"
                "1234567890123456\n"
                "Иван Иванович С",
                parse_mode="Markdown"
            )
            return

        bank_name = lines[0].strip()
        card_number = lines[1].strip().replace(' ', '')  # Удаляем пробелы из номера карты
        recipient_name = lines[2].strip()

        # Валидация номера карты (пример простой проверки длины)
        if not re.fullmatch(r'\d{16}', card_number):
            await message.answer("❌ Номер карты должен содержать 16 цифр. Попробуйте снова.")
            return

        # Сохраняем реквизиты в базу данных
        async with async_session() as session:
            # Проверяем, существует ли уже такой номер карты
            existing = await session.execute(
                select(PaymentDetails).where(PaymentDetails.card_number == card_number)
            )
            existing_payment = existing.scalar_one_or_none()
            if existing_payment:
                await message.answer("❌ Реквизиты с таким номером карты уже существуют.")
                return

            payment_detail = PaymentDetails(
                bank_name=bank_name,
                card_number=card_number,
                recipient_name=recipient_name
                # min_limit и max_limit удалены
            )
            session.add(payment_detail)
            await session.commit()
            await message.answer("✅ Реквизиты успешно добавлены.", parse_mode="Markdown")
            await log_admin_action(
                message.from_user.id,
                f"Добавлены реквизиты: {bank_name}, {card_number}, ФИО получателя: {recipient_name}"
            )

    except ValueError:
        await message.answer(
            "❌ Пожалуйста, убедитесь, что данные введены в правильном формате.\n\n"
            "🔍 **Пример:**\n"
            "Банк А\n"
            "1234567890123456\n"
            "Иван Иванович С",
            parse_mode="Markdown"
        )
        return
    except Exception:
        await message.answer("⚠️ Произошла ошибка при добавлении реквизитов. Попробуйте позже.", parse_mode="Markdown")
    finally:
        await state.set_state(AdminStates.MainMenu)
        await message.answer("🗂 **Выберите действие:**", reply_markup=admin_main_menu_kb(), parse_mode="Markdown")

# Функция для отображения меню удаления реквизитов
async def delete_payment_details_menu(callback_query: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        result = await session.execute(select(PaymentDetails))
        payment_details = result.scalars().all()
        if not payment_details:
            await callback_query.message.edit_text("❌ Нет доступных реквизитов для удаления.", reply_markup=admin_main_menu_kb(), parse_mode="Markdown")
            await state.set_state(AdminStates.MainMenu)
            await log_admin_action(callback_query.from_user.id, "Удаление реквизитов: реквизиты отсутствуют")
            return

        # Создаём InlineKeyboardMarkup с кнопками "Удалить" для каждого реквизита
        inline_kb = admin_delete_payment_kb(payment_details)

        await callback_query.message.edit_text("🗑 **Выберите реквизиты для удаления:**", reply_markup=inline_kb, parse_mode="Markdown")

# Хендлер для удаления реквизитов через Inline кнопки
@admin_router.callback_query(F.data.startswith("delete_payment_"), IsAdminCallbackQueryFilter())
async def delete_payment_callback(callback_query: CallbackQuery, state: FSMContext):
    data = callback_query.data
    try:
        # Извлекаем ID реквизита
        detail_id = int(data.split("_")[-1])
    except ValueError:
        await callback_query.answer("❌ Некорректный ID реквизита.", show_alert=True)
        return

    async with async_session() as session:
        result = await session.execute(select(PaymentDetails).where(PaymentDetails.id == detail_id))
        payment_detail = result.scalar_one_or_none()
        if payment_detail:
            await session.delete(payment_detail)
            await session.commit()
            await callback_query.answer("✅ Реквизиты успешно удалены.", show_alert=True)
            await log_admin_action(callback_query.from_user.id, f"Удалены реквизиты ID: {detail_id}")
        else:
            await callback_query.answer("❌ Реквизиты не найдены.", show_alert=True)
            return

        # Получаем оставшиеся реквизиты
        remaining_details = await session.execute(select(PaymentDetails))
        remaining_details = remaining_details.scalars().all()

        if remaining_details:
            # Создаём обновлённый InlineKeyboardMarkup
            updated_inline_kb = admin_delete_payment_kb(remaining_details)
            await callback_query.message.edit_text("🗑 **Выберите реквизиты для удаления:**", reply_markup=updated_inline_kb, parse_mode="Markdown")
        else:
            # Если реквизитов нет, информируем администратора и возвращаемся в главное меню
            await callback_query.message.edit_text("✅ Все реквизиты успешно удалены.", reply_markup=admin_main_menu_kb(), parse_mode="Markdown")

# Хендлер для кнопки "Статистика"
@admin_router.callback_query(F.data == "admin_statistics", IsAdminCallbackQueryFilter())
async def show_statistics(callback_query: CallbackQuery, state: FSMContext):
    try:
        async with async_session() as session:
            # Общий оборот: сумма amount_rub для завершённых заявок
            result = await session.execute(
                select(func.sum(Application.amount_rub)).where(Application.status == 'completed')
            )
            total_turnover = result.scalar() or 0.0

            # Получение последней комиссии
            result = await session.execute(
                select(Commission.rate).order_by(Commission.id.desc()).limit(1)
            )
            latest_commission_rate = result.scalar() or 0.0

            # Заработок с комиссий
            total_commission = total_turnover * (latest_commission_rate / 100)

            # Количество пользователей
            result = await session.execute(select(func.count(User.id)))
            user_count = result.scalar()

            # Количество заявок
            result = await session.execute(select(func.count(Application.id)))
            total_applications = result.scalar()

            # Количество заявок по статусам
            result = await session.execute(
                select(Application.status, func.count(Application.id)).group_by(Application.status)
            )
            status_counts = result.fetchall()

            # Формируем строку с количеством заявок по статусам
            status_summary = ""
            for status, count in status_counts:
                status_summary += f"**{status.capitalize()}**: {count}\n"

            # Отправляем статистику
            stats_message = (
                f"📊 **Статистика за всё время:**\n\n"
                f"**💸 Общий оборот:** `{total_turnover:.2f} ₽`\n"
                f"**💰 Заработок с комиссий ({latest_commission_rate}%):** `{total_commission:.2f} ₽`\n"
                f"**👥 Количество пользователей:** `{user_count}`\n"
                f"**📄 Количество заявок:** `{total_applications}`\n\n"
                f"**📈 Статусы заявок:**\n{status_summary}"
            )

            await callback_query.message.edit_text(
                stats_message,
                parse_mode="Markdown",
                reply_markup=stats_back_kb()
            )
            await log_admin_action(callback_query.from_user.id, "Просмотр статистики")
    except Exception:
        await callback_query.message.edit_text(
            "⚠️ Произошла ошибка при получении статистики.",
            reply_markup=admin_main_menu_kb(),
            parse_mode="Markdown"
        )
        await callback_query.answer("⚠️ Произошла ошибка при получении статистики.", show_alert=True)

# Функция для отображения списка заблокированных пользователей
async def view_blocked_users(callback_query: CallbackQuery, state: FSMContext):
    async with async_session() as session:
        result = await session.execute(select(User).where(User.is_blocked == True))
        blocked_users = result.scalars().all()
        if not blocked_users:
            await callback_query.message.edit_text("✅ Нет заблокированных пользователей.", reply_markup=admin_main_menu_kb(), parse_mode="Markdown")
            await state.set_state(AdminStates.MainMenu)
            await log_admin_action(callback_query.from_user.id, "Просмотр заблокированных пользователей: нет пользователей")
            return

        # Формируем список заблокированных пользователей
        blocked_list = ""
        for user in blocked_users:
            blocked_list += f"🔹 **ID:** `{user.id}` | **Telegram ID:** `{user.telegram_id}` | **Имя:** {user.first_name or user.username or 'Неизвестно'}\n"

        blocked_message = (
            f"🚫 **Заблокированные пользователи:**\n\n"
            f"{blocked_list}\n"
            f"Чтобы разблокировать пользователя, отправьте команду:\n"
            f"`/unban <telegram_id>`\n\n"
            f"🔙 Нажмите **Назад**, чтобы вернуться в главное меню."
        )

        await callback_query.message.edit_text(
            blocked_message,
            parse_mode="Markdown",
            reply_markup=blocked_users_back_kb()
        )
        await log_admin_action(callback_query.from_user.id, "Просмотр заблокированных пользователей")

# Хендлер для кнопки "Назад" из статистики и заблокированных пользователей
@admin_router.callback_query(F.data == "admin_back_main_menu", IsAdminCallbackQueryFilter())
async def back_to_main_menu(callback_query: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.MainMenu)
    await callback_query.message.edit_text("🗂 **Выберите действие:**", reply_markup=admin_main_menu_kb(), parse_mode="Markdown")
    await callback_query.answer()
    await log_admin_action(callback_query.from_user.id, "Возврат в главное меню")

# Хендлер для команды /unban ID
@admin_router.message(Command("unban"), IsAdminMessageFilter())
async def unban_user(message: Message, state: FSMContext):
    try:
        # Извлекаем telegram_id из команды
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("❌ Неправильный формат команды.\n\nИспользуйте: `/unban <telegram_id>`", parse_mode="Markdown")
            return

        telegram_id = int(parts[1])
    except (IndexError, ValueError):
        await message.answer("❌ Неправильный формат команды.\n\nИспользуйте: `/unban <telegram_id>`", parse_mode="Markdown")
        return

    async with async_session() as session:
        # Ищем пользователя по telegram_id
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            await message.answer(f"❌ Пользователь с Telegram ID `{telegram_id}` не найден.", parse_mode="Markdown")
            return

        if not user.is_blocked:
            await message.answer(f"ℹ️ Пользователь `{telegram_id}` не заблокирован.", parse_mode="Markdown")
            return

        # Разблокируем пользователя
        user.is_blocked = False
        await session.commit()
        await message.answer(f"✅ Пользователь `{telegram_id}` успешно разблокирован.", parse_mode="Markdown")
        await log_admin_action(message.from_user.id, f"Разблокирован пользователь Telegram ID: {telegram_id}")

        # Уведомляем пользователя о разблокировке (если требуется)
        bot = Bot(token=BOT_TOKEN)
        try:
            await bot.send_message(
                user.telegram_id,
                "✅ Ваш доступ к боту был восстановлен. Теперь вы можете пользоваться всеми функциями.",
                parse_mode="Markdown"
            )
        except Exception:
            pass  # Можно добавить обработку ошибок, если необходимо
        finally:
            await bot.close()

# --- Функция для Логирования Действий ---

async def log_admin_action(admin_id: int, action: str):
    async with async_session() as session:
        log_entry = AdminActionLog(
            admin_id=admin_id,
            action=action,
            timestamp=datetime.utcnow()
        )
        session.add(log_entry)
        await session.commit()
