import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from config import BOT_TOKEN
from database import db
from handlers import main_handlers, wallet_handlers, deal_handlers, rating_handlers, admin_handlers, chat_handlers

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

async def set_bot_commands(bot: Bot):
    """Установка меню команд бота"""
    commands = [
        BotCommand(command="start", description="🏠 Главное меню")
    ]
    
    # Очищаем все команды и устанавливаем только нужные
    await bot.delete_my_commands()
    await bot.set_my_commands(commands)
    logger.info("Меню команд установлено")

async def main():
    """Основная функция запуска бота"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN не найден в переменных окружения!")
        return
    
    # Инициализация бота и диспетчера
    bot = Bot(
        token="8332247846:AAG-uK60fMlLIjDLioqS-pdsm8EQMDgEcsg",
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN)
    )
    
    dp = Dispatcher()
    
    # Подключение роутеров
    dp.include_router(main_handlers.router)
    dp.include_router(wallet_handlers.router)
    dp.include_router(deal_handlers.router)
    dp.include_router(rating_handlers.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(chat_handlers.router)
    
    try:
        # Инициализация базы данных
        logger.info("Инициализация базы данных...")
        await db.init_db()
        
        # Установка меню команд
        await set_bot_commands(bot)
        
        logger.info("Запуск бота...")
        
        # Запуск задачи очистки просроченных сделок
        cleanup_task = asyncio.create_task(main_handlers.auto_cleanup_deals())
        
        # Запуск бота
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"Ошибка запуска бота: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}") 