"""
Тесты для модуля записи аудио.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, Mock
import threading

import pytest
import numpy as np

# Мокируем sounddevice до импорта модуля
mock_sd = MagicMock()
mock_sd.PortAudioError = Exception
sys.modules['sounddevice'] = mock_sd

from app.audio import AudioRecorder, LevelCallback


@pytest.fixture
def audio_recorder():
    """Создать AudioRecorder для тестов."""
    return AudioRecorder()


@pytest.fixture
def mock_sounddevice():
    """Мок для sounddevice."""
    with patch('app.audio.sd') as sd_mock:
        sd_mock.PortAudioError = Exception
        yield sd_mock


class TestAudioRecorderInit:
    """Тесты для инициализации AudioRecorder."""

    def test_init_default_params(self):
        """Тест параметров по умолчанию."""
        recorder = AudioRecorder()
        assert recorder.samplerate == 16000
        assert recorder.channels == 1
        assert recorder.dtype == "int16"

    def test_init_custom_params(self):
        """Тест кастомных параметров."""
        recorder = AudioRecorder(samplerate=44100, channels=2)
        assert recorder.samplerate == 44100
        assert recorder.channels == 2

    def test_init_not_recording(self):
        """Тест что запись не активна после инициализации."""
        recorder = AudioRecorder()
        assert recorder.recording is False
        assert recorder.monitoring is False


class TestAudioRecorderListDevices:
    """Тесты для list_input_devices()."""

    def test_list_input_devices_returns_list(self, audio_recorder, mock_sounddevice):
        """Тест что метод возвращает список."""
        mock_sounddevice.query_devices.return_value = [
            {"name": "Microphone 1", "max_input_channels": 2},
            {"name": "Speakers", "max_input_channels": 0},
            {"name": "Microphone 2", "max_input_channels": 1},
        ]

        devices = audio_recorder.list_input_devices()

        assert isinstance(devices, list)
        assert len(devices) == 2  # Только устройства с input channels > 0

    def test_list_input_devices_format(self, audio_recorder, mock_sounddevice):
        """Тест формата вывода."""
        mock_sounddevice.query_devices.return_value = [
            {"name": "Test Mic", "max_input_channels": 2},
        ]

        devices = audio_recorder.list_input_devices()

        assert len(devices) == 1
        assert devices[0] == "0: Test Mic"

    def test_list_input_devices_empty(self, audio_recorder, mock_sounddevice):
        """Тест когда нет устройств ввода."""
        mock_sounddevice.query_devices.return_value = [
            {"name": "Speakers Only", "max_input_channels": 0},
        ]

        devices = audio_recorder.list_input_devices()

        assert devices == []


class TestAudioRecorderStartStop:
    """Тесты для start() и stop()."""

    def test_start_sets_recording_flag(self, audio_recorder, mock_sounddevice):
        """Тест что start устанавливает флаг записи."""
        mock_stream = MagicMock()
        mock_sounddevice.RawInputStream.return_value = mock_stream

        audio_recorder.start()

        assert audio_recorder.recording is True

    def test_start_creates_temp_file(self, audio_recorder, mock_sounddevice):
        """Тест создания временного файла."""
        mock_stream = MagicMock()
        mock_sounddevice.RawInputStream.return_value = mock_stream

        audio_recorder.start()

        assert audio_recorder._tmp_path is not None
        assert audio_recorder._tmp_path.suffix == ".wav"

    def test_start_twice_does_nothing(self, audio_recorder, mock_sounddevice):
        """Тест что повторный вызов start не создаёт новый поток."""
        mock_stream = MagicMock()
        mock_sounddevice.RawInputStream.return_value = mock_stream

        audio_recorder.start()
        first_path = audio_recorder._tmp_path

        audio_recorder.start()  # Второй вызов

        assert audio_recorder._tmp_path == first_path

    def test_stop_returns_path(self, audio_recorder, mock_sounddevice):
        """Тест что stop возвращает путь к файлу."""
        mock_stream = MagicMock()
        mock_sounddevice.RawInputStream.return_value = mock_stream

        audio_recorder.start()
        path = audio_recorder.stop()

        assert path is not None
        assert isinstance(path, Path)

    def test_stop_clears_recording_flag(self, audio_recorder, mock_sounddevice):
        """Тест что stop сбрасывает флаг записи."""
        mock_stream = MagicMock()
        mock_sounddevice.RawInputStream.return_value = mock_stream

        audio_recorder.start()
        audio_recorder.stop()

        assert audio_recorder.recording is False

    def test_stop_without_start_returns_none(self, audio_recorder):
        """Тест что stop без start возвращает None."""
        path = audio_recorder.stop()
        assert path is None

    def test_start_with_device(self, audio_recorder, mock_sounddevice):
        """Тест запуска с конкретным устройством."""
        mock_stream = MagicMock()
        mock_sounddevice.RawInputStream.return_value = mock_stream

        audio_recorder.start(device=1)

        mock_sounddevice.RawInputStream.assert_called_once()
        call_kwargs = mock_sounddevice.RawInputStream.call_args[1]
        assert call_kwargs['device'] == 1


class TestAudioRecorderLevelCallback:
    """Тесты для level callback."""

    def test_start_with_level_callback(self, audio_recorder, mock_sounddevice):
        """Тест запуска с callback для уровня."""
        mock_stream = MagicMock()
        mock_sounddevice.RawInputStream.return_value = mock_stream

        levels_received = []
        def callback(levels):
            levels_received.extend(levels)

        audio_recorder.start(level_callback=callback)

        assert audio_recorder._level_callback is not None

    def test_level_callback_clears_on_stop(self, audio_recorder, mock_sounddevice):
        """Тест очистки callback при остановке."""
        mock_stream = MagicMock()
        mock_sounddevice.RawInputStream.return_value = mock_stream

        audio_recorder.start(level_callback=lambda x: None)
        audio_recorder.stop()

        assert audio_recorder._level_callback is None


class TestAudioRecorderCallback:
    """Тесты для внутреннего callback обработки аудио."""

    def test_callback_puts_data_to_queue(self, audio_recorder, mock_sounddevice):
        """Тест что callback добавляет данные в очередь."""
        mock_stream = MagicMock()
        mock_sounddevice.RawInputStream.return_value = mock_stream

        audio_recorder.start()

        # Симулируем вызов callback
        test_data = np.array([100, 200, 300], dtype=np.int16).tobytes()
        audio_recorder._callback(test_data, 3, None, None)

        # Проверяем что данные в очереди
        assert not audio_recorder._queue.empty()
        data = audio_recorder._queue.get_nowait()
        assert data == test_data

    def test_callback_calculates_level(self, audio_recorder, mock_sounddevice):
        """Тест что callback вычисляет уровень громкости."""
        mock_stream = MagicMock()
        mock_sounddevice.RawInputStream.return_value = mock_stream

        levels_received = []
        def level_callback(levels):
            levels_received.append(levels.copy())

        audio_recorder.start(level_callback=level_callback)

        # Симулируем вызов callback с аудио данными
        # Создаём сигнал с известной амплитудой
        test_data = np.array([1000] * 1024, dtype=np.int16).tobytes()
        audio_recorder._callback(test_data, 1024, None, None)

        assert len(levels_received) > 0
        # Уровень должен быть между 0 и 1
        assert all(0 <= level <= 1 for level in levels_received[-1])


class TestAudioRecorderMonitoring:
    """Тесты для мониторинга микрофона."""

    def test_start_monitoring(self, audio_recorder, mock_sounddevice):
        """Тест запуска мониторинга."""
        mock_stream = MagicMock()
        mock_sounddevice.RawInputStream.return_value = mock_stream

        result = audio_recorder.start_monitoring()

        assert result is True
        assert audio_recorder.monitoring is True

    def test_stop_monitoring(self, audio_recorder, mock_sounddevice):
        """Тест остановки мониторинга."""
        mock_stream = MagicMock()
        mock_sounddevice.RawInputStream.return_value = mock_stream

        audio_recorder.start_monitoring()
        audio_recorder.stop_monitoring()

        assert audio_recorder.monitoring is False

    def test_monitoring_twice_returns_true(self, audio_recorder, mock_sounddevice):
        """Тест что повторный вызов start_monitoring возвращает True."""
        mock_stream = MagicMock()
        mock_sounddevice.RawInputStream.return_value = mock_stream

        audio_recorder.start_monitoring()
        result = audio_recorder.start_monitoring()

        assert result is True

    def test_stop_monitoring_when_not_monitoring(self, audio_recorder):
        """Тест stop_monitoring когда мониторинг не активен."""
        # Не должно вызывать исключений
        audio_recorder.stop_monitoring()
        assert audio_recorder.monitoring is False


class TestAudioRecorderProperties:
    """Тесты для свойств."""

    def test_recording_property_false(self, audio_recorder):
        """Тест свойства recording когда не записывается."""
        assert audio_recorder.recording is False

    def test_monitoring_property_false(self, audio_recorder):
        """Тест свойства monitoring когда не мониторится."""
        assert audio_recorder.monitoring is False


class TestAudioRecorderErrors:
    """Тесты для обработки ошибок."""

    def test_start_with_invalid_device(self, audio_recorder, mock_sounddevice):
        """Тест запуска с невалидным устройством."""
        # Используем Exception как PortAudioError
        mock_sounddevice.RawInputStream.side_effect = Exception("Invalid device")

        with pytest.raises(RuntimeError) as exc_info:
            audio_recorder.start(device=999)

        assert "Не удалось открыть устройство" in str(exc_info.value)

    def test_start_cleans_up_on_error(self, audio_recorder, mock_sounddevice):
        """Тест очистки ресурсов при ошибке."""
        mock_sounddevice.RawInputStream.side_effect = Exception("Device error")

        try:
            audio_recorder.start()
        except RuntimeError:
            pass

        assert audio_recorder._tmp_path is None
        assert audio_recorder.recording is False

