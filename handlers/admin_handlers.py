import logging
import aiosqlite
import aiohttp
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import asyncio
from datetime import datetime

from database import db
from config import OWNER_ID
from utils.messages import *
from utils.keyboards import *
from utils.validators import format_amount
from handlers.chat_handlers import format_chat_export, upload_to_pastebin

# Текстовые константы
DEAL_COMPLETED_MESSAGE = "✅ **Сделка завершена!**\n\nСделка успешно выполнена. Спасибо за использование нашего сервиса!"
DEAL_CANCELLED_MESSAGE = "❌ **Сделка отменена**\n\nСделка была отменена администратором."

logger = logging.getLogger(__name__)
router = Router()

class AdminStates(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_balance_amount = State()
    waiting_for_guarantor_id = State()
    waiting_for_broadcast_message = State()
    waiting_for_search_term = State()
    waiting_for_balance_currency = State()
    waiting_for_scammer_id = State()
    waiting_for_scammer_description = State()
    waiting_for_remove_scammer_id = State()

def is_admin(user_id: int) -> bool:
    """Проверка прав администратора"""
    return user_id == OWNER_ID

@router.callback_query(F.data == "admin_users")
async def show_admin_users_menu(callback: CallbackQuery):
    """Меню управления пользователями"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    await callback.message.edit_text(
        "👥 **Управление пользователями**\n\nВыберите действие:",
        reply_markup=get_admin_users_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_find_user")
async def start_find_user(callback: CallbackQuery, state: FSMContext):
    """Начало поиска пользователя"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_user_id)
    
    await callback.message.edit_text(
        "🔍 **Поиск пользователя**\n\nВведите ID пользователя:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_user_id)
async def process_find_user(message: Message, state: FSMContext):
    """Обработка поиска пользователя"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён")
        return
    
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer(
            "❌ Некорректный ID. Введите числовой ID пользователя:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    user = await db.get_user(user_id)
    
    if not user:
        await message.answer(
            "❌ Пользователь не найден",
            reply_markup=get_admin_users_keyboard()
        )
        await state.clear()
        return
    
    # Получаем дополнительную информацию
    wallets = await db.get_user_wallets(user_id)
    active_deal = await db.get_user_active_deal(user_id)
    
    user_info = f"""
👤 **Информация о пользователе**

**ID:** `{user['user_id']}`
**Username:** @{user['username'] or 'Не указан'}
**Имя:** {user['first_name'] or 'Не указано'}
**Рейтинг:** {user['rating']} ⭐
**Сделок:** {user['total_deals']} (завершено: {user['completed_deals']})

**Балансы:**
⭐ Звёзды: {user['balance_stars']}
₿ Крипта: {user.get('balance_crypto', 0):.2f}
💰 Рубли: {user.get('balance_rub', 0):.2f}

**Кошельков:** {len(wallets)}
**Статус:** {'🚫 Заблокирован' if user['is_banned'] else '✅ Активен'}
**Гарант:** {'✅ Да' if user['is_guarantor'] else '❌ Нет'}
**Активная сделка:** {'✅ Есть' if active_deal else '❌ Нет'}
**Зарегистрирован:** {user['created_at'][:10]}
"""
    
    # Создаём клавиатуру с действиями
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🚫 Заблокировать" if not user['is_banned'] else "✅ Разблокировать",
                callback_data=f"admin_toggle_ban_{user_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="👨‍💼 Сделать гарантом" if not user['is_guarantor'] else "❌ Убрать гаранта",
                callback_data=f"admin_toggle_guarantor_{user_id}"
            )
        ],
        [InlineKeyboardButton(text="💰 Изменить баланс", callback_data=f"admin_balance_{user_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_users")]
    ])
    
    await message.answer(
        user_info,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await state.clear()

@router.callback_query(F.data.startswith("admin_toggle_ban_"))
async def toggle_user_ban(callback: CallbackQuery):
    """Блокировка/разблокировка пользователя"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[-1])
    user = await db.get_user(user_id)
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    new_ban_status = not user['is_banned']
    await db.ban_user(user_id, new_ban_status)
    
    action = "заблокирован" if new_ban_status else "разблокирован"
    await callback.answer(f"Пользователь {action}")
    
    # Обновляем информацию
    await process_find_user_by_callback(callback, user_id)

@router.callback_query(F.data.startswith("admin_toggle_guarantor_"))
async def toggle_user_guarantor(callback: CallbackQuery):
    """Назначение/снятие гаранта"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[-1])
    user = await db.get_user(user_id)
    
    if not user:
        await callback.answer("Пользователь не найден", show_alert=True)
        return
    
    new_guarantor_status = not user['is_guarantor']
    await db.set_guarantor(user_id, new_guarantor_status)
    
    action = "назначен гарантом" if new_guarantor_status else "снят с должности гаранта"
    await callback.answer(f"Пользователь {action}")
    
    # Обновляем информацию
    await process_find_user_by_callback(callback, user_id)

@router.callback_query(F.data.startswith("admin_balance_"))
async def start_change_balance(callback: CallbackQuery, state: FSMContext):
    """Начало изменения баланса - выбор валюты"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    user_id = int(callback.data.split("_")[-1])
    await state.update_data(target_user_id=user_id)
    await state.set_state(AdminStates.waiting_for_balance_currency)
    
    user = await db.get_user(user_id)
    
    balance_text = f"""
💰 **Изменение баланса**

**Пользователь:** {user['first_name'] or user['username'] or 'Неизвестно'}

**Текущие балансы:**
⭐ Звёзды: {user['balance_stars']}
₿ Крипта: {user.get('balance_crypto', 0):.2f}
💰 Рубли: {user.get('balance_rub', 0):.2f}

Выберите валюту для изменения:
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Звёзды", callback_data="balance_currency_stars")],
        [InlineKeyboardButton(text="₿ Крипта", callback_data="balance_currency_crypto")],
        [InlineKeyboardButton(text="💰 Рубли", callback_data="balance_currency_rub")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_users")]
    ])
    
    await callback.message.edit_text(
        balance_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("balance_currency_"))
async def select_balance_currency(callback: CallbackQuery, state: FSMContext):
    """Выбор валюты для изменения баланса"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    currency = callback.data.split("_")[-1]
    await state.update_data(currency=currency)
    await state.set_state(AdminStates.waiting_for_balance_amount)
    
    data = await state.get_data()
    user_id = data['target_user_id']
    user = await db.get_user(user_id)
    
    currency_names = {
        'stars': 'звёзды',
        'crypto': 'крипта',
        'rub': 'рубли'
    }
    
    currency_symbols = {
        'stars': '⭐',
        'crypto': '₿',
        'rub': '💰'
    }
    
    current_balance = user.get(f'balance_{currency}', 0)
    
    await callback.message.edit_text(
        f"💰 **Изменение баланса**\n\n"
        f"Пользователь: {user['first_name'] or user['username'] or 'Неизвестно'}\n"
        f"Валюта: {currency_symbols[currency]} {currency_names[currency]}\n"
        f"Текущий баланс: {current_balance} {currency_symbols[currency]}\n\n"
        f"Введите сумму для изменения (например: +100, -50):",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_balance_amount)
async def process_balance_change(message: Message, state: FSMContext):
    """Обработка изменения баланса"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён")
        return
    
    data = await state.get_data()
    target_user_id = data['target_user_id']
    currency = data['currency']
    
    try:
        if currency == 'stars':
            amount = int(message.text.strip())
        else:
            amount = float(message.text.strip())
    except ValueError:
        example = "+100, -50" if currency == 'stars' else "+100.50, -25.25"
        await message.answer(
            f"❌ Некорректная сумма. Введите число (например: {example}):",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    await db.update_user_balance(target_user_id, amount, currency)
    
    user = await db.get_user(target_user_id)
    
    currency_symbols = {
        'stars': '⭐',
        'crypto': '₿',
        'rub': '💰'
    }
    
    currency_names = {
        'stars': 'звёзды',
        'crypto': 'крипта',
        'rub': 'рубли'
    }
    
    symbol = currency_symbols[currency]
    new_balance = user.get(f'balance_{currency}', 0)
    
    if currency == 'stars':
        amount_str = f"{amount:+d}"
        balance_str = f"{new_balance}"
    else:
        amount_str = f"{amount:+.2f}"
        balance_str = f"{new_balance:.2f}"
    
    await message.answer(
        f"✅ **Баланс изменён**\n\n"
        f"Пользователь: {user['first_name'] or user['username'] or 'Неизвестно'}\n"
        f"Валюта: {currency_names[currency]}\n"
        f"Изменение: {amount_str} {symbol}\n"
        f"Новый баланс: {balance_str} {symbol}",
        reply_markup=get_admin_users_keyboard(),
        parse_mode="Markdown"
    )
    await state.clear()

async def process_find_user_by_callback(callback: CallbackQuery, user_id: int):
    """Вспомогательная функция для обновления информации о пользователе"""
    user = await db.get_user(user_id)
    wallets = await db.get_user_wallets(user_id)
    active_deal = await db.get_user_active_deal(user_id)
    
    user_info = f"""
👤 **Информация о пользователе**

**ID:** `{user['user_id']}`
**Username:** @{user['username'] or 'Не указан'}
**Имя:** {user['first_name'] or 'Не указано'}
**Рейтинг:** {user['rating']} ⭐
**Сделок:** {user['total_deals']} (завершено: {user['completed_deals']})

**Балансы:**
⭐ Звёзды: {user['balance_stars']}
₿ Крипта: {user.get('balance_crypto', 0):.2f}
💰 Рубли: {user.get('balance_rub', 0):.2f}

**Кошельков:** {len(wallets)}
**Статус:** {'🚫 Заблокирован' if user['is_banned'] else '✅ Активен'}
**Гарант:** {'✅ Да' if user['is_guarantor'] else '❌ Нет'}
**Активная сделка:** {'✅ Есть' if active_deal else '❌ Нет'}
**Зарегистрирован:** {user['created_at'][:10]}
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🚫 Заблокировать" if not user['is_banned'] else "✅ Разблокировать",
                callback_data=f"admin_toggle_ban_{user_id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="👨‍💼 Сделать гарантом" if not user['is_guarantor'] else "❌ Убрать гаранта",
                callback_data=f"admin_toggle_guarantor_{user_id}"
            )
        ],
        [InlineKeyboardButton(text="💰 Изменить баланс", callback_data=f"admin_balance_{user_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_users")]
    ])
    
    await callback.message.edit_text(
        user_info,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "admin_guarantors")
