"""
Unit тесты для модуля overlay.py

Тестируем OverlayWidget без реального отображения окна.
"""

import math
import pytest
from unittest.mock import MagicMock, patch

from app.overlay import OverlayState, OverlayWidget


class TestOverlayState:
    """Тесты для enum OverlayState."""

    def test_all_states_defined(self):
        """Проверяем что все состояния определены."""
        assert OverlayState.HIDDEN is not None
        assert OverlayState.RECORDING is not None
        assert OverlayState.PROCESSING is not None
        assert OverlayState.SUCCESS is not None
        assert OverlayState.ERROR is not None

    def test_states_are_unique(self):
        """Все состояния уникальны."""
        states = [
            OverlayState.HIDDEN,
            OverlayState.RECORDING,
            OverlayState.PROCESSING,
            OverlayState.SUCCESS,
            OverlayState.ERROR,
        ]
        assert len(states) == len(set(states))


class TestOverlayWidgetPositions:
    """Тесты позиционирования overlay."""

    def test_valid_positions(self):
        """Проверяем список валидных позиций."""
        expected = [
            "bottom-right", "bottom-left",
            "top-right", "top-left",
            "bottom-center", "top-center"
        ]
        assert OverlayWidget.POSITIONS == expected


class TestOverlayWidgetSettings:
    """Тесты настроек overlay (без создания окна)."""

    @pytest.fixture
    def mock_qapp(self):
        """Мок для QApplication."""
        with patch('app.overlay.QApplication'):
            yield

    def test_set_corner_valid(self, mock_qapp):
        """set_corner с валидной позицией."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._corner = "bottom-right"
            widget.POSITIONS = OverlayWidget.POSITIONS
            widget._update_position = MagicMock()

            widget.set_corner("top-left")

            assert widget._corner == "top-left"
            widget._update_position.assert_called_once()

    def test_set_corner_invalid(self, mock_qapp):
        """set_corner с невалидной позицией не меняет значение."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._corner = "bottom-right"
            widget.POSITIONS = OverlayWidget.POSITIONS
            widget._update_position = MagicMock()

            widget.set_corner("invalid-position")

            assert widget._corner == "bottom-right"
            widget._update_position.assert_not_called()

    def test_set_margin_valid(self, mock_qapp):
        """set_margin с валидным значением."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._margin = 20
            widget._update_position = MagicMock()

            widget.set_margin(50)

            assert widget._margin == 50
            widget._update_position.assert_called_once()

    def test_set_margin_clamps_low(self, mock_qapp):
        """set_margin ограничивает минимальное значение."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._margin = 20
            widget._update_position = MagicMock()

            widget.set_margin(-10)

            assert widget._margin == 0

    def test_set_margin_clamps_high(self, mock_qapp):
        """set_margin ограничивает максимальное значение."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._margin = 20
            widget._update_position = MagicMock()

            widget.set_margin(500)

            assert widget._margin == 200

    def test_set_wave_gain_valid(self, mock_qapp):
        """set_wave_gain с валидным значением."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._gain = 3.0

            widget.set_wave_gain(5.0)

            assert widget._gain == 5.0

    def test_set_wave_gain_clamps_low(self, mock_qapp):
        """set_wave_gain ограничивает минимум."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._gain = 3.0

            widget.set_wave_gain(0.5)

            assert widget._gain == 1.0

    def test_set_wave_gain_clamps_high(self, mock_qapp):
        """set_wave_gain ограничивает максимум."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._gain = 3.0

            widget.set_wave_gain(20.0)

            assert widget._gain == 10.0

    def test_set_bg_opacity_valid(self, mock_qapp):
        """set_bg_opacity с валидным значением."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._bg_opacity = 255
            widget._update_bg_cache = MagicMock()
            widget.update = MagicMock()

            widget.set_bg_opacity(200)

            assert widget._bg_opacity == 200
            widget._update_bg_cache.assert_called_once()

    def test_set_bg_opacity_clamps(self, mock_qapp):
        """set_bg_opacity ограничивает диапазон [0, 255]."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._bg_opacity = 255
            widget._update_bg_cache = MagicMock()
            widget.update = MagicMock()

            widget.set_bg_opacity(-50)
            assert widget._bg_opacity == 0

            widget.set_bg_opacity(300)
            assert widget._bg_opacity == 255


