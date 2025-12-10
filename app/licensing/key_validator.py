"""
Валидация и генерация лицензионных ключей.
Формат ключа: XXXX-XXXX-XXXX-XXXX (16 символов + 3 дефиса)
Последние 4 символа - контрольная сумма.
"""

import hashlib
import secrets
import string
from typing import Optional


# Секретный ключ для генерации (НЕ МЕНЯТЬ после выпуска!)
_SECRET_SALT = "MindType2024SecretKey"

# Алфавит для ключей (без похожих символов: 0/O, 1/I/L)
_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def _compute_checksum(key_body: str) -> str:
    """Вычислить контрольную сумму для тела ключа."""
    data = f"{_SECRET_SALT}{key_body}".encode("utf-8")
    hash_hex = hashlib.sha256(data).hexdigest()

    # Преобразуем часть хеша в символы из алфавита
    checksum = ""
    for i in range(4):
        idx = int(hash_hex[i * 2 : i * 2 + 2], 16) % len(_ALPHABET)
        checksum += _ALPHABET[idx]

    return checksum


def generate_license_key() -> str:
    """
    Сгенерировать новый лицензионный ключ.

    Returns:
        Ключ в формате XXXX-XXXX-XXXX-XXXX
    """
    # Генерируем 12 случайных символов (3 группы по 4)
    body_chars = "".join(secrets.choice(_ALPHABET) for _ in range(12))

    # Вычисляем контрольную сумму
    checksum = _compute_checksum(body_chars)

    # Форматируем ключ
    full_key = body_chars + checksum
    return f"{full_key[0:4]}-{full_key[4:8]}-{full_key[8:12]}-{full_key[12:16]}"


class KeyValidator:
    """Валидатор лицензионных ключей."""

    @staticmethod
    def normalize_key(key: str) -> str:
        """Нормализовать ключ (убрать пробелы, привести к верхнему регистру)."""
        return key.strip().upper().replace(" ", "")

    @staticmethod
    def format_key(key: str) -> str:
        """Отформатировать ключ с дефисами."""
        normalized = KeyValidator.normalize_key(key).replace("-", "")
        if len(normalized) != 16:
            return key
        return f"{normalized[0:4]}-{normalized[4:8]}-{normalized[8:12]}-{normalized[12:16]}"

    @staticmethod
    def validate(key: str) -> bool:
        """
        Проверить формат лицензионного ключа.
        Проверяет только формат - реальную валидацию делает сервер.

        Args:
            key: Ключ для проверки (с дефисами или без)

        Returns:
            True если формат ключа корректен
        """
        # Нормализуем
        normalized = KeyValidator.normalize_key(key).replace("-", "")

        # Проверяем длину (16 символов)
        if len(normalized) != 16:
            return False

        # Проверяем что все символы - буквы или цифры
        for char in normalized:
            if not char.isalnum():
                return False

        return True

    @staticmethod
    def validate_checksum(key: str) -> bool:
        """
        Полная проверка ключа с контрольной суммой.
        Используется для локально сгенерированных ключей.

        Args:
            key: Ключ для проверки

        Returns:
            True если ключ валиден (формат + контрольная сумма)
        """
        # Нормализуем
        normalized = KeyValidator.normalize_key(key).replace("-", "")

        # Проверяем длину
        if len(normalized) != 16:
            return False

        # Проверяем символы из алфавита
        for char in normalized:
            if char not in _ALPHABET:
                return False

        # Разделяем на тело и контрольную сумму
        body = normalized[:12]
        provided_checksum = normalized[12:16]

        # Вычисляем ожидаемую контрольную сумму
        expected_checksum = _compute_checksum(body)

        return provided_checksum == expected_checksum

    @staticmethod
    def get_key_info(key: str) -> Optional[dict]:
        """
        Получить информацию о ключе.

        Returns:
            dict с информацией или None если ключ невалиден
        """
        if not KeyValidator.validate(key):
            return None

        normalized = KeyValidator.normalize_key(key).replace("-", "")

        return {
            "key": KeyValidator.format_key(key),
            "body": normalized[:12],
            "checksum": normalized[12:16],
            "valid": True,
        }


# Для тестирования
if __name__ == "__main__":
    # Генерируем несколько ключей
    print("Генерация тестовых ключей:")
    for i in range(5):
        key = generate_license_key()
        format_ok = KeyValidator.validate(key)
        checksum_ok = KeyValidator.validate_checksum(key)
        print(f"  {key} - Format: {'✓' if format_ok else '✗'}, Checksum: {'✓' if checksum_ok else '✗'}")

    # Тест формата
    print("\nТест формата ключей:")
    test_keys = [
        "AAAA-BBBB-CCCC-DDDD",  # Формат ОК, но контрольная сумма не совпадёт
        "1234-5678-9012-3456",  # Формат ОК
        "2X26-C72M-QAPM-44G7",  # Серверный ключ - формат ОК
        "SHORT",  # Слишком короткий
        "",  # Пустой
    ]
    for key in test_keys:
        format_ok = KeyValidator.validate(key)
        print(f"  {key or '(empty)'} - Format: {'✓ OK' if format_ok else '✗ Invalid'}")



