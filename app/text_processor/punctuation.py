"""
Модуль восстановления пунктуации в транскрипциях.

Использует deepmultilingualpunctuation для автоматической расстановки
знаков препинания в тексте без пунктуации.
"""

import re
from typing import Optional

from .config import ProcessingConfig


class PunctuationRestorer:
    """
    Восстанавливает пунктуацию в тексте.

    Использует модель deepmultilingualpunctuation, которая поддерживает:
    - Русский язык
    - Английский язык
    - И другие европейские языки

    Пример использования:
        restorer = PunctuationRestorer()
        text = restorer.restore("привет как дела я хотел спросить")
        # "Привет, как дела? Я хотел спросить."
    """

    def __init__(self, config: Optional[ProcessingConfig] = None):
        self.config = config or ProcessingConfig()
        self._model = None
        self._loaded = False

    def _load_model(self):
        """Ленивая загрузка модели."""
        if self._loaded:
            return

        try:
            from deepmultilingualpunctuation import PunctuationModel
            self._model = PunctuationModel()
            self._loaded = True
        except ImportError:
            # Если библиотека не установлена, используем fallback
            self._model = None
            self._loaded = True

    def restore(self, text: str, language: Optional[str] = None) -> str:
        """
        Восстанавливает пунктуацию в тексте.

        Args:
            text: Текст без пунктуации (или с частичной)
            language: Язык текста (не используется напрямую, модель мультиязычная)

        Returns:
            Текст с восстановленной пунктуацией
        """
        if not text or not text.strip():
            return text

        self._load_model()

        if self._model is None:
            # Fallback: простое восстановление на основе правил
            return self._fallback_restore(text, language)

        try:
            # Разбиваем на части, если текст слишком длинный
            # deepmultilingualpunctuation работает лучше с короткими текстами
            max_length = 500
            if len(text) <= max_length:
                return self._model.restore_punctuation(text)

            # Разбиваем на предложения или по длине
            parts = self._split_text(text, max_length)
            restored_parts = []

            for part in parts:
                if part.strip():
                    restored = self._model.restore_punctuation(part)
                    restored_parts.append(restored)

            return " ".join(restored_parts)

        except Exception:
            # При любой ошибке — fallback
            return self._fallback_restore(text, language)

    def _split_text(self, text: str, max_length: int) -> list:
        """
        Разбивает текст на части для обработки.
        Старается разбивать по границам предложений.
        """
        # Если текст короче лимита
        if len(text) <= max_length:
            return [text]

        parts = []
        current = ""

        # Пробуем разбить по потенциальным границам предложений
        # (после слов, заканчивающихся на определённые паттерны)
        words = text.split()

        for word in words:
            if len(current) + len(word) + 1 > max_length:
                if current:
                    parts.append(current.strip())
                current = word
            else:
                current = f"{current} {word}" if current else word

        if current:
            parts.append(current.strip())

        return parts

    def _fallback_restore(self, text: str, language: Optional[str] = None) -> str:
        """
        Простое восстановление пунктуации на основе правил.
        Используется если deepmultilingualpunctuation недоступен.
        """
        lang = language or self._detect_language(text)

        result = text.strip()

        # Капитализация первой буквы
        if result and result[0].islower():
            result = result[0].upper() + result[1:]

        # Добавляем точку в конце, если нет знака препинания
        if result and result[-1] not in ".!?":
            result += "."

        # Простые правила для русского языка
        if lang == "ru":
            result = self._apply_russian_rules(result)
        else:
            result = self._apply_english_rules(result)

        return result

    def _apply_russian_rules(self, text: str) -> str:
        """Применяет расширенные правила пунктуации для русского языка."""
        result = text

        # 1. Запятая перед союзами (противительные и подчинительные)
        conjunctions = [
            "но", "однако", "зато", "а", "хотя", "если", "когда",
            "потому что", "так как", "чтобы", "будто", "словно",
            "который", "которая", "которое", "которые"
        ]
        for conj in conjunctions:
            # Добавляем запятую перед союзом, если её нет
            pattern = rf"(\w)\s+({conj})\b"
            result = re.sub(pattern, rf"\1, \2", result, flags=re.IGNORECASE)

        # 2. Вводные слова и конструкции (выделение запятыми)
        intro_words = [
            "конечно", "кажется", "вероятно", "может быть", "пожалуй",
            "наверное", "впрочем", "значит", "следовательно", "итак",
            "напротив", "наоборот", "во-первых", "во-вторых", "в-третьих",
            "кстати", "между прочим", "по сути", "в общем"
        ]
        for word in intro_words:
            # В начале предложения
            result = re.sub(rf"^({word})\s+", rf"\1, ", result, flags=re.IGNORECASE)
            # В середине предложения
            result = re.sub(rf"\s+({word})\s+", rf", \1, ", result, flags=re.IGNORECASE)

        # 3. Вопросительные слова в начале → вопрос в конце
        question_starters = ["как", "что", "где", "когда", "почему", "зачем", "кто", "сколько", "какой"]
        for starter in question_starters:
            if result.lower().startswith(starter + " "):
                # Заменяем точку на вопросительный знак
                if result.endswith("."):
                    result = result[:-1] + "?"
                break

        # 4. Очистка и нормализация
        # Убираем пробелы перед знаками
        result = re.sub(r"\s+([,.!?;:])", r"\1", result)
        # Убираем двойные запятые (могли появиться от вводных слов)
        result = re.sub(r",\s*,", ",", result)
        # Убираем запятую перед точкой/вопросом
        result = re.sub(r",\s*([.!?])", r"\1", result)
        # Убираем двойные пробелы
        result = re.sub(r"\s+", " ", result)

        return result.strip()

    def _apply_english_rules(self, text: str) -> str:
        """Применяет простые правила пунктуации для английского языка."""
        result = text

        # Запятая перед координирующими союзами
        conjunctions = ["but", "however", "although", "yet", "so", "because", "if", "when"]
        for conj in conjunctions:
            pattern = rf"(\w)\s+({conj})\b"
            result = re.sub(pattern, rf"\1, \2", result, flags=re.IGNORECASE)

        # Вопросительные слова
        question_starters = ["what", "where", "when", "why", "how", "who", "which", "whose"]
        for starter in question_starters:
            if result.lower().startswith(starter + " "):
                if result.endswith("."):
                    result = result[:-1] + "?"
                break

        # Убираем двойные знаки
        result = re.sub(r"[,]+", ",", result)
        result = re.sub(r"[.]+", ".", result)
        result = re.sub(r"\s+([,.])", r"\1", result)

        return result

    def _detect_language(self, text: str) -> str:
        """Определение языка по преобладающему алфавиту."""
        cyrillic = len(re.findall(r"[а-яёА-ЯЁ]", text))
        latin = len(re.findall(r"[a-zA-Z]", text))
        return "ru" if cyrillic > latin else "en"

    @property
    def is_available(self) -> bool:
        """Проверяет, доступна ли ML-модель."""
        self._load_model()
        return self._model is not None

    def restore_with_confidence(self, text: str) -> tuple:
        """
        Восстанавливает пунктуацию и возвращает уверенность.

        Returns:
            Tuple[str, float]: (текст с пунктуацией, уверенность 0-1)
        """
        self._load_model()

        if self._model is None:
            # Fallback с низкой уверенностью
            return self._fallback_restore(text), 0.3

        try:
            restored = self._model.restore_punctuation(text)
            # Оцениваем уверенность по количеству добавленных знаков
            original_punct = len(re.findall(r"[.,!?;:]", text))
            restored_punct = len(re.findall(r"[.,!?;:]", restored))
            added = restored_punct - original_punct

            # Если добавили много знаков — уверенность выше
            confidence = min(0.95, 0.7 + added * 0.05)
            return restored, confidence
        except Exception:
            return self._fallback_restore(text), 0.3








