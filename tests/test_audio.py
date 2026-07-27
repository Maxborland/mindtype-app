"""
Unit тесты для модуля audio.py

Тестируем AudioRecorder без реального доступа к микрофону
используя mocking.
"""

import queue

import numpy as np
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

from app.audio import AudioRecorder
from app.audio_sources import AudioCaptureStatus, AudioSourceKind


class TestAudioRecorder:
    """Тесты для класса AudioRecorder."""

    def test_init_defaults(self):
        """Проверяем значения по умолчанию при инициализации."""
        recorder = AudioRecorder()

        assert recorder.samplerate == 16000
        assert recorder.channels == 1
        assert recorder.dtype == "int16"
        assert recorder.recording is False
        assert recorder.monitoring is False

    def test_init_custom_params(self):
        """Проверяем инициализацию с кастомными параметрами."""
        recorder = AudioRecorder(samplerate=44100, channels=2)

        assert recorder.samplerate == 44100
        assert recorder.channels == 2

    @patch('app.audio.sd.query_devices')
    def test_list_input_devices(self, mock_query_devices):
        """Тест получения списка устройств ввода."""
        mock_query_devices.return_value = [
            {'name': 'Microphone 1', 'max_input_channels': 2, 'max_output_channels': 0},
            {'name': 'Speakers', 'max_input_channels': 0, 'max_output_channels': 2},
            {'name': 'Microphone 2', 'max_input_channels': 1, 'max_output_channels': 0},
        ]

        recorder = AudioRecorder()
        devices = recorder.list_input_devices()

        assert len(devices) == 2
        assert '0: Microphone 1' in devices
        assert '2: Microphone 2' in devices
        assert '1: Speakers' not in devices

    def test_recording_property_initially_false(self):
        """recording должен быть False до начала записи."""
        recorder = AudioRecorder()
        assert recorder.recording is False

    def test_monitoring_property_initially_false(self):
        """monitoring должен быть False до начала мониторинга."""
        recorder = AudioRecorder()
        assert recorder.monitoring is False

    @patch('app.audio.sd.RawInputStream')
    @patch('app.audio.tempfile.NamedTemporaryFile')
    def test_start_creates_temp_file(self, mock_tempfile, mock_stream):
        """При старте записи должен создаваться временный файл."""
        # Настраиваем mock для временного файла
        mock_file = MagicMock()
        mock_file.name = '/tmp/test.wav'
        mock_tempfile.return_value = mock_file

        # Настраиваем mock для потока
        mock_stream_instance = MagicMock()
        mock_stream.return_value = mock_stream_instance

        recorder = AudioRecorder()
        recorder.start()

        # Проверяем что временный файл создан
        mock_tempfile.assert_called_once_with(delete=False, suffix='.wav')
        assert recorder.recording is True

        # Останавливаем для cleanup
        recorder.stop()

    def test_stop_without_start_returns_none(self):
        """stop() без предварительного start() возвращает None."""
        recorder = AudioRecorder()
        result = recorder.stop()
        assert result is None

    def test_stop_does_not_return_path_while_writer_is_alive(self, tmp_path):
        recorder = AudioRecorder()
        wav_path = tmp_path / "unfinished.wav"
        wav_path.touch()
        recorder._tmp_path = wav_path
        recorder._running.set()
        recorder._stream = MagicMock()
        recorder._writer_thread = MagicMock()
        recorder._writer_thread.is_alive.return_value = True

        with pytest.raises(RuntimeError, match="ещё записывается"):
            recorder.stop(timeout=0.01)

        assert recorder.recording is False
        assert recorder._tmp_path == wav_path

    @patch("app.audio.sd.RawInputStream")
    def test_writer_timeout_blocks_restart_until_pending_wav_is_finalized(
        self,
        mock_stream,
        tmp_path,
    ):
        recorder = AudioRecorder()
        wav_path = tmp_path / "unfinished.wav"
        wav_path.touch()
        pending_queue = MagicMock()
        writer = MagicMock()
        writer.is_alive.side_effect = [True, True, False]
        recorder._tmp_path = wav_path
        recorder._queue = pending_queue
        recorder._running.set()
        recorder._stream = MagicMock()
        recorder._writer_thread = writer

        with pytest.raises(RuntimeError, match="ещё записывается"):
            recorder.stop(timeout=0.01)

        with pytest.raises(RuntimeError, match="[Пп]редыдущ"):
            recorder.start()

        assert recorder._queue is pending_queue
        assert recorder._tmp_path == wav_path
        mock_stream.assert_not_called()

        assert recorder.stop(timeout=0.01) == wav_path
        assert recorder._writer_thread is None
        assert recorder._tmp_path is None

    def test_typed_stop_retry_preserves_original_capture_timestamp(
        self,
        tmp_path,
    ):
        recorder = AudioRecorder()
        wav_path = tmp_path / "unfinished.wav"
        wav_path.touch()
        writer = MagicMock()
        writer.is_alive.side_effect = [True, True, True, False]
        recorder._tmp_path = wav_path
        recorder._queue = MagicMock()
        recorder._running.set()
        recorder._stream = MagicMock()
        recorder._writer_thread = writer
        recorder._started_at_monotonic_ns = 123

        unfinished = recorder.stop_capture(timeout=0.01)
        finalized = recorder.stop_capture(timeout=0.01)

        assert unfinished.status is AudioCaptureStatus.INTERRUPTED
        assert unfinished.track is None
        assert finalized.status is AudioCaptureStatus.COMPLETED
        assert finalized.track is not None
        assert finalized.track.started_at_monotonic_ns == 123

    def test_full_queue_stop_retries_the_writer_sentinel(self, tmp_path):
        recorder = AudioRecorder()
        wav_path = tmp_path / "pending.wav"
        wav_path.touch()
        pending_queue = queue.Queue(maxsize=1)
        pending_queue.put(b"audio")
        writer = MagicMock()
        writer.is_alive.side_effect = [True, False]
        recorder._tmp_path = wav_path
        recorder._queue = pending_queue
        recorder._running.set()
        recorder._stream = MagicMock()
        recorder._writer_thread = writer

        with pytest.raises(RuntimeError, match="аудиобуфер переполнен"):
            recorder.stop(timeout=0.01)

        assert recorder._writer_stop_requested is False
        assert pending_queue.get_nowait() == b"audio"
        assert recorder.stop(timeout=0.01) == wav_path
        assert recorder._writer_thread is None

    def test_dead_writer_is_reaped_before_full_queue_sentinel(self, tmp_path):
        recorder = AudioRecorder()
        wav_path = tmp_path / "failed.wav"
        wav_path.touch()
        pending_queue = queue.Queue(maxsize=1)
        pending_queue.put(b"audio")
        writer = MagicMock()
        writer.is_alive.return_value = False
        recorder._tmp_path = wav_path
        recorder._queue = pending_queue
        recorder._running.set()
        recorder._stream = MagicMock()
        recorder._writer_thread = writer
        recorder._writer_error = OSError("disk full")

        result = recorder.stop_capture(timeout=0.01)

        assert result.status is AudioCaptureStatus.INTERRUPTED
        assert result.track is None
        assert "disk full" in (result.error or "")
        assert recorder._writer_thread is None
        assert recorder.finalizing is False
        assert wav_path.exists() is False

    def test_compatibility_stop_discards_finalized_interrupted_capture(
        self,
        tmp_path,
    ):
        recorder = AudioRecorder()
        wav_path = tmp_path / "overflowed.wav"
        wav_path.touch()
        recorder._tmp_path = wav_path
        recorder._running.set()
        recorder._stream = MagicMock()
        writer = MagicMock()
        writer.is_alive.return_value = False
        recorder._writer_thread = writer
        recorder._overflowed.set()

        with pytest.raises(RuntimeError, match="аудиобуфер был переполнен"):
            recorder.stop(timeout=0.01)

        assert recorder._tmp_path is None
        assert recorder._writer_thread is None
        assert not wav_path.exists()


    @patch('app.audio.sd.RawInputStream')
    def test_start_monitoring_success(self, mock_stream):
        """Успешный старт мониторинга."""
        mock_stream_instance = MagicMock()
        mock_stream.return_value = mock_stream_instance

        recorder = AudioRecorder()
        level_values = []

        def level_callback(levels):
            level_values.extend(levels)

        result = recorder.start_monitoring(level_callback=level_callback)

        assert result is True
        assert recorder.monitoring is True

        recorder.stop_monitoring()

    @patch('app.audio.sd.RawInputStream')
    def test_stop_monitoring(self, mock_stream):
        """Остановка мониторинга."""
        mock_stream_instance = MagicMock()
        mock_stream.return_value = mock_stream_instance

        recorder = AudioRecorder()
        recorder.start_monitoring()

        assert recorder.monitoring is True

        recorder.stop_monitoring()

        assert recorder.monitoring is False
        mock_stream_instance.stop.assert_called_once()
        mock_stream_instance.close.assert_called_once()

    def test_stop_monitoring_without_start(self):
        """stop_monitoring() без start_monitoring() не должен падать."""
        recorder = AudioRecorder()
        # Не должно выбрасывать исключение
        recorder.stop_monitoring()
        assert recorder.monitoring is False


