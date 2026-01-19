"""
Тесты для модуля валидации лицензионных ключей.
"""

import pytest
from app.licensing.key_validator import (
    KeyValidator,
    generate_license_key,
    _compute_checksum,
    _ALPHABET,
)


class TestKeyValidatorValidate:
    """Тесты для метода validate()."""

    def test_validate_correct_format_with_dashes(self):
        """Тест валидации ключа с дефисами."""
        assert KeyValidator.validate("ABCD-EFGH-JKMN-PQRS") is True

    def test_validate_correct_format_without_dashes(self):
        """Тест валидации ключа без дефисов."""
        assert KeyValidator.validate("ABCDEFGHJKMNPQRS") is True

    def test_validate_lowercase_key(self):
        """Тест валидации ключа в нижнем регистре."""
        assert KeyValidator.validate("abcd-efgh-jkmn-pqrs") is True

    def test_validate_mixed_case_key(self):
        """Тест валидации ключа со смешанным регистром."""
        assert KeyValidator.validate("AbCd-EfGh-JkMn-PqRs") is True

    def test_validate_with_spaces(self):
        """Тест валидации ключа с пробелами."""
        assert KeyValidator.validate("  ABCD-EFGH-JKMN-PQRS  ") is True

    def test_validate_numeric_key(self):
        """Тест валидации ключа с цифрами."""
        assert KeyValidator.validate("1234-5678-9012-3456") is True

    def test_validate_alphanumeric_key(self):
        """Тест валидации алфавитно-цифрового ключа."""
        assert KeyValidator.validate("2X26-C72M-QAPM-44G7") is True

    def test_validate_too_short(self):
        """Тест отклонения слишком короткого ключа."""
        assert KeyValidator.validate("SHORT") is False

    def test_validate_too_long(self):
        """Тест отклонения слишком длинного ключа."""
        assert KeyValidator.validate("ABCD-EFGH-JKMN-PQRS-EXTRA") is False

    def test_validate_empty_string(self):
        """Тест отклонения пустой строки."""
        assert KeyValidator.validate("") is False

    def test_validate_special_characters(self):
        """Тест отклонения ключа со спецсимволами."""
        assert KeyValidator.validate("ABC@-EFGH-JKMN-PQRS") is False

    def test_validate_15_characters(self):
        """Тест отклонения ключа с 15 символами."""
        assert KeyValidator.validate("ABCDEFGHJKMNPQR") is False

    def test_validate_17_characters(self):
        """Тест отклонения ключа с 17 символами."""
        assert KeyValidator.validate("ABCDEFGHJKMNPQRST") is False


class TestKeyValidatorNormalize:
    """Тесты для метода normalize_key()."""

    def test_normalize_uppercase(self):
        """Тест приведения к верхнему регистру."""
        result = KeyValidator.normalize_key("abcd-efgh-jkmn-pqrs")
        assert result == "ABCD-EFGH-JKMN-PQRS"

    def test_normalize_trim_spaces(self):
        """Тест удаления пробелов по краям."""
        result = KeyValidator.normalize_key("  ABCD-EFGH  ")
        assert result == "ABCD-EFGH"

    def test_normalize_remove_spaces(self):
        """Тест удаления пробелов внутри."""
        result = KeyValidator.normalize_key("ABCD EFGH JKMN PQRS")
        assert result == "ABCDEFGHJKMNPQRS"


class TestKeyValidatorFormat:
    """Тесты для метода format_key()."""

    def test_format_without_dashes(self):
        """Тест форматирования ключа без дефисов."""
        result = KeyValidator.format_key("ABCDEFGHJKMNPQRS")
        assert result == "ABCD-EFGH-JKMN-PQRS"

    def test_format_already_formatted(self):
        """Тест форматирования уже отформатированного ключа."""
        result = KeyValidator.format_key("ABCD-EFGH-JKMN-PQRS")
        assert result == "ABCD-EFGH-JKMN-PQRS"

    def test_format_lowercase(self):
        """Тест форматирования ключа в нижнем регистре."""
        result = KeyValidator.format_key("abcdefghjkmnpqrs")
        assert result == "ABCD-EFGH-JKMN-PQRS"

    def test_format_invalid_length_returns_original(self):
        """Тест возврата оригинала при неверной длине."""
        result = KeyValidator.format_key("SHORT")
        assert result == "SHORT"


