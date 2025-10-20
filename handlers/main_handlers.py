import asyncio
import logging
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import db
from config import OWNER_ID, DEFAULT_COMMISSION
from utils.messages import *
from utils.keyboards import *
from utils.validators import format_amount

logger = logging.getLogger(__name__)
router = Router()

class UserStates(StatesGroup):
    waiting_for_deal_code = State()
    waiting_for_amount = State()
    waiting_for_description = State()
    waiting_for_wallet_address = State()
    waiting_for_admin_user_id = State()
    waiting_for_balance_change = State()
    waiting_for_scammer_id = State()
    waiting_for_scammer_description = State()
    waiting_for_validation_id = State()

async def register_user(user_id: int, username: str = None, first_name: str = None) -> bool:
    """Регистрация нового пользователя"""
    user = await db.get_user(user_id)
    if not user:
        return await db.create_user(user_id, username, first_name)
    return True

async def check_user_access(user_id: int) -> tuple[bool, str]:
    """Проверка доступа пользователя"""
    # Проверяем режим технических работ (админы всегда проходят)
    if user_id != OWNER_ID and await db.is_maintenance_mode():
        return False, """
🔧 **Технические работы**

Бот временно недоступен из-за технических работ.
Попробуйте позже.

Приносим извинения за неудобства.
"""
    
    user = await db.get_user(user_id)
    if not user:
        return False, "Пользователь не найден"
    if user.get('is_banned', False):
        return False, ERROR_USER_BANNED
    return True, ""

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработка команды /start"""
    await state.clear()
    
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    
    # Регистрируем пользователя
    await register_user(user_id, username, first_name)
    
    # Проверяем доступ
    has_access, error_msg = await check_user_access(user_id)
    if not has_access:
        await message.answer(error_msg)
        return
    
    await message.answer(
        WELCOME_MESSAGE,
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "main_menu")
async def show_main_menu(callback: CallbackQuery, state: FSMContext):
    """Показ главного меню"""
    await state.clear()
    
    has_access, error_msg = await check_user_access(callback.from_user.id)
    if not has_access:
        await callback.message.edit_text(error_msg)
        return
    
    await callback.message.edit_text(
        MAIN_MENU_MESSAGE,
        reply_markup=get_main_menu_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "profile")
async def show_profile(callback: CallbackQuery):
    """Показ профиля пользователя"""
    user_id = callback.from_user.id
    user = await db.get_user(user_id)
    wallets = await db.get_user_wallets(user_id)
    
    if not user:
        await callback.answer("Ошибка получения профиля")
        return
    
    profile_text = f"""
👤 **Ваш профиль**

📊 **Статистика:**
• Рейтинг: {user['rating']} ⭐
• Всего сделок: {user['total_deals']}
• Завершено: {user['completed_deals']}

💰 **Балансы:**
⭐ Звёзды: {user['balance_stars']}
₿ Крипта: {user.get('balance_crypto', 0):.2f}
💰 Рубли: {user.get('balance_rub', 0):.2f}

💳 **Кошельки:** {len(wallets)}
"""
    
    await callback.message.edit_text(
        profile_text,
        reply_markup=get_profile_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "support")
async def show_support(callback: CallbackQuery):
    """Показ контактов поддержки"""
    support_text = """
📞 **Поддержка**

Если у вас возникли вопросы или проблемы, обратитесь к администратору:

**Способы связи:**
💬 Telegram: @Siriusatop123
⏰ Время работы: 8:00 - 22:00

**Дополнительная информация:**
🚫 Список скамеров: @scamnftalert

**Часто задаваемые вопросы:**
• Как создать сделку?
• Как стать гарантом?
• Как добавить кошелёк?
• Как работает система?