async def show_admin_guarantors_menu(callback: CallbackQuery):
    """Меню управления гарантами"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    await callback.message.edit_text(
        "👨‍💼 **Управление гарантами**\n\nВыберите действие:",
        reply_markup=get_admin_guarantors_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_list_guarantors")
async def list_guarantors(callback: CallbackQuery):
    """Список всех гарантов"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    users = await db.get_all_users()
    guarantors = [u for u in users if u.get('is_guarantor', False)]
    
    if not guarantors:
        guarantors_text = "👨‍💼 **Список гарантов**\n\nГарантов нет."
    else:
        guarantors_text = "👨‍💼 **Список гарантов:**\n\n"
        
        for i, guarantor in enumerate(guarantors, 1):
            status = "🟢" if not guarantor.get('is_banned', False) else "🔴"
            name = guarantor['first_name'] or guarantor['username'] or f"ID{guarantor['user_id']}"
            
            guarantors_text += f"{i}. {status} {name} (`{guarantor['user_id']}`)\n"
            guarantors_text += f"   Рейтинг: {guarantor['rating']} ⭐\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_guarantors")]
    ])
    
    await callback.message.edit_text(
        guarantors_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_deals")
async def show_all_deals(callback: CallbackQuery):
    """Просмотр всех сделок"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    deals = await db.get_all_deals()
    
    if not deals:
        deals_text = "💼 **Все сделки**\n\nСделок нет."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
        ])
    else:
        deals_text = "💼 **Последние сделки:**\n\n"
        
        # Показываем последние 10 сделок
        keyboard_buttons = []
        
        for deal in deals[:10]:
            status_emoji = {
                'waiting_buyer': '⏳',
                'waiting_guarantor': '🔍',
                'in_progress': '⚡',
                'completed': '✅',
                'cancelled': '❌'
            }.get(deal['status'], '❓')
            
            deals_text += f"{status_emoji} **Сделка #{deal['id']}**\n"
            deals_text += f"Код: `{deal['deal_code']}`\n"
            deals_text += f"Сумма: {deal['amount']} {deal['currency_type']}\n"
            deals_text += f"Продавец: {deal['seller_name'] or 'ID' + str(deal['seller_id'])}\n"
            
            if deal['buyer_id']:
                deals_text += f"Покупатель: {deal['buyer_name'] or 'ID' + str(deal['buyer_id'])}\n"
            
            if deal['guarantor_id']:
                deals_text += f"Гарант: {deal['guarantor_name'] or 'ID' + str(deal['guarantor_id'])}\n"
            
            deals_text += f"Создана: {deal['created_at'][:10]}\n\n"
            
            # Добавляем кнопку просмотра чата если есть участники
            if deal['buyer_id'] or deal['guarantor_id']:
                keyboard_buttons.append([
                    InlineKeyboardButton(
                        text=f"💬 Чат #{deal['id']} ({deal['deal_code']})",
                        callback_data=f"admin_view_chat_{deal['id']}"
                    )
                ])
        
        # Добавляем кнопку "Назад"
        keyboard_buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    
    await callback.message.edit_text(
        deals_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_logs")
async def show_admin_logs(callback: CallbackQuery):
    """Просмотр логов"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    logs = await db.get_logs(20)
    
    if not logs:
        logs_text = "📜 **Логи системы**\n\nЛогов нет."
    else:
        logs_text = "📜 **Последние действия:**\n\n"
        
        for log in logs:
            timestamp = log['timestamp'][:16]  # Убираем секунды
            action = str(log['action']).replace('_', ' ').title()
            user_id = log['user_id'] or 'Система'
            
            # Экранируем специальные символы для markdown
            action = action.replace('*', '\\*').replace('_', '\\_').replace('`', '\\`')
            details = str(log['details'] or '').replace('*', '\\*').replace('_', '\\_').replace('`', '\\`')
            
            logs_text += f"`{timestamp}` {action}\n"
            logs_text += f"Пользователь: {user_id}\n"
            
            if details:
                logs_text += f"Детали: {details}\n"
            
            logs_text += "\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(
        logs_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    """Начало рассылки"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_broadcast_message)
    
    await callback.message.edit_text(
        "📢 **Рассылка сообщения**\n\nВведите текст для рассылки всем пользователям:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_broadcast_message)
async def process_broadcast(message: Message, state: FSMContext):
    """Обработка сообщения для рассылки"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён")
        return
    
    broadcast_text = message.text
    
    # Проверяем что текст не пустой
    if not broadcast_text or broadcast_text.strip() == "":
        await message.answer(
            "❌ Сообщение не может быть пустым. Введите текст для рассылки:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    if len(broadcast_text) > 4000:
        await message.answer(
            "❌ Сообщение слишком длинное. Максимум 4000 символов.",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Получаем всех активных пользователей
    users = await db.get_all_users()
    active_users = [u for u in users if not u.get('is_banned', False)]
    
    await message.answer("📢 Начинаю рассылку...")
    
    success_count = 0
    error_count = 0
    
    for user in active_users:
        try:
            await message.bot.send_message(
                chat_id=user['user_id'],
                text=f"📢 **Сообщение от администрации:**\n\n{broadcast_text}",
                parse_mode="Markdown"
            )
            success_count += 1
        except Exception as e:
            error_count += 1
            logger.error(f"Ошибка рассылки пользователю {user['user_id']}: {e}")
    
    result_text = f"""
✅ **Рассылка завершена**

📊 **Статистика:**
• Успешно отправлено: {success_count}
• Ошибок: {error_count}
• Всего пользователей: {len(active_users)}
"""
    
    await message.answer(
        result_text,
        reply_markup=get_admin_keyboard(),
        parse_mode="Markdown"
    )
    
    await state.clear()
    await db.log_action('broadcast_sent', message.from_user.id, details=f'Отправлено: {success_count}, ошибок: {error_count}')

@router.callback_query(F.data == "admin_banned_users")
async def show_banned_users(callback: CallbackQuery):
    """Показ заблокированных пользователей"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    users = await db.get_all_users()
    banned_users = [u for u in users if u.get('is_banned', False)]
    
    if not banned_users:
        banned_text = "🚫 **Заблокированные пользователи**\n\nЗаблокированных пользователей нет."
    else:
        banned_text = "🚫 **Заблокированные пользователи:**\n\n"
        
        for i, user in enumerate(banned_users, 1):
            name = user['first_name'] or user['username'] or f"ID{user['user_id']}"
            banned_text += f"{i}. {name} (`{user['user_id']}`)\n"
            banned_text += f"   Заблокирован: {user['created_at'][:10]}\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_users")]
    ])
    
    await callback.message.edit_text(
        banned_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_change_balance")
async def admin_change_balance_menu(callback: CallbackQuery, state: FSMContext):
    """Меню изменения баланса - перенаправление на поиск пользователя"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    await callback.answer("Сначала найдите пользователя для изменения баланса")
    
    # Перенаправляем на поиск пользователя
    await start_find_user(callback, state)

@router.callback_query(F.data == "admin_settings")
async def show_admin_settings(callback: CallbackQuery):
    """Показ настроек системы"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    # Получаем текущие настройки
    maintenance_mode = await db.is_maintenance_mode()
    maintenance_status = "🔧 Включены" if maintenance_mode else "✅ Выключены"
    
    settings_text = f"""
⚙️ **Настройки системы**

**Основные параметры:**
• Комиссия сделки: 5.0%
• Время жизни сделки: 10 минут
• Минимум оценок для рейтинга: 3
• Базовый рейтинг: 5.0 ⭐

**Статус системы:**
• Технические работы: {maintenance_status}
• Автоочистка просроченных сделок: ✅ Включена
• Логирование действий: ✅ Включено
• Уведомления гарантам: ✅ Включены

*Основные настройки задаются в файле config.py*
"""
    
    maintenance_button_text = "🔧 Включить техработы" if not maintenance_mode else "✅ Отключить техработы"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=maintenance_button_text, callback_data="admin_toggle_maintenance")],
        [InlineKeyboardButton(text="🔄 Очистить просроченные", callback_data="admin_cleanup_deals")],
        [InlineKeyboardButton(text="🗑 Очистить логи", callback_data="admin_clear_logs")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(
        settings_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_toggle_maintenance")
async def toggle_maintenance_mode(callback: CallbackQuery):
    """Переключение режима технических работ"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    current_mode = await db.is_maintenance_mode()
    new_mode = not current_mode
    
    await db.set_setting('maintenance_mode', 'true' if new_mode else 'false')
    
    status_text = "включён" if new_mode else "отключён"
    await callback.answer(f"🔧 Режим технических работ {status_text}", show_alert=True)
    
    # Обновляем настройки
    await show_admin_settings(callback)

@router.callback_query(F.data == "admin_cleanup_deals")
async def admin_cleanup_deals(callback: CallbackQuery):
    """Принудительная очистка просроченных сделок"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    deleted_count = await db.delete_expired_deals()
    
    await callback.answer(f"🗑 Удалено просроченных сделок: {deleted_count}", show_alert=True)

@router.callback_query(F.data == "admin_clear_logs")
async def admin_clear_logs(callback: CallbackQuery):
    """Очистка логов (подтверждение)"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, очистить", callback_data="admin_confirm_clear_logs"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="admin_settings")
        ]
    ])
    
    await callback.message.edit_text(
        "⚠️ **Подтверждение очистки логов**\n\nВы уверены, что хотите удалить ВСЕ логи?\nЭто действие необратимо!",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_confirm_clear_logs")
async def admin_confirm_clear_logs(callback: CallbackQuery):
    """Подтверждённая очистка логов"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    # Очищаем логи
    async with aiosqlite.connect(db.db_path) as database:
        await database.execute('DELETE FROM logs')
        await database.commit()
    
    await db.log_action('logs_cleared', callback.from_user.id)
    
    await callback.answer("🗑 Логи успешно очищены", show_alert=True)
    
    # Возвращаемся к настройкам
    await show_admin_settings(callback)

@router.callback_query(F.data == "admin_add_guarantor")
async def admin_add_guarantor_menu(callback: CallbackQuery, state: FSMContext):
    """Добавление гаранта"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_guarantor_id)
    await state.update_data(action="add_guarantor")
    
    await callback.message.edit_text(
        "👨‍💼 **Добавление гаранта**\n\nВведите ID пользователя для назначения гарантом:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_remove_guarantor")
async def admin_remove_guarantor_menu(callback: CallbackQuery, state: FSMContext):
    """Удаление гаранта"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_guarantor_id)
    await state.update_data(action="remove_guarantor")
    
    await callback.message.edit_text(
        "👨‍💼 **Удаление гаранта**\n\nВведите ID гаранта для снятия статуса:",
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_guarantor_id)
async def process_guarantor_change(message: Message, state: FSMContext):
    """Обработка изменения статуса гаранта"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён")
        return
    
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer(
            "❌ Некорректный ID. Введите числовой ID пользователя:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    user = await db.get_user(user_id)
    if not user:
        await message.answer(
            "❌ Пользователь не найден",
            reply_markup=get_admin_guarantors_keyboard()
        )
        await state.clear()
        return
    
    data = await state.get_data()
    action = data.get('action')
    
    if action == "add_guarantor":
        if user.get('is_guarantor', False):
            await message.answer(
                f"❌ Пользователь {user['first_name'] or user['username'] or user_id} уже является гарантом",
                reply_markup=get_admin_guarantors_keyboard()
            )
        else:
            await db.set_guarantor(user_id, True)
            await message.answer(
                f"✅ Пользователь {user['first_name'] or user['username'] or user_id} назначен гарантом",
                reply_markup=get_admin_guarantors_keyboard()
            )
    
    elif action == "remove_guarantor":
        if not user.get('is_guarantor', False):
            await message.answer(
                f"❌ Пользователь {user['first_name'] or user['username'] or user_id} не является гарантом",
                reply_markup=get_admin_guarantors_keyboard()
            )
        else:
            await db.set_guarantor(user_id, False)
            await message.answer(
                f"✅ У пользователя {user['first_name'] or user['username'] or user_id} снят статус гаранта",
                reply_markup=get_admin_guarantors_keyboard()
            )
    
    await state.clear()

# === УПРАВЛЕНИЕ ЧАТАМИ ===

@router.callback_query(F.data == "admin_chats")
async def show_admin_chats_menu(callback: CallbackQuery):
    """Меню управления чатами"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    # Получаем статистику чатов
    chat_stats = await db.get_deal_chat_stats()
    
    stats_text = f"""
💬 **Управление чатами сделок**

**📊 Статистика:**
• Всего сообщений: {chat_stats['total_messages']}
• Активных чатов: {chat_stats['active_chats']}
• Среднее сообщений на чат: {chat_stats['avg_messages_per_chat']}
• Системных сообщений: {chat_stats['system_messages']}

Выберите действие:
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список активных чатов", callback_data="admin_list_chats")],
        [InlineKeyboardButton(text="🔍 Поиск по сообщениям", callback_data="admin_search_messages")],
        [InlineKeyboardButton(text="📊 Подробная статистика", callback_data="admin_chat_detailed_stats")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(
        stats_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_list_chats")
async def list_deal_chats(callback: CallbackQuery):
    """Список активных чатов сделок"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    chats = await db.get_all_deal_chats_summary(15)
    
    if not chats:
        chats_text = "💬 **Активные чаты сделок**\n\nАктивных чатов нет."
    else:
        chats_text = "💬 **Активные чаты сделок:**\n\n"
        
        for chat in chats:
            status_emoji = {
                'waiting_buyer': '⏳',
                'waiting_guarantor': '🔍', 
                'in_progress': '⚡',
                'completed': '✅',
                'cancelled': '❌'
            }.get(chat['status'], '❓')
            
            seller_name = chat['seller_name'] or chat['seller_username'] or 'Неизвестно'
            buyer_name = chat['buyer_name'] or chat['buyer_username'] or 'Нет' if chat['buyer_name'] or chat['buyer_username'] else 'Нет'
            
            last_msg_time = chat['last_message_time'][:16] if chat['last_message_time'] else 'Нет'
            
            chats_text += f"{status_emoji} **Сделка #{chat['id']}** (`{chat['deal_code']}`)\n"
            chats_text += f"👥 {seller_name} ↔ {buyer_name}\n"
            chats_text += f"💬 Сообщений: {chat['message_count']}\n"
            chats_text += f"🕐 Последнее: {last_msg_time}\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_list_chats")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_chats")]
    ])
    
    try:
        await callback.message.edit_text(
            chats_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка редактирования списка чатов: {e}")
        try:
            await callback.message.answer(
                chats_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as e2:
            logger.error(f"Ошибка отправки списка чатов: {e2}")
            await callback.answer("❌ Ошибка отображения списка чатов", show_alert=True)
            return
    
    await callback.answer()

@router.callback_query(F.data == "admin_search_messages")
async def start_message_search(callback: CallbackQuery, state: FSMContext):
    """Начало поиска по сообщениям"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_search_term)
    
    await callback.message.edit_text(
        "🔍 **Поиск по сообщениям в чатах**\n\nВведите текст для поиска:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_chats")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_search_term)
async def process_message_search(message: Message, state: FSMContext):
    """Обработка поиска по сообщениям"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён")
        return
    
    search_term = message.text.strip()
    if len(search_term) < 2:
        await message.answer(
            "❌ Слишком короткий запрос. Минимум 2 символа:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_chats")]
            ])
        )
        return
    
    results = await db.search_deal_messages(search_term, 20)
    
    if not results:
        results_text = f"🔍 **Поиск по чатам**\n\nПо запросу «{search_term}» ничего не найдено."
    else:
        results_text = f"🔍 **Результаты поиска** для «{search_term}»:\n\n"
        
        for result in results:
            sender_name = result['first_name'] or result['username'] or f"ID{result['user_id']}"
            message_preview = result['message_text'][:50] + "..." if len(result['message_text']) > 50 else result['message_text']
            timestamp = result['created_at'][:16] if result['created_at'] else 'Неизвестно'
            
            results_text += f"📋 **Сделка #{result['deal_id']}** (`{result['deal_code']}`)\n"
            results_text += f"👤 {sender_name}: {message_preview}\n"
            results_text += f"🕐 {timestamp}\n\n"
            
            if len(results_text) > 3500:  # Ограничение Telegram
                results_text += f"... и ещё {len(results) - results.index(result) - 1} результатов"
                break
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Новый поиск", callback_data="admin_search_messages")],
        [InlineKeyboardButton(text="◀️ К чатам", callback_data="admin_chats")]
    ])
    
    await message.answer(
        results_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await state.clear()

@router.callback_query(F.data == "admin_chat_detailed_stats")
async def show_detailed_chat_stats(callback: CallbackQuery):
    """Подробная статистика чатов"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    stats = await db.get_deal_chat_stats()
    
    # Дополнительная статистика
    async with aiosqlite.connect(db.db_path) as database:
        # Сообщения по типам
        async with database.execute(
            'SELECT message_type, COUNT(*) FROM deal_messages GROUP BY message_type'
        ) as cursor:
            message_types = dict(await cursor.fetchall())
        
        # Самые активные чаты
        async with database.execute(
            '''SELECT deal_id, COUNT(*) as msg_count 
               FROM deal_messages 
               GROUP BY deal_id 
               ORDER BY msg_count DESC 
               LIMIT 5'''
        ) as cursor:
            top_chats = await cursor.fetchall()
        
        # Активность по дням (последние 7 дней)
        async with database.execute(
            '''SELECT DATE(created_at) as day, COUNT(*) as count
               FROM deal_messages 
               WHERE created_at >= date('now', '-7 days')
               GROUP BY DATE(created_at)
               ORDER BY day DESC'''
        ) as cursor:
            daily_activity = await cursor.fetchall()
    
    detailed_text = f"""
📊 **Подробная статистика чатов**

**🔢 Общие показатели:**
• Всего сообщений: {stats['total_messages']}
• Активных чатов: {stats['active_chats']}
• Среднее сообщений/чат: {stats['avg_messages_per_chat']}

**📝 По типам сообщений:**
• Пользовательские: {message_types.get('user', 0)}
• Системные: {message_types.get('system', 0)}

**🏆 Топ-5 активных чатов:**
"""
    
    for i, (deal_id, msg_count) in enumerate(top_chats, 1):
        detailed_text += f"{i}. Сделка #{deal_id}: {msg_count} сообщений\n"
    
    if daily_activity:
        detailed_text += f"\n**📅 Активность за неделю:**\n"
        for day, count in daily_activity:
            detailed_text += f"• {day}: {count} сообщений\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_chat_detailed_stats")],
        [InlineKeyboardButton(text="◀️ К чатам", callback_data="admin_chats")]
    ])
    
    try:
        await callback.message.edit_text(
            detailed_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка редактирования подробной статистики: {e}")
        try:
            await callback.message.answer(
                detailed_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as e2:
            logger.error(f"Ошибка отправки подробной статистики: {e2}")
            await callback.answer("❌ Ошибка отображения статистики", show_alert=True)
            return
    
    await callback.answer()

@router.message(Command("deal_chat"))
async def admin_deal_chat(message: Message):
    """Просмотр чата сделки по коду (команда /deal_chat код)"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Эта команда доступна только администраторам")
        return
    
    try:
        # Парсим аргументы команды
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer(
                "❌ Укажите код сделки\n"
                "Пример: `/deal_chat ABC123`",
                parse_mode="Markdown"
            )
            return
        
        deal_code = args[1].strip().upper()
        
        # Ищем сделку по коду
        deal = await db.get_deal_by_code(deal_code)
        if not deal:
            await message.answer(f"❌ Сделка с кодом `{deal_code}` не найдена", parse_mode="Markdown")
            return
        
        # Сообщаем о начале экспорта
        wait_msg = await message.answer("📝 Экспортирую чат...")
        
        # Создаем экспорт чата (та же функция, что используют участники)
        paste_result = await create_chat_paste(deal['id'], deal_code)
        
        if paste_result.startswith("http"):
            # Успешно создана ссылка на pastebin/dpaste
            response_text = f"""
💬 **Чат сделки #{deal['id']}**

🔢 **Код:** `{deal_code}`
💰 **Сумма:** {format_amount(deal['amount'], deal['currency_type'])}
📅 **Статус:** {deal['status']}

🔗 **Ссылка на полный экспорт чата:**
{paste_result}

✅ **Это та же ссылка, что получают участники при экспорте!**

⚠️ Ссылка действительна ограниченное время
"""
            disable_preview = True
        elif paste_result.startswith("Чат сделки"):
            # Возвращён текст чата (внешние сервисы недоступны)
            response_text = f"""
💬 **Чат сделки #{deal['id']}**

🔢 **Код:** `{deal_code}`
💰 **Сумма:** {format_amount(deal['amount'], deal['currency_type'])}
📅 **Статус:** {deal['status']}

📝 **Содержимое чата:**

```
{paste_result}
```

ℹ️ Внешние сервисы недоступны, показан краткий чат
"""
            disable_preview = False
        else:
            # Ошибка создания экспорта
            response_text = f"""
💬 **Чат сделки #{deal['id']}**

🔢 **Код:** `{deal_code}`
💰 **Сумма:** {format_amount(deal['amount'], deal['currency_type'])}
📅 **Статус:** {deal['status']}

❌ **Ошибка экспорта чата:**
{paste_result}

Попробуйте еще раз позже.
"""
            disable_preview = False
        
        # Удаляем сообщение ожидания и отправляем результат
        await wait_msg.delete()
        await message.answer(
            response_text,
            parse_mode="Markdown",
            disable_web_page_preview=disable_preview
        )
        
    except Exception as e:
        logger.error(f"Ошибка команды deal_chat: {e}")
        await message.answer("❌ Произошла ошибка при обработке команды")

@router.message(Command("complete_deal"))
async def admin_complete_deal(message: Message):
    """Завершение сделки командой администратором"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён")
        return
    
    try:
        # Парсим код или ID сделки из команды
        command_parts = message.text.split()
        if len(command_parts) != 2:
            await message.answer("❌ Использование: /complete_deal <код_сделки>")
            return
        
        deal_identifier = command_parts[1].strip().upper()
        
        # Пытаемся найти сделку по коду или ID
        deal = None
        if deal_identifier.isdigit():
            # Если введён числовой ID
            deal = await db.get_deal_by_id(int(deal_identifier))
        else:
            # Если введён код сделки
            deal = await db.get_deal_by_code(deal_identifier)
        
        if not deal:
            await message.answer(f"❌ Сделка {deal_identifier} не найдена")
            return
        
        # Проверяем статус сделки
        if deal['status'] != 'in_progress':
            status_names = {
                'waiting_buyer': 'ожидает покупателя',
                'waiting_guarantor': 'ожидает гаранта',
                'completed': 'уже завершена',
                'cancelled': 'отменена'
            }
            status_name = status_names.get(deal['status'], 'неизвестный статус')
            await message.answer(f"❌ Нельзя завершить сделку в статусе «{status_name}»")
            return
        
        # Завершаем сделку (используем ID админа как завершающего)
        success = await db.complete_deal(deal['id'], message.from_user.id)
        
        if success:
            # Добавляем системное сообщение о завершении админом
            admin_name = message.from_user.first_name or message.from_user.username or f"ID{message.from_user.id}"
            system_message = f"👨‍💼 Администратор {admin_name} завершил сделку"
            await db.add_deal_message(deal['id'], message.from_user.id, system_message, 'system')
            
            # Получаем информацию для уведомления
            seller = await db.get_user(deal['seller_id'])
            buyer = await db.get_user(deal['buyer_id'])
            guarantor = await db.get_user(deal['guarantor_id']) if deal['guarantor_id'] else None
            
            formatted_amount = format_amount(deal['amount'], deal['currency_type'])
            
            success_text = f"""
✅ **Сделка #{deal['id']} завершена администратором**

**Информация о сделке:**
🔢 Код: `{deal['deal_code']}`
💰 Сумма: {formatted_amount}
👤 Продавец: {seller['first_name'] or seller['username'] or 'Неизвестно'}
👤 Покупатель: {buyer['first_name'] or buyer['username'] or 'Неизвестно'}
👨‍💼 Гарант: {guarantor['first_name'] or guarantor['username'] or 'Не назначен' if guarantor else 'Не назначен'}

Сделка успешно завершена.
"""
            
            await message.answer(success_text, parse_mode="Markdown")
            
            # Уведомляем участников сделки
            completion_text = """
✅ **Сделка завершена администратором**

Сделка была завершена администратором системы.
Спасибо за использование нашего сервиса!
Не забудьте оценить своего партнёра.
"""
            
            bot = message.bot
            participants = [deal['seller_id'], deal['buyer_id']]
            if deal['guarantor_id']:
                participants.append(deal['guarantor_id'])
            
            for user_id in participants:
                if user_id != message.from_user.id:  # Не отправляем уведомление самому админу
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=completion_text,
                            reply_markup=get_rating_keyboard() if user_id in [deal['seller_id'], deal['buyer_id']] else get_back_to_main_keyboard(),
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.error(f"Ошибка уведомления участника {user_id}: {e}")
            
        else:
            await message.answer("❌ Ошибка при завершении сделки")
        
    except Exception as e:
        logger.error(f"Ошибка завершения сделки админом: {e}")
        await message.answer(f"❌ Ошибка: {e}")

@router.message(Command("cancel_deal"))
async def admin_cancel_deal(message: Message):
    """Отмена сделки командой администратором"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён")
        return
    
    try:
        # Парсим код или ID сделки из команды
        command_parts = message.text.split()
        if len(command_parts) != 2:
            await message.answer("❌ Использование: /cancel_deal <код_сделки>")
            return
        
        deal_identifier = command_parts[1].strip().upper()
        
        # Пытаемся найти сделку по коду или ID
        deal = None
        if deal_identifier.isdigit():
            # Если введён числовой ID
            deal = await db.get_deal_by_id(int(deal_identifier))
        else:
            # Если введён код сделки
            deal = await db.get_deal_by_code(deal_identifier)
        
        if not deal:
            await message.answer(f"❌ Сделка {deal_identifier} не найдена")
            return
        
        # Проверяем статус сделки
        if deal['status'] in ['completed', 'cancelled']:
            status_name = 'уже завершена' if deal['status'] == 'completed' else 'уже отменена'
            await message.answer(f"❌ Сделка {status_name}")
            return
        
        # Отменяем сделку
        success = await db.cancel_deal(deal['id'], message.from_user.id)
        
        if success:
            # Добавляем системное сообщение об отмене админом
            admin_name = message.from_user.first_name or message.from_user.username or f"ID{message.from_user.id}"
            system_message = f"👨‍💼 Администратор {admin_name} отменил сделку"
            await db.add_deal_message(deal['id'], message.from_user.id, system_message, 'system')
            
            # Получаем информацию для уведомления
            seller = await db.get_user(deal['seller_id'])
            buyer = await db.get_user(deal['buyer_id']) if deal['buyer_id'] else None
            guarantor = await db.get_user(deal['guarantor_id']) if deal['guarantor_id'] else None
            
            formatted_amount = format_amount(deal['amount'], deal['currency_type'])
            
            success_text = f"""
❌ **Сделка #{deal['id']} отменена администратором**

**Информация о сделке:**
🔢 Код: `{deal['deal_code']}`
💰 Сумма: {formatted_amount}
👤 Продавец: {seller['first_name'] or seller['username'] or 'Неизвестно'}
👤 Покупатель: {buyer['first_name'] or buyer['username'] or 'Не подключен' if buyer else 'Не подключен'}
👨‍💼 Гарант: {guarantor['first_name'] or guarantor['username'] or 'Не назначен' if guarantor else 'Не назначен'}

Сделка отменена.
"""
            
            await message.answer(success_text, parse_mode="Markdown")
            
            # Уведомляем участников сделки
            cancellation_text = """
❌ **Сделка отменена администратором**

Ваша сделка была отменена администратором системы.
Если у вас есть вопросы, обратитесь в поддержку.
"""
            
            bot = message.bot
            participants = [deal['seller_id']]
            if deal['buyer_id']:
                participants.append(deal['buyer_id'])
            if deal['guarantor_id']:
                participants.append(deal['guarantor_id'])
            
            for user_id in participants:
                if user_id != message.from_user.id:  # Не отправляем уведомление самому админу
                    try:
                        await bot.send_message(
                            chat_id=user_id,
                            text=cancellation_text,
                            reply_markup=get_back_to_main_keyboard(),
                            parse_mode="Markdown"
                        )
                    except Exception as e:
                        logger.error(f"Ошибка уведомления участника {user_id}: {e}")
            
        else:
            await message.answer("❌ Ошибка при отмене сделки")
        
    except Exception as e:
        logger.error(f"Ошибка отмены сделки админом: {e}")
        await message.answer(f"❌ Ошибка: {e}")

async def create_chat_paste(deal_id: int, deal_code: str) -> str:
    """Создание пасты чата сделки используя ту же логику, что и участники"""
    try:
        # Получаем данные для экспорта (та же функция, что используют участники)
        export_data = await db.get_deal_chat_export_data(deal_id)
        
        if not export_data:
            return "Ошибка: данные сделки не найдены"
        
        # Форматируем текст для экспорта (та же функция, что используют участники)
        export_text = await format_chat_export(export_data)
        
        # Загружаем на pastebin (та же функция, что используют участники)
        pastebin_url = await upload_to_pastebin(export_text, f"Chat_Deal_{deal_id}")
        
        if pastebin_url:
            return pastebin_url
        else:
            # Если не удалось загрузить, возвращаем краткую версию чата
            messages = export_data['messages']
            if not messages:
                return "Чат сделки пуст"
            
            # Формируем краткую версию для показа в Telegram
            deal = export_data['deal']
            chat_text = f"=== ЧАТ СДЕЛКИ {deal_code} ===\n\n"
            
            # Показываем последние 10 сообщений
            recent_messages = messages[-10:] if len(messages) > 10 else messages
            
            for msg in recent_messages:
                timestamp = msg['created_at'][:19] if msg['created_at'] else 'Неизвестно'
                
                if msg['message_type'] == 'system':
                    chat_text += f"[{timestamp}] СИСТЕМА: {msg['message_text']}\n"
                else:
                    name = msg['first_name'] or msg['username'] or f"ID{msg['user_id']}"
                    if msg['user_id'] == deal['seller_id']:
                        role = "ПРОДАВЕЦ"
                    elif msg['user_id'] == deal['buyer_id']:
                        role = "ПОКУПАТЕЛЬ"
                    elif msg['user_id'] == deal['guarantor_id']:
                        role = "ГАРАНТ"
                    else:
                        role = "УЧАСТНИК"
                    
                    chat_text += f"[{timestamp}] {name} ({role}): {msg['message_text']}\n"
            
            if len(messages) > 10:
                chat_text += f"\n... показано последних 10 из {len(messages)} сообщений"
            
            chat_text += f"\n\n=== КОНЕЦ ЧАТА ==="
            
            return f"Чат сделки (внешние сервисы недоступны):\n\n{chat_text}"
            
    except Exception as e:
        logger.error(f"Ошибка создания пасты чата: {e}")
        return f"Ошибка: {str(e)}"

@router.callback_query(F.data.startswith("admin_view_chat_"))
async def admin_view_chat(callback: CallbackQuery):
    """Просмотр чата сделки через экспорт"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    deal_id = int(callback.data.split("_")[-1])
    
    # Получаем информацию о сделке
    deal = await db.get_deal_by_id(deal_id)
    if not deal:
        await callback.answer("Сделка не найдена", show_alert=True)
        return
    
    await callback.answer("📝 Экспортирую чат...")
    
    # Создаем экспорт чата (та же функция, что используют участники)
    paste_result = await create_chat_paste(deal_id, deal['deal_code'])
    
    if paste_result.startswith("http"):
        # Успешно создана ссылка на pastebin/dpaste
        response_text = f"""
💬 **Чат сделки #{deal_id}**

🔢 **Код:** `{deal['deal_code']}`
💰 **Сумма:** {format_amount(deal['amount'], deal['currency_type'])}
📅 **Статус:** {deal['status']}

🔗 **Ссылка на полный экспорт чата:**
{paste_result}

✅ **Это та же ссылка, что получают участники при экспорте!**

⚠️ Ссылка действительна ограниченное время
"""
        disable_preview = True
    elif paste_result.startswith("Чат сделки"):
        # Возвращён текст чата (внешние сервисы недоступны)
        response_text = f"""
💬 **Чат сделки #{deal_id}**

🔢 **Код:** `{deal['deal_code']}`
💰 **Сумма:** {format_amount(deal['amount'], deal['currency_type'])}
📅 **Статус:** {deal['status']}

📝 **Содержимое чата:**

```
{paste_result}
```

ℹ️ Внешние сервисы недоступны, показан краткий чат
"""
        disable_preview = False
    else:
        # Ошибка создания экспорта
        response_text = f"""
💬 **Чат сделки #{deal_id}**

🔢 **Код:** `{deal['deal_code']}`
💰 **Сумма:** {format_amount(deal['amount'], deal['currency_type'])}
📅 **Статус:** {deal['status']}

❌ **Ошибка экспорта чата:**
{paste_result}

Попробуйте еще раз позже.
"""
        disable_preview = False
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"admin_view_chat_{deal_id}")],
        [InlineKeyboardButton(text="◀️ К списку сделок", callback_data="admin_deals")]
    ])
    
    try:
        await callback.message.edit_text(
            response_text,
            reply_markup=keyboard,
            parse_mode="Markdown",
            disable_web_page_preview=disable_preview
        )
    except Exception as e:
        # Если не можем отредактировать, отправляем новое сообщение
        logger.error(f"Ошибка редактирования сообщения чата: {e}")
        try:
            await callback.message.answer(
                response_text,
                reply_markup=keyboard,
                parse_mode="Markdown",
                disable_web_page_preview=disable_preview
            )
        except Exception as e2:
            logger.error(f"Ошибка отправки сообщения чата: {e2}")
            await callback.answer("❌ Ошибка отображения чата", show_alert=True)

