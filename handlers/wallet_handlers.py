import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import db
from config import WALLET_TYPES
from utils.messages import *
from utils.keyboards import *
from utils.validators import validate_wallet
from handlers.main_handlers import UserStates, check_user_access

logger = logging.getLogger(__name__)
router = Router()

class WalletStates(StatesGroup):
    waiting_for_wallet_address = State()

@router.callback_query(F.data == "wallets")
async def show_wallets_menu(callback: CallbackQuery, state: FSMContext):
    """Показ меню кошельков"""
    await state.clear()
    
    has_access, error_msg = await check_user_access(callback.from_user.id)
    if not has_access:
        await callback.message.edit_text(error_msg)
        return
    
    user_id = callback.from_user.id
    wallets = await db.get_user_wallets(user_id)
    
    if not wallets:
        await callback.message.edit_text(
            NO_WALLETS_MESSAGE,
            reply_markup=get_wallets_keyboard(has_wallets=False),
            parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text(
            "💳 **Управление кошельками**\n\nВыберите действие:",
            reply_markup=get_wallets_keyboard(has_wallets=True),
            parse_mode="Markdown"
        )
    
    await callback.answer()

@router.callback_query(F.data == "show_wallets")
async def show_wallets_list(callback: CallbackQuery):
    """Показ списка кошельков"""
    user_id = callback.from_user.id
    wallets = await db.get_user_wallets(user_id)
    
    if not wallets:
        await callback.message.edit_text(
            NO_WALLETS_MESSAGE,
            reply_markup=get_wallets_keyboard(has_wallets=False),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    # Формируем список кошельков
    wallets_text = "💳 **Ваши кошельки:**\n\n"
    
    for i, wallet in enumerate(wallets, 1):
        wallet_type_name = WALLET_TYPES.get(wallet['wallet_type'], wallet['wallet_type'])
        address = wallet['wallet_address']
        
        # Сокращаем длинные адреса
        if len(address) > 20:
            display_address = f"{address[:10]}...{address[-6:]}"
        else:
            display_address = address
        
        wallets_text += f"{i}. {wallet_type_name}\n"
        wallets_text += f"   `{display_address}`\n\n"
    
    await callback.message.edit_text(
        wallets_text,
        reply_markup=get_wallet_list_keyboard(wallets),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("wallet_info_"))
async def show_wallet_info(callback: CallbackQuery):
    """Показ информации о кошельке"""
    wallet_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    
    # Получаем кошелёк и проверяем принадлежность
    wallets = await db.get_user_wallets(user_id)
    wallet = next((w for w in wallets if w['id'] == wallet_id), None)
    
    if not wallet:
        await callback.answer("Кошелёк не найден", show_alert=True)
        return
    
    wallet_type_name = WALLET_TYPES.get(wallet['wallet_type'], wallet['wallet_type'])
    
    wallet_text = f"""
💳 **Информация о кошельке**

**Тип:** {wallet_type_name}
**Адрес:** `{wallet['wallet_address']}`
**Добавлен:** {wallet['created_at'][:10]}

Выберите действие:
"""
    
    await callback.message.edit_text(
        wallet_text,
        reply_markup=get_wallet_actions_keyboard(wallet_id),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "add_wallet")
async def start_add_wallet(callback: CallbackQuery, state: FSMContext):
    """Начало добавления кошелька"""
    has_access, error_msg = await check_user_access(callback.from_user.id)
    if not has_access:
        await callback.message.edit_text(error_msg)
        return
    
    await callback.message.edit_text(
        ADD_WALLET_MESSAGE,
        reply_markup=get_wallet_types_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("wallet_type_"))
async def select_wallet_type(callback: CallbackQuery, state: FSMContext):
    """Выбор типа кошелька"""
    wallet_type = callback.data.split("_")[-1]
    
    await state.update_data(wallet_type=wallet_type)
    await state.set_state(WalletStates.waiting_for_wallet_address)
    
    wallet_type_name = WALLET_TYPES.get(wallet_type, wallet_type)
    
    prompt_text = f"""
💳 **Добавление кошелька: {wallet_type_name}**

Введите адрес кошелька:

"""
    
    # Добавляем подсказки для каждого типа
    if wallet_type == "card":
        prompt_text += "Пример: `1234567890123456` (16 цифр)"
    elif wallet_type == "btc":
        prompt_text += "Пример: `1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa`"
    elif wallet_type == "usdt":
        prompt_text += "Пример: `0x742d35Cc6634C0532925a3b8D84162542E2C5aE6` (Ethereum)\nили `TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t` (TRON)"
    elif wallet_type == "ton":
        prompt_text += "Пример: `EQBvI0aFLnw2QbZgjMPCLRdtRHxhUyinQudWdKsRgLRgKE_Q`"
    
    await callback.message.edit_text(
        prompt_text,
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(WalletStates.waiting_for_wallet_address)
async def process_wallet_address(message: Message, state: FSMContext):
    """Обработка введённого адреса кошелька"""
    data = await state.get_data()
    wallet_type = data.get('wallet_type')
    address = message.text.strip()
    
    # Валидируем адрес
    is_valid, validation_message = validate_wallet(wallet_type, address)
    
    if not is_valid:
        await message.answer(
            f"{validation_message}\n\nПопробуйте ещё раз:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Добавляем кошелёк в базу
    user_id = message.from_user.id
    success = await db.add_wallet(user_id, wallet_type, address)
    
    if success:
        wallet_type_name = WALLET_TYPES.get(wallet_type, wallet_type)
        success_text = WALLET_ADDED_SUCCESS.format(
            wallet_type=wallet_type_name,
            address=address
        )
        
        await message.answer(
            success_text,
            reply_markup=get_wallets_keyboard(has_wallets=True),
            parse_mode="Markdown"
        )
        
        await state.clear()
    else:
        await message.answer(
            "❌ Ошибка при добавлении кошелька. Попробуйте позже.",
            reply_markup=get_cancel_keyboard()
        )

@router.callback_query(F.data.startswith("delete_wallet_"))
async def confirm_delete_wallet(callback: CallbackQuery):
    """Подтверждение удаления кошелька"""
    wallet_id = callback.data.split("_")[-1]
    
    await callback.message.edit_text(
        "⚠️ **Подтверждение удаления**\n\nВы уверены, что хотите удалить этот кошелёк?",
        reply_markup=get_confirmation_keyboard("delete_wallet", wallet_id),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("confirm_delete_wallet_"))
async def delete_wallet(callback: CallbackQuery):
    """Удаление кошелька"""
    wallet_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    
    success = await db.delete_wallet(wallet_id, user_id)
    
    if success:
        await callback.message.edit_text(
            WALLET_DELETED_SUCCESS,
            reply_markup=get_wallets_keyboard(has_wallets=True),
            parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text(
            "❌ Ошибка при удалении кошелька",
            reply_markup=get_wallets_keyboard(has_wallets=True)
        )
    
    await callback.answer()

async def user_has_wallets(user_id: int) -> bool:
    """Проверка наличия кошельков у пользователя"""
    wallets = await db.get_user_wallets(user_id)
    return len(wallets) > 0 

async def user_has_compatible_wallet(user_id: int, currency_type: str) -> bool:
    """Проверка наличия совместимого кошелька для валюты"""
    wallets = await db.get_user_wallets(user_id)
    
    if not wallets:
        return False
    
    # Совместимость валют и кошельков
    compatible_wallets = {
        'rub': ['card'],  # Рубли - банковская карта
        'crypto': ['btc', 'usdt', 'ton'],  # Крипта - любой криптокошелёк
        'stars': ['card', 'btc', 'usdt', 'ton']  # Звёзды - любой кошелёк
    }
    
    required_wallet_types = compatible_wallets.get(currency_type, [])
    if not required_wallet_types:
        return False
    
    # Проверяем есть ли у пользователя подходящий кошелёк
    user_wallet_types = [wallet['wallet_type'] for wallet in wallets]
    return any(wallet_type in required_wallet_types for wallet_type in user_wallet_types) 