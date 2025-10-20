import aiosqlite
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from config import DATABASE_PATH, DEFAULT_RATING

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.db_path = DATABASE_PATH
    
    async def init_db(self):
        """Инициализация базы данных и создание таблиц"""
        async with aiosqlite.connect(self.db_path) as db:
            # Таблица пользователей
            await db.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    rating REAL DEFAULT 5.0,
                    total_deals INTEGER DEFAULT 0,
                    completed_deals INTEGER DEFAULT 0,
                    is_banned BOOLEAN DEFAULT FALSE,
                    is_guarantor BOOLEAN DEFAULT FALSE,
                    balance_stars INTEGER DEFAULT 0,
                    balance_crypto REAL DEFAULT 0,
                    balance_rub REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица кошельков
            await db.execute('''
                CREATE TABLE IF NOT EXISTS wallets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    wallet_type TEXT NOT NULL,
                    wallet_address TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # Таблица сделок
            await db.execute('''
                CREATE TABLE IF NOT EXISTS deals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deal_code TEXT UNIQUE NOT NULL,
                    seller_id INTEGER NOT NULL,
                    buyer_id INTEGER,
                    guarantor_id INTEGER,
                    currency_type TEXT NOT NULL,
                    amount REAL NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT DEFAULT 'waiting_buyer',
                    commission REAL DEFAULT 5.0,
                    is_guarantor_called BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    FOREIGN KEY (seller_id) REFERENCES users (user_id),
                    FOREIGN KEY (buyer_id) REFERENCES users (user_id),
                    FOREIGN KEY (guarantor_id) REFERENCES users (user_id)
                )
            ''')
            
            # Таблица оценок
            await db.execute('''
                CREATE TABLE IF NOT EXISTS ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deal_id INTEGER NOT NULL,
                    from_user_id INTEGER NOT NULL,
                    to_user_id INTEGER NOT NULL,
                    rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
                    comment TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (deal_id) REFERENCES deals (id),
                    FOREIGN KEY (from_user_id) REFERENCES users (user_id),
                    FOREIGN KEY (to_user_id) REFERENCES users (user_id),
                    UNIQUE(deal_id, from_user_id, to_user_id)
                )
            ''')
            
            # Таблица логов
            await db.execute('''
                CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    action TEXT NOT NULL,
                    user_id INTEGER,
                    deal_id INTEGER,
                    details TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Таблица настроек
            await db.execute('''
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            ''')
            
            # Таблица скамеров
            await db.execute('''
                CREATE TABLE IF NOT EXISTS scammers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    description TEXT NOT NULL,
                    added_by INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (added_by) REFERENCES users (user_id)
                )
            ''')
            
            # Таблица сообщений в чате сделки
            await db.execute('''
                CREATE TABLE IF NOT EXISTS deal_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    deal_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    message_text TEXT NOT NULL,
                    message_type TEXT DEFAULT 'user',
                    is_read_by_partner BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (deal_id) REFERENCES deals (id),
                    FOREIGN KEY (user_id) REFERENCES users (user_id)
                )
            ''')
            
            # Миграция: добавляем новые поля балансов для существующих пользователей
            try:
                await db.execute('ALTER TABLE users ADD COLUMN balance_crypto REAL DEFAULT 0')
                await db.execute('ALTER TABLE users ADD COLUMN balance_rub REAL DEFAULT 0')
                await db.commit()
            except aiosqlite.OperationalError:
                # Поля уже существуют
                pass
            
            # Миграция: добавляем поле is_guarantor_called для существующих сделок
            try:
                await db.execute('ALTER TABLE deals ADD COLUMN is_guarantor_called BOOLEAN DEFAULT FALSE')
                await db.commit()
            except aiosqlite.OperationalError:
                # Поле уже существует
                pass
            
            await db.commit()
        
        logger.info("База данных инициализирована")
    
    async def log_action(self, action: str, user_id: int = None, deal_id: int = None, details: str = None):
        """Логирование действий"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'INSERT INTO logs (action, user_id, deal_id, details) VALUES (?, ?, ?, ?)',
                (action, user_id, deal_id, details)
            )
            await db.commit()
    
    # === ПОЛЬЗОВАТЕЛИ ===
    
    async def create_user(self, user_id: int, username: str = None, first_name: str = None) -> bool:
        """Создание нового пользователя"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    'INSERT INTO users (user_id, username, first_name) VALUES (?, ?, ?)',
                    (user_id, username, first_name)
                )
                await db.commit()
                await self.log_action('user_registered', user_id)
                return True
        except aiosqlite.IntegrityError:
            return False
    
    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получение информации о пользователе"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute('SELECT * FROM users WHERE user_id = ?', (user_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def update_user_rating(self, user_id: int, new_rating: float):
        """Обновление рейтинга пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET rating = ? WHERE user_id = ?',
                (new_rating, user_id)
            )
            await db.commit()
    
    async def ban_user(self, user_id: int, is_banned: bool = True):
        """Блокировка/разблокировка пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET is_banned = ? WHERE user_id = ?',
                (is_banned, user_id)
            )
            await db.commit()
            action = 'user_banned' if is_banned else 'user_unbanned'
            await self.log_action(action, user_id)
    
    async def set_guarantor(self, user_id: int, is_guarantor: bool = True):
        """Назначение/снятие гаранта"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'UPDATE users SET is_guarantor = ? WHERE user_id = ?',
                (is_guarantor, user_id)
            )
            await db.commit()
            action = 'guarantor_added' if is_guarantor else 'guarantor_removed'
            await self.log_action(action, user_id)
    
    async def update_user_balance(self, user_id: int, amount: int, currency: str = 'stars'):
        """Обновление баланса пользователя в указанной валюте"""
        if currency == 'stars':
            column = 'balance_stars'
        elif currency == 'crypto':
            column = 'balance_crypto'
        elif currency == 'rub':
            column = 'balance_rub'
        else:
            raise ValueError(f"Неподдерживаемая валюта: {currency}")
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                f'UPDATE users SET {column} = {column} + ? WHERE user_id = ?',
                (amount, user_id)
            )
            await db.commit()
            await self.log_action(
                'balance_updated', 
                user_id, 
                details=f'Изменение: {amount} {currency}'
            )
    
    # === КОШЕЛЬКИ ===
    
    async def add_wallet(self, user_id: int, wallet_type: str, wallet_address: str) -> bool:
        """Добавление кошелька"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    'INSERT INTO wallets (user_id, wallet_type, wallet_address) VALUES (?, ?, ?)',
                    (user_id, wallet_type, wallet_address)
                )
                await db.commit()
                await self.log_action('wallet_added', user_id, details=f'{wallet_type}: {wallet_address}')
                return True
        except Exception as e:
            logger.error(f"Ошибка добавления кошелька: {e}")
            return False
    
    async def get_user_wallets(self, user_id: int) -> List[Dict[str, Any]]:
        """Получение кошельков пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM wallets WHERE user_id = ? AND is_active = TRUE',
                (user_id,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]
    
    async def delete_wallet(self, wallet_id: int, user_id: int) -> bool:
        """Удаление кошелька"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'UPDATE wallets SET is_active = FALSE WHERE id = ? AND user_id = ?',
                (wallet_id, user_id)
            )
            await db.commit()
            if cursor.rowcount > 0:
                await self.log_action('wallet_deleted', user_id, details=f'Wallet ID: {wallet_id}')
                return True
            return False
    
    # === СДЕЛКИ ===
    
    async def create_deal(self, seller_id: int, currency_type: str, amount: float, 
                         description: str, deal_code: str) -> Optional[int]:
        """Создание новой сделки"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                cursor = await db.execute(
                    '''INSERT INTO deals (deal_code, seller_id, currency_type, amount, description) 
                       VALUES (?, ?, ?, ?, ?)''',
                    (deal_code, seller_id, currency_type, amount, description)
                )
                await db.commit()
                deal_id = cursor.lastrowid
                await self.log_action('deal_created', seller_id, deal_id, f'Код: {deal_code}')
                return deal_id
        except Exception as e:
            logger.error(f"Ошибка создания сделки: {e}")
            return None
    
    async def get_deal_by_code(self, deal_code: str) -> Optional[Dict[str, Any]]:
        """Получение сделки по коду"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute('SELECT * FROM deals WHERE deal_code = ?', (deal_code,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def get_deal_by_id(self, deal_id: int) -> Optional[Dict[str, Any]]:
        """Получение сделки по ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute('SELECT * FROM deals WHERE id = ?', (deal_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def join_deal(self, deal_code: str, buyer_id: int) -> bool:
        """Присоединение к сделке покупателя"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'UPDATE deals SET buyer_id = ?, status = "waiting_guarantor" WHERE deal_code = ? AND buyer_id IS NULL',
                (buyer_id, deal_code)
            )
            await db.commit()
            if cursor.rowcount > 0:
                await self.log_action('buyer_joined', buyer_id, details=f'Код: {deal_code}')
                return True
            return False
    
    async def assign_guarantor(self, deal_id: int, guarantor_id: int) -> bool:
        """Назначение гаранта на сделку"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'UPDATE deals SET guarantor_id = ?, status = "in_progress", started_at = CURRENT_TIMESTAMP WHERE id = ?',
                (guarantor_id, deal_id)
            )
            await db.commit()
            if cursor.rowcount > 0:
                await self.log_action('guarantor_assigned', guarantor_id, deal_id)
                return True
            return False
    
    async def mark_guarantor_called(self, deal_id: int, is_called: bool = True) -> bool:
        """Отметка что гарант был вызван для сделки"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'UPDATE deals SET is_guarantor_called = ? WHERE id = ?',
                (is_called, deal_id)
            )
            await db.commit()
            if cursor.rowcount > 0:
                action = 'guarantor_called' if is_called else 'guarantor_call_reset'
                await self.log_action(action, None, deal_id)
                return True
            return False
    
    async def complete_deal(self, deal_id: int, user_id: int = None) -> bool:
        """Завершение сделки (гарантом или администратором)"""
        async with aiosqlite.connect(self.db_path) as db:
            # Если указан user_id, проверяем что это гарант сделки или админ
            if user_id:
                # Получаем информацию о сделке
                async with db.execute('SELECT guarantor_id FROM deals WHERE id = ?', (deal_id,)) as cursor:
                    row = await cursor.fetchone()
                    if not row:
                        return False
                    guarantor_id = row[0]
                
                # Разрешаем завершение если это гарант сделки или админ (OWNER_ID)
                from config import OWNER_ID
                if user_id != guarantor_id and user_id != OWNER_ID:
                    return False
            
            cursor = await db.execute(
                '''UPDATE deals SET status = "completed", completed_at = CURRENT_TIMESTAMP 
                   WHERE id = ?''',
                (deal_id,)
            )
            await db.commit()
            if cursor.rowcount > 0:
                # Добавляем системное сообщение о завершении чата
                await self.add_deal_message(
                    deal_id, 
                    0,  # Системное сообщение
                    "🔒 Чат завершён. Сделка успешно выполнена!",
                    'system'
                )
                
                await self.log_action('deal_completed', user_id, deal_id)
                # Обновляем статистику участников
                await self._update_deal_stats(deal_id)
                return True
            return False
    
    async def cancel_deal(self, deal_id: int, user_id: int = None) -> bool:
        """Отмена сделки (пользователем или администратором)"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                'UPDATE deals SET status = "cancelled", is_guarantor_called = FALSE, completed_at = CURRENT_TIMESTAMP WHERE id = ?',
                (deal_id,)
            )
            await db.commit()
            if cursor.rowcount > 0:
                # Добавляем системное сообщение о завершении чата
                await self.add_deal_message(
                    deal_id, 
                    0,  # Системное сообщение
                    "🔒 Чат завершён. Сделка была отменена.",
                    'system'
                )
                
                action = 'deal_cancelled_admin' if user_id else 'deal_cancelled'
                await self.log_action(action, user_id, deal_id)
                return True
            return False
    
    async def _update_deal_stats(self, deal_id: int):
        """Обновление статистики пользователей после завершения сделки"""
        async with aiosqlite.connect(self.db_path) as db:
            # Получаем участников сделки
            async with db.execute(
                'SELECT seller_id, buyer_id FROM deals WHERE id = ?', (deal_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    seller_id, buyer_id = row
                    # Обновляем статистику
                    for user_id in [seller_id, buyer_id]:
                        if user_id:
                            await db.execute(
                                'UPDATE users SET total_deals = total_deals + 1, completed_deals = completed_deals + 1 WHERE user_id = ?',
                                (user_id,)
                            )
                    await db.commit()
    
    async def get_user_active_deal(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получение активной сделки пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                '''SELECT * FROM deals 
                   WHERE (seller_id = ? OR buyer_id = ?) 
                   AND status IN ("waiting_buyer", "waiting_guarantor", "in_progress")''',
                (user_id, user_id)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def get_guarantor_active_deal(self, guarantor_id: int) -> Optional[Dict[str, Any]]:
        """Получение активной сделки гаранта"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM deals WHERE guarantor_id = ? AND status = "in_progress"',
                (guarantor_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def get_pending_deals(self) -> List[Dict[str, Any]]:
        """Получение сделок, ожидающих гаранта"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM deals WHERE status = "waiting_guarantor"'
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]
    
    async def delete_expired_deals(self) -> int:
        """Удаление просроченных сделок"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                '''DELETE FROM deals 
                   WHERE status = "waiting_buyer" 
                   AND datetime(created_at, '+10 minutes') < datetime('now')'''
            )
            await db.commit()
            deleted_count = cursor.rowcount
            if deleted_count > 0:
                await self.log_action('expired_deals_deleted', details=f'Удалено: {deleted_count}')
            return deleted_count
    
    async def get_user_deals_history(self, user_id: int) -> List[Dict[str, Any]]:
        """Получение истории сделок пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                '''SELECT d.*, 
                          s.username as seller_username, s.first_name as seller_name,
                          b.username as buyer_username, b.first_name as buyer_name,
                          g.username as guarantor_username, g.first_name as guarantor_name
                   FROM deals d
                   LEFT JOIN users s ON d.seller_id = s.user_id
                   LEFT JOIN users b ON d.buyer_id = b.user_id  
                   LEFT JOIN users g ON d.guarantor_id = g.user_id
                   WHERE (d.seller_id = ? OR d.buyer_id = ? OR d.guarantor_id = ?)
                   ORDER BY d.created_at DESC''',
                (user_id, user_id, user_id)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    # === ОЦЕНКИ ===
    
    async def add_rating(self, deal_id: int, from_user_id: int, to_user_id: int, 
                        rating: int, comment: str = None) -> bool:
        """Добавление оценки"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    '''INSERT INTO ratings (deal_id, from_user_id, to_user_id, rating, comment) 
                       VALUES (?, ?, ?, ?, ?)''',
                    (deal_id, from_user_id, to_user_id, rating, comment)
                )
                await db.commit()
                await self._recalculate_user_rating(to_user_id)
                await self.log_action('rating_added', from_user_id, deal_id, f'Оценка: {rating}')
                return True
        except Exception as e:
            logger.error(f"Ошибка добавления оценки: {e}")
            return False
    
    async def _recalculate_user_rating(self, user_id: int):
        """Пересчёт рейтинга пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                'SELECT AVG(rating) as avg_rating, COUNT(*) as count FROM ratings WHERE to_user_id = ?',
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row and row[1] >= 3:  # Минимум 3 оценки
                    new_rating = round(row[0], 1)
                    await db.execute(
                        'UPDATE users SET rating = ? WHERE user_id = ?',
                        (new_rating, user_id)
                    )
                    await db.commit()
    
    # === СТАТИСТИКА И АДМИНКА ===
    
    async def get_all_deals(self) -> List[Dict[str, Any]]:
        """Получение всех сделок для админки"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                '''SELECT d.*, 
                          s.username as seller_username, s.first_name as seller_name,
                          b.username as buyer_username, b.first_name as buyer_name,
                          g.username as guarantor_username, g.first_name as guarantor_name
                   FROM deals d
                   LEFT JOIN users s ON d.seller_id = s.user_id
                   LEFT JOIN users b ON d.buyer_id = b.user_id  
                   LEFT JOIN users g ON d.guarantor_id = g.user_id
                   ORDER BY d.created_at DESC'''
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]
    
    async def get_stats(self) -> Dict[str, Any]:
        """Получение общей статистики"""
        async with aiosqlite.connect(self.db_path) as db:
            stats = {}
            
            # Пользователи
            async with db.execute('SELECT COUNT(*) FROM users') as cursor:
                stats['total_users'] = (await cursor.fetchone())[0]
            
            async with db.execute('SELECT COUNT(*) FROM users WHERE is_banned = TRUE') as cursor:
                stats['banned_users'] = (await cursor.fetchone())[0]
            
            async with db.execute('SELECT COUNT(*) FROM users WHERE is_guarantor = TRUE') as cursor:
                stats['guarantors'] = (await cursor.fetchone())[0]
            
            # Сделки
            async with db.execute('SELECT COUNT(*) FROM deals') as cursor:
                stats['total_deals'] = (await cursor.fetchone())[0]
            
            async with db.execute('SELECT COUNT(*) FROM deals WHERE status = "completed"') as cursor:
                stats['completed_deals'] = (await cursor.fetchone())[0]
            
            async with db.execute('SELECT COUNT(*) FROM deals WHERE status = "cancelled"') as cursor:
                stats['cancelled_deals'] = (await cursor.fetchone())[0]
            
            async with db.execute('SELECT COUNT(*) FROM deals WHERE status IN ("waiting_buyer", "waiting_guarantor", "in_progress")') as cursor:
                stats['active_deals'] = (await cursor.fetchone())[0]
            
            # Суммы
            async with db.execute('SELECT SUM(amount) FROM deals WHERE status = "completed"') as cursor:
                result = await cursor.fetchone()
                stats['total_volume'] = result[0] if result[0] else 0
            
            return stats
    
    async def get_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Получение логов для админки"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                'SELECT * FROM logs ORDER BY timestamp DESC LIMIT ?',
                (limit,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]
    
    async def get_all_users(self) -> List[Dict[str, Any]]:
        """Получение всех пользователей для админки"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute('SELECT * FROM users ORDER BY created_at DESC') as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    # === НАСТРОЙКИ ===
    
    async def get_setting(self, key: str, default_value: str = None) -> str:
        """Получение настройки"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute('SELECT value FROM settings WHERE key = ?', (key,)) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else default_value
    
    async def set_setting(self, key: str, value: str):
        """Установка настройки"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                'INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)',
                (key, value)
            )
            await db.commit()
            await self.log_action('setting_changed', details=f'{key}: {value}')
    
    async def is_maintenance_mode(self) -> bool:
        """Проверка режима технических работ"""
        value = await self.get_setting('maintenance_mode', 'false')
        return value.lower() == 'true'
    
    # === ЧАТЫ СДЕЛОК ===
    
    async def add_deal_message(self, deal_id: int, user_id: int, message_text: str, message_type: str = 'user') -> bool:
        """Добавление сообщения в чат сделки"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    '''INSERT INTO deal_messages (deal_id, user_id, message_text, message_type) 
                       VALUES (?, ?, ?, ?)''',
                    (deal_id, user_id, message_text, message_type)
                )
                await db.commit()
                await self.log_action('message_sent', user_id, deal_id, f'Type: {message_type}')
                return True
        except Exception as e:
            logger.error(f"Ошибка добавления сообщения: {e}")
            return False
    
    async def get_deal_messages(self, deal_id: int, limit: int = 50) -> List[Dict[str, Any]]:
        """Получение сообщений чата сделки"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                '''SELECT dm.*, u.username, u.first_name 
                   FROM deal_messages dm
                   LEFT JOIN users u ON dm.user_id = u.user_id
                   WHERE dm.deal_id = ?
                   ORDER BY dm.created_at ASC
                   LIMIT ?''',
                (deal_id, limit)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]
    
    async def get_unread_messages_count(self, deal_id: int, user_id: int) -> int:
        """Получение количества непрочитанных сообщений для пользователя"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                '''SELECT COUNT(*) FROM deal_messages 
                   WHERE deal_id = ? AND user_id != ? AND is_read_by_partner = FALSE''',
                (deal_id, user_id)
            ) as cursor:
                return (await cursor.fetchone())[0]
    
    async def mark_messages_as_read(self, deal_id: int, reader_user_id: int) -> bool:
        """Отметить сообщения как прочитанные"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    '''UPDATE deal_messages 
                       SET is_read_by_partner = TRUE 
                       WHERE deal_id = ? AND user_id != ? AND is_read_by_partner = FALSE''',
                    (deal_id, reader_user_id)
                )
                await db.commit()
                return True
        except Exception as e:
            logger.error(f"Ошибка обновления статуса сообщений: {e}")
            return False
    
    async def get_deal_chat_export_data(self, deal_id: int) -> Dict[str, Any]:
        """Подготовка данных для экспорта чата сделки"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            
            # Получаем информацию о сделке
            async with db.execute(
                '''SELECT d.*, 
                          s.username as seller_username, s.first_name as seller_name,
                          b.username as buyer_username, b.first_name as buyer_name,
                          g.username as guarantor_username, g.first_name as guarantor_name
                   FROM deals d
                   LEFT JOIN users s ON d.seller_id = s.user_id
                   LEFT JOIN users b ON d.buyer_id = b.user_id  
                   LEFT JOIN users g ON d.guarantor_id = g.user_id
                   WHERE d.id = ?''',
                (deal_id,)
            ) as cursor:
                deal = dict(await cursor.fetchone()) if cursor else None
            
            if not deal:
                return None
            
            # Получаем все сообщения
            messages = await self.get_deal_messages(deal_id, limit=1000)
            
            return {
                'deal': deal,
                'messages': messages
            }
    
    async def get_all_deal_chats_summary(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Получение сводки всех чатов сделок для админа"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                '''SELECT d.id, d.deal_code, d.status, d.created_at,
                          COUNT(dm.id) as message_count,
                          MAX(dm.created_at) as last_message_time,
                          s.username as seller_username, s.first_name as seller_name,
                          b.username as buyer_username, b.first_name as buyer_name
                   FROM deals d
                   LEFT JOIN deal_messages dm ON d.id = dm.deal_id
                   LEFT JOIN users s ON d.seller_id = s.user_id
                   LEFT JOIN users b ON d.buyer_id = b.user_id
                   GROUP BY d.id
                   HAVING COUNT(dm.id) > 0
                   ORDER BY MAX(dm.created_at) DESC
                   LIMIT ?''',
                (limit,)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]
    
    async def search_deal_messages(self, search_term: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Поиск сообщений в чатах сделок"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                '''SELECT dm.*, d.deal_code, d.status as deal_status,
                          u.username, u.first_name
                   FROM deal_messages dm
                   LEFT JOIN deals d ON dm.deal_id = d.id
                   LEFT JOIN users u ON dm.user_id = u.user_id
                   WHERE dm.message_text LIKE ?
                   ORDER BY dm.created_at DESC
                   LIMIT ?''',
                (f'%{search_term}%', limit)
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]
    
    async def get_deal_chat_stats(self) -> Dict[str, Any]:
        """Статистика чатов сделок"""
        async with aiosqlite.connect(self.db_path) as db:
            stats = {}
            
            # Общее количество сообщений
            async with db.execute('SELECT COUNT(*) FROM deal_messages') as cursor:
                stats['total_messages'] = (await cursor.fetchone())[0]
            
            # Количество активных чатов (с сообщениями)
            async with db.execute(
                'SELECT COUNT(DISTINCT deal_id) FROM deal_messages'
            ) as cursor:
                stats['active_chats'] = (await cursor.fetchone())[0]
            
            # Среднее количество сообщений на чат
            async with db.execute(
                '''SELECT AVG(message_count) FROM (
                    SELECT COUNT(*) as message_count 
                    FROM deal_messages 
                    GROUP BY deal_id
                )'''
            ) as cursor:
                result = await cursor.fetchone()
                stats['avg_messages_per_chat'] = round(result[0], 2) if result[0] else 0
            
            # Количество системных сообщений
            async with db.execute(
                'SELECT COUNT(*) FROM deal_messages WHERE message_type = ?', 
                ('system',)
            ) as cursor:
                stats['system_messages'] = (await cursor.fetchone())[0]
            
            return stats

    # === СКАМЕРЫ ===
    
    async def add_scammer(self, user_id: int, description: str, added_by: int) -> bool:
        """Добавление пользователя в список скамеров"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Получаем информацию о пользователе
                user = await self.get_user(user_id)
                username = user.get('username') if user else None
                first_name = user.get('first_name') if user else None
                
                await db.execute(
                    '''INSERT OR REPLACE INTO scammers (user_id, username, first_name, description, added_by) 
                       VALUES (?, ?, ?, ?, ?)''',
                    (user_id, username, first_name, description, added_by)
                )
                await db.commit()
                await self.log_action('scammer_added', added_by, details=f'User ID: {user_id}')
                return True
        except Exception as e:
            logger.error(f"Ошибка добавления скамера: {e}")
            return False
    
    async def remove_scammer(self, user_id: int, removed_by: int) -> bool:
        """Удаление пользователя из списка скамеров"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute('DELETE FROM scammers WHERE user_id = ?', (user_id,))
            await db.commit()
            if cursor.rowcount > 0:
                await self.log_action('scammer_removed', removed_by, details=f'User ID: {user_id}')
                return True
            return False
    
    async def is_scammer(self, user_id: int) -> bool:
        """Проверка, является ли пользователь скамером"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute('SELECT 1 FROM scammers WHERE user_id = ?', (user_id,)) as cursor:
                return await cursor.fetchone() is not None
    
    async def get_scammer_info(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получение информации о скамере"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute('SELECT * FROM scammers WHERE user_id = ?', (user_id,)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
    
    async def get_all_scammers(self) -> List[Dict[str, Any]]:
        """Получение списка всех скамеров"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                '''SELECT s.*, u.username as added_by_username, u.first_name as added_by_name
                   FROM scammers s
                   LEFT JOIN users u ON s.added_by = u.user_id
                   ORDER BY s.created_at DESC'''
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

# Глобальный экземпляр базы данных
db = Database() 