# === УПРАВЛЕНИЕ СКАМЕРАМИ ===

@router.callback_query(F.data == "admin_scammers")
async def show_admin_scammers_menu(callback: CallbackQuery):
    """Меню управления скамерами"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    scammers = await db.get_all_scammers()
    
    menu_text = f"""
🚫 **Управление скамерами**

📊 **Статистика:**
• Всего скамеров в базе: {len(scammers)}

**Возможности:**
• Добавить пользователя в список скамеров
• Удалить из списка скамеров
• Просмотреть полный список с пруфами

Выберите действие:
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить скамера", callback_data="admin_add_scammer")],
        [InlineKeyboardButton(text="👀 Список скамеров", callback_data="admin_list_scammers")],
        [InlineKeyboardButton(text="➖ Удалить скамера", callback_data="admin_remove_scammer")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(
        menu_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_add_scammer")
async def start_add_scammer(callback: CallbackQuery, state: FSMContext):
    """Начало процесса добавления скамера"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_scammer_id)
    
    await callback.message.edit_text(
        """
🚫 **Добавление скамера**

Введите ID пользователя, которого нужно добавить в список скамеров:

💡 **Подсказка:** ID можно получить из профиля пользователя или переслав его сообщение.
""",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_scammers")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_scammer_id)
async def process_scammer_id(message: Message, state: FSMContext):
    """Обработка ID скамера"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён")
        return
    
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. Введите числовой ID пользователя:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_scammers")]
            ])
        )
        return
    
    # Проверяем, что пользователь не является администратором
    if user_id == OWNER_ID:
        await message.answer(
            "❌ Нельзя добавить администратора в список скамеров!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_scammers")]
            ])
        )
        await state.clear()
        return
    
    # Проверяем, не добавлен ли уже
    if await db.is_scammer(user_id):
        await message.answer(
            f"⚠️ Пользователь ID {user_id} уже находится в списке скамеров!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_scammers")]
            ])
        )
        await state.clear()
        return
    
    # Сохраняем ID и запрашиваем описание
    await state.update_data(scammer_id=user_id)
    await state.set_state(AdminStates.waiting_for_scammer_description)
    
    user = await db.get_user(user_id)
    user_name = "Неизвестно"
    if user:
        user_name = user.get('first_name') or user.get('username') or f"ID{user_id}"
    
    await message.answer(
        f"""
🚫 **Добавление скамера**

**Пользователь:** {user_name} (ID: `{user_id}`)

Теперь введите описание с пруфами и ссылками на чаты:

**Пример:**
```
Мошенник продаёт несуществующие товары.

Пруфы:
1. Скриншот переписки: t.me/c/...
2. Видео обман: t.me/c/...
3. Жалобы от жертв: @channel

Группа пострадавших: t.me/victims_chat
```

💡 **Рекомендации:**
• Укажите конкретные факты обмана
• Добавьте ссылки на доказательства
• Укажите чат для связи с пострадавшими
""",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_scammers")]
        ]),
        parse_mode="Markdown"
    )