class TestKeyValidatorChecksum:
    """Тесты для метода validate_checksum()."""

    def test_validate_checksum_generated_key(self):
        """Тест валидации контрольной суммы сгенерированного ключа."""
        key = generate_license_key()
        assert KeyValidator.validate_checksum(key) is True

    def test_validate_checksum_invalid_checksum(self):
        """Тест отклонения ключа с неверной контрольной суммой."""
        # Формат правильный, но контрольная сумма не совпадает
        assert KeyValidator.validate_checksum("AAAA-BBBB-CCCC-DDDD") is False

    def test_validate_checksum_too_short(self):
        """Тест отклонения слишком короткого ключа."""
        assert KeyValidator.validate_checksum("ABCD") is False

    def test_validate_checksum_invalid_characters(self):
        """Тест отклонения ключа с символами вне алфавита."""
        # '0', 'O', 'I', 'L', '1' не входят в алфавит
        assert KeyValidator.validate_checksum("0000-1111-OOOO-LLLL") is False


class TestKeyValidatorGetInfo:
    """Тесты для метода get_key_info()."""

    def test_get_key_info_valid_key(self):
        """Тест получения информации о валидном ключе."""
        info = KeyValidator.get_key_info("ABCD-EFGH-JKMN-PQRS")
        assert info is not None
        assert info["key"] == "ABCD-EFGH-JKMN-PQRS"
        assert info["body"] == "ABCDEFGHJKMN"
        assert info["checksum"] == "PQRS"
        assert info["valid"] is True

    def test_get_key_info_invalid_key(self):
        """Тест получения информации о невалидном ключе."""
        info = KeyValidator.get_key_info("SHORT")
        assert info is None


class TestGenerateLicenseKey:
    """Тесты для функции generate_license_key()."""

    def test_generate_key_format(self):
        """Тест формата сгенерированного ключа."""
        key = generate_license_key()
        assert len(key) == 19  # 16 символов + 3 дефиса
        assert key.count("-") == 3

    def test_generate_key_validate_format(self):
        """Тест валидности формата сгенерированного ключа."""
        key = generate_license_key()
        assert KeyValidator.validate(key) is True

    def test_generate_key_validate_checksum(self):
        """Тест контрольной суммы сгенерированного ключа."""
        key = generate_license_key()
        assert KeyValidator.validate_checksum(key) is True

    def test_generate_key_unique(self):
        """Тест уникальности сгенерированных ключей."""
        keys = [generate_license_key() for _ in range(100)]
        assert len(set(keys)) == 100  # Все ключи уникальны

    def test_generate_key_uses_alphabet(self):
        """Тест использования только символов из алфавита."""
        key = generate_license_key()
        normalized = key.replace("-", "")
        for char in normalized:
            assert char in _ALPHABET


class TestComputeChecksum:
    """Тесты для функции _compute_checksum()."""

    def test_checksum_deterministic(self):
        """Тест детерминированности контрольной суммы."""
        body = "ABCDEFGHJKMN"
        checksum1 = _compute_checksum(body)
        checksum2 = _compute_checksum(body)
        assert checksum1 == checksum2

    def test_checksum_length(self):
        """Тест длины контрольной суммы."""
        checksum = _compute_checksum("ABCDEFGHJKMN")
        assert len(checksum) == 4

    def test_checksum_different_inputs(self):
        """Тест разных контрольных сумм для разных входов."""
        checksum1 = _compute_checksum("ABCDEFGHJKMN")
        checksum2 = _compute_checksum("XYZWVUTSRQPM")
        assert checksum1 != checksum2

    def test_checksum_uses_alphabet(self):
        """Тест использования только символов алфавита."""
        checksum = _compute_checksum("TESTBODYDATA")
        for char in checksum:
            assert char in _ALPHABET

