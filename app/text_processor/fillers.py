"""
Модуль удаления слов-паразитов (филлеров) из транскрипций.

Поддерживает русский и английский языки.
Учитывает контекст, чтобы не удалять слова в составе фраз.
"""

import re
from typing import List, Optional, Set, Tuple

from .config import ProcessingConfig


# Филлеры русского языка
FILLERS_RU = [
    # Звуковые филлеры
    "эээ", "ээ", "э-э-э", "э-э",
    "ммм", "мм", "м-м-м", "м-м",
    "ааа", "а-а-а",
    "угу", "ага",

    # Слова-паразиты (одиночные)
    "ну",
    "вот",
    "так",
    # "это" - убрано, слишком часто используется осмысленно
    "того",
    "значит",
    "короче",
    "блин",
    "типа",
    "прикинь",
    "прикиньте",
    "слышь",
    "чё",
    "чо",

    # Фразы-паразиты
    "как бы",
    "то есть",
    "так сказать",
    "в общем",
    "в принципе",
    "на самом деле",
    "по факту",
    "как говорится",
    "скажем так",
    "грубо говоря",
    "если честно",
    "честно говоря",
    "по сути",
    "по идее",
    "в целом",
    "собственно говоря",
    "собственно",
]

# Филлеры английского языка
FILLERS_EN = [
    # Sound fillers
    "uh", "uhh", "uhhh",
    "um", "umm", "ummm",
    "er", "err",
    "ah", "ahh",
    "hmm", "hm",

    # Filler words
    "like",
    "basically",
    "actually",
    "literally",
    "honestly",
    "seriously",
    "obviously",
    "apparently",
    "definitely",

    # Filler phrases
    "you know",
    "i mean",
    "you see",
    "kind of",
    "sort of",
    "at the end of the day",
    "to be honest",
    "for what it's worth",
    "as a matter of fact",
]

# Контексты, в которых НЕ нужно удалять слова
# (слово : список паттернов где оно НЕ филлер)
CONTEXT_EXCEPTIONS_RU = {
    "ну": [
        r"ну и что\b",       # "ну и что?" - вопрос
        r"ну-ну\b",          # "ну-ну" - междометие
        r"ну да\b",          # "ну да" - согласие
        r"ну нет\b",         # "ну нет" - несогласие
    ],
    "вот": [
        r"вот это\b",        # "вот это да!" - восклицание
        r"вот так\b",        # "вот так" - указание
        r"вот именно\b",     # "вот именно" - согласие
    ],
    "так": [
        r"так и\b",          # "так и есть"
        r"так что\b",        # "так что" - вывод
        r"и так\b",          # "и так далее"
        r"так как\b",        # "так как" - причина
        r"так же\b",         # "так же" - сравнение
        r"вот так\b",        # "вот так" - указание
    ],
    "слушай": [
        r"слушай музыку",
        r"слушай радио",
        r"слушай аудио",
        r"слушай подкаст",
    ],
}

CONTEXT_EXCEPTIONS_EN = {
    "like": [
        r"would like\b",     # "would like to"
        r"looks like\b",     # "looks like"
        r"feels like\b",     # "feels like"
        r"sounds like\b",    # "sounds like"
        r"seems like\b",     # "seems like"
        r"just like\b",      # "just like"
        r"like this\b",      # "like this"
        r"like that\b",      # "like that"
        r"like \d+",         # "like 5 times"
    ],
    "actually": [
        r"actually \w+ed\b",  # "actually happened"
    ],
}