@router.message(AdminStates.waiting_for_scammer_description)
async def process_scammer_description(message: Message, state: FSMContext):
    """Обработка описания скамера"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён")
        return
    
    description = message.text.strip()
    if len(description) < 10:
        await message.answer(
            "❌ Описание слишком короткое. Минимум 10 символов.\nВведите подробное описание с пруфами:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_scammers")]
            ])
        )
        return
    
    data = await state.get_data()
    scammer_id = data['scammer_id']
    
    # Добавляем скамера в базу
    success = await db.add_scammer(scammer_id, description, message.from_user.id)
    
    if success:
        user = await db.get_user(scammer_id)
        user_name = "Неизвестно"
        if user:
            user_name = user.get('first_name') or user.get('username') or f"ID{scammer_id}"
        
        success_text = f"""
✅ **Скамер добавлен!**

**Пользователь:** {user_name} (ID: `{scammer_id}`)
**Описание:** {description[:200]}{'...' if len(description) > 200 else ''}

Теперь этот пользователь отображается в списке скамеров для всех пользователей бота.
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить ещё", callback_data="admin_add_scammer")],
            [InlineKeyboardButton(text="👀 Список скамеров", callback_data="admin_list_scammers")],
            [InlineKeyboardButton(text="◀️ К управлению", callback_data="admin_scammers")]
        ])
        
        await message.answer(
            success_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "❌ Ошибка при добавлении скамера в базу данных!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_scammers")]
            ])
        )
    
    await state.clear()

