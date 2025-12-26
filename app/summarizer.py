"""
Модуль суммаризации транскрипций с помощью локальной LLM (Qwen3-1.7B).

Использует двухэтапную обработку для длинных текстов:
1. Извлечение фактов из чанков
2. Агрегация в финальное саммари

Особенности:
- Гарантия ответа на русском языке (retry при английском)
- Валидация на галлюцинации (проверка чисел/дат)
- Оптимизация для маленьких моделей (1-3B параметров)
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import time
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Отдельный логгер для ответов LLM
llm_logger = logging.getLogger("mindtype.llm")
llm_logger.setLevel(logging.DEBUG)

def _setup_llm_logging():
    """Настройка детального лога для LLM."""
    try:
        log_dir = Path.home() / ".cache" / "mindtype" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "summarizer.log"

        handler = logging.FileHandler(log_file, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        llm_logger.addHandler(handler)
    except:
        pass

_setup_llm_logging()

# =============================================================================
# ПРОМПТЫ
# =============================================================================

SYSTEM_PROMPT = """Ты — PM-ассистент. Пиши строго на русском.
Твоя задача: выписать факты, числа и задачи из текста.

ПРАВИЛА:
1. Только русский язык (английский запрещён).
2. Все числа, даты и сроки из текста должны быть в ответе.
3. Не выдумывай того, чего нет в тексте.
4. Техтермины не переводи: ТЗ, ТЭП, МАФ, ДОУ, ЭП, стадия Р, стилобат.
"""

EXTRACTION_PROMPT = """Текст для анализа:
\"\"\"
{chunk_text}
\"\"\"

Выпиши все факты из текста выше на русском языке.

## 1. Числа, даты, сроки
- [значение] — [контекст]

## 2. Решения и договорённости
- ...

## 3. Задачи
- [Кто] → [что сделает] (срок)

## 4. Риски и вопросы
- ...

ВАЖНО: Пиши только правду из текста. Если информации для раздела нет, пиши "—"."""

AGGREGATION_PROMPT = """Объедини факты из {n_chunks} частей в одно итоговое PM-саммари.

ФАКТЫ:
\"\"\"
{extracted_facts}
\"\"\"

Итоговое саммари на русском языке:

## 1) Все числа/даты/сроки
- [значение] — [контекст]

## 2) Решения и договорённости
- ...

## 3) Ждём от заказчика
- ...

## 4) Ждём от исполнителя
- ...

## 5) Риски и вопросы
- ...

## 6) Следующие шаги
| Действие | Ответственный | Срок |
|----------|---------------|------|
| ... | ... | ... |

ВАЖНО: Не теряй ни одного числа или даты из списка выше."""

SHORT_PROMPT = """ТРАНСКРИПЦИЯ:
\"\"\"
{transcript}
\"\"\"

---

Сделай PM-саммари на русском языке. Заполни ВСЕ разделы ниже. Если раздел пустой — напиши "—".

## 1) Все даты/числа/сроки
Выпиши КАЖДУЮ дату, число, срок, сумму из текста:
- [дата/число] — [контекст из текста]

## 2) Решения и договорённости
Что решили, согласовали, утвердили:
- ...

## 3) Ждём от заказчика
Что должен сделать/прислать заказчик:
- ...

## 4) Ждём от исполнителя
Что должен сделать исполнитель:
- ...

## 5) Риски и открытые вопросы
Что не решено, неясно, может пойти не так:
- ...

## 6) Следующие шаги
| Действие | Ответственный | Срок |
|----------|---------------|------|
| ... | ... | ... |

ВАЖНО: Заполни ВСЕ 6 разделов. Отвечай только на русском."""

# =============================================================================
# ПРОМПТЫ ДЛЯ ДИАЛОГОВ (С РАЗМЕТКОЙ СПИКЕРОВ)
# =============================================================================

DIALOG_SYSTEM_PROMPT = """Ты — PM-ассистент. Пиши строго на русском.
В тексте есть SPEAKER_XX. Привязывай факты к спикерам.

ПРАВИЛА:
1. Только русский язык.
2. Не выдумывай факты.
3. Сохраняй SPEAKER_XX в ответах.
"""

DIALOG_EXTRACTION_PROMPT = """ТРАНСКРИПЦИЯ:
\"\"\"
{chunk_text}
\"\"\"

Выпиши факты по спикерам на русском языке.

## Участники
- SPEAKER_XX: [роль]

## Числа и даты
- [SPEAKER_XX]: [значение] — [контекст]

## Решения и задачи
- [SPEAKER_XX] → [что сделал/сделает]

## Вопросы
- [SPEAKER_XX]: ..."""

DIALOG_AGGREGATION_PROMPT = """Объедини факты из {n_chunks} частей встречи.

ФАКТЫ:
\"\"\"
{extracted_facts}
\"\"\"

Итоговый протокол на русском:

## Участники встречи
| Спикер | Роль | Кратко |
|--------|------|--------|
| SPEAKER_XX | [роль] | [тема] |

## 1) Все числа/даты/сроки
- [SPEAKER_XX]: [значение] — [контекст]

## 2) Решения и задачи
- [SPEAKER_XX]: ...

## 3) Риски и вопросы
- [SPEAKER_XX]: ...

## 4) Следующие шаги
| Действие | Ответственный | Срок |
|----------|---------------|------|
| ... | SPEAKER_XX | ... |"""

DIALOG_SHORT_PROMPT = """ТРАНСКРИПЦИЯ ВСТРЕЧИ:
\"\"\"
{transcript}
\"\"\"

---

Сделай протокол встречи на русском языке. Заполни ВСЕ разделы. Если раздел пустой — напиши "—".

## Участники встречи
Определи роль каждого спикера по контексту:
| Спикер | Роль |
|--------|------|
| SPEAKER_XX | [заказчик/исполнитель/эксперт/неизвестно] |

## 1) Все даты/числа/сроки
Выпиши с указанием кто озвучил:
- [SPEAKER_XX]: [дата/число] — [контекст]

## 2) Решения и договорённости
Что решили, согласовали, утвердили:
- [SPEAKER_XX]: ...

## 3) Задачи по участникам
### SPEAKER_00:
- [задача] (срок)

### SPEAKER_01:
- [задача] (срок)

## 4) Риски и открытые вопросы
- [SPEAKER_XX]: ...

## 5) Следующие шаги
| Действие | Ответственный | Срок |
|----------|---------------|------|
| ... | SPEAKER_XX | ... |

ВАЖНО: Заполни ВСЕ 5 разделов. Указывай ID спикеров. Отвечай только на русском."""

# =============================================================================
# СТАНДАРТНЫЕ ПРОМПТЫ (БЕЗ РАЗМЕТКИ СПИКЕРОВ)
# =============================================================================

FULL_PROMPT_WITH_EXAMPLE = """Ты — PM-ассистент. Делаешь выжимки из транскрипций на русском языке.

ПРАВИЛА:
- Только русский язык
- Не выдумывай факты
- Все числа/даты из текста → в раздел "Числа и даты"
- Следуй формату точно

═══════════════════════════════════════
ПРИМЕР
═══════════════════════════════════════

ТРАНСКРИПЦИЯ:
\"\"\"
Иван: Дедлайн 15 марта, бюджет 500 тысяч рублей.
Мария: Согласовано. Геодезию пришлём до 20 февраля.
Иван: Хорошо. По дренажу пока не решили, надо уточнить.
\"\"\"

ОТВЕТ:

## 1) Числа и даты
- **15 марта** — дедлайн проекта
- **500 000 руб.** — бюджет
- **до 20 февраля** — срок предоставления геодезии

## 2) Решения
- Дедлайн и бюджет согласованы

## 3) Ждём от заказчика
- Геодезия — до 20 февраля

## 4) Ждём от исполнителя
- (не указано)

## 5) Риски и вопросы
- Вопрос по дренажу не решён

## 6) Следующие шаги
| Действие | Владелец | Срок |
|---|---|---|
| Прислать геодезию | Заказчик (Мария) | до 20 февраля |
| Уточнить по дренажу | Исполнитель (Иван) | не указан |

═══════════════════════════════════════
ТВОЯ ЗАДАЧА
═══════════════════════════════════════

ТРАНСКРИПЦИЯ:
\"\"\"
{transcript}
\"\"\"