class TestOverlayWidgetGetters:
    """Тесты геттеров."""

    def test_get_position(self):
        """get_position возвращает текущую позицию."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._corner = "top-center"

            assert widget.get_position() == "top-center"

    def test_get_margin(self):
        """get_margin возвращает текущий отступ."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._margin = 42

            assert widget.get_margin() == 42

    def test_get_wave_gain(self):
        """get_wave_gain возвращает текущее усиление."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._gain = 4.5

            assert widget.get_wave_gain() == 4.5

    def test_get_bg_opacity(self):
        """get_bg_opacity возвращает текущую прозрачность."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._bg_opacity = 180

            assert widget.get_bg_opacity() == 180


class TestOverlayWaveformUpdate:
    """Тесты обновления уровня звука."""

    def test_update_waveform_in_recording_state(self):
        """update_waveform обновляет уровень в состоянии RECORDING."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._state = OverlayState.RECORDING
            widget._target_level = 0.0
            widget._gain = 3.0

            widget.update_waveform([0.5])

            # sqrt(0.5) * 3.0 ≈ 2.12, clamped to 1.0
            assert widget._target_level == 1.0

    def test_update_waveform_not_in_recording_state(self):
        """update_waveform не делает ничего если не в RECORDING."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._state = OverlayState.PROCESSING
            widget._target_level = 0.0
            widget._gain = 3.0

            widget.update_waveform([0.5])

            assert widget._target_level == 0.0

    def test_update_waveform_empty_levels(self):
        """update_waveform с пустым списком устанавливает 0."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._state = OverlayState.RECORDING
            widget._target_level = 0.5
            widget._gain = 3.0

            widget.update_waveform([])

            # Устанавливается sqrt(0) * gain = 0
            assert widget._target_level == 0.0

    def test_update_waveform_takes_last_value(self):
        """update_waveform берёт последнее значение из списка."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._state = OverlayState.RECORDING
            widget._target_level = 0.0
            widget._gain = 1.0  # Без усиления для простоты

            widget.update_waveform([0.1, 0.2, 0.25])

            # sqrt(0.25) * 1.0 = 0.5
            assert widget._target_level == 0.5


class TestOverlayStateTransitions:
    """Тесты переходов между состояниями."""

    def test_show_recording_sets_state(self):
        """show_recording устанавливает RECORDING."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._state = OverlayState.HIDDEN
            widget._hide_timer = MagicMock()
            widget._update_position = MagicMock()
            widget._show_animated = MagicMock()
            widget._levels = []
            widget._target_levels = []

            widget.show_recording()

            assert widget._state == OverlayState.RECORDING
            widget._hide_timer.stop.assert_called_once()

    def test_show_processing_sets_state(self):
        """show_processing устанавливает PROCESSING."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._state = OverlayState.RECORDING
            widget._hide_timer = MagicMock()
            widget._base_flags = 0
            widget._pulse_phase = None
            widget.setWindowFlags = MagicMock()
            widget.setAttribute = MagicMock()
            widget.show = MagicMock()
            widget.update = MagicMock()

            widget.show_processing()

            assert widget._state == OverlayState.PROCESSING
            widget._hide_timer.stop.assert_called_once()

    def test_show_success_sets_state(self):
        """show_success устанавливает SUCCESS."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._state = OverlayState.PROCESSING
            widget._hide_timer = MagicMock()
            widget._flash_alpha = 0.0
            widget.update = MagicMock()

            widget.show_success(auto_hide_ms=1000)

            assert widget._state == OverlayState.SUCCESS
            widget._hide_timer.start.assert_called_once_with(1000)

    def test_show_success_no_auto_hide(self):
        """show_success с auto_hide_ms=0 не запускает таймер."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._state = OverlayState.PROCESSING
            widget._hide_timer = MagicMock()
            widget._flash_alpha = 0.0
            widget.update = MagicMock()

            widget.show_success(auto_hide_ms=0)

            widget._hide_timer.start.assert_not_called()

    def test_show_error_sets_state(self):
        """show_error устанавливает ERROR."""
        with patch.object(OverlayWidget, '__init__', lambda x, y=None: None):
            widget = OverlayWidget()
            widget._state = OverlayState.PROCESSING
            widget._hide_timer = MagicMock()
            widget._flash_alpha = 0.0
            widget.update = MagicMock()

            widget.show_error("Test error", auto_hide_ms=1200)

            assert widget._state == OverlayState.ERROR
            widget._hide_timer.start.assert_called_once_with(1200)