class TestAudioLevelCalculation:
    """Тесты для расчёта уровня громкости."""

    def test_level_normalization(self):
        """Проверка нормализации уровня к диапазону [0, 1]."""
        # Создаём тестовые аудио данные
        # Тихий звук
        quiet_audio = np.array([100, -100, 50, -50], dtype=np.int16)
        quiet_rms = np.sqrt(np.mean(quiet_audio.astype(np.float32) ** 2))
        quiet_normalized = min(1.0, quiet_rms / 2000)

        assert 0.0 <= quiet_normalized <= 1.0
        assert quiet_normalized < 0.1  # Тихий звук должен быть < 10%

        # Громкий звук
        loud_audio = np.array([5000, -5000, 4000, -4000], dtype=np.int16)
        loud_rms = np.sqrt(np.mean(loud_audio.astype(np.float32) ** 2))
        loud_normalized = min(1.0, loud_rms / 2000)

        assert 0.0 <= loud_normalized <= 1.0
        assert loud_normalized > quiet_normalized  # Громкий > тихого

    def test_silent_audio_level(self):
        """Тишина должна давать уровень близкий к нулю."""
        silent_audio = np.zeros(1000, dtype=np.int16)
        rms = np.sqrt(np.mean(silent_audio.astype(np.float32) ** 2))
        normalized = min(1.0, rms / 2000)

        assert normalized == 0.0

    def test_max_level_clipping(self):
        """Максимальный уровень не должен превышать 1.0."""
        max_audio = np.full(1000, 32767, dtype=np.int16)
        rms = np.sqrt(np.mean(max_audio.astype(np.float32) ** 2))
        normalized = min(1.0, rms / 2000)

        assert normalized == 1.0


class TestErrorHandling:
    """Тесты обработки ошибок."""

    @patch('app.audio.tempfile.NamedTemporaryFile')
    @patch('app.audio.sd.RawInputStream')
    def test_stream_start_failure_rolls_back_every_resource(
        self,
        mock_stream,
        mock_tempfile,
        tmp_path,
    ):
        import sounddevice as sd

        wav_path = tmp_path / "failed-start.wav"
        wav_path.touch()
        mock_file = MagicMock(name=str(wav_path))
        mock_file.name = str(wav_path)
        mock_tempfile.return_value = mock_file
        stream = MagicMock()
        stream.start.side_effect = sd.PortAudioError("Device disconnected")
        mock_stream.return_value = stream
        recorder = AudioRecorder()

        with pytest.raises(RuntimeError, match="запустить устройство записи"):
            recorder.start()

        assert recorder.recording is False
        assert recorder._writer_thread is None
        assert recorder._tmp_path is None
        assert not wav_path.exists()
        stream.close.assert_called_once()

    @patch('app.audio.sd.RawInputStream')
    def test_start_with_invalid_device(self, mock_stream):
        """start() с несуществующим устройством должен выбрасывать исключение."""
        import sounddevice as sd
        mock_stream.side_effect = sd.PortAudioError("Device not found")

        recorder = AudioRecorder()

        with pytest.raises(RuntimeError) as exc_info:
            recorder.start(device=999)

        assert "Не удалось открыть устройство записи" in str(exc_info.value)
        assert recorder.recording is False

    @patch('app.audio.sd.RawInputStream')
    def test_start_monitoring_failure(self, mock_stream):
        """Неудачный старт мониторинга возвращает False."""
        import sounddevice as sd
        mock_stream.side_effect = sd.PortAudioError("Device not found")

        recorder = AudioRecorder()
        result = recorder.start_monitoring(device=999)

        assert result is False
        assert recorder.monitoring is False

    @patch("app.audio.sd.RawInputStream")
    def test_typed_stop_preserves_completed_microphone_track(
        self,
        mock_stream,
    ):
        recorder = AudioRecorder()
        recorder.start()

        result = recorder.stop_capture()

        assert result.status is AudioCaptureStatus.COMPLETED
        assert result.track is not None
        assert result.track.source is AudioSourceKind.MICROPHONE
        assert result.track.path.is_file()
        result.track.path.unlink()

    @patch("app.audio.sd.RawInputStream")
    def test_typed_stop_preserves_partial_track_after_device_disconnect(
        self,
        mock_stream,
    ):
        stream = MagicMock()
        stream.stop.side_effect = OSError("device disconnected")
        mock_stream.return_value = stream
        recorder = AudioRecorder()
        recorder.start()
        recorder._callback(
            np.array([100, -100], dtype=np.int16).tobytes(),
            2,
            None,
            None,
        )

        result = recorder.stop_capture()

        assert result.status is AudioCaptureStatus.INTERRUPTED
        assert result.track is not None
        assert result.track.path.is_file()
        assert "device disconnected" in (result.error or "")
        result.track.path.unlink()