Сделай PM-саммари по формату выше. Отвечай на русском."""


# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

@dataclass
class SummarizerConfig:
    """Конфигурация суммаризатора."""
    # Провайдер: "local" или "openrouter"
    provider: str = "local"

    # OpenRouter настройки
    openrouter_api_key: str = ""
    openrouter_model: str = ""  # например "anthropic/claude-3-haiku"
    openrouter_reasoning: bool = False  # Включить reasoning mode
    openrouter_reasoning_effort: str = "medium"  # low / medium / high

    # Локальная модель (unsloth - надёжное зеркало)
    model_repo: str = "unsloth/Qwen3-1.7B-GGUF"
    model_file: str = "Qwen3-1.7B-Q8_0.gguf"  # ~1.8 GB

    # Параметры инференса
    n_ctx: int = 4096
    n_threads: int = 0  # 0 = auto (физические ядра)
    n_gpu_layers: int = -1  # -1 = все на GPU если доступен
    temperature: float = 0.4  # Более стабильные ответы для PM
    top_p: float = 0.9
    max_tokens: int = 8096  # Большой лимит для длинных саммари и reasoning
    repeat_penalty: float = 1.1
    enable_thinking: bool = True  # Включить режим размышлений Qwen3

    # Чанкинг
    max_chunk_tokens: int = 400  # ~270 слов — модель видит весь чанк
    overlap_tokens: int = 100   # больше контекста на границах
    short_threshold: int = 500  # раньше включать чанкинг

    # Retry
    max_language_retries: int = 3
    max_format_retries: int = 2

    # Кэширование
    cache_enabled: bool = True
    cache_size: int = 100

    # Кастомные промпты (None = дефолтные)
    custom_prompts: Optional[Dict[str, str]] = None


# =============================================================================
# ЧАНКЕР
# =============================================================================

@dataclass
class Chunk:
    """Чанк транскрипции."""
    id: int
    text: str
    token_count: int


class TranscriptChunker:
    """
    Разбивает транскрипцию на чанки для обработки LLM.

    Особенности:
    - Не режет посередине реплики спикера
    - Добавляет overlap для сохранения контекста
    - Учитывает специфику русского языка (~1.5 токена на слово)
    """

    def __init__(
        self,
        max_tokens: int = 700,
        overlap_tokens: int = 50,
    ):
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    def estimate_tokens(self, text: str) -> int:
        """
        Оценка количества токенов.
        Для русского языка: ~1.5 токена на слово.
        """
        words = len(text.split())
        return int(words * 1.5)

    def chunk(self, text: str) -> List[Chunk]:
        """
        Разбить текст на чанки.

        Args:
            text: Полный текст транскрипции

        Returns:
            Список чанков
        """
        # Паттерн для разбиения по репликам спикеров
        # Формат: "Имя:" или "Имя Фамилия:" в начале строки
        speaker_pattern = r'(?=(?:[А-ЯЁA-Z][а-яёa-z]+(?:\s+[А-ЯЁA-Z][а-яёa-z]+)?)\s*:)'
        segments = re.split(speaker_pattern, text)
        segments = [s.strip() for s in segments if s.strip()]

        # Если нет явных спикеров — разбиваем по предложениям
        if len(segments) <= 1:
            segments = self._split_by_sentences(text)

        chunks = []
        current_chunk: List[str] = []
        current_tokens = 0
        chunk_id = 0

        for segment in segments:
            segment_tokens = self.estimate_tokens(segment)

            # Если сегмент сам по себе слишком большой
            if segment_tokens > self.max_tokens:
                # Сохранить текущий чанк
                if current_chunk:
                    chunks.append(Chunk(
                        id=chunk_id,
                        text=" ".join(current_chunk),
                        token_count=current_tokens
                    ))
                    chunk_id += 1
                    current_chunk = []
                    current_tokens = 0

                # Разбить большой сегмент по предложениям
                sentences = self._split_by_sentences(segment)
                for sentence in sentences:
                    sent_tokens = self.estimate_tokens(sentence)
                    if current_tokens + sent_tokens > self.max_tokens:
                        if current_chunk:
                            chunks.append(Chunk(
                                id=chunk_id,
                                text=" ".join(current_chunk),
                                token_count=current_tokens
                            ))
                            chunk_id += 1
                        current_chunk = [sentence]
                        current_tokens = sent_tokens
                    else:
                        current_chunk.append(sentence)
                        current_tokens += sent_tokens

            # Если добавление превысит лимит
            elif current_tokens + segment_tokens > self.max_tokens:
                # Сохранить текущий чанк
                chunks.append(Chunk(
                    id=chunk_id,
                    text=" ".join(current_chunk),
                    token_count=current_tokens
                ))
                chunk_id += 1

                # Начать новый с overlap
                overlap_text = current_chunk[-1] if current_chunk else ""
                current_chunk = [overlap_text, segment] if overlap_text else [segment]
                current_tokens = self.estimate_tokens(" ".join(current_chunk))

            else:
                current_chunk.append(segment)
                current_tokens += segment_tokens

        # Последний чанк
        if current_chunk:
            chunks.append(Chunk(
                id=chunk_id,
                text=" ".join(current_chunk),
                token_count=current_tokens
            ))

        return chunks

    def _split_by_sentences(self, text: str) -> List[str]:
        """Разбить текст по предложениям."""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]


# =============================================================================
# ВАЛИДАЦИЯ
# =============================================================================

def detect_language(text: str) -> str:
    """
    Определить язык по преобладающему алфавиту.

    Returns:
        "ru" если кириллицы больше, иначе "en"
    """
    cyrillic = len(re.findall(r'[а-яёА-ЯЁ]', text))
    latin = len(re.findall(r'[a-zA-Z]', text))
    return "ru" if cyrillic > latin else "en"


def extract_numbers(text: str) -> set:
    """Извлечь все числа из текста."""
    # Числа: целые, дробные, с пробелами (1 000 000)
    numbers = re.findall(r'\d[\d\s]*\d|\d', text)
    # Нормализуем — убираем пробелы
    return {re.sub(r'\s+', '', n) for n in numbers}


def validate_facts(response: str, original_text: str) -> Dict:
    """
    Проверить, что извлечённые факты есть в оригинале.

    Returns:
        Словарь с результатами валидации
    """
    response_numbers = extract_numbers(response)
    original_numbers = extract_numbers(original_text)

    hallucinated = response_numbers - original_numbers
    # Исключаем мелкие числа (1, 2, 3...) — они могут быть нумерацией
    hallucinated = {n for n in hallucinated if len(n) > 1 or int(n) > 6}

    missing = original_numbers - response_numbers
    # Исключаем мелкие числа из пропущенных тоже
    missing = {n for n in missing if len(n) > 1}

    return {
        "valid": len(hallucinated) == 0,
        "hallucinated": hallucinated,
        "missing": missing,
        "response_numbers": response_numbers,
        "original_numbers": original_numbers,
    }


def validate_format(response: str, required_sections: List[str]) -> bool:
    """Проверить наличие обязательных разделов."""
    for section in required_sections:
        if section not in response:
            return False
    return True


# =============================================================================
# МЕТРИКИ
# =============================================================================

@dataclass
class SummarizationMetrics:
    """Метрики процесса суммаризации."""
    input_tokens: int = 0
    input_chunks: int = 0
    llm_calls: int = 0
    total_generation_tokens: int = 0
    processing_time_sec: float = 0.0
    language_retries: int = 0
    format_retries: int = 0
    hallucinations_detected: int = 0
    output_tokens: int = 0
    facts_per_chunk: List[int] = field(default_factory=list)  # сколько фактов в каждом чанке
    numbers_extracted: int = 0  # сколько чисел/дат извлечено

    def to_dict(self) -> dict:
        return {
            "input": {
                "tokens": self.input_tokens,
                "chunks": self.input_chunks,
            },
            "processing": {
                "llm_calls": self.llm_calls,
                "generation_tokens": self.total_generation_tokens,
                "time_sec": round(self.processing_time_sec, 2),
                "tokens_per_sec": round(
                    self.total_generation_tokens / max(self.processing_time_sec, 0.1),
                    1
                ),
            },
            "quality": {
                "language_retries": self.language_retries,
                "format_retries": self.format_retries,
                "hallucinations": self.hallucinations_detected,
            },
            "extraction": {
                "facts_per_chunk": self.facts_per_chunk,
                "total_facts": sum(self.facts_per_chunk),
                "numbers_extracted": self.numbers_extracted,
            },
            "output_tokens": self.output_tokens,
        }


# =============================================================================
# КЭШИРОВАНИЕ
# =============================================================================

def hash_text(text: str) -> str:
    """Хэш текста для кэширования."""
    return hashlib.md5(text.encode()).hexdigest()[:16]


class ResponseCache:
    """Простой LRU-кэш для ответов LLM."""

    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self._cache: Dict[str, str] = {}

    def get(self, prompt: str) -> Optional[str]:
        key = hash_text(prompt)
        return self._cache.get(key)

    def set(self, prompt: str, response: str) -> None:
        key = hash_text(prompt)

        # LRU: удалить старые, если переполнение
        if len(self._cache) >= self.max_size:
            oldest_key = next(iter(self._cache))
            del self._cache[oldest_key]

        self._cache[key] = response

    def clear(self) -> None:
        self._cache.clear()


# =============================================================================
# СУММАРИЗАТОР
# =============================================================================

# Callback для прогресса
SummaryProgressCallback = Callable[[str, int, int], None]  # (status, current, total)
ThinkingCallback = Callable[[str], None]  # (thinking_text) - для стриминга размышлений


class Summarizer:
    """
    Суммаризатор транскрипций на базе Qwen3.

    Использует двухэтапную обработку:
    1. Извлечение фактов из чанков
    2. Агрегация в финальное саммари
    """

    def __init__(self, config: Optional[SummarizerConfig] = None):
        self.config = config or SummarizerConfig()
        self.model = None
        self._model_loaded = False
        self._cache = ResponseCache(self.config.cache_size) if self.config.cache_enabled else None
        self._chunker = TranscriptChunker(
            max_tokens=self.config.max_chunk_tokens,
            overlap_tokens=self.config.overlap_tokens,
        )
        self._metrics = SummarizationMetrics()

    def _get_prompt(self, key: str, is_dialog: bool = False) -> str:
        """
        Получить промпт с учётом кастомизации и формата диалога.

        Args:
            key: Ключ промпта (system, short, extraction, aggregation)
            is_dialog: True если текст содержит разметку спикеров
        """
        # Стандартные промпты
        defaults = {
            "system": SYSTEM_PROMPT,
            "short": SHORT_PROMPT,
            "extraction": EXTRACTION_PROMPT,
            "aggregation": AGGREGATION_PROMPT,
        }

        # Промпты для диалогов со спикерами
        dialog_prompts = {
            "system": DIALOG_SYSTEM_PROMPT,
            "short": DIALOG_SHORT_PROMPT,
            "extraction": DIALOG_EXTRACTION_PROMPT,
            "aggregation": DIALOG_AGGREGATION_PROMPT,
        }

        # Кастомные промпты имеют приоритет
        if self.config.custom_prompts and key in self.config.custom_prompts:
            return self.config.custom_prompts[key]

        # Выбираем промпт в зависимости от формата
        if is_dialog:
            return dialog_prompts.get(key, defaults.get(key, ""))
        return defaults.get(key, "")

    def _is_dialog_format(self, text: str) -> bool:
        """
        Проверяет, содержит ли текст разметку спикеров.

        Returns:
            True если найдены метки SPEAKER_XX:
        """
        return bool(re.search(r'SPEAKER_\d+:', text))

    @property
    def is_loaded(self) -> bool:
        """Проверить, загружена ли модель."""
        if self.config.provider == "openrouter":
            return self._model_loaded  # Для OpenRouter модель не нужна
        return self._model_loaded and self.model is not None

    def load_model(
        self,
        models_dir: Optional[Path] = None,
        progress_callback: Optional[SummaryProgressCallback] = None,
    ) -> None:
        """
        Загрузить модель (локальную Qwen3 или проверить OpenRouter).

        Args:
            models_dir: Директория для моделей (по умолчанию ~/.cache/mindtype)
            progress_callback: Callback для отображения прогресса
        """
        if self._model_loaded:
            return

        # Для OpenRouter не нужна локальная модель
        if self.config.provider == "openrouter":
            if progress_callback:
                progress_callback("Проверка OpenRouter API...", 50, 100)

            # Проверяем ключ
            if not self.config.openrouter_api_key:
                raise RuntimeError("OpenRouter API ключ не задан")
            if not self.config.openrouter_model:
                raise RuntimeError("OpenRouter модель не выбрана")

            # Проверяем валидность ключа
            from .openrouter import OpenRouterClient, OpenRouterAuthError
            try:
                client = OpenRouterClient(self.config.openrouter_api_key)
                client.validate_api_key()
            except OpenRouterAuthError as e:
                raise RuntimeError(f"Неверный API ключ OpenRouter: {e}")

            self._model_loaded = True
            if progress_callback:
                progress_callback("OpenRouter готов", 100, 100)
            return

        try:
            from llama_cpp import Llama
        except ImportError:
            raise RuntimeError(
                "llama-cpp-python не установлен. "
                "Установите: pip install llama-cpp-python"
            )

        if progress_callback:
            progress_callback("Загрузка модели Qwen3...", 0, 100)

        # Определяем директорию для моделей
        if models_dir is None:
            models_dir = Path.home() / ".cache" / "mindtype" / "summarizer"
        models_dir.mkdir(parents=True, exist_ok=True)

        # Определяем количество потоков
        n_threads = self.config.n_threads
        if n_threads == 0:
            try:
                import psutil
                n_threads = psutil.cpu_count(logical=False) or 4
            except ImportError:
                import os as os_module
                n_threads = max(1, (os_module.cpu_count() or 4) // 2)

        if progress_callback:
            progress_callback("Инициализация LLM...", 30, 100)

        # Сначала проверяем локальный файл
        local_path = models_dir / self.config.model_file

        if local_path.exists():
            # Загружаем из локального файла
            if progress_callback:
                progress_callback("Загрузка модели из кэша...", 50, 100)

            self.model = Llama(
                model_path=str(local_path),
                n_ctx=self.config.n_ctx,
                n_threads=n_threads,
                n_gpu_layers=self.config.n_gpu_layers,
                verbose=False,
                chat_format="chatml",  # Qwen использует ChatML
            )
        else:
            # Пробуем загрузить из HuggingFace (с поддержкой зеркала для России/Китая)
            import os
            if not os.environ.get("HF_ENDPOINT"):
                os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"

            try:
                self.model = Llama.from_pretrained(
                    repo_id=self.config.model_repo,
                    filename=self.config.model_file,
                    n_ctx=self.config.n_ctx,
                    n_threads=n_threads,
                    n_gpu_layers=self.config.n_gpu_layers,
                    verbose=False,
                    chat_format="chatml",
                )
            except Exception as e:
                raise RuntimeError(
                    f"Не удалось загрузить модель: {e}\n\n"
                    f"Скачайте вручную и положите в:\n{local_path}"
                )

        self._model_loaded = True

        if progress_callback:
            progress_callback("Модель загружена", 100, 100)

    def unload_model(self) -> None:
        """Выгрузить модель из памяти."""
        if self.model:
            del self.model
            self.model = None
        self._model_loaded = False
        if self._cache:
            self._cache.clear()

    def _generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        thinking_callback: Optional[ThinkingCallback] = None,
    ) -> str:
        """
        Сгенерировать ответ от LLM с поддержкой стриминга thinking.

        Args:
            prompt: Пользовательский промпт
            system_prompt: Системный промпт (None = из конфига/кастомный)
            max_tokens: Максимум токенов (по умолчанию из конфига)
            thinking_callback: Callback для стриминга размышлений

        Returns:
            Сгенерированный текст
        """
        # Выбор провайдера
        if self.config.provider == "openrouter":
            return self._generate_openrouter(prompt, system_prompt, max_tokens, thinking_callback)

        return self._generate_local(prompt, system_prompt, max_tokens, thinking_callback)

    def _generate_openrouter(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        thinking_callback: Optional[ThinkingCallback] = None,
    ) -> str:
        """Генерация через OpenRouter API."""
        from .openrouter import OpenRouterClient, OpenRouterError

        if not self.config.openrouter_api_key:
            raise RuntimeError("OpenRouter API ключ не задан")
        if not self.config.openrouter_model:
            raise RuntimeError("OpenRouter модель не выбрана")

        # Используем кастомный или дефолтный системный промпт
        system_prompt = system_prompt or self._get_prompt("system")

        # Проверяем кэш
        cache_key = f"openrouter:{self.config.openrouter_model}:{system_prompt}|||{prompt}"
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached:
                return cached

        # Создаём клиент
        client = OpenRouterClient(self.config.openrouter_api_key)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        try:
            if thinking_callback:
                # Стриминг с колбэком
                result = client.chat_completion(
                    messages=messages,
                    model=self.config.openrouter_model,
                    max_tokens=max_tokens or self.config.max_tokens,
                    temperature=self.config.temperature,
                    stream=True,
                    on_token=thinking_callback,
                    reasoning=self.config.openrouter_reasoning,
                    reasoning_effort=self.config.openrouter_reasoning_effort,
                )
            else:
                result = client.chat_completion(
                    messages=messages,
                    model=self.config.openrouter_model,
                    max_tokens=max_tokens or self.config.max_tokens,
                    temperature=self.config.temperature,
                    stream=False,
                    reasoning=self.config.openrouter_reasoning,
                    reasoning_effort=self.config.openrouter_reasoning_effort,
                )
        except OpenRouterError as e:
            logger.error(f"OpenRouter ошибка: {e}")
            raise RuntimeError(f"Ошибка OpenRouter: {e}")

        # Обновляем метрики
        self._metrics.llm_calls += 1

        # Сохраняем в кэш
        if self._cache:
            self._cache.set(cache_key, result)

        return result.strip()

    def _generate_local(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        max_tokens: Optional[int] = None,
        thinking_callback: Optional[ThinkingCallback] = None,
    ) -> str:
        """Генерация через локальную модель Qwen3."""
        if not self.is_loaded:
            raise RuntimeError("Модель не загружена")

        # Используем кастомный или дефолтный системный промпт
        system_prompt = system_prompt or self._get_prompt("system")

        # Проверяем кэш
        cache_key = f"{system_prompt}|||{prompt}"
        if self._cache:
            cached = self._cache.get(cache_key)
            if cached:
                return cached

        # Добавляем /think или /no_think в зависимости от настройки
        if self.config.enable_thinking:
            # Thinking mode: модель сначала размышляет в <think></think>, потом отвечает
            user_prompt = prompt  # Qwen3 по умолчанию использует thinking
        else:
            # Быстрый режим без размышлений
            user_prompt = f"/no_think\n{prompt}"

        # Используем chat completion для Qwen3
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        # Если есть thinking_callback - используем стриминг
        if thinking_callback and self.config.enable_thinking:
            result = self._generate_streaming(messages, max_tokens, thinking_callback)
        else:
            response = self.model.create_chat_completion(
                messages=messages,
                max_tokens=max_tokens or self.config.max_tokens,
                temperature=self.config.temperature,
                top_p=self.config.top_p,
                repeat_penalty=self.config.repeat_penalty,
            )
            result = response["choices"][0]["message"]["content"].strip()

            # Логируем ответ
            llm_logger.debug(f"PROMPT: {prompt[:200]}...")
            llm_logger.debug(f"RESPONSE: {result}")

            # Обновляем метрики
            if "usage" in response:
                self._metrics.total_generation_tokens += response["usage"].get("completion_tokens", 0)

        # Если был thinking mode, извлекаем ответ после </think>
        if self.config.enable_thinking:
            if "</think>" in result:
                # Формат: <think>размышления</think>ответ
                parts = result.split("</think>", 1)
                if len(parts) > 1:
                    result = parts[1].strip()
            elif "<think>" in result:
                # Если тег не закрыт, значит ответ пуст или в процессе
                logger.warning("LLM не закрыла тег </think>, ответ может быть пустым.")
                # Попробуем взять всё, что после <think> если там есть текст без тегов
                result = re.sub(r'<think>.*?</think>', '', result, flags=re.DOTALL).strip()
                if not result and "<think>" in result:
                     # Если всё еще пусто, значит LLM только размышляла
                     raise ValueError("LLM выдала только размышления без итогового текста.")

        # Очистка от Markdown мусора (иногда модель пишет ```markdown или подобное в начале)
        result = re.sub(r'^```[a-zA-Z]*\n', '', result)
        result = re.sub(r'\n```$', '', result)
        result = result.strip()

        # Если результат пуст или слишком короткий
        if not result:
            raise ValueError("LLM вернула пустой результат.")

        if len(result) < 50:
            # Проверяем, не является ли это просто заголовками без содержания
            clean_content = re.sub(r'#.*?\n', '', result).strip()
            if len(clean_content) < 10:
                logger.error(f"LLM вернула слишком короткий ответ ({len(result)} симв): {result}")
                raise ValueError("LLM вернула слишком короткий или неполный ответ.")

        # Обновляем метрики
        self._metrics.llm_calls += 1

        # Сохраняем в кэш
        if self._cache:
            self._cache.set(cache_key, result)

        return result

    def _generate_streaming(
        self,
        messages: List[dict],
        max_tokens: Optional[int],
        thinking_callback: ThinkingCallback,
    ) -> str:
        """Генерация со стримингом для отображения thinking."""
        full_response = ""
        in_thinking = False
        thinking_buffer = ""

        for chunk in self.model.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens or self.config.max_tokens,
            temperature=self.config.temperature,
            top_p=self.config.top_p,
            repeat_penalty=self.config.repeat_penalty,
            stream=True,
        ):
            if "choices" in chunk and len(chunk["choices"]) > 0:
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content", "")

                if content:
                    full_response += content

                    # Отслеживаем thinking блок
                    if "<think>" in full_response and not in_thinking:
                        in_thinking = True
                        thinking_callback("[Размышляю...]\n")

                    if in_thinking and "</think>" not in full_response:
                        # Стримим thinking content (убираем тег <think>)
                        clean_content = content.replace("<think>", "")
                        if clean_content:
                            thinking_callback(clean_content)
                    elif "</think>" in full_response and in_thinking:
                        in_thinking = False
                        thinking_callback("\n[Готово]\n")

        self._metrics.total_generation_tokens += len(full_response.split())

        # Логируем ответ
        llm_logger.debug(f"PROMPT (STREAMING): {messages[-1]['content'][:200]}...")
        llm_logger.debug(f"RESPONSE: {full_response}")

        return full_response

    def _ensure_russian(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        thinking_callback: Optional[ThinkingCallback] = None,
    ) -> str:
        """
        Генерация с гарантией русского ответа.

        Если модель отвечает на английском — повторяем запрос
        с усиленным промптом.
        """
        system_prompt = system_prompt or self._get_prompt("system")
        for attempt in range(self.config.max_language_retries):
            response = self._generate(prompt, system_prompt, thinking_callback=thinking_callback)

            if detect_language(response) == "ru":
                return response

            self._metrics.language_retries += 1

            # Усиливаем промпт
            prompt = f"""ВАЖНО: Отвечай ТОЛЬКО НА РУССКОМ ЯЗЫКЕ.
