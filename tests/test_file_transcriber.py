"""
Тесты для модуля file_transcriber.

Тестирует:
- Добавление задач в очередь
- Проверку поддерживаемых файлов
- Переходы статусов задач
"""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


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
