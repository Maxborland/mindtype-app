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
import math
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
        try:
            log_dir = Path(os.getenv("APPDATA", Path.home())) / "MindType"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "diarization.log"

            handler = logging.FileHandler(log_file, encoding="utf-8")
            handler.setFormatter(logging.Formatter(
                "%(asctime)s - %(levelname)s - %(message)s"
            ))
            logger.addHandler(handler)
        except Exception:
            # Restricted environments (tests/sandbox) may disallow writing outside the workspace.
            logger.addHandler(logging.NullHandler())
    return logger

logger = _setup_logger()


@dataclass
class SpeakerSegment:
    """Сегмент речи одного спикера."""
    speaker: str
    start: float
    end: float
    text: str = ""

    def __post_init__(self) -> None:
        start = float(self.start)
        end = float(self.end)
        if not math.isfinite(start) or not math.isfinite(end):
            raise ValueError("Таймкоды сегмента должны быть конечными числами")
        start, end = sorted((max(0.0, start), max(0.0, end)))
        self.start = start
        self.end = end


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


# Локализованное слово «Спикер» для дружелюбных имён по умолчанию.
_SPEAKER_WORD = {
    "ru": "Спикер",
    "uk": "Спікер",
    "de": "Sprecher",
    "fr": "Intervenant",
    "es": "Hablante",
    "it": "Interlocutore",
    "pt": "Falante",
}


def default_speaker_names(speaker_ids: List[str], language: str = "ru") -> Dict[str, str]:
    """
    Построить дружелюбные имена по умолчанию: SPEAKER_00 -> «Спикер 1».

    Нумерация идёт по порядку сортировки ID, начиная с 1.
    """
    word = _SPEAKER_WORD.get((language or "").lower()[:2], "Speaker")
    return {
        speaker_id: f"{word} {index + 1}"
        for index, speaker_id in enumerate(sorted(set(speaker_ids)))
    }


