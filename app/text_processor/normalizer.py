"""
Модуль нормализации текста: числа, даты, время, валюта.

Преобразует произнесённые числительные в цифровой формат:
- "двадцать третьего марта" → "23 марта"
- "пятьсот тысяч рублей" → "500 000 руб."
- "два часа тридцать минут" → "2:30"
"""

import re
from typing import Dict, List, Optional, Tuple

from .config import ProcessingConfig


# Числительные (русский язык)
NUMBERS_RU = {
    # Единицы
    "ноль": 0, "нуль": 0,
    "один": 1, "одна": 1, "одно": 1, "первый": 1, "первого": 1, "первое": 1,
    "два": 2, "две": 2, "второй": 2, "второго": 2, "второе": 2,
    "три": 3, "третий": 3, "третьего": 3, "третье": 3,
    "четыре": 4, "четвёртый": 4, "четвертый": 4, "четвёртого": 4, "четвертого": 4,
    "пять": 5, "пятый": 5, "пятого": 5,
    "шесть": 6, "шестой": 6, "шестого": 6,
    "семь": 7, "седьмой": 7, "седьмого": 7,
    "восемь": 8, "восьмой": 8, "восьмого": 8,
    "девять": 9, "девятый": 9, "девятого": 9,

    # Десятки
    "десять": 10, "десятый": 10, "десятого": 10,
    "одиннадцать": 11, "одиннадцатый": 11, "одиннадцатого": 11,
    "двенадцать": 12, "двенадцатый": 12, "двенадцатого": 12,
    "тринадцать": 13, "тринадцатый": 13, "тринадцатого": 13,
    "четырнадцать": 14, "четырнадцатый": 14, "четырнадцатого": 14,
    "пятнадцать": 15, "пятнадцатый": 15, "пятнадцатого": 15,
    "шестнадцать": 16, "шестнадцатый": 16, "шестнадцатого": 16,
    "семнадцать": 17, "семнадцатый": 17, "семнадцатого": 17,
    "восемнадцать": 18, "восемнадцатый": 18, "восемнадцатого": 18,
    "девятнадцать": 19, "девятнадцатый": 19, "девятнадцатого": 19,
    "двадцать": 20, "двадцатый": 20, "двадцатого": 20,
    "тридцать": 30, "тридцатый": 30, "тридцатого": 30,
    "сорок": 40, "сороковой": 40, "сорокового": 40,
    "пятьдесят": 50, "пятидесятый": 50, "пятидесятого": 50,
    "шестьдесят": 60, "шестидесятый": 60, "шестидесятого": 60,
    "семьдесят": 70, "семидесятый": 70, "семидесятого": 70,
    "восемьдесят": 80, "восьмидесятый": 80, "восьмидесятого": 80,
    "девяносто": 90, "девяностый": 90, "девяностого": 90,

    # Сотни
    "сто": 100, "сотый": 100,
    "двести": 200, "двухсотый": 200,
    "триста": 300, "трёхсотый": 300, "трехсотый": 300,
    "четыреста": 400, "четырёхсотый": 400, "четырехсотый": 400,
    "пятьсот": 500, "пятисотый": 500,
    "шестьсот": 600, "шестисотый": 600,
    "семьсот": 700, "семисотый": 700,
    "восемьсот": 800, "восьмисотый": 800,
    "девятьсот": 900, "девятисотый": 900,
}

# Множители
MULTIPLIERS_RU = {
    "тысяча": 1000, "тысячи": 1000, "тысяч": 1000, "тыс": 1000, "тыщ": 1000,
    "миллион": 1_000_000, "миллиона": 1_000_000, "миллионов": 1_000_000, "млн": 1_000_000,
    "миллиард": 1_000_000_000, "миллиарда": 1_000_000_000, "миллиардов": 1_000_000_000, "млрд": 1_000_000_000,
}

