"""
Диаризация спикеров через LLM (OpenRouter).

Вместо акустической кластеризации (MFCC) спикеры размечаются языковой моделью
по структуре диалога: обращения, вопросы-ответы, смена темы, «я/ты», имена.
На связных разговорах (созвоны, интервью) это точнее лёгкой локальной
диаризации, а при обращениях по имени модель возвращает настоящие имена.

Требует OpenRouter API ключ. При любой ошибке вызывающий код (pipeline)
откатывается на локальную диаризацию.
"""

import json
import logging
import re
from typing import Callable, Dict, List, Optional

from .diarization import DiarizationResult, SpeakerSegment

logger = logging.getLogger("diarization")

# Максимум символов транскрипта в одном запросе (консервативно: ~12k токенов).
MAX_CHARS_PER_BATCH = 24_000
# Максимум сегментов в одном запросе (длина labels в ответе).
MAX_SEGMENTS_PER_BATCH = 120

SYSTEM_PROMPT = """You are a speaker diarization assistant. You read a meeting/call transcript split into numbered segments and decide which speaker said each segment.

Use dialogue structure: questions vs answers, addressing by name, self-references, topic ownership, speech style. Segments are in chronological order; consecutive segments often belong to the same speaker.

Respond with STRICT JSON only, no prose, no code fences:
{"num_speakers": <int>, "labels": [<int per segment, 1-based speaker number>], "names": {"<speaker number>": "<real name if clearly identifiable from the text>"}}

Rules:
1. "labels" MUST have exactly one integer for every input segment, in order.
2. Speaker numbers are 1-based and consistent across the whole transcript.
3. Include a name in "names" ONLY if the transcript makes it clear (introduced themselves or addressed by name and then answering). Otherwise omit that speaker.
4. If it is clearly a monologue, use a single speaker 1 for all segments."""


def _format_time(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes:02d}:{secs:02d}"


def _parse_llm_json(raw: str) -> dict:
    """Распарсить JSON из ответа LLM (терпимо к code fences и прозе вокруг)."""
    text = raw.strip()
    # Убираем ```json ... ``` обёртку
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Последняя попытка: вырезать первый {...} блок
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            return json.loads(brace.group(0))
        raise


DiarizationProgressCallback = Callable[[str, int, int], None]


