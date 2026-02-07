"""
Фильтр повторений для борьбы с hallucination looping в Whisper.

Whisper иногда "застревает" на одной фразе и повторяет её бесконечно.
Этот модуль детектирует такие повторения и удаляет их.
"""

import re
import logging
from typing import List, Tuple, Optional
from difflib import SequenceMatcher
from collections import deque

logger = logging.getLogger("repetition_filter")



# Известные галлюцинации Whisper (нормализованные, lowercase, без пунктуации)
# Whisper натренирован на YouTube — часто выдаёт эти фразы на тишине/шуме
KNOWN_HALLUCINATIONS = {
    "реклама",
    "конец",
    "продолжение следует",
    "субтитры создал",
    "субтитры сделал",
    "субтитры подготовил",
    "субтитры отредактировал",
    "спасибо за просмотр",
    "подписывайтесь на канал",
    "ставьте лайки",
    "thanks for watching",
    "subscribe",
    "thank you for watching",
    "please subscribe",
    "like and subscribe",
    "music",
    "applause",
    "silence",
    "you",
    "the end",
}


def is_known_hallucination(text: str) -> bool:
    """Проверяет, является ли текст известной галлюцинацией Whisper."""
    normalized = re.sub(r'[^\w\s]', '', text.lower().strip())
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    if not normalized:
        return True
    if normalized in KNOWN_HALLUCINATIONS:
        return True
    # Проверяем вхождение (например "субтитры создал dimaTorzworker")
    for pattern in KNOWN_HALLUCINATIONS:
        if len(pattern) > 5 and normalized.startswith(pattern):
            return True
    return False


class HallucinationDetector:
    """
    Детектор зацикливания (hallucination loop) в реальном времени.

    Отслеживает последние сегменты транскрипции и детектирует
    когда Whisper начинает повторять одну и ту же фразу.

    Использование:
        detector = HallucinationDetector()
        for segment in segments:
            if detector.check(segment.text):
                logger.warning("Зацикливание обнаружено!")
                break
            # ... обработка сегмента
    """

    def __init__(
        self,
        similarity_threshold: float = 0.80,
        max_similar_segments: int = 3,
        history_size: int = 5,
        min_segment_length: int = 3,
    ):
        """
        Args:
            similarity_threshold: Порог схожести текстов (0-1), выше = похожи
            max_similar_segments: Сколько похожих сегментов подряд = зацикливание
            history_size: Сколько последних сегментов хранить для сравнения
            min_segment_length: Минимальная длина сегмента для проверки
        """
        self.similarity_threshold = similarity_threshold
        self.max_similar_segments = max_similar_segments
        self.history_size = history_size
        self.min_segment_length = min_segment_length

        self._history: deque = deque(maxlen=history_size)
        self._similar_count: int = 0
        self._last_similar_text: Optional[str] = None
        self._hallucination_detected: bool = False

    def _normalize(self, text: str) -> str:
        """Нормализует текст для сравнения."""
        # Lowercase
        text = text.lower().strip()
        # Убираем пунктуацию
        text = re.sub(r'[^\w\s]', '', text)
        # Убираем множественные пробелы
        text = re.sub(r'\s+', ' ', text)
        return text

    def _similarity(self, text1: str, text2: str) -> float:
        """Вычисляет схожесть двух текстов (0-1)."""
        if not text1 or not text2:
            return 0.0
        return SequenceMatcher(None, text1, text2).ratio()

    def check(self, segment_text: str) -> bool:
        """
        Проверяет сегмент на повторение или известную галлюцинацию.

        Args:
            segment_text: Текст нового сегмента

        Returns:
            True если сегмент является повторением/галлюцинацией и его нужно ПРОПУСТИТЬ
        """
        # Проверяем блоклист известных галлюцинаций
        if is_known_hallucination(segment_text):
            self._similar_count += 1
            self._last_similar_text = segment_text[:50]
            if self._similar_count >= 2:
                if not self._hallucination_detected:
                    self._hallucination_detected = True
                    logger.warning(
                        f"Известная галлюцинация Whisper: '{self._last_similar_text}'"
                    )
                return True
            return False

        normalized = self._normalize(segment_text)

        # Слишком короткие сегменты пропускаем проверку
        if len(normalized) < self.min_segment_length:
            return False

        # Проверяем схожесть с историей
        is_similar = False
        for prev_text in self._history:
            similarity = self._similarity(normalized, prev_text)
            if similarity >= self.similarity_threshold:
                is_similar = True
                break

        if is_similar:
            self._similar_count += 1
            self._last_similar_text = segment_text[:50]

            if self._similar_count >= self.max_similar_segments:
                if not self._hallucination_detected:
                    self._hallucination_detected = True
                    logger.warning(
                        f"Зацикливание обнаружено! Пропускаем повторяющиеся сегменты. "
                        f"Текст: '{self._last_similar_text}...'"
                    )
                # Возвращаем True = пропустить этот сегмент, но НЕ прерывать
                return True
        else:
            # Новый уникальный контент - сбрасываем состояние
            if self._hallucination_detected:
                logger.info(f"Новый контент после зацикливания: '{segment_text[:50]}...'")
            self._similar_count = 0
            self._last_similar_text = None
            self._hallucination_detected = False
            # Добавляем в историю только уникальные сегменты
            self._history.append(normalized)

        return False

    def reset(self) -> None:
        """Сбрасывает состояние детектора."""
        self._history.clear()
        self._similar_count = 0
        self._last_similar_text = None
        self._hallucination_detected = False

    @property
    def is_hallucinating(self) -> bool:
        """Было ли обнаружено зацикливание."""
        return self._hallucination_detected

    @property
    def similar_count(self) -> int:
        """Текущее количество похожих сегментов подряд."""
        return self._similar_count