Обращайтесь в рабочее время для быстрого ответа!
"""
    
    await callback.message.edit_text(
        support_text,
        reply_markup=get_back_to_main_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "deal_history")
async def show_deal_history(callback: CallbackQuery):
    """Показ истории сделок пользователя"""
    user_id = callback.from_user.id
    deals = await db.get_user_deals_history(user_id)
    
    if not deals:
        await callback.message.edit_text(
            "📈 **История сделок**\n\nУ вас пока нет завершенных сделок.",
            reply_markup=get_back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    # Показываем последние 10 сделок
    history_text = "📈 **История ваших сделок:**\n\n"
    
    for deal in deals[:10]:
        # Определяем статус с эмодзи
        status_emoji = {
            'waiting_buyer': '⏳',
            'waiting_guarantor': '🔍', 
            'in_progress': '⚡',
            'completed': '✅',
            'cancelled': '❌'
        }.get(deal['status'], '❓')
        
        # Определяем роль пользователя
        if deal['seller_id'] == user_id:
            user_role = "Продавец"
            partner_name = deal['buyer_name'] or deal['buyer_username'] or f"ID{deal['buyer_id']}" if deal['buyer_id'] else "Нет покупателя"
        elif deal['buyer_id'] == user_id:
            user_role = "Покупатель"
            partner_name = deal['seller_name'] or deal['seller_username'] or f"ID{deal['seller_id']}"
        elif deal['guarantor_id'] == user_id:
            user_role = "Гарант"
            seller_name = deal['seller_name'] or deal['seller_username'] or f"ID{deal['seller_id']}"
            buyer_name = deal['buyer_name'] or deal['buyer_username'] or f"ID{deal['buyer_id']}" if deal['buyer_id'] else "Нет покупателя"
            partner_name = f"{seller_name} ↔ {buyer_name}"
        else:
            user_role = "Неизвестно"
            partner_name = "Неизвестно"
        
        # Форматируем дату
        date = deal['created_at'][:10] if deal['created_at'] else 'Неизвестно'
        
        history_text += f"{status_emoji} **Сделка #{deal['id']}** - {user_role}\n"
        history_text += f"💰 {format_amount(deal['amount'], deal['currency_type'])}\n"
        history_text += f"👤 Партнер: {partner_name}\n"
        history_text += f"📅 {date}\n"
        
        # Добавляем описание если есть место
        if len(deal['description']) <= 30:
            history_text += f"📝 {deal['description']}\n"
        
        history_text += "\n"
    
    # Если сделок больше 10, добавляем информацию об этом
    if len(deals) > 10:
        history_text += f"И ещё {len(deals) - 10} сделок...\n"
    
    # Добавляем общую статистику
    completed_deals = len([d for d in deals if d['status'] == 'completed'])
    cancelled_deals = len([d for d in deals if d['status'] == 'cancelled'])
    
    history_text += f"\n📊 **Статистика:**\n"
    history_text += f"✅ Завершено: {completed_deals}\n"
    history_text += f"❌ Отменено: {cancelled_deals}\n"
    history_text += f"📊 Всего: {len(deals)}"
    
    await callback.message.edit_text(
        history_text,
        reply_markup=get_back_to_main_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "faq")
async def show_faq(callback: CallbackQuery):
    """Показ FAQ"""
    faq_text = FAQ_MESSAGE.format(commission=DEFAULT_COMMISSION)
    
    await callback.message.edit_text(
        faq_text,
        reply_markup=get_back_to_main_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "my_deals")
async def show_my_deals(callback: CallbackQuery):
    """Показ активных сделок пользователя"""
    user_id = callback.from_user.id
    
    # Проверяем активную сделку как продавец/покупатель
    deal = await db.get_user_active_deal(user_id)
    
    # Если не найдена, проверяем как гарант
    if not deal:
        deal = await db.get_guarantor_active_deal(user_id)
    
    if not deal:
        await callback.message.edit_text(
            "У вас нет активных сделок",
            reply_markup=get_back_to_main_keyboard()
        )
        await callback.answer()
        return
    
    # Определяем роль пользователя в сделке
    if deal['seller_id'] == user_id:
        user_role = "seller"
    elif deal['buyer_id'] == user_id:
        user_role = "buyer"
    elif deal['guarantor_id'] == user_id:
        user_role = "guarantor"
    else:
        user_role = "unknown"
    
    # Получаем информацию об участниках
    seller = await db.get_user(deal['seller_id'])
    buyer = await db.get_user(deal['buyer_id']) if deal['buyer_id'] else None
    guarantor = await db.get_user(deal['guarantor_id']) if deal['guarantor_id'] else None
    
    # Функция для форматирования рейтинга
    def format_rating(rating):
        stars = "⭐" * int(rating)
        if rating != int(rating):
            stars += "✨"  # Полузвезда для дробных рейтингов
        return f"{stars} ({rating:.1f})"
    
    # Формируем сообщение в зависимости от статуса
    if deal['status'] == 'waiting_buyer':
        deal_text = f"""
🔄 **Ожидание покупателя**

🔢 **Код сделки:** `{deal['deal_code']}`
💰 **Сумма:** {format_amount(deal['amount'], deal['currency_type'])}
📝 **Описание:** {deal['description']}
👤 **Продавец:** {seller['first_name'] or seller['username'] or 'Неизвестно'}
📊 **Рейтинг продавца:** {format_rating(seller.get('rating', 5.0))}

Отправьте код покупателю для присоединения к сделке.
"""
    
    elif deal['status'] == 'waiting_guarantor':
        deal_text = f"""
⏳ **Ожидание гаранта**

🔢 **Код сделки:** `{deal['deal_code']}`
💰 **Сумма:** {format_amount(deal['amount'], deal['currency_type'])}
👤 **Продавец:** {seller['first_name'] or seller['username'] or 'Неизвестно'}
📊 **Рейтинг продавца:** {format_rating(seller.get('rating', 5.0))}
👤 **Покупатель:** {buyer['first_name'] or buyer['username'] or 'Неизвестно' if buyer else 'Не подключен'}