@router.callback_query(F.data == "admin_list_scammers")
async def list_scammers_admin(callback: CallbackQuery):
    """Список скамеров для админа с полной информацией"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    scammers = await db.get_all_scammers()
    
    if not scammers:
        await callback.message.edit_text(
            "🚫 **Список скамеров**\n\n✅ Список скамеров пуст.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить скамера", callback_data="admin_add_scammer")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_scammers")]
            ]),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    scammers_text = f"🚫 **Список скамеров** ({len(scammers)} пользователей)\n\n"
    
    for i, scammer in enumerate(scammers[:10], 1):  # Показываем первые 10
        name = scammer['first_name'] or scammer['username'] or f"ID{scammer['user_id']}"
        date = scammer['created_at'][:10] if scammer['created_at'] else 'Неизвестно'
        added_by_name = scammer['added_by_name'] or scammer['added_by_username'] or f"ID{scammer['added_by']}"
        
        scammers_text += f"**{i}. {name}** (ID: `{scammer['user_id']}`)\n"
        scammers_text += f"📅 Добавлен: {date}\n"
        scammers_text += f"👤 Кем: {added_by_name}\n"
        
        # Показываем первые 150 символов описания
        description_short = scammer['description'][:150] + "..." if len(scammer['description']) > 150 else scammer['description']
        scammers_text += f"📝 {description_short}\n\n"
        
        # Прерываем если текст становится слишком длинным для Telegram
        if len(scammers_text) > 3500:
            scammers_text += f"... и ещё {len(scammers) - i} скамеров\n\n"
            break
    
    if len(scammers) > 10 and len(scammers_text) <= 3500:
        scammers_text += f"... и ещё {len(scammers) - 10} скамеров\n\n"
    
    scammers_text += "💡 Для удаления используйте кнопку \"Удалить скамера\""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add_scammer"),
         InlineKeyboardButton(text="➖ Удалить", callback_data="admin_remove_scammer")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin_list_scammers")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_scammers")]
    ])
    
    try:
        await callback.message.edit_text(
            scammers_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception:
        # Если не удалось изменить сообщение, отправляем новое
        await callback.message.answer(
            scammers_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    await callback.answer("🔄 Список обновлен")

@router.callback_query(F.data == "admin_remove_scammer")
async def start_remove_scammer(callback: CallbackQuery, state: FSMContext):
    """Начало процесса удаления скамера"""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    await state.set_state(AdminStates.waiting_for_remove_scammer_id)
    
    scammers = await db.get_all_scammers()
    
    if not scammers:
        await callback.message.edit_text(
            "🚫 **Удаление скамера**\n\n❌ Список скамеров пуст - некого удалять!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_scammers")]
            ]),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    # Формируем список для удобства
    scammers_list = ""
    for scammer in scammers[:15]:  # Показываем первые 15
        name = scammer['first_name'] or scammer['username'] or f"ID{scammer['user_id']}"
        scammers_list += f"• {name} - ID: `{scammer['user_id']}`\n"
    
    if len(scammers) > 15:
        scammers_list += f"... и ещё {len(scammers) - 15} скамеров"
    
    await callback.message.edit_text(
        f"""
