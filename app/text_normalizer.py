"""
Нормализация текста перед TTS (Text-to-Speech).

Преобразует:
- Числа -> слова (1500 -> тысяча пятьсот)
- Даты -> текст (25.05.2025 -> двадцать пятое мая...)
- Время -> текст (14:30 -> четырнадцать тридцать)
- Проценты, валюты
- Аббревиатуры (API -> АПИ)
- Транслитерация английских слов
"""

import re
import logging
from typing import Dict, Optional
from datetime import datetime

try:
    from num2words import num2words
except ImportError:
    num2words = None

try:
    from transliterate import translit
except ImportError:
    translit = None

logger = logging.getLogger(__name__)


class TextNormalizer:
    """Нормализатор текста для TTS."""

    def __init__(self, language: str = "ru"):
        """
        Args:
            language: Язык для нормализации (ru, en, etc.)
        """
        self.language = language
        self.enabled = {
            "numbers": True,
            "dates": True,
            "time": True,
            "currency": True,
            "percent": True,
            "abbreviations": True,
            "translit": True,
        }

        # Карта аббревиатур для русского
        self.ru_abbreviations = {
            "API": "АПИ",
            "URL": "ю-ар-эль",
            "HTTP": "аш-ти-ти-пи",
            "HTTPS": "аш-ти-ти-пи-эс",
            "HTML": "аш-ти-эм-эль",
            "CSS": "си-эс-эс",
            "JS": "джей-эс",
            "SQL": "эс-кью-эль",
            "GPU": "джи-пи-ю",
            "CPU": "си-пи-ю",
            "RAM": "рам",
            "SSD": "эс-эс-ди",
            "USB": "ю-эс-би",
            "AI": "ай-ай",
            "ML": "эм-эль",
            "NLP": "эн-эль-пи",
            "TTS": "ти-ти-эс",
            "STT": "эс-ти-ти",
            "UI": "ю-ай",
            "UX": "ю-экс",
            "ID": "ай-ди",
            "OK": "окей",
            "FAQ": "эф-эй-кью",
        }

        # Названия месяцев в родительном падеже
        self.ru_months_genitive = {
            1: "января",
            2: "февраля",
            3: "марта",
            4: "апреля",
            5: "мая",
            6: "июня",
            7: "июля",
            8: "августа",
            9: "сентября",
            10: "октября",
            11: "ноября",
            12: "декабря",
        }

    def normalize(self, text: str) -> str:
        """
        Нормализовать текст для TTS.

        Args:
            text: Исходный текст

        Returns:
            Нормализованный текст
        """
        if not text:
            return text

        # Порядок важен!
        if self.enabled["dates"]:
            text = self._normalize_dates(text)

        if self.enabled["time"]:
            text = self._normalize_time(text)

        if self.enabled["currency"]:
            text = self._normalize_currency(text)

        if self.enabled["percent"]:
            text = self._normalize_percent(text)

        if self.enabled["numbers"]:
            text = self._normalize_numbers(text)

        if self.enabled["abbreviations"]:
            text = self._normalize_abbreviations(text)

        if self.enabled["translit"]:
            text = self._normalize_english_words(text)

        return text

    def _normalize_numbers(self, text: str) -> str:
        """Преобразовать числа в слова."""
        if not num2words:
            return text

        def replace_number(match):
            number_str = match.group(0)
            try:
                # Убираем разделители
                number_str = number_str.replace(",", "").replace(" ", "")
                number = int(number_str)

                # Для русского используем num2words
                if self.language == "ru":
                    return num2words(number, lang="ru")
                else:
                    return num2words(number, lang=self.language)
            except (ValueError, NotImplementedError):
                return match.group(0)

        # Находим числа (включая с разделителями)
        pattern = r"\b\d{1,3}(?:[,\s]\d{3})*\b"
        return re.sub(pattern, replace_number, text)

    def _normalize_dates(self, text: str) -> str:
        """Преобразовать даты в текст."""
        if self.language != "ru":
            return text

        # Паттерн для дат: DD.MM.YYYY, DD/MM/YYYY, DD-MM-YYYY
        pattern = r"\b(\d{1,2})[\./\-](\d{1,2})[\./\-](\d{4})\b"

        def replace_date(match):
            day, month, year = match.groups()
            try:
                day_num = int(day)
                month_num = int(month)
                year_num = int(year)

                if not (1 <= day_num <= 31 and 1 <= month_num <= 12):
                    return match.group(0)

                # Форматируем дату для русского языка
                if num2words:
                    day_word = num2words(day_num, lang="ru", to="ordinal")
                    year_word = num2words(year_num, lang="ru", to="ordinal")
                    month_word = self.ru_months_genitive.get(month_num, "")

                    # "двадцать пятое мая две тысячи двадцать пятого года"
                    return f"{day_word} {month_word} {year_word} года"
                else:
                    return match.group(0)
            except (ValueError, NotImplementedError):
                return match.group(0)

        return re.sub(pattern, replace_date, text)

    def _normalize_time(self, text: str) -> str:
        """Преобразовать время в текст."""
        # Паттерн для времени: HH:MM или HH:MM:SS
        pattern = r"\b(\d{1,2}):(\d{2})(?::(\d{2}))?\b"

        def replace_time(match):
            hours, minutes, seconds = match.groups()
            try:
                hours_num = int(hours)
                minutes_num = int(minutes)

                if not (0 <= hours_num <= 23 and 0 <= minutes_num <= 59):
                    return match.group(0)

                if num2words and self.language == "ru":
                    hours_word = num2words(hours_num, lang="ru")
                    minutes_word = num2words(minutes_num, lang="ru")

                    # Простой формат: "четырнадцать тридцать"
                    result = f"{hours_word} {minutes_word}"

                    if seconds:
                        seconds_num = int(seconds)
                        if 0 <= seconds_num <= 59:
                            seconds_word = num2words(seconds_num, lang="ru")
                            result += f" {seconds_word}"

                    return result
                else:
                    return match.group(0)
            except (ValueError, NotImplementedError):
                return match.group(0)

        return re.sub(pattern, replace_time, text)

    def _normalize_currency(self, text: str) -> str:
        """Преобразовать валюты в текст."""
        # Символы валют
        currencies = {
            "$": "долларов",
            "€": "евро",
            "£": "фунтов",
            "¥": "йен",
            "₽": "рублей",
        }

        for symbol, word in currencies.items():
            # $100 или 100$
            pattern = rf"(?:({re.escape(symbol)})(\d+)|(\d+)({re.escape(symbol)}))"

            def replace_currency(match):
                if match.group(1):  # $100
                    amount = match.group(2)
                else:  # 100$
                    amount = match.group(3)

                try:
                    amount_num = int(amount)
                    if num2words and self.language == "ru":
                        amount_word = num2words(amount_num, lang="ru")
                        return f"{amount_word} {word}"
                    else:
                        return f"{amount} {word}"
                except (ValueError, NotImplementedError):
                    return match.group(0)

            text = re.sub(pattern, replace_currency, text)

        return text

    def _normalize_percent(self, text: str) -> str:
        """Преобразовать проценты в текст."""
        pattern = r"(\d+(?:\.\d+)?)%"

        def replace_percent(match):
            number_str = match.group(1)
            try:
                if "." in number_str:
                    number = float(number_str)
                else:
                    number = int(number_str)

                if num2words and self.language == "ru":
                    if isinstance(number, float):
                        # Для дробных используем строку
                        number_word = str(number).replace(".", " целых ")
                    else:
                        number_word = num2words(number, lang="ru")
                    return f"{number_word} процентов"
                else:
                    return f"{number_str} процентов"
            except (ValueError, NotImplementedError):
                return match.group(0)

        return re.sub(pattern, replace_percent, text)

    def _normalize_abbreviations(self, text: str) -> str:
        """Преобразовать аббревиатуры."""
        if self.language != "ru":
            return text

        # Заменяем известные аббревиатуры
        for abbr, replacement in self.ru_abbreviations.items():
            # Ищем целые слова
            pattern = rf"\b{re.escape(abbr)}\b"
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

        return text

    def _normalize_english_words(self, text: str) -> str:
        """Транслитерировать английские слова в русский."""
        if self.language != "ru" or not translit:
            return text

        # Находим английские слова (буквы a-z, A-Z)
        pattern = r"\b[a-zA-Z]+(?:\s+[a-zA-Z]+)?\b"

        def replace_english(match):
            word = match.group(0)

            # Пропускаем короткие слова и аббревиатуры
            if len(word) <= 2 or word.upper() in self.ru_abbreviations:
                return word

            try:
                # Транслитерируем в кириллицу
                transliterated = translit(word, "ru", reversed=True)
                return transliterated.lower()
            except Exception:
                return word

        return re.sub(pattern, replace_english, text)

    def set_enabled(self, option: str, enabled: bool) -> None:
        """
        Включить/выключить опцию нормализации.

        Args:
            option: Название опции (numbers, dates, translit, etc.)
            enabled: Включить или выключить
        """
        if option in self.enabled:
            self.enabled[option] = enabled


# Глобальный экземпляр
_normalizer: Optional[TextNormalizer] = None


def get_normalizer(language: str = "ru") -> TextNormalizer:
    """Получить глобальный нормализатор."""
    global _normalizer
    if _normalizer is None or _normalizer.language != language:
        _normalizer = TextNormalizer(language)
    return _normalizer


