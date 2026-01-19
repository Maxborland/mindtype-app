"""
Модуль диаризации спикеров (лёгкая версия).

Определяет кто говорит в аудиозаписи и размечает транскрипцию по спикерам.
Использует MFCC features + кластеризацию (без тяжёлых нейросетей).

Требования: librosa, sklearn (обычно уже есть)
"""

# Отключаем CUDA для numba (используется librosa)
# Это предотвращает падение если CUDA драйверы не установлены
import os
os.environ["NUMBA_DISABLE_JIT"] = "0"  # JIT включён, но без CUDA
os.environ["NUMBA_CUDA_DRIVER"] = ""  # Отключаем CUDA драйвер

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from .config import ProcessingConfig

# Настройка логирования
def _setup_logger():
    logger = logging.getLogger("diarization")
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)

        log_dir = Path(os.getenv("APPDATA", Path.home())) / "MindType"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "diarization.log"

        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(levelname)s - %(message)s"
        ))
        logger.addHandler(handler)
    return logger

logger = _setup_logger()


@dataclass
class SpeakerSegment:
    """Сегмент речи одного спикера."""
    speaker: str
    start: float
    end: float
    text: str = ""


@dataclass
class SpeakerStatistics:
    """Статистика по спикеру."""
    speaker_id: str
    speaker_name: str
    total_duration: float
    segment_count: int
    word_count: int

    def to_dict(self) -> dict:
        return {
            "speaker_id": self.speaker_id,
            "speaker_name": self.speaker_name,
            "total_duration": self.total_duration,
            "segment_count": self.segment_count,
            "word_count": self.word_count,
        }


@dataclass
class DiarizationResult:
    """Результат диаризации."""
    segments: List[SpeakerSegment] = field(default_factory=list)
    num_speakers: int = 0
    speaker_names: Dict[str, str] = field(default_factory=dict)

    @property
    def formatted_text(self) -> str:
        lines = []
        current_speaker = None
        for seg in self.segments:
            speaker_name = self.speaker_names.get(seg.speaker, seg.speaker)
            if seg.speaker != current_speaker:
                lines.append(f"\n{speaker_name}:")
                current_speaker = seg.speaker
            if seg.text:
                lines.append(seg.text)
        return " ".join(lines).strip()

    def get_speaker_statistics(self) -> List[SpeakerStatistics]:
        stats: Dict[str, dict] = {}
        for seg in self.segments:
            if seg.speaker not in stats:
                stats[seg.speaker] = {"total_duration": 0.0, "segment_count": 0, "word_count": 0}
            stats[seg.speaker]["total_duration"] += (seg.end - seg.start)
            stats[seg.speaker]["segment_count"] += 1
            if seg.text:
                stats[seg.speaker]["word_count"] += len(seg.text.split())

        return [
            SpeakerStatistics(
                speaker_id=sid,
                speaker_name=self.speaker_names.get(sid, sid),
                total_duration=data["total_duration"],
                segment_count=data["segment_count"],
                word_count=data["word_count"],
            )
            for sid, data in sorted(stats.items())
        ]

    def get_segments_by_speaker(self, speaker_id: str) -> List[SpeakerSegment]:
        return [seg for seg in self.segments if seg.speaker == speaker_id]

    def get_unique_speakers(self) -> List[str]:
        return list(sorted(set(seg.speaker for seg in self.segments)))


DiarizationProgressCallback = Callable[[str, int, int], None]