class LLMDiarizer:
    """Диаризация транскрипта через chat-модель OpenRouter."""

    def __init__(self, api_key: str, model: str, timeout: int = 180):
        self.api_key = (api_key or "").strip()
        self.model = (model or "").strip()
        self.timeout = timeout
        self._provider = None

    @property
    def is_available(self) -> bool:
        return bool(self.api_key and self.model)

    def _get_provider(self):
        if self._provider is None:
            from ..llm.openrouter import OpenRouterProvider
            self._provider = OpenRouterProvider(api_key=self.api_key, timeout=self.timeout)
        return self._provider

    def diarize_segments(
        self,
        transcription_segments: List[dict],
        language: str = "ru",
        progress_callback: Optional[DiarizationProgressCallback] = None,
    ) -> DiarizationResult:
        """
        Разметить сегменты транскрипции по спикерам.

        Args:
            transcription_segments: [{"start": float, "end": float, "text": str}, ...]
            language: язык транскрипта (для сообщения прогресса)
            progress_callback: callback прогресса

        Returns:
            DiarizationResult: сегменты уже с текстом и таймкодами транскрипции.

        Raises:
            Exception: при ошибке API/парсинга — вызывающий код делает fallback.
        """
        segments = [
            s for s in transcription_segments
            if (s.get("text") or "").strip()
        ]
        if not segments:
            return DiarizationResult(segments=[], num_speakers=0)

        batches = self._make_batches(segments)
        logger.info(
            f"LLM-диаризация: {len(segments)} сегментов, {len(batches)} запрос(ов), "
            f"модель {self.model}"
        )

        all_labels: List[int] = []
        names: Dict[str, str] = {}

        for batch_idx, batch in enumerate(batches):
            if progress_callback:
                progress_callback(
                    f"Диаризация через OpenRouter ({batch_idx + 1}/{len(batches)})...",
                    10 + int(80 * batch_idx / len(batches)),
                    100,
                )

            labels, batch_names = self._diarize_batch(
                batch,
                offset=len(all_labels),
                known_names=names,
                prev_segments=segments[:len(all_labels)],
                prev_labels=all_labels,
            )
            all_labels.extend(labels)
            names.update(batch_names)

        if len(all_labels) != len(segments):
            raise ValueError(
                f"LLM вернула {len(all_labels)} меток для {len(segments)} сегментов"
            )

        result_segments = [
            SpeakerSegment(
                speaker=f"SPEAKER_{label - 1:02d}",
                start=float(seg.get("start", 0.0)),
                end=float(seg.get("end", 0.0)),
                text=(seg.get("text") or "").strip(),
            )
            for seg, label in zip(segments, all_labels)
        ]

        speaker_names = {
            f"SPEAKER_{int(num) - 1:02d}": str(name).strip()
            for num, name in names.items()
            if str(num).isdigit() and str(name).strip()
        }

        num_speakers = len(set(s.speaker for s in result_segments))

        if progress_callback:
            progress_callback("Диаризация завершена", 100, 100)

        logger.info(
            f"LLM-диаризация: найдено {num_speakers} спикеров, "
            f"имена: {speaker_names or '—'}"
        )

        return DiarizationResult(
            segments=result_segments,
            num_speakers=num_speakers,
            speaker_names=speaker_names,
        )

    def _make_batches(self, segments: List[dict]) -> List[List[dict]]:
        """Разбить сегменты на батчи по лимитам символов и количества."""
        batches: List[List[dict]] = []
        current: List[dict] = []
        current_chars = 0

        for seg in segments:
            seg_chars = len(seg.get("text") or "") + 24  # + накладные на номер/таймкод
            if current and (
                current_chars + seg_chars > MAX_CHARS_PER_BATCH
                or len(current) >= MAX_SEGMENTS_PER_BATCH
            ):
                batches.append(current)
                current = []
                current_chars = 0
            current.append(seg)
            current_chars += seg_chars

        if current:
            batches.append(current)
        return batches

    def _diarize_batch(
        self,
        batch: List[dict],
        offset: int,
        known_names: Dict[str, str],
        prev_segments: List[dict],
        prev_labels: List[int],
    ) -> tuple:
        """
        Разметить один батч. Возвращает (labels, names).

        Для батчей после первого в промпт добавляется контекст: последние
        реплики каждого уже известного спикера, чтобы нумерация оставалась
        сквозной и согласованной.
        """
        lines = []
        for i, seg in enumerate(batch):
            time = _format_time(float(seg.get("start", 0.0)))
            text = (seg.get("text") or "").strip()
            lines.append(f"[{offset + i}] [{time}] {text}")

        context = ""
        if prev_labels:
            # Последняя реплика каждого известного спикера из предыдущих батчей
            last_by_speaker: Dict[int, str] = {}
            for seg, label in zip(prev_segments, prev_labels):
                text = (seg.get("text") or "").strip()
                if text:
                    last_by_speaker[label] = text[-160:]

            context_lines = []
            for label in sorted(last_by_speaker):
                name = known_names.get(str(label), "")
                title = f"Speaker {label}" + (f" ({name})" if name else "")
                context_lines.append(f'- {title}: "...{last_by_speaker[label]}"')

            context = (
                "Speakers already identified in the previous part of this transcript "
                "(KEEP the same numbering):\n" + "\n".join(context_lines) + "\n\n"
            )

        user_prompt = (
            f"{context}"
            f"Transcript segments (segment index, start time, text):\n"
            + "\n".join(lines)
            + f'\n\nReturn JSON with exactly {len(batch)} labels '
            f'(for segments {offset}..{offset + len(batch) - 1}).'
        )

        provider = self._get_provider()
        raw = provider.complete(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            model=self.model,
            max_tokens=4096,
            temperature=0.0,
        )

        data = _parse_llm_json(raw)
        labels = data.get("labels")
        if not isinstance(labels, list) or len(labels) != len(batch):
            raise ValueError(
                f"LLM вернула некорректные labels: ожидалось {len(batch)}, "
                f"получено {len(labels) if isinstance(labels, list) else type(labels)}"
            )

        clean_labels = []
        for label in labels:
            try:
                value = int(label)
            except (TypeError, ValueError):
                raise ValueError(f"Некорректная метка спикера: {label!r}")
            clean_labels.append(max(1, value))

        raw_names = data.get("names") or {}
        names = {
            str(k): str(v).strip()
            for k, v in raw_names.items()
            if str(v).strip()
        } if isinstance(raw_names, dict) else {}

        return clean_labels, names
