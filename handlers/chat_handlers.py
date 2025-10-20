import logging
import aiohttp
from datetime import datetime
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import db
from utils.keyboards import get_back_to_main_keyboard
from utils.validators import format_amount

logger = logging.getLogger(__name__)
router = Router()

class ChatStates(StatesGroup):
    waiting_for_message = State()

@router.callback_query(F.data.startswith("deal_chat_"))
async def show_deal_chat(callback: CallbackQuery):
    """Показ чата сделки"""
    deal_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    
    # Проверяем, что пользователь участвует в сделке
    deal = await db.get_deal_by_id(deal_id)
    if not deal or user_id not in [deal.get('seller_id'), deal.get('buyer_id'), deal.get('guarantor_id')]:
        await callback.answer("У вас нет доступа к этому чату", show_alert=True)
        return
    
    # Отмечаем сообщения как прочитанные
    await db.mark_messages_as_read(deal_id, user_id)
    
    # Получаем последние сообщения (пагинация)
    page = 1  # По умолчанию первая страница
    messages_per_page = 15
    messages = await db.get_deal_messages(deal_id, limit=messages_per_page)
    
    # Получаем общее количество сообщений для пагинации
    import aiosqlite
    async with aiosqlite.connect(db.db_path) as database:
        async with database.execute(
            'SELECT COUNT(*) FROM deal_messages WHERE deal_id = ?', (deal_id,)
        ) as cursor:
            total_messages = (await cursor.fetchone())[0]
    
    # Формируем текст чата
    if not messages:
        chat_text = f"💬 **Чат сделки #{deal_id}**\n\n_Сообщений пока нет_\n\nНапишите что-нибудь для начала общения!"
    else:
        shown_count = len(messages)
        chat_text = f"💬 **Чат сделки #{deal_id}**\n"
        if total_messages > messages_per_page:
            chat_text += f"📝 Показано последних {shown_count} из {total_messages} сообщений\n\n"
        else:
            chat_text += f"📝 Всего сообщений: {total_messages}\n\n"
        
        for msg in messages[-messages_per_page:]:  # Последние сообщения
            # Определяем отправителя
            if msg['message_type'] == 'system':
                sender = "🤖 Система"
            else:
                name = msg['first_name'] or msg['username'] or f"ID{msg['user_id']}"
                if msg['user_id'] == deal['seller_id']:
                    sender = f"🔹 {name} (Продавец)"
                elif msg['user_id'] == deal['buyer_id']:
                    sender = f"🔸 {name} (Покупатель)"
                elif msg['user_id'] == deal['guarantor_id']:
                    sender = f"👨‍💼 {name} (Гарант)"
                else:
                    sender = f"❓ {name}"
            
            time_str = msg['created_at'][:16] if msg['created_at'] else ""
            message_text = msg['message_text'][:100] + "..." if len(msg['message_text']) > 100 else msg['message_text']
            
            chat_text += f"`{time_str}` {sender}:\n{message_text}\n\n"
    
    # Создаем клавиатуру
    buttons = []
    
    # Кнопка написания сообщения только для активных сделок
    if deal['status'] not in ['completed', 'cancelled']:
        buttons.append([InlineKeyboardButton(text="✍️ Написать сообщение", callback_data=f"write_message_{deal_id}")])
    else:
        # Показываем статус завершённого чата
        status_text = "завершён" if deal['status'] == 'completed' else "закрыт"
        chat_text += f"\n🔒 **Чат {status_text}** - новые сообщения недоступны.\n"
    
    buttons.append([InlineKeyboardButton(text="📋 Экспорт чата", callback_data=f"export_chat_{deal_id}")])
    
    # Добавляем навигацию если сообщений больше, чем помещается на странице
    if total_messages > messages_per_page:
        nav_buttons = []
        nav_buttons.append(InlineKeyboardButton(text="📜 Показать все", callback_data=f"chat_show_all_{deal_id}"))
        if total_messages > 50:  # Если очень много сообщений
            nav_buttons.append(InlineKeyboardButton(text="⬆️ Старые", callback_data=f"chat_older_{deal_id}"))
        buttons.append(nav_buttons)
    
    buttons.extend([
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"deal_chat_{deal_id}")],
        [InlineKeyboardButton(text="◀️ К сделке", callback_data="my_deals")]
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    try:
        await callback.message.edit_text(
            chat_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка редактирования сообщения чата: {e}")
        # Если не можем отредактировать, отправляем новое сообщение
        try:
            await callback.message.answer(
                chat_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
        except Exception as e2:
            logger.error(f"Ошибка отправки нового сообщения чата: {e2}")
            await callback.answer("❌ Ошибка отображения чата", show_alert=True)
            return
    
    await callback.answer()

@router.callback_query(F.data.startswith("write_message_"))
async def start_write_message(callback: CallbackQuery, state: FSMContext):
    """Начало написания сообщения"""
    deal_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    
    # Проверяем доступ
    deal = await db.get_deal_by_id(deal_id)
    if not deal or user_id not in [deal.get('seller_id'), deal.get('buyer_id'), deal.get('guarantor_id')]:
        await callback.answer("У вас нет доступа к этому чату", show_alert=True)
        return
    
    # Проверяем статус сделки - нельзя писать в завершённые чаты
    if deal['status'] in ['completed', 'cancelled']:
        status_text = "завершена" if deal['status'] == 'completed' else "отменена"
        await callback.answer(f"❌ Чат закрыт. Сделка {status_text}.", show_alert=True)
        return
    
    await state.set_state(ChatStates.waiting_for_message)
    await state.update_data(deal_id=deal_id)
    
    await callback.message.edit_text(
        f"✍️ **Написание сообщения в чат сделки #{deal_id}**\n\nВведите ваше сообщение:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"deal_chat_{deal_id}")]
        ]),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(ChatStates.waiting_for_message)
async def process_chat_message(message: Message, state: FSMContext):
    """Обработка сообщения для чата"""
    data = await state.get_data()
    deal_id = data.get('deal_id')
    user_id = message.from_user.id
    
    if not deal_id:
        await message.answer("Ошибка: сделка не найдена")
        await state.clear()
        return
    
    # Проверяем доступ снова
    deal = await db.get_deal_by_id(deal_id)
    if not deal or user_id not in [deal.get('seller_id'), deal.get('buyer_id'), deal.get('guarantor_id')]:
        await message.answer("У вас нет доступа к этому чату")
        await state.clear()
        return
    
    # Проверяем статус сделки - нельзя писать в завершённые чаты
    if deal['status'] in ['completed', 'cancelled']:
        status_text = "завершена" if deal['status'] == 'completed' else "отменена"
        await message.answer(f"❌ Чат закрыт. Сделка {status_text}.")
        await state.clear()
        return
    
    # Ограничиваем длину сообщения
    message_text = message.text[:1000] if message.text else "Пустое сообщение"
    
    # Сохраняем сообщение
    success = await db.add_deal_message(deal_id, user_id, message_text)
    
    if success:
        await message.answer("✅ Сообщение отправлено!")
        
        # Отправляем уведомления другим участникам
        await send_chat_notifications(deal, user_id, message_text, message.bot)
        
        # Возвращаемся к чату
        await state.clear()
        
        # Отправляем новое сообщение с обновленным чатом
        await send_updated_chat(message, deal_id)
    else:
        await message.answer("❌ Ошибка отправки сообщения")
        await state.clear()

async def send_updated_chat(message: Message, deal_id: int):
    """Отправка обновлённого чата после добавления сообщения"""
    user_id = message.from_user.id
    
    # Проверяем доступ
    deal = await db.get_deal_by_id(deal_id)
    if not deal:
        await message.answer("❌ Сделка не найдена")
        return
    
    # Проверяем доступ (участники сделки или админ)
    from config import OWNER_ID
    if user_id not in [deal.get('seller_id'), deal.get('buyer_id'), deal.get('guarantor_id')] and user_id != OWNER_ID:
        await message.answer("❌ У вас нет доступа к этому чату")
        return
    
    # Отмечаем сообщения как прочитанные
    await db.mark_messages_as_read(deal_id, user_id)
    
    # Получаем последние сообщения
    messages_per_page = 15
    messages = await db.get_deal_messages(deal_id, limit=messages_per_page)
    
    # Получаем общее количество сообщений
    import aiosqlite
    async with aiosqlite.connect(db.db_path) as database:
        async with database.execute(
            'SELECT COUNT(*) FROM deal_messages WHERE deal_id = ?', (deal_id,)
        ) as cursor:
            total_messages = (await cursor.fetchone())[0]
    
    # Формируем текст чата
    if not messages:
        chat_text = f"💬 **Чат сделки #{deal_id}**\n\n_Сообщений пока нет_"
    else:
        shown_count = len(messages)
        chat_text = f"💬 **Чат сделки #{deal_id}**\n"
        if total_messages > messages_per_page:
            chat_text += f"📝 Показано последних {shown_count} из {total_messages} сообщений\n\n"
        else:
            chat_text += f"📝 Всего сообщений: {total_messages}\n\n"
        
        for msg in messages[-messages_per_page:]:
            if msg['message_type'] == 'system':
                sender = "🤖 Система"
            else:
                name = msg['first_name'] or msg['username'] or f"ID{msg['user_id']}"
                if msg['user_id'] == deal['seller_id']:
                    sender = f"🔹 {name}"
                elif msg['user_id'] == deal['buyer_id']:
                    sender = f"🔸 {name}"
                elif msg['user_id'] == deal['guarantor_id']:
                    sender = f"👨‍💼 {name}"
                else:
                    sender = f"❓ {name}"
            
            time_str = msg['created_at'][:16] if msg['created_at'] else ""
            message_text = msg['message_text'][:150] + "..." if len(msg['message_text']) > 150 else msg['message_text']
            
            chat_text += f"`{time_str}` {sender}:\n{message_text}\n\n"
    
    # Создаем клавиатуру
    buttons = []
    
    # Кнопка написания сообщения только для активных сделок
    if deal['status'] not in ['completed', 'cancelled']:
        buttons.append([InlineKeyboardButton(text="✍️ Написать сообщение", callback_data=f"write_message_{deal_id}")])
    else:
        # Показываем статус завершённого чата
        status_text = "завершён" if deal['status'] == 'completed' else "закрыт"
        chat_text += f"\n🔒 **Чат {status_text}** - новые сообщения недоступны.\n"
    
    buttons.append([InlineKeyboardButton(text="📋 Экспорт чата", callback_data=f"export_chat_{deal_id}")])
    
    # Добавляем навигацию если сообщений больше, чем помещается на странице
    if total_messages > messages_per_page:
        nav_buttons = []
        nav_buttons.append(InlineKeyboardButton(text="📜 Показать все", callback_data=f"chat_show_all_{deal_id}"))
        if total_messages > 50:  # Если очень много сообщений
            nav_buttons.append(InlineKeyboardButton(text="⬆️ Старые", callback_data=f"chat_older_{deal_id}"))
        buttons.append(nav_buttons)
    
    buttons.extend([
        [InlineKeyboardButton(text="🔄 Обновить", callback_data=f"deal_chat_{deal_id}")],
        [InlineKeyboardButton(text="◀️ К сделке", callback_data="my_deals")]
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    # Отправляем новое сообщение
    try:
        await message.answer(
            chat_text,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Ошибка отправки обновленного чата: {e}")
        await message.answer("❌ Ошибка отображения чата")

async def send_chat_notifications(deal: dict, sender_id: int, message_text: str, bot):
    """Отправка уведомлений о новом сообщении"""
    participants = [deal['seller_id'], deal['buyer_id'], deal['guarantor_id']]
    
    # Получаем информацию об отправителе
    sender = await db.get_user(sender_id)
    sender_name = sender['first_name'] or sender['username'] or f"ID{sender_id}"
    
    # Определяем роль отправителя
    if sender_id == deal['seller_id']:
        role = "Продавец"
    elif sender_id == deal['buyer_id']:
        role = "Покупатель"
    elif sender_id == deal['guarantor_id']:
        role = "Гарант"
    else:
        role = "Неизвестный"
    
    # Сокращаем сообщение для уведомления
    short_message = message_text[:50] + "..." if len(message_text) > 50 else message_text
    
    notification_text = f"""
💬 **Новое сообщение в чате сделки #{deal['id']}**

**От:** {role} {sender_name}
**Сообщение:** {short_message}

Нажмите кнопку ниже для просмотра чата.
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Открыть чат", callback_data=f"deal_chat_{deal['id']}")]
    ])
    
    for participant_id in participants:
        if participant_id and participant_id != sender_id:
            try:
                await bot.send_message(
                    chat_id=participant_id,
                    text=notification_text,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления пользователю {participant_id}: {e}")

@router.callback_query(F.data.startswith("export_chat_"))
async def export_deal_chat(callback: CallbackQuery):
    """Экспорт чата сделки на pastebin"""
    deal_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    
    # Проверяем доступ
    deal = await db.get_deal_by_id(deal_id)
    if not deal:
        await callback.answer("Сделка не найдена", show_alert=True)
        return
    
    # Только участники и админы могут экспортировать чат
    if user_id not in [deal.get('seller_id'), deal.get('buyer_id'), deal.get('guarantor_id')]:
        # Проверяем, админ ли это
        from config import OWNER_ID
        if user_id != OWNER_ID:
            await callback.answer("У вас нет доступа к экспорту этого чата", show_alert=True)
            return
    
    await callback.answer("🔄 Подготавливаем экспорт...")
    
    # Получаем данные для экспорта
    export_data = await db.get_deal_chat_export_data(deal_id)
    
    if not export_data:
        await callback.message.edit_text(
            "❌ Ошибка при подготовке экспорта чата",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data=f"deal_chat_{deal_id}")]
            ])
        )
        return
    
    # Формируем текст для экспорта
    export_text = await format_chat_export(export_data)
    
    # Загружаем на pastebin
    pastebin_url = await upload_to_pastebin(export_text, f"Chat_Deal_{deal_id}")
    
    if pastebin_url:
        success_text = f"""
✅ **Чат экспортирован!**

**Сделка:** #{deal_id}
**Участники:** 
• Продавец: {export_data['deal']['seller_name'] or export_data['deal']['seller_username'] or 'ID' + str(export_data['deal']['seller_id'])}
• Покупатель: {export_data['deal']['buyer_name'] or export_data['deal']['buyer_username'] or 'ID' + str(export_data['deal']['buyer_id']) if export_data['deal']['buyer_id'] else 'Нет'}

**Ссылка на экспорт:** {pastebin_url}

⚠️ Ссылка действительна ограниченное время
"""
    else:
        success_text = "❌ Ошибка при загрузке на pastebin. Попробуйте позже."
    
    await callback.message.edit_text(
        success_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ К чату", callback_data=f"deal_chat_{deal_id}")]
        ]),
        parse_mode="Markdown"
    )

async def format_chat_export(export_data: dict) -> str:
    """Форматирование данных чата для экспорта"""
    deal = export_data['deal']
    messages = export_data['messages']
    
    # Статистика сообщений
    user_messages = [m for m in messages if m['message_type'] == 'user']
    system_messages = [m for m in messages if m['message_type'] == 'system']
    
    # Подсчёт сообщений по участникам
    participant_stats = {}
    for msg in user_messages:
        user_id = msg['user_id']
        if user_id not in participant_stats:
            participant_stats[user_id] = 0
        participant_stats[user_id] += 1
    
    # Заголовок с расширенной информацией
    export_text = f"""╔══════════════════════════════════════════════════════════════════════════════╗
║                            ЧАТ СДЕЛКИ #{deal['id']}                            ║
╚══════════════════════════════════════════════════════════════════════════════╝

📋 ИНФОРМАЦИЯ О СДЕЛКЕ:
    • Код сделки: {deal['deal_code']}
    • Сумма: {format_amount(deal['amount'], deal['currency_type'])}
    • Статус: {deal['status'].upper()}
    • Создана: {deal['created_at']}
    • Завершена: {deal['completed_at'] or 'Не завершена'}
    • Описание: {deal.get('description', 'Не указано')}

👥 УЧАСТНИКИ СДЕЛКИ:
    • Продавец: {deal['seller_name'] or deal['seller_username'] or 'Неизвестно'} (ID: {deal['seller_id']})
    • Покупатель: {deal['buyer_name'] or deal['buyer_username'] or 'Неизвестно' if deal['buyer_id'] else 'Нет'} {f"(ID: {deal['buyer_id']})" if deal['buyer_id'] else ''}
    • Гарант: {deal['guarantor_name'] or deal['guarantor_username'] or 'Неизвестно' if deal['guarantor_id'] else 'Нет'} {f"(ID: {deal['guarantor_id']})" if deal['guarantor_id'] else ''}

📊 СТАТИСТИКА ЧАТА:
    • Всего сообщений: {len(messages)}
    • Пользовательских: {len(user_messages)}
    • Системных: {len(system_messages)}
    • Участников писало: {len(participant_stats)}
"""

    # Статистика по участникам
    if participant_stats:
        export_text += "    • Сообщений по участникам:\n"
        for user_id, count in participant_stats.items():
            if user_id == deal['seller_id']:
                role = "Продавец"
                name = deal['seller_name'] or deal['seller_username'] or f"ID{user_id}"
            elif user_id == deal['buyer_id']:
                role = "Покупатель"
                name = deal['buyer_name'] or deal['buyer_username'] or f"ID{user_id}"
            elif user_id == deal['guarantor_id']:
                role = "Гарант"
                name = deal['guarantor_name'] or deal['guarantor_username'] or f"ID{user_id}"
            else:
                role = "Неизвестный"
                name = f"ID{user_id}"
            export_text += f"      - {role} {name}: {count} сообщений\n"

    export_text += "\n" + "="*80 + "\n"
    export_text += "                                  СООБЩЕНИЯ\n"
    export_text += "="*80 + "\n\n"
    
    # Сообщения
    if not messages:
        export_text += "📝 Сообщений в чате нет.\n"
    else:
        for i, msg in enumerate(messages, 1):
            # Определяем отправителя
            if msg['message_type'] == 'system':
                sender = "🤖 СИСТЕМА"
                sender_color = ""
            else:
                name = msg['first_name'] or msg['username'] or f"ID{msg['user_id']}"
                if msg['user_id'] == deal['seller_id']:
                    sender = f"🔹 {name} [ПРОДАВЕЦ]"
                elif msg['user_id'] == deal['buyer_id']:
                    sender = f"🔸 {name} [ПОКУПАТЕЛЬ]"
                elif msg['user_id'] == deal['guarantor_id']:
                    sender = f"👨‍💼 {name} [ГАРАНТ]"
                else:
                    sender = f"❓ {name} [НЕИЗВЕСТНЫЙ]"
            
            timestamp = msg['created_at'] or 'Неизвестно'
            message_text = msg['message_text']
            
            # Форматируем сообщение
            export_text += f"[{i:03d}] {timestamp}\n"
            export_text += f"     {sender}\n"
            export_text += f"     {'─' * 60}\n"
            
            # Разбиваем длинные сообщения на строки
            lines = []
            words = message_text.split(' ')
            current_line = ""
            
            for word in words:
                if len(current_line + word) <= 70:
                    current_line += word + " "
                else:
                    lines.append(current_line.strip())
                    current_line = word + " "
            if current_line:
                lines.append(current_line.strip())
            
            for line in lines:
                export_text += f"     {line}\n"
            
            export_text += "\n"
    
    # Футер
    export_text += "="*80 + "\n"
    export_text += f"Экспорт создан: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    export_text += f"Версия бота: Garant Bot v1.0\n"
    export_text += f"Общая длина чата: {len(export_text)} символов\n"
    export_text += "="*80 + "\n"
    
    return export_text

async def upload_to_pastebin(text: str, title: str) -> str:
    """Загрузка текста на pastebin"""
    try:
        url = "https://pastebin.com/api/api_post.php"
        data = {
            'api_dev_key': '',  # Вставьте свой API ключ Pastebin
            'api_option': 'paste',
            'api_paste_code': text,
            'api_paste_name': title,
            'api_paste_expire_date': '1W',  # Неделя
            'api_paste_private': '1',  # Unlisted
            'api_paste_format': 'text'
        }
        
        # Если нет ключа API, используем простую версию
        if not data['api_dev_key']:
            # Альтернативный сервис - dpaste.com
            alt_url = "https://dpaste.com/api/v2/"
            alt_data = {
                'content': text,
                'title': title,
                'syntax': 'text',
                'expiry_days': 7
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.post(alt_url, data=alt_data) as response:
                    if response.status == 201:
                        location = response.headers.get('Location')
                        if location:
                            return location + '.txt'  # Добавляем .txt для raw view
            
            return None
        
        # Если есть ключ API pastebin
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=data) as response:
                result = await response.text()
                if response.status == 200 and result.startswith('https://pastebin.com/'):
                    return result
                else:
                    logger.error(f"Ошибка pastebin: {result}")
                    return None
                    
    except Exception as e:
        logger.error(f"Ошибка загрузки на pastebin: {e}")
        return None

@router.callback_query(F.data.startswith("chat_show_all_"))
async def show_all_messages(callback: CallbackQuery):
    """Показ всех сообщений чата"""
    deal_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    
    # Проверяем доступ
    deal = await db.get_deal_by_id(deal_id)
    if not deal or user_id not in [deal.get('seller_id'), deal.get('buyer_id'), deal.get('guarantor_id')]:
        await callback.answer("У вас нет доступа к этому чату", show_alert=True)
        return
    
    # Получаем все сообщения
    messages = await db.get_deal_messages(deal_id, limit=1000)
    
    if not messages:
        await callback.answer("Сообщений нет")
        return
    
    # Формируем текст со всеми сообщениями
    chat_text = f"💬 **Полная история чата сделки #{deal_id}**\n"
    chat_text += f"📝 Всего сообщений: {len(messages)}\n\n"
    
    # Показываем первые 20 сообщений для предварительного просмотра
    for i, msg in enumerate(messages[:20], 1):
        if msg['message_type'] == 'system':
            sender = "🤖 Система"
        else:
            name = msg['first_name'] or msg['username'] or f"ID{msg['user_id']}"
            if msg['user_id'] == deal['seller_id']:
                sender = f"🔹 {name}"
            elif msg['user_id'] == deal['buyer_id']:
                sender = f"🔸 {name}"
            elif msg['user_id'] == deal['guarantor_id']:
                sender = f"👨‍💼 {name}"
            else:
                sender = f"❓ {name}"
        
        time_str = msg['created_at'][:16] if msg['created_at'] else ""
        message_text = msg['message_text'][:80] + "..." if len(msg['message_text']) > 80 else msg['message_text']
        
        chat_text += f"`{time_str}` {sender}:\n{message_text}\n\n"
        
        # Ограничиваем размер текста для Telegram
        if len(chat_text) > 3500:
            remaining = len(messages) - i
            chat_text += f"... и ещё {remaining} сообщений\n\n💡 Используйте экспорт для полной истории"
            break
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Экспорт полной истории", callback_data=f"export_chat_{deal_id}")],
        [InlineKeyboardButton(text="◀️ К чату", callback_data=f"deal_chat_{deal_id}")]
    ])
    
    await callback.message.edit_text(
        chat_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("chat_older_"))
async def show_older_messages(callback: CallbackQuery):
    """Показ старых сообщений"""
    deal_id = int(callback.data.split("_")[-1])
    user_id = callback.from_user.id
    
    # Проверяем доступ
    deal = await db.get_deal_by_id(deal_id)
    if not deal or user_id not in [deal.get('seller_id'), deal.get('buyer_id'), deal.get('guarantor_id')]:
        await callback.answer("У вас нет доступа к этому чату", show_alert=True)
        return
    
    # Получаем старые сообщения (исключаем последние 15)
    import aiosqlite
    async with aiosqlite.connect(db.db_path) as database:
        database.row_factory = aiosqlite.Row
        async with database.execute(
            '''SELECT dm.*, u.username, u.first_name 
               FROM deal_messages dm
               LEFT JOIN users u ON dm.user_id = u.user_id
               WHERE dm.deal_id = ?
               ORDER BY dm.created_at ASC
               LIMIT 20 OFFSET (
                   SELECT MAX(0, COUNT(*) - 35) 
                   FROM deal_messages 
                   WHERE deal_id = ?
               )''',
            (deal_id, deal_id)
        ) as cursor:
            older_messages = [dict(row) for row in await cursor.fetchall()]
    
    if not older_messages:
        await callback.answer("Старых сообщений нет")
        return
    
    chat_text = f"💬 **Старые сообщения сделки #{deal_id}**\n"
    chat_text += f"📝 Показано: {len(older_messages)} сообщений\n\n"
    
    for msg in older_messages:
        if msg['message_type'] == 'system':
            sender = "🤖 Система"
        else:
            name = msg['first_name'] or msg['username'] or f"ID{msg['user_id']}"
            if msg['user_id'] == deal['seller_id']:
                sender = f"🔹 {name}"
            elif msg['user_id'] == deal['buyer_id']:
                sender = f"🔸 {name}"
            elif msg['user_id'] == deal['guarantor_id']:
                sender = f"👨‍💼 {name}"
            else:
                sender = f"❓ {name}"
        
        time_str = msg['created_at'][:16] if msg['created_at'] else ""
        message_text = msg['message_text'][:100] + "..." if len(msg['message_text']) > 100 else msg['message_text']
        
        chat_text += f"`{time_str}` {sender}:\n{message_text}\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📜 Все сообщения", callback_data=f"chat_show_all_{deal_id}")],
        [InlineKeyboardButton(text="◀️ К чату", callback_data=f"deal_chat_{deal_id}")]
    ])
    
    await callback.message.edit_text(
        chat_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )
    await callback.answer() 