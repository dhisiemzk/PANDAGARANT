import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery

from database import db
from utils.messages import *
from utils.keyboards import *

logger = logging.getLogger(__name__)
router = Router()

@router.callback_query(F.data.startswith("rate_"))
async def process_rating(callback: CallbackQuery):
    """Обработка оценки пользователя"""
    rating = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    
    # Находим последнюю завершённую сделку пользователя
    deals = await db.get_all_deals()
    user_deals = [
        d for d in deals 
        if d['status'] == 'completed' 
        and (d['seller_id'] == user_id or d['buyer_id'] == user_id)
    ]
    
    if not user_deals:
        await callback.answer("Нет завершённых сделок для оценки", show_alert=True)
        return
    
    # Берём последнюю сделку
    last_deal = sorted(user_deals, key=lambda x: x['completed_at'])[-1]
    
    # Определяем, кого оценивать
    if last_deal['seller_id'] == user_id:
        # Продавец оценивает покупателя
        target_user_id = last_deal['buyer_id']
    else:
        # Покупатель оценивает продавца
        target_user_id = last_deal['seller_id']
    
    # Проверяем, не оценивал ли уже этого пользователя в этой сделке
    try:
        success = await db.add_rating(
            deal_id=last_deal['id'],
            from_user_id=user_id,
            to_user_id=target_user_id,
            rating=rating
        )
        
        if success:
            target_user = await db.get_user(target_user_id)
            partner_name = target_user['first_name'] or target_user['username'] or 'Пользователь'
            
            await callback.message.edit_text(
                RATING_ADDED_SUCCESS,
                reply_markup=get_back_to_main_keyboard(),
                parse_mode="Markdown"
            )
            await callback.answer(f"Вы поставили {rating} ⭐ пользователю {partner_name}")
        else:
            await callback.answer("Вы уже оценили этого пользователя в данной сделке", show_alert=True)
    
    except Exception as e:
        logger.error(f"Ошибка добавления оценки: {e}")
        await callback.answer("Ошибка при добавлении оценки", show_alert=True)

@router.callback_query(F.data == "my_ratings")
async def show_my_ratings(callback: CallbackQuery):
    """Показ оценок пользователя"""
    user_id = callback.from_user.id
    
    # Получаем оценки пользователя
    # Здесь нужно добавить метод в базу данных для получения оценок
    user = await db.get_user(user_id)
    
    if not user:
        await callback.answer("Ошибка получения данных", show_alert=True)
        return
    
    ratings_text = f"""
⭐ **Ваши оценки**

**Текущий рейтинг:** {user['rating']} ⭐
**Всего сделок:** {user['total_deals']}
**Завершено:** {user['completed_deals']}

Ваш рейтинг формируется на основе оценок партнёров по сделкам.
Для изменения рейтинга нужно минимум 3 оценки.
"""
    
    await callback.message.edit_text(
        ratings_text,
        reply_markup=get_back_to_main_keyboard(),
        parse_mode="Markdown"
    )
    await callback.answer() 