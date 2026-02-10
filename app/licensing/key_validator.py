"""
Валидация и форматирование лицензионных ключей.
Формат ключа: XXXX-XXXX-XXXX-XXXX (16 символов + 3 дефиса)
"""

from __future__ import annotations

from typing import Optional
import hashlib
import secrets


# Alphabet without ambiguous characters (0, O, 1, I, L).
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _compute_checksum(body: str) -> str:
    """
    Compute a deterministic 4-character checksum for a 12-character body.

    This is not a security feature; it's meant to catch typos before sending
    the key to the server.
    """
    digest = hashlib.sha256(body.encode("utf-8")).digest()
    # Map 4 bytes -> 4 chars from the alphabet.
    return "".join(_ALPHABET[b % len(_ALPHABET)] for b in digest[:4])


def generate_license_key() -> str:
    """Generate a new license key in XXXX-XXXX-XXXX-XXXX format."""
    body = "".join(secrets.choice(_ALPHABET) for _ in range(12))
    checksum = _compute_checksum(body)
    raw = body + checksum
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}-{raw[12:16]}"


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
        Validate checksum of a license key (offline typo detection).

        The checksum is the last 4 characters; it's computed from the first 12.
        """
        normalized = KeyValidator.normalize_key(key).replace("-", "")
        if len(normalized) != 16:
            return False

        # Strict alphabet check (reject ambiguous characters).
        for ch in normalized:
            if ch not in _ALPHABET:
                return False

        body = normalized[:12]
        checksum = normalized[12:16]
        return checksum == _compute_checksum(body)

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
