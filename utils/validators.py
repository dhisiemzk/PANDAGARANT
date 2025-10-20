import re
from typing import Tuple

def validate_card_number(card: str) -> Tuple[bool, str]:
    """Валидация номера банковской карты"""
    # Удаляем пробелы и дефисы
    card = re.sub(r'[\s\-]', '', card)
    
    if not card.isdigit():
        return False, "❌ Номер карты должен содержать только цифры"
    
    if len(card) != 16:
        return False, "❌ Номер карты должен содержать ровно 16 цифр"
    
    return True, "✅ Корректный номер карты"

def validate_btc_address(address: str) -> Tuple[bool, str]:
    """Валидация Bitcoin адреса"""
    address = address.strip()
    
    if not address:
        return False, "❌ Адрес не может быть пустым"
    
    # Legacy addresses (1...)
    if address.startswith('1'):
        if len(address) in [26, 35] and re.match(r'^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$', address):
            return True, "✅ Корректный BTC адрес (Legacy)"
    
    # SegWit addresses (3...)
    elif address.startswith('3'):
        if len(address) in [26, 35] and re.match(r'^[13][a-km-zA-HJ-NP-Z1-9]{25,34}$', address):
            return True, "✅ Корректный BTC адрес (SegWit)"
    
    # Bech32 addresses (bc1...)
    elif address.startswith('bc1'):
        if len(address) in [42, 62] and re.match(r'^bc1[a-z0-9]{39,59}$', address):
            return True, "✅ Корректный BTC адрес (Bech32)"
    
    return False, "❌ Некорректный Bitcoin адрес"

def validate_usdt_address(address: str) -> Tuple[bool, str]:
    """Валидация USDT адреса (Ethereum или TRON)"""
    address = address.strip()
    
    if not address:
        return False, "❌ Адрес не может быть пустым"
    
    # Ethereum адрес (0x...)
    if address.startswith('0x'):
        if len(address) == 42 and re.match(r'^0x[a-fA-F0-9]{40}$', address):
            return True, "✅ Корректный USDT адрес (Ethereum)"
    
    # TRON адрес (T...)
    elif address.startswith('T'):
        if len(address) == 34 and re.match(r'^T[A-Za-z1-9]{33}$', address):
            return True, "✅ Корректный USDT адрес (TRON)"
    
    return False, "❌ Некорректный USDT адрес"

def validate_ton_address(address: str) -> Tuple[bool, str]:
    """Валидация TON адреса"""
    address = address.strip()
    
    if not address:
        return False, "❌ Адрес не может быть пустым"
    
    # TON addresses are typically 48 characters long and contain letters, numbers, and some symbols
    if len(address) == 48 and re.match(r'^[A-Za-z0-9_-]{48}$', address):
        return True, "✅ Корректный TON адрес"
    
    # User-friendly format (EQ...)
    elif address.startswith('EQ') and len(address) == 48:
        if re.match(r'^EQ[A-Za-z0-9_-]{46}$', address):
            return True, "✅ Корректный TON адрес"
    
    return False, "❌ Некорректный TON адрес"

def validate_wallet(wallet_type: str, address: str) -> Tuple[bool, str]:
    """Универсальная валидация кошелька по типу"""
    validators = {
        'card': validate_card_number,
        'btc': validate_btc_address,
        'usdt': validate_usdt_address,
        'ton': validate_ton_address
    }
    
    if wallet_type not in validators:
        return False, "❌ Неизвестный тип кошелька"
    
    return validators[wallet_type](address)

def format_amount(amount: float, currency_type: str) -> str:
    """Форматирование суммы с валютой"""
    if currency_type == 'rub':
        return f"{amount:,.2f} ₽"
    elif currency_type == 'crypto':
        return f"{amount} crypto"
    elif currency_type == 'stars':
        return f"{int(amount)} ⭐"
    return str(amount)

def generate_deal_code() -> str:
    """Генерация кода сделки"""
    import random
    import string
    from config import DEAL_CODE_LENGTH
    
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=DEAL_CODE_LENGTH))

def is_valid_amount(amount_str: str) -> Tuple[bool, float]:
    """Проверка корректности суммы"""
    try:
        amount = float(amount_str.replace(',', '.'))
        if amount <= 0:
            return False, 0
        if amount > 1000000:  # Максимальная сумма
            return False, 0
        return True, amount
    except (ValueError, TypeError):
        return False, 0 