Нажмите "Позвать гаранта" для начала сделки.
"""
    
    elif deal['status'] == 'in_progress':
        if user_role == "guarantor":
            deal_text = f"""
⚡ **Вы ведете сделку**

🔢 **Код сделки:** `{deal['deal_code']}`
💰 **Сумма:** {format_amount(deal['amount'], deal['currency_type'])}
📝 **Описание:** {deal['description']}
👤 **Продавец:** {seller['first_name'] or seller['username'] or 'Неизвестно'}
📊 **Рейтинг продавца:** {format_rating(seller.get('rating', 5.0))}
👤 **Покупатель:** {buyer['first_name'] or buyer['username'] or 'Неизвестно' if buyer else 'Не подключен'}

Как гарант вы можете:
✅ Завершить сделку
❌ Отменить сделку
💬 Общаться в чате
"""
        else:
            deal_text = f"""
⚡ **Сделка в процессе**

🔢 **Код сделки:** `{deal['deal_code']}`
💰 **Сумма:** {format_amount(deal['amount'], deal['currency_type'])}
👤 **Продавец:** {seller['first_name'] or seller['username'] or 'Неизвестно'}
📊 **Рейтинг продавца:** {format_rating(seller.get('rating', 5.0))}
👤 **Покупатель:** {buyer['first_name'] or buyer['username'] or 'Неизвестно' if buyer else 'Не подключен'}
👨‍💼 **Гарант:** {guarantor['first_name'] or guarantor['username'] or 'Неизвестно' if guarantor else 'Не назначен'}
{'📊 **Рейтинг гаранта:** ' + format_rating(guarantor.get('rating', 5.0)) if guarantor else ''}

Следуйте инструкциям гаранта.
"""
    
    else:
        deal_text = "Неизвестный статус сделки"
    
    keyboard = await get_deal_actions_keyboard(deal['status'], user_role, deal['id'], user_id)
    await callback.message.edit_text(
        deal_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "scammers")
async def show_scammers_list(callback: CallbackQuery):
    """Показ списка скамеров"""
    scammers = await db.get_all_scammers()
    
    if not scammers:
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔍 Валидация по ID", callback_data="validate_user_id")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
        ])
        
        await callback.message.edit_text(
            """🚫 **Список скамеров**

✅ В данный момент список скамеров пуст.
Будьте осторожны при проведении сделок!

📢 **Дополнительная информация:**
🔗 Канал с предупреждениями: https://t.me/scamnftalert""",
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    scammers_text = "🚫 **Список скамеров**\n\n⚠️ Эти пользователи замечены в мошенничестве:\n\n"
    
    for i, scammer in enumerate(scammers[:20], 1):  # Показываем первые 20
        name = scammer['first_name'] or scammer['username'] or f"ID{scammer['user_id']}"
        date = scammer['created_at'][:10] if scammer['created_at'] else 'Неизвестно'
        
        scammers_text += f"**{i}. {name}** (ID: `{scammer['user_id']}`)\n"
        scammers_text += f"📅 Добавлен: {date}\n"
        scammers_text += f"📝 {scammer['description'][:100]}{'...' if len(scammer['description']) > 100 else ''}\n\n"
    
    if len(scammers) > 20:
        scammers_text += f"... и ещё {len(scammers) - 20} пользователей\n\n"
    
    scammers_text += """⚠️ **Будьте внимательны при работе с этими пользователями!**

📢 **Дополнительная информация о скамерах:**
🔗 Канал с актуальными предупреждениями: https://t.me/scamnftalert"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Валидация по ID", callback_data="validate_user_id")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu")]
    ])
    
    await callback.message.edit_text(
        scammers_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Админ-панель"""
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ У вас нет доступа к админ-панели")
        return
    
    await message.answer(
        ADMIN_PANEL_MESSAGE,
        reply_markup=get_admin_keyboard(),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "admin_panel")