class FillerRemover:
    """
    Удаляет слова-паразиты из текста с учётом контекста.

    Пример использования:
        remover = FillerRemover()
        clean = remover.remove("Ну, эээ, давайте обсудим, типа, бюджет")
        # "Давайте обсудим бюджет"
    """

    def __init__(self, config: Optional[ProcessingConfig] = None):
        self.config = config or ProcessingConfig()

        # Собираем все филлеры
        self._fillers_ru: Set[str] = set(FILLERS_RU)
        self._fillers_en: Set[str] = set(FILLERS_EN)

        # Добавляем кастомные
        if self.config.custom_fillers_ru:
            self._fillers_ru.update(self.config.custom_fillers_ru)
        if self.config.custom_fillers_en:
            self._fillers_en.update(self.config.custom_fillers_en)

        # Компилируем паттерны для контекстных исключений
        self._exceptions_ru = self._compile_exceptions(CONTEXT_EXCEPTIONS_RU)
        self._exceptions_en = self._compile_exceptions(CONTEXT_EXCEPTIONS_EN)

    def _compile_exceptions(self, exceptions: dict) -> dict:
        """Компилирует регулярные выражения для исключений."""
        compiled = {}
        for word, patterns in exceptions.items():
            compiled[word] = [re.compile(p, re.IGNORECASE) for p in patterns]
        return compiled

    def _should_keep(self, word: str, text: str, position: int, language: str) -> bool:
        """
        Проверяет, нужно ли сохранить слово (является ли оно частью значимой фразы).

        Args:
            word: Слово для проверки
            text: Полный текст
            position: Позиция слова в тексте
            language: Язык ("ru" или "en")

        Returns:
            True если слово нужно сохранить
        """
        if not self.config.filler_preserve_context:
            return False

        exceptions = self._exceptions_ru if language == "ru" else self._exceptions_en
        word_lower = word.lower()

        if word_lower not in exceptions:
            return False

        # Проверяем контекст вокруг слова
        context_start = max(0, position - 20)
        context_end = min(len(text), position + len(word) + 20)
        context = text[context_start:context_end].lower()

        for pattern in exceptions[word_lower]:
            if pattern.search(context):
                return True

        return False

    def _build_filler_pattern(self, fillers: Set[str]) -> re.Pattern:
        """
        Строит регулярное выражение для поиска филлеров.

        Филлеры сортируются по длине (длинные первыми),
        чтобы "как бы" матчилось раньше "как".
        """
        # Сортируем по длине (длинные первыми)
        sorted_fillers = sorted(fillers, key=len, reverse=True)

        # Экранируем спецсимволы и добавляем границы слов
        patterns = []
        for filler in sorted_fillers:
            escaped = re.escape(filler)
            # Добавляем опциональные запятые/пробелы вокруг
            patterns.append(rf"(?:^|[\s,])({escaped})(?:[\s,]|$)")

        return re.compile("|".join(patterns), re.IGNORECASE)

    def remove(self, text: str, language: Optional[str] = None) -> str:
        """
        Удаляет филлеры из текста.

        Args:
            text: Исходный текст
            language: Язык текста ("ru", "en" или None для автоопределения)

        Returns:
            Текст без филлеров
        """
        if not text:
            return text

        lang = language or self._detect_language(text)
        fillers = self._fillers_ru if lang == "ru" else self._fillers_en

        result = text

        # Сначала обрабатываем многословные филлеры
        multi_word = [f for f in fillers if " " in f]
        for filler in sorted(multi_word, key=len, reverse=True):
            pattern = re.compile(
                rf"(?:^|[\s,])({re.escape(filler)})(?:[\s,.]|$)",
                re.IGNORECASE
            )
            result = pattern.sub(" ", result)

        # Затем одиночные слова
        single_word = [f for f in fillers if " " not in f]
        for filler in sorted(single_word, key=len, reverse=True):
            # Ищем все вхождения
            pattern = re.compile(
                rf"\b({re.escape(filler)})\b",
                re.IGNORECASE
            )

            matches = list(pattern.finditer(result))
            # Обрабатываем в обратном порядке, чтобы позиции не сбивались
            for match in reversed(matches):
                if not self._should_keep(filler, result, match.start(), lang):
                    # Удаляем, сохраняя пробелы
                    before = result[:match.start()]
                    after = result[match.end():]

                    # Убираем лишние запятые
                    if before.rstrip().endswith(","):
                        before = before.rstrip()[:-1] + " "
                    if after.lstrip().startswith(","):
                        after = after.lstrip()[1:]

                    result = before + after

        # Очистка: убираем двойные пробелы, лишние запятые
        result = re.sub(r"\s+", " ", result)
        result = re.sub(r"\s*,\s*,\s*", ", ", result)
        result = re.sub(r"^\s*,\s*", "", result)
        result = re.sub(r"\s*,\s*$", "", result)
        result = result.strip()

        # Капитализация первой буквы после удаления
        if result and result[0].islower() and (not text or text[0].isupper()):
            result = result[0].upper() + result[1:]

        return result

    def _detect_language(self, text: str) -> str:
        """
        Простое определение языка по преобладающему алфавиту.
        """
        cyrillic = len(re.findall(r"[а-яёА-ЯЁ]", text))
        latin = len(re.findall(r"[a-zA-Z]", text))
        return "ru" if cyrillic > latin else "en"

    def get_fillers_found(self, text: str, language: Optional[str] = None) -> List[Tuple[str, int]]:
        """
        Возвращает список найденных филлеров с их позициями.

        Args:
            text: Текст для анализа
            language: Язык текста

        Returns:
            Список кортежей (филлер, позиция)
        """
        lang = language or self._detect_language(text)
        fillers = self._fillers_ru if lang == "ru" else self._fillers_en

        found = []
        for filler in fillers:
            pattern = re.compile(rf"\b({re.escape(filler)})\b", re.IGNORECASE)
            for match in pattern.finditer(text):
                if not self._should_keep(filler, text, match.start(), lang):
                    found.append((match.group(1), match.start()))

        return sorted(found, key=lambda x: x[1])

