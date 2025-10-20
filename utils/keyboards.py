from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from config import CURRENCY_TYPES, WALLET_TYPES

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆕 Создать сделку", callback_data="create_deal")],
        [InlineKeyboardButton(text="🔍 Присоединиться к сделке", callback_data="join_deal")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="💳 Кошельки", callback_data="wallets")],
        [InlineKeyboardButton(text="📊 Мои сделки", callback_data="my_deals"),
         InlineKeyboardButton(text="❓ FAQ", callback_data="faq")],
        [InlineKeyboardButton(text="🚫 Скамеры", callback_data="scammers"),
         InlineKeyboardButton(text="📞 Поддержка", callback_data="support")]
    ])
    return keyboard

def get_profile_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура профиля"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📈 История сделок", callback_data="deal_history")],
        [InlineKeyboardButton(text="⭐ Мои оценки", callback_data="my_ratings")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
    ])
    return keyboard

def get_wallets_keyboard(has_wallets: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура кошельков"""
    buttons = []
    
    if has_wallets:
        buttons.append([InlineKeyboardButton(text="👀 Показать кошельки", callback_data="show_wallets")])
    
    buttons.extend([
        [InlineKeyboardButton(text="➕ Добавить кошелёк", callback_data="add_wallet")],
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_wallet_types_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора типа кошелька"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Банковская карта", callback_data="wallet_type_card")],
        [InlineKeyboardButton(text="₿ Bitcoin", callback_data="wallet_type_btc")],
        [InlineKeyboardButton(text="💎 USDT", callback_data="wallet_type_usdt")],
        [InlineKeyboardButton(text="💙 TON", callback_data="wallet_type_ton")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="wallets")]
    ])
    return keyboard

def get_wallet_list_keyboard(wallets: list) -> InlineKeyboardMarkup:
    """Клавиатура со списком кошельков"""
    buttons = []
    
    for wallet in wallets:
        wallet_name = WALLET_TYPES.get(wallet['wallet_type'], wallet['wallet_type'])
        address_short = wallet['wallet_address'][:10] + "..." if len(wallet['wallet_address']) > 13 else wallet['wallet_address']
        
        buttons.append([
            InlineKeyboardButton(
                text=f"{wallet_name}: {address_short}",
                callback_data=f"wallet_info_{wallet['id']}"
            )
        ])
    
    buttons.append([InlineKeyboardButton(text="➕ Добавить", callback_data="add_wallet")])
    buttons.append([InlineKeyboardButton(text="◀️ Назад", callback_data="wallets")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_wallet_actions_keyboard(wallet_id: int) -> InlineKeyboardMarkup:
    """Действия с кошельком"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete_wallet_{wallet_id}")],
        [InlineKeyboardButton(text="◀️ К кошелькам", callback_data="show_wallets")]
    ])
    return keyboard