def filter_hallucinated_segments(
    segments: List[dict],
    similarity_threshold: float = 0.80,
    max_similar: int = 3,
) -> Tuple[List[dict], bool]:
    """
    Фильтрует повторяющиеся сегменты, сохраняя уникальный контент.

    НЕ прерывает на зацикливании — продолжает и собирает новый контент
    когда он появляется.

    Args:
        segments: Список сегментов [{"start": float, "end": float, "text": str}, ...]
        similarity_threshold: Порог схожести
        max_similar: Максимум похожих сегментов до начала пропуска

    Returns:
        (отфильтрованные_сегменты, было_ли_зацикливание)
    """
    if not segments:
        return segments, False

    detector = HallucinationDetector(
        similarity_threshold=similarity_threshold,
        max_similar_segments=max_similar,
    )

    filtered = []
    hallucination_detected = False
    skipped_count = 0

    for seg in segments:
        text = seg.get("text", "")

        # check() возвращает True если сегмент нужно ПРОПУСТИТЬ
        if detector.check(text):
            hallucination_detected = True
            skipped_count += 1
            continue  # Пропускаем, но НЕ прерываем

        filtered.append(seg)

    # Если были галлюцинации — дополнительно убираем все сегменты из блоклиста
    # (первый сегмент мог проскочить детектор до набора порога)
    if hallucination_detected:
        before_cleanup = len(filtered)
        filtered = [
            seg for seg in filtered
            if not is_known_hallucination(seg.get("text", ""))
        ]
        skipped_count += before_cleanup - len(filtered)
        logger.info(
            f"Фильтрация: пропущено {skipped_count} галлюцинаций/повторов, "
            f"сохранено {len(filtered)} из {len(segments)}"
        )

    return filtered, hallucination_detected


def remove_repetitions(
    text: str,
    max_repeats: int = 2,
    min_phrase_length: int = 10,
    add_marker: bool = False,
) -> str:
    """
    Удаляет повторяющиеся фразы из текста.

    Args:
        text: Исходный текст транскрипции
        max_repeats: Максимальное количество повторений одной фразы (по умолчанию 2)
        min_phrase_length: Минимальная длина фразы для детекции повторений
        add_marker: Добавлять ли маркер [...] если были удалены повторения

    Returns:
        Очищенный текст без повторений
    """
    if not text or len(text) < min_phrase_length * 2:
        return text

    original_text = text

    # Метод 1: Детекция повторяющихся предложений
    text = _remove_repeated_sentences(text, max_repeats, min_phrase_length)

    # Метод 2: Детекция повторяющихся n-грамм (более агрессивный)
    text = _remove_repeated_ngrams(text, max_repeats, min_phrase_length)

    # Метод 3: Детекция циклических паттернов
    text = _remove_cyclic_patterns(text, max_repeats)

    # Финальная очистка
    text = _cleanup_text(text)

    # Логируем если были удаления
    if len(text) < len(original_text) * 0.9:
        removed_chars = len(original_text) - len(text)
        logger.info(f"Удалено {removed_chars} символов повторений")
        if add_marker and removed_chars > 50:
            text = text.rstrip() + " [...]"

    return text


def _remove_repeated_sentences(text: str, max_repeats: int, min_length: int) -> str:
    """Удаляет повторяющиеся предложения."""
    # Разбиваем на предложения
    sentences = re.split(r'(?<=[.!?])\s+', text)

    if len(sentences) < 3:
        return text

    result = []
    repeat_count = {}

    for sentence in sentences:
        # Нормализуем для сравнения
        normalized = sentence.lower().strip()

        if len(normalized) < min_length:
            result.append(sentence)
            continue

        # Считаем повторения
        if normalized in repeat_count:
            repeat_count[normalized] += 1
            if repeat_count[normalized] > max_repeats:
                logger.debug(f"Пропущено повторяющееся предложение: {sentence[:50]}...")
                continue
        else:
            repeat_count[normalized] = 1

        result.append(sentence)

    return " ".join(result)