НЕ используй английский.

{prompt}

Ответ на русском:"""

        # Возвращаем как есть с предупреждением
        return f"[ВНИМАНИЕ: модель ответила на английском]\n\n{response}"

    def _extract_from_chunk(
        self,
        chunk: Chunk,
        is_dialog: bool = False,
        thinking_callback: Optional[ThinkingCallback] = None,
    ) -> str:
        """Извлечь факты из одного чанка."""
        extraction_prompt = self._get_prompt("extraction", is_dialog=is_dialog)
        prompt = extraction_prompt.format(chunk_text=chunk.text)
        facts = self._ensure_russian(prompt, thinking_callback=thinking_callback)

        # Подсчёт извлечённых фактов для метрик
        fact_count = facts.count('\n- ')
        self._metrics.facts_per_chunk.append(fact_count)

        # Подсчёт чисел/дат (паттерн: цифры, месяцы, проценты)
        number_pattern = r'\d+(?:[.,]\d+)?(?:\s*(?:%|₽|руб|тыс|млн|дн|мес|год|лет|м²|кв\.м))?'
        numbers_found = len(re.findall(number_pattern, facts))
        self._metrics.numbers_extracted += numbers_found

        return facts

    def _aggregate_facts(
        self,
        facts: List[str],
        is_dialog: bool = False,
        thinking_callback: Optional[ThinkingCallback] = None,
    ) -> str:
        """Агрегировать факты в финальное саммари."""
        combined = "\n\n".join([f"[Чанк {i+1}]\n{f}" for i, f in enumerate(facts)])
        aggregation_prompt = self._get_prompt("aggregation", is_dialog=is_dialog)
        prompt = aggregation_prompt.format(extracted_facts=combined, n_chunks=len(facts))
        return self._ensure_russian(prompt, thinking_callback=thinking_callback)

    def summarize(
        self,
        transcript: str,
        progress_callback: Optional[SummaryProgressCallback] = None,
        thinking_callback: Optional[ThinkingCallback] = None,
        use_few_shot: bool = False,
    ) -> Tuple[str, SummarizationMetrics]:
        """
        Суммаризировать транскрипцию.

        Args:
            transcript: Полный текст транскрипции
            progress_callback: Callback для прогресса
            use_few_shot: Использовать few-shot промпт (медленнее, но стабильнее)

        Returns:
            Кортеж (саммари, метрики)
        """
        if not transcript or not transcript.strip():
            logger.warning("Summarizer: пустой входной текст.")
            raise ValueError("Текст транскрипции пуст, саммаризация невозможна.")

        if not self.is_loaded:
            raise RuntimeError("Модель не загружена. Вызовите load_model() сначала.")

        start_time = time.time()
        self._metrics = SummarizationMetrics()

        # Очистка от "призрачных" спикеров, если их слишком много
        speakers = set(re.findall(r'SPEAKER_(\d+):', transcript))
        if len(speakers) > 15:
            logger.info(f"Summarizer: Обнаружено {len(speakers)} спикеров. Упрощаем разметку.")
            transcript = re.sub(r'SPEAKER_\d+:', "Участник:", transcript)

        # Определяем формат текста (диалог со спикерами или нет)
        is_dialog = self._is_dialog_format(transcript)

        # Оцениваем размер
        estimated_tokens = self._chunker.estimate_tokens(transcript)
        self._metrics.input_tokens = estimated_tokens

        if progress_callback:
            format_info = "протокола встречи" if is_dialog else "транскрипции"
            progress_callback(f"Анализ {format_info}...", 5, 100)

        # Выбираем стратегию
        if estimated_tokens < self.config.short_threshold:
            # Короткий текст — один запрос
            self._metrics.input_chunks = 1

            if progress_callback:
                progress_callback("Генерация саммари...", 20, 100)

            if use_few_shot and not is_dialog:
                # Few-shot только для стандартного формата
                prompt = FULL_PROMPT_WITH_EXAMPLE.format(transcript=transcript)
            else:
                short_prompt = self._get_prompt("short", is_dialog=is_dialog)
                prompt = short_prompt.format(transcript=transcript)

            summary = self._ensure_russian(prompt, thinking_callback=thinking_callback)

        else:
            # Длинный текст — двухэтапная обработка
            chunks = self._chunker.chunk(transcript)
            self._metrics.input_chunks = len(chunks)

            if progress_callback:
                progress_callback(f"Обработка {len(chunks)} чанков...", 10, 100)

            # Этап 1: Извлечение из каждого чанка
            extracted_facts = []
            for i, chunk in enumerate(chunks):
                if progress_callback:
                    progress = 10 + int(60 * (i + 1) / len(chunks))
                    progress_callback(f"Извлечение фактов ({i+1}/{len(chunks)})...", progress, 100)

                if thinking_callback:
                    thinking_callback(f"\n[Чанк {i+1}/{len(chunks)}]\n")

                facts = self._extract_from_chunk(chunk, is_dialog=is_dialog, thinking_callback=thinking_callback)
                extracted_facts.append(facts)

            # Этап 2: Агрегация
            if progress_callback:
                progress_callback("Агрегация саммари...", 80, 100)

            if thinking_callback:
                thinking_callback("\n[Агрегация фактов...]\n")

            summary = self._aggregate_facts(extracted_facts, is_dialog=is_dialog, thinking_callback=thinking_callback)

        # Валидация
        validation = validate_facts(summary, transcript)
        if not validation["valid"]:
            self._metrics.hallucinations_detected = len(validation["hallucinated"])

        # Финализация метрик
        self._metrics.processing_time_sec = time.time() - start_time
        self._metrics.output_tokens = self._chunker.estimate_tokens(summary)

        if progress_callback:
            progress_callback("Готово", 100, 100)

        return summary, self._metrics

    def summarize_simple(self, transcript: str) -> str:
        """
        Упрощённый метод суммаризации (без метрик и прогресса).

        Args:
            transcript: Текст транскрипции

        Returns:
            Текст саммари
        """
        summary, _ = self.summarize(transcript)
        return summary


# =============================================================================
# SINGLETON ДЛЯ ГЛОБАЛЬНОГО ДОСТУПА
# =============================================================================

_summarizer_instance: Optional[Summarizer] = None


def get_summarizer(config: Optional[SummarizerConfig] = None) -> Summarizer:
    """
    Получить глобальный экземпляр суммаризатора.

    Создаёт новый экземпляр при первом вызове или если передан config.
    """
    global _summarizer_instance

    if _summarizer_instance is None or config is not None:
        _summarizer_instance = Summarizer(config)

    return _summarizer_instance