def assign_speaker_by_overlap(
    start: float,
    end: float,
    speaker_segments: List["SpeakerSegment"],
) -> Optional[str]:
    """
    Выбрать спикера для интервала [start, end] по СУММАРНОМУ перекрытию.

    Устойчивее, чем выбор одного диар-сегмента с максимальным перекрытием:
    если интервал накрывает несколько коротких сегментов одного спикера,
    их вклад складывается.
    """
    overlaps: Dict[str, float] = {}
    for seg in speaker_segments:
        overlap = min(end, seg.end) - max(start, seg.start)
        if overlap > 0:
            overlaps[seg.speaker] = overlaps.get(seg.speaker, 0.0) + overlap

    if overlaps:
        return max(overlaps.items(), key=lambda kv: kv[1])[0]

    if speaker_segments:
        closest = min(
            speaker_segments,
            key=lambda s: min(abs(s.start - start), abs(s.end - end)),
        )
        return closest.speaker
    return None


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
        requested_min = (
            self.config.diarization_min_speakers
            if min_speakers is None
            else int(min_speakers)
        )
        requested_max = (
            self.config.diarization_max_speakers
            if max_speakers is None
            else int(max_speakers)
        )
        if requested_min < 1 or requested_max < 1:
            raise ValueError("Количество спикеров должно быть положительным")
        if requested_min > requested_max:
            raise ValueError("min_speakers не может быть больше max_speakers")
        if requested_min > 10:
            raise ValueError("Локальная диаризация поддерживает не более 10 спикеров")

        if not self.is_available:
            logger.warning("Диаризация недоступна")
            return DiarizationResult()

        try:
            import librosa
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

            # Энергетический VAD на уровне фреймов (50 мс): окно попадает в
            # кластеризацию только если достаточная доля его фреймов громкая.
            # Это отсекает и тишину, и «переходные» окна на границе
            # речь/тишина, чьи смешанные признаки образуют ложных спикеров.
            frame_samples = max(1, int(0.05 * sr))
            n_frames = math.ceil(len(wav) / frame_samples) if len(wav) else 0
            padded_wav = (
                np.pad(wav, (0, n_frames * frame_samples - len(wav)))
                if n_frames
                else wav
            )
            frame_rms = np.sqrt(np.mean(
                padded_wav.reshape(n_frames, frame_samples) ** 2,
                axis=1,
            )) if n_frames > 0 else np.array([])

            silence_threshold = 1e-4
            if frame_rms.size:
                # 10% от «громкой» части записи, но не ниже абсолютного пола.
                silence_threshold = max(1e-4, 0.1 * float(np.percentile(frame_rms, 95)))
            voiced_frames = frame_rms > silence_threshold

            def window_voiced_fraction(sample_start: int, sample_end: int) -> float:
                f0 = sample_start // frame_samples
                f1 = max(f0 + 1, math.ceil(sample_end / frame_samples))
                window = voiced_frames[f0:f1]
                return float(np.mean(window)) if window.size else 0.0

            window_bounds = self._window_starts(
                len(wav), segment_samples, hop_samples
            )

            # Извлекаем MFCC для каждого озвученного сегмента
            segments_data = []
            features = []

            for i in window_bounds:
                actual_end = min(len(wav), i + segment_samples)
                if window_voiced_fraction(i, actual_end) < 0.6:
                    continue  # Тишина или граница речь/тишина — пропускаем

                segment_wav = wav[i:actual_end]
                if len(segment_wav) < segment_samples:
                    segment_wav = np.pad(
                        segment_wav, (0, segment_samples - len(segment_wav))
                    )
                start_time = i / sr
                end_time = actual_end / sr

                # Извлекаем MFCC (20 коэффициентов)
                mfcc = librosa.feature.mfcc(y=segment_wav, sr=sr, n_mfcc=20)

                # Статистики по времени: mean + std самих MFCC и дельт.
                # Дельты добавляют информацию о динамике голоса (темп, артикуляция)
                # и заметно улучшают разделение похожих голосов.
                mfcc_delta = librosa.feature.delta(mfcc)
                feature_vector = np.concatenate([
                    np.mean(mfcc, axis=1),
                    np.std(mfcc, axis=1),
                    np.mean(mfcc_delta, axis=1),
                    np.std(mfcc_delta, axis=1),
                ])

                features.append(feature_vector)
                segments_data.append({"start": start_time, "end": end_time})

                if progress_callback and i % (hop_samples * 10) == 0:
                    progress = 20 + int(40 * i / len(wav))
                    progress_callback(f"Обработка... {progress}%", progress, 100)

            logger.info(
                f"VAD: {len(features)} озвученных окон из {len(window_bounds)} "
                f"(порог RMS {silence_threshold:.5f})"
            )

            if not features:
                logger.warning("Не удалось извлечь признаки")
                return DiarizationResult()

            if progress_callback:
                progress_callback("Кластеризация спикеров...", 70, 100)

            logger.info(f"Кластеризация {len(features)} сегментов...")

            # Нормализуем features
            features_array = np.array(features)
            scaler = StandardScaler()
            features_normalized = scaler.fit_transform(features_array)

            max_spk = min(requested_max, len(features), 10)
            min_spk = min(requested_min, max_spk)
            raw_labels = self._cluster_features(
                features_normalized,
                min_speakers=min_spk,
                max_speakers=max_spk,
            )

            # Сглаживаем метки: одиночные «выбросы» между окнами одного спикера
            # почти всегда ошибка кластеризации, а не реальная смена говорящего.
            labels = self._smooth_labels(raw_labels)
            if len(set(labels.tolist())) < min_spk:
                labels = raw_labels
            labels = self._canonicalize_labels(labels)

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
            return DiarizationResult()

    @staticmethod
    def _window_starts(
        total_samples: int, segment_samples: int, hop_samples: int
    ) -> List[int]:
        if total_samples <= 0:
            return []
        if segment_samples <= 0 or hop_samples <= 0:
            raise ValueError("Размеры окна и шага должны быть положительными")
        if total_samples <= segment_samples:
            return [0]
        starts = list(
            range(0, total_samples - segment_samples + 1, hop_samples)
        )
        tail_start = total_samples - segment_samples
        if not starts or starts[-1] != tail_start:
            starts.append(tail_start)
        return starts

    @staticmethod
    def _fit_clusters(
        features: np.ndarray,
        n_clusters: int,
        *,
        clustering_type=None,
    ) -> np.ndarray:
        if clustering_type is None:
            from sklearn.cluster import AgglomerativeClustering
            clustering_type = AgglomerativeClustering
        try:
            clustering = clustering_type(
                n_clusters=n_clusters,
                metric="euclidean",
                linkage="ward",
            )
        except TypeError:
            clustering = clustering_type(
                n_clusters=n_clusters,
                affinity="euclidean",
                linkage="ward",
            )
        return np.asarray(clustering.fit_predict(features), dtype=int)

    @classmethod
    def _cluster_features(
        cls,
        features: np.ndarray,
        *,
        min_speakers: int,
        max_speakers: int,
    ) -> np.ndarray:
        count = len(features)
        if count == 0:
            return np.array([], dtype=int)
        effective_max = min(max(1, int(max_speakers)), count, 10)
        effective_min = min(max(1, int(min_speakers)), effective_max)
        if effective_max == 1:
            return np.zeros(count, dtype=int)
        if effective_min == effective_max:
            return cls._fit_clusters(features, effective_min)

        from sklearn.metrics import silhouette_score

        best_labels: Optional[np.ndarray] = None
        best_score = float("-inf")
        upper_scored = min(effective_max, count - 1)
        for clusters in range(max(2, effective_min), upper_scored + 1):
            try:
                trial = cls._fit_clusters(features, clusters)
                score = float(silhouette_score(features, trial))
                logger.debug(
                    "n_clusters=%s, silhouette=%.3f", clusters, score
                )
                if score > best_score:
                    best_score = score
                    best_labels = trial
            except (TypeError, ValueError) as exc:
                logger.debug("Ошибка при n=%s: %s", clusters, exc)

        if effective_min == 1 and (best_labels is None or best_score < 0.12):
            return np.zeros(count, dtype=int)
        if best_labels is not None:
            return best_labels
        return cls._fit_clusters(features, effective_min)

    @staticmethod
    def _canonicalize_labels(labels: np.ndarray) -> np.ndarray:
        mapping: Dict[int, int] = {}
        canonical: List[int] = []
        for value in np.asarray(labels, dtype=int).tolist():
            if value not in mapping:
                mapping[value] = len(mapping)
            canonical.append(mapping[value])
        return np.asarray(canonical, dtype=int)

    @staticmethod
    def _smooth_labels(labels: np.ndarray, kernel: int = 3) -> np.ndarray:
        """
        Медианное (по моде) сглаживание последовательности меток спикеров.

        Окно из kernel соседних меток; если у центральной метки оба соседа
        совпадают между собой, но отличаются от неё — заменяем на соседей.
        """
        labels = np.asarray(labels)
        if len(labels) < kernel or len(set(labels.tolist())) < 2:
            return labels

        half = kernel // 2
        smoothed = labels.copy()
        for i in range(half, len(labels) - half):
            window = labels[i - half:i + half + 1]
            values, counts = np.unique(window, return_counts=True)
            mode = values[np.argmax(counts)]
            if counts.max() > half:
                smoothed[i] = mode
        return smoothed

    def _merge_adjacent_segments(
        self,
        segments: List[SpeakerSegment],
        gap_threshold: float = 0.3
    ) -> List[SpeakerSegment]:
        """Объединить соседние сегменты одного спикера."""
        if not segments:
            return []

        ordered = sorted(segments, key=lambda segment: (segment.start, segment.end))
        first = ordered[0]
        merged = [SpeakerSegment(first.speaker, first.start, first.end, first.text)]
        for seg in ordered[1:]:
            last = merged[-1]
            if (
                seg.speaker == last.speaker
                and seg.start - last.end <= gap_threshold
            ):
                last.end = max(last.end, seg.end)
                if seg.text:
                    last.text = " ".join(part for part in (last.text, seg.text) if part)
            else:
                merged.append(
                    SpeakerSegment(seg.speaker, seg.start, seg.end, seg.text)
                )
        return merged

    def merge_short_speakers(
        self,
        result: DiarizationResult,
        min_duration_ratio: float = 0.05,  # Спикеры < 5% времени будут слиты
        min_segments: int = 2,  # Или < 2 сегментов
        min_speakers: Optional[int] = None,
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
        required_speakers = max(
            1,
            self.config.diarization_min_speakers
            if min_speakers is None
            else int(min_speakers),
        )

        # Сначала находим валидных спикеров (оставляем хотя бы одного, самого длительного)
        sorted_speakers = sorted(stats.items(), key=lambda x: x[1], reverse=True)
        protected = {
            speaker for speaker, _duration in sorted_speakers[:required_speakers]
        }
        main_speaker = sorted_speakers[0][0]
        for spk, duration in sorted_speakers:
            if spk in protected:
                continue
            ratio = duration / total_duration
            count = seg_counts.get(spk, 0)

            if ratio < min_duration_ratio and count < min_segments:
                mapping[spk] = main_speaker  # Сливаем с самым активным

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
            speaker_names={
                speaker: name
                for speaker, name in result.speaker_names.items()
                if speaker in {segment.speaker for segment in merged}
            },
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
            try:
                raw_start = float(trans_seg.get("start", 0))
                raw_end = float(trans_seg.get("end", 0))
            except (TypeError, ValueError):
                logger.warning("Пропущен transcript segment с невалидными таймкодами")
                continue
            if not math.isfinite(raw_start) or not math.isfinite(raw_end):
                logger.warning("Пропущен transcript segment с невалидными таймкодами")
                continue
            trans_start, trans_end = sorted(
                (max(0.0, raw_start), max(0.0, raw_end))
            )
            trans_text = trans_seg.get("text", "").strip()

            if not trans_text:
                continue

            best_speaker = assign_speaker_by_overlap(
                trans_start, trans_end, diarization_result.segments
            )

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
        sentence_groups = np.array_split(np.asarray(sentences, dtype=object), num_segments)

        for i, seg in enumerate(diarization_result.segments):
            speaker_name = diarization_result.speaker_names.get(seg.speaker, seg.speaker)
            if seg.speaker != current_speaker:
                lines.append(f"\n{speaker_name}:")
                current_speaker = seg.speaker

            segment_sentences = sentence_groups[i].tolist()

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