# Месяцы
MONTHS_RU = {
    "января": "января", "январь": "января", "янв": "января",
    "февраля": "февраля", "февраль": "февраля", "фев": "февраля",
    "марта": "марта", "март": "марта", "мар": "марта",
    "апреля": "апреля", "апрель": "апреля", "апр": "апреля",
    "мая": "мая", "май": "мая",
    "июня": "июня", "июнь": "июня", "июн": "июня",
    "июля": "июля", "июль": "июля", "июл": "июля",
    "августа": "августа", "август": "августа", "авг": "августа",
    "сентября": "сентября", "сентябрь": "сентября", "сен": "сентября",
    "октября": "октября", "октябрь": "октября", "окт": "октября",
    "ноября": "ноября", "ноябрь": "ноября", "ноя": "ноября",
    "декабря": "декабря", "декабрь": "декабря", "дек": "декабря",
}

# Валюты
CURRENCIES_RU = {
    "рубль": "руб.", "рубля": "руб.", "рублей": "руб.", "руб": "руб.", "р": "руб.",
    "доллар": "$", "доллара": "$", "долларов": "$", "бакс": "$", "баксов": "$",
    "евро": "€",
    "юань": "¥", "юаня": "¥", "юаней": "¥",
}


class TextNormalizer:
    """
    Нормализатор текста: преобразует произнесённые числа, даты и т.д.

    Пример использования:
        normalizer = TextNormalizer()
        text = normalizer.normalize("встреча двадцать третьего марта в два часа")
        # "встреча 23 марта в 2:00"
    """

    def __init__(self, config: Optional[ProcessingConfig] = None):
        self.config = config or ProcessingConfig()

        # Компилируем паттерны для чисел
        self._number_words = set(NUMBERS_RU.keys()) | set(MULTIPLIERS_RU.keys())
        self._number_pattern = self._build_number_pattern()

    def _build_number_pattern(self) -> re.Pattern:
        """Строит паттерн для поиска числительных."""
        words = sorted(self._number_words, key=len, reverse=True)
        escaped = [re.escape(w) for w in words]
        pattern = r"\b(" + "|".join(escaped) + r")(\s+(" + "|".join(escaped) + r"))*\b"
        return re.compile(pattern, re.IGNORECASE)

    def normalize(self, text: str, language: Optional[str] = None) -> str:
        """
        Нормализует текст: числа, даты, время, валюту.

        Args:
            text: Исходный текст
            language: Язык ("ru" или "en")

        Returns:
            Нормализованный текст
        """
        if not text:
            return text

        lang = language or self._detect_language(text)

        result = text

        if lang == "ru":
            if self.config.normalize_dates:
                result = self._normalize_dates_ru(result)

            if self.config.normalize_time:
                result = self._normalize_time_ru(result)

            if self.config.normalize_numbers:
                result = self._normalize_numbers_ru(result)

            if self.config.normalize_currency:
                result = self._normalize_currency_ru(result)

        return result

    def _normalize_numbers_ru(self, text: str) -> str:
        """Нормализует числительные в тексте."""
        result = text

        def replace_number(match):
            words = match.group(0).lower().split()
            value = self._words_to_number(words)
            if value is not None:
                return self._format_number(value)
            return match.group(0)

        result = self._number_pattern.sub(replace_number, result)

        return result

    def _words_to_number(self, words: List[str]) -> Optional[int]:
        """
        Преобразует список слов-числительных в число.

        Алгоритм:
        - Складываем единицы, десятки, сотни
        - При встрече множителя (тысяча, миллион) — умножаем накопленное
        """
        if not words:
            return None

        # Фильтруем только числовые слова
        num_words = [w for w in words if w in NUMBERS_RU or w in MULTIPLIERS_RU]
        if not num_words:
            return None

        total = 0
        current = 0

        for word in num_words:
            if word in NUMBERS_RU:
                current += NUMBERS_RU[word]
            elif word in MULTIPLIERS_RU:
                multiplier = MULTIPLIERS_RU[word]
                if current == 0:
                    current = 1
                current *= multiplier

                # Если это тысячи и выше — добавляем к total
                if multiplier >= 1000:
                    total += current
                    current = 0

        total += current
        return total if total > 0 else None

    def _format_number(self, value: int) -> str:
        """Форматирует число с разделителями."""
        if value >= 1000:
            # Добавляем пробелы как разделители тысяч
            return f"{value:,}".replace(",", " ")
        return str(value)

    def _normalize_dates_ru(self, text: str) -> str:
        """
        Нормализует даты в тексте.

        "двадцать третьего марта" → "23 марта"
        "пятое января" → "5 января"
        """
        result = text

        # Паттерн: числительные + месяц (включая составные типа "двадцать третьего")
        for month_word, month_norm in MONTHS_RU.items():
            # Паттерн для составных порядковых: "двадцать третьего", "тридцать первого"
            compound_pattern = rf"(\b(?:двадцать|тридцать)\s+\w+(?:ого|его|ьего))\s+{re.escape(month_word)}\b"

            def replace_compound_date(match):
                words = match.group(1).lower().split()
                if len(words) == 2:
                    tens = NUMBERS_RU.get(words[0], 0)
                    units = NUMBERS_RU.get(words[1], 0)
                    day = tens + units
                    if day > 0:
                        return f"{day} {month_norm}"
                return match.group(0)

            result = re.sub(compound_pattern, replace_compound_date, result, flags=re.IGNORECASE)

            # Паттерн для простых порядковых: "пятого", "десятого"
            simple_pattern = rf"(\b\w+(?:ого|его|ьего|ое|ый|ий)\b)\s+{re.escape(month_word)}\b"

            def replace_simple_date(match):
                ordinal = match.group(1).lower()
                if ordinal in NUMBERS_RU:
                    day = NUMBERS_RU[ordinal]
                    return f"{day} {month_norm}"
                return match.group(0)

            result = re.sub(simple_pattern, replace_simple_date, result, flags=re.IGNORECASE)

        return result

    def _normalize_time_ru(self, text: str) -> str:
        """
        Нормализует время в тексте.

        "два часа тридцать минут" → "2:30"
        "в три часа" → "в 3:00"
        """
        result = text

        # Паттерн: X часов Y минут
        time_pattern = r"(\w+)\s+час(?:а|ов|)\s+(\w+)\s+минут(?:а|ы|)"

        def replace_time_full(match):
            hour_word = match.group(1).lower()
            minute_word = match.group(2).lower()

            hour = NUMBERS_RU.get(hour_word)
            minute = NUMBERS_RU.get(minute_word)

            if hour is not None and minute is not None:
                return f"{hour}:{minute:02d}"
            return match.group(0)

        result = re.sub(time_pattern, replace_time_full, result, flags=re.IGNORECASE)

        # Паттерн: X часов (без минут)
        hour_only_pattern = r"(\w+)\s+час(?:а|ов|)\b"

        def replace_time_hour(match):
            hour_word = match.group(1).lower()
            hour = NUMBERS_RU.get(hour_word)
            if hour is not None and hour <= 24:
                return f"{hour}:00"
            return match.group(0)

        result = re.sub(hour_only_pattern, replace_time_hour, result, flags=re.IGNORECASE)

        return result

    def _normalize_currency_ru(self, text: str) -> str:
        """
        Нормализует валюту в тексте.

        "пятьсот тысяч рублей" → "500 000 руб."
        """
        result = text

        for currency_word, currency_symbol in CURRENCIES_RU.items():
            # Паттерн: число + валюта
            pattern = rf"(\d[\d\s]*)\s*{re.escape(currency_word)}\b"

            def make_replacer(symbol):
                def replace_currency(match):
                    number = match.group(1).strip()
                    return f"{number} {symbol}"
                return replace_currency

            result = re.sub(pattern, make_replacer(currency_symbol), result, flags=re.IGNORECASE)

        return result

    def _detect_language(self, text: str) -> str:
        """Определение языка по алфавиту."""
        cyrillic = len(re.findall(r"[а-яёА-ЯЁ]", text))
        latin = len(re.findall(r"[a-zA-Z]", text))
        return "ru" if cyrillic > latin else "en"

    def get_numbers_found(self, text: str) -> List[Tuple[str, int, int]]:
        """
        Находит все числительные в тексте.

        Returns:
            Список кортежей (текст, значение, позиция)
        """
        found = []

        for match in self._number_pattern.finditer(text):
            words = match.group(0).lower().split()
            value = self._words_to_number(words)
            if value is not None:
                found.append((match.group(0), value, match.start()))

        return found

