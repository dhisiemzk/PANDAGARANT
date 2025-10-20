import os
from dotenv import load_dotenv

load_dotenv()

# Основные настройки
BOT_TOKEN = os.getenv('BOT_TOKEN')
OWNER_ID = int(os.getenv('OWNER_ID', '8494369584'))  # ID владельца бота

# Настройки базы данных
DATABASE_PATH = 'bot_database.db'

# Настройки сделок
DEAL_CODE_LENGTH = 6
DEAL_TIMEOUT_MINUTES = 10  # Время для автоудаления неактивных сделок
DEFAULT_COMMISSION = 5.0  # Комиссия по умолчанию в процентах

# Текстовые константы
CURRENCY_TYPES = {
    'rub': '💰 Рубли',
    'crypto': '₿ Крипта', 
    'stars': '⭐ Звёзды'
}

WALLET_TYPES = {
    'card': '💳 Банковская карта',
    'btc': '₿ Bitcoin',
    'usdt': '💎 USDT',
    'ton': '💙 TON'
}

# Рейтинг по умолчанию
DEFAULT_RATING = 5.0 