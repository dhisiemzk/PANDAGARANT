import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import db
from config import CURRENCY_TYPES, WALLET_TYPES, DEFAULT_COMMISSION
from utils.messages import *
from utils.keyboards import *
from utils.validators import generate_deal_code, is_valid_amount, format_amount
from handlers.main_handlers import check_user_access
from handlers.wallet_handlers import user_has_wallets, user_has_compatible_wallet

logger = logging.getLogger(__name__)
router = Router()

class DealStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_description = State()
    waiting_for_deal_code = State()

@router.callback_query(F.data == "create_deal")
async def start_create_deal(callback: CallbackQuery, state: FSMContext):
    """Начало создания сделки"""
    user_id = callback.from_user.id
    
    # Проверяем доступ
    has_access, error_msg = await check_user_access(user_id)
    if not has_access:
        await callback.message.edit_text(error_msg)
        return
    
    # Проверяем, не является ли пользователь скамером
    if await db.is_scammer(user_id):
        scammer_info = await db.get_scammer_info(user_id)
        warning_text = f"""
🚫 **Доступ к созданию сделок ограничен**

Ваш аккаунт находится в списке ненадёжных пользователей.

**Причина:** {scammer_info['description'][:200]}{'...' if len(scammer_info['description']) > 200 else ''}

Если вы считаете это ошибкой, обратитесь в поддержку.
"""
        await callback.message.edit_text(
            warning_text,
            reply_markup=get_back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    # Проверяем, нет ли уже активной сделки
    active_deal = await db.get_user_active_deal(user_id)
    if active_deal:
        await callback.message.edit_text(
            ERROR_ALREADY_HAVE_DEAL,
            reply_markup=get_back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    # Проверяем наличие кошельков
    if not await user_has_wallets(user_id):
        await callback.message.edit_text(
            NO_WALLETS_MESSAGE,
            reply_markup=get_wallets_keyboard(has_wallets=False),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    # Показываем выбор валюты
    await callback.message.edit_text(
        CREATE_DEAL_SELECT_CURRENCY,
        reply_markup=get_currency_selection_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("currency_"))
async def select_currency(callback: CallbackQuery, state: FSMContext):
    """Выбор валюты для сделки"""
    currency = callback.data.split("_")[1]
    user_id = callback.from_user.id
    
    # Проверяем совместимость валюты с кошельками пользователя
    if not await user_has_compatible_wallet(user_id, currency):
        currency_name = CURRENCY_TYPES.get(currency, currency)
        
        # Определяем какие кошельки нужны
        required_wallets = {
            'rub': 'банковскую карту',
            'crypto': 'криптокошелёк (Bitcoin, USDT или TON)',
            'stars': 'любой кошелёк'
        }
        
        wallet_needed = required_wallets.get(currency, 'подходящий кошелёк')
        
        error_text = f"""
❌ **Кошелёк не найден**

Для создания сделки в валюте **{currency_name}** необходимо добавить {wallet_needed}.

Перейдите в раздел "Кошельки" и добавьте нужный тип кошелька.
"""
        
        await callback.message.edit_text(
            error_text,
            reply_markup=get_wallets_keyboard(has_wallets=False),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    await state.update_data(currency_type=currency)
    await state.set_state(DealStates.waiting_for_amount)
    
    currency_name = CURRENCY_TYPES.get(currency, currency)
    
    await callback.message.edit_text(
        CREATE_DEAL_ENTER_AMOUNT.format(currency=currency_name),
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(DealStates.waiting_for_amount)
async def process_deal_amount(message: Message, state: FSMContext):
    """Обработка суммы сделки"""
    amount_text = message.text
    
    # Проверяем корректность суммы
    is_valid, amount = is_valid_amount(amount_text)
    
    if not is_valid:
        await message.answer(
            ERROR_INVALID_AMOUNT,
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    await state.update_data(amount=amount)
    await state.set_state(DealStates.waiting_for_description)
    
    await message.answer(
        CREATE_DEAL_ENTER_DESCRIPTION,
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )

@router.message(DealStates.waiting_for_description)
async def process_deal_description(message: Message, state: FSMContext):
    """Обработка описания сделки"""
    description = message.text.strip()
    
    if len(description) < 3:
        await message.answer(
            "❌ Описание слишком короткое. Введите минимум 3 символа:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    if len(description) > 200:
        await message.answer(
            "❌ Описание слишком длинное. Максимум 200 символов:",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    # Получаем данные из состояния
    data = await state.get_data()
    currency_type = data['currency_type']
    amount = data['amount']
    
    # Генерируем уникальный код сделки
    deal_code = generate_deal_code()
    
    # Проверяем уникальность кода
    while await db.get_deal_by_code(deal_code):
        deal_code = generate_deal_code()
    
    # Создаём сделку
    user_id = message.from_user.id
    deal_id = await db.create_deal(
        seller_id=user_id,
        currency_type=currency_type,
        amount=amount,
        description=description,
        deal_code=deal_code
    )
    
    if deal_id:
        currency_name = CURRENCY_TYPES.get(currency_type, currency_type)
        formatted_amount = format_amount(amount, currency_type)
        
        success_text = DEAL_CREATED_MESSAGE.format(
            deal_code=deal_code,
            amount=formatted_amount,
            currency=currency_name,
            description=description
        )
        
        await message.answer(
            success_text,
            reply_markup=get_main_menu_keyboard(),
            parse_mode="Markdown"
        )
        
        await state.clear()
    else:
        await message.answer(
            "❌ Ошибка при создании сделки. Попробуйте позже.",
            reply_markup=get_cancel_keyboard()
        )

@router.callback_query(F.data == "join_deal")
async def start_join_deal(callback: CallbackQuery, state: FSMContext):
    """Начало присоединения к сделке"""
    user_id = callback.from_user.id
    
    # Проверяем доступ
    has_access, error_msg = await check_user_access(user_id)
    if not has_access:
        await callback.message.edit_text(error_msg)
        return
    
    # Проверяем, не является ли пользователь скамером
    if await db.is_scammer(user_id):
        scammer_info = await db.get_scammer_info(user_id)
        warning_text = f"""
🚫 **Доступ к участию в сделках ограничен**

Ваш аккаунт находится в списке ненадёжных пользователей.

**Причина:** {scammer_info['description'][:200]}{'...' if len(scammer_info['description']) > 200 else ''}

Если вы считаете это ошибкой, обратитесь в поддержку.
"""
        await callback.message.edit_text(
            warning_text,
            reply_markup=get_back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    # Проверяем, нет ли уже активной сделки
    active_deal = await db.get_user_active_deal(user_id)
    if active_deal:
        await callback.message.edit_text(
            ERROR_ALREADY_HAVE_DEAL,
            reply_markup=get_back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    await state.set_state(DealStates.waiting_for_deal_code)
    
    await callback.message.edit_text(
        JOIN_DEAL_MESSAGE,
        reply_markup=get_cancel_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(DealStates.waiting_for_deal_code)
async def process_deal_code(message: Message, state: FSMContext):
    """Обработка кода сделки для присоединения"""
    user_text = message.text.strip()
    user_id = message.from_user.id
    
    # Проверяем, показывалось ли предупреждение о скамере
    data = await state.get_data()
    if data.get('scammer_warning_shown'):
        if user_text == "СОГЛАСЕН":
            # Пользователь подтвердил участие в сделке со скамером
            deal_code = data['deal_code']
            
            # Логируем это действие для админа
            await db.log_action(
                'scammer_deal_join_confirmed', 
                user_id, 
                details=f'Присоединился к сделке скамера: {deal_code}'
            )
            
            await message.answer(
                "⚠️ Вы подтвердили участие в сделке с ненадёжным пользователем. Будьте крайне осторожны!",
                parse_mode="Markdown"
            )
            
            # Сбрасываем флаг предупреждения и продолжаем обычную логику
            await state.update_data(scammer_warning_shown=False)
        else:
            # Пользователь отказался от сделки со скамером
            await message.answer(
                "✅ Разумное решение! Сделка отменена для вашей безопасности.",
                reply_markup=get_back_to_main_keyboard(),
                parse_mode="Markdown"
            )
            await state.clear()
            return
    else:
        deal_code = user_text.upper()
    
    # Ищем сделку по коду
    deal = await db.get_deal_by_code(deal_code)
    
    if not deal:
        await message.answer(
            ERROR_DEAL_NOT_FOUND,
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    # Проверяем, что это не собственная сделка
    if deal['seller_id'] == user_id:
        await message.answer(
            ERROR_CANT_JOIN_OWN_DEAL,
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    # Проверяем статус сделки
    if deal['status'] not in ['waiting_buyer']:
        if deal['status'] == 'completed':
            await message.answer(
                "❌ **Сделка уже завершена**\n\nЭта сделка была успешно завершена и больше недоступна.",
                reply_markup=get_cancel_keyboard(),
                parse_mode="Markdown"
            )
        elif deal['status'] == 'cancelled':
            await message.answer(
                "❌ **Сделка отменена**\n\nЭта сделка была отменена и больше недоступна.",
                reply_markup=get_cancel_keyboard(),
                parse_mode="Markdown"
            )
        else:
            await message.answer(
                "❌ **Сделка недоступна**\n\nК этой сделке нельзя присоединиться.",
                reply_markup=get_cancel_keyboard(),
                parse_mode="Markdown"
            )
        return

    # Проверяем, что к сделке ещё не присоединился покупатель
    if deal['buyer_id'] is not None:
        await message.answer(
            ERROR_DEAL_ALREADY_HAS_BUYER,
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )
        return
    
    # Проверяем, не является ли продавец скамером
    if await db.is_scammer(deal['seller_id']):
        scammer_info = await db.get_scammer_info(deal['seller_id'])
        seller = await db.get_user(deal['seller_id'])
        seller_name = seller['first_name'] or seller['username'] or f"ID{deal['seller_id']}"
        
        warning_text = f"""
⚠️ **ВНИМАНИЕ! ВОЗМОЖНЫЙ СКАМЕР**

Продавец **{seller_name}** находится в списке ненадёжных пользователей!

**Причина блокировки:**
{scammer_info['description'][:300]}{'...' if len(scammer_info['description']) > 300 else ''}

🚫 **НЕ РЕКОМЕНДУЕТСЯ** участвовать в этой сделке!

Если вы уверены в своих действиях, напишите "СОГЛАСЕН" (заглавными буквами).
Для отмены введите любой другой текст.
"""
        
        await message.answer(
            warning_text,
            reply_markup=get_cancel_keyboard(),
            parse_mode="Markdown"
        )
        
        # Сохраняем данные для подтверждения
        await state.update_data(
            deal_code=deal_code,
            scammer_warning_shown=True
        )
        return
    
    # Присоединяемся к сделке
    success = await db.join_deal(deal_code, user_id)
    
    if success:
        # Получаем обновленную информацию о сделке
        updated_deal = await db.get_deal_by_code(deal_code)
        seller = await db.get_user(updated_deal['seller_id'])
        buyer = await db.get_user(user_id)
        
        # Добавляем системное сообщение о присоединении
        buyer_name = buyer['first_name'] or buyer['username'] or f"ID{user_id}"
        system_message = f"🔸 Покупатель {buyer_name} присоединился к сделке"
        await db.add_deal_message(updated_deal['id'], user_id, system_message, 'system')
        
        formatted_amount = format_amount(updated_deal['amount'], updated_deal['currency_type'])
        
        # Получаем рейтинг продавца для отображения
        seller_rating = seller.get('rating', 5.0)
        
        # Функция для форматирования рейтинга
        def format_rating(rating):
            stars = "⭐" * int(rating)
            if rating != int(rating):
                stars += "✨"  # Полузвезда для дробных рейтингов
            return f"{stars} ({rating:.1f})"
        
        # Сообщение для покупателя с рейтингом продавца
        buyer_text = DEAL_JOINED_MESSAGE.format(
            deal_code=deal_code,
            amount=formatted_amount,
            seller_name=seller['first_name'] or seller['username'] or 'Неизвестно',
            buyer_name=buyer['first_name'] or buyer['username'] or 'Неизвестно'
        )
        buyer_text += f"\n\n📊 **Рейтинг продавца:** {format_rating(seller_rating)}"
        
        # Сообщение для продавца (без рейтинга)
        seller_text = DEAL_JOINED_MESSAGE.format(
            deal_code=deal_code,
            amount=formatted_amount,
            seller_name=seller['first_name'] or seller['username'] or 'Неизвестно',
            buyer_name=buyer['first_name'] or buyer['username'] or 'Неизвестно'
        )
        
        # Отправляем сообщение покупателю
        await message.answer(
            buyer_text,
            reply_markup=get_deal_actions_keyboard_sync("waiting_guarantor", "buyer", updated_deal['id']),
            parse_mode="Markdown"
        )
        
        # Уведомляем продавца
        try:
            bot = message.bot
            await bot.send_message(
                chat_id=updated_deal['seller_id'],
                text=seller_text,
                reply_markup=get_deal_actions_keyboard_sync("waiting_guarantor", "seller", updated_deal['id']),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления продавца: {e}")
        
        await state.clear()
    else:
        await message.answer(
            "❌ Ошибка при присоединении к сделке. Попробуйте позже.",
            reply_markup=get_cancel_keyboard()
        )

@router.callback_query(F.data == "call_guarantor")
async def call_guarantor(callback: CallbackQuery):
    """Вызов гаранта для сделки"""
    user_id = callback.from_user.id
    
    # Получаем активную сделку пользователя
    deal = await db.get_user_active_deal(user_id)
    
    if not deal or deal['status'] != 'waiting_guarantor':
        await callback.answer("Сделка не найдена или недоступна", show_alert=True)
        return
    
    # Проверяем, что гарант еще не был вызван
    if deal.get('is_guarantor_called', False):
        await callback.answer("Гарант уже был вызван для этой сделки", show_alert=True)
        return
    
    # Отмечаем что гарант вызван
    await db.mark_guarantor_called(deal['id'])
    
    # Получаем всех гарантов
    guarantors = await db.get_all_users()
    guarantors = [g for g in guarantors if g.get('is_guarantor', False) and not g.get('is_banned', False)]
    
    if not guarantors:
        await callback.message.edit_text(
            "❌ В данный момент нет доступных гарантов. Попробуйте позже.",
            reply_markup=get_back_to_main_keyboard()
        )
        await callback.answer()
        return
    
    # Получаем информацию об участниках
    seller = await db.get_user(deal['seller_id'])
    buyer = await db.get_user(deal['buyer_id'])
    
    formatted_amount = format_amount(deal['amount'], deal['currency_type'])
    
    notification_text = GUARANTOR_NOTIFICATION.format(
        deal_id=deal['id'],
        deal_code=deal['deal_code'],
        amount=formatted_amount,
        seller_name=seller['first_name'] or seller['username'] or 'Неизвестно',
        buyer_name=buyer['first_name'] or buyer['username'] or 'Неизвестно',
        description=deal['description']
    )
    
    # Отправляем уведомления всем гарантам
    bot = callback.bot
    notified_count = 0
    
    for guarantor in guarantors:
        # Проверяем, не занят ли гарант другой сделкой
        guarantor_deal = await db.get_guarantor_active_deal(guarantor['user_id'])
        if guarantor_deal:
            continue
        
        try:
            await bot.send_message(
                chat_id=guarantor['user_id'],
                text=notification_text,
                reply_markup=get_guarantor_response_keyboard(deal['id']),
                parse_mode="Markdown"
            )
            notified_count += 1
        except Exception as e:
            logger.error(f"Ошибка уведомления гаранта {guarantor['user_id']}: {e}")
    
    if notified_count > 0:
        # Обновляем сообщение для участников сделки
        called_text = GUARANTOR_CALLED_MESSAGE.format(
            deal_id=deal['id'],
            deal_code=deal['deal_code'],
            amount=formatted_amount,
            seller_name=seller['first_name'] or seller['username'] or 'Неизвестно',
            buyer_name=buyer['first_name'] or buyer['username'] or 'Неизвестно'
        )
        
        await callback.message.edit_text(
            called_text,
            reply_markup=get_back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        
        # Уведомляем второго участника
        other_user_id = deal['buyer_id'] if user_id == deal['seller_id'] else deal['seller_id']
        try:
            await bot.send_message(
                chat_id=other_user_id,
                text=called_text,
                reply_markup=get_back_to_main_keyboard(),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления участника сделки: {e}")
        
        await callback.answer(f"Уведомлено гарантов: {notified_count}")
    else:
        # Убираем отметку если никого не уведомили
        await db.mark_guarantor_called(deal['id'], False)
        await callback.answer("Все гаранты заняты. Попробуйте позже.", show_alert=True)

@router.callback_query(F.data.startswith("accept_deal_"))
async def accept_deal_as_guarantor(callback: CallbackQuery):
    """Принятие сделки гарантом"""
    deal_id = int(callback.data.split("_")[-1])
    guarantor_id = callback.from_user.id
    
    # Проверяем, что пользователь является гарантом
    guarantor = await db.get_user(guarantor_id)
    if not guarantor or not guarantor.get('is_guarantor', False):
        await callback.answer("У вас нет прав гаранта", show_alert=True)
        return
    
    # Проверяем, не занят ли гарант другой сделкой
    active_deal = await db.get_guarantor_active_deal(guarantor_id)
    if active_deal:
        await callback.message.edit_text(
            ERROR_GUARANTOR_BUSY,
            reply_markup=get_back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    # Назначаем гаранта на сделку
    success = await db.assign_guarantor(deal_id, guarantor_id)
    
    if success:
        # Добавляем системное сообщение о назначении гаранта
        guarantor_name = guarantor['first_name'] or guarantor['username'] or f"ID{guarantor_id}"
        system_message = f"👨‍💼 Гарант {guarantor_name} принял сделку. Сделка началась!"
        await db.add_deal_message(deal_id, guarantor_id, system_message, 'system')
        # Получаем информацию о сделке
        deal = await db.get_deal_by_code("")  # Получаем по ID
        # Находим сделку по ID (нужно добавить метод в базу данных)
        all_deals = await db.get_all_deals()
        deal = next((d for d in all_deals if d['id'] == deal_id), None)
        
        if deal:
            seller = await db.get_user(deal['seller_id'])
            buyer = await db.get_user(deal['buyer_id'])
            
            # Получаем подходящий кошелёк продавца для валюты сделки
            if deal['currency_type'] == 'stars':
                # Для звёзд Telegram кошелёк не нужен - платежи через бота
                wallet_info = 'Платежи через бота (следуйте указаниям гаранта)'
            else:
                seller_wallets = await db.get_user_wallets(deal['seller_id'])
                if seller_wallets:
                    # Определяем совместимые типы кошельков для валюты сделки
                    compatible_wallets = {
                        'rub': ['card'],  # Рубли - банковская карта
                        'crypto': ['btc', 'usdt', 'ton'],  # Крипта - любой криптокошелёк
                    }
                    
                    required_wallet_types = compatible_wallets.get(deal['currency_type'], [])
                    
                    # Ищем подходящий кошелек
                    compatible_wallet = None
                    for wallet in seller_wallets:
                        if wallet['wallet_type'] in required_wallet_types:
                            compatible_wallet = wallet
                            break
                    
                    if compatible_wallet:
                        wallet_type_name = WALLET_TYPES.get(compatible_wallet['wallet_type'], compatible_wallet['wallet_type'])
                        wallet_address = compatible_wallet['wallet_address']
                        wallet_info = f"{wallet_type_name} - `{wallet_address}`"
                    else:
                        # Если не найден подходящий, берем первый и помечаем несоответствие
                        wallet = seller_wallets[0]
                        wallet_type_name = WALLET_TYPES.get(wallet['wallet_type'], wallet['wallet_type'])
                        wallet_address = wallet['wallet_address']
                        wallet_info = f"⚠️ {wallet_type_name} - `{wallet_address}` (может не подходить для {CURRENCY_TYPES.get(deal['currency_type'])})"
                else:
                    wallet_info = 'Не указан'
            
            formatted_amount = format_amount(deal['amount'], deal['currency_type'])
            
            progress_text = DEAL_IN_PROGRESS_MESSAGE.format(
                deal_code=deal['deal_code'],
                amount=formatted_amount,
                seller_name=seller['first_name'] or seller['username'] or 'Неизвестно',
                buyer_name=buyer['first_name'] or buyer['username'] or 'Неизвестно',
                guarantor_name=guarantor['first_name'] or guarantor['username'] or 'Неизвестно',
                wallet_info=wallet_info,
                commission=DEFAULT_COMMISSION
            )
            
            # Уведомляем гаранта
            await callback.message.edit_text(
                progress_text,
                reply_markup=get_deal_actions_keyboard_sync("in_progress", "guarantor", deal_id),
                parse_mode="Markdown"
            )
            
            # Уведомляем участников сделки
            bot = callback.bot
            for user_id in [deal['seller_id'], deal['buyer_id']]:
                user_role = "seller" if user_id == deal['seller_id'] else "buyer"
                try:
                    await bot.send_message(
                        chat_id=user_id,
                        text=progress_text,
                        reply_markup=get_deal_actions_keyboard_sync("in_progress", user_role, deal_id),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    logger.error(f"Ошибка уведомления участника сделки: {e}")
            
            await callback.answer("Сделка принята!")
        else:
            await callback.answer("Ошибка получения информации о сделке", show_alert=True)
    else:
        await callback.answer("Ошибка при принятии сделки", show_alert=True)

@router.callback_query(F.data.startswith("decline_deal_"))
async def decline_deal_as_guarantor(callback: CallbackQuery):
    """Отказ от сделки гарантом"""
    await callback.message.delete()
    await callback.answer("Вы отказались от сделки")

@router.callback_query(F.data == "complete_deal")
async def complete_deal(callback: CallbackQuery):
    """Завершение сделки гарантом"""
    guarantor_id = callback.from_user.id
    
    # Получаем активную сделку гаранта
    deal = await db.get_guarantor_active_deal(guarantor_id)
    
    if not deal:
        await callback.answer("У вас нет активных сделок", show_alert=True)
        return
    
    # Завершаем сделку
    success = await db.complete_deal(deal['id'], guarantor_id)
    
    if success:
        # Добавляем системное сообщение о завершении
        guarantor = await db.get_user(guarantor_id)
        guarantor_name = guarantor['first_name'] or guarantor['username'] or f"ID{guarantor_id}"
        system_message = f"✅ Гарант {guarantor_name} завершил сделку. Сделка успешно выполнена!"
        await db.add_deal_message(deal['id'], guarantor_id, system_message, 'system')
        # Уведомляем всех участников
        completion_text = DEAL_COMPLETED_MESSAGE
        
        await callback.message.edit_text(
            completion_text,
            reply_markup=get_back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        
        # Уведомляем участников сделки
        bot = callback.bot
        for user_id in [deal['seller_id'], deal['buyer_id']]:
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=completion_text,
                    reply_markup=get_rating_keyboard(),  # Кнопки для оценки
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления участника сделки: {e}")
        
        await callback.answer("Сделка успешно завершена!")
    else:
        await callback.answer("Ошибка при завершении сделки", show_alert=True)

@router.callback_query(F.data == "cancel_deal")
async def cancel_deal(callback: CallbackQuery):
    """Отмена сделки"""
    user_id = callback.from_user.id
    
    # Получаем активную сделку пользователя (как участника или гаранта)
    deal = await db.get_user_active_deal(user_id)
    if not deal:
        deal = await db.get_guarantor_active_deal(user_id)
    
    if not deal:
        await callback.answer("У вас нет активных сделок", show_alert=True)
        return
    
    # Отменяем сделку
    success = await db.cancel_deal(deal['id'], user_id)
    
    if success:
        # Добавляем системное сообщение об отмене
        user = await db.get_user(user_id)
        user_name = user['first_name'] or user['username'] or f"ID{user_id}"
        
        # Определяем роль отменившего
        if deal['seller_id'] == user_id:
            role = "Продавец"
        elif deal['buyer_id'] == user_id:
            role = "Покупатель"
        elif deal['guarantor_id'] == user_id:
            role = "Гарант"
        else:
            role = "Пользователь"
        
        system_message = f"❌ {role} {user_name} отменил сделку"
        await db.add_deal_message(deal['id'], user_id, system_message, 'system')
        await callback.message.edit_text(
            DEAL_CANCELLED_MESSAGE,
            reply_markup=get_back_to_main_keyboard(),
            parse_mode="Markdown"
        )
        
        # Уведомляем других участников
        bot = callback.bot
        users_to_notify = []
        
        if deal['seller_id'] and deal['seller_id'] != user_id:
            users_to_notify.append(deal['seller_id'])
        if deal['buyer_id'] and deal['buyer_id'] != user_id:
            users_to_notify.append(deal['buyer_id'])
        if deal['guarantor_id'] and deal['guarantor_id'] != user_id:
            users_to_notify.append(deal['guarantor_id'])
        
        for notify_user_id in users_to_notify:
            try:
                await bot.send_message(
                    chat_id=notify_user_id,
                    text=DEAL_CANCELLED_MESSAGE,
                    reply_markup=get_back_to_main_keyboard(),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления участника о отмене: {e}")
        
        await callback.answer("Сделка отменена")
    else:
        await callback.answer("Ошибка при отмене сделки", show_alert=True) 