class SpeakerDiarizer:
    """
    Лёгкий диаризатор на основе MFCC features.

    Не требует PyTorch или тяжёлых моделей.
    Использует librosa для извлечения features и sklearn для кластеризации.
    """

    def __init__(self, config: Optional[ProcessingConfig] = None):
        self.config = config or ProcessingConfig()
        self._available = None
        self._load_error: Optional[str] = None

    def _check_available(self) -> bool:
        """Проверить доступность зависимостей."""
        if self._available is not None:
            return self._available

        try:
            import librosa
            from sklearn.cluster import AgglomerativeClustering
            self._available = True
            logger.info("Диаризация доступна (librosa + sklearn)")
        except ImportError as e:
            self._available = False
            self._load_error = f"Отсутствует зависимость: {e}"
            logger.warning(f"Диаризация недоступна: {self._load_error}")

        return self._available

    @property
    def is_available(self) -> bool:
        return self._check_available()

    @property
    def load_error(self) -> Optional[str]:
        self._check_available()
        return self._load_error

    def diarize(
        self,
        audio_path: Path,
        min_speakers: Optional[int] = None,
        max_speakers: Optional[int] = None,
        progress_callback: Optional[DiarizationProgressCallback] = None,
    ) -> DiarizationResult:
        """
        Выполнить диаризацию аудиофайла.

        Использует MFCC features для создания "голосовых отпечатков"
        и агломеративную кластеризацию для группировки по спикерам.
        """
        if not self.is_available:
            logger.warning("Диаризация недоступна")
            return DiarizationResult(
                segments=[SpeakerSegment(speaker="SPEAKER_00", start=0.0, end=0.0)],
                num_speakers=1,
            )

        try:
            import librosa
            from sklearn.cluster import AgglomerativeClustering
            from sklearn.preprocessing import StandardScaler

            if progress_callback:
                progress_callback("Загрузка аудио...", 10, 100)

            logger.info(f"Загружаем аудио: {audio_path}")

            # Загружаем аудио (16kHz mono)
            wav, sr = librosa.load(str(audio_path), sr=16000, mono=True)
            duration = len(wav) / sr

            logger.info(f"Длительность: {duration:.1f} сек")

            if progress_callback:
                progress_callback("Извлечение признаков...", 20, 100)

            # Параметры сегментации
            segment_duration = self.config.diarization_segment_duration  # 1.5 сек
            hop_duration = segment_duration / 2  # 50% перекрытие

            segment_samples = int(segment_duration * sr)
            hop_samples = int(hop_duration * sr)

            # Извлекаем MFCC для каждого сегмента
            segments_data = []
            features = []

            for i in range(0, len(wav) - segment_samples + 1, hop_samples):
                segment_wav = wav[i:i + segment_samples]
                start_time = i / sr
                end_time = (i + segment_samples) / sr

                # Извлекаем MFCC (20 коэффициентов)
                mfcc = librosa.feature.mfcc(y=segment_wav, sr=sr, n_mfcc=20)

                # Усредняем по времени -> получаем вектор из 20 чисел
                mfcc_mean = np.mean(mfcc, axis=1)
                mfcc_std = np.std(mfcc, axis=1)

                # Объединяем mean и std для лучшего представления голоса
                feature_vector = np.concatenate([mfcc_mean, mfcc_std])

                features.append(feature_vector)
                segments_data.append({"start": start_time, "end": end_time})

                if progress_callback and i % (hop_samples * 10) == 0:
                    progress = 20 + int(40 * i / len(wav))
                    progress_callback(f"Обработка... {progress}%", progress, 100)

            if not features:
                logger.warning("Не удалось извлечь признаки")
                return DiarizationResult(
                    segments=[SpeakerSegment(speaker="SPEAKER_00", start=0.0, end=duration)],
                    num_speakers=1,
                )

            if progress_callback:
                progress_callback("Кластеризация спикеров...", 70, 100)

            logger.info(f"Кластеризация {len(features)} сегментов...")

            # Нормализуем features
            features_array = np.array(features)
            scaler = StandardScaler()
            features_normalized = scaler.fit_transform(features_array)

            # Кластеризация с автоопределением оптимального количества спикеров
            if len(features) < 2:
                labels = np.zeros(len(features), dtype=int)
            else:
                from sklearn.metrics import silhouette_score

                # Ограничиваем максимальное количество спикеров разумным пределом
                max_spk_limit = 10
                max_spk = min(max_speakers or self.config.diarization_max_speakers, len(features), max_spk_limit)
                min_spk = max(1, min_speakers or self.config.diarization_min_speakers)

                if max_spk < 2:
                    labels = np.zeros(len(features), dtype=int)
                    best_n = 1
                    best_score = 0.0
                else:
                    # Перебираем количество кластеров от 2 до max и выбираем лучший по silhouette
                    best_labels = np.zeros(len(features), dtype=int)
                    best_score = -1
                    best_n = 1

                    for n in range(2, max_spk + 1):
                        try:
                            clustering = AgglomerativeClustering(
                                n_clusters=n,
                                metric="euclidean",
                                linkage="ward",
                            )
                            trial_labels = clustering.fit_predict(features_normalized)
                            score = silhouette_score(features_normalized, trial_labels)

                            logger.debug(f"n_clusters={n}, silhouette={score:.3f}")

                            # Silhouette > 0.15 считается "разумным" разделением для MFCC
                            if score > best_score:
                                best_score = score
                                best_labels = trial_labels
                                best_n = n
                        except Exception as e:
                            logger.debug(f"Ошибка при n={n}: {e}")
                            continue

                    # Если лучший силуэт слишком низкий, вероятно спикер один
                    if best_score < 0.12:
                        logger.info(f"Силуэт {best_score:.3f} слишком низкий, считаем что спикер один.")
                        labels = np.zeros(len(features), dtype=int)
                        best_n = 1
                    else:
                        labels = best_labels

                logger.info(f"Оптимальное количество кластеров: {best_n} (silhouette={best_score:.3f})")

            num_speakers = len(set(labels))
            logger.info(f"Найдено спикеров: {num_speakers}")

            if progress_callback:
                progress_callback("Формирование результата...", 90, 100)

            # Создаём сегменты
            segments = []
            for seg_data, label in zip(segments_data, labels):
                segments.append(SpeakerSegment(
                    speaker=f"SPEAKER_{label:02d}",
                    start=seg_data["start"],
                    end=seg_data["end"],
                ))

            # Объединяем соседние сегменты одного спикера
            merged_segments = self._merge_adjacent_segments(segments)

            if progress_callback:
                progress_callback("Готово", 100, 100)

            logger.info(f"Диаризация завершена: {len(merged_segments)} сегментов")

            return DiarizationResult(
                segments=merged_segments,
                num_speakers=num_speakers,
            )

        except Exception as e:
            logger.error(f"Ошибка диаризации: {e}")
            return DiarizationResult(
                segments=[SpeakerSegment(speaker="SPEAKER_00", start=0.0, end=0.0)],
                num_speakers=1,
            )

    def _merge_adjacent_segments(
        self,
        segments: List[SpeakerSegment],
        gap_threshold: float = 0.3
    ) -> List[SpeakerSegment]:
        """Объединить соседние сегменты одного спикера."""
        if not segments:
            return segments

        merged = [segments[0]]
        for seg in segments[1:]:
            last = merged[-1]
            if seg.speaker == last.speaker and seg.start - last.end < gap_threshold:
                last.end = seg.end
            else:
                merged.append(seg)
        return merged

    def merge_short_speakers(
        self,
        result: DiarizationResult,
        min_duration_ratio: float = 0.05,  # Спикеры < 5% времени будут слиты
        min_segments: int = 2,  # Или < 2 сегментов
    ) -> DiarizationResult:
        """
        Объединить "мелких" спикеров с доминирующими.
        Если спикер говорит очень мало, скорее всего это ошибка кластеризации.
        """
        if result.num_speakers <= 1:
            return result

        total_duration = sum(s.end - s.start for s in result.segments)
        if total_duration <= 0:
            return result

        # Считаем статистику
        stats = {}
        for seg in result.segments:
            stats[seg.speaker] = stats.get(seg.speaker, 0.0) + (seg.end - seg.start)

        seg_counts = {}
        for seg in result.segments:
            seg_counts[seg.speaker] = seg_counts.get(seg.speaker, 0) + 1

        # Определяем кого сливать
        mapping = {}
        valid_speakers = []

        # Сначала находим валидных спикеров (оставляем хотя бы одного, самого длительного)
        sorted_speakers = sorted(stats.items(), key=lambda x: x[1], reverse=True)
        main_speaker = sorted_speakers[0][0]
        valid_speakers.append(main_speaker)

        for spk, duration in sorted_speakers[1:]:
            ratio = duration / total_duration
            count = seg_counts.get(spk, 0)

            if ratio < min_duration_ratio or count < min_segments:
                mapping[spk] = main_speaker  # Сливаем с самым активным
            else:
                valid_speakers.append(spk)

        if not mapping:
            return result

        logger.info(f"Слияние мелких спикеров: {mapping}")

        # Обновляем сегменты
        new_segments = []
        for seg in result.segments:
            new_speaker = mapping.get(seg.speaker, seg.speaker)
            # Если спикер изменился, обновляем
            if new_speaker != seg.speaker:
                 seg = SpeakerSegment(new_speaker, seg.start, seg.end, seg.text)
            new_segments.append(seg)

        # Объединяем соседние (т.к. могли появиться подряд идущие одного спикера)
        merged = self._merge_adjacent_segments(new_segments)

        return DiarizationResult(
            segments=merged,
            num_speakers=len(set(s.speaker for s in merged)),
            speaker_names=result.speaker_names
        )

    def align_with_transcription(
        self,
        diarization_result: DiarizationResult,
        transcription_segments: List[dict],
    ) -> DiarizationResult:
        """Выровнять результат диаризации с сегментами транскрипции."""
        if not diarization_result.segments or not transcription_segments:
            return diarization_result

        new_segments = []
        for trans_seg in transcription_segments:
            trans_start = trans_seg.get("start", 0)
            trans_end = trans_seg.get("end", 0)
            trans_text = trans_seg.get("text", "").strip()

            if not trans_text:
                continue

            best_speaker = None
            best_overlap = 0

            for diar_seg in diarization_result.segments:
                overlap_start = max(trans_start, diar_seg.start)
                overlap_end = min(trans_end, diar_seg.end)
                overlap = max(0, overlap_end - overlap_start)

                if overlap > best_overlap:
                    best_overlap = overlap
                    best_speaker = diar_seg.speaker

            if best_speaker is None and diarization_result.segments:
                closest = min(
                    diarization_result.segments,
                    key=lambda s: min(abs(s.start - trans_start), abs(s.end - trans_end))
                )
                best_speaker = closest.speaker

            new_segments.append(SpeakerSegment(
                speaker=best_speaker or "SPEAKER_00",
                start=trans_start,
                end=trans_end,
                text=trans_text,
            ))

        return DiarizationResult(
            segments=new_segments,
            num_speakers=diarization_result.num_speakers,
            speaker_names=diarization_result.speaker_names,
        )

    def format_with_speakers(
        self,
        text: str,
        diarization_result: DiarizationResult,
        transcription_segments: Optional[List[dict]] = None,
    ) -> str:
        """Форматировать текст с разметкой спикеров."""
        if transcription_segments:
            aligned = self.align_with_transcription(diarization_result, transcription_segments)
            return aligned.formatted_text

        if not diarization_result.segments:
            return text

        import re
        lines = []
        current_speaker = None

        sentences = re.split(r'(?<=[.!?])\s+', text)
        num_segments = len(diarization_result.segments)
        sentences_per_segment = max(1, len(sentences) // num_segments)

        for i, seg in enumerate(diarization_result.segments):
            speaker_name = diarization_result.speaker_names.get(seg.speaker, seg.speaker)
            if seg.speaker != current_speaker:
                lines.append(f"\n{speaker_name}:")
                current_speaker = seg.speaker

            start_idx = i * sentences_per_segment
            end_idx = start_idx + sentences_per_segment
            segment_sentences = sentences[start_idx:end_idx]

            if segment_sentences:
                lines.append(" ".join(segment_sentences))

        return " ".join(lines).strip()

    def rename_speakers(
        self,
        result: DiarizationResult,
        names: Dict[str, str],
    ) -> DiarizationResult:
        """Переименовать спикеров."""
        result.speaker_names.update(names)
        return result
