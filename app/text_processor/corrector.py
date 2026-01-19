"""
Модуль коррекции типичных ошибок ASR (Automatic Speech Recognition).

Исправляет:
- Аббревиатуры, произнесённые по буквам ("тэ зэ" → "ТЗ")
- Частые ошибки распознавания
- Технические термины
- Имена собственные
"""

import re
from typing import Dict, List, Optional, Tuple

from .config import ProcessingConfig


# Аббревиатуры, произнесённые по буквам (русский)
ABBREVIATIONS_RU = {
    # Документация
    "тэ зэ": "ТЗ",
    "тэзэ": "ТЗ",
    "т з": "ТЗ",

    "тэ э пэ": "ТЭП",
    "тэпэ": "ТЭП",
    "т э п": "ТЭП",

    "эм а эф": "МАФ",
    "маф": "МАФ",
    "м а ф": "МАФ",

    "дэ о у": "ДОУ",
    "доу": "ДОУ",
    "д о у": "ДОУ",

    "эл дэ пэ эр": "ЛДПР",
    "эл дэ пэ р": "ЛДПР",

    "эс эс эс эр": "СССР",
    "эс эс эс р": "СССР",

    "эс ша а": "США",
    "сша": "США",

    "эс эн гэ": "СНГ",
    "снг": "СНГ",

    "пэ дэ эф": "PDF",
    "пдф": "PDF",
    "п д ф": "PDF",

    "дэ о кэ": "DOC",
    "док": "DOC",

    "и пэ": "IP",
    "ай пи": "IP",

    "вэ пэ эн": "VPN",
    "впн": "VPN",

    "эй ай": "AI",
    "ай ай": "AI",

    "эс эм эс": "SMS",
    "смс": "SMS",

    "эс ай ди": "SID",
    "сид": "SID",

    # Строительство/архитектура
    "стадия р": "стадия Р",
    "стадия пэ": "стадия П",

    "эп": "ЭП",
    "э пэ": "ЭП",

    "бэ и эм": "BIM",
    "бим": "BIM",

    "а эс": "АС",
    "а с": "АС",

    "о вэ": "ОВ",
    "о в": "ОВ",

    "вэ кэ": "ВК",
    "в к": "ВК",

    "эс эс": "СС",
    "с с": "СС",

    "а эр": "АР",
    "а р": "АР",

    "кэ жэ": "КЖ",
    "к ж": "КЖ",

    "кэ эм": "КМ",
    "к м": "КМ",

    # IT термины
    "эс кю эл": "SQL",
    "скьюл": "SQL",
    "сиквел": "SQL",

    "эйч тэ тэ пэ": "HTTP",
    "хттп": "HTTP",

    "эйч тэ эм эл": "HTML",
    "хтмл": "HTML",

    "си эс эс": "CSS",
    "цсс": "CSS",

    "джи эс о эн": "JSON",
    "джейсон": "JSON",
    "жсон": "JSON",

    "а пэ и": "API",
    "апи": "API",
    "эй пи ай": "API",

    "си ди": "CD",
    "сиди": "CD",

    "ди ви ди": "DVD",
    "двд": "DVD",

    "ю эс бэ": "USB",
    "юсб": "USB",
    "усб": "USB",

    "джи пэ ю": "GPU",
    "гпу": "GPU",

    "си пэ ю": "CPU",
    "цпу": "CPU",
    "цэпэу": "CPU",

    "эс эс ди": "SSD",
    "ссд": "SSD",

    "эйч ди ди": "HDD",
    "хдд": "HDD",
}

# Частые ошибки распознавания (русский)
COMMON_ERRORS_RU = {
    # Омофоны и похожие звуки
    "в течении": "в течение",
    "в следствии": "вследствие",
    "в следствие": "вследствие",
    "впринципе": "в принципе",
    "вобщем": "в общем",
    "в общем то": "в общем-то",
    "потомучто": "потому что",
    "так же": "также",  # контекстно
    "тоже самое": "то же самое",
    "за ранее": "заранее",
    "в виду": "ввиду",
    "не смотря на": "несмотря на",
    "по этому": "поэтому",  # контекстно

    # Цифры/числа
    "тысщ": "тысяч",
    "тыщ": "тысяч",
    "милион": "миллион",
    "миллиён": "миллион",
    "милиард": "миллиард",

    # Технические термины
    "транскрипт": "транскрипт",
    "транскрибция": "транскрипция",

    # Строительные термины
    "стило бат": "стилобат",
    "мало этажный": "малоэтажный",
    "много этажный": "многоэтажный",
    "жил комплекс": "жилкомплекс",
    "жилой комплекс": "жилой комплекс",  # норм
}