def _remove_repeated_ngrams(text: str, max_repeats: int, min_length: int) -> str:
    """
    Удаляет повторяющиеся n-граммы (последовательности слов).

    Это ловит случаи типа:
    "Спасибо за внимание. Спасибо за внимание. Спасибо за внимание."
    """
    words = text.split()

    if len(words) < 6:
        return text

    # Проверяем разные размеры n-грамм (от 3 до 15 слов)
    for ngram_size in range(3, min(16, len(words) // 2)):
        i = 0
        new_words = []
        repeat_count = 0

        while i < len(words):
            if i + ngram_size * 2 <= len(words):
                # Берём текущую n-грамму
                current_ngram = " ".join(words[i:i + ngram_size]).lower()
                next_ngram = " ".join(words[i + ngram_size:i + ngram_size * 2]).lower()

                # Если следующая такая же
                if current_ngram == next_ngram and len(current_ngram) >= min_length:
                    # Считаем сколько раз повторяется
                    repeats = 1
                    check_pos = i + ngram_size

                    while check_pos + ngram_size <= len(words):
                        check_ngram = " ".join(words[check_pos:check_pos + ngram_size]).lower()
                        if check_ngram == current_ngram:
                            repeats += 1
                            check_pos += ngram_size
                        else:
                            break

                    if repeats > max_repeats:
                        # Оставляем только max_repeats повторений
                        for _ in range(max_repeats):
                            new_words.extend(words[i:i + ngram_size])
                        logger.debug(f"Удалено {repeats - max_repeats} повторений фразы из {ngram_size} слов")
                        i = check_pos
                        continue

            new_words.append(words[i])
            i += 1

        words = new_words

    return " ".join(words)


def _remove_cyclic_patterns(text: str, max_repeats: int) -> str:
    """
    Удаляет циклические паттерны любой длины.

    Использует алгоритм поиска повторяющейся подстроки.
    """
    if len(text) < 50:
        return text

    # Ищем повторяющиеся паттерны разной длины
    for pattern_len in range(20, min(200, len(text) // 3)):
        pattern = text[-pattern_len:]

        # Считаем сколько раз паттерн повторяется в конце текста
        count = 0
        check_text = text

        while check_text.endswith(pattern):
            count += 1
            check_text = check_text[:-pattern_len]

        if count > max_repeats:
            # Оставляем только max_repeats
            result = check_text + (pattern * max_repeats)
            logger.debug(f"Удалён циклический паттерн длиной {pattern_len}, повторялся {count} раз")
            return result

    return text


def _cleanup_text(text: str) -> str:
    """Финальная очистка текста."""
    # Убираем множественные пробелы
    text = re.sub(r'\s+', ' ', text)

    # Убираем пробелы перед знаками препинания
    text = re.sub(r'\s+([.!?,;:])', r'\1', text)

    return text.strip()


def check_transcription_quality(
    segments: List[dict],
    duration_seconds: float,
    min_words_per_minute: float = 30.0,
) -> Tuple[bool, str]:
    """
    Проверяет качество транскрипции по соотношению слов к длительности.

    Нормальная речь: 100-160 слов/мин (русский).
    Порог 30 слов/мин — очень консервативный, ловит только явные галлюцинации.

    Args:
        segments: Сегменты транскрипции
        duration_seconds: Длительность аудио в секундах
        min_words_per_minute: Минимально ожидаемая скорость речи

    Returns:
        (is_ok, warning_message) — True если качество приемлемое
    """
    if duration_seconds < 10 or not segments:
        return True, ""

    total_words = sum(len(s.get("text", "").split()) for s in segments)
    duration_minutes = duration_seconds / 60.0
    words_per_minute = total_words / duration_minutes if duration_minutes > 0 else 0

    # Проверяем долю галлюцинаций
    hallucination_count = sum(
        1 for s in segments if is_known_hallucination(s.get("text", ""))
    )
    hallucination_ratio = hallucination_count / len(segments) if segments else 0

    if hallucination_ratio > 0.5:
        return False, (
            f"Транскрипция содержит {hallucination_ratio:.0%} галлюцинаций Whisper. "
            f"Попробуйте модель large-v3 или проверьте качество аудио."
        )

    if words_per_minute < min_words_per_minute:
        return False, (
            f"Подозрительно мало слов: {total_words} слов на {duration_minutes:.1f} мин "
            f"({words_per_minute:.0f} сл/мин, норма >100). "
            f"Возможна галлюцинация Whisper. Попробуйте модель large-v3."
        )

    return True, ""


def detect_repetition_ratio(text: str, window_size: int = 100) -> float:
    """
    Оценивает степень повторяемости текста.

    Args:
        text: Текст для анализа
        window_size: Размер окна для анализа

    Returns:
        Коэффициент от 0 до 1, где 1 = много повторений
    """
    if len(text) < window_size * 2:
        return 0.0

    # Разбиваем на окна
    windows = []
    for i in range(0, len(text) - window_size, window_size // 2):
        windows.append(text[i:i + window_size].lower())

    if len(windows) < 2:
        return 0.0

    # Считаем уникальные окна
    unique_windows = set(windows)

    # Чем меньше уникальных окон относительно общего числа, тем больше повторений
    ratio = 1.0 - (len(unique_windows) / len(windows))

    return ratio
