"""
Тесты для модуля file_transcriber.

Тестирует:
- Добавление задач в очередь
- Проверку поддерживаемых файлов
- Переходы статусов задач
"""

import tempfile
import wave
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def test_windows_ga_media_limit_rejects_more_than_eight_hours() -> None:
    from app.media_io import (
        MediaDurationTooLong,
        MediaDurationUnavailable,
        enforce_media_duration_limit,
    )

    enforce_media_duration_limit(8 * 60 * 60)

    with pytest.raises(MediaDurationUnavailable, match="measured"):
        enforce_media_duration_limit(0)
    with pytest.raises(MediaDurationTooLong, match="8 hours"):
        enforce_media_duration_limit(8 * 60 * 60 + 0.001)


def test_duration_uses_bundled_soundfile_when_ffprobe_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.media_io import get_file_duration

    source = tmp_path / "duration.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16_000)
        audio.writeframes(b"\0\0" * 8_000)
    monkeypatch.setattr(
        "app.media_io.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )

    assert get_file_duration(source) == pytest.approx(0.5)


class TestIsSupportedFile:
    """Тесты для is_supported_file."""

    def test_is_supported_file_audio(self):
        """is_supported_file должен возвращать True для аудио файлов."""
        from app.file_transcriber import is_supported_file

        audio_files = [
            Path("test.mp3"),
            Path("test.wav"),
            Path("test.m4a"),
            Path("test.flac"),
            Path("test.ogg"),
            Path("test.aac"),
            Path("test.wma"),
            Path("test.opus"),
        ]

        for audio_file in audio_files:
            assert is_supported_file(audio_file) is True, f"Should support {audio_file.suffix}"

    def test_is_supported_file_video(self):
        """is_supported_file должен возвращать True для видео файлов."""
        from app.file_transcriber import is_supported_file

        video_files = [
            Path("test.mp4"),
            Path("test.mkv"),
            Path("test.avi"),
            Path("test.mov"),
            Path("test.webm"),
            Path("test.wmv"),
            Path("test.flv"),
            Path("test.m4v"),
        ]

        for video_file in video_files:
            assert is_supported_file(video_file) is True, f"Should support {video_file.suffix}"

    def test_is_supported_file_unsupported(self):
        """is_supported_file должен возвращать False для неподдерживаемых файлов."""
        from app.file_transcriber import is_supported_file

        unsupported_files = [
            Path("test.txt"),
            Path("test.pdf"),
            Path("test.doc"),
            Path("test.jpg"),
            Path("test.png"),
            Path("test.exe"),
        ]

        for unsupported_file in unsupported_files:
            assert is_supported_file(unsupported_file) is False, f"Should not support {unsupported_file.suffix}"

    def test_is_supported_file_case_insensitive(self):
        """is_supported_file должен быть case-insensitive."""
        from app.file_transcriber import is_supported_file

        assert is_supported_file(Path("test.MP3")) is True
        assert is_supported_file(Path("test.Mp4")) is True
        assert is_supported_file(Path("test.WAV")) is True


class TestFileTask:
    """Тесты для FileTask."""

    def test_file_task_init(self):
        """FileTask должен инициализироваться с правильными значениями."""
        from app.file_transcriber import FileTask, FileStatus

        task = FileTask(file_path=Path("test.mp3"))

        assert task.file_path == Path("test.mp3")
        assert task.status == FileStatus.PENDING
        assert task.progress == 0
        assert task.error_message == ""
        assert task.result is None
        assert task.output_files == {}
        assert task.claim_trial_time_charge() is True
        assert task.claim_trial_time_charge() is False

    def test_file_task_is_video(self):
        """is_video должен возвращать True для видео файлов."""
        from app.file_transcriber import FileTask

        video_task = FileTask(file_path=Path("test.mp4"))
        audio_task = FileTask(file_path=Path("test.mp3"))

        assert video_task.is_video is True
        assert audio_task.is_video is False

    def test_file_task_is_audio(self):
        """is_audio должен возвращать True для аудио файлов."""
        from app.file_transcriber import FileTask

        video_task = FileTask(file_path=Path("test.mp4"))
        audio_task = FileTask(file_path=Path("test.mp3"))

        assert audio_task.is_audio is True
        assert video_task.is_audio is False

    def test_file_task_file_name(self):
        """file_name должен возвращать имя файла."""
        from app.file_transcriber import FileTask

        task = FileTask(file_path=Path("/path/to/test.mp3"))

        assert task.file_name == "test.mp3"

    def test_file_task_uses_durable_asset_without_losing_display_name(
        self,
        tmp_path,
    ):
        from app.file_transcriber import FileTask

        spool_source = tmp_path / "spool" / "operation-1" / "source.wav"
        task = FileTask(
            file_path=Path("C:/Users/customer/interview.wav"),
            source_asset_path=spool_source,
            display_name="customer interview.wav",
        )

        assert task.processing_path == spool_source
        assert task.file_name == "customer interview.wav"


class TestFileStatus:
    """Тесты для FileStatus."""

    def test_file_status_values(self):
        """FileStatus должен иметь все необходимые статусы."""
        from app.file_transcriber import FileStatus

        assert FileStatus.PENDING.value == "pending"
        assert FileStatus.EXTRACTING.value == "extracting"
        assert FileStatus.TRANSCRIBING.value == "transcribing"
        assert FileStatus.PROCESSING.value == "processing"
        assert FileStatus.SUMMARIZING.value == "summarizing"
        assert FileStatus.GENERATING.value == "generating"
        assert FileStatus.COMPLETED.value == "completed"
        assert FileStatus.ERROR.value == "error"
        assert FileStatus.CANCELLED.value == "cancelled"

    def test_queue_status_transitions(self):
        """Статусы задач должны корректно переходить."""
        from app.file_transcriber import FileTask, FileStatus

        task = FileTask(file_path=Path("test.mp4"))

        # Начальный статус
        assert task.status == FileStatus.PENDING

        # Переход в extracting
        task.status = FileStatus.EXTRACTING
        assert task.status == FileStatus.EXTRACTING

        # Переход в transcribing
        task.status = FileStatus.TRANSCRIBING
        assert task.status == FileStatus.TRANSCRIBING

        # Переход в completed
        task.status = FileStatus.COMPLETED
        assert task.status == FileStatus.COMPLETED


class TestFileCancellation:
    def test_cancel_returns_every_pending_task_for_durable_sync(self, tmp_path):
        from app.file_transcriber import (
            FileStatus,
            FileTask,
            FileTranscriptionQueue,
            TranscribeOptions,
        )

        completed = []
        queue = FileTranscriptionQueue(
            MagicMock(),
            TranscribeOptions(
                model_size="tiny",
                compute_type="int8",
                device="cpu",
                language="ru",
                beam_size=1,
                vad_filter=False,
                models_dir=tmp_path,
            ),
            on_completed=completed.append,
        )
        active = FileTask(file_path=tmp_path / "active.wav")
        active.status = FileStatus.TRANSCRIBING
        pending = [
            FileTask(file_path=tmp_path / "second.wav"),
            FileTask(file_path=tmp_path / "third.wav"),
        ]
        queue._tasks.extend([active, *pending])

        cancelled = queue.cancel()

        assert cancelled == pending
        assert completed == pending
        assert all(task.status is FileStatus.CANCELLED for task in pending)
        assert active.status is FileStatus.TRANSCRIBING

    def test_cancel_persists_every_prepared_batch_item(self, tmp_path):
        from app.file_transcriber import (
            FileStatus,
            FileTask,
            FileTranscriptionQueue,
            TranscribeOptions,
        )
        from app.operation_coordinator import OperationCoordinator
        from app.operation_models import OperationStatus
        from app.operation_store import OperationStore
        from app.spool import SpoolManager

        coordinator = OperationCoordinator(
            store=OperationStore(tmp_path / "operations.sqlite3"),
            spool=SpoolManager(tmp_path / "spool"),
        )
        tasks = []
        for index in range(2):
            source = tmp_path / f"batch-{index}.wav"
            source.write_bytes(f"audio-{index}".encode())
            task = FileTask(file_path=source)
            coordinator.prepare_file_task(
                task,
                route={"transcription": {"provider": "local", "model": "tiny"}},
            )
            tasks.append(task)

        queue = FileTranscriptionQueue(
            MagicMock(),
            TranscribeOptions(
                model_size="tiny",
                compute_type="int8",
                device="cpu",
                language="ru",
                beam_size=1,
                vad_filter=False,
                models_dir=tmp_path,
            ),
            on_completed=coordinator.sync_file_task,
        )
        queue._tasks.extend(tasks)

        queue.cancel()

        assert all(task.status is FileStatus.CANCELLED for task in tasks)
        assert all(
            coordinator.store.get(task.operation_id).status
            is OperationStatus.CANCELLED
            for task in tasks
        )

    def test_cancel_during_transcription_cannot_return_to_completed(
        self,
        tmp_path,
        monkeypatch,
    ):
        from app.file_transcriber import (
            FileStatus,
            FileTask,
            FileTranscriptionQueue,
            TranscribeOptions,
        )

        audio_path = tmp_path / "recording.wav"
        audio_path.touch()

        class CancellingTranscriber:
            queue = None

            def transcribe_with_timestamps(self, **kwargs):
                self.queue.cancel()
                return ([{"start": 0.0, "end": 1.0, "text": "текст"}], "ru", 1.0)

        transcriber = CancellingTranscriber()
        completed = []
        queue = FileTranscriptionQueue(
            transcriber,
            TranscribeOptions(
                model_size="tiny",
                compute_type="int8",
                device="cpu",
                language="ru",
                beam_size=1,
                vad_filter=False,
                models_dir=tmp_path,
            ),
            on_completed=completed.append,
        )
        transcriber.queue = queue
        task = FileTask(file_path=audio_path)
        monkeypatch.setattr("app.file_transcriber.get_file_duration", lambda _: 1.0)

        queue._process_task(task)

        assert task.status is FileStatus.CANCELLED
        assert completed == [task]


class TestDurableFileSource:
    def test_queue_reads_spool_asset_when_original_is_unavailable(
        self,
        tmp_path,
        monkeypatch,
    ):
        from app.file_transcriber import (
            FileStatus,
            FileTask,
            FileTranscriptionQueue,
            TranscribeOptions,
        )

        class CapturingTranscriber:
            def __init__(self):
                self.audio_path = None

            def transcribe_with_timestamps(self, *, audio_path, **_kwargs):
                self.audio_path = audio_path
                return (
                    [{"start": 0.0, "end": 1.0, "text": "durable text"}],
                    "en",
                    0.9,
                )

        original = tmp_path / "deleted-original.wav"
        spool_source = tmp_path / "spool" / "operation-1" / "source.wav"
        spool_source.parent.mkdir(parents=True)
        spool_source.write_bytes(b"audio")
        duration_paths = []
        monkeypatch.setattr(
            "app.file_transcriber.get_file_duration",
            lambda path: duration_paths.append(path) or 1.0,
        )
        transcriber = CapturingTranscriber()
        queue = FileTranscriptionQueue(
            transcriber,
            TranscribeOptions(
                model_size="tiny",
                compute_type="int8",
                device="cpu",
                language="en",
                beam_size=1,
                vad_filter=False,
                models_dir=tmp_path,
            ),
        )
        task = FileTask(
            file_path=original,
            source_asset_path=spool_source,
            display_name="customer interview.wav",
        )

        queue._process_task(task)

        assert task.status is FileStatus.COMPLETED
        assert transcriber.audio_path == spool_source
        assert duration_paths == [spool_source]
        assert task.result.file_path.name == "customer interview.wav"

    def test_worker_cleans_temporary_files_after_unexpected_failure(
        self,
        tmp_path,
        monkeypatch,
    ):
        from app.file_transcriber import (
            FileStatus,
            FileTask,
            FileTranscriptionQueue,
            TranscribeOptions,
        )

        class LoadedTranscriber:
            def load_model(self, **kwargs):
                return None

        completed = []
        queue = FileTranscriptionQueue(
            LoadedTranscriber(),
            TranscribeOptions(
                model_size="tiny",
                compute_type="int8",
                device="cpu",
                language="ru",
                beam_size=1,
                vad_filter=False,
                models_dir=tmp_path,
            ),
            on_completed=completed.append,
        )
        source = tmp_path / "source.wav"
        source.touch()
        temporary = tmp_path / "extracted.wav"
        temporary.touch()
        task = FileTask(file_path=source)
        queue._tasks.append(task)
        queue._queue.put(task)
        queue._temp_files.append(temporary)
        queue._running.set()
        monkeypatch.setattr(
            queue,
            "_process_task",
            lambda _: (_ for _ in ()).throw(RuntimeError("unexpected")),
        )

        queue._worker()

        assert not temporary.exists()
        assert not queue.is_running
        assert task.status is FileStatus.ERROR
        assert completed == [task]


class TestTranscriptionSegment:
    """Тесты для TranscriptionSegment."""

    def test_segment_init(self):
        """TranscriptionSegment должен инициализироваться."""
        from app.file_transcriber import TranscriptionSegment

        segment = TranscriptionSegment(
            start=0.0,
            end=5.0,
            text="Hello world",
        )

        assert segment.start == 0.0
        assert segment.end == 5.0
        assert segment.text == "Hello world"
        assert segment.speaker is None

    def test_segment_start_formatted(self):
        """start_formatted должен форматировать время."""
        from app.file_transcriber import TranscriptionSegment

        segment = TranscriptionSegment(start=65.0, end=70.0, text="Test")

        assert segment.start_formatted == "01:05"

    def test_segment_start_formatted_with_hours(self):
        """start_formatted должен включать часы если > 1 часа."""
        from app.file_transcriber import TranscriptionSegment

        segment = TranscriptionSegment(start=3665.0, end=3670.0, text="Test")

        assert segment.start_formatted == "01:01:05"


class TestTranscriptionResult:
    """Тесты для TranscriptionResult."""

    def test_result_full_text(self):
        """full_text должен объединять текст всех сегментов."""
        from app.file_transcriber import TranscriptionResult, TranscriptionSegment

        segments = [
            TranscriptionSegment(start=0, end=5, text="Hello"),
            TranscriptionSegment(start=5, end=10, text="world"),
        ]

        result = TranscriptionResult(
            file_path=Path("test.mp3"),
            segments=segments,
            detected_language="en",
            language_probability=0.95,
            duration=10.0,
            model_used="large-v3",
        )

        assert result.full_text == "Hello world"

    def test_result_duration_formatted(self):
        """duration_formatted должен форматировать длительность."""
        from app.file_transcriber import TranscriptionResult

        # Секунды
        result = TranscriptionResult(
            file_path=Path("test.mp3"),
            segments=[],
            detected_language="en",
            language_probability=0.95,
            duration=45.0,
            model_used="large-v3",
        )
        assert result.duration_formatted == "45с"

        # Минуты
        result.duration = 125.0
        assert result.duration_formatted == "2м 5с"

        # Часы
        result.duration = 3725.0
        assert result.duration_formatted == "1ч 2м 5с"

    def test_result_has_summary(self):
        """has_summary должен возвращать True если есть саммари."""
        from app.file_transcriber import TranscriptionResult

        result = TranscriptionResult(
            file_path=Path("test.mp3"),
            segments=[],
            detected_language="en",
            language_probability=0.95,
            duration=10.0,
            model_used="large-v3",
        )

        assert result.has_summary is False

        result.summary = "This is a summary"
        assert result.has_summary is True

    def test_result_has_speakers(self):
        """has_speakers должен возвращать True если есть несколько спикеров."""
        from app.file_transcriber import TranscriptionResult, SpeakerStats

        result = TranscriptionResult(
            file_path=Path("test.mp3"),
            segments=[],
            detected_language="en",
            language_probability=0.95,
            duration=10.0,
            model_used="large-v3",
        )

        assert result.has_speakers is False

        result.num_speakers = 2
        result.speaker_stats = [
            SpeakerStats("SPEAKER_00", "Speaker 1", 30.0, 5, 100),
            SpeakerStats("SPEAKER_01", "Speaker 2", 25.0, 4, 80),
        ]
        assert result.has_speakers is True


class TestSpeakerStats:
    """Тесты для SpeakerStats."""

    def test_speaker_stats_init(self):
        """SpeakerStats должен инициализироваться."""
        from app.file_transcriber import SpeakerStats

        stats = SpeakerStats(
            speaker_id="SPEAKER_00",
            speaker_name="John",
            total_duration=125.5,
            segment_count=10,
            word_count=200,
        )

        assert stats.speaker_id == "SPEAKER_00"
        assert stats.speaker_name == "John"
        assert stats.total_duration == 125.5
        assert stats.segment_count == 10
        assert stats.word_count == 200

    def test_speaker_stats_duration_formatted(self):
        """duration_formatted должен форматировать время."""
        from app.file_transcriber import SpeakerStats

        stats = SpeakerStats(
            speaker_id="SPEAKER_00",
            speaker_name="John",
            total_duration=125.5,
            segment_count=10,
            word_count=200,
        )

        assert stats.duration_formatted == "2:05"


class TestExtensions:
    """Тесты для констант расширений."""

    def test_audio_extensions(self):
        """AUDIO_EXTENSIONS должен содержать аудио форматы."""
        from app.file_transcriber import AUDIO_EXTENSIONS

        assert ".mp3" in AUDIO_EXTENSIONS
        assert ".wav" in AUDIO_EXTENSIONS
        assert ".flac" in AUDIO_EXTENSIONS

    def test_video_extensions(self):
        """VIDEO_EXTENSIONS должен содержать видео форматы."""
        from app.file_transcriber import VIDEO_EXTENSIONS

        assert ".mp4" in VIDEO_EXTENSIONS
        assert ".mkv" in VIDEO_EXTENSIONS
        assert ".avi" in VIDEO_EXTENSIONS

    def test_all_extensions(self):
        """ALL_EXTENSIONS должен содержать все форматы."""
        from app.file_transcriber import ALL_EXTENSIONS, AUDIO_EXTENSIONS, VIDEO_EXTENSIONS

        assert ALL_EXTENSIONS == AUDIO_EXTENSIONS | VIDEO_EXTENSIONS
