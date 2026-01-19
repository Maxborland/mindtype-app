"""
Валидация и форматирование лицензионных ключей.
Формат ключа: XXXX-XXXX-XXXX-XXXX (16 символов + 3 дефиса)
"""

from typing import Optional


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