# Технические термины, которые часто искажаются
TECHNICAL_TERMS_RU = {
    "уисепер": "Whisper",
    "вхиспер": "Whisper",
    "виспер": "Whisper",

    "нейронка": "нейросеть",
    "нейронная сетка": "нейросеть",

    "квен": "Qwen",
    "кьюэн": "Qwen",

    "опенроутер": "OpenRouter",
    "опен роутер": "OpenRouter",

    "хаггинг фейс": "HuggingFace",
    "хагинг фейс": "HuggingFace",

    "лама": "LLaMA",
    "llama": "LLaMA",

    "гпт": "GPT",
    "джи пи ти": "GPT",

    "чат гпт": "ChatGPT",
    "чатгпт": "ChatGPT",
}

# Английские ошибки
COMMON_ERRORS_EN = {
    "could of": "could have",
    "would of": "would have",
    "should of": "should have",
    "must of": "must have",
    "might of": "might have",

    "your welcome": "you're welcome",
    "its a": "it's a",

    "definately": "definitely",
    "seperate": "separate",
    "occured": "occurred",
    "recieve": "receive",

    "gonna": "going to",
    "wanna": "want to",
    "gotta": "got to",
    "kinda": "kind of",
    "sorta": "sort of",
    "coulda": "could have",
    "woulda": "would have",
    "shoulda": "should have",
}


class ASRCorrector:
    """
    Корректор типичных ошибок ASR.

    Пример использования:
        corrector = ASRCorrector()
        fixed = corrector.correct("Нужно сделать тэ зэ до пятницы")
        # "Нужно сделать ТЗ до пятницы"
    """

    def __init__(self, config: Optional[ProcessingConfig] = None):
        self.config = config or ProcessingConfig()

        # Собираем все словари коррекций
        self._corrections_ru: Dict[str, str] = {}
        self._corrections_ru.update(ABBREVIATIONS_RU)
        self._corrections_ru.update(COMMON_ERRORS_RU)
        self._corrections_ru.update(TECHNICAL_TERMS_RU)

        self._corrections_en: Dict[str, str] = {}
        self._corrections_en.update(COMMON_ERRORS_EN)

        # Добавляем кастомные коррекции
        if self.config.custom_corrections:
            self._corrections_ru.update(self.config.custom_corrections)
            self._corrections_en.update(self.config.custom_corrections)

        # Компилируем паттерны
        self._patterns_ru = self._compile_patterns(self._corrections_ru)
        self._patterns_en = self._compile_patterns(self._corrections_en)

    def _compile_patterns(self, corrections: Dict[str, str]) -> List[Tuple[re.Pattern, str]]:
        """
        Компилирует регулярные выражения для замен.
        Сортирует по длине (длинные первыми).
        """
        patterns = []
        for error, fix in sorted(corrections.items(), key=lambda x: len(x[0]), reverse=True):
            # Создаём паттерн с границами слов
            pattern = re.compile(
                rf"\b{re.escape(error)}\b",
                re.IGNORECASE
            )
            patterns.append((pattern, fix))
        return patterns

    def correct(self, text: str, language: Optional[str] = None) -> str:
        """
        Исправляет типичные ошибки ASR в тексте.

        Args:
            text: Исходный текст
            language: Язык ("ru", "en" или None для автоопределения)

        Returns:
            Исправленный текст
        """
        if not text:
            return text

        lang = language or self._detect_language(text)
        patterns = self._patterns_ru if lang == "ru" else self._patterns_en

        result = text
        for pattern, replacement in patterns:
            # Сохраняем регистр первой буквы
            def replace_with_case(match):
                original = match.group(0)
                if original[0].isupper():
                    return replacement[0].upper() + replacement[1:]
                return replacement

            result = pattern.sub(replace_with_case, result)

        return result

    def _detect_language(self, text: str) -> str:
        """Определение языка по преобладающему алфавиту."""
        cyrillic = len(re.findall(r"[а-яёА-ЯЁ]", text))
        latin = len(re.findall(r"[a-zA-Z]", text))
        return "ru" if cyrillic > latin else "en"

    def get_corrections_found(self, text: str, language: Optional[str] = None) -> List[Tuple[str, str, int]]:
        """
        Находит все возможные коррекции в тексте.

        Args:
            text: Текст для анализа
            language: Язык текста

        Returns:
            Список кортежей (ошибка, исправление, позиция)
        """
        lang = language or self._detect_language(text)
        patterns = self._patterns_ru if lang == "ru" else self._patterns_en

        found = []
        for pattern, replacement in patterns:
            for match in pattern.finditer(text):
                found.append((match.group(0), replacement, match.start()))

        return sorted(found, key=lambda x: x[2])

    def add_correction(self, error: str, fix: str) -> None:
        """
        Добавляет новое правило коррекции.

        Args:
            error: Ошибочное написание
            fix: Правильное написание
        """
        self._corrections_ru[error] = fix
        self._corrections_en[error] = fix

        # Перекомпилируем паттерны
        self._patterns_ru = self._compile_patterns(self._corrections_ru)
        self._patterns_en = self._compile_patterns(self._corrections_en)

    def get_all_corrections(self, language: str = "ru") -> Dict[str, str]:
        """Возвращает все правила коррекции для языка."""
        return self._corrections_ru.copy() if language == "ru" else self._corrections_en.copy()