🚫 **Удаление скамера**

**Текущие скамеры:**
{scammers_list}

Введите ID пользователя, которого нужно удалить из списка скамеров:
""",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_scammers")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(AdminStates.waiting_for_remove_scammer_id)
async def process_remove_scammer_id(message: Message, state: FSMContext):
    """Обработка удаления скамера"""
    if not is_admin(message.from_user.id):
        await message.answer("❌ Доступ запрещён")
        return
    
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. Введите числовой ID пользователя:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="admin_scammers")]
            ])
        )
        return
    
    # Проверяем, есть ли пользователь в списке скамеров
    if not await db.is_scammer(user_id):
        await message.answer(
            f"❌ Пользователь ID {user_id} не найден в списке скамеров!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_scammers")]
            ])
        )
        await state.clear()
        return
    
    # Получаем информацию о скамере перед удалением
    scammer_info = await db.get_scammer_info(user_id)
    
    # Удаляем скамера
    success = await db.remove_scammer(user_id, message.from_user.id)
    
    if success:
        user_name = scammer_info['first_name'] or scammer_info['username'] or f"ID{user_id}"
        
        success_text = f"""
✅ **Скамер удалён!**

**Пользователь:** {user_name} (ID: `{user_id}`)

Пользователь больше не отображается в списке скамеров.
"""
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➖ Удалить ещё", callback_data="admin_remove_scammer")],
            [InlineKeyboardButton(text="👀 Список скамеров", callback_data="admin_list_scammers")],
            [InlineKeyboardButton(text="◀️ К управлению", callback_data="admin_scammers")]
        ])
        
        await message.answer(
            success_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    else:
        await message.answer(
            "❌ Ошибка при удалении скамера из базы данных!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_scammers")]
            ])
        )
    
    await state.clear()