def get_currency_selection_keyboard() -> InlineKeyboardMarkup:
    """Выбор валюты для сделки"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Рубли", callback_data="currency_rub")],
        [InlineKeyboardButton(text="₿ Крипта", callback_data="currency_crypto")],
        [InlineKeyboardButton(text="⭐ Звёзды", callback_data="currency_stars")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu")]
    ])
    return keyboard

async def get_deal_actions_keyboard(deal_status: str, user_role: str, deal_id: int = None, user_id: int = None) -> InlineKeyboardMarkup:
    """Действия со сделкой в зависимости от статуса и роли"""
    from database import db  # Импорт здесь чтобы избежать циклических импортов
    
    buttons = []
    
    if deal_status == "waiting_buyer" and user_role == "seller":
        buttons.append([InlineKeyboardButton(text="❌ Отменить сделку", callback_data="cancel_deal")])
    
    elif deal_status == "waiting_guarantor":
        # Чат доступен когда есть покупатель
        if deal_id and user_id:
            unread_count = await db.get_unread_messages_count(deal_id, user_id)
            chat_text = f"💬 Чат сделки"
            if unread_count > 0:
                chat_text += f" ({unread_count})"
            buttons.append([InlineKeyboardButton(text=chat_text, callback_data=f"deal_chat_{deal_id}")])
        buttons.append([InlineKeyboardButton(text="🚨 Позвать гаранта", callback_data="call_guarantor")])
        if user_role == "seller":
            buttons.append([InlineKeyboardButton(text="❌ Отменить сделку", callback_data="cancel_deal")])
    
    elif deal_status == "in_progress":
        # Чат доступен для всех участников активной сделки
        if deal_id and user_id:
            unread_count = await db.get_unread_messages_count(deal_id, user_id)
            chat_text = f"💬 Чат сделки"
            if unread_count > 0:
                chat_text += f" ({unread_count})"
            buttons.append([InlineKeyboardButton(text=chat_text, callback_data=f"deal_chat_{deal_id}")])
        
        if user_role == "guarantor":
            buttons.extend([
                [InlineKeyboardButton(text="✅ Завершить сделку", callback_data="complete_deal")],
                [InlineKeyboardButton(text="❌ Отменить сделку", callback_data="cancel_deal")]
            ])
    
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_deal_actions_keyboard_sync(deal_status: str, user_role: str, deal_id: int = None) -> InlineKeyboardMarkup:
    """Синхронная версия для обратной совместимости"""
    buttons = []
    
    if deal_status == "waiting_buyer" and user_role == "seller":
        buttons.append([InlineKeyboardButton(text="❌ Отменить сделку", callback_data="cancel_deal")])
    
    elif deal_status == "waiting_guarantor":
        if deal_id:
            buttons.append([InlineKeyboardButton(text="💬 Чат сделки", callback_data=f"deal_chat_{deal_id}")])
        buttons.append([InlineKeyboardButton(text="🚨 Позвать гаранта", callback_data="call_guarantor")])
        if user_role == "seller":
            buttons.append([InlineKeyboardButton(text="❌ Отменить сделку", callback_data="cancel_deal")])
    
    elif deal_status == "in_progress":
        if deal_id:
            buttons.append([InlineKeyboardButton(text="💬 Чат сделки", callback_data=f"deal_chat_{deal_id}")])
        
        if user_role == "guarantor":
            buttons.extend([
                [InlineKeyboardButton(text="✅ Завершить сделку", callback_data="complete_deal")],
                [InlineKeyboardButton(text="❌ Отменить сделку", callback_data="cancel_deal")]
            ])
    
    buttons.append([InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_guarantor_response_keyboard(deal_id: int) -> InlineKeyboardMarkup:
    """Ответ гаранта на вызов"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Принять сделку", callback_data=f"accept_deal_{deal_id}")],
        [InlineKeyboardButton(text="❌ Отказаться", callback_data=f"decline_deal_{deal_id}")]
    ])
    return keyboard

def get_rating_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура для оценки"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="1 ⭐", callback_data="rate_1"),
            InlineKeyboardButton(text="2 ⭐", callback_data="rate_2"),
            InlineKeyboardButton(text="3 ⭐", callback_data="rate_3")
        ],
        [
            InlineKeyboardButton(text="4 ⭐", callback_data="rate_4"),
            InlineKeyboardButton(text="5 ⭐", callback_data="rate_5")
        ]
    ])
    return keyboard

def get_admin_keyboard() -> InlineKeyboardMarkup:
    """Админская панель"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="👥 Управление пользователями", callback_data="admin_users")],
        [InlineKeyboardButton(text="💼 Все сделки", callback_data="admin_deals")],
        [InlineKeyboardButton(text="💬 Управление чатами", callback_data="admin_chats")],
        [InlineKeyboardButton(text="👨‍💼 Управление гарантами", callback_data="admin_guarantors")],
        [InlineKeyboardButton(text="🚫 Управление скамерами", callback_data="admin_scammers")],
        [InlineKeyboardButton(text="📜 Логи", callback_data="admin_logs")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="⚙️ Настройки", callback_data="admin_settings")]
    ])
    return keyboard

def get_admin_users_keyboard() -> InlineKeyboardMarkup:
    """Управление пользователями"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Найти пользователя", callback_data="admin_find_user")],
        [InlineKeyboardButton(text="🚫 Заблокированные", callback_data="admin_banned_users")],
        [InlineKeyboardButton(text="💰 Изменить баланс", callback_data="admin_change_balance")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])
    return keyboard

def get_admin_guarantors_keyboard() -> InlineKeyboardMarkup:
    """Управление гарантами"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить гаранта", callback_data="admin_add_guarantor")],
        [InlineKeyboardButton(text="➖ Удалить гаранта", callback_data="admin_remove_guarantor")],
        [InlineKeyboardButton(text="📋 Список гарантов", callback_data="admin_list_guarantors")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_panel")]
    ])
    return keyboard

def get_back_to_main_keyboard() -> InlineKeyboardMarkup:
    """Возврат в главное меню"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏠 Главное меню", callback_data="main_menu")]
    ])
    return keyboard

def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Отмена действия"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="main_menu")]
    ])
    return keyboard

def get_confirmation_keyboard(action: str, item_id: str = "") -> InlineKeyboardMarkup:
    """Подтверждение действия"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"confirm_{action}_{item_id}"),
            InlineKeyboardButton(text="❌ Нет", callback_data="main_menu")
        ]
    ])
    return keyboard 