"""
Модуль суммаризации транскрипций с помощью LLM провайдеров.

Поддерживает:
- OpenAI, Anthropic, Gemini, Ollama, OpenRouter
- Двухэтапная обработка для длинных текстов
- Reasoning/Thinking mode для поддерживающих моделей
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
import time
import uuid
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .llm import LLMProvider

logger = logging.getLogger(__name__)

# Отдельный логгер для ответов LLM (в проде лучше держать на WARNING или INFO)
llm_logger = logging.getLogger("mindtype.llm")
llm_logger.setLevel(logging.INFO)

def _setup_llm_logging():
    """Настройка детального лога для LLM."""
    try:
        log_dir = Path.home() / ".cache" / "mindtype" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "summarizer.log"

        handler = logging.FileHandler(log_file, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s'))
        llm_logger.addHandler(handler)
    except (OSError, IOError, PermissionError):
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
|| Действие | Ответственный | Срок |
||----------|---------------|------|
|| ... | ... | ... |

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
|| Действие | Ответственный | Срок |
||----------|---------------|------|
|| ... | ... | ... |

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
|| Спикер | Роль | Кратко |
||--------|------|--------|
|| SPEAKER_XX | [роль] | [тема] |

## 1) Все числа/даты/сроки
- [SPEAKER_XX]: [значение] — [контекст]

## 2) Решения и задачи
- [SPEAKER_XX]: ...

## 3) Риски и вопросы
- [SPEAKER_XX]: ...

## 4) Следующие шаги
|| Действие | Ответственный | Срок |
||----------|---------------|------|
|| ... | SPEAKER_XX | ... |"""

DIALOG_SHORT_PROMPT = """ТРАНСКРИПЦИЯ ВСТРЕЧИ:
\"\"\"
{transcript}
\"\"\"

---

Сделай протокол встречи на русском языке. Заполни ВСЕ разделы. Если раздел пустой — напиши "—".

## Участники встречи
Определи роль каждого спикера по контексту:
|| Спикер | Роль |
||--------|------|
|| SPEAKER_XX | [заказчик/исполнитель/эксперт/неизвестно] |

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
|| Действие | Ответственный | Срок |
||----------|---------------|------|
|| ... | SPEAKER_XX | ... |

ВАЖНО: Заполни ВСЕ 5 разделов. Указывай ID спикеров. Отвечай только на русском."""

# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

@dataclass
class SummarizerConfig:
    """Конфигурация суммаризатора."""
    # Провайдер: openai, anthropic, gemini, ollama, openrouter, mindtype_cloud
    provider: str = "openrouter"

    # API ключ (для всех провайдеров кроме Ollama)
    api_key: str = ""

    # Модель (ID модели для выбранного провайдера)
    model: str = ""

    # Base URL (для Ollama)
    base_url: str = ""

    # Reasoning/Thinking mode
    reasoning_enabled: bool = True
    reasoning_effort: str = "medium"  # low / medium / high
    reasoning_budget_tokens: int = 10000  # Для Anthropic/Gemini

    # Параметры инференса
    temperature: float = 0.4  # Более стабильные ответы для PM
    max_tokens: int = 8096  # Большой лимит для длинных саммари и reasoning

    # Чанкинг
    max_chunk_tokens: int = 2000 # Для облачных моделей чанки могут быть больше
    overlap_tokens: int = 200
    short_threshold: int = 3000

    # Retry
    max_language_retries: int = 3

    # Кэширование
    cache_enabled: bool = True
    cache_size: int = 100

    # Кастомные промпты (None = дефолтные)
    custom_prompts: Optional[Dict[str, str]] = None

    # Legacy поля для обратной совместимости
    openrouter_api_key: str = ""
    openrouter_model: str = ""
    openrouter_reasoning: bool = False
    openrouter_reasoning_effort: str = "medium"
    enable_thinking: bool = True

    def __post_init__(self):
        """Миграция legacy полей."""
        # Если используются legacy поля, мигрируем их
        if self.openrouter_api_key and not self.api_key:
            self.api_key = self.openrouter_api_key
        if self.openrouter_model and not self.model:
            self.model = self.openrouter_model
        if self.openrouter_reasoning and not self.reasoning_enabled:
            self.reasoning_enabled = self.openrouter_reasoning
        if self.openrouter_reasoning_effort and self.reasoning_effort == "medium":
            self.reasoning_effort = self.openrouter_reasoning_effort


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
    """Разбивает транскрипцию на чанки."""

    def __init__(self, max_tokens: int = 2000, overlap_tokens: int = 200):
        self.max_tokens = max_tokens
        self.overlap_tokens = overlap_tokens

    def estimate_tokens(self, text: str) -> int:
        """Оценка количества токенов (~1.5 на слово для RU)."""
        return int(len(text.split()) * 1.5)

    def chunk(self, text: str) -> List[Chunk]:
        """Разбить текст на чанки."""
        # Упрощенная логика разбиения для облачных API
        if self.estimate_tokens(text) <= self.max_tokens:
            return [Chunk(id=0, text=text, token_count=self.estimate_tokens(text))]

        # Разбиение по спикерам или предложениям
        speaker_pattern = r'(?=(?:SPEAKER_\d+:))'
        segments = re.split(speaker_pattern, text)
        segments = [s.strip() for s in segments if s.strip()]

        chunks = []
        current_text = ""
        current_tokens = 0
        chunk_id = 0

        for segment in segments:
            seg_tokens = self.estimate_tokens(segment)
            if current_tokens + seg_tokens > self.max_tokens and current_text:
                chunks.append(Chunk(id=chunk_id, text=current_text, token_count=current_tokens))
                chunk_id += 1
                # Overlap (последние пару предложений)
                overlap = " ".join(current_text.split()[-50:])
                current_text = overlap + " " + segment
                current_tokens = self.estimate_tokens(current_text)
            else:
                current_text = (current_text + " " + segment).strip()
                current_tokens += seg_tokens

        if current_text:
            chunks.append(Chunk(id=chunk_id, text=current_text, token_count=current_tokens))

        return chunks


# =============================================================================
# ВАЛИДАЦИЯ И МЕТРИКИ
# =============================================================================

def detect_language(text: str) -> str:
    cyrillic = len(re.findall(r'[а-яёА-ЯЁ]', text))
    latin = len(re.findall(r'[a-zA-Z]', text))
    return "ru" if cyrillic > latin else "en"

@dataclass
class SummarizationMetrics:
    input_tokens: int = 0
    input_chunks: int = 0
    llm_calls: int = 0
    processing_time_sec: float = 0.0
    language_retries: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "input": {"tokens": self.input_tokens, "chunks": self.input_chunks},
            "processing": {
                "llm_calls": self.llm_calls,
                "time_sec": round(self.processing_time_sec, 2),
            },
            "quality": {"language_retries": self.language_retries},
            "output_tokens": self.output_tokens,
        }

class ResponseCache:
    def __init__(self, max_size: int = 100):
        self.max_size = max_size
        self._cache: Dict[str, str] = {}

    def get(self, prompt: str) -> Optional[str]:
        key = hashlib.md5(prompt.encode()).hexdigest()[:16]
        return self._cache.get(key)

    def set(self, prompt: str, response: str) -> None:
        key = hashlib.md5(prompt.encode()).hexdigest()[:16]
        if len(self._cache) >= self.max_size:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = response

# =============================================================================
# СУММАРИЗАТОР
# =============================================================================

SummaryProgressCallback = Callable[[str, int, int], None]
ThinkingCallback = Callable[[str], None]

class Summarizer:
    def __init__(self, config: Optional[SummarizerConfig] = None):
        self.config = config or SummarizerConfig()
        self._provider: Optional["LLMProvider"] = None
        self._model_loaded = False
        self._cache = ResponseCache(self.config.cache_size) if self.config.cache_enabled else None
        self._chunker = TranscriptChunker(
            max_tokens=self.config.max_chunk_tokens,
            overlap_tokens=self.config.overlap_tokens,
        )
        self._metrics = SummarizationMetrics()

    def _get_prompt(self, key: str, is_dialog: bool = False) -> str:
        defaults = {"system": SYSTEM_PROMPT, "short": SHORT_PROMPT, "extraction": EXTRACTION_PROMPT, "aggregation": AGGREGATION_PROMPT}
        dialog_prompts = {"system": DIALOG_SYSTEM_PROMPT, "short": DIALOG_SHORT_PROMPT, "extraction": DIALOG_EXTRACTION_PROMPT, "aggregation": DIALOG_AGGREGATION_PROMPT}

        if self.config.custom_prompts and key in self.config.custom_prompts:
            return self.config.custom_prompts[key]

        return dialog_prompts.get(key, defaults.get(key, "")) if is_dialog else defaults.get(key, "")

    @property
    def is_loaded(self) -> bool:
        return self._model_loaded

    def _create_provider(self) -> "LLMProvider":
        """Создать провайдер на основе конфигурации."""
        from .llm import get_provider_by_name

        return get_provider_by_name(
            name=self.config.provider,
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=180,
        )

    def _get_reasoning_config(self):
        """Получить конфигурацию reasoning mode."""
        from .llm import ReasoningConfig, ReasoningEffort

        if not self.config.reasoning_enabled:
            return None

        effort_map = {
            "low": ReasoningEffort.LOW,
            "medium": ReasoningEffort.MEDIUM,
            "high": ReasoningEffort.HIGH,
        }

        return ReasoningConfig(
            enabled=True,
            effort=effort_map.get(self.config.reasoning_effort, ReasoningEffort.MEDIUM),
            budget_tokens=self.config.reasoning_budget_tokens,
        )

    def load_model(self, models_dir: Optional[Path] = None, progress_callback: Optional[SummaryProgressCallback] = None) -> None:
        if self._model_loaded: return

        provider_name = self.config.provider.upper()
        if progress_callback: progress_callback(f"Проверка {provider_name} API...", 50, 100)

        # Проверяем наличие API ключа (не требуется для Ollama и MindType Cloud без ключа)
        no_key_providers = ("ollama", "mindtype_cloud")
        if self.config.provider not in no_key_providers and not self.config.api_key:
            raise RuntimeError(f"API ключ для {provider_name} не задан")

        # Создаём и проверяем провайдер
        self._provider = self._create_provider()

        if not self._provider.validate_api_key():
            raise RuntimeError(f"Неверный API ключ для {provider_name}")

        self._model_loaded = True
        if progress_callback: progress_callback(f"{provider_name} готов", 100, 100)

    def _generate(self, prompt: str, system_prompt: Optional[str] = None, max_tokens: Optional[int] = None, thinking_callback: Optional[ThinkingCallback] = None, meeting_id: Optional[str] = None) -> str:
        """Сгенерировать ответ через LLM провайдер."""
        if not self._provider:
            self._provider = self._create_provider()

        system_prompt = system_prompt or self._get_prompt("system")
        cache_key = f"{self.config.provider}:{self.config.model}:{system_prompt}|||{prompt}"

        if self._cache:
            cached = self._cache.get(cache_key)
            if cached: return cached

        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
        reasoning = self._get_reasoning_config()

        # Дополнительные параметры для MindType Cloud
        cloud_kwargs = {}
        if self.config.provider == "mindtype_cloud":
            cloud_kwargs["task"] = "summarize"
            if meeting_id:
                cloud_kwargs["meeting_id"] = meeting_id

        # Используем стриминг если есть callback
        if thinking_callback:
            result = self._provider.stream(
                messages=messages,
                model=self.config.model,
                on_token=thinking_callback,
                reasoning=reasoning,
                on_thinking=thinking_callback,  # Для thinking блоков
                max_tokens=max_tokens or self.config.max_tokens,
                temperature=self.config.temperature,
                **cloud_kwargs,
            )
        else:
            result = self._provider.complete(
                messages=messages,
                model=self.config.model,
                reasoning=reasoning,
                max_tokens=max_tokens or self.config.max_tokens,
                temperature=self.config.temperature,
                **cloud_kwargs,
            )

        self._metrics.llm_calls += 1
        if self._cache: self._cache.set(cache_key, result)
        return result.strip()

    def _ensure_russian(self, prompt: str, system_prompt: Optional[str] = None, thinking_callback: Optional[ThinkingCallback] = None, meeting_id: Optional[str] = None) -> str:
        for _ in range(self.config.max_language_retries):
            response = self._generate(prompt, system_prompt, thinking_callback=thinking_callback, meeting_id=meeting_id)
            if detect_language(response) == "ru": return response
            self._metrics.language_retries += 1
            prompt = f"ВАЖНО: Отвечай ТОЛЬКО НА РУССКОМ ЯЗЫКЕ.\n\n{prompt}"
        return response

    def summarize(self, transcript: str, progress_callback: Optional[SummaryProgressCallback] = None, thinking_callback: Optional[ThinkingCallback] = None, meeting_id: Optional[str] = None) -> Tuple[str, SummarizationMetrics]:
        if not transcript.strip(): raise ValueError("Текст транскрипции пуст")
        if not self._model_loaded: self.load_model(progress_callback=progress_callback)

        start_time = time.time()
        self._metrics = SummarizationMetrics()
        is_dialog = bool(re.search(r'SPEAKER_\d+:', transcript))
        estimated_tokens = self._chunker.estimate_tokens(transcript)
        self._metrics.input_tokens = estimated_tokens

        # Генерируем meeting_id для MindType Cloud (группировка кредитов)
        if not meeting_id and self.config.provider == "mindtype_cloud":
            meeting_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, transcript[:500]))

        if estimated_tokens < self.config.short_threshold:
            self._metrics.input_chunks = 1
            if progress_callback: progress_callback("Генерация саммари...", 50, 100)
            prompt = self._get_prompt("short", is_dialog=is_dialog).format(transcript=transcript)
            summary = self._ensure_russian(prompt, thinking_callback=thinking_callback, meeting_id=meeting_id)
        else:
            chunks = self._chunker.chunk(transcript)
            self._metrics.input_chunks = len(chunks)
            facts = []
            for i, chunk in enumerate(chunks):
                if progress_callback: progress_callback(f"Анализ чанка {i+1}/{len(chunks)}...", 10 + int(70 * (i+1)/len(chunks)), 100)
                fact = self._ensure_russian(self._get_prompt("extraction", is_dialog=is_dialog).format(chunk_text=chunk.text), thinking_callback=thinking_callback, meeting_id=meeting_id)
                facts.append(fact)

            if progress_callback: progress_callback("Агрегация...", 90, 100)
            summary = self._ensure_russian(self._get_prompt("aggregation", is_dialog=is_dialog).format(extracted_facts="\n\n".join(facts), n_chunks=len(facts)), thinking_callback=thinking_callback, meeting_id=meeting_id)

        self._metrics.processing_time_sec = time.time() - start_time
        self._metrics.output_tokens = self._chunker.estimate_tokens(summary)
        return summary, self._metrics

def get_summarizer(config: Optional[SummarizerConfig] = None) -> Summarizer:
    global _summarizer_instance
    if _summarizer_instance is None or config is not None:
        _summarizer_instance = Summarizer(config)
    return _summarizer_instance

_summarizer_instance: Optional[Summarizer] = None