async def show_admin_panel(callback: CallbackQuery):
    """Показ админ-панели"""
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    await callback.message.edit_text(
        ADMIN_PANEL_MESSAGE,
        reply_markup=get_admin_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_stats")
async def show_admin_stats(callback: CallbackQuery):
    """Показ статистики для админа"""
    if callback.from_user.id != OWNER_ID:
        await callback.answer("❌ Доступ запрещён", show_alert=True)
        return
    
    stats = await db.get_stats()
    
    stats_text = ADMIN_STATS_MESSAGE.format(
        total_users=stats['total_users'],
        banned_users=stats['banned_users'],
        guarantors=stats['guarantors'],
        total_deals=stats['total_deals'],
        completed_deals=stats['completed_deals'],
        cancelled_deals=stats['cancelled_deals'],
        active_deals=stats['active_deals'],
        total_volume=f"{stats['total_volume']:,.2f}"
    )
    
    # Кнопка назад к админ-панели
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])
    
    await callback.message.edit_text(
        stats_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(Command("logs"))
async def cmd_logs(message: Message):
    """Просмотр логов для админа"""
    if message.from_user.id != OWNER_ID:
        await message.answer("❌ У вас нет доступа к логам")
        return
    
    logs = await db.get_logs(50)  # Последние 50 записей
    
    if not logs:
        await message.answer("📜 Логи пусты")
        return
    
    logs_text = "📜 **Последние действия:**\n\n"
    
    for log in logs[:20]:  # Показываем только первые 20 для читаемости
        timestamp = log['timestamp'][:19]  # Убираем миллисекунды
        action = log['action']
        user_id = log['user_id'] or 'Система'
        details = log['details'] or ''
        
        logs_text += f"`{timestamp}` - {action}\n"
        logs_text += f"Пользователь: {user_id}\n"
        if details:
            logs_text += f"Детали: {details}\n"
        logs_text += "\n"
    
    if len(logs_text) > 4000:  # Telegram ограничение
        logs_text = logs_text[:4000] + "...\n\nИспользуйте /logs для полного списка"
    
    await message.answer(logs_text, parse_mode="Markdown")

@router.callback_query(F.data == "validate_user_id")
async def start_user_validation(callback: CallbackQuery, state: FSMContext):
    """Начало валидации пользователя по ID"""
    await state.set_state(UserStates.waiting_for_validation_id)
    
    await callback.message.edit_text(
        """🔍 **Валидация пользователя**

Введите ID пользователя для получения ссылки на его профиль.

💡 **Зачем это нужно:**
• Проверить правильность ID скамера
• Убедиться что вы смотрите на нужного человека
• Получить ссылку на профиль для перехода

**Примеры:**
• `123456789` → получите @username или ссылку
• Можно скопировать ID из списка скамеров

Введите ID:""",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data="scammers")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(UserStates.waiting_for_validation_id)
async def process_user_validation(message: Message, state: FSMContext):
    """Обработка валидации пользователя"""
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer(
            "❌ Неверный формат ID. Введите числовой ID пользователя:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="❌ Отмена", callback_data="scammers")]
            ])
        )
        return
    
    # Проверяем есть ли пользователь в базе
    user = await db.get_user(user_id)
    is_scammer = await db.is_scammer(user_id)
    
    # Формируем ответ
    validation_text = f"""🔍 **Результат валидации**

**ID:** `{user_id}`
"""
    
    # Определяем информацию о пользователе
    if user:
        name = user.get('first_name', 'Не указано')
        username = user.get('username')
        
        validation_text += f"**Имя:** {name}\n"
        
        if username:
            validation_text += f"**Username:** @{username}\n"
            validation_text += f"**Ссылка:** @{username}\n"
        else:
            validation_text += f"**Username:** Не установлен\n"
            validation_text += f"**Ссылка:** [Открыть профиль](tg://user?id={user_id})\n"
            
        validation_text += f"**Статус:** Найден в базе бота ✅\n"
    else:
        validation_text += f"**Статус:** Не найден в базе бота\n"
        validation_text += f"**Ссылка:** [Открыть профиль](tg://user?id={user_id})\n"
        validation_text += f"**Примечание:** Пользователь может существовать в Telegram, но не взаимодействовал с ботом\n"
    
    # Статус скамера
    validation_text += f"**Скамер:** {'Да ⚠️' if is_scammer else 'Нет ✅'}\n"
    
    validation_text += f"""
💡 **Инструкция:**
1. Нажмите на ссылку выше для перехода в профиль
2. Проверьте фото, имя и описание профиля  
3. Убедитесь что это тот человек, которого вы ищете
4. {'Будьте особенно осторожны - этот пользователь помечен как скамер!' if is_scammer else 'Соблюдайте осторожность при любых сделках'}"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Проверить другой ID", callback_data="validate_user_id")],
        [InlineKeyboardButton(text="◀️ К списку скамеров", callback_data="scammers")]
    ])
    
    await message.answer(
        validation_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await state.clear()

# Автоматическая очистка просроченных сделок
async def auto_cleanup_deals():
    """Автоматическая очистка просроченных сделок"""
    while True:
        try:
            deleted_count = await db.delete_expired_deals()
            if deleted_count > 0:
                logger.info(f"Удалено просроченных сделок: {deleted_count}")
        except Exception as e:
            logger.error(f"Ошибка очистки сделок: {e}")
        
        # Проверяем каждые 5 минут
        await asyncio.sleep